"""Step 13 · Demand simulation at different prices for the 40 pilot SKUs

 13.1 Refresh         LightGBM refit on all data to 27 Sep 2026; level calibration from a model trained to 3 Aug 2026
                      and checked on the 8 weeks to 27 Sep (no look-ahead); P(sell) from the last 13 weeks
 13.2 Baseline        next 13 weeks (28 Sep - 27 Dec 2026) per store x SKU at the CURRENT price:
                      0.30 x ML (recursive; stock, discount, cost, margin, macro frozen at the forecast date)
                      + 0.70 x last-13-week average x seasonal path (2024 & 2025 analog years), x P(sell)
                      (locked config: analysis/pilot/baseline_config.json)
 13.3 Price grid      chain-wide change -15%..+15% (1% steps) applied to the SKU alone:
                      own units = baseline x (1 + d) ^ e, e = step 9 rise elasticity for d > 0, cut elasticity for d < 0
                      rivals in the SKU's substitute cluster: units x (1 + d) ^ cross-elasticity (step 9 fix 2)
                      range: e scaled by the 95% interval of the SKU's elasticity (low / likely / high response)
Outputs: clean/pilot/baseline_forecast.parquet, clean/pilot/simulation_grid.parquet, analysis/pilot/simulation.xlsx,
analysis/pilot/simulation/*.png
"""
import __main__
import json
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import pilot_train_eval as T
from build_weekly_model_set import calendar
from pilot_models import PRICE_FEATS, prepare

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "pilot", ROOT / "analysis" / "pilot"
FIG = OUT / "simulation"
FIG.mkdir(exist_ok=True)
ORIGIN, H = pd.Timestamp("2026-09-28"), 13
GRID = np.round(np.arange(-0.15, 0.1501, 0.01), 2)
CFG = json.load(open(OUT / "baseline_config.json"))
W_ML, W_AVG = CFG["weights"]["ML_LightGBM"], CFG["weights"]["Last13_Average"]
ANALOG_ORIGINS = [pd.Timestamp(d) for d in CFG["seasonal_path"]["analog_origins"]]   # 2024 and 2025, not 2023


def _analog_ratios(f, a, min_weeks=8):
    """store-SKU weekly units in horizon week h divided by the store-SKU's average over the 13 weeks before analog
    origin a; only store-SKUs selling in >= min_weeks of those 13 weeks (8 for the SKU paths: no launches or
    stock-gap bases; 1 for the locked chain path, which tested better on the Q4 2025 holdout)"""
    g = f[["Week", "Plant", "ArticleCode", "ln_Units"]].assign(U=np.exp(f.ln_Units))
    pre = g[(g.Week < a) & (g.Week >= a - pd.Timedelta(weeks=13))].groupby(["Plant", "ArticleCode"]).U.agg(["mean", "size"])
    pre = pre[pre["size"] >= min_weeks]["mean"].rename("pre")
    post = g[(g.Week >= a) & (g.Week < a + pd.Timedelta(weeks=H))].copy()
    post["h"] = (post.Week - a).dt.days // 7 + 1
    post = post.join(pre, on=["Plant", "ArticleCode"], how="inner")
    post["ratio"] = post.U / post.pre
    return post


def seasonal_path(f):
    """chain seasonal path: median store-SKU ratio per horizon week, averaged over the analog years"""
    paths = []
    for a in ANALOG_ORIGINS:
        post = _analog_ratios(f, a, min_weeks=1)
        paths.append(post.groupby("h").ratio.median().rename(str(a.year)))
    P = pd.concat(paths, axis=1)
    P["Path"] = P.mean(axis=1).clip(0.6, 2.5)
    return P


BLOCKS = {"Oct": range(1, 6), "Nov": range(6, 10), "Dec": range(10, 14)}


