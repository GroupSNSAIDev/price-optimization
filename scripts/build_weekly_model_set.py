"""Build the weekly modelling dataset for price-elasticity analysis.

Source: clean/sales_daily (cleaned daily sales), clean/panel_monthly (stock, location, article, macro).

Grain: week (Monday start) x location x article.
Cost:  actual COGS from the sales lines; unit cost per base unit from days without a cost outlier;
       Margin_Pct = (net sales - COGS) / net sales.
Price: realized price per base unit from non-return, non-outlier days;
       CPI-deflated (Price_Real_KZ) and category-relative (Relative_Price, leave-one-out SubGroup index).

In_Model_Sample excludes:
  - weeks in a month where the article was out of stock at the location (sales limited by supply, not price)
  - weeks with unusually few selling days for that article-location (likely partial stock-out)
  - the first 13 weeks after a location opened (ramp-up)
  - the first and last (partial) weeks of the data
  - article-locations with fewer than MIN_WEEKS usable weeks

Outputs: clean/weekly_model.parquet, clean/calendar_weekly.parquet
"""
from pathlib import Path

import numpy as np
import pandas as pd

from add_price_indices import MIN_PEERS, leave_one_out_index

ROOT = Path(__file__).resolve().parents[1]
CL = ROOT / "clean"
MIN_WEEKS = 20

# Angola public holidays 2023-2026 (national, incl. Carnival and Good Friday)
HOLIDAYS = pd.to_datetime([
    *[f"{y}-01-01" for y in range(2023, 2027)], *[f"{y}-02-04" for y in range(2023, 2027)],
    *[f"{y}-03-08" for y in range(2023, 2027)], *[f"{y}-03-23" for y in range(2023, 2027)],
    *[f"{y}-04-04" for y in range(2023, 2027)], *[f"{y}-05-01" for y in range(2023, 2027)],
    *[f"{y}-09-17" for y in range(2023, 2027)], *[f"{y}-11-02" for y in range(2023, 2027)],
    *[f"{y}-11-11" for y in range(2023, 2027)], *[f"{y}-12-25" for y in range(2023, 2027)],
    "2023-02-21", "2024-02-13", "2025-03-04", "2026-02-17",   # Carnival
    "2023-04-07", "2024-03-29", "2025-04-18", "2026-04-03",   # Good Friday
])


def calendar(weeks):
    c = pd.DataFrame({"Week": weeks})
    days = c.Week.apply(lambda w: pd.date_range(w, periods=7))
    c["Holidays_In_Week"] = days.apply(lambda d: d.isin(HOLIDAYS).sum())
    c["Payday_Week"] = days.apply(lambda d: bool(((d.day >= 25) | (d.day <= 3)).any()))
    c["Month"] = (c.Week + pd.Timedelta(days=3)).dt.to_period("M").astype(str)   # month of the week's Thursday
    c["Week_Of_Year"] = c.Week.dt.isocalendar().week.astype(int)
    c["Month_Of_Year"] = (c.Week + pd.Timedelta(days=3)).dt.month
    c["Christmas_Season"] = c.Month_Of_Year.eq(12) & (c.Week + pd.Timedelta(days=3)).dt.day.ge(8)
    return c


