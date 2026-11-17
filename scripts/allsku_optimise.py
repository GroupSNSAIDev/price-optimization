"""All-SKU project, phases F + G: simulation, profit and price optimisation (chain level, 52 weeks), Max-profit guardrails.

F1  Supply at risk: stores selling in the last 4 weeks < 70% of the usual (weeks 5-26), or stock-out weeks >= 20% of
    store-weeks in the last 13 weeks (allsku_stockouts.py) -> no price cut.
F2  Price grid: -15% .. +15% in 1% steps, limited to each SKU's tested range (5-95% of its own past price moves vs the
    regular price, clipped to 3-15%; 10% max) and the 10% step limit. Units: own response (rise / cut elasticity) plus
    sales won from SubGroup rivals (diversion: share of the lost value that stays in the SubGroup, capped at 60%).
F3  Profit: NET of IVA price and unit cost of the last 4 regular-price weeks; GP over the 52-week baseline;
    likely / cautious / optimistic sensitivity.
F4  Cost pass-through scan: cost vs price change over 26 weeks, catch-up needed to get back to the SubGroup margin.
F5  Overstock and slow movers: weeks of stock > 26 and units falling > 25% -> markdown candidate, no rise.
G1  Guardrails (demo Max-profit plan): rise <= 8% (cut <= 10%), Low-confidence rise <= 5%, at most 60% of a
    SubGroup's SKUs raised at once, customer basket rise <= 1.8% (sales-weighted, ~3 months of CPI; a penalty on each
    SKU's sales-weighted rise, set by bisection), tested range, unit loss <= 10% class A / 15% others (cautious case
    for Low confidence), cautious GP of each SubGroup must not fall, no rise after a >= 15% rise in the last 26 weeks,
    no cut on supply risk, never below unit cost, Everyday KVIs held (the demo rule; "KVI unlocked" shown as a scenario),
    not on shelf -> hold, min gain (500k Kz per 13 weeks or 2% of the SKU's GP; loss-makers exempt), smallest move giving
    90% of the gain. Tier: thin tail (Low confidence, class C) -> rules only (cost pass-through to the SubGroup margin).
G2  Optimiser test: coordinate ascent with substitution (demo) vs MILP over the price grid (scipy HiGHS, own response,
    group cautious-GP constraint, price-order constraints); both scored on the full model.
G3  Volume vs GP frontier: unit-loss caps 5 / 10 / 15 / 20% for every SKU.
G4  Scenarios: likely / cautious / optimistic, cost drift (CPI 0.6% a month), FX +10% on imported costs, KVI unlocked.
G5  Timing: GP gain of the plan by start week (23 Nov, 30 Nov, 4 Jan, 1 Feb) over the first 13 weeks.
G6  Limits waterfall: the plan before the step-3 limits, then each limit added in turn (what each one costs).

Usage: python scripts/allsku_optimise.py [--forecast file.csv]   (CSV: SKU_Code, Week_Start, Units; chain level)
Outputs: clean/allsku/optimal_prices.parquet, clean/allsku/weekly_impact.parquet, analysis/allsku/optimisation.xlsx
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
FX = 1050.0
MAX_STEP, GRID = 0.10, np.round(np.arange(-0.15, 0.1501, 0.01), 2)
MAX_RISE, LOW_RISE, SUB_RISE_SHARE, BASKET_MAX = 0.08, 0.05, 0.60, 1.75   # basket target 1.75 leaves room for rounding (limit 1.8)
LAMBDA = 0.0                                                              # basket penalty, set in main()
VOL_CAP = {"A": 0.10, "B": 0.15, "C": 0.15}
MIN_GAIN_KZ_13W, MIN_GAIN_PCT, SMALLEST_MOVE = 500_000, 2.0, 0.90
REPRICED_PCT, SUPPLY_RISK, MAX_DIV, STOCKOUT_RISK = 15, 0.70, 0.60, 0.20
CPI_MONTHLY = 0.006
SCARCITY = set(json.loads((ROOT / "analysis" / "pilot" / "optimisation_config_sweetspot.json").read_text())["scarcity_skus"])


def inputs(forecast=None):
    sc = pd.read_parquet(CL / "scope.parquet").set_index("Code")
    el = pd.read_parquet(CL / "elasticity.parquet").set_index("Code")
    bl = pd.read_parquet(CL / "baseline_forecast.parquet")
    if forecast:
        up = pd.read_csv(forecast) if str(forecast).endswith(".csv") else pd.read_excel(forecast)
        up = up.rename(columns={"SKU_Code": "Code", "Week_Start": "Week", "Units": "Pred_up"})
        up["Code"] = up.Code.astype(str).str.lstrip("0")
        up["Week"] = pd.to_datetime(up.Week)
        bl = bl.merge(up[["Code", "Week", "Pred_up"]], on=["Code", "Week"], how="left")
        bl["Source"] = np.where(bl.Pred_up.notna(), "Uploaded", "Ours")
        bl["Pred"] = bl.Pred_up.fillna(bl.Pred)
        bl = bl.drop(columns="Pred_up")
    else:
        bl["Source"] = "Ours"
    cw = pd.read_parquet(CL / "chain_weekly.parquet")
    end = cw.Week.max()
    reg = cw[~cw.Markdown_Week & (cw.Units > 0)]
    l4 = reg[reg.Week > end - pd.Timedelta(weeks=4)].groupby("Code").agg(n=("Net_Sales_KZ", "sum"), k=("COGS_KZ", "sum"), u=("Units", "sum"),
                                                                          g=("Sales_KZ", "sum"))
    l8 = reg[reg.Week > end - pd.Timedelta(weeks=8)].groupby("Code").agg(n=("Net_Sales_KZ", "sum"), k=("COGS_KZ", "sum"), u=("Units", "sum"),
                                                                          g=("Sales_KZ", "sum"))
    l4 = l4.combine_first(l8)                                         # SKUs not sold in the last 4 weeks: last 8
    s = pd.DataFrame({"P": l4.n / l4.u, "C": l4.k / l4.u, "Gross_P": l4.g / l4.u})
    # F1 supply at risk
    st = cw.pivot_table(index="Code", columns="Week", values="Stores_Selling", aggfunc="sum")
    wk = sorted(cw.Week.unique())
    s["Stores_Selling_4w"] = st[wk[-4:]].median(axis=1)
    s["Stores_usual"] = st[wk[-26:-4]].median(axis=1)
    s["Supply_Risk_Stores"] = s.Stores_Selling_4w < SUPPLY_RISK * s.Stores_usual
    so = pd.read_parquet(CL / "stockout_chain.parquet")
    so = so[so.Week > end - pd.Timedelta(weeks=13)].groupby("Code").Gap_Stores.sum()
    sold13 = cw[cw.Week > end - pd.Timedelta(weeks=13)].groupby("Code").Stores_Selling.sum()
    s["Stockout_13w_%"] = (so.reindex(sold13.index).fillna(0) / (sold13 + so.reindex(sold13.index).fillna(0)).replace(0, np.nan) * 100)
    s["Supply_Risk"] = s.Supply_Risk_Stores | (s["Stockout_13w_%"].fillna(0) >= STOCKOUT_RISK * 100)
    # recent repricing (median regular price, last 4 weeks vs weeks 14-26)
    pr = reg.pivot_table(index="Code", columns="Week", values="Price_KZ", aggfunc="median")
    s["Repriced_26w_%"] = (pr[[w for w in wk[-4:] if w in pr]].median(axis=1) / pr[[w for w in wk[-26:-13] if w in pr]].median(axis=1) - 1) * 100
    # tested range: own past price moves vs the regular price, last 104 weeks
    h = cw[(cw.Week > end - pd.Timedelta(weeks=104)) & cw.Regular_Price_KZ.notna() & (cw.Units > 0)]
    dev = np.log(h.Price_KZ / h.Regular_Price_KZ)
    rng_ = dev.groupby(h.Code).quantile([0.05, 0.95]).unstack()
    s["Range_Up"] = (np.exp(rng_[0.95]) - 1).clip(0.03, 0.15)
    s["Range_Down"] = (1 - np.exp(rng_[0.05])).clip(0.03, 0.15)
    # F4 cost pass-through (26 weeks)
    p26 = reg[(reg.Week > end - pd.Timedelta(weeks=30)) & (reg.Week <= end - pd.Timedelta(weeks=26))].groupby("Code").agg(
        n=("Net_Sales_KZ", "sum"), k=("COGS_KZ", "sum"), u=("Units", "sum"))
    s["Cost_chg_26w_%"] = ((l4.k / l4.u) / (p26.k / p26.u) - 1) * 100
    s["Price_chg_26w_%"] = ((l4.n / l4.u) / (p26.n / p26.u) - 1) * 100
    # F5 overstock: stock on hand (latest month) vs weekly units, and trend
    stock = pd.read_parquet(ROOT / "clean" / "stock_monthly.parquet", columns=["Month", "ArticleCode", "Closing_Qty_Base"])
    stock = stock[stock.Month == stock.Month.max()]
    stock["Code"] = stock.ArticleCode.astype(str).str.lstrip("0")
    s["Stock"] = stock.groupby("Code").Closing_Qty_Base.sum()
    u13 = cw[cw.Week > end - pd.Timedelta(weeks=13)].groupby("Code").Units.mean()
    u13p = cw[(cw.Week > end - pd.Timedelta(weeks=26)) & (cw.Week <= end - pd.Timedelta(weeks=13))].groupby("Code").Units.mean()
    s["Weeks_Cover"] = s.Stock / u13
    s["Units_Trend_%"] = (u13 / u13p - 1) * 100
    s["Overstock"] = (s.Weeks_Cover > 26) & (s["Units_Trend_%"] < -25)
    d = sc.join(el[["Elasticity", "Rise", "Cut", "Cautious", "CI_High", "Diversion", "Confidence", "Own_Only_Final", "Group_Move_Final"]]).join(s)
    base = bl.groupby("Code").Pred.sum().rename("Base_52w")
    d = d.join(base)
    d["Base_52w"] = d.Base_52w.fillna(0)
    return d, bl


def valid(d):
    """SKUs the model can price: forecast, net price, cost and elasticities all present"""
    return (d.Base_52w > 0) & (d.P > 0) & (d.C > 0) & d[["Rise", "Cut", "Elasticity"]].notna().all(axis=1)


def allowed_moves(d, kvi_hold=True, vol_cap=None):
    """per SKU: allowed % changes and the reason when only 0 is allowed"""
    out, why = {}, {}
    sub_margin = d.groupby("SubGroup").apply(lambda g: ((g.P - g.C) * g.Base_52w).sum() / max((g.P * g.Base_52w).sum(), 1e-9))
    for code, r in d.iterrows():
        reason = ""
        if not r.in_scope:
            reason = "not on shelf / no stock"
        elif not (r.P > 0) or not (r.C > 0) or r.Base_52w <= 0:
            reason = "no price, cost or forecast"
        elif kvi_hold and r.Insight == "Everyday KVI":
            reason = "Everyday KVI: held (demo rule)"
        if reason:
            out[code], why[code] = [0.0], reason
            continue
        up = min(MAX_RISE, r.Range_Up if r.Range_Up == r.Range_Up else 0.05)
        dn = min(MAX_STEP, r.Range_Down if r.Range_Down == r.Range_Down else 0.05)
        if r.Confidence == "Low":
            up, dn = min(up, LOW_RISE), min(dn, 0.10)
        g = [x for x in GRID if -dn - 1e-9 <= x <= up + 1e-9]
        if r.Supply_Risk or r.Overstock:
            g = [x for x in g if x >= 0] if r.Supply_Risk else g
        if r.Overstock:
            g = [x for x in g if x <= 0]
        if r["Repriced_26w_%"] >= REPRICED_PCT:
            g = [x for x in g if x <= 0]
        g = [x for x in g if r.P * (1 + x) >= r.C or x >= 0]                    # never cut below unit cost
        # thin tail: rules only (cost pass-through back toward the SubGroup margin)
        if r.Confidence == "Low" and r.ABC == "C":
            target = sub_margin.get(r.SubGroup, 0.12)
            need = r.C / (1 - target) / r.P - 1
            rise_ok = any(x > 0 for x in g)                                # rise bans above (recent rise, overstock) still hold
            cu = float(np.clip(np.round(need, 2), 0, up)) if (rise_ok and r["Cost_chg_26w_%"] > r["Price_chg_26w_%"] + 2 and need > 0.01) else 0.0
            g = sorted({0.0, cu})
            why[code] = "tail: cost pass-through rule"
        out[code] = g if g else [0.0]
    return out, why


class Group:
    """one SubGroup, numpy evaluation of own response + diversion to rivals"""

    def __init__(self, d):
        self.codes = list(d.index)
        self.B, self.P, self.C = d.Base_52w.to_numpy(float), d.P.to_numpy(float), d.C.to_numpy(float)
        self.eR, self.eC = d.Rise.to_numpy(float), d.Cut.to_numpy(float)
        k = (d.Cautious / d.Elasticity).clip(1, 2).fillna(1.5).to_numpy(float)
        self.eRs, self.eCs = np.minimum(self.eR * k, -0.2), np.minimum(self.eC * k, -0.1)
        self.eRo, self.eCo = self.eR * 0.67, self.eC * 0.67                 # optimistic: customers react a third less
        self.div = d.Diversion.fillna(0).clip(0, MAX_DIV).to_numpy(float)
        rev = self.B * self.P
        self.share = rev / rev.sum() if rev.sum() > 0 else np.zeros(len(rev))
        self.GP0 = self.B * (self.P - self.C)
        self.W = d.Revenue_USD.fillna(0).to_numpy(float) * FX               # basket weight (sales, as in the rules check)

    def units(self, dd, case="L"):
        eR, eC = {"L": (self.eR, self.eC), "S": (self.eRs, self.eCs), "O": (self.eRo, self.eCo)}[case]
        own = self.B * np.where(dd > 0, (1 + dd) ** eR, (1 + dd) ** eC)
        if len(dd) < 2:
            return own
        # value of sales a SKU loses (+) or wins (-) that stays in the SubGroup, shared out to the other members
        # in proportion to their sales: gain_j = sum over i != j of lost_i * share_j / (1 - share_i)
        lost = (self.B - own) * self.P * self.div
        a = lost / np.maximum(1 - self.share, 1e-9)
        gain_val = self.share * (a.sum() - a)
        return own + gain_val / (self.P * (1 + dd))

    def gp(self, dd, case="L"):
        u = self.units(dd, case)
        return u * (self.P * (1 + dd) - self.C), u


def rise_limit(m):
    return m if SUB_RISE_SHARE >= 1 else max(1, int(SUB_RISE_SHARE * m))


def feasible(G, dd, caps, low):
    if (dd > 0).sum() > rise_limit(len(dd)):
        return False
    u_l = G.units(dd, "L")
    loss = u_l / np.maximum(G.B, 1e-9) - 1
    if np.any((dd > 0) & (loss < -caps - 1e-9)):
        return False
    u_s = G.units(dd, "S")
    if np.any((dd > 0) & low & (u_s / np.maximum(G.B, 1e-9) - 1 < -caps - 1e-9)):
        return False
    if (dd != 0).any():
        gs, _ = G.gp(dd, "S")
        if gs.sum() < G.GP0.sum() - 1e-6:
            return False
    return True


def coord_ascent(G, allowed, caps, low, rounds=6):
    dd = np.zeros(len(G.codes))
    for _ in range(rounds):
        changed = False
        for i, c in enumerate(G.codes):
            best, bd = None, dd[i]
            for x in allowed[c]:
                t = dd.copy(); t[i] = x
                if not feasible(G, t, caps, low):
                    continue
                v = G.gp(t)[0].sum() - LAMBDA * (G.W * t).sum()
                if best is None or v > best + 1e-6:
                    best, bd = v, x
            if bd != dd[i]:
                dd[i], changed = bd, True
        if not changed:
            break
    return dd


def solve_milp(G, allowed, caps, low):
    """one grid point per SKU, own response only; group cautious GP >= now; price order kept for close substitutes"""
    var, idx = [], []
    for i, c in enumerate(G.codes):
        for x in allowed[c]:
            t = np.zeros(len(G.codes)); t[i] = x
            u_l = G.B[i] * ((1 + x) ** (G.eR[i] if x > 0 else G.eC[i]))
            u_s = G.B[i] * ((1 + x) ** (G.eRs[i] if x > 0 else G.eCs[i]))
            if x > 0 and (u_l / G.B[i] - 1 < -caps[i] or (low[i] and u_s / G.B[i] - 1 < -caps[i])):
                continue
            var.append((i, x, u_l * (G.P[i] * (1 + x) - G.C[i]), u_s * (G.P[i] * (1 + x) - G.C[i]) - G.GP0[i]))
    n, m = len(var), len(G.codes)
    if n == 0:
        return np.zeros(m)
    c = -np.array([v[2] - LAMBDA * G.W[v[0]] * v[1] for v in var])
    A1 = np.zeros((m, n))
    for j, v in enumerate(var):
        A1[v[0], j] = 1
    cons = [LinearConstraint(A1, 1, 1), LinearConstraint(np.array([[v[3] for v in var]]), 0, np.inf)]
    if rise_limit(m) < m:                                                 # at most 60% of the SubGroup raised
        cons.append(LinearConstraint(np.array([[1.0 if v[1] > 0 else 0.0 for v in var]]), 0, rise_limit(m)))
    # price order: pairs within 10% of each other keep their order
    P = G.P
    order = np.argsort(P)
    rows = []
    for a, b in zip(order[:-1], order[1:]):
        if P[b] / P[a] - 1 < 0.10:
            row = np.zeros(n)
            for j, v in enumerate(var):
                if v[0] == b:
                    row[j] += P[b] * (1 + v[1])
                if v[0] == a:
                    row[j] -= P[a] * (1 + v[1])
            rows.append(row)
    if rows:
        cons.append(LinearConstraint(np.array(rows), 0, np.inf))
    r = milp(c, constraints=cons, integrality=np.ones(n), bounds=Bounds(0, 1), options={"time_limit": 30})
    dd = np.zeros(m)
    if r.x is None:
        return dd
    for j, v in enumerate(var):
        if r.x[j] > 0.5:
            dd[v[0]] = v[1]
    return dd


def run_plan(d, allowed, caps_by_code, method="coord"):
    res = []
    t = time.time()
    for sg, g in d[valid(d)].groupby("SubGroup"):
        G = Group(g)
        caps = np.array([caps_by_code[c] for c in G.codes])
        low = (g.Confidence == "Low").to_numpy()
        dd = coord_ascent(G, allowed, caps, low) if method == "coord" else solve_milp(G, allowed, caps, low)
        if method != "coord" and not feasible(G, dd, caps, low):
            dd = coord_ascent(G, allowed, caps, low)
        res.append(pd.Series(dd, index=G.codes))
    return pd.concat(res), time.time() - t


def finalise(d, dd, allowed, caps_by_code):
    """min gain and smallest move giving 90% of the SKU's gain (others held at their optimum)"""
    dd = dd.copy()
    for sg, g in d[valid(d)].groupby("SubGroup"):
        G = Group(g)
        caps = np.array([caps_by_code[c] for c in G.codes])
        low = (g.Confidence == "Low").to_numpy()
        v = dd.reindex(G.codes).fillna(0).to_numpy()
        for i, c in enumerate(G.codes):
            if v[i] == 0:
                continue
            t0 = v.copy(); t0[i] = 0
            g_opt, g_0 = G.gp(v)[0].sum(), G.gp(t0)[0].sum()
            gain = g_opt - g_0
            loss_maker = G.P[i] < G.C[i]
            if not loss_maker and (gain < MIN_GAIN_KZ_13W * 4 and gain < MIN_GAIN_PCT / 100 * max(G.GP0[i], 0)):
                if feasible(G, t0, caps, low):
                    v = t0
                    continue
            for x in sorted(allowed[c], key=abs):
                if abs(x) >= abs(v[i]) or np.sign(x) != np.sign(v[i]):
                    continue
                t = v.copy(); t[i] = x
                if feasible(G, t, caps, low) and G.gp(t)[0].sum() - g_0 >= SMALLEST_MOVE * gain:
                    v = t
                    break
        dd.loc[G.codes] = v
    return dd