def sku_seasonal_path(f, P, min_stores=10, min_move=np.log(1.25)):
    """SKU seasonal path (fix 3). A SKU's deviation from the chain path is measured per period (Oct h1-5, Nov h6-9,
    Dec h10-13) in each analog year (log of the SKU's median store ratio over that year's chain path). The 2024 and
    2025 deviations do not repeat in general (correlation ~0 for Nov and Dec), so a SKU keeps its own deviation only
    where both years agree: same direction and each at least 25%; it then takes the smaller of the two. Otherwise,
    or with < min_stores qualifying stores in a year (launches, stock gaps), or when fewer than 70% of the stores
    selling it after the origin had a stable base before it (supply returning, not season), the SKU follows the
    chain path."""
    dev = {}
    for a in ANALOG_ORIGINS:
        post = _analog_ratios(f, a)
        n = post.groupby("ArticleCode").Plant.nunique()
        sold = f[(f.Week >= a) & (f.Week < a + pd.Timedelta(weeks=H))].groupby("ArticleCode").Plant.nunique()
        stable = (n / sold.reindex(n.index)) >= 0.7
        ok = n[(n >= min_stores) & stable].index
        sk = post[post.ArticleCode.isin(ok)].groupby(["ArticleCode", "h"]).ratio.median().unstack()
        d = np.log(sk.clip(lower=0.05)).sub(np.log(P[str(a.year)]), axis=1)
        dev[str(a.year)] = pd.DataFrame({k: d[[h for h in hs if h in d]].mean(axis=1) for k, hs in BLOCKS.items()})
    y0, y1 = [str(a.year) for a in ANALOG_ORIGINS]
    rows, ev = [], []
    for k in BLOCKS:
        x = pd.concat([dev[y0][k].rename(y0), dev[y1][k].rename(y1)], axis=1)
        both = x.dropna()
        ev.append({"Period": k, "SKUs_both_years": len(both), "Correlation_2024_vs_2025": both.corr().iloc[0, 1]})
        agree = (np.sign(x[y0]) == np.sign(x[y1])) & (x[y0].abs() >= min_move) & (x[y1].abs() >= min_move)
        use = np.where(agree, np.sign(x[y0]) * np.minimum(x[y0].abs(), x[y1].abs()), 0.0)
        rows.append(pd.DataFrame({"ArticleCode": x.index, "Period": k, f"Factor_{y0}": np.exp(x[y0]).values,
                                  f"Factor_{y1}": np.exp(x[y1]).values, "Agree": agree.values,
                                  "Factor_Used": np.exp(use)}))
    D = pd.concat(rows, ignore_index=True)
    S = pd.DataFrame(1.0, index=sorted(set(D.ArticleCode)), columns=P.index)
    for _, r in D[D.Agree].iterrows():
        S.loc[r.ArticleCode, list(BLOCKS[r.Period])] = r.Factor_Used
    S = S.mul(P.Path, axis=1).clip(0.5, 3.0)
    return S, D, pd.DataFrame(ev)


def tested_range(f):
    """price range the data has actually tested, per SKU (2024 onwards, clearance below cost excluded): the narrower of
    (a) 5th / 95th percentile of store-week price vs usual price and (b) of chain weekly real price vs its 26-week
    rolling median (unit-weighted). Floor 3%, ceiling 15%; SKUs at the elasticity limit or with Low confidence
    are capped at 10% (fix 2)"""
    d = f[(f.Week >= "2024-01-01") & (f.Price_KZ >= f.Unit_COGS_KZ / 1.5)].copy()
    d["w"] = np.exp(d.ln_Units)

    def wq(x, w, q):
        o = np.argsort(x)
        return float(np.interp(q, np.cumsum(w[o]) / w.sum(), x[o]))
    rows = {}
    for a, g in d.groupby("ArticleCode"):
        s = g.dropna(subset=["ln_Price_vs_Usual"])
        c = g.assign(x=g.ln_Price_Real * g.w).groupby("Week")[["x", "w"]].sum()
        c = (c.x / c.w)
        c = (c - c.rolling(26, min_periods=8).median()).dropna()
        rows[a] = {"Store_Low": wq(s.ln_Price_vs_Usual.values, s.w.values, .05),
                   "Store_High": wq(s.ln_Price_vs_Usual.values, s.w.values, .95),
                   "Chain_Low": c.quantile(.05), "Chain_High": c.quantile(.95)}
    r = np.expm1(pd.DataFrame(rows).T)
    r["Down_%"] = -np.minimum(-r.Store_Low, -r.Chain_Low).clip(0.03, 0.15) * 100
    r["Up_%"] = np.minimum(r.Store_High, r.Chain_High).clip(0.03, 0.15) * 100
    return r


