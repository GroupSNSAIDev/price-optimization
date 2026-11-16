"""Step 8 · Statistical analysis & hypothesis testing for the 40 pilot SKUs (statsmodels)

Data: store x SKU x week, Jan 2023 - Jun 2026 (train + valid; the Jul-Sep 2026 test period is not touched).
Significance 5%; Benjamini-Hochberg false-discovery-rate correction across the 40 SKUs in every test family.

 T1 price effect per SKU      log-log OLS: ln units ~ ln relative price + store FE + season/holiday/payday/trend,
                              store-clustered SE; t-test, p-value, 95% CI
 T2 rise vs cut asymmetry     same model with price above / below the store-SKU usual level; Wald test b_up = b_down
                              (per SKU, per group, chain)
 T3 group differences         ANOVA + Kruskal-Wallis across groups A-D (elasticity, margin, volume) + pairwise tests
 T4 zone differences          per SKU: price x zone interaction, Wald test of equal slopes; store margin by zone
 T5 correlations              within store-SKU (demeaned): price-units, discount-units, stock cover-units,
                              cost-margin; Pearson & Spearman with p-values
 T6 time-series checks        chain weekly units per store: ADF stationarity, Ljung-Box autocorrelation,
                              December & payday effects, Chow structural break at the Jun 2023 devaluation
 T7 model assumptions         residual normality (Jarque-Bera), heteroscedasticity (Breusch-Pagan),
                              residual autocorrelation (Durbin-Watson), VIF of the linear feature set
 T8 price-change events       Wilcoxon signed-rank: volume moves against price after the SKU's own price changes
 -> per-SKU evidence table with an overall confidence rating (High / Medium / Low)
"""
import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson, jarque_bera
from statsmodels.tsa.stattools import adfuller

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, AN = ROOT / "clean", ROOT / "analysis"
OUT = AN / "pilot"
TEST_START = pd.Timestamp("2026-06-29")
BREAK = pd.Timestamp("2023-06-12")                    # kwanza devaluation
ALPHA = 0.05
CONTROLS = ["Week_Sin", "Week_Cos", "Christmas_Season", "Payday_Week", "Holidays_In_Week", "Trend_Weeks"]
C = {"A": "#156082", "B": "#E97132", "C": "#196B24", "D": "#A02B93"}


def load():
    f = pd.read_parquet(CL / "pilot" / "pilot_features.parquet")
    f = f[(f.Week < TEST_START)].dropna(subset=["ln_Units", "ln_Relative_Price"]).copy()
    loc = pd.read_parquet(CL / "dim_location.parquet", columns=["Plant", "Area_Zone"])
    f = f.merge(loc, on="Plant", how="left")
    f["Zone"] = np.where(f.Area_Zone.eq("PROVINCE"), "Province", "Luanda")
    # clearance weeks: sold far below cost, or a deep one-off cut (> 30% below usual) that is back within 2 weeks
    f = f.sort_values(["Plant", "ArticleCode", "Week"]).reset_index(drop=True)
    g = f.groupby(["Plant", "ArticleCode"], sort=False)
    usual = f.ln_Price_Real - f.ln_Price_vs_Usual
    back = np.fmax(g.ln_Price_Real.shift(-1), g.ln_Price_Real.shift(-2)) >= usual + np.log(0.95)
    f["Below_Cost"] = f.Price_KZ < f.Unit_COGS_KZ / 1.5
    f["Deep_OneOff_Cut"] = (f.ln_Price_vs_Usual < np.log(0.7)) & back.fillna(False)
    f["Clearance"] = f.Below_Cost | f.Deep_OneOff_Cut
    return add_dev(f)


def add_dev(f):
    """deviation of relative price from the store-SKU usual level, split into rise / cut parts"""
    f = f.copy()
    f["dev"] = f.ln_Relative_Price - f.groupby(["Plant", "ArticleCode"]).ln_Relative_Price.transform("mean")
    f["Rel_Up"], f["Rel_Down"] = f.dev.clip(lower=0), f.dev.clip(upper=0)
    return f


