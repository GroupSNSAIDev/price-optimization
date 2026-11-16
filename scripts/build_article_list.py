"""Build the in-scope article list.

Rule: article was sold in at least one scope location (59 Fresmart stores + HDDS dark stores + HRCA)
in the sales history (checkpoints/sales_article_level_*.parquet), and either
  - is ACTIVE in the DB article master (Dim_ArticleMaster.Active_status), or
  - is Purchase Blocked / blank status AND sold in the last 4 months of the sales history.

Outputs:
  checkpoints/article_list.parquet   in-scope articles with master attributes + sales/price/stock coverage
  article_list.xlsx                  same, for review (plus a summary sheet)
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CP = ROOT / "checkpoints"


def sales_by_article():
    cols = ["ArticleCode", "PLANTNAME", "HRCA / HDDS Classification", "DateConverted",
            "SalesQty", "KZ_GrossSales", "USD_GrossSales"]
    parts = []
    for f in sorted(CP.glob("sales_article_level_*.parquet")):
        d = pd.read_parquet(f, columns=cols)
        for c in ["SalesQty", "KZ_GrossSales", "USD_GrossSales"]:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
        d["Channel"] = d["HRCA / HDDS Classification"]
        g = d.groupby(["ArticleCode", "Channel"]).agg(
            KZ_Sales=("KZ_GrossSales", "sum"), USD_Sales=("USD_GrossSales", "sum"),
            First_Sale=("DateConverted", "min"), Last_Sale=("DateConverted", "max"))
        g = g.join(d.groupby(["ArticleCode", "Channel"])["PLANTNAME"].unique().rename("Plants"))
        parts.append(g.reset_index())
    s = pd.concat(parts, ignore_index=True)
    plants = s.groupby("ArticleCode")["Plants"].agg(lambda x: set().union(*map(set, x)))
    usd_ch = s.pivot_table(index="ArticleCode", columns="Channel", values="USD_Sales", aggfunc="sum").fillna(0)
    usd_ch.columns = [f"USD_Sales_{c}" for c in usd_ch.columns]
    out = s.groupby("ArticleCode").agg(KZ_Sales=("KZ_Sales", "sum"), USD_Sales=("USD_Sales", "sum"),
                                       First_Sale=("First_Sale", "min"), Last_Sale=("Last_Sale", "max"))
    out["N_Locations_Sold"] = plants.map(len)
    return out.join(usd_ch).reset_index()


def main():
    dim = pd.read_parquet(CP / "dim_article_master.parquet").drop_duplicates("ArticalCode")
    dim = dim.rename(columns={"ArticalCode": "ArticleCode", "ArticalName": "ArticleName"})
    sales = sales_by_article()

    price = pd.read_parquet(CP / "price_changes.parquet", columns=["ArticleCode"])["ArticleCode"].unique()
    stock = pd.read_parquet(CP / "stock_monthly.parquet", columns=["ArticleCode"])["ArticleCode"].unique()

    allx = dim.merge(sales, on="ArticleCode", how="outer", indicator=True)
    allx["Sold_In_Scope"] = allx["_merge"].isin(["both", "right_only"])
    allx["In_DB_Master"] = allx["_merge"].isin(["both", "left_only"])
    allx["Is_Active"] = allx["Active_status"].eq("ACTIVE")
    allx = allx.drop(columns="_merge")

    # Purchase Blocked / blank-status articles count only if still selling in the last 4 months
    recent_from = (allx.Last_Sale.max().to_period("M") - 3).start_time
    allx["Sold_Last_4M"] = allx.Last_Sale >= recent_from
    allx["Inclusion"] = None
    allx.loc[allx.Is_Active, "Inclusion"] = "ACTIVE"
    allx.loc[~allx.Is_Active & allx.Sold_Last_4M, "Inclusion"] = (
        allx["Active_status"].fillna("BLANK STATUS").str.upper() + " - sold since " + recent_from.strftime("%b %Y"))

    lst = allx[allx.Inclusion.notna() & allx.Sold_In_Scope].copy()
    lst["Has_Price"] = lst.ArticleCode.isin(price)
    lst["Has_Stock"] = lst.ArticleCode.isin(stock)
    lst["Sold_Last_6M"] = lst.Last_Sale >= lst.Last_Sale.max() - pd.DateOffset(months=6)
    lst = lst.sort_values("USD_Sales", ascending=False)

    front = ["ArticleCode", "Inclusion", "ArticleName", "MainGroup", "SubGroup", "Category", "ProductName", "BRAND_DESCR",
             "Import", "IsFrozen", "BaseUOM", "SalesUOM", "SalesUOMConversion", "SalesUOMNetWeight",
             "Active_status", "Product_Stage", "Creation_Date", "First_Date_Of_Sales",
             "USD_Sales", "KZ_Sales", "First_Sale", "Last_Sale", "Sold_Last_4M", "Sold_Last_6M", "N_Locations_Sold"]
    rest = [c for c in lst.columns if c not in front and c not in ("Sold_In_Scope", "In_DB_Master", "Is_Active")]
    lst = lst[front + rest]
    lst.to_parquet(CP / "article_list.parquet", index=False)

    sold = allx[allx.Sold_In_Scope]
    summary = (sold.assign(Status=sold.Active_status.fillna("(blank)"))
               .groupby("Status").agg(Articles=("ArticleCode", "size"), USD_Sales=("USD_Sales", "sum"))
               .sort_values("USD_Sales", ascending=False))
    summary["USD_Share_%"] = (summary.USD_Sales / summary.USD_Sales.sum() * 100).round(1)
    by_incl = (lst.groupby("Inclusion").agg(Articles=("ArticleCode", "size"), USD_Sales=("USD_Sales", "sum"))
               .sort_values("USD_Sales", ascending=False))
    by_group = (lst.groupby("MainGroup", dropna=False)
                .agg(Articles=("ArticleCode", "size"), USD_Sales=("USD_Sales", "sum"))
                .sort_values("USD_Sales", ascending=False))
    with pd.ExcelWriter(ROOT / "article_list.xlsx") as xw:
        summary.to_excel(xw, sheet_name="Status summary")
        by_incl.to_excel(xw, sheet_name="Included by rule")
        by_group.to_excel(xw, sheet_name="Active by MainGroup")
        lst.to_excel(xw, sheet_name="Article list", index=False)

    print(summary.to_string())
    print("\n" + by_incl.assign(USD_M=(by_incl.USD_Sales / 1e6).round(1)).drop(columns="USD_Sales").to_string())
    print(f"\nIn-scope article list: {len(lst):,} articles, USD {lst.USD_Sales.sum()/1e6:,.1f}M")
    print(f"  sold in last 6 months: {lst.Sold_Last_6M.sum():,}")
    print(f"  with price data: {lst.Has_Price.sum():,}   with stock data: {lst.Has_Stock.sum():,}")
    print(f"Active in master but never sold in scope: {(allx.Is_Active & ~allx.Sold_In_Scope).sum():,}")
    print("\n" + by_group.assign(USD_M=(by_group.USD_Sales / 1e6).round(1)).drop(columns="USD_Sales").to_string())


if __name__ == "__main__":
    main()