def refit_ml(f, cols, mono, params):
    cal_start = ORIGIN - pd.Timedelta(weeks=8)
    m_cal = T.fit("LightGBM", params, f[f.Week < cal_start], cols, mono)
    cal = f[(f.Week >= cal_start) & (f.Week < ORIGIN)]
    d = pd.DataFrame({"a": cal.ArticleCode.values, "y": np.exp(cal.ln_Units.values), "p": m_cal.units(cal) / m_cal.smear})
    G = d.y.sum() / d.p.sum()
    g = d.groupby("a").agg(y=("y", "sum"), p=("p", "sum"), n=("y", "size"))
    r = (G + (g.y / g.p - G) * g.n / (g.n + 50)).clip(0.75 * G, 1.25 * G)
    m = T.fit("LightGBM", params, f[f.Week < ORIGIN], cols, mono)
    m.calib, m.calib_global = r.to_dict(), float(G)
    return m


def future_rows(f):
    """one row per active store-SKU per future week, at the current price and with the future calendar"""
    hist = f[f.Week < ORIGIN]
    active = hist[hist.Week >= ORIGIN - pd.Timedelta(weeks=13)][["Plant", "ArticleCode"]].drop_duplicates()
    last = hist.sort_values("Week").groupby(["Plant", "ArticleCode"]).tail(1).merge(active, on=["Plant", "ArticleCode"])
    weeks = pd.date_range(ORIGIN, periods=H, freq="7D")
    cal = calendar(pd.Series(weeks)).set_index("Week")
    t0 = f.Week.min()
    rows = []
    for wk in weeks:
        r = last.copy()
        c = cal.loc[wk]
        r["Week"] = wk
        r["Holidays_In_Week"], r["Payday_Week"] = c.Holidays_In_Week, int(c.Payday_Week)
        r["Christmas_Season"], r["December"] = int(c.Christmas_Season), int(c.Month_Of_Year == 12)
        r["Month_Sin"], r["Month_Cos"] = np.sin(2 * np.pi * c.Month_Of_Year / 12), np.cos(2 * np.pi * c.Month_Of_Year / 12)
        r["Week_Sin"], r["Week_Cos"] = np.sin(2 * np.pi * c.Week_Of_Year / 52), np.cos(2 * np.pi * c.Week_Of_Year / 52)
        r["Trend_Weeks"] = (wk - t0).days / 7
        r["dln_Price_1w"] = 0.0                        # price held at its current level
        rows.append(r)
    return pd.concat(rows, ignore_index=True)