def chain_ts(d):
    """third specification: chain-level weekly time series (suits centrally set prices)
    ln(units per selling store) ~ ln(sales-weighted relative price) + season, Christmas, payday, holidays, trend; HAC SE"""
    d = d.assign(w=d.Sales_KZ * d.ln_Relative_Price)
    wk = d.groupby("Week").agg(Units=("Units", "sum"), Stores=("Plant", "nunique"), W=("w", "sum"), S=("Sales_KZ", "sum"),
                               Christmas=("Christmas_Season", "max"), Payday=("Payday_Week", "max"),
                               Holidays=("Holidays_In_Week", "max"), Wsin=("Week_Sin", "first"),
                               Wcos=("Week_Cos", "first"), Trend=("Trend_Weeks", "first"))
    wk = wk[wk.Stores >= 3]
    if len(wk) < 40:
        return np.nan, np.nan, np.nan
    y = np.log(wk.Units / wk.Stores)
    X = sm.add_constant(pd.DataFrame({"lnP": wk.W / wk.S, "Christmas": wk.Christmas, "Payday": wk.Payday,
                                      "Holidays": wk.Holidays, "Wsin": wk.Wsin, "Wcos": wk.Wcos, "Trend": wk.Trend}))
    m = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
    return m.params.lnP, m.bse.lnP, m.pvalues.lnP


def within(d, cols, by="Plant"):
    """store fixed effects by demeaning"""
    return d[cols] - d.groupby(by)[cols].transform("mean")


def fit(d, xcols):
    y = within(d, ["ln_Units"]).ln_Units
    X = within(d, xcols + CONTROLS)
    X = X.loc[:, X.std() > 1e-9]
    m = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": d.Plant.astype("category").cat.codes})
    return m, X, y


def fit_twoway(d, xcol):
    """robustness: store FE + week FE (two-way, alternating projections); no other controls needed"""
    Z = d[["ln_Units", xcol]].copy()
    for _ in range(8):
        Z = Z - Z.groupby(d.Plant.values).transform("mean")
        Z = Z - Z.groupby(d.Week.values).transform("mean")
    m = sm.OLS(Z.ln_Units, Z[[xcol]]).fit(cov_type="cluster", cov_kwds={"groups": d.Plant.astype("category").cat.codes})
    return m.params[xcol], m.bse[xcol], m.pvalues[xcol]


def bh(p):
    p = pd.Series(p)
    out = pd.Series(np.nan, index=p.index)
    ok = p.notna()
    if ok.any():
        out[ok] = multipletests(p[ok], method="fdr_bh")[1]
    return out