def evaluate(d, dd, bl):
    """per SKU totals for likely / cautious / optimistic and the weekly impact table"""
    rows, wk = [], []
    for sg, g in d[valid(d)].groupby("SubGroup"):
        G = Group(g)
        v = dd.reindex(G.codes).fillna(0).to_numpy()
        r = pd.DataFrame(index=G.codes)
        r["Change"] = v
        r["Units_now"], r["GP_now"] = G.B, G.GP0
        r["Rev_now"] = G.B * G.P
        for case in "LSO":
            gp, u = G.gp(v, case)
            r[f"Units_{case}"], r[f"GP_{case}"], r[f"Rev_{case}"] = u, gp, u * G.P * (1 + v)
        rows.append(r)
    res = pd.concat(rows)
    w = bl.merge(res[["Units_now", "Units_L", "Units_S", "Units_O"]], left_on="Code", right_index=True)
    for case in "LSO":
        w[f"Units_new_{case}"] = w.Pred * w[f"Units_{case}"] / w.Units_now.replace(0, np.nan)
    w = w.join(d[["P", "C"]], on="Code").join(dd.rename("Change"), on="Code")
    w["Units_now_w"] = w.Pred
    w["Rev_now_KZ"], w["GP_now_KZ"] = w.Pred * w.P, w.Pred * (w.P - w.C)
    for case in "LSO":
        w[f"Rev_new_{case}_KZ"] = w[f"Units_new_{case}"] * w.P * (1 + w.Change)
        w[f"GP_new_{case}_KZ"] = w[f"Units_new_{case}"] * (w.P * (1 + w.Change) - w.C)
    keep = ["Code", "Week", "h", "Source", "Units_now_w", "Units_new_L", "Units_new_S", "Units_new_O", "Rev_now_KZ", "Rev_new_L_KZ",
            "Rev_new_S_KZ", "Rev_new_O_KZ", "GP_now_KZ", "GP_new_L_KZ", "GP_new_S_KZ", "GP_new_O_KZ"]
    return res, w[keep].rename(columns={"Units_now_w": "Units_now"})