def main():
    __main__.Fitted = T.Fitted
    f, _ = prepare()
    dec = json.load(open(OUT / "pca_decision.json"))
    lin_raw = [("ln_Days_Of_Cover_Filled" if c == "ln_Days_Of_Cover" else c) for c in dec["linear_features"]]
    f[lin_raw] = f[lin_raw].fillna(f[f.Split == "train"][lin_raw].median())
    f = T.add_relative(f)
    cols = T.swap_features(dec["tree_features"])
    mono = [-1 if c in PRICE_FEATS else 0 for c in cols]
    tune = pd.read_excel(OUT / "model_evaluation.xlsx", sheet_name="CV tuning (6 folds)")
    params = json.loads(tune[tune.Model == "LightGBM"].sort_values("CV_WAPE").iloc[0].Params)

    # 13.1 refresh + 13.2 baseline -----------------------------------------------------------------------------
    m = refit_ml(f, cols, mono, params)
    hist = f[f.Week < ORIGIN]
    fut = future_rows(f)
    ml = T.recursive(m, hist, fut, calibrate=True, freeze=True)
    hist_u = hist.assign(U=np.exp(hist.ln_Units))
    avg13 = hist_u.sort_values("Week").groupby(["Plant", "ArticleCode"]).tail(13).groupby(["Plant", "ArticleCode"]).U.mean()
    b1 = pd.MultiIndex.from_arrays([fut.Plant, fut.ArticleCode]).map(avg13).values
    wm = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=["Week", "Plant", "ArticleCode"])
    wm = wm[wm.ArticleCode.isin(f.ArticleCode.unique()) & (wm.Week < ORIGIN) & (wm.Week >= ORIGIN - pd.Timedelta(weeks=13))]
    psell = (wm.groupby(["Plant", "ArticleCode"]).Week.nunique() / 13).clip(upper=1)
    # supply at risk: sold in < 70% of its usual stores in the last 4 weeks (vs the 9 weeks before); for these the
    # share of weeks selling comes from the last 4 weeks only (stores not selling now drop out)
    last4 = wm[wm.Week >= ORIGIN - pd.Timedelta(weeks=4)]
    cover = last4.groupby("ArticleCode").Plant.nunique() /         wm[wm.Week < ORIGIN - pd.Timedelta(weeks=4)].groupby("ArticleCode").Plant.nunique()
    risk = cover[cover < 0.7]
    ps4 = (last4.groupby(["Plant", "ArticleCode"]).Week.nunique() / 4).clip(upper=1)
    psell = psell.to_frame("P").join(ps4.rename("P4"), how="left")
    on_risk = psell.index.get_level_values(1).isin(risk.index)
    psell = pd.Series(np.where(on_risk, psell.P4.fillna(0), psell.P), index=psell.index)
    supply = pd.DataFrame({"Store_Coverage_Last4w": cover, "Supply_At_Risk": cover < 0.7})
    supply.to_parquet(CL / "supply_risk.parquet")
    print("supply at risk:", {a.lstrip("0"): round(v, 2) for a, v in risk.items()}, flush=True)
    psell.rename("P_Sell").reset_index().to_parquet(CL / "p_sell.parquet", index=False)
    ps = pd.MultiIndex.from_arrays([fut.Plant, fut.ArticleCode]).map(psell).fillna(0.5).values
    ml = np.where(np.isnan(ml), b1, ml)
    P = seasonal_path(f)
    S, D, sev = sku_seasonal_path(f, P)
    print(sev.round(3).to_string(index=False), flush=True)
    print(D[D.Agree].round(2).to_string(index=False), flush=True)
    h = ((fut.Week - ORIGIN).dt.days // 7 + 1).values
    sp_chain = P.Path.reindex(h).fillna(1.0).values
    sp = pd.MultiIndex.from_arrays([fut.ArticleCode, h]).map(S.stack()).values.astype(float)
    sp = np.where(np.isnan(sp), sp_chain, sp)
    fut["ML_Units"], fut["Avg13_Units"], fut["Season_Factor"], fut["P_Sell"] = ml, b1, sp, ps
    fut["Baseline_Units"] = (W_ML * ml + W_AVG * b1 * sp) * ps
    base = fut[["Week", "Plant", "ArticleCode", "ArticleName", "SubGroup", "Pilot_Group", "ML_Units", "Avg13_Units",
                "Season_Factor", "P_Sell", "Baseline_Units", "Christmas_Season", "Payday_Week"]]
    base.to_parquet(CL / "baseline_forecast.parquet", index=False)
    print(f"baseline: {fut.Plant.nunique()} stores, {fut.ArticleCode.nunique()} SKUs, {H} weeks, "
          f"{base.Baseline_Units.sum():,.0f} units; calibration factor {m.calib_global:.3f}", flush=True)

    # current price and unit cost (sales-weighted, last 4 weeks)
    rec = f[(f.Week < ORIGIN) & (f.Week >= ORIGIN - pd.Timedelta(weeks=4))].copy()
    rec["U"] = np.exp(rec.ln_Units)
    g = rec.assign(R=rec.Price_KZ * rec.U, Cst=rec.Unit_COGS_KZ * rec.U).groupby("ArticleCode")
    cur = pd.DataFrame({"Current_Price_KZ": g.R.sum() / g.U.sum(), "Unit_Cost_KZ": g.Cst.sum() / g.U.sum()})

    # 13.3 price grid ---------------------------------------------------------------------------------------------
    e = pd.read_parquet(CL / "sku_elasticity.parquet").set_index("ArticleCode")
    x = pd.read_parquet(CL / "cross_elasticity.parquet")
    chain = base.groupby("ArticleCode").Baseline_Units.sum()
    weekly = base.groupby(["ArticleCode", "Week"]).Baseline_Units.sum().unstack()
    ratio_lo = (e.CI_Low / e.E_Shrunk).clip(lower=0.5, upper=2.0)              # stronger response
    ratio_hi = (e.CI_High / e.E_Shrunk).clip(lower=0.0, upper=1.0)             # weaker response (0 = none)
    rng = tested_range(f)
    limited = (e.Elasticity_Final.abs() >= 3.9) | (e.Rise_Final.abs() >= 4.9) | (e.Cut_Final.abs() >= 3.9) |         (e.Confidence_Final == "Low")
    rng["Limited_10%"] = limited.reindex(rng.index).fillna(False)
    rng.loc[rng["Limited_10%"], "Down_%"] = rng.loc[rng["Limited_10%"], "Down_%"].clip(lower=-10)
    rng.loc[rng["Limited_10%"], "Up_%"] = rng.loc[rng["Limited_10%"], "Up_%"].clip(upper=10)
    rows = []
    for a, r in e.iterrows():
        if a not in chain:
            continue
        B, P0 = chain[a], cur.Current_Price_KZ.get(a)
        rivals = x[((x.SKU_Price == a.lstrip("0")) | (x.SKU_Price == a)) & (x.Cross_Used > 0)]
        for d in GRID:
            el = r.Rise_Final if d > 0 else r.Cut_Final
            out = {"ArticleCode": a, "ArticleName": r.ArticleName, "Group": r.Group, "Price_Change_%": d * 100,
                   "Current_Price_KZ": P0, "New_Price_KZ": P0 * (1 + d),
                   "Unit_Cost_KZ": cur.Unit_Cost_KZ.get(a), "Elasticity_Used": el, "Baseline_Units_13w": B,
                   "Confidence": r.Confidence_Final}
            for lab, k in [("Likely", 1.0), ("Strong", ratio_lo.get(a, 1.0)), ("Weak", ratio_hi.get(a, 1.0))]:
                out[f"Units_{lab}"] = B * (1 + d) ** (el * k)
            # Low confidence: the strong case also covers the sub-group evidence (prior - 1 SD) and the SKU's own
            # unclipped 95% bound, since a weak own estimate may reflect prices that moved with the market
            if r.Confidence_Final == "Low":
                e_strong = max(min(el * ratio_lo.get(a, 1.0), r.Prior_Elasticity - r.Prior_SD,
                                   el * r.CI_Low / r.E_Shrunk if r.E_Shrunk < 0 else el), -5.0)
                out["Units_Strong"] = B * (1 + d) ** e_strong
                out["Elasticity_Strong"] = e_strong
            else:
                out["Elasticity_Strong"] = el * ratio_lo.get(a, 1.0)
            # fix 1: rival effect measured in value-equivalent units of this SKU (rival units x rival price / own
            # price, so a 20 L bidon or 25 kg sack counts by its size) and capped at 60% of the own change
            own = out["Units_Likely"] - B
            gains = {}
            for _, rv in rivals.iterrows():
                q = rv.SKU_Quantity if rv.SKU_Quantity in chain else rv.SKU_Quantity.zfill(18)
                if q in chain:
                    gains[q] = chain[q] * ((1 + d) ** rv.Cross_Used - 1)
            equiv = sum(g * cur.Current_Price_KZ.get(q) / P0 for q, g in gains.items())
            cap = 0.6 * abs(own)
            scale = min(1.0, cap / abs(equiv)) if equiv != 0 else 1.0
            out["Rival_Units_Change"] = sum(gains.values()) * scale
            out["Rival_Equiv_Units_Change"] = equiv * scale
            out["Rival_Revenue_Change_KZ"] = sum(g * cur.Current_Price_KZ.get(q) for q, g in gains.items()) * scale
            out["Rival_GP_Change_KZ"] = sum(g * (cur.Current_Price_KZ.get(q) - cur.Unit_Cost_KZ.get(q))
                                            for q, g in gains.items()) * scale
            out["Diversion_Capped"] = scale < 1.0
            out["Recapture_%"] = -equiv * scale / own * 100 if own != 0 else 0.0
            out["Supply_At_Risk"] = bool(supply.Supply_At_Risk.get(a, False))
            out["Tested_Down_%"], out["Tested_Up_%"] = rng.at[a, "Down_%"], rng.at[a, "Up_%"]
            out["Within_Tested_Range"] = rng.at[a, "Down_%"] - 1e-9 <= d * 100 <= rng.at[a, "Up_%"] + 1e-9
            rows.append(out)
    sim = pd.DataFrame(rows)
    sim["Units_Change_%"] = (sim.Units_Likely / sim.Baseline_Units_13w - 1) * 100
    sim.to_parquet(CL / "simulation_grid.parquet", index=False)

    view = sim[sim["Price_Change_%"].isin([-10, -5, 0, 5, 10])].pivot_table(
        index=["Group", "ArticleName", "Confidence"], columns="Price_Change_%", values="Units_Change_%").round(1)
    with pd.ExcelWriter(OUT / "simulation.xlsx") as xw:
        view.to_excel(xw, sheet_name="Units change summary")
        sim.round(3).to_excel(xw, sheet_name="Full price grid", index=False)
        weekly.round(1).to_excel(xw, sheet_name="Baseline by week (chain)")
        base.groupby(["Pilot_Group", "ArticleCode", "ArticleName"]).agg(
            Stores=("Plant", "nunique"), Baseline_13w=("Baseline_Units", "sum"), ML_13w=("ML_Units", "sum"),
            Avg13_13w=("Avg13_Units", "sum"), Mean_P_Sell=("P_Sell", "mean")).round(2).to_excel(xw, sheet_name="Baseline per SKU")
        cur.round(2).to_excel(xw, sheet_name="Current price & cost")
        P.round(3).to_excel(xw, sheet_name="Seasonal path")
        S.round(3).to_excel(xw, sheet_name="SKU seasonal path")
        D.round(3).to_excel(xw, sheet_name="SKU season 2024 vs 2025", index=False)
        sev.round(3).to_excel(xw, sheet_name="SKU season repeatability", index=False)
        rng.round(2).to_excel(xw, sheet_name="Tested price range")
        supply.round(2).to_excel(xw, sheet_name="Supply risk")
        pd.DataFrame({"Item": ["Forecast weeks", "Baseline", "Price effect", "Range", "Cross effects", "Calibration",
                           "Seasonality", "Tested price range"],
                      "Value": [f"{ORIGIN.date()} + {H} weeks", CFG["baseline"],
                                "step 9 rise elasticity for increases, cut elasticity for decreases",
                                "elasticity scaled by its 95% interval (strong / weak response); Low confidence: "
                                "strong case also covers sub-group prior - 1 SD",
                                "rivals in the substitute cluster, step 9 cross-elasticities; measured in value-"
                                "equivalent units, capped at 60% of the own change",
                                f"chain factor {m.calib_global:.3f} from the 8 weeks to {ORIGIN.date()}",
                                "chain path; SKU's own Oct/Nov/Dec factor only where 2024 and 2025 agree (same direction, "
                                ">= 25% each; smaller one used)",
                                "narrower of store and chain 5-95% price moves, 3-15%; 10% max at the elasticity "
                                "limit or Low confidence; outside = extrapolation, not used in step 15"]}).to_excel(
            xw, sheet_name="Method", index=False)

    # charts: demand curves for all 40 SKUs
    skus = sim.drop_duplicates("ArticleCode").sort_values(["Group", "ArticleName"])
    fig, axs = plt.subplots(5, 8, figsize=(20, 12), sharex=True)
    col = {"A": "#156082", "B": "#E97132", "C": "#196B24", "D": "#A02B93"}
    for ax, (_, s) in zip(axs.flat, skus.iterrows()):
        d = sim[sim.ArticleCode == s.ArticleCode]
        idx = lambda v: v / d.Baseline_Units_13w.iloc[0] * 100
        ax.fill_between(d["Price_Change_%"], idx(d.Units_Weak), idx(d.Units_Strong), color=col[s.Group], alpha=.18)
        ax.plot(d["Price_Change_%"], idx(d.Units_Likely), color=col[s.Group], lw=1, ls="--")
        dt = d[d.Within_Tested_Range]
        ax.plot(dt["Price_Change_%"], idx(dt.Units_Likely), color=col[s.Group], lw=2.2)
        ax.axhline(100, color="#7F8781", lw=.6)
        ax.axvline(0, color="#7F8781", lw=.6)
        ax.set_title(f"{s.Group} · {str(s.ArticleName).title()[:26]} ({s.Confidence[0]})"
                     + (" ⚠ supply" if s.Supply_At_Risk else ""), fontsize=7, color="#C00000" if s.Supply_At_Risk else "k")
        ax.tick_params(labelsize=6)
    fig.supxlabel("price change, %")
    fig.supylabel("units over 13 weeks, index (current price = 100); band = 95% elasticity range; dashed = untested")
    fig.tight_layout()
    fig.savefig(FIG / "13_demand_curves_40.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    wk = weekly.sum().rename("Baseline")
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(wk.index, wk.values / 1e3, marker="o", color="#156082")
    ax.set_ylabel("baseline units, thousand (40 SKUs, chain)")
    ax.set_title("Baseline forecast at current prices, 28 Sep - 27 Dec 2026")
    fig.savefig(FIG / "13_baseline_weekly.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(view.to_string(), flush=True)


if __name__ == "__main__":
    main()
