"""Deeper relationship analysis for the PDF report. Writes tables to analysis/deep/*.parquet.

  A  stock x price      price moves by stock cover; elasticity by stock cover
  B  price x macro      category price pass-through from FX / Brent / CPI (lags 0-6 months); volume vs macro
  C  location           store price premium vs chain; zone x category elasticity; per-store elasticity
  D  time               day-of-month and weekday patterns; category x year volume growth; elasticity by year
  E  price structure    elasticity by price tier and import vs local; price dispersion across stores
  F  margin x elasticity by sub-category
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pyfixest as pf

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean", ROOT / "analysis" / "deep"
OUT.mkdir(parents=True, exist_ok=True)
TOP_GROUPS = ["POULTRY", "DRY-COMMODITY", "CATTLE", "BEVERAGES", "DAIRY PRODUCTS", "DRY DIVISION", "FNV",
              "CHARCUTARIA", "PERSONAL CARE", "HOUSEHOLD"]


def save(df, name):
    df = df.copy()
    df.columns = df.columns.astype(str) if isinstance(df.columns.dtype, pd.CategoricalDtype) else df.columns
    if isinstance(df.index.dtype, pd.CategoricalDtype):
        df.index = df.index.astype(str)
    df.to_parquet(OUT / f"{name}.parquet")
    print(f"  saved {name} ({len(df)} rows)", flush=True)


def m2(g, min_rows=3000):
    if len(g) < min_rows or g.ArticleCode.nunique() < 5:
        return None
    try:
        f = pf.feols("ln_Qty ~ ln_Relative_Price | AS + WK", g, vcov={"CRV1": "ArticleCode"})
        t = f.tidy().iloc[0]
        return {"Elasticity": t["Estimate"], "SE": t["Std. Error"], "Obs": f._N, "Articles": g.ArticleCode.nunique()}
    except Exception:
        return None


def load_weekly():
    w = pd.read_parquet(CL / "weekly_model.parquet", columns=[
        "Week", "Month", "Plant", "ArticleCode", "ln_Qty", "ln_Relative_Price", "Price_Real_KZ", "Days_Of_Cover",
        "MainGroup", "SubGroup", "Area_Zone", "Store_Class", "Store_Name", "Sales_KZ", "In_Model_Sample"])
    w = w[w.In_Model_Sample].drop(columns="In_Model_Sample")
    w["AS"] = (w.Plant + "|" + w.ArticleCode).astype("category").cat.codes
    w["WK"] = w.Week.astype("category").cat.codes
    art = pd.read_parquet(CL / "dim_article.parquet", columns=["ArticleCode", "PurchaseType", "BaseUOM"])
    w = w.merge(art, on="ArticleCode", how="left")
    print(f"weekly rows {len(w):,}", flush=True)
    return w


def elasticity_splits(w):
    rows = []

    def add(dim, key, g):
        r = m2(g)
        if r:
            rows.append({"Dimension": dim, "Value": key, **r})

    w["Year"] = w.Week.dt.year
    for k, g in w.groupby("Year"):
        add("Year", str(k), g)
    cov = w[w.Days_Of_Cover.notna() & np.isfinite(w.Days_Of_Cover)]
    cov = cov.assign(Cover=pd.cut(cov.Days_Of_Cover, [-0.1, 7, 14, 30, 60, np.inf],
                                  labels=["<1 week", "1-2 weeks", "2-4 weeks", "1-2 months", ">2 months"]))
    for k, g in cov.groupby("Cover", observed=True):
        add("Stock cover", str(k), g)
    # price tier: article's median real price within sub-category x base unit
    med = w.groupby(["SubGroup", "BaseUOM", "ArticleCode"]).Price_Real_KZ.median().rename("p").reset_index()
    med["Tier"] = med.groupby(["SubGroup", "BaseUOM"]).p.transform(
        lambda s: pd.qcut(s.rank(method="first"), 3, labels=["Economy", "Mid", "Premium"]) if len(s) >= 3 else np.nan)
    w2 = w.merge(med[["ArticleCode", "Tier"]].drop_duplicates("ArticleCode"), on="ArticleCode", how="left")
    for k, g in w2.groupby("Tier", observed=True):
        add("Price tier", str(k), g)
    for k, g in w.groupby("PurchaseType"):
        add("Sourcing", str(k), g)
    print("splits done", flush=True)
    save(pd.DataFrame(rows), "elasticity_splits")

    zrows = []
    for (z, mg), g in w[w.MainGroup.isin(TOP_GROUPS)].groupby(["Area_Zone", "MainGroup"]):
        r = m2(g, 2000)
        if r:
            zrows.append({"Area_Zone": z, "MainGroup": mg, **r})
    print("zone x group done", flush=True)
    save(pd.DataFrame(zrows), "elasticity_zone_group")

    srows = []
    for (p, n, z, c), g in w.groupby(["Plant", "Store_Name", "Area_Zone", "Store_Class"]):
        r = m2(g, 5000)
        if r:
            srows.append({"Plant": p, "Store_Name": n, "Area_Zone": z, "Store_Class": c, **r,
                          "Sales_KZ": g.Sales_KZ.sum()})
    print("per store done", flush=True)
    save(pd.DataFrame(srows), "elasticity_store")


def monthly_panel():
    p = pd.read_parquet(CL / "panel_monthly.parquet", columns=[
        "Month", "Plant", "ArticleCode", "MainGroup", "SubGroup", "Area_Zone", "Store_Class", "Store_Name", "Channel",
        "Total_Sqm", "Has_Sales", "Realized_Price_KZ", "Sales_KZ", "Sales_Real_KZ", "Sales_KG", "Gross_Qty_Base",
        "Days_Of_Cover", "Out_Of_Stock", "Has_Stock_Record", "Margin_Pct_Est", "Gross_Sales_USD", "Relative_Price",
        "Margin_Pct_COGS", "KZ_NetsSales", "KZ_COGS"])
    return p


def stock_price(p):
    s = p[p.Has_Stock_Record & p.Has_Sales & p.Realized_Price_KZ.gt(0)].sort_values(["Plant", "ArticleCode", "Month"])
    g = s.groupby(["Plant", "ArticleCode"])
    s["next_rel"] = g.Relative_Price.shift(-1)
    s["next_m"] = g.Month.shift(-1)
    s = s[pd.PeriodIndex(s.next_m.fillna("1900-01"), freq="M") == pd.PeriodIndex(s.Month, freq="M") + 1]
    s["dRel"] = np.log(s.next_rel / s.Relative_Price)
    s["Cover"] = pd.cut(s.Days_Of_Cover, [-0.1, 7, 14, 30, 60, 120, np.inf],
                        labels=["<1 wk", "1-2 wk", "2-4 wk", "1-2 mo", "2-4 mo", ">4 mo"])
    s["Next move"] = pd.cut(s.dRel, [-9, -0.10, -0.03, 0.03, 0.10, 9],
                            labels=["cut >10%", "cut 3-10%", "stable", "rise 3-10%", "rise >10%"])
    h = s.groupby(["Cover", "Next move"], observed=True).size().unstack()
    save(h.div(h.sum(axis=1), axis=0) * 100, "stock_cover_vs_next_price")
    # stock-outs by relative price level
    s2 = p[p.Has_Stock_Record & p.Relative_Price.notna()].copy()
    s2["RelBand"] = pd.cut(s2.Relative_Price, [0, 0.85, 0.95, 1.05, 1.15, 99],
                           labels=["<0.85", "0.85-0.95", "0.95-1.05", "1.05-1.15", ">1.15"])
    nxt = p[p.Has_Stock_Record][["Plant", "ArticleCode", "Month", "Out_Of_Stock"]].copy()
    nxt["Month"] = (pd.PeriodIndex(nxt.Month, freq="M") - 1).astype(str)
    s2 = s2.merge(nxt.rename(columns={"Out_Of_Stock": "OOS_next"}), on=["Plant", "ArticleCode", "Month"], how="left")
    save(s2.groupby(["MainGroup", "RelBand"], observed=True).OOS_next.mean().unstack().mul(100)
         .loc[lambda d: d.index.isin(TOP_GROUPS)], "oos_next_by_relprice")
    print("stock x price done", flush=True)


def category_index(p):
    q = p[p.Has_Sales & p.Realized_Price_KZ.gt(0)][["Month", "Plant", "ArticleCode", "MainGroup",
                                                    "Realized_Price_KZ", "Sales_KZ"]]
    q = q.sort_values(["Plant", "ArticleCode", "Month"])
    g = q.groupby(["Plant", "ArticleCode"])
    q["prev"], q["prev_m"] = g.Realized_Price_KZ.shift(1), g.Month.shift(1)
    q = q[pd.PeriodIndex(q.prev_m.fillna("1900-01"), freq="M") + 1 == pd.PeriodIndex(q.Month, freq="M")]
    q["dlp"] = np.log(q.Realized_Price_KZ / q.prev).clip(-1, 1)
    q["w"] = q.Sales_KZ.clip(lower=0)
    q["wd"] = q.dlp * q.w
    d = q.groupby(["MainGroup", "Month"])[["wd", "w"]].sum()
    d = (d.wd / d.w).unstack(0)
    tot = q.groupby("Month")[["wd", "w"]].sum()
    d["ALL"] = tot.wd / tot.w
    return d  # monthly log price change by group


def macro_passthrough(p):
    dl = category_index(p)
    mac = pd.read_parquet(CL / "macro_monthly.parquet").set_index("Month")
    x = pd.DataFrame({"FX": np.log(mac.FX_BNA_Avg).diff(), "Brent": np.log(mac.Brent_USD).diff(),
                      "CPI": np.log(mac.CPI_Index).diff()})
    rows = []
    for driver in ["FX", "Brent", "CPI"]:
        lags = pd.concat({f"L{k}": x[driver].shift(k) for k in range(7)}, axis=1)
        for grp in ["ALL"] + TOP_GROUPS:
            y = dl[grp].rename("y")
            dd = pd.concat([y, lags], axis=1).dropna()
            if len(dd) < 20:
                continue
            X = np.column_stack([np.ones(len(dd)), dd[lags.columns].to_numpy()])
            beta = np.linalg.lstsq(X, dd.y.to_numpy(), rcond=None)[0]
            cum = np.cumsum(beta[1:])
            for k in range(7):
                rows.append({"Driver": driver, "Group": grp, "Lag": k, "Cumulative_PassThrough": cum[k]})
    save(pd.DataFrame(rows), "passthrough")
    idx = np.exp(dl.cumsum()) * 100
    save(idx, "category_price_index")
    # volume (LFL) by group x year
    lfl_pl = p[p.Has_Sales].groupby("Plant").Month.nunique()
    lfl_pl = lfl_pl[lfl_pl == p.Month.nunique()].index
    v = p[p.Has_Sales & p.Plant.isin(lfl_pl) & p.MainGroup.isin(TOP_GROUPS)].assign(Year=lambda d: d.Month.str[:4])
    v = v[v.Month.str[5:7] <= "09"]  # Jan-Sep of every year, comparable with 2026
    vy = v.groupby(["MainGroup", "Year"]).agg(KG=("Sales_KG", "sum"), Real=("Sales_Real_KZ", "sum")).unstack()
    save(vy, "group_year_volume")
    # LFL monthly volume vs macro
    lm = p[p.Has_Sales & p.Plant.isin(lfl_pl)].groupby("Month").agg(KG=("Sales_KG", "sum"),
                                                                       Real=("Sales_Real_KZ", "sum"))
    lm = lm.join(mac[["FX_BNA_Avg", "Inflation_YoY_Pct", "Brent_USD", "GDP_Real_YoY_Pct_Q", "CPI_Index"]])
    save(lm, "lfl_monthly_macro")
    print("macro done", flush=True)


def location(p):
    q = p[p.Has_Sales & p.Realized_Price_KZ.gt(0) & p.Channel.eq("STORE")]
    chain = q.groupby(["ArticleCode", "Month"]).Realized_Price_KZ.transform("median")
    q = q.assign(Premium=np.log(q.Realized_Price_KZ / chain))
    q = q[q.Premium.abs() < 0.7]
    wavg = lambda d: np.average(d.Premium, weights=d.Sales_KZ.clip(lower=1))
    st = q.groupby(["Plant", "Store_Name", "Area_Zone", "Store_Class", "Total_Sqm"]).apply(wavg, include_groups=False)
    st = (np.exp(st) - 1).mul(100).rename("Price_Premium_pct").reset_index()
    perf = p[p.Has_Sales].groupby("Plant").agg(Sales_USD=("Gross_Sales_USD", "sum"), Months=("Month", "nunique"))
    st = st.merge(perf, on="Plant")
    st["USD_per_Month"] = st.Sales_USD / st.Months
    st["USD_per_Sqm_Month"] = st.USD_per_Month / st.Total_Sqm
    save(st, "store_price_premium")
    zg = q[q.MainGroup.isin(TOP_GROUPS)].groupby(["Area_Zone", "MainGroup"]).apply(wavg, include_groups=False)
    save((np.exp(zg) - 1).mul(100).unstack(), "zone_group_premium")
    disp = q.groupby(["MainGroup", "ArticleCode", "Month"]).Premium.std().groupby("MainGroup").median()
    save(disp.mul(100).rename("Median_CV_pct").to_frame(), "price_dispersion")
    # category mix by zone
    mix = p[p.Has_Sales & p.MainGroup.isin(TOP_GROUPS)].pivot_table(index="Area_Zone", columns="MainGroup",
                                                                    values="Gross_Sales_USD", aggfunc="sum")
    save(mix.div(mix.sum(axis=1), axis=0) * 100, "zone_category_mix")
    print("location done", flush=True)


def calendar_patterns():
    art = pd.read_parquet(CL / "dim_article.parquet", columns=["ArticleCode", "MainGroup"])
    cpi = pd.read_parquet(CL / "macro_monthly.parquet", columns=["Month", "CPI_Rebased_Jan2023"])
    parts = []
    for f in sorted((CL / "sales_daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["Date", "ArticleCode", "Sales_KZ", "Is_Return"])
        d = d[~d.Is_Return].merge(art, on="ArticleCode", how="left")
        parts.append(d.groupby(["Date", "MainGroup"]).Sales_KZ.sum())
    d = pd.concat(parts).reset_index()
    d["Month"] = d.Date.dt.to_period("M").astype(str)
    d = d.merge(cpi, on="Month", how="left")
    d["Real"] = d.Sales_KZ / d.CPI_Rebased_Jan2023.ffill() * 100
    tot = d.groupby("Date").Real.sum().to_frame()
    tot["Month"] = tot.index.to_period("M")
    tot["idx"] = tot.Real / tot.groupby("Month").Real.transform("mean") * 100
    tot["Day"] = tot.index.day
    tot["Weekday"] = tot.index.dayofweek
    save(tot.groupby("Day").idx.agg(["mean", "std", "size"]), "day_of_month")
    d = d[d.MainGroup.isin(TOP_GROUPS)]
    d["Week"] = d.Date.dt.to_period("W")
    d["idx"] = d.Real / d.groupby(["MainGroup", "Week"]).Real.transform("mean") * 100
    d["Weekday"] = d.Date.dt.dayofweek
    save(d.groupby(["MainGroup", "Weekday"]).idx.mean().unstack(), "weekday_by_group")
    mm = d.groupby(["Month", "MainGroup"]).Real.sum().unstack()
    save(mm, "group_month_real")
    print("calendar done", flush=True)


def margin_vs_elasticity(p):
    a = pd.read_parquet(ROOT / "analysis" / "article_elasticity.parquet")
    sub = a.groupby(["MainGroup", "SubGroup"]).apply(
        lambda d: pd.Series({"Elasticity": np.average(d.Elasticity, weights=d.Sales_KZ), "Articles": len(d),
                             "Sales_KZ": d.Sales_KZ.sum()}), include_groups=False)
    # actual COGS margin (net sales - COGS) / net sales, all months; stock-value estimate kept for comparison
    m = p[p.KZ_NetsSales.gt(0)]
    mg = m.groupby(["MainGroup", "SubGroup"])[["KZ_NetsSales", "KZ_COGS"]].sum()
    mg["Margin_pct"] = (1 - mg.KZ_COGS / mg.KZ_NetsSales) * 100
    e = p[p.Margin_Pct_Est.between(-50, 90) & p.Gross_Sales_USD.gt(0)]
    mg["Margin_pct_stock_est"] = e.groupby(["MainGroup", "SubGroup"]).apply(
        lambda d: np.average(d.Margin_Pct_Est, weights=d.Gross_Sales_USD), include_groups=False)
    save(sub.join(mg[["Margin_pct", "Margin_pct_stock_est"]]).reset_index(), "margin_vs_elasticity")


def main():
    p = monthly_panel()
    stock_price(p)
    macro_passthrough(p)
    location(p)
    margin_vs_elasticity(p)
    del p
    calendar_patterns()
    elasticity_splits(load_weekly())


if __name__ == "__main__":
    main()
