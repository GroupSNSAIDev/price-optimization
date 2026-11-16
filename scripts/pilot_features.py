"""Step 5 · Feature engineering for the 40 pilot SKUs -> clean/pilot/pilot_features.parquet

Grain: store x SKU x week (weeks with sales, from clean/weekly_model.parquet, model-sample filters applied:
no stock-out months, low-availability weeks, store ramp-up or partial weeks).
Target: ln_Units = log(units sold in base unit).
Only information known at the start of the week is used for history features (lags, rolling means), so the
features can be used for forecasting without leakage. Price is a decision variable and is used as-is.
Split (architecture slide 11): train Jan 2023 - Mar 2026, validate Apr - Jun 2026, test Jul - Sep 2026.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL = ROOT / "clean"
OUT = CL / "pilot"
OUT.mkdir(exist_ok=True)
VALID_START, TEST_START = pd.Timestamp("2026-03-30"), pd.Timestamp("2026-06-29")


def load():
    sk = pd.read_parquet(ROOT / "analysis" / "rda" / "sku_shortlist.parquet")
    sk["ArticleCode"] = sk.ArticleCode.str.zfill(18)
    sk["Pilot_Group"] = sk.Group.str[0]
    w = pd.read_parquet(CL / "weekly_model.parquet")
    subgroups = w[w.ArticleCode.isin(sk.ArticleCode)].SubGroup.unique()
    cat = w[w.SubGroup.isin(subgroups)]                         # for category-demand features
    w = w[w.ArticleCode.isin(sk.ArticleCode)].merge(sk[["ArticleCode", "Pilot_Group"]], on="ArticleCode")
    art = pd.read_parquet(CL / "dim_article.parquet", columns=["ArticleCode", "PurchaseType"])
    return w.merge(art, on="ArticleCode", how="left"), cat


def category_demand(cat):
    """real sales of the sub-category in the store-week, and of the SKU itself (to leave it out)"""
    cat = cat.assign(Real=cat.Sales_KZ / cat.CPI_Deflator * 100)
    return cat.groupby(["SubGroup", "Plant", "Week"]).Real.sum().rename("Cat_Real")


def build():
    w, cat = load()
    w = w.sort_values(["Plant", "ArticleCode", "Week"]).reset_index(drop=True)
    k = ["Plant", "ArticleCode"]
    g = w.groupby(k, sort=False)
    consecutive = g.Week.diff().dt.days.eq(7)

    f = pd.DataFrame(index=w.index)
    f["Week"], f["Plant"], f["ArticleCode"] = w.Week, w.Plant, w.ArticleCode
    f["ArticleName"], f["SubGroup"], f["MainGroup"], f["Pilot_Group"] = w.ArticleName, w.SubGroup, w.MainGroup, w.Pilot_Group
    f["Units"] = w.Qty_Clean
    f["ln_Units"] = np.log(w.Qty_Clean)                                                  # target
    f["Price_KZ"], f["Unit_COGS_KZ"], f["Sales_KZ"] = w.Realized_Price_KZ, w.Unit_COGS_KZ, w.Sales_KZ

    # ---- price (decision variables)
    f["ln_Price_Real"] = w.ln_Price_Real
    f["ln_Relative_Price"] = w.ln_Relative_Price
    f["ln_Price_vs_Usual"] = w.ln_Price_Real - g.ln_Price_Real.transform(
        lambda x: x.shift(1).rolling(13, min_periods=4).median())                       # vs previous quarter
    f["Price_Above_Usual"] = f.ln_Price_vs_Usual.clip(lower=0)
    f["Price_Below_Usual"] = f.ln_Price_vs_Usual.clip(upper=0)
    f["dln_Price_1w"] = (w.ln_Price_Real - g.ln_Price_Real.shift(1)).where(consecutive)
    f["Temp_Price_Cut"] = (f.ln_Price_vs_Usual < np.log(0.9)).astype(int)
    f["Discount_Pct"] = (w.KZ_Discount / (w.KZ_NetsSales + w.KZ_Discount) * 100).fillna(0).clip(0, 50)
    f["ln_Category_Price_Index"] = np.log(w.Category_Price_Index)

    # ---- cost & margin: last week's values only (the same week's cost comes from that week's sales lines)
    lc = np.log(w.Unit_COGS_Real_KZ)
    gc = lc.groupby([w.Plant, w.ArticleCode], sort=False)
    f["ln_Unit_Cost_Real_Lag1"] = gc.shift(1)
    f["Margin_Pct_Lag1"] = g.Margin_Pct.shift(1).clip(-50, 80)
    f["dln_Cost_4w_Lag1"] = gc.shift(1) - gc.shift(5)

    # ---- demand history (all shifted: only past weeks)
    lq = f.ln_Units
    gl = lq.groupby([w.Plant, w.ArticleCode], sort=False)
    f["ln_Units_Lag1"] = gl.shift(1).where(consecutive)
    f["ln_Units_Lag2"] = gl.shift(2)
    f["ln_Units_Lag4"] = gl.shift(4)
    f["ln_Units_Roll4"] = gl.transform(lambda x: x.shift(1).rolling(4, min_periods=2).mean())
    f["ln_Units_Roll13"] = gl.transform(lambda x: x.shift(1).rolling(13, min_periods=4).mean())
    f["ln_Units_Store_SKU_Mean"] = gl.transform(lambda x: x.shift(1).expanding(min_periods=4).mean())  # baseline
    f["Units_Trend_13w"] = f.ln_Units_Roll4 - f.ln_Units_Roll13
    f["Weeks_Selling"] = g.cumcount()

    # ---- category demand (previous week, own SKU left out)
    cd = category_demand(cat)
    own = (w.Sales_KZ / w.CPI_Deflator * 100).values
    catv = cd.reindex(pd.MultiIndex.from_arrays([w.SubGroup, w.Plant, w.Week])).values
    loo = np.log(np.clip(catv - own, 1, None))
    f["ln_Category_Demand_Lag1"] = pd.Series(loo).groupby([w.Plant, w.ArticleCode], sort=False).shift(1).where(consecutive)

    # ---- calendar
    f["Holidays_In_Week"], f["Payday_Week"] = w.Holidays_In_Week, w.Payday_Week.astype(int)
    f["Christmas_Season"] = w.Christmas_Season.astype(int)
    f["Month_Sin"], f["Month_Cos"] = np.sin(2 * np.pi * w.Month_Of_Year / 12), np.cos(2 * np.pi * w.Month_Of_Year / 12)
    f["Week_Sin"], f["Week_Cos"] = np.sin(2 * np.pi * w.Week_Of_Year / 52), np.cos(2 * np.pi * w.Week_Of_Year / 52)
    f["December"] = (w.Month_Of_Year == 12).astype(int)
    f["Trend_Weeks"] = (w.Week - w.Week.min()).dt.days / 7

    # ---- stock & supply (no stock data before Jun 2024: left missing, never filled with a constant)
    f["ln_Days_Of_Cover"] = np.log1p(w.Days_Of_Cover.clip(0, 365))
    f["Stock_Data_Available"] = w.Days_Of_Cover.notna().astype(int)
    f["Has_Stock_Record"] = w.Has_Stock_Record.fillna(False).astype(int)

    # ---- store
    f["ln_Store_Sqm"] = np.log(w.Total_Sqm)
    f["Store_Age_Weeks"] = ((w.Week - w.Open_Date).dt.days / 7).clip(lower=0)
    for c in ["A", "B", "C", "P"]:
        f[f"Store_Class_{c}"] = (w.Store_Class == c).astype(int)
    for z in sorted(w.Area_Zone.dropna().unique()):
        f[f"Zone_{z.title()}"] = (w.Area_Zone == z).astype(int)
    f["Channel_HDDS"] = (w.Channel == "HDDS").astype(int)

    # ---- product
    f["Imported"] = (w.PurchaseType == "Import").astype(int)
    for gname in "ABCD":
        f[f"Group_{gname}"] = (w.Pilot_Group == gname).astype(int)

    # ---- macro
    f["ln_FX_BNA"] = np.log(w.FX_BNA_Avg)
    f["Inflation_YoY"], f["Inflation_MoM"] = w.Inflation_YoY_Pct, w.Inflation_MoM_Pct
    f["ln_Brent"] = np.log(w.Brent_USD)
    f["GDP_Growth"] = w.GDP_Real_YoY_Pct_Q

    f["Split"] = np.where(f.Week >= TEST_START, "test", np.where(f.Week >= VALID_START, "valid", "train"))
    f = f.replace([np.inf, -np.inf], np.nan)
    f.to_parquet(OUT / "pilot_features.parquet", index=False)
    return f


ID_COLS = ["Week", "Plant", "ArticleCode", "ArticleName", "SubGroup", "MainGroup", "Pilot_Group", "Units", "ln_Units",
           "Price_KZ", "Unit_COGS_KZ", "Sales_KZ", "Split"]

if __name__ == "__main__":
    f = build()
    feats = [c for c in f.columns if c not in ID_COLS]
    print(f"rows {len(f):,}  SKUs {f.ArticleCode.nunique()}  stores {f.Plant.nunique()}  features {len(feats)}")
    print(f.Split.value_counts().to_string())
    print((f[feats].isna().mean() * 100).round(1).sort_values(ascending=False).head(12).to_string())