def main():
    fa = load()                                   # all weeks (incl. clearance) - used for time series & comparison
    f = add_dev(fa[~fa.Clearance])                # clearance weeks excluded from every price-response test
    sk = fa.groupby("ArticleCode").agg(ArticleName=("ArticleName", "first"), SubGroup=("SubGroup", "first"),
                                       Group=("Pilot_Group", "first"), Rows=("ln_Units", "size"),
                                       Stores=("Plant", "nunique"))
    # clearance impact: share of weeks flagged, and the store-FE estimates with vs without them
    clr = []
    for code, d in fa.groupby("ArticleCode"):
        mA, _, _ = fit(d, ["ln_Relative_Price"])
        mB, _, _ = fit(d, ["Rel_Up", "Rel_Down"])
        clr.append({"ArticleCode": code, "Clearance_Weeks_%": d.Clearance.mean() * 100,
                    "Below_Cost_%": d.Below_Cost.mean() * 100, "Deep_OneOff_Cut_%": d.Deep_OneOff_Cut.mean() * 100,
                    "Elasticity_All_Weeks": mA.params["ln_Relative_Price"], "Cut_All_Weeks": mB.params.get("Rel_Down"),
                    "Rise_All_Weeks": mB.params.get("Rel_Up")})
    clr = pd.DataFrame(clr).set_index("ArticleCode")
    print(f"clearance weeks excluded: {fa.Clearance.sum():,} of {len(fa):,} ({fa.Clearance.mean() * 100:.1f}%)", flush=True)
    t1, t2, t4, t5, t7 = [], [], [], [], []
    for code, d in f.groupby("ArticleCode"):
        # T1 price effect
        m, X, y = fit(d, ["ln_Relative_Price"])
        b, se = m.params["ln_Relative_Price"], m.bse["ln_Relative_Price"]
        ci = m.conf_int().loc["ln_Relative_Price"]
        t1.append({"ArticleCode": code, "Elasticity": b, "SE": se, "t": m.tvalues["ln_Relative_Price"],
                   "p": m.pvalues["ln_Relative_Price"], "CI_low": ci[0], "CI_high": ci[1],
                   "R2_within": m.rsquared, "Price_SD": d.dev.std()})
        b2, se2, p2 = fit_twoway(d, "ln_Relative_Price")
        b3, se3, p3 = chain_ts(d)
        t1[-1].update({"Elasticity_WeekFE": b2, "SE_WeekFE": se2, "p_WeekFE": p2,
                       "Elasticity_Chain": b3, "SE_Chain": se3, "p_Chain": p3})
        # T7 assumptions on this regression
        res = m.resid
        jb_p = jarque_bera(res)[1]
        bp_p = het_breuschpagan(res, sm.add_constant(X))[1]
        dw = durbin_watson(res.loc[d.sort_values(["Plant", "Week"]).index])
        t7.append({"ArticleCode": code, "JarqueBera_p": jb_p, "Normal_Residuals": jb_p >= ALPHA,
                   "BreuschPagan_p": bp_p, "Constant_Variance": bp_p >= ALPHA, "Durbin_Watson": dw,
                   "Residual_Autocorrelation": not (1.5 <= dw <= 2.5),
                   "Remedy": "store-clustered standard errors (robust to both)"})
        # T2 asymmetry
        m2, _, _ = fit(d, ["Rel_Up", "Rel_Down"])
        w = m2.wald_test("Rel_Up = Rel_Down", scalar=True)
        t2.append({"ArticleCode": code, "Elasticity_Rise": m2.params.get("Rel_Up"), "p_Rise": m2.pvalues.get("Rel_Up"),
                   "Elasticity_Cut": m2.params.get("Rel_Down"), "p_Cut": m2.pvalues.get("Rel_Down"),
                   "Wald_p": float(w.pvalue)})
        # T4 zone: price x province interaction
        if d.Zone.nunique() == 2 and (d.Zone == "Province").sum() > 200:
            d = d.assign(Price_x_Province=d.ln_Relative_Price * (d.Zone == "Province"))
            m4, _, _ = fit(d, ["ln_Relative_Price", "Price_x_Province"])
            t4.append({"ArticleCode": code, "Elasticity_Luanda": m4.params["ln_Relative_Price"],
                       "Province_Difference": m4.params["Price_x_Province"],
                       "Elasticity_Province": m4.params["ln_Relative_Price"] + m4.params["Price_x_Province"],
                       "p_Difference": m4.pvalues["Price_x_Province"]})
        # T5 correlations, within store-SKU
        dd = d.copy()
        dd["Stock"] = dd.ln_Days_Of_Cover
        cols = {"Price vs units": ("ln_Relative_Price", "ln_Units"), "Discount vs units": ("Discount_Pct", "ln_Units"),
                "Stock cover vs units": ("Stock", "ln_Units"), "Last week's cost vs margin":
                ("ln_Unit_Cost_Real_Lag1", "Margin_Pct_Lag1")}
        for name, (a, bcol) in cols.items():
            x = dd[[a, bcol, "Plant"]].dropna()
            if len(x) < 30 or x[a].std() == 0:
                continue
            xa = x[a] - x.groupby("Plant")[a].transform("mean")
            xb = x[bcol] - x.groupby("Plant")[bcol].transform("mean")
            pr, pp = stats.pearsonr(xa, xb)
            sr, spv = stats.spearmanr(xa, xb)
            t5.append({"ArticleCode": code, "Relationship": name, "Pearson_r": pr, "Pearson_p": pp,
                       "Spearman_rho": sr, "Spearman_p": spv, "N": len(x)})
    t1, t2 = pd.DataFrame(t1).set_index("ArticleCode"), pd.DataFrame(t2).set_index("ArticleCode")
    t4, t5, t7 = pd.DataFrame(t4).set_index("ArticleCode"), pd.DataFrame(t5), pd.DataFrame(t7).set_index("ArticleCode")
    t1["p_BH"] = bh(t1.p)
    t1["Significant"] = (t1.p_BH < ALPHA) & (t1.Elasticity < 0)
    t1["CI_Width"] = t1.CI_high - t1.CI_low
    t1["Specs_Negative"] = ((t1.Elasticity < 0).astype(int) + (t1.Elasticity_WeekFE < 0).astype(int)
                            + (t1.Elasticity_Chain < 0).astype(int))
    t1["Sign_Robust"] = t1.Specs_Negative >= 2           # at least 2 of the 3 specifications negative
    t1["All_3_Negative"] = t1.Specs_Negative == 3
    t2["Wald_p_BH"] = bh(t2.Wald_p)
    t2["Asymmetric"] = t2.Wald_p_BH < ALPHA
    t2["Cut_Response_Reliable"] = t2.Elasticity_Cut < 0      # positive = clearance / reverse causality, not usable
    t4["p_BH"] = bh(t4.p_Difference)
    t4["Zone_Differs"] = t4.p_BH < ALPHA
    t5["Pearson_p_BH"] = t5.groupby("Relationship").Pearson_p.transform(lambda p: bh(p.reset_index(drop=True)).values)
    print(f"T1 price significant (BH): {int(t1.Significant.sum())}/40; T2 asymmetric: {int(t2.Asymmetric.sum())}; "
          f"T4 zone differs: {int(t4.Zone_Differs.sum())}/{len(t4)}", flush=True)

    # T2 pooled: per group and chain (SKU x store fixed effects)
    pooled = []
    for name, d in [("Chain (40 SKUs)", f)] + [(f"Group {g}", d) for g, d in f.groupby("Pilot_Group")]:
        key = d.Plant + "|" + d.ArticleCode
        y = within(d, ["ln_Units"], key).ln_Units
        X = within(d, ["Rel_Up", "Rel_Down"] + CONTROLS, key)
        m = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": d.Plant.astype("category").cat.codes})
        w = m.wald_test("Rel_Up = Rel_Down", scalar=True)
        pooled.append({"Scope": name, "Elasticity_Rise": m.params.Rel_Up, "SE_Rise": m.bse.Rel_Up,
                       "Elasticity_Cut": m.params.Rel_Down, "SE_Cut": m.bse.Rel_Down, "Wald_F": float(w.statistic),
                       "Wald_p": float(w.pvalue), "Asymmetric": float(w.pvalue) < ALPHA})
    pooled = pd.DataFrame(pooled)

    # T3 groups
    # margin = last-12-month margin, the period the groups were defined on (fix 1)
    prof = pd.read_parquet(CL / "pilot" / "product_segments.parquet").set_index("ArticleCode")
    short = pd.read_parquet(AN / "rda" / "sku_shortlist.parquet")
    short.index = short.ArticleCode.str.zfill(18)
    g = sk.join(t1[["Elasticity"]]).join(short[["Margin_Pct"]].rename(columns={"Margin_Pct": "Margin_Pct_L12M"}))
    g = g.join(prof[["ln_Weekly_Units", "Volatility_CV"]])
    t3, pair = [], []
    for v in ["Elasticity", "Margin_Pct_L12M", "ln_Weekly_Units", "Volatility_CV"]:
        arr = [x[v].dropna().values for _, x in g.groupby("Group")]
        fstat, pa = stats.f_oneway(*arr)
        kh, pk = stats.kruskal(*arr)
        t3.append({"Measure": v, "ANOVA_F": fstat, "ANOVA_p": pa, "KruskalWallis_H": kh, "KruskalWallis_p": pk,
                   "Groups_Differ": pk < ALPHA, **{f"Median_{k}": np.median(a) for k, a in zip("ABCD", arr)}})
        for i, a in enumerate("ABCD"):
            for b in "ABCD"[i + 1:]:
                u, pu = stats.mannwhitneyu(g[g.Group == a][v].dropna(), g[g.Group == b][v].dropna())
                pair.append({"Measure": v, "Pair": f"{a} vs {b}", "MannWhitney_p": pu})
    t3, pair = pd.DataFrame(t3), pd.DataFrame(pair)
    pair["p_BH"] = pair.groupby("Measure").MannWhitney_p.transform(lambda p: bh(p.reset_index(drop=True)).values)

    # T4b store margin by zone (training months)
    st = pd.read_parquet(CL / "pilot" / "store_segments.parquet")
    st = st.merge(pd.read_parquet(CL / "dim_location.parquet", columns=["Plant", "Area_Zone"]), on="Plant")
    zarr = [x.Margin_Pct.values for _, x in st.groupby("Area_Zone") if len(x) >= 2]
    zone_margin = {"ANOVA_p": stats.f_oneway(*zarr).pvalue, "KruskalWallis_p": stats.kruskal(*zarr).pvalue,
                   "Province_median": st[st.Area_Zone == "PROVINCE"].Margin_Pct.median(),
                   "Luanda_median": st[st.Area_Zone != "PROVINCE"].Margin_Pct.median()}

    # T6 time series: chain weekly units per selling store
    t6 = []
    for code, d in fa.groupby("ArticleCode"):                       # demand series uses all weeks
        wk = d.groupby("Week").agg(Units=("Units", "sum"), Stores=("Plant", "nunique"), Christ=("Christmas_Season", "max"),
                                   Pay=("Payday_Week", "max"))
        wk = wk[wk.Stores >= 3]
        s = np.log(wk.Units / wk.Stores)
        if len(s) < 40:
            continue
        adf_p = adfuller(s, autolag="AIC")[1]
        lb_p = acorr_ljungbox(s, lags=[4]).lb_pvalue.iloc[0]
        tt = np.arange(len(s))
        Xs = sm.add_constant(np.column_stack([tt, wk.Christ.values, wk.Pay.values]))
        ms = sm.OLS(s.values, Xs).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
        pre, post = s.index < BREAK, s.index >= BREAK
        chow_p = np.nan
        if pre.sum() >= 8 and post.sum() >= 8:                      # Chow test on a trend model
            def rss(mask):
                return sm.OLS(s.values[mask], sm.add_constant(tt[mask])).fit().ssr
            k = 2
            r_all, r_1, r_2 = rss(np.ones(len(s), bool)), rss(pre), rss(post)
            Fc = ((r_all - r_1 - r_2) / k) / ((r_1 + r_2) / (len(s) - 2 * k))
            chow_p = 1 - stats.f.cdf(Fc, k, len(s) - 2 * k)
        t6.append({"ArticleCode": code, "Weeks": len(s), "ADF_p": adf_p, "Stationary": adf_p < ALPHA,
                   "LjungBox_p_lag4": lb_p, "Autocorrelated": lb_p < ALPHA,
                   "December_Effect_%": (np.exp(ms.params[2]) - 1) * 100, "December_p": ms.pvalues[2],
                   "Payday_Effect_%": (np.exp(ms.params[3]) - 1) * 100, "Payday_p": ms.pvalues[3],
                   "Chow_Break_p": chow_p, "Break_Jun2023": chow_p < ALPHA if not np.isnan(chow_p) else None})
    t6 = pd.DataFrame(t6).set_index("ArticleCode")
    for c in ["December_p", "Payday_p"]:
        t6[c + "_BH"] = bh(t6[c])

    # T7b VIF of the linear feature set
    linf = json.load(open(OUT / "selected_features.json"))["linear_features"]
    V = f[linf].fillna(f[linf].median()).sample(min(50000, len(f)), random_state=1)
    V = sm.add_constant((V - V.mean()) / V.std().replace(0, 1))
    vif = pd.DataFrame({"Feature": linf, "VIF": [variance_inflation_factor(V.values, i + 1) for i in range(len(linf))]})

    # T8 price-change events (own SKU, vs category in the same store)
    ev = pd.read_parquet(AN / "price_events.parquet")
    ev = ev[ev.ArticleCode.isin(sk.index) & (ev.Week < TEST_START)]
    t8 = []
    for code, d in ev.groupby("ArticleCode"):
        signed = -np.sign(d["Price_Change_%"]) * d["Volume_Change_%"]       # > 0 when volume moves against price
        p = stats.wilcoxon(signed, alternative="greater").pvalue if len(d) >= 6 else np.nan
        t8.append({"ArticleCode": code, "Events": len(d), "Share_Against_Price_%": (signed > 0).mean() * 100,
                   "Median_Arc_Elasticity": d.Arc_Elasticity.median(), "Wilcoxon_p": p})
    t8 = pd.DataFrame(t8).set_index("ArticleCode")
    t8["Wilcoxon_p_BH"] = bh(t8.Wilcoxon_p)
    t8["Events_Confirm"] = t8.Wilcoxon_p_BH < 0.10

    # evidence table + confidence rating
    ev_tab = sk.join(t1[["Elasticity", "CI_low", "CI_high", "CI_Width", "p_BH", "Significant", "Elasticity_WeekFE",
                         "Elasticity_Chain", "p_Chain", "Specs_Negative", "Sign_Robust", "All_3_Negative"]]) \
        .join(clr[["Clearance_Weeks_%", "Elasticity_All_Weeks", "Cut_All_Weeks"]]) \
        .join(t2[["Elasticity_Rise", "Elasticity_Cut", "Wald_p_BH", "Asymmetric", "Cut_Response_Reliable"]]) \
        .join(t4[["Elasticity_Province", "Zone_Differs"]]) \
        .join(t6[["Stationary", "December_Effect_%", "December_p_BH", "Break_Jun2023"]]) \
        .join(t8[["Events", "Share_Against_Price_%", "Events_Confirm"]])
    def rating(r):
        """High: significant, negative in all 3 specifications, confirmed by own price events, precise.
        Medium: significant and negative in at least 2 of 3 specifications. Low: otherwise."""
        if r.Significant and r.All_3_Negative and r.Events_Confirm is True and r.CI_Width < 1.5:
            return "High"
        if r.Significant and r.Sign_Robust:
            return "Medium"
        return "Low"
    ev_tab["Events_Confirm"] = ev_tab.Events_Confirm.astype(object).where(ev_tab.Events_Confirm.notna(), None)
    ev_tab["Confidence"] = ev_tab.apply(rating, axis=1)
    ev_tab = ev_tab.reset_index().sort_values(["Group", "Confidence"])
    summary = ev_tab.groupby("Group").agg(SKUs=("ArticleCode", "size"), Price_Significant=("Significant", "sum"),
                                          Neg_2of3=("Sign_Robust", "sum"), Neg_3of3=("All_3_Negative", "sum"),
                                          Asymmetric=("Asymmetric", "sum"),
                                          Cut_Reliable=("Cut_Response_Reliable", "sum"),
                                          High=("Confidence", lambda x: (x == "High").sum()),
                                          Medium=("Confidence", lambda x: (x == "Medium").sum()),
                                          Low=("Confidence", lambda x: (x == "Low").sum()),
                                          Median_Elasticity=("Elasticity", "median"))
    print(summary.to_string(), flush=True)
    print(pooled.round(3).to_string(index=False), flush=True)

    with pd.ExcelWriter(OUT / "statistical_tests.xlsx") as xw:
        summary.reset_index().round(2).to_excel(xw, sheet_name="Summary by group", index=False)
        ev_tab.round(3).to_excel(xw, sheet_name="Evidence per SKU", index=False)
        ci = sk[["ArticleName", "Group"]].join(clr)
        ci["Elasticity_Excl_Clearance"] = t1.Elasticity
        ci["Cut_Excl_Clearance"] = t2.Elasticity_Cut
        ci.reset_index().round(3).to_excel(xw, sheet_name="Clearance impact", index=False)
        sk.join(t1).reset_index().round(4).to_excel(xw, sheet_name="T1 Price effect", index=False)
        sk[["ArticleName", "Group"]].join(t2).reset_index().round(4).to_excel(xw, sheet_name="T2 Asymmetry per SKU",
                                                                              index=False)
        pooled.round(4).to_excel(xw, sheet_name="T2 Asymmetry pooled", index=False)
        t3.round(4).to_excel(xw, sheet_name="T3 Groups", index=False)
        pair.round(4).to_excel(xw, sheet_name="T3 Pairwise", index=False)
        sk[["ArticleName", "Group"]].join(t4, how="inner").reset_index().round(4).to_excel(
            xw, sheet_name="T4 Zone per SKU", index=False)
        pd.DataFrame([zone_margin]).round(4).to_excel(xw, sheet_name="T4 Store margin by zone", index=False)
        t5.merge(sk[["ArticleName", "Group"]].reset_index(), on="ArticleCode").round(4).to_excel(
            xw, sheet_name="T5 Correlations", index=False)
        t5.groupby("Relationship").agg(SKUs=("ArticleCode", "size"), Median_Pearson=("Pearson_r", "median"),
                                       Significant_BH=("Pearson_p_BH", lambda p: (p < ALPHA).sum())).round(3).to_excel(
            xw, sheet_name="T5 Summary")
        sk[["ArticleName", "Group"]].join(t6, how="inner").reset_index().round(4).to_excel(
            xw, sheet_name="T6 Time series", index=False)
        sk[["ArticleName", "Group"]].join(t7).reset_index().round(4).to_excel(xw, sheet_name="T7 Assumptions",
                                                                              index=False)
        vif.round(2).to_excel(xw, sheet_name="T7 VIF linear set", index=False)
        sk[["ArticleName", "Group"]].join(t8, how="inner").reset_index().round(4).to_excel(
            xw, sheet_name="T8 Events", index=False)
    ev_tab.to_parquet(CL / "pilot" / "sku_evidence.parquet", index=False)

    # forest plot of SKU elasticities with 95% CI
    e = ev_tab.sort_values(["Group", "Elasticity"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(8, 10))
    y = np.arange(len(e))
    for i, r in e.iterrows():
        ax.plot([r.CI_low, r.CI_high], [i, i], color=C[r.Group], lw=2, alpha=.6)
        ax.scatter(r.Elasticity, i, color=C[r.Group], s=30, zorder=3,
                   marker="o" if r.Significant else "x")
    ax.axvline(0, color="#4D5751", lw=.8)
    ax.axvline(-1, color="#4D5751", lw=.8, ls="--")
    ax.set_yticks(y, [f"{r.Group} · {str(r.ArticleName).title()[:34]} ({r.Confidence[0]})" for _, r in e.iterrows()],
                  fontsize=6.5)
    ax.set_xlabel("price elasticity (log-log, store FE, 95% CI)   o = significant after BH, x = not")
    ax.set_xlim(-8, 3)
    ax.invert_yaxis()
    fig.savefig(OUT / "elasticity_forest.png", dpi=180, bbox_inches="tight")
    json.dump({"price_significant": int(t1.Significant.sum()), "asymmetric_skus": int(t2.Asymmetric.sum()),
               "zone_differs": int(t4.Zone_Differs.sum()), "zone_tested": len(t4),
               "confidence": ev_tab.Confidence.value_counts().to_dict(),
               "pooled": pooled.round(4).to_dict("records"), "zone_margin": zone_margin},
              open(OUT / "statistical_tests.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
