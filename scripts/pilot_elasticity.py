"""Step 9 · Price elasticity estimation for the 40 pilot SKUs -> one final elasticity per SKU

Data: store x SKU x week, Jan 2023 - Jun 2026, clearance weeks excluded (Jul-Sep 2026 kept for the back-test).

 9.1 Linear regression     Units = a + b x real price (store FE)            elasticity at the means = b x P/Q
 9.2 Multiple regression   + season, Christmas, payday, holidays, trend, stock cover, last week's category demand
 9.3 Log-log regression    ln Units = a + beta x ln relative price + controls (store FE)  -> beta = elasticity
                           three specifications from step 8: store FE, store + week FE, chain weekly series
                           rise / cut elasticities (price above / below the usual level)
 9.4 Combine               random-effects meta-analysis of the three log-log specifications (DerSimonian-Laird):
                           disagreement between specifications widens the interval instead of being ignored
 9.5 Shrink                empirical-Bayes toward the sub-category prior from the Phase 1 model (3,716 articles)
 9.6 Final values          overall, rise and cut elasticities; cut capped / made conservative where the cut
                           response is unreliable; bounded to a realistic range for simulation
 9.7 Sanity checks         range, agreement with the SKU's own price events, stability 2024 vs 2025
Outputs: analysis/pilot/elasticity_final.xlsx, clean/pilot/sku_elasticity.parquet, charts.
"""
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from pilot_stats import CONTROLS, add_dev, chain_ts, fit, fit_twoway, load, within

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, AN = ROOT / "clean", ROOT / "analysis"
OUT = AN / "pilot"
BOUNDS = {"overall": (-4.0, -0.2), "rise": (-5.0, -0.2), "cut": (-4.0, -0.1)}
SE_FLOOR = 0.10
C = {"A": "#156082", "B": "#E97132", "C": "#196B24", "D": "#A02B93"}


def level_regression(d, extra):
    """9.1 / 9.2: units in levels on real price (store FE); elasticity evaluated at the means"""
    d = d.assign(Price_Real=np.exp(d.ln_Price_Real), Cover=d.ln_Days_Of_Cover.fillna(d.ln_Days_Of_Cover.median()),
                 CatDem=d.ln_Category_Demand_Lag1.fillna(d.ln_Category_Demand_Lag1.median()))
    cols = ["Units", "Price_Real"] + extra
    Z = within(d, cols)
    Z = Z.loc[:, Z.std() > 1e-9]
    m = sm.OLS(Z.Units, Z.drop(columns="Units")).fit(cov_type="cluster",
                                                      cov_kwds={"groups": d.Plant.astype("category").cat.codes})
    b = m.params.Price_Real
    scale = d.Price_Real.mean() / d.Units.mean()
    return b * scale, m.bse.Price_Real * scale, m.pvalues.Price_Real


def dersimonian_laird(est, se):
    est, se = np.asarray(est, float), np.maximum(np.asarray(se, float), SE_FLOOR)
    ok = ~np.isnan(est) & ~np.isnan(se)
    est, se = est[ok], se[ok]
    w = 1 / se ** 2
    fixed = (w * est).sum() / w.sum()
    q = (w * (est - fixed) ** 2).sum()
    tau2 = max(0.0, (q - (len(est) - 1)) / (w.sum() - (w ** 2).sum() / w.sum())) if len(est) > 1 else 0.0
    wr = 1 / (se ** 2 + tau2)
    return (wr * est).sum() / wr.sum(), np.sqrt(1 / wr.sum()), tau2, q


def subgroup_priors():
    """prior for each sub-group from the Phase 1 article model: robust centre and spread"""
    e = pd.read_parquet(AN / "article_elasticity.parquet")
    out = {}
    for lvl in ["SubGroup", "MainGroup"]:
        for k, x in e.groupby(lvl):
            centre = np.average(x.Elasticity, weights=x.Sales_KZ.clip(lower=1))
            spread = 1.4826 * np.median(np.abs(x.Elasticity_Raw - x.Elasticity_Raw.median()))
            out[(lvl, k)] = (centre, float(np.clip(spread, 0.5, 2.0)), len(x))
    return out


def shrink(est, se, prior, tau):
    w_d, w_p = 1 / se ** 2, 1 / tau ** 2
    post = (w_d * est + w_p * prior) / (w_d + w_p)
    return post, np.sqrt(1 / (w_d + w_p)), w_d / (w_d + w_p)


