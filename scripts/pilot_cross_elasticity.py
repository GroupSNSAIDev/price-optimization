"""Step 9 (fixes) · rise-elasticity calibration and cross-price effects between substitute pilot SKUs

Fix 1 - rise elasticity: the regression rise estimate (few weeks above the usual price -> noisy) is combined with the
        SKU's own price-rise events (median arc elasticity vs category, winsorised), inverse-variance weighted,
        shrunk toward the SKU's final elasticity and capped at 1.5 x the overall elasticity.
Fix 2 - substitution inside Fresmart: for clusters of pilot SKUs that replace each other on the shelf, regress each
        SKU's units on its own and its rivals' real prices (store FE, season, Christmas, payday, holidays, trend,
        store-clustered SE). Cross-elasticities are shrunk toward 0, kept only when positive (substitutes), and turned
        into diversion ratios: the share of the revenue a SKU loses on a price rise that its rivals win back.
        Diversion per SKU is capped at 90%.
Updates clean/pilot/sku_elasticity.parquet; writes clean/pilot/cross_elasticity.parquet and adds sheets to
analysis/pilot/elasticity_final.xlsx.
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from pilot_stats import CONTROLS, TEST_START, load

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, AN = ROOT / "clean", ROOT / "analysis"
OUT = AN / "pilot"
RISE_CAP_MULT = 1.5
TAU_RISE, TAU_CROSS, MAX_DIVERSION, CROSS_P = 0.75, 0.5, 0.6, 0.10
CLUSTERS = {   # pilot SKUs that substitute for each other on the shelf (codes without leading zeros)
    "Soy oil": ["117433", "110680", "101304", "117443"],
    "Chicken sausage": ["116433", "118520"],
    "Chicken leg quarters": ["100501", "100423", "107620", "107637", "100520"],
    "Delta Q capsules": ["106283", "105970", "105969"],
    "Sugar Kapanda": ["101241", "101237"],
    "Rice": ["101249", "101250"],
    "Friboi beef cuts": ["113475", "113480", "113484"],
}
z = lambda c: c.zfill(18)


def calibrate_rise(e):
    ev = pd.read_parquet(AN / "price_events.parquet")
    ev = ev[ev.ArticleCode.isin(e.index) & (ev.Week < TEST_START) & (ev["Price_Change_%"] > 0)]
    ev["Arc"] = ev.Arc_Elasticity.clip(-10, 5)
    g = ev.groupby("ArticleCode").Arc
    evs = pd.DataFrame({"Rise_Events": g.size(), "Rise_Event_Median": g.median(),
                        "Rise_Event_SE": (1.2533 * g.std() / np.sqrt(g.size())).clip(lower=0.3)})
    e = e.join(evs)
    rows = []
    for code, r in e.iterrows():
        est = [r.E_Rise_raw]
        se = [max(r.SE_Rise, 0.1)]
        if r.Rise_Events >= 3 and pd.notna(r.Rise_Event_Median):
            est.append(r.Rise_Event_Median)
            se.append(r.Rise_Event_SE)
        w = 1 / np.square(se)
        comb, comb_se = np.dot(w, est) / w.sum(), np.sqrt(1 / w.sum())
        wd, wp = 1 / comb_se ** 2, 1 / TAU_RISE ** 2
        post = (wd * comb + wp * r.Elasticity_Final) / (wd + wp)
        capped = float(np.clip(post, max(RISE_CAP_MULT * r.Elasticity_Final, -5.0), -0.2))
        rows.append({"ArticleCode": code, "Rise_Combined_Reg_Events": comb, "Rise_Shrunk": post,
                     "Rise_Capped": post < max(RISE_CAP_MULT * r.Elasticity_Final, -5.0), "Rise_Final_New": capped})
    e = e.join(pd.DataFrame(rows).set_index("ArticleCode"))
    e["Rise_Final_Old"] = e.Rise_Final
    e["Rise_Final"] = e.Rise_Final_New
    # re-apply the cut cap against the new rise value
    e["Cut_Final"] = np.maximum(e.Cut_Final, np.minimum(e.Elasticity_Final, e.Rise_Final)).clip(-4, -0.1)
    return e.drop(columns="Rise_Final_New")


def price_panel(codes):
    """ln real price per store-week for the cluster's SKUs; gaps filled from the store's previous/next week, then the
    chain weekly median"""
    f = pd.read_parquet(CL / "pilot" / "pilot_features.parquet", columns=["Week", "Plant", "ArticleCode",
                                                                           "ln_Price_Real"])
    f = f[f.ArticleCode.isin(codes)]
    p = f.pivot_table(index=["Plant", "Week"], columns="ArticleCode", values="ln_Price_Real")
    p = p.groupby(level=0).transform(lambda s: s.ffill().bfill())
    chain = f.groupby(["Week", "ArticleCode"]).ln_Price_Real.median().unstack()
    for c in p.columns:
        p[c] = p[c].fillna(pd.Series(p.index.get_level_values(1), index=p.index).map(chain[c]))
    return p


def cross_effects(e, f):
    rows = []
    for name, short in CLUSTERS.items():
        codes = [z(c) for c in short if z(c) in e.index]
        if len(codes) < 2:
            continue
        P = price_panel(codes)
        for i in codes:
            d = f[f.ArticleCode == i].set_index(["Plant", "Week"])
            d = d.join(P.add_prefix("p_"), how="left")
            own, rivals = f"p_{i}", [f"p_{j}" for j in codes if j != i]
            cols = ["ln_Units", own] + rivals + CONTROLS
            d = d.dropna(subset=cols)
            groups = pd.Categorical(d.index.get_level_values(0)).codes
            # spec 1: store FE + season / holiday / payday / trend controls
            Z = d[cols] - d.groupby(level=0)[cols].transform("mean")
            Z = Z.loc[:, Z.std() > 1e-9]
            m = sm.OLS(Z.ln_Units, Z.drop(columns="ln_Units")).fit(cov_type="cluster", cov_kwds={"groups": groups})
            # spec 2: store FE + week FE (removes shocks common to all brands: FX, supplier cost, market demand)
            c2 = ["ln_Units", own] + rivals
            W = d[c2].copy()
            wk = d.index.get_level_values(1)
            for _ in range(8):
                W = W - W.groupby(level=0).transform("mean")
                W = W - W.groupby(wk).transform("mean")
            W = W.loc[:, W.std() > 1e-9]
            m2 = sm.OLS(W.ln_Units, W.drop(columns="ln_Units")).fit(cov_type="cluster", cov_kwds={"groups": groups})
            for rv in rivals:
                if rv not in m.params:
                    continue
                b, se = m.params[rv], m.bse[rv]
                b2, se2 = m2.params.get(rv, np.nan), m2.bse.get(rv, np.nan)
                s1 = b * TAU_CROSS ** 2 / (TAU_CROSS ** 2 + se ** 2)
                s2 = b2 * TAU_CROSS ** 2 / (TAU_CROSS ** 2 + se2 ** 2) if pd.notna(b2) else np.nan
                ok = (s1 > 0) and (s2 > 0) and min(m.pvalues[rv], m2.pvalues.get(rv, 1)) < CROSS_P
                rows.append({"Cluster": name, "SKU_Quantity": i, "SKU_Price": rv[2:], "Cross_Raw": b, "Cross_SE": se,
                             "Cross_p": m.pvalues[rv], "Cross_Raw_WeekFE": b2, "Cross_p_WeekFE": m2.pvalues.get(rv),
                             "Cross_Shrunk": min(s1, s2) if ok else 0.0, "Own_Real_Price_Coef": m.params.get(own)})
    x = pd.DataFrame(rows)
    x["Substitute"] = x.Cross_Shrunk > 0
    x["Cross_Used"] = x.Cross_Shrunk.clip(lower=0)
    # weekly revenue level (last 52 weeks before the test period) for diversion ratios
    rev = (f[f.Week >= TEST_START - pd.Timedelta(weeks=52)].groupby("ArticleCode").Sales_KZ.sum() / 52)
    x["Rev_Q"], x["Rev_P"] = x.SKU_Quantity.map(rev), x.SKU_Price.map(rev)
    own_e = e.Elasticity_Final
    # diversion from the price-changing SKU (SKU_Price) to the rival (SKU_Quantity), in revenue terms
    x["Diversion"] = x.Cross_Used * x.Rev_Q / (own_e.reindex(x.SKU_Price).abs().values * x.Rev_P)
    tot = x.groupby("SKU_Price").Diversion.transform("sum")
    scale = np.where(tot > MAX_DIVERSION, MAX_DIVERSION / tot, 1.0)
    x["Diversion"] *= scale
    x["Cross_Used"] *= scale
    return x


def main():
    e = pd.read_parquet(CL / "pilot" / "sku_elasticity.parquet").set_index("ArticleCode")
    e = calibrate_rise(e)
    fa = load()
    f = fa[~fa.Clearance]
    x = cross_effects(e, f)
    name = e.ArticleName.str.title().str[:30]
    x.insert(1, "Name_Quantity", x.SKU_Quantity.map(name))
    x.insert(3, "Name_Price", x.SKU_Price.map(name))
    div = x.groupby("SKU_Price").Diversion.sum().rename("Diversion_Total")
    e = e.join(div)
    e["Diversion_Total"] = e.Diversion_Total.fillna(0)
    e["Elasticity_Category_Net"] = e.Elasticity_Final * (1 - e.Diversion_Total)    # net effect for Fresmart
    e.reset_index().to_parquet(CL / "pilot" / "sku_elasticity.parquet", index=False)
    x.to_parquet(CL / "pilot" / "cross_elasticity.parquet", index=False)

    rise = e.reset_index()[["Group", "ArticleCode", "ArticleName", "Elasticity_Final", "E_Rise_raw", "SE_Rise",
                            "Rise_Events", "Rise_Event_Median", "Rise_Combined_Reg_Events", "Rise_Shrunk", "Rise_Capped",
                            "Rise_Final_Old", "Rise_Final", "Cut_Final"]]
    clus = e.reset_index()[e.reset_index().Diversion_Total > 0][["Group", "ArticleCode", "ArticleName", "Elasticity_Final",
                                                                 "Diversion_Total", "Elasticity_Category_Net"]]
    with pd.ExcelWriter(OUT / "elasticity_final.xlsx", mode="a", engine="openpyxl", if_sheet_exists="replace") as xw:
        rise.round(3).to_excel(xw, sheet_name="Fix 1 Rise calibration", index=False)
        x.round(4).to_excel(xw, sheet_name="Fix 2 Cross elasticity", index=False)
        clus.round(3).to_excel(xw, sheet_name="Fix 2 Diversion summary", index=False)
        e.reset_index()[["Group", "ArticleCode", "ArticleName", "SubGroup", "Elasticity_Final", "CI_Low", "CI_High",
                         "Rise_Final", "Cut_Final", "Cut_Response_Reliable", "Diversion_Total", "Elasticity_Category_Net",
                         "Confidence_Final", "Use", "Bounded", "Weight_On_Data"]].round(3).to_excel(
            xw, sheet_name="Final elasticity", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 30)
    print(rise[["Group", "ArticleName", "Elasticity_Final", "E_Rise_raw", "Rise_Events", "Rise_Event_Median",
                "Rise_Final_Old", "Rise_Final", "Rise_Capped"]].round(2).to_string(index=False))
    print(x[["Cluster", "Name_Price", "Name_Quantity", "Cross_Raw", "Cross_p", "Cross_Used", "Diversion"]].round(3)
          .to_string(index=False))
    print(clus.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