def weekly_sales():
    parts = []
    for f in sorted((CL / "sales_daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["Date", "Plant", "ArticleCode", "Qty_Base", "Sales_KZ", "Sales_USD",
                                        "Txn_Count", "Is_Return", "Price_Outlier", "KZ_COGS", "KZ_NetsSales",
                                        "KZ_Discount", "Cost_Outlier", "Below_Cost_50"])
        d = d[~d.Is_Return & (d.Qty_Base > 0) & (d.Sales_KZ > 0)]
        d["Week"] = d.Date - pd.to_timedelta(d.Date.dt.weekday, unit="D")
        d["Clean_Day"] = ~d.Price_Outlier
        d["Qty_Clean"] = d.Qty_Base.where(d.Clean_Day, 0)
        d["KZ_Clean"] = d.Sales_KZ.where(d.Clean_Day, 0)
        cost_ok = ~d.Cost_Outlier & d.KZ_COGS.gt(0)
        d["Qty_Cost"] = d.Qty_Base.where(cost_ok, 0)
        d["COGS_Clean"] = d.KZ_COGS.where(cost_ok, 0)
        d["Qty_Below_Cost"] = d.Qty_Base.where(d.Below_Cost_50, 0)
        g = d.groupby(["Week", "Plant", "ArticleCode"]).agg(
            Qty_Base=("Qty_Base", "sum"), Sales_KZ=("Sales_KZ", "sum"), Sales_USD=("Sales_USD", "sum"),
            Txn_Count=("Txn_Count", "sum"), Days_Sold=("Date", "nunique"), Outlier_Days=("Price_Outlier", "sum"),
            Qty_Clean=("Qty_Clean", "sum"), KZ_Clean=("KZ_Clean", "sum"), KZ_COGS=("KZ_COGS", "sum"),
            KZ_NetsSales=("KZ_NetsSales", "sum"), KZ_Discount=("KZ_Discount", "sum"), Qty_Cost=("Qty_Cost", "sum"),
            COGS_Clean=("COGS_Clean", "sum"), Qty_Below_Cost=("Qty_Below_Cost", "sum"))
        parts.append(g)
        print(f"  {f.stem}", flush=True)
    w = pd.concat(parts).groupby(level=[0, 1, 2]).sum().reset_index()  # weeks spanning two month files
    w["Realized_Price_KZ"] = (w.KZ_Clean / w.Qty_Clean).where(w.Qty_Clean > 0)
    w["Unit_COGS_KZ"] = (w.COGS_Clean / w.Qty_Cost).where(w.Qty_Cost > 0)
    w["Margin_Pct"] = (1 - w.KZ_COGS / w.KZ_NetsSales) * 100
    w["Below_Cost_Week"] = w.Qty_Below_Cost > 0.5 * w.Qty_Base   # flagged only, kept in the sample
    w = w.drop(columns=["Qty_Cost", "COGS_Clean", "Qty_Below_Cost"])
    return w