def main():
    fa = load()
    f = add_dev(fa[~fa.Clearance])
    priors = subgroup_priors()
    ev = pd.read_parquet(CL / "pilot" / "sku_evidence.parquet").set_index("ArticleCode")
    t8 = pd.read_excel(OUT / "statistical_tests.xlsx", sheet_name="T8 Events").set_index("ArticleCode")
    rows = []
    for code, d in f.groupby("ArticleCode"):
        r = {"ArticleCode": code, "ArticleName": d.ArticleName.iloc[0], "SubGroup": d.SubGroup.iloc[0],
             "MainGroup": d.MainGroup.iloc[0], "Group": d.Pilot_Group.iloc[0], "Rows": len(d),
             "Stores": d.Plant.nunique(), "Weeks": d.Week.nunique()}
        # 9.1 / 9.2 level regressions
        r["E_Linear"], r["SE_Linear"], r["p_Linear"] = level_regression(d, [])
        r["E_Multiple"], r["SE_Multiple"], r["p_Multiple"] = level_regression(
            d, ["Week_Sin", "Week_Cos", "Christmas_Season", "Payday_Week", "Holidays_In_Week", "Trend_Weeks", "Cover",
                "CatDem"])
        # 9.3 log-log: three specifications + rise / cut
        m, _, _ = fit(d, ["ln_Relative_Price"])
        r["E_LogLog_StoreFE"], r["SE_LogLog_StoreFE"] = m.params.ln_Relative_Price, m.bse.ln_Relative_Price
        r["E_LogLog_WeekFE"], r["SE_LogLog_WeekFE"], _ = fit_twoway(d, "ln_Relative_Price")
        r["E_LogLog_Chain"], r["SE_LogLog_Chain"], _ = chain_ts(d)
        m2, _, _ = fit(d, ["Rel_Up", "Rel_Down"])
        r["E_Rise_raw"], r["SE_Rise"] = m2.params.get("Rel_Up", np.nan), m2.bse.get("Rel_Up", np.nan)
        r["E_Cut_raw"], r["SE_Cut"] = m2.params.get("Rel_Down", np.nan), m2.bse.get("Rel_Down", np.nan)
        # stability: store-FE log-log by year
        for yr in (2024, 2025):
            dy = d[d.Week.dt.year == yr]
            if len(dy) > 300 and dy.ln_Relative_Price.std() > 0:
                my, _, _ = fit(dy, ["ln_Relative_Price"])
                r[f"E_{yr}"] = my.params.ln_Relative_Price
        rows.append(r)
    e = pd.DataFrame(rows).set_index("ArticleCode")

    # 9.4 combine the three log-log specifications
    comb = e.apply(lambda r: pd.Series(dersimonian_laird(
        [r.E_LogLog_StoreFE, r.E_LogLog_WeekFE, r.E_LogLog_Chain],
        [r.SE_LogLog_StoreFE, r.SE_LogLog_WeekFE, r.SE_LogLog_Chain]),
        index=["E_Combined", "SE_Combined", "Tau2_Between_Specs", "Q_Heterogeneity"]), axis=1)
    e = e.join(comb)

    # 9.5 shrink toward the sub-category prior
    pri = []
    for code, r in e.iterrows():
        key = ("SubGroup", r.SubGroup) if priors.get(("SubGroup", r.SubGroup), (0, 0, 0))[2] >= 5 else ("MainGroup", r.MainGroup)
        centre, tau, n = priors[key]
        post, post_se, wdata = shrink(r.E_Combined, r.SE_Combined, centre, tau)
        pri.append({"ArticleCode": code, "Prior_Level": key[0], "Prior_Elasticity": centre, "Prior_SD": tau,
                    "Prior_N_Articles": n, "E_Shrunk": post, "SE_Shrunk": post_se, "Weight_On_Data": wdata})
    e = e.join(pd.DataFrame(pri).set_index("ArticleCode"))

    # 9.6 final overall / rise / cut
    lo, hi = BOUNDS["overall"]
    e["Elasticity_Final"] = e.E_Shrunk.clip(lo, hi)
    e["CI_Low"], e["CI_High"] = e.E_Shrunk - 1.96 * e.SE_Shrunk, e.E_Shrunk + 1.96 * e.SE_Shrunk
    e["Bounded"] = (e.E_Shrunk < lo) | (e.E_Shrunk > hi)
    # rise / cut: each shrunk toward the SKU's final elasticity (tau 0.75), so asymmetry needs data support
    e["Rise_Final"] = [shrink(r.E_Rise_raw, max(r.SE_Rise, SE_FLOOR), r.Elasticity_Final, 0.75)[0]
                       for _, r in e.iterrows()]
    cut_ok = e.E_Cut_raw < 0
    cut_sh = [shrink(r.E_Cut_raw, max(r.SE_Cut, SE_FLOOR), r.Elasticity_Final, 0.75)[0] for _, r in e.iterrows()]
    e["Cut_Response_Reliable"] = cut_ok
    e["Cut_Final"] = np.where(cut_ok, cut_sh, 0.5 * e.Elasticity_Final)       # unreliable: assume half the response
    e["Cut_Final"] = np.maximum(e.Cut_Final, np.minimum(e.Elasticity_Final, e.Rise_Final))  # cut never > max(|e|,|rise|)
    e["Rise_Final"] = e.Rise_Final.clip(*BOUNDS["rise"])
    e["Cut_Final"] = e.Cut_Final.clip(*BOUNDS["cut"])

    # 9.7 sanity checks
    e = e.join(t8[["Events", "Median_Arc_Elasticity", "Share_Against_Price_%"]], how="left")
    e = e.join(ev[["Confidence"]].rename(columns={"Confidence": "Confidence_Step8"}))
    e["Check_Range"] = e.E_Shrunk.between(-4, -0.2)
    e["Check_Events"] = np.where(e.Events.fillna(0) >= 3,
                                 (e["Share_Against_Price_%"] >= 60) & (e.Median_Arc_Elasticity < 0), np.nan)
    e["Check_Stable"] = np.where(e.E_2024.notna() & e.E_2025.notna(), np.sign(e.E_2024) == np.sign(e.E_2025), np.nan)
    e["Check_CI_Excludes_0"] = e.CI_High < 0
    checks = ["Check_Range", "Check_Events", "Check_Stable", "Check_CI_Excludes_0"]
    e["Checks_Passed"] = e[checks].apply(lambda r: int(np.nansum(r.astype(float))), axis=1)
    e["Checks_Available"] = e[checks].notna().sum(axis=1)

    def confidence(r):
        if r.Confidence_Step8 == "Low" or not r.Check_CI_Excludes_0:
            return "Low"
        if r.Confidence_Step8 == "High" and r.Checks_Passed == r.Checks_Available:
            return "High"
        return "Medium"
    e["Confidence_Final"] = e.apply(confidence, axis=1)
    e["Use"] = e.Confidence_Final.map({"High": "Recommend price change", "Medium": "Recommend, monitor closely",
                                       "Low": "Store test before any change"})
    e = e.reset_index().sort_values(["Group", "Elasticity_Final"])

    summary = e.groupby("Group").agg(SKUs=("ArticleCode", "size"), Median_Final=("Elasticity_Final", "median"),
                                     Median_Rise=("Rise_Final", "median"), Median_Cut=("Cut_Final", "median"),
                                     High=("Confidence_Final", lambda x: (x == "High").sum()),
                                     Medium=("Confidence_Final", lambda x: (x == "Medium").sum()),
                                     Low=("Confidence_Final", lambda x: (x == "Low").sum()),
                                     Bounded=("Bounded", "sum"), Cut_Unreliable=("Cut_Response_Reliable", lambda x: (~x).sum()))
    methods = e[["E_Linear", "E_Multiple", "E_LogLog_StoreFE", "E_LogLog_WeekFE", "E_LogLog_Chain", "E_Combined",
                 "E_Shrunk", "Elasticity_Final"]].describe().T[["mean", "50%", "min", "max"]]
    methods.columns = ["Mean", "Median", "Min", "Max"]
    print(summary.round(2).to_string(), flush=True)
    print(methods.round(2).to_string(), flush=True)

    final_cols = ["Group", "ArticleCode", "ArticleName", "SubGroup", "Elasticity_Final", "CI_Low", "CI_High",
                  "Rise_Final", "Cut_Final", "Cut_Response_Reliable", "Confidence_Final", "Use", "Bounded",
                  "Weight_On_Data", "Prior_Elasticity"]
    with pd.ExcelWriter(OUT / "elasticity_final.xlsx") as xw:
        e[final_cols].round(3).to_excel(xw, sheet_name="Final elasticity", index=False)
        summary.reset_index().round(2).to_excel(xw, sheet_name="Summary by group", index=False)
        methods.reset_index().rename(columns={"index": "Method"}).round(3).to_excel(xw, sheet_name="Methods compared",
                                                                                   index=False)
        e[["Group", "ArticleCode", "ArticleName", "E_Linear", "SE_Linear", "p_Linear", "E_Multiple", "SE_Multiple",
           "p_Multiple"]].round(4).to_excel(xw, sheet_name="9.1-9.2 Linear & multiple", index=False)
        e[["Group", "ArticleCode", "ArticleName", "E_LogLog_StoreFE", "SE_LogLog_StoreFE", "E_LogLog_WeekFE",
           "SE_LogLog_WeekFE", "E_LogLog_Chain", "SE_LogLog_Chain", "E_Rise_raw", "SE_Rise", "E_Cut_raw", "SE_Cut"]
          ].round(4).to_excel(xw, sheet_name="9.3 Log-log specs", index=False)
        e[["Group", "ArticleCode", "ArticleName", "E_Combined", "SE_Combined", "Tau2_Between_Specs",
           "Q_Heterogeneity", "Prior_Level", "Prior_Elasticity", "Prior_SD", "Prior_N_Articles", "Weight_On_Data",
           "E_Shrunk", "SE_Shrunk"]].round(4).to_excel(xw, sheet_name="9.4-9.5 Combine & shrink", index=False)
        e[["Group", "ArticleCode", "ArticleName", "E_Shrunk", "Events", "Median_Arc_Elasticity", "Share_Against_Price_%",
           "E_2024", "E_2025"] + checks + ["Checks_Passed", "Checks_Available", "Confidence_Step8",
                                           "Confidence_Final"]].round(3).to_excel(xw, sheet_name="9.7 Sanity checks",
                                                                                  index=False)
        pd.DataFrame({"Item": ["Data", "Overall bounds", "Rise bounds", "Cut bounds", "Unreliable cut rule",
                               "Combination", "Shrinkage prior", "SE floor"],
                      "Value": ["store x SKU x week, Jan 2023 - Jun 2026, clearance weeks excluded",
                                str(BOUNDS["overall"]), str(BOUNDS["rise"]), str(BOUNDS["cut"]),
                                "cut = 0.5 x overall elasticity; |cut| never above max(|overall|, |rise|)",
                                "DerSimonian-Laird random effects over store-FE, week-FE and chain specifications",
                                "Phase 1 sub-category elasticity (sales-weighted), spread = robust SD clipped 0.5-2.0",
                                str(SE_FLOOR)]}).to_excel(xw, sheet_name="Method notes", index=False)
    e.to_parquet(CL / "pilot" / "sku_elasticity.parquet", index=False)

    # charts: final elasticity with CI, and raw combined vs final
    d = e.sort_values(["Group", "Elasticity_Final"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(8.5, 10))
    for i, r in d.iterrows():
        ax.plot([max(r.CI_Low, -8), min(r.CI_High, 2)], [i, i], color=C[r.Group], lw=2, alpha=.5)
        ax.scatter(r.E_Combined, i, color="#7F8781", s=14, marker="|", zorder=3)
        ax.scatter(r.Elasticity_Final, i, color=C[r.Group], s=34, zorder=4,
                   marker={"High": "o", "Medium": "s", "Low": "x"}[r.Confidence_Final])
    ax.axvline(0, color="#4D5751", lw=.8)
    ax.axvline(-1, color="#4D5751", lw=.8, ls="--")
    ax.set_yticks(range(len(d)), [f"{r.Group} · {str(r.ArticleName).title()[:34]}" for _, r in d.iterrows()],
                  fontsize=6.5)
    ax.set_xlim(-8, 2)
    ax.invert_yaxis()
    ax.set_xlabel("final elasticity (o High, ■ Medium, x Low) · grey tick = combined before shrinkage · line = 95% CI")
    fig.savefig(OUT / "elasticity_final.png", dpi=180, bbox_inches="tight")


if __name__ == "__main__":
    main()
