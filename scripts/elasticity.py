"""Price elasticity and drivers of sales on clean/weekly_model.parquet (In_Model_Sample rows).

Models (log quantity in base units on the left, standard errors clustered by article):
  M0  nominal price, article-location FE only        -> shows the inflation bias (what NOT to use)
  M1  CPI-deflated price, article-location + week FE
  M2  category-relative price, article-location + week FE           <- headline elasticity
  M3  M2 split into price above / below the article-location's usual level (asymmetry)
  M4  M2 by MainGroup, SubGroup, store class, zone, channel
  M5  drivers: real price + exchange rate + inflation + oil + GDP + holidays + payday + Christmas
      + month of year, article-location FE (SE clustered by week, macro varies by week only)
Per-article elasticities: two-way within (location, week) per article, shrunk to the SubGroup average.
Event study: clean step changes in relative price (>=5%, stable 4 weeks either side) and the volume response.

Outputs: analysis/elasticity_results.xlsx, analysis/article_elasticity.parquet, analysis/price_events.parquet
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pyfixest as pf

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean", ROOT / "analysis"
OUT.mkdir(exist_ok=True)
R = {}


def tidy(fit, name, extra=None):
    t = fit.tidy().reset_index().rename(columns={"Coefficient": "Term"})
    t.insert(0, "Model", name)
    t["N"] = fit._N
    if extra:
        for k, v in extra.items():
            t[k] = v
    return t


def load():
    cols = ["Week", "Plant", "ArticleCode", "ln_Qty", "ln_Relative_Price", "ln_Price_Real", "Realized_Price_KZ",
            "Qty_Clean", "Sales_KZ", "MainGroup", "SubGroup", "Store_Class", "Area_Zone", "Channel", "Holidays_In_Week",
            "Payday_Week", "Christmas_Season", "Month_Of_Year", "FX_BNA_Avg", "Inflation_YoY_Pct", "Brent_USD",
            "GDP_Real_YoY_Pct_Q", "In_Model_Sample", "ArticleName"]
    w = pd.read_parquet(CL / "weekly_model.parquet", columns=cols)
    w = w[w.In_Model_Sample].drop(columns="In_Model_Sample")
    w["AS"] = (w.Plant + "|" + w.ArticleCode).astype("category").cat.codes
    w["WK"] = w.Week.astype("category").cat.codes
    w["ART"] = w.ArticleCode.astype("category").cat.codes
    w["ln_Price_Nominal"] = np.log(w.Realized_Price_KZ)
    dev = w.ln_Relative_Price - w.groupby("AS").ln_Relative_Price.transform("mean")
    w["ln_Rel_Above"], w["ln_Rel_Below"] = dev.clip(lower=0), dev.clip(upper=0)
    w["ln_FX"] = np.log(w.FX_BNA_Avg)
    w["ln_Brent"] = np.log(w.Brent_USD)
    w["Payday_Week"] = w.Payday_Week.astype(int)
    w["Christmas_Season"] = w.Christmas_Season.astype(int)
    print(f"model rows {len(w):,}", flush=True)
    return w


def pooled(w):
    out = []
    v = {"CRV1": "ART"}
    out.append(tidy(pf.feols("ln_Qty ~ ln_Price_Nominal | AS", w, vcov=v), "M0 nominal price, no time control"))
    out.append(tidy(pf.feols("ln_Qty ~ ln_Price_Real | AS + WK", w, vcov=v), "M1 CPI-deflated price"))
    out.append(tidy(pf.feols("ln_Qty ~ ln_Relative_Price | AS + WK", w, vcov=v), "M2 relative price (headline)"))
    out.append(tidy(pf.feols("ln_Qty ~ ln_Rel_Above + ln_Rel_Below | AS + WK", w, vcov=v),
                    "M3 asymmetry: above vs below usual price"))
    print("pooled done", flush=True)
    return pd.concat(out)


def by_segment(w):
    out = []
    for seg in ["MainGroup", "Store_Class", "Area_Zone", "Channel", "SubGroup"]:
        for k, g in w.groupby(seg):
            if g.ART.nunique() < 5 or len(g) < 5000:
                continue
            try:
                fit = pf.feols("ln_Qty ~ ln_Relative_Price | AS + WK", g, vcov={"CRV1": "ART"})
            except Exception as e:  # singular / no variation
                print(f"  skip {seg}={k}: {e}"[:120])
                continue
            t = tidy(fit, f"M4 by {seg}", {"Segment": seg, "Value": k, "Articles": g.ArticleCode.nunique(),
                                          "Sales_KZ": g.Sales_KZ.sum()})
            out.append(t)
        print(f"segment {seg} done", flush=True)
    return pd.concat(out)


def drivers(w):
    f = ("ln_Qty ~ ln_Price_Real + ln_FX + Inflation_YoY_Pct + ln_Brent + GDP_Real_YoY_Pct_Q + Holidays_In_Week"
         " + Payday_Week + Christmas_Season + C(Month_Of_Year) | AS")
    fit = pf.feols(f, w.dropna(subset=["GDP_Real_YoY_Pct_Q"]), vcov={"CRV1": "WK"})
    print("drivers done", flush=True)
    return tidy(fit, "M5 drivers of sales")


def demean2(v, g1, g2, n1, n2, iters=30):
    v = v - v.mean()
    for _ in range(iters):
        v = v - (np.bincount(g1, v, n1) / np.bincount(g1, minlength=n1))[g1]
        v = v - (np.bincount(g2, v, n2) / np.bincount(g2, minlength=n2))[g2]
    return v


def per_article(w):
    rows = []
    for (art, sub, mg, name), g in w.groupby(["ArticleCode", "SubGroup", "MainGroup", "ArticleName"], observed=True):
        if len(g) < 40:
            continue
        g1 = g.Plant.astype("category").cat.codes.to_numpy()
        g2 = g.WK.astype("category").cat.codes.to_numpy()
        n1, n2 = int(g1.max()) + 1, int(g2.max()) + 1
        x = demean2(g.ln_Relative_Price.to_numpy(), g1, g2, n1, n2)
        y = demean2(g.ln_Qty.to_numpy(), g1, g2, n1, n2)
        sxx = (x * x).sum()
        if np.sqrt(sxx / len(g)) < 0.02:  # not enough price variation to measure
            continue
        b = (x * y).sum() / sxx
        e = y - b * x
        dof = max(len(g) - n1 - n2, 1)
        se = np.sqrt((x * x * e * e).sum() / sxx ** 2 * len(g) / dof)
        rows.append((art, name, mg, sub, len(g), n1, np.sqrt(sxx / len(g)), b, se, g.Sales_KZ.sum()))
    a = pd.DataFrame(rows, columns=["ArticleCode", "ArticleName", "MainGroup", "SubGroup", "Obs", "Locations",
                                    "Price_Variation_SD", "Elasticity_Raw", "SE", "Sales_KZ"])
    # empirical-Bayes shrinkage towards the sales-weighted SubGroup mean
    a["prec"] = 1 / a.SE.clip(lower=0.01) ** 2
    grp = a.groupby("SubGroup")
    a["Group_Mean"] = grp.apply(lambda d: np.average(d.Elasticity_Raw, weights=d.prec), include_groups=False) \
        .reindex(a.SubGroup).values
    tau2 = grp.apply(lambda d: max(np.var(d.Elasticity_Raw) - np.mean(d.SE ** 2), 0.05), include_groups=False) \
        .reindex(a.SubGroup).values
    wgt = tau2 / (tau2 + a.SE ** 2)
    a["Elasticity"] = wgt * a.Elasticity_Raw + (1 - wgt) * a.Group_Mean
    a["Shrink_Weight"] = wgt
    a["Class"] = pd.cut(a.Elasticity, [-np.inf, -2, -1, -0.3, 0, np.inf],
                        labels=["highly elastic (< -2)", "elastic (-2 to -1)", "moderate (-1 to -0.3)",
                                "inelastic (-0.3 to 0)", "positive (check)"])
    a = a.drop(columns="prec").sort_values("Sales_KZ", ascending=False)
    a.to_parquet(OUT / "article_elasticity.parquet", index=False)
    print(f"per-article: {len(a):,} articles", flush=True)
    return a


def events(w):
    w = w.sort_values(["AS", "Week"]).reset_index(drop=True)
    # volume relative to the same category in the same store and week
    w["ln_Qty_Adj"] = w.ln_Qty - w.groupby(["SubGroup", "Plant", "Week"]).ln_Qty.transform("mean")
    g = w.groupby("AS")
    pos, rpos = g.cumcount(), g.cumcount(ascending=False)
    k = 4
    # rolling windows on the whole sorted frame; rows whose window crosses into another article-location are masked
    span_before = (w.Week - w.Week.shift(k)).dt.days        # t-4 .. t
    span_after = (w.Week.shift(-(k - 1)) - w.Week).dt.days   # t .. t+3
    for col in ["ln_Relative_Price", "ln_Qty_Adj"]:
        w[f"{col}_b"] = w[col].shift(1).rolling(k).mean()
        w[f"{col}_a"] = w[col][::-1].rolling(k).mean()[::-1]
    w["sd_b"] = w.ln_Relative_Price.shift(1).rolling(k).std()
    w["sd_a"] = w.ln_Relative_Price[::-1].rolling(k).std()[::-1]
    w["dP"] = w.ln_Relative_Price_a - w.ln_Relative_Price_b
    ev = w[(pos >= k) & (rpos >= k - 1) & (span_before == 28) & (span_after == 21) & (w.dP.abs() >= 0.05)
           & (w.sd_b < 0.02) & (w.sd_a < 0.02)].copy()
    # one event per step: drop events within 8 weeks of an earlier one at the same article-location
    ev = ev[(ev.groupby("AS").Week.diff().dt.days.fillna(999) > 56)]
    ev["dQ"] = ev.ln_Qty_Adj_a - ev.ln_Qty_Adj_b
    ev["Direction"] = np.where(ev.dP > 0, "price rise", "price cut")
    ev["Size"] = pd.cut(ev.dP.abs(), [0.05, 0.10, 0.20, 0.50, 5], labels=["5-10%", "10-20%", "20-50%", ">50%"],
                        include_lowest=True)
    ev["Price_Change_%"] = (np.exp(ev.dP) - 1) * 100
    ev["Volume_Change_%"] = (np.exp(ev.dQ) - 1) * 100
    ev["Arc_Elasticity"] = ev.dQ / ev.dP
    keep = ["Week", "Plant", "ArticleCode", "ArticleName", "MainGroup", "SubGroup", "Direction", "Size",
            "Price_Change_%", "Volume_Change_%", "Arc_Elasticity"]
    ev[keep].to_parquet(OUT / "price_events.parquet", index=False)
    print(f"events: {len(ev):,}", flush=True)
    summ = ev.groupby(["Direction", "Size"], observed=True).agg(
        Events=("dQ", "size"), Median_Price_Change_pct=("Price_Change_%", "median"),
        Median_Volume_Change_pct=("Volume_Change_%", "median"), Mean_Volume_Change_pct=("Volume_Change_%", "mean"),
        Median_Arc_Elasticity=("Arc_Elasticity", "median"))
    by_mg = ev.groupby(["MainGroup", "Direction"]).agg(
        Events=("dQ", "size"), Median_Price_Change_pct=("Price_Change_%", "median"),
        Median_Volume_Change_pct=("Volume_Change_%", "median"),
        Median_Arc_Elasticity=("Arc_Elasticity", "median"))
    return summ.round(2), by_mg[by_mg.Events >= 30].round(2)


def main():
    w = load()

    def cached(name, fn):  # the pooled fixed-effects models are slow; reuse a finished run
        f = OUT / f"_cache_{name}.parquet"
        if f.exists():
            return pd.read_parquet(f)
        r = fn(w)
        r.to_parquet(f)
        return r

    R["Pooled models"] = cached("pooled", pooled)
    print(R["Pooled models"][["Model", "Term", "Estimate", "Std. Error", "N"]].to_string(index=False), flush=True)
    R["Drivers (M5)"] = cached("drivers", drivers)
    print(R["Drivers (M5)"][["Term", "Estimate", "Std. Error", "Pr(>|t|)"]].to_string(index=False), flush=True)
    R["By segment (M4)"] = cached("segments", by_segment)
    a = per_article(w)
    R["Article elasticity summary"] = a.groupby("Class", observed=True).agg(
        Articles=("ArticleCode", "size"), Sales_KZ=("Sales_KZ", "sum"))
    R["SubGroup from articles"] = a.groupby(["MainGroup", "SubGroup"]).apply(
        lambda d: pd.Series({"Articles": len(d), "Median_Elasticity": d.Elasticity.median(),
                             "Weighted_Elasticity": np.average(d.Elasticity, weights=d.Sales_KZ),
                             "Sales_KZ": d.Sales_KZ.sum()}), include_groups=False).sort_values("Sales_KZ",
                                                                                               ascending=False)
    R["Top 200 articles"] = a.head(200)
    R["Events summary"], R["Events by MainGroup"] = events(w)
    with pd.ExcelWriter(OUT / "elasticity_results.xlsx") as xw:
        for k, v in R.items():
            v.to_excel(xw, sheet_name=k[:31], index=not isinstance(v.index, pd.RangeIndex))
    seg = R["By segment (M4)"]
    print(seg[seg.Segment != "SubGroup"][["Segment", "Value", "Estimate", "Std. Error", "Articles"]]
          .round(3).to_string(index=False))
    print(R["Article elasticity summary"].to_string())
    print(R["Events summary"].to_string())


if __name__ == "__main__":
    main()