def main():
    print("Weekly sales ...", flush=True)
    w = weekly_sales()
    cal = calendar(np.sort(w.Week.unique()))
    cal.to_parquet(CL / "calendar_weekly.parquet", index=False)
    w = w.merge(cal, on="Week", how="left")

    print("Linking stock, location, article, macro ...", flush=True)
    panel = pd.read_parquet(CL / "panel_monthly.parquet", columns=[
        "Month", "Plant", "ArticleCode", "Out_Of_Stock", "Has_Stock_Record", "Closing_Qty_Base", "Days_Of_Cover",
        "Unit_Cost_USD", "CPI_Deflator", "FX_BNA_Avg", "FX_Internal", "Inflation_YoY_Pct", "Inflation_MoM_Pct",
        "Brent_USD", "GDP_Real_YoY_Pct_Q"])
    macro = panel.drop_duplicates("Month")[["Month", "CPI_Deflator", "FX_BNA_Avg", "Inflation_YoY_Pct",
                                            "Inflation_MoM_Pct", "Brent_USD", "GDP_Real_YoY_Pct_Q"]]
    w = w.merge(panel[["Month", "Plant", "ArticleCode", "Out_Of_Stock", "Has_Stock_Record", "Days_Of_Cover",
                       "Unit_Cost_USD"]], on=["Month", "Plant", "ArticleCode"], how="left")
    w = w.merge(macro, on="Month", how="left")
    loc = pd.read_parquet(CL / "dim_location.parquet")[
        ["Plant", "Store_Name", "Channel", "Area_Zone", "Store_Class", "Total_Sqm", "Open_Date"]]
    art = pd.read_parquet(CL / "dim_article.parquet")[
        ["ArticleCode", "ArticleName", "MainGroup", "SubGroup", "Category", "BRAND_DESCR", "Import", "IsFrozen",
         "Inclusion"]]
    w = w.merge(loc, on="Plant", how="left").merge(art, on="ArticleCode", how="left")

    print("Prices ...", flush=True)
    w["Price_Real_KZ"] = w.Realized_Price_KZ / w.CPI_Deflator * 100
    w["Unit_COGS_Real_KZ"] = w.Unit_COGS_KZ / w.CPI_Deflator * 100
    w["Markup_Pct"] = (w.Realized_Price_KZ / w.Unit_COGS_KZ - 1) * 100
    ok = w.Realized_Price_KZ.gt(0) & w.SubGroup.notna()
    d = w.loc[ok, ["Week", "Plant", "ArticleCode", "SubGroup", "Realized_Price_KZ", "KZ_Clean"]].copy()
    lp = np.log(d.Realized_Price_KZ)
    d["lr"] = lp - lp.groupby([d.Plant, d.ArticleCode]).transform("mean")
    d["w"], d["wlr"] = d.KZ_Clean, d.KZ_Clean * d.lr
    s_idx, s_n = leave_one_out_index(d, ["SubGroup", "Plant", "Week"])
    c_idx, c_n = leave_one_out_index(d, ["SubGroup", "Week"])
    use_store = s_n >= MIN_PEERS
    w.loc[ok, "Category_Price_Index"] = np.where(use_store, s_idx, c_idx)
    w.loc[ok, "Relative_Price"] = np.exp(d.lr) / w.loc[ok, "Category_Price_Index"]
    w["ln_Qty"] = np.log(w.Qty_Clean.where(w.Qty_Clean > 0))
    w["ln_Price_Real"] = np.log(w.Price_Real_KZ)
    w["ln_Relative_Price"] = np.log(w.Relative_Price)

    print("Sample filters ...", flush=True)
    med_days = w.groupby(["Plant", "ArticleCode"]).Days_Sold.transform("median")
    w["Low_Availability"] = w.Days_Sold < 0.5 * med_days
    w["Stockout_Month"] = w.Out_Of_Stock.fillna(False).astype(bool)
    w["Store_Ramp_Up"] = w.Week < (w.Open_Date + pd.Timedelta(weeks=13))
    w["Partial_Week"] = w.Week.isin([w.Week.min(), w.Week.max()])
    base = (w.ln_Qty.notna() & w.ln_Relative_Price.notna() & ~w.Low_Availability & ~w.Stockout_Month
            & ~w.Store_Ramp_Up & ~w.Partial_Week)
    n_weeks = base.groupby([w.Plant, w.ArticleCode]).transform("sum")
    w["Too_Few_Weeks"] = n_weeks < MIN_WEEKS
    w["In_Model_Sample"] = base & ~w.Too_Few_Weeks
    w = w.drop(columns=["KZ_Clean"])
    w.to_parquet(CL / "weekly_model.parquet", index=False)

    rep = pd.DataFrame([
        ("Weekly rows (week x location x article with sales)", len(w)),
        ("  dropped: stock-out month", int(w.Stockout_Month.sum())),
        ("  dropped: low availability week", int(w.Low_Availability.sum())),
        ("  dropped: store ramp-up (first 13 weeks)", int(w.Store_Ramp_Up.sum())),
        ("  dropped: partial first/last week", int(w.Partial_Week.sum())),
        (f"  dropped: article-location with < {MIN_WEEKS} usable weeks", int((base & w.Too_Few_Weeks).sum())),
        ("In model sample", int(w.In_Model_Sample.sum())),
        ("  locations", w.loc[w.In_Model_Sample, "Plant"].nunique()),
        ("  articles", w.loc[w.In_Model_Sample, "ArticleCode"].nunique()),
        ("  article-locations", w.loc[w.In_Model_Sample, ["Plant", "ArticleCode"]].drop_duplicates().shape[0]),
        ("  below-cost weeks in sample (flagged, kept)", int((w.In_Model_Sample & w.Below_Cost_Week).sum())),
        ("  gross margin % in sample", round((1 - w.loc[w.In_Model_Sample, "KZ_COGS"].sum()
                                              / w.loc[w.In_Model_Sample, "KZ_NetsSales"].sum()) * 100, 1)),
        ("  share of sales KZ", round(w.loc[w.In_Model_Sample, "Sales_KZ"].sum() / w.Sales_KZ.sum() * 100, 1)),
    ], columns=["Step", "Rows"])
    print(rep.to_string(index=False))
    rep.to_csv(CL / "weekly_model_sample_report.csv", index=False)


if __name__ == "__main__":
    main()
