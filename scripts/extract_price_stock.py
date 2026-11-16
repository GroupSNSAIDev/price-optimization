"""Extract price and month-on-month stock data from Azure SQL into checkpoints/.

Scope: all locations in 'Formal Location Master.xlsx' plus HRCA (HORECA).

Outputs:
  checkpoints/price_changes.parquet       raw price-change log (Fact_Price), scope plants, all years
  checkpoints/price_monthly.parquet       price in effect at month start / month end per plant-article-UOM
  checkpoints/stock_monthly.parquet       opening stock (first day) and closing stock (last day) per month
  checkpoints/dim_article_master.parquet  full Dim_ArticleMaster table
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pymssql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "checkpoints"
load_dotenv(ROOT / ".env")

PRICE_FROM = "2023-01"  # month-level price table starts with the sales history


def connect():
    return pymssql.connect(
        server=os.environ["AZURE_SQL_SERVER"],
        user=os.environ["AZURE_SQL_USER"],
        password=os.environ["AZURE_SQL_PASSWORD"],
        database=os.environ["AZURE_SQL_DATABASE"],
        login_timeout=30,
    )


def query(sql, retries=3):
    for attempt in range(1, retries + 1):
        try:
            with connect() as conn:
                cur = conn.cursor(as_dict=False)
                cur.execute(sql)
                cols = [c[0] for c in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=cols)
        except Exception as e:
            print(f"  query failed (attempt {attempt}): {e!r}"[:300], flush=True)
            if attempt == retries:
                raise
            time.sleep(10 * attempt)


def scope_plants():
    loc = pd.read_excel(ROOT / "Formal Location Master.xlsx")
    plants = sorted(set(loc["ST-Code"].dropna().str.strip()) | {"HRCA"})
    return plants


def to_num(df, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def extract_article_master():
    print("Dim_ArticleMaster ...", flush=True)
    df = query("select * from Newaco.Dim_ArticleMaster")
    df.to_parquet(OUT / "dim_article_master.parquet", index=False)
    print(f"  {len(df):,} rows", flush=True)


def extract_prices(plants):
    print("Fact_Price ...", flush=True)
    plist = ",".join(f"'{p}'" for p in plants)
    df = query(f"select * from Newaco.Fact_Price where PlantName in ({plist})")
    df = to_num(df, ["Price", "Sec_Price_Per", "IVA", "PriceIVA"])
    df["EffectiveTS"] = pd.to_datetime(df["Date"] + df["Time"].str.zfill(6), format="%Y%m%d%H%M%S", errors="coerce")
    df = df.sort_values(["PlantName", "ArticleCode", "SalesUOM", "EffectiveTS"]).reset_index(drop=True)
    df.to_parquet(OUT / "price_changes.parquet", index=False)
    print(f"  {len(df):,} price-change rows", flush=True)
    return df


def build_price_monthly(chg):
    """Price in effect at the start and end of each month, carried forward from the last change."""
    chg = chg.dropna(subset=["EffectiveTS"])
    key = ["PlantName", "ArticleCode", "SalesUOM"]
    months = pd.period_range(PRICE_FROM, pd.Timestamp.today().to_period("M"), freq="M")
    out = []
    for m in months:
        start, end = m.start_time, m.end_time
        before_start = chg[chg.EffectiveTS < start].groupby(key).tail(1).set_index(key)
        before_end = chg[chg.EffectiveTS <= end].groupby(key).tail(1).set_index(key)
        n_chg = chg[(chg.EffectiveTS >= start) & (chg.EffectiveTS <= end)].groupby(key).size()
        df = pd.DataFrame(index=before_end.index)
        df["Month"] = str(m)
        df["Price_Start"] = before_start["Price"]
        df["PriceIVA_Start"] = before_start["PriceIVA"]
        df["Price_End"] = before_end["Price"]
        df["PriceIVA_End"] = before_end["PriceIVA"]
        df["IVA"] = before_end["IVA"]
        df["LastChangeTS"] = before_end["EffectiveTS"]
        df["N_Changes_InMonth"] = n_chg.reindex(df.index).fillna(0).astype(int)
        out.append(df.reset_index())
    res = pd.concat(out, ignore_index=True)
    res["Price_Change_Pct"] = (res.Price_End / res.Price_Start - 1) * 100
    res.to_parquet(OUT / "price_monthly.parquet", index=False)
    print(f"  price_monthly: {len(res):,} rows", flush=True)


def extract_stock(plants):
    print("Fact_Stock_Details (month-on-month) ...", flush=True)
    dates = query("select distinct Date from Newaco.Fact_Stock_Details")["Date"]
    d = pd.DataFrame({"Date": dates})
    d["dt"] = pd.to_datetime(d.Date, format="%Y%m%d")
    d["Month"] = d.dt.dt.to_period("M").astype(str)
    bounds = d.groupby("Month").agg(first=("Date", "min"), last=("Date", "max")).reset_index()

    plist = ",".join(f"'{p}'" for p in plants)
    cols = "ArticleCode, Plants, Date, OS_Qty, OS_Value, CS_Qty, CS_Value, Company"
    parts = []
    for _, b in bounds.iterrows():
        print(f"  {b.Month}: opening {b['first']}, closing {b['last']}", flush=True)
        df = query(f"select {cols} from Newaco.Fact_Stock_Details "
                   f"where Date in ('{b['first']}','{b['last']}') and Plants in ({plist})")
        df = to_num(df, ["OS_Qty", "OS_Value", "CS_Qty", "CS_Value"])
        key = ["Plants", "ArticleCode"]
        op = df[df.Date == b["first"]].groupby(key)[["OS_Qty", "OS_Value"]].sum()
        cl = df[df.Date == b["last"]].groupby(key)[["CS_Qty", "CS_Value"]].sum()
        m = op.join(cl, how="outer").reset_index()
        m.columns = ["Plant", "ArticleCode", "Opening_Qty", "Opening_Value", "Closing_Qty", "Closing_Value"]
        m.insert(0, "Month", b.Month)
        m["Opening_Date"] = b["first"]
        m["Closing_Date"] = b["last"]
        parts.append(m)
    res = pd.concat(parts, ignore_index=True)
    # flag months where the snapshot is not a true month start / month end
    od = pd.to_datetime(res.Opening_Date, format="%Y%m%d")
    cd = pd.to_datetime(res.Closing_Date, format="%Y%m%d")
    res["Opening_Is_Month_Start"] = od.dt.day == 1
    res["Closing_Is_Month_End"] = cd.dt.is_month_end
    res.to_parquet(OUT / "stock_monthly.parquet", index=False)
    print(f"  stock_monthly: {len(res):,} rows", flush=True)


if __name__ == "__main__":
    steps = sys.argv[1:] or ["articles", "price", "stock"]
    plants = scope_plants()
    print(f"{len(plants)} scope plants", flush=True)
    if "articles" in steps:
        extract_article_master()
    if "price" in steps:
        build_price_monthly(extract_prices(plants))
    if "stock" in steps:
        extract_stock(plants)
    print("done", flush=True)
