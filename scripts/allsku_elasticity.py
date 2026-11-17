"""All-SKU project, phase D: price sensitivity for every ACTIVE SKU (demo steps 8-9 at scale + Conzmo additions).

Data: store x SKU x week (clean/allsku/model_weekly.parquet), Jan 2024 - week of 2 Nov 2026, model-sample rows,
HRCA out; clearance (below cost), markdown (8% below regular), transition (week of + after a price step) and stock-out
edge weeks (ran out / refilled mid-week, allsku_stockouts.py) left out; full stock-out weeks have no sales row.
Relative price = SKU real price vs its SubGroup price index in the same store-week (leave-one-out).

D1  Statistical tests per SKU, 3 log-log specifications:
      S1 store FE + controls (season sin/cos, Christmas, payday, holidays, trend), store-clustered SE
      S2 store FE + week FE (two-way), store-clustered SE
      S3 chain weekly series (units per selling store), HAC SE
    plus the demo's level regression (elasticity at the means), for reporting.
D2  DerSimonian-Laird combination of S1-S3 (disagreement widens the interval).
D3  Pooling candidates: none / SubGroup / behaviour cluster / hierarchical (SKU -> SubGroup -> MainGroup);
    chosen on the back-test D7.
D4  Rise vs cut: price above / below the store-SKU usual level (Wald test of equality); rise calibrated with the SKU's
    own price-rise events, capped at 1.5x the overall value and at -5.
D5  Own vs SubGroup move: ln units on own-vs-group price and on the group price index -> own-only elasticity and
    whole-group elasticity; diversion (share of lost sales kept inside the SubGroup) capped at 60%.
D6  Bounds (overall -4..-0.2, rise -5..-0.2, cut -4..-0.1), confidence High / Medium / Low;
    Low -> cautious value = prior - 1 SD.
D7  Back-test: estimated on data before 11 May 2026, scored on the lasting price steps after it
    (4 weeks after vs 4 before, vs the rest of the SubGroup); MAE of the log response, sign hit rate, 80% coverage.
D8  Store clusters (store class A / B / C / P, wholesale HDDS): pooled elasticity per cluster and MainGroup.
D9  Over time: pooled elasticity per MainGroup, Jan 2024 - Jun 2025 vs Jul 2025 - Nov 2026.

Outputs: clean/allsku/elasticity.parquet, analysis/allsku/elasticity.xlsx
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
HOLD_START = pd.Timestamp("2026-05-11")
CONTROLS = ["Week_Sin", "Week_Cos", "Christmas_Season", "Payday_Week", "Holidays_In_Week", "Trend_Weeks"]
BOUNDS = {"overall": (-4.0, -0.2), "rise": (-5.0, -0.2), "cut": (-4.0, -0.1)}
SE_FLOOR, MIN_ROWS, MIN_SD = 0.10, 60, 0.015
RISE_CAP_MULT, MAX_DIVERSION = 1.5, 0.6
SEED = 2026


# ---------------------------------------------------------------- estimation helpers
def demean(v, g, n):
    return v - (np.bincount(g, v, n) / np.bincount(g, minlength=n))[g]


def demean2(v, g1, g2, n1, n2, iters=25):
    v = v - v.mean()
    for _ in range(iters):
        v = demean(v, g1, n1)
        v = demean(v, g2, n2)
    return v


def ols_cluster(X, y, g):
    """OLS on already-demeaned data, SE clustered by g (store); returns beta, se"""
    XtX = X.T @ X
    try:
        inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        return np.full(X.shape[1], np.nan), np.full(X.shape[1], np.nan)
    b = inv @ X.T @ y
    e = y - X @ b
    G = g.max() + 1
    S = np.zeros((G, X.shape[1]))
    np.add.at(S, g, X * e[:, None])
    meat = S.T @ S
    n, k = X.shape
    adj = G / max(G - 1, 1) * (n - 1) / max(n - k, 1)
    V = inv @ meat @ inv * adj
    return b, np.sqrt(np.clip(np.diag(V), 0, None))


def ols_hac(X, y, lags=4):
    XtX = X.T @ X
    inv = np.linalg.inv(XtX)
    b = inv @ X.T @ y
    e = y - X @ b
    u = X * e[:, None]
    S = u.T @ u
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = u[l:].T @ u[:-l]
        S += w * (G + G.T)
    V = inv @ S @ inv
    return b, np.sqrt(np.clip(np.diag(V), 0, None))


def estimate(code, d):
    """all specifications for one SKU on its store-week rows"""
    out = {"Code": code, "Rows": len(d), "Stores": d.Plant.nunique(), "Weeks": d.Week.nunique()}
    if len(d) < MIN_ROWS or d.Plant.nunique() < 1:
        return out
    gs = d.Plant.astype("category").cat.codes.to_numpy()
    gw = d.Week.astype("category").cat.codes.to_numpy()
    ns, nw = gs.max() + 1, gw.max() + 1
    y = d.ln_Qty.to_numpy()
    x = d.ln_Relative_Price.to_numpy()
    xd = demean(x, gs, ns)
    out["Price_SD"] = float(np.sqrt((xd ** 2).mean()))
    if out["Price_SD"] < MIN_SD:
        return out
    C = np.column_stack([demean(d[c].to_numpy(float), gs, ns) for c in CONTROLS])
    keep = C.std(axis=0) > 1e-9
    C = C[:, keep]
    yd = demean(y, gs, ns)
    # S1 store FE + controls
    b, se = ols_cluster(np.column_stack([xd, C]), yd, gs)
    out["S1"], out["S1_SE"] = b[0], se[0]
    # S2 two-way
    x2, y2 = demean2(x, gs, gw, ns, nw), demean2(y, gs, gw, ns, nw)
    b, se = ols_cluster(x2[:, None], y2, gs)
    out["S2"], out["S2_SE"] = b[0], se[0]
    # S3 chain weekly series
    wk = d.assign(wx=d.Sales_KZ * d.ln_Relative_Price).groupby("Week").agg(
        U=("Qty_Clean", "sum"), N=("Plant", "nunique"), W=("wx", "sum"), S=("Sales_KZ", "sum"),
        **{c: (c, "first") for c in CONTROLS})
    wk = wk[(wk.N >= 3) & (wk.U > 0)]
    if len(wk) >= 40:
        Xc = np.column_stack([np.ones(len(wk)), wk.W / wk.S, wk[CONTROLS].to_numpy(float)])
        Xc = Xc[:, np.r_[True, True, wk[CONTROLS].std().to_numpy() > 1e-9]]
        try:
            b, se = ols_hac(Xc, np.log(wk.U / wk.N).to_numpy())
            out["S3"], out["S3_SE"] = b[1], se[1]
        except np.linalg.LinAlgError:
            pass
    # level regression (demo 9.1/9.2), elasticity at the means
    P = np.exp(d.ln_Price_Real.to_numpy())
    b, se = ols_cluster(np.column_stack([demean(P, gs, ns), C]), demean(d.Qty_Clean.to_numpy(float), gs, ns), gs)
    scale = P.mean() / max(d.Qty_Clean.mean(), 1e-9)
    out["Level"], out["Level_SE"] = b[0] * scale, se[0] * scale
    # D4 rise vs cut (price above / below the store-SKU usual level)
    dev = xd
    up, dn = np.clip(dev, 0, None), np.clip(dev, None, 0)
    if (up > 0.01).sum() >= 10 and (dn < -0.01).sum() >= 10:
        b, se = ols_cluster(np.column_stack([up, dn, C]), yd, gs)
        out["Rise_Reg"], out["Rise_Reg_SE"], out["Cut_Reg"], out["Cut_Reg_SE"] = b[0], se[0], b[1], se[1]
        z_ = (b[0] - b[1]) / np.sqrt(se[0] ** 2 + se[1] ** 2) if se[0] > 0 and se[1] > 0 else np.nan
        out["Asym_p"] = 2 * (1 - stats.norm.cdf(abs(z_))) if z_ == z_ else np.nan
    # D5 own vs SubGroup move: own-vs-group price and group index
    gi = demean(d.ln_Cat_Index.to_numpy(), gs, ns)
    if np.sqrt((gi ** 2).mean()) > MIN_SD:
        b, se = ols_cluster(np.column_stack([xd, gi, C]), yd, gs)
        # ln q = b0 (own vs group) + b1 (group level): a whole-group move leaves the relative price unchanged -> effect b1
        out["Own_Only"], out["Own_Only_SE"], out["Group_Move"], out["Group_Move_SE"] = b[0], se[0], b[1], se[1]
    return out


def dersimonian_laird(est, se):
    est, se = np.asarray(est, float), np.maximum(np.asarray(se, float), SE_FLOOR)
    ok = ~np.isnan(est) & ~np.isnan(se)
    est, se = est[ok], se[ok]
    if not len(est):
        return np.nan, np.nan, 0.0
    w = 1 / se ** 2
    fixed = (w * est).sum() / w.sum()
    q = (w * (est - fixed) ** 2).sum()
    tau2 = max(0.0, (q - (len(est) - 1)) / (w.sum() - (w ** 2).sum() / w.sum())) if len(est) > 1 else 0.0
    ws = 1 / (se ** 2 + tau2)
    return (ws * est).sum() / ws.sum(), np.sqrt(1 / ws.sum()), tau2


def load(scope):
    cols = ["Week", "Plant", "Code", "Qty_Clean", "Sales_KZ", "ln_Qty", "ln_Relative_Price", "ln_Price_Real", "Category_Price_Index",
            "In_Model_Sample", "Below_Cost_Week", "Holidays_In_Week", "Payday_Week", "Christmas_Season", "Week_Of_Year",
            "Store_Class", "Channel", "CPI_Deflator"]
    d = pd.read_parquet(CL / "model_weekly.parquet", columns=cols)
    cw = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Markdown_Week", "Transition_Week"])
    d = d.merge(cw, on=["Code", "Week"], how="left")
    # store-weeks that ran out or were refilled mid-week (allsku_stockouts.py): units there are supply, not demand
    so = pd.read_parquet(CL / "stockout_weeks.parquet", columns=["Plant", "Code", "Week", "Flag"])
    so = so[so.Flag == "edge"].drop(columns="Flag").assign(Stockout_Edge=1)
    d = d.merge(so, on=["Plant", "Code", "Week"], how="left")
    d = d[d.In_Model_Sample & ~d.Below_Cost_Week.fillna(False) & ~d.Markdown_Week.fillna(False) & ~d.Transition_Week.fillna(False)
          & d.Stockout_Edge.isna()]
    d = d[np.isfinite(d.ln_Qty) & np.isfinite(d.ln_Relative_Price) & d.Code.isin(scope)]
    d["Week_Sin"], d["Week_Cos"] = np.sin(2 * np.pi * d.Week_Of_Year / 52), np.cos(2 * np.pi * d.Week_Of_Year / 52)
    d["Trend_Weeks"] = (d.Week - d.Week.min()).dt.days / 7
    d["ln_Cat_Index"] = np.log(d.Category_Price_Index.clip(lower=1e-6) / d.CPI_Deflator)     # real SubGroup price level
    for c in ["Christmas_Season", "Payday_Week"]:
        d[c] = d[c].astype(float)
    return d


def run(d):
    groups = list(d.groupby("Code", sort=False))
    res = Parallel(n_jobs=8, batch_size=32, backend="threading")(delayed(estimate)(c, g) for c, g in groups)
    return pd.DataFrame(res).set_index("Code")


def combine(r):
    cmb = r.apply(lambda s: pd.Series(dersimonian_laird([s.get("S1"), s.get("S2"), s.get("S3")],
                                                        [s.get("S1_SE"), s.get("S2_SE"), s.get("S3_SE")]),
                                      index=["Combined", "Combined_SE", "Tau2"]), axis=1)
    return r.join(cmb)


def eb(est, se, prior, tau):
    w = tau ** 2 / (tau ** 2 + se ** 2)
    return w * est + (1 - w) * prior, np.sqrt(w) * se, w


def group_prior(r, key):
    ok = r.Combined.notna()
    t = r[ok].assign(k=key[ok], w=1 / r.Combined_SE[ok].clip(lower=SE_FLOOR) ** 2, e=r.Combined[ok].clip(-6, 2))
    mean = t.groupby("k").apply(lambda g: np.average(g.e, weights=g.w))
    tau = t.groupby("k").apply(lambda g: np.sqrt(max(np.var(g.e) - np.mean(g.Combined_SE.clip(lower=SE_FLOOR) ** 2), 0.05)))
    n = t.groupby("k").size()
    return mean, tau, n


def pooled(r, sc, clusters):
    """D3 candidates: dict name -> (estimate, se) per SKU"""
    out = {"No pooling": (r.Combined.clip(-6, 2), r.Combined_SE)}
    over = np.average(r.Combined.dropna().clip(-6, 2), weights=1 / r.Combined_SE.dropna().clip(lower=SE_FLOOR) ** 2)
    for name, key in [("SubGroup", sc.SubGroup.reindex(r.index)), ("Behaviour cluster", clusters.reindex(r.index))]:
        m, t, n = group_prior(r, key)
        prior = key.map(m).fillna(over)
        tau = key.map(t).fillna(0.5)
        e, s, _ = eb(r.Combined.clip(-6, 2), r.Combined_SE.clip(lower=SE_FLOOR), prior, tau)
        out[name] = (e.fillna(prior), s.fillna(tau))
    # hierarchical: SubGroup means shrunk to MainGroup, then SKUs to the shrunk SubGroup
    sub, main = sc.SubGroup.reindex(r.index), sc.MainGroup.reindex(r.index)
    ms, ts, ns = group_prior(r, sub)
    mm, tm, nm = group_prior(r, main)
    sub_main = sc.groupby("SubGroup").MainGroup.agg(lambda x: x.mode()[0])
    sub_se = ts / np.sqrt(ns)
    mp = sub_main.reindex(ms.index).map(mm).fillna(over)
    mt = sub_main.reindex(ms.index).map(tm).fillna(0.5)
    ms_shr, _, _ = eb(ms, sub_se, mp, mt)
    prior = sub.map(ms_shr).fillna(main.map(mm)).fillna(over)
    tau = sub.map(ts).fillna(main.map(tm)).fillna(0.5)
    e, s, _ = eb(r.Combined.clip(-6, 2), r.Combined_SE.clip(lower=SE_FLOOR), prior, tau)
    out["Hierarchical"] = (e.fillna(prior), s.fillna(tau))
    return out


def events(cw, start, sc):
    """lasting chain price steps in the hold-out, 4 weeks after vs 4 before, relative to the rest of the SubGroup"""
    cw = cw.sort_values(["Code", "Week"]).copy()
    cw["SubGroup"] = cw.Code.map(sc.SubGroup)
    cat = cw.groupby(["SubGroup", "Week"]).Units.sum().rename("CatU")
    cw = cw.join(cat, on=["SubGroup", "Week"])
    cw["Other"] = cw.CatU - cw.Units
    rows = []
    rng = np.random.default_rng(SEED)
    for code, g in cw.groupby("Code"):
        g = g.reset_index(drop=True)
        steps = list(g.index[(g.Price_Step) & (g.Week >= start)])
        calm = [i for i in g.index[(~g.Price_Step) & (g.Week >= start)] if not g.Price_Step.iloc[max(0, i - 4):i + 4].any()]
        placebo = list(rng.choice(calm, min(2, len(calm)), replace=False)) if calm else []
        for i in steps + placebo:
            if i < 4 or i + 4 > len(g):
                continue
            pre, post = g.iloc[i - 4:i], g.iloc[i:i + 4]
            if (pre.Markdown_Week | pre.Spike_Week).any() or (post.Markdown_Week | post.Spike_Week).any():
                continue
            if pre.Units.sum() <= 0 or post.Units.sum() <= 0 or pre.Other.sum() <= 0 or post.Other.sum() <= 0:
                continue
            resp = np.log(post.Units.sum() / pre.Units.sum()) - np.log(post.Other.sum() / pre.Other.sum())
            step = np.log(post.Price_KZ.mean() / pre.Price_KZ.mean())
            is_step = i in steps
            if is_step and abs(step) < 0.03:
                continue
            rows.append({"Code": code, "Week": g.Week[i], "Step_ln": step, "Response_ln": resp, "Placebo": not is_step})
    return pd.DataFrame(rows)


def score(ev, est, se):
    """price-step events: calibration slope of actual on predicted response (1 = right size), binned check,
    and 80% coverage of a predictive range that includes normal 4-week noise (measured on placebo weeks)"""
    noise = ev[ev.Placebo].Response_ln.std()
    ev = ev[~ev.Placebo]
    e = ev.Code.map(est)
    s = ev.Code.map(se)
    ok = e.notna()
    pred = (e[ok] * ev.Step_ln[ok]).to_numpy()
    act = ev.Response_ln[ok].to_numpy()
    psd = np.sqrt((s[ok].to_numpy() * ev.Step_ln[ok].to_numpy()) ** 2 + noise ** 2)
    slope = float((pred * act).sum() / (pred * pred).sum())
    slope_se = float(np.sqrt(((act - slope * pred) ** 2).sum() / max(len(act) - 1, 1) / (pred * pred).sum()))
    # zero model (no price effect) for reference
    mae0 = float(np.abs(act).mean())
    q = pd.qcut(pred, 4, labels=False, duplicates="drop")
    bins = pd.DataFrame({"q": q, "p": pred, "a": act}).groupby("q").mean()
    return {"Events": int(ok.sum()), "MAE_log": float(np.abs(act - pred).mean()), "MAE_no_effect": mae0,
            "Calib_slope": slope, "Slope_SE": slope_se,
            "Sign_hit_%": float((np.sign(act) == np.sign(pred)).mean() * 100),
            "Corr": float(np.corrcoef(act, pred)[0, 1]) if ok.sum() > 2 else np.nan,
            "Coverage_80_%": float((np.abs(act - pred) <= 1.28 * psd).mean() * 100),
            "Noise_SD_4wk": float(noise),
            "Q1_pred/actual": f"{bins.p.iloc[0]:.3f}/{bins.a.iloc[0]:.3f}", "Q4_pred/actual": f"{bins.p.iloc[-1]:.3f}/{bins.a.iloc[-1]:.3f}"}


def behaviour_clusters(bh):
    cols = ["tickets_per_store_wk", "reach_pct", "wow_change_pct", "dec_vs_octnov_pct", "Margin_Pct"]
    x = bh[cols].copy()
    x["tickets_per_store_wk"] = np.log1p(x.tickets_per_store_wk)
    x = x.clip(x.quantile(0.02), x.quantile(0.98), axis=1).fillna(x.median())
    labels = kmeans(StandardScaler().fit_transform(x), 8)      # sklearn.cluster is blocked by Windows Application Control here
    return pd.Series(labels, index=bh.index).map(lambda k: f"B{k + 1}")


def kmeans(X, k, n_init=10, iters=100):
    rng = np.random.default_rng(SEED)
    best, best_inertia = None, np.inf
    for _ in range(n_init):
        c = X[rng.choice(len(X), 1)]
        for _ in range(k - 1):                                   # k-means++ start
            d2 = ((X[:, None, :] - c[None]) ** 2).sum(-1).min(1)
            c = np.vstack([c, X[rng.choice(len(X), 1, p=d2 / d2.sum())]])
        for _ in range(iters):
            lab = ((X[:, None, :] - c[None]) ** 2).sum(-1).argmin(1)
            new = np.array([X[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
            if np.allclose(new, c):
                break
            c = new
        inertia = ((X - c[lab]) ** 2).sum()
        if inertia < best_inertia:
            best, best_inertia = lab, inertia
    return best


def pooled_slope(d, by):
    """pooled two-way elasticity (SKU-store FE + week FE) per group"""
    res = []
    for k, g in d.groupby(by):
        if len(g) < 2000:
            continue
        gs = (g.Code + "|" + g.Plant).astype("category").cat.codes.to_numpy()
        gw = g.Week.astype("category").cat.codes.to_numpy()
        x = demean2(g.ln_Relative_Price.to_numpy(), gs, gw, gs.max() + 1, gw.max() + 1)
        y = demean2(g.ln_Qty.to_numpy(), gs, gw, gs.max() + 1, gw.max() + 1)
        b, se = ols_cluster(x[:, None], y, g.Plant.astype("category").cat.codes.to_numpy())
        res.append(dict(zip(by if isinstance(by, list) else [by], k if isinstance(k, tuple) else [k]), Elasticity=b[0], SE=se[0], Rows=len(g)))
    return pd.DataFrame(res)


def recency_shift(d, sc):
    """D9: per MainGroup, pooled elasticity of the most recent 16 months minus the whole period, kept only when the
    two halves differ significantly (p < 5%) and the shift is material (> 0.2); half of it applied (shrunk)"""
    d = d.assign(MainGroup=d.Code.map(sc.MainGroup))
    mid = d.Week.min() + (d.Week.max() - d.Week.min()) / 2
    a = pooled_slope(d[d.Week < mid], "MainGroup").set_index("MainGroup")
    b = pooled_slope(d[d.Week >= mid], "MainGroup").set_index("MainGroup")
    j = a.join(b, lsuffix="_old", rsuffix="_new").dropna()
    z_ = (j.Elasticity_new - j.Elasticity_old) / np.sqrt(j.SE_old ** 2 + j.SE_new ** 2)
    ok = (2 * (1 - stats.norm.cdf(z_.abs())) < 0.05) & ((j.Elasticity_new - j.Elasticity_old).abs() > 0.2) & (j.Elasticity_new < 0) & (j.Elasticity_old < 0)
    return (0.5 * (j.Elasticity_new - j.Elasticity_old)).where(ok).dropna()


def main():
    sc = pd.read_parquet(CL / "scope.parquet").set_index("Code")
    bh = pd.read_parquet(CL / "sku_behaviour.parquet").set_index("Code")
    d = load(set(sc.index))
    print(f"panel {len(d):,} rows, {d.Code.nunique():,} SKUs", flush=True)

    # ---- D7 back-test: estimate on data before the hold-out, score on hold-out price steps
    r_bt = combine(run(d[d.Week < HOLD_START]))
    clusters = behaviour_clusters(bh)
    cand_bt = pooled(r_bt, sc, clusters)
    shift_bt = recency_shift(d[d.Week < HOLD_START], sc)
    e_h, s_h = cand_bt["Hierarchical"]
    cand_bt["Hierarchical + recent-period shift"] = (e_h + sc.MainGroup.reindex(e_h.index).map(shift_bt).fillna(0), s_h)
    cw = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Units", "Price_KZ", "Price_Step", "Markdown_Week", "Spike_Week"])
    ev = events(cw, HOLD_START, sc)
    bt = pd.DataFrame({k: score(ev, e, s) for k, (e, s) in cand_bt.items()}).T
    p1 = pd.read_parquet(ROOT / "analysis" / "article_elasticity.parquet", columns=["ArticleCode", "Elasticity"])
    p1.index = p1.ArticleCode.astype(str).str.lstrip("0")
    bt.loc["Phase 1 estimate (reference)"] = score(ev, p1.Elasticity, pd.Series(0.3, index=p1.index))
    bt["Rank"] = bt.MAE_log.astype(float).rank() + (bt.Calib_slope.astype(float) - 1).abs().rank()
    choice = bt.drop(index="Phase 1 estimate (reference)").Rank.idxmin()
    print(bt.round(3).to_string(), "\nchosen:", choice, flush=True)

    # ---- full-data estimation
    r = combine(run(d))
    cand = pooled(r, sc, clusters)
    shift = recency_shift(d, sc)
    e_h, s_h = cand["Hierarchical"]
    cand["Hierarchical + recent-period shift"] = (e_h + sc.MainGroup.reindex(e_h.index).map(shift).fillna(0), s_h)
    r["Pooled"], r["Pooled_SE"] = cand[choice]
    for k, (e, s) in cand.items():
        r[f"Cand_{k.replace(' ', '_')}"] = e
    r = r.reindex(sc.index)
    # SKUs with no own estimate: pooled prior only
    r["Measured"] = r.Combined.notna()

    # ---- D4 rise / cut with own events (whole history) and caps
    ev_all = events(cw, cw.Week.min(), sc)
    ev_all["arc"] = ev_all.Response_ln / ev_all.Step_ln
    up = ev_all[ev_all.Step_ln > 0].groupby("Code").arc.agg(["median", "size"]).rename(columns={"median": "Rise_Events", "size": "Rise_Events_N"})
    r = r.join(up)
    re_se = r.Rise_Reg_SE.clip(lower=SE_FLOOR)
    ev_se = (1.2 / np.sqrt(r.Rise_Events_N)).clip(lower=0.3)
    w1, w2 = 1 / re_se ** 2, 1 / ev_se ** 2
    rise_raw = np.where(r.Rise_Reg.notna() & r.Rise_Events.notna(), (w1 * r.Rise_Reg + w2 * r.Rise_Events.clip(-6, 2)) / (w1 + w2),
                        np.where(r.Rise_Reg.notna(), r.Rise_Reg, r.Rise_Events.clip(-6, 2)))
    rise = pd.Series(rise_raw, index=r.index)
    rise_shr = 0.5 * rise + 0.5 * r.Pooled                                     # toward the SKU's own final value
    r["Elasticity"] = r.Pooled.clip(*BOUNDS["overall"])
    r["Rise"] = rise_shr.fillna(r.Pooled).clip(lower=np.maximum(RISE_CAP_MULT * r.Elasticity, -5), upper=BOUNDS["rise"][1]).clip(*BOUNDS["rise"])
    cut = 0.5 * r.Cut_Reg.clip(-6, 2) + 0.5 * r.Pooled
    r["Cut"] = cut.fillna(r.Pooled).clip(*BOUNDS["cut"])
    r["Cut_Reliable"] = r.Cut_Reg.notna() & (r.Cut_Reg < 0) & (r.Cut_Reg_SE < 1)
    r.loc[~r.Cut_Reliable, "Cut"] = np.maximum(r.Cut, r.Elasticity * 0.8)        # conservative: cuts win back less

    # ---- D5 own vs SubGroup move, diversion
    r["Own_Only_Final"] = (0.5 * r.Own_Only.clip(-6, 2) + 0.5 * r.Elasticity).fillna(r.Elasticity).clip(*BOUNDS["overall"])
    r["Group_Move_Final"] = (0.5 * r.Group_Move.clip(-6, 2) + 0.5 * r.Elasticity).fillna(r.Elasticity).clip(-4, -0.05)
    r["Group_Move_Final"] = np.maximum(r.Group_Move_Final, r.Own_Only_Final)   # moving the whole group never loses more
    r["Diversion"] = (1 - r.Group_Move_Final / r.Own_Only_Final).clip(0, MAX_DIVERSION)

    # ---- D6 confidence and cautious value
    spec = r[["S1", "S2", "S3"]]
    agree = (np.sign(spec) == -1).sum(axis=1)
    ci_w = 2 * 1.96 * r.Pooled_SE
    steps = cw[cw.Price_Step].groupby("Code").size().reindex(r.index).fillna(0)
    r["Price_Steps"] = steps
    r["Confidence"] = np.select([r.Measured & (agree >= 3) & (ci_w < 1.2) & (steps >= 6),
                                 r.Measured & (agree >= 2) & (ci_w < 2.0) & (steps >= 2)], ["High", "Medium"], "Low")
    prior_sd = r.Pooled_SE.fillna(0.5)
    r["Cautious"] = np.where(r.Confidence == "Low", np.minimum(r.Elasticity, r.Pooled - prior_sd), r.Elasticity * 1.5).clip(-5, -0.2)
    r["CI_Low"], r["CI_High"] = r.Pooled - 1.96 * r.Pooled_SE, r.Pooled + 1.96 * r.Pooled_SE
    r["Behaviour_Cluster"] = clusters.reindex(r.index)

    # ---- D8 store clusters, D9 over time (pooled, by MainGroup)
    d["MainGroup"] = d.Code.map(sc.MainGroup)
    d["Store_Cluster"] = np.where(d.Channel == "HDDS", "Wholesale (HDDS)", "Class " + d.Store_Class.astype(str))
    st = pooled_slope(d, ["MainGroup", "Store_Cluster"])
    st_all = pooled_slope(d.assign(All="All"), ["All", "Store_Cluster"])
    d["Period"] = np.where(d.Week < "2025-07-01", "Jan 2024 - Jun 2025", "Jul 2025 - Nov 2026")
    tm = pooled_slope(d, ["MainGroup", "Period"])
    tm_all = pooled_slope(d.assign(All="All"), ["All", "Period"])
    tmw = tm.pivot(index="MainGroup", columns="Period", values=["Elasticity", "SE"])
    tmw.columns = [f"{a} {b}" for a, b in tmw.columns]
    a, b = "Jan 2024 - Jun 2025", "Jul 2025 - Nov 2026"
    tmw["Change"] = tmw[f"Elasticity {b}"] - tmw[f"Elasticity {a}"]
    tmw["p"] = 2 * (1 - stats.norm.cdf((tmw.Change / np.sqrt(tmw[f"SE {a}"] ** 2 + tmw[f"SE {b}"] ** 2)).abs()))

    # ---- outputs
    keep = ["Rows", "Stores", "Weeks", "Price_SD", "Price_Steps", "S1", "S1_SE", "S2", "S2_SE", "S3", "S3_SE", "Level", "Combined",
            "Combined_SE", "Tau2"] + [c for c in r.columns if c.startswith("Cand_")] + [
            "Pooled", "Pooled_SE", "CI_Low", "CI_High", "Elasticity", "Rise", "Cut", "Cut_Reliable", "Rise_Reg", "Cut_Reg", "Asym_p",
            "Rise_Events", "Rise_Events_N", "Own_Only_Final", "Group_Move_Final", "Diversion", "Confidence", "Cautious", "Measured",
            "Behaviour_Cluster"]
    out = r[keep].join(sc[["Name", "MainGroup", "SubGroup", "Segment", "ABC", "Insight", "in_scope", "Revenue_USD"]])
    out.index.name = "Code"
    out.reset_index().to_parquet(CL / "elasticity.parquet", index=False)
    T = out.Revenue_USD.sum()
    out["Band"] = pd.cut(out.Elasticity, [-10, -2, -1, -0.5, 0], labels=["Highly elastic", "Elastic", "Moderate", "Inelastic"])
    bands = out.groupby("Band", observed=True).agg(SKUs=("Name", "size"), Rev_Pct=("Revenue_USD", lambda x: x.sum() / T * 100), Median=("Elasticity", "median"))
    conf = out.groupby("Confidence").agg(SKUs=("Name", "size"), Rev_Pct=("Revenue_USD", lambda x: x.sum() / T * 100))
    t1 = pd.DataFrame({"Test": ["S1 negative & p<5%", "S2 negative & p<5%", "S3 negative & p<5%", "All 3 specs negative",
                                "Rise differs from cut (p<5%)", "Diversion > 20% (switching inside SubGroup)"],
                       "SKUs": [int(((r.S1 < 0) & (r.S1 / r.S1_SE < -1.96)).sum()), int(((r.S2 < 0) & (r.S2 / r.S2_SE < -1.96)).sum()),
                                int(((r.S3 < 0) & (r.S3 / r.S3_SE < -1.96)).sum()), int((agree >= 3).sum()), int((r.Asym_p < 0.05).sum()),
                                int((r.Diversion > 0.2).sum())]})
    with pd.ExcelWriter(OUT / "elasticity.xlsx") as xw:
        pd.DataFrame({"Item": ["Panel rows", "SKUs with own estimate", "SKUs pooled only", "Hold-out start", "Hold-out price steps scored",
                               "Pooling chosen (D3/D7)"],
                      "Value": [len(d), int(out.Measured.sum()), int((~out.Measured).sum()), str(HOLD_START.date()), len(ev), choice]}
                     ).to_excel(xw, sheet_name="Summary", index=False)
        t1.to_excel(xw, sheet_name="D1 tests", index=False)
        bt.round(3).to_excel(xw, sheet_name="D3-D7 back-test")
        bands.round(2).to_excel(xw, sheet_name="Bands"); conf.round(1).to_excel(xw, sheet_name="Confidence")
        st.round(3).to_excel(xw, sheet_name="D8 store clusters", index=False); st_all.round(3).to_excel(xw, sheet_name="D8 all", index=False)
        tmw.round(3).to_excel(xw, sheet_name="D9 over time"); tm_all.round(3).to_excel(xw, sheet_name="D9 all", index=False)
        out.reset_index().round(3).to_excel(xw, sheet_name="SKUs", index=False)
    pd.set_option("display.width", 220)
    print(t1.to_string(index=False)); print(bands.round(2).to_string()); print(conf.round(1).to_string())
    print("median elasticity", round(out.Elasticity.median(), 2), "| rise", round(out.Rise.median(), 2), "| cut", round(out.Cut.median(), 2),
          "| diversion median", round(out.Diversion.median(), 2))
    print(st_all.round(3).to_string(index=False)); print(tm_all.round(3).to_string(index=False))
    print(tmw[["Change", "p"]].round(3).sort_values("p").head(8).to_string())


if __name__ == "__main__":
    main()