def basket(d, dd):
    w = d.Revenue_USD.fillna(0)
    return float((dd.reindex(d.index).fillna(0) * w).sum() / w.sum() * 100)


def plan(d, allowed, caps, method="milp"):
    x, _ = run_plan(d, allowed, caps, method)
    return finalise(d, x, allowed, caps)


def set_basket_penalty(d, allowed, caps):
    """smallest penalty that keeps the finalised plan's basket rise within BASKET_MAX (bisection)"""
    global LAMBDA
    LAMBDA = 0.0
    b = basket(d, plan(d, allowed, caps))
    if b <= BASKET_MAX:
        return 0.0, b
    lo, hi = 0.0, 0.5
    for _ in range(8):
        LAMBDA = (lo + hi) / 2
        b = basket(d, plan(d, allowed, caps))
        lo, hi = (LAMBDA, hi) if b > BASKET_MAX else (lo, LAMBDA)
    LAMBDA = hi
    return hi, basket(d, plan(d, allowed, caps))


def waterfall(d, caps, bl, lam):
    """G6: plan before the step-3 limits, then each limit added in turn"""
    global MAX_RISE, LOW_RISE, SUB_RISE_SHARE, LAMBDA
    final = (MAX_RISE, LOW_RISE, SUB_RISE_SHARE, LAMBDA)
    steps = [("Before the step-3 limits (rise <= 10%, Low confidence <= 10%)", 0.10, 0.10, 1.0, 0.0),
             ("+ biggest rise 8%", 0.08, 0.10, 1.0, 0.0),
             ("+ Low-confidence rise <= 5%", 0.08, 0.05, 1.0, 0.0),
             ("+ at most 60% of a SubGroup raised", 0.08, 0.05, 0.60, 0.0),
             (f"+ basket rise <= 1.8% (penalty {lam:.3f})", 0.08, 0.05, 0.60, lam)]
    rows = []
    for name, MAX_RISE, LOW_RISE, SUB_RISE_SHARE, LAMBDA in steps:
        al, _ = allowed_moves(d)
        x = plan(d, al, caps)
        rows.append({"Step": name, **totals(evaluate(d, x, bl)[0]), "Basket_%": basket(d, x),
                     "Rises_7pct_plus": int((x >= 0.07 - 1e-9).sum())})
    MAX_RISE, LOW_RISE, SUB_RISE_SHARE, LAMBDA = final
    return pd.DataFrame(rows)


