"""Add inflation-adjusted and category-relative prices to clean/panel_monthly.parquet.

Nominal kwanza prices and volumes both trend up over 2023-2026 (inflation, devaluation, new stores),
so a model on nominal prices would see "price up, sales up". Two adjustments:

1. CPI-deflated price (Jan 2023 kwanza):
     Price_Real_KZ = Realized_Price_KZ / CPI_Rebased_Jan2023 * 100
   Months after the last published CPI are extended at the average monthly inflation of the last 3 months
   (CPI_Estimated = True).

2. Category-relative price (inflation cancels out, including category-specific inflation such as
   imported goods that track the exchange rate more than CPI):
     article index  r = price / article-location geometric-mean price
     category index  = sales-weighted geometric mean of r over the OTHER articles in the same
                       SubGroup x location x month (leave-one-out, so an article's own price
                       does not move its benchmark); chain-wide SubGroup x month when the
                       location has fewer than MIN_PEERS other articles
     Relative_Price  = r / category index   (1.0 = moved in line with its category)
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "clean" / "panel_monthly.parquet"
MIN_PEERS = 5


def extend_cpi(p):
    m = pd.read_parquet(ROOT / "clean" / "macro_monthly.parquet")[["Month", "CPI_Rebased_Jan2023"]]
    m = m.set_index(pd.PeriodIndex(m.Month, freq="M"))["CPI_Rebased_Jan2023"]
    months = pd.period_range(m.index.min(), pd.Period(p.Month.max(), freq="M"), freq="M")
    m = m.reindex(months)
    last = m.last_valid_index()
    rate = (m[last] / m[last - 3]) ** (1 / 3)
    est = m.isna() & (m.index > last)
    for i in m.index[est]:
        m[i] = m[i - 1] * rate
    return pd.DataFrame({"Month": m.index.astype(str), "CPI_Deflator": m.values, "CPI_Estimated": est.values})


def leave_one_out_index(df, keys):
    """Sales-weighted geometric mean of r over the other articles in each group."""
    g = df.groupby(keys)
    S = g["wlr"].transform("sum")
    W = g["w"].transform("sum")
    N = g["w"].transform("size")
    loo = np.exp((S - df.wlr) / (W - df.w))
    return loo.where((N - 1 >= 1) & (W - df.w > 0)), N - 1


def main():
    p = pd.read_parquet(PANEL)
    p = p.drop(columns=[c for c in p.columns if c in {
        "CPI_Deflator", "CPI_Estimated", "Price_Real_KZ", "Sales_Real_KZ", "Article_Price_Index",
        "Category_Price_Index", "Category_Index_Level", "Category_Peers", "Relative_Price",
        "ln_Qty_Base", "ln_Price_Real", "ln_Relative_Price"}])

    p = p.merge(extend_cpi(p), on="Month", how="left")
    p["Price_Real_KZ"] = p.Realized_Price_KZ / p.CPI_Deflator * 100
    p["Sales_Real_KZ"] = p.Sales_KZ / p.CPI_Deflator * 100

    ok = p.Realized_Price_KZ.gt(0) & p.Gross_Sales_KZ.gt(0) & p.SubGroup.notna()
    d = p.loc[ok, ["Month", "Plant", "ArticleCode", "SubGroup", "Realized_Price_KZ", "Gross_Sales_KZ"]].copy()
    lp = np.log(d.Realized_Price_KZ)
    d["lr"] = lp - lp.groupby([d.Plant, d.ArticleCode]).transform("mean")
    d["w"] = d.Gross_Sales_KZ
    d["wlr"] = d.w * d.lr

    store_idx, store_n = leave_one_out_index(d, ["SubGroup", "Plant", "Month"])
    chain_idx, chain_n = leave_one_out_index(d, ["SubGroup", "Month"])
    use_store = store_n >= MIN_PEERS
    d["Category_Price_Index"] = np.where(use_store, store_idx, chain_idx)
    d["Category_Index_Level"] = np.where(use_store, "SubGroup x location", "SubGroup chain-wide")
    d["Category_Peers"] = np.where(use_store, store_n, chain_n)
    d["Article_Price_Index"] = np.exp(d.lr)
    d["Relative_Price"] = d.Article_Price_Index / d.Category_Price_Index

    cols = ["Article_Price_Index", "Category_Price_Index", "Category_Index_Level", "Category_Peers", "Relative_Price"]
    p = p.join(d[cols])
    p["ln_Qty_Base"] = np.log(p.Gross_Qty_Base.where(p.Gross_Qty_Base > 0))
    p["ln_Price_Real"] = np.log(p.Price_Real_KZ.where(p.Price_Real_KZ > 0))
    p["ln_Relative_Price"] = np.log(p.Relative_Price.where(p.Relative_Price > 0))
    p.to_parquet(PANEL, index=False)

    # sanity: nominal vs real vs relative price trend (median across articles)
    t = p[ok].groupby("Month").agg(Nominal=("Realized_Price_KZ", "median"), Real=("Price_Real_KZ", "median"),
                                   Relative=("Relative_Price", "median"))
    t = (t / t.iloc[0] * 100).round(1)
    print(t.iloc[::3].to_string())
    print(f"\nrows with relative price: {p.Relative_Price.notna().sum():,} of {ok.sum():,} priced rows")
    print(p.loc[ok, "Category_Index_Level"].value_counts().to_string())
    print("CPI estimated for:", sorted(p.loc[p.CPI_Estimated.fillna(False), "Month"].unique()))


if __name__ == "__main__":
    main()
