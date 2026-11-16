"""Exploratory data analysis on the clean monthly panel. Writes analysis/eda_tables.xlsx and prints key numbers."""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL = ROOT / "clean"
OUT = ROOT / "analysis"
OUT.mkdir(exist_ok=True)

T = {}  # sheet name -> table


def main():
    p = pd.read_parquet(CL / "panel_monthly.parquet")
    p = p[p.Has_Sales]
    p["Year"] = p.Month.str[:4]
    macro = pd.read_parquet(CL / "macro_monthly.parquet")

    # 1. chain trend
    m = p.groupby("Month").agg(Sales_KZ=("Sales_KZ", "sum"), Sales_Real_KZ=("Sales_Real_KZ", "sum"),
                               Sales_USD=("Sales_USD", "sum"), Sales_KG=("Sales_KG", "sum"),
                               Locations=("Plant", "nunique"), Articles=("ArticleCode", "nunique"))
    m["Sales_Real_per_Location"] = m.Sales_Real_KZ / m.Locations
    T["01 Chain monthly"] = m

    # 2. like-for-like: stores selling in every month
    months = p.Month.nunique()
    lfl = p.groupby("Plant").Month.nunique()
    lfl = lfl[lfl == months].index
    l = p[p.Plant.isin(lfl)].groupby("Month").agg(Sales_Real_KZ=("Sales_Real_KZ", "sum"),
                                                  Qty_Base=("Gross_Qty_Base", "sum"), Sales_KG=("Sales_KG", "sum"))
    l["Locations"] = len(lfl)
    T["02 Like-for-like"] = l
    y = p.groupby("Year").agg(Sales_KZ=("Sales_KZ", "sum"), Sales_Real_KZ=("Sales_Real_KZ", "sum"),
                              Sales_USD=("Sales_USD", "sum"), Locations=("Plant", "nunique"),
                              Months=("Month", "nunique"))
    yl = p[p.Plant.isin(lfl)].groupby("Year").agg(LFL_Real_KZ=("Sales_Real_KZ", "sum"), LFL_KG=("Sales_KG", "sum"))
    y = y.join(yl)
    for c in ["Sales_KZ", "Sales_Real_KZ", "Sales_USD", "LFL_Real_KZ", "LFL_KG"]:
        y[c + "_per_month"] = y[c] / y.Months
    T["03 Yearly"] = y

    # 3. category mix
    cat = p.pivot_table(index="MainGroup", columns="Year", values="Sales_Real_KZ", aggfunc="sum")
    cat["Share_%"] = cat.sum(axis=1) / cat.sum(axis=1).sum() * 100
    T["04 MainGroup by year"] = cat.sort_values("Share_%", ascending=False)
    sub = p.groupby(["MainGroup", "SubGroup"]).agg(Sales_USD=("Sales_USD", "sum"), Articles=("ArticleCode", "nunique"))
    T["05 SubGroup"] = sub.sort_values("Sales_USD", ascending=False)

    # 4. concentration
    a = p.groupby("ArticleCode").Sales_USD.sum().sort_values(ascending=False)
    cum = a.cumsum() / a.sum()
    T["06 Concentration"] = pd.DataFrame({
        "Share_of_articles_%": [round((cum <= s).mean() * 100, 1) for s in [0.5, 0.8, 0.9, 0.95]]},
        index=["50% of sales", "80% of sales", "90% of sales", "95% of sales"])

    # 5. stores
    s = p.groupby(["Plant", "Store_Name", "Channel", "Area_Zone", "Store_Class", "Total_Sqm"], dropna=False).agg(
        Sales_USD=("Sales_USD", "sum"), Months=("Month", "nunique")).reset_index()
    s["USD_per_Month"] = s.Sales_USD / s.Months
    s["USD_per_Month_per_Sqm"] = s.USD_per_Month / s.Total_Sqm
    T["07 Stores"] = s.sort_values("USD_per_Month", ascending=False)
    T["08 Zone x Class"] = s.groupby(["Area_Zone", "Store_Class"]).agg(
        Stores=("Plant", "size"), USD_per_Month=("USD_per_Month", "mean"),
        USD_per_Month_per_Sqm=("USD_per_Month_per_Sqm", "mean"))
    T["09 Channel"] = p.groupby(["Channel", "Year"]).Sales_USD.sum().unstack()

    # 6. seasonality (like-for-like, real, index = 100 average month)
    l2 = l.copy()
    l2["Month_Of_Year"] = pd.PeriodIndex(l2.index, freq="M").month
    l2["Year"] = l2.index.str[:4]
    l2["idx"] = l2.Sales_Real_KZ / l2.groupby("Year").Sales_Real_KZ.transform("mean") * 100
    T["10 Seasonality"] = l2.groupby("Month_Of_Year").idx.mean().round(1).to_frame("Index_avg_month_100")

    # 7. price history: chain Laspeyres-style index from article-location relative changes (fixed mix)
    q = p[p.Realized_Price_KZ > 0][["Month", "Plant", "ArticleCode", "MainGroup", "Import",
                                    "Realized_Price_KZ", "Sales_KZ"]].sort_values(["Plant", "ArticleCode", "Month"])
    q["prev"] = q.groupby(["Plant", "ArticleCode"]).Realized_Price_KZ.shift(1)
    q["prev_m"] = q.groupby(["Plant", "ArticleCode"]).Month.shift(1)
    q = q[pd.PeriodIndex(q.prev_m.fillna("1900-01"), freq="M") + 1 == pd.PeriodIndex(q.Month, freq="M")]
    q["dlp"] = np.log(q.Realized_Price_KZ / q.prev).clip(-1, 1)
    q["wdlp"] = q.dlp * q.Sales_KZ

    def chain_index(df):
        g = df.groupby("Month")
        return np.exp((g.wdlp.sum() / g.Sales_KZ.sum()).cumsum()) * 100

    pi = pd.DataFrame({"Fresmart_Price_Index": chain_index(q)})
    for grp in ["POULTRY", "CATTLE", "DRY-COMMODITY", "BEVERAGES", "DAIRY PRODUCTS", "DRY DIVISION", "FNV"]:
        pi[grp] = chain_index(q[q.MainGroup == grp])
    for imp in q.Import.dropna().unique():
        pi[f"Import={imp}"] = chain_index(q[q.Import == imp])
    mac = macro.set_index("Month")
    pi["CPI"] = mac.CPI_Index / mac.CPI_Index.loc[pi.index[0]] * 100
    pi["FX_BNA"] = mac.FX_BNA_Avg / mac.FX_BNA_Avg.loc[pi.index[0]] * 100
    pi["FX_Internal"] = m.Sales_KZ / m.Sales_USD
    pi["FX_Internal"] = pi.FX_Internal / pi.FX_Internal.iloc[0] * 100
    T["11 Price index vs CPI FX"] = pi.round(1)

    # 8. price-change frequency (monthly, article-location)
    q["Change"] = pd.cut(q.dlp, [-1.01, -0.10, -0.03, 0.03, 0.10, 1.01],
                         labels=["cut >10%", "cut 3-10%", "stable (+/-3%)", "rise 3-10%", "rise >10%"])
    T["12 Price change freq"] = (q.groupby(["MainGroup", "Change"], observed=True).size().unstack()
                                 .pipe(lambda x: x.div(x.sum(axis=1), axis=0) * 100).round(1))
    T["13 Price change by year"] = (q.assign(Year=q.Month.str[:4]).groupby(["Year", "Change"], observed=True).size()
                                    .unstack().pipe(lambda x: x.div(x.sum(axis=1), axis=0) * 100).round(1))

    # 9. stock-outs (Jun 2024+)
    st = pd.read_parquet(CL / "panel_monthly.parquet", columns=[
        "Month", "Plant", "ArticleCode", "MainGroup", "Has_Stock_Record", "Out_Of_Stock", "Days_Of_Cover", "Has_Sales"])
    st = st[st.Has_Stock_Record]
    T["14 Stock-outs"] = st.groupby("MainGroup").agg(
        Rows=("Out_Of_Stock", "size"), Out_Of_Stock_pct=("Out_Of_Stock", lambda x: x.mean() * 100),
        Median_Days_Cover=("Days_Of_Cover", "median")).sort_values("Rows", ascending=False).round(1)

    # 10. macro vs like-for-like real sales and volume
    mm = l.join(mac[["FX_BNA_Avg", "Inflation_YoY_Pct", "Brent_USD", "GDP_Real_YoY_Pct_Q"]])
    mm["Real_Sales_YoY_%"] = mm.Sales_Real_KZ.pct_change(12, fill_method=None) * 100
    mm["KG_YoY_%"] = mm.Sales_KG.pct_change(12, fill_method=None) * 100
    mm["FX_YoY_%"] = mm.FX_BNA_Avg.pct_change(12, fill_method=None) * 100
    T["15 Macro vs LFL"] = mm
    T["16 Macro correlations"] = mm[["Real_Sales_YoY_%", "KG_YoY_%", "FX_YoY_%", "Inflation_YoY_Pct", "Brent_USD",
                                     "GDP_Real_YoY_Pct_Q"]].dropna().corr().round(2)

    with pd.ExcelWriter(OUT / "eda_tables.xlsx") as xw:
        for k, v in T.items():
            v.to_excel(xw, sheet_name=k[:31])
    for k in ["03 Yearly", "06 Concentration", "09 Channel", "10 Seasonality", "13 Price change by year",
              "14 Stock-outs", "16 Macro correlations"]:
        print(f"\n== {k}\n{T[k].round(1).to_string()}")
    print("\n== Price index (every 6 months)\n", T["11 Price index vs CPI FX"].iloc[::6].to_string())
    print("\n== Price change freq\n", T["12 Price change freq"].to_string())
    print("\nLFL locations:", len(lfl))


if __name__ == "__main__":
    main()