def totals(res):
    t = res.sum()
    return {"GP_now_$": t.GP_now / FX, "GP_gain_likely_$": (t.GP_L - t.GP_now) / FX, "GP_gain_cautious_$": (t.GP_S - t.GP_now) / FX,
            "GP_gain_optimistic_$": (t.GP_O - t.GP_now) / FX, "Units_%": (t.Units_L / t.Units_now - 1) * 100,
            "Revenue_%": (t.Rev_L / t.Rev_now - 1) * 100, "Raise": int((res.Change > 0).sum()), "Cut": int((res.Change < 0).sum()),
            "Hold": int((res.Change == 0).sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forecast", default=None)
    a = ap.parse_args()
    t0 = time.time()
    d, bl = inputs(a.forecast)
    caps = {c: (0.15 if c in SCARCITY else VOL_CAP.get(r.ABC, 0.15)) for c, r in d.iterrows()}
    allowed, why = allowed_moves(d)
    lam, b_lam = set_basket_penalty(d, allowed, caps)
    print(f"basket penalty {lam:.4f} -> basket {b_lam:.2f}%", flush=True)

    # ---- G2 optimiser test
    dd_c, sec_c = run_plan(d, allowed, caps, "coord")
    dd_m, sec_m = run_plan(d, allowed, caps, "milp")
    res_c, _ = evaluate(d, dd_c, bl)
    res_m, _ = evaluate(d, dd_m, bl)
    def order_breaks(dd):
        n = 0
        for sg, g in d[valid(d)].groupby("SubGroup"):
            p = g.P.to_numpy(); q = p * (1 + dd.reindex(g.index).fillna(0).to_numpy())
            o = np.argsort(p)
            n += int(sum((p[b] / p[a] - 1 < 0.10) and q[b] < q[a] for a, b in zip(o[:-1], o[1:])))
        return n
    g2 = pd.DataFrame([{"Optimiser": "Coordinate ascent (demo, with substitution)", **totals(res_c), "Order_breaks": order_breaks(dd_c), "Seconds": round(sec_c)},
                       {"Optimiser": "MILP over price grid (HiGHS)", **totals(res_m), "Order_breaks": order_breaks(dd_m), "Seconds": round(sec_m)}])
    pick = 0 if g2.loc[0, "GP_gain_likely_$"] - g2.loc[1, "GP_gain_likely_$"] > -0.01 * abs(g2.loc[1, "GP_gain_likely_$"]) and g2.loc[0, "Order_breaks"] <= g2.loc[1, "Order_breaks"] else 1
    dd = dd_c if pick == 0 else dd_m
    print(g2.round(1).to_string(index=False), "\nchosen:", g2.Optimiser[pick], flush=True)
    dd = finalise(d, dd, allowed, caps)
    res, weekly = evaluate(d, dd, bl)

    # ---- G3 frontier
    front = []
    for cap in (0.05, 0.10, 0.15, 0.20):
        cc = {c: cap for c in d.index}
        x, _ = run_plan(d, allowed, cc, "coord" if pick == 0 else "milp")
        front.append({"Unit_loss_cap_%": cap * 100, **totals(evaluate(d, x, bl)[0])})
    front = pd.DataFrame(front)

    # ---- G4 scenarios
    sc_rows = [{"Scenario": "Plan, likely", **totals(res)}]
    t = res.sum()
    sc_rows.append({"Scenario": "Plan, cautious (customers react 1.5x)", "GP_gain_likely_$": (t.GP_S - t.GP_now) / FX})
    sc_rows.append({"Scenario": "Plan, optimistic (react 0.67x)", "GP_gain_likely_$": (t.GP_O - t.GP_now) / FX})
    imp = pd.read_parquet(ROOT / "checkpoints" / "dim_article_master.parquet", columns=["ArticalCode", "PurchaseType"])
    imp["c"] = imp.ArticalCode.astype(str).str.lstrip("0")
    imported = d.index.isin(imp[imp.PurchaseType == "Import"].c)
    for name, mult in [("Cost drift: CPI 0.6% a month (avg over the year), prices as planned", np.full(len(d), 1 + CPI_MONTHLY * 6)),
                       ("FX +10% on imported costs, prices as planned", np.where(imported, 1.10, 1.0))]:
        d2 = d.copy(); d2["C"] = d.C * mult
        r2, _ = evaluate(d2, dd, bl)
        tt = r2.sum()
        sc_rows.append({"Scenario": name, "GP_now_$": tt.GP_now / FX, "GP_gain_likely_$": (tt.GP_L - tt.GP_now) / FX})
    al_kvi, _ = allowed_moves(d, kvi_hold=False)
    x, _ = run_plan(d, al_kvi, caps, "coord" if pick == 0 else "milp")
    sc_rows.append({"Scenario": "KVI unlocked (Everyday KVIs optimised too)", **totals(evaluate(d, finalise(d, x, al_kvi, caps), bl)[0])})
    scen = pd.DataFrame(sc_rows)

    # ---- G5 timing
    tim = []
    for start in ["2026-11-23", "2026-11-30", "2027-01-04", "2027-02-01"]:
        s0 = pd.Timestamp(start)
        ww = weekly[(weekly.Week >= s0) & (weekly.Week < s0 + pd.Timedelta(weeks=13))]
        tim.append({"Start": start, "GP_gain_13w_$": (ww.GP_new_L_KZ.sum() - ww.GP_now_KZ.sum()) / FX,
                    "GP_gain_13w_cautious_$": (ww.GP_new_S_KZ.sum() - ww.GP_now_KZ.sum()) / FX,
                    "Units_13w_%": (ww.Units_new_L.sum() / ww.Units_now.sum() - 1) * 100})
    tim = pd.DataFrame(tim)

    # ---- G6 limits waterfall
    wf = waterfall(d, caps, bl, lam)
    print(wf.round(2).to_string(index=False), flush=True)

    # ---- outputs
    out = d.join(res).join(pd.Series(why, name="Hold_Reason"))
    out["Change_%"] = out.Change.fillna(0) * 100
    out["Units_chg_%"] = (out.Units_L / out.Units_now - 1) * 100
    out["GP_gain_52w_$"] = (out.GP_L - out.GP_now) / FX
    out["GP_gain_52w_cautious_$"] = (out.GP_S - out.GP_now) / FX
    out["Margin_now_%"] = (out.P - out.C) / out.P * 100
    out["Margin_new_%"] = (out.P * (1 + out.Change.fillna(0)) - out.C) / (out.P * (1 + out.Change.fillna(0))) * 100
    out["Catch_up_needed_%"] = (out.C / (1 - out.SubGroup.map(out.groupby("SubGroup").apply(lambda g: np.nanmedian(g["Margin_now_%"])) / 100)) / out.P - 1) * 100
    out.index.name = "Code"
    out.reset_index().to_parquet(CL / "optimal_prices.parquet", index=False)
    weekly.to_parquet(CL / "weekly_impact.parquet", index=False)
    T = totals(res)
    grp = lambda col: out[out.Base_52w > 0].groupby(col).agg(SKUs=("Name", "size"), Raise=("Change_%", lambda x: int((x > 0).sum())),
                                                            Cut=("Change_%", lambda x: int((x < 0).sum())), Avg_change=("Change_%", lambda x: x[x != 0].mean()),
                                                            GP_gain_52w=("GP_gain_52w_$", "sum"), GP_gain_cautious=("GP_gain_52w_cautious_$", "sum"))
    holds = out[out["Change_%"].eq(0)].Hold_Reason.fillna("optimiser: no gainful feasible move").value_counts()
    with pd.ExcelWriter(OUT / "optimisation.xlsx") as xw:
        pd.DataFrame({"Item": list(T.keys()) + ["Optimiser", "Forecast source", "Run time (min)"],
                      "Value": [round(v, 1) if isinstance(v, float) else v for v in T.values()] + [g2.Optimiser[pick],
                                "uploaded file" if a.forecast else "our baseline", round((time.time() - t0) / 60, 1)]}).to_excel(xw, sheet_name="Summary", index=False)
        g2.round(1).to_excel(xw, sheet_name="G2 optimiser test", index=False)
        for col in ["Segment", "Insight", "ABC", "MainGroup", "Confidence"]:
            grp(col).round(1).to_excel(xw, sheet_name=f"By {col}")
        holds.to_frame("SKUs").to_excel(xw, sheet_name="Hold reasons")
        front.round(1).to_excel(xw, sheet_name="G3 frontier", index=False)
        scen.round(1).to_excel(xw, sheet_name="G4 scenarios", index=False)
        tim.round(1).to_excel(xw, sheet_name="G5 timing", index=False)
        wf.round(2).to_excel(xw, sheet_name="G6 limits waterfall", index=False)
        out[out.Overstock.fillna(False)].reset_index()[["Code", "Name", "Weeks_Cover", "Units_Trend_%", "Margin_now_%"]].to_excel(xw, sheet_name="F5 overstock", index=False)
        out[(out["Cost_chg_26w_%"] - out["Price_chg_26w_%"] > 3) & out.in_scope].reset_index()[[
            "Code", "Name", "SubGroup", "Cost_chg_26w_%", "Price_chg_26w_%", "Margin_now_%", "Catch_up_needed_%", "Change_%"]].round(1).to_excel(xw, sheet_name="F4 pass-through", index=False)
        out.reset_index().round(3).to_excel(xw, sheet_name="SKUs", index=False)
    pd.set_option("display.width", 220)
    print(pd.Series(T).round(1).to_string()); print(grp("Segment").round(1).to_string()); print(grp("Insight").round(1).to_string())
    print(holds.to_string()); print(front.round(1).to_string(index=False)); print(scen.round(1).to_string(index=False)); print(tim.round(1).to_string(index=False))
    print(f"{(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
