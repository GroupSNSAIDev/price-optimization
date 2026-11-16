"""Extract daily article-level sales from Azure SQL into checkpoints/sales_article_level_YYYY_MM.parquet.

Same grain and totals as the original checkpoint files (all billing types, scope locations,
summed per day x location x article x UOM), plus cost / discount / profit columns.

Usage:  python scripts/extract_sales.py 2026-08 2026-09
        python scripts/extract_sales.py 2023-01:2026-07      (range)

Historical months (before TABLE_SPLIT) are read from Fact_Sales_Details_Historical only, later months from
Fact_Sales_Details_New only (samples show Historical ends 2025-12-31 and New starts 2026-01-02).
An existing checkpoint is moved to checkpoints/_original/ and its totals are compared with the new extract.
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pymssql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CP = ROOT / "checkpoints"
load_dotenv(ROOT / ".env")

TABLE_SPLIT = pd.Period("2026-01", freq="M")
SUMS = ["SalesQty", "SalesQtyAsPerBaseUOM", "KZ_GrossSales", "USD_GrossSales", "KZ_COGS", "KZ_Discount",
        "KZ_NetsSales", "KZ_GrossProfit", "KZ_Tax", "USD_COGS", "USD_Discount", "USD_NetSales", "USD_GrossProfit",
        "USD_Tax"]
# location attributes carried on every checkpoint row
LOC_COLS = ["Location Code", "Master Location Code", "Store/Location Code", "Store/Location Name",
            "Store Name Master", "City", "Region", "Country", "Area/Zone", "Store Class", "Original Classification",
            "Fresmart Status", "Fresmart Included", "HRCA / HDDS Classification", "Location Mapping Status"]


def query(sql, retries=3):
    for attempt in range(1, retries + 1):
        try:
            with pymssql.connect(server=os.environ["AZURE_SQL_SERVER"], user=os.environ["AZURE_SQL_USER"],
                                 password=os.environ["AZURE_SQL_PASSWORD"],
                                 database=os.environ["AZURE_SQL_DATABASE"], login_timeout=30) as conn:
                cur = conn.cursor()
                cur.execute(sql)
                return pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
        except Exception as e:
            print(f"  query failed (attempt {attempt}): {e!r}"[:300], flush=True)
            if attempt == retries:
                raise
            time.sleep(15 * attempt)


def scope_plants():
    loc = pd.read_excel(ROOT / "Formal Location Master.xlsx")
    return sorted(set(loc["ST-Code"].dropna().str.strip()) | {"HRCA"})


def location_attrs(plants):
    """Location attributes from the most recent existing checkpoint; new plants get them from the master."""
    last = sorted(CP.glob("sales_article_level_*.parquet"))[-1]
    a = pd.read_parquet(last, columns=["PLANTNAME"] + LOC_COLS).drop_duplicates("PLANTNAME").set_index("PLANTNAME")
    loc = pd.read_excel(ROOT / "Formal Location Master.xlsx").set_index("ST-Code")
    for p in plants:
        if p in a.index or p not in loc.index:
            continue
        r = loc.loc[p]
        hd = str(r["Type"]).endswith("HD")
        a.loc[p] = {"Location Code": p, "Master Location Code": p, "Store/Location Code": p,
                    "Store/Location Name": r["Store Name"], "Store Name Master": r["Store Name"],
                    "City": r["Area/Zone"], "Region": r["Area/Zone"], "Country": "Angola",
                    "Area/Zone": r["Area/Zone"], "Store Class": r["ST CLASS"], "Original Classification": r["Type"],
                    "Fresmart Status": "NOT_FRESMART" if hd else "FRESMART_STORE",
                    "Fresmart Included": "NO" if hd else "YES",
                    "HRCA / HDDS Classification": "HDDS" if hd else "STORE",
                    "Location Mapping Status": "HDDS" if hd else "MATCHED_FRESMART"}
    return a


def extract_month(month, plants, attrs):
    m = pd.Period(month, freq="M")
    start, end = m.start_time.date(), (m + 1).start_time.date()
    plist = ",".join(f"'{p}'" for p in plants)
    sums = ", ".join(f"sum({c}) as {c}" for c in SUMS)
    parts = []
    # one week per query: a whole month in one query drops the connection
    edges = list(pd.date_range(start, end, freq="7D").date) + [end]
    edges = sorted(set(edges))
    tmp = CP / "_sales_chunks"
    tmp.mkdir(exist_ok=True)
    tables = ["Fact_Sales_Details_Historical"] if m < TABLE_SPLIT else ["Fact_Sales_Details_New"]
    for table in tables:
        for a, b in zip(edges[:-1], edges[1:]):
            chunk = tmp / f"{table}_{a}_{b}.parquet"
            if chunk.exists():  # resume: week already pulled
                parts.append(pd.read_parquet(chunk))
                continue
            t = time.time()
            df = query(f"""select DateConverted, PLANTNAME, StoreName, ArticleCode, SalesUOM, BaseUOM,
                                  count(*) as SourceRecordCount, {sums}
                           from Newaco.{table}
                           where DateConverted >= '{a}' and DateConverted < '{b}' and PLANTNAME in ({plist})
                           group by DateConverted, PLANTNAME, StoreName, ArticleCode, SalesUOM, BaseUOM""")
            print(f"  {month} {table} {a}..{b}: {len(df):,} rows in {time.time() - t:.0f}s", flush=True)
            df = df.assign(SourceTable=table)
            df.to_parquet(chunk, index=False)
            parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    if df.SourceTable.nunique() > 1:
        raise RuntimeError(f"{month}: rows in both sales tables - check for double counting before saving")
    df = df.drop(columns="SourceTable")
    for c in SUMS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["DateConverted"] = pd.to_datetime(df.DateConverted)
    df["Date"] = df.DateConverted.dt.strftime("%Y%m%d")
    df = df.join(attrs, on="PLANTNAME")
    df["ArticleCode"] = df.ArticleCode.str.strip()
    df["Article Code"] = df.ArticleCode
    out = CP / f"sales_article_level_{m.year}_{m.month:02d}.parquet"
    if out.exists():  # keep the original extract and check the new one reproduces it
        bak = CP / "_original"
        bak.mkdir(exist_ok=True)
        old = pd.read_parquet(out, columns=["SourceRecordCount", "KZ_GrossSales"])
        o_n, o_kz = old.SourceRecordCount.sum(), pd.to_numeric(old.KZ_GrossSales).astype(float).sum()
        n_n, n_kz = df.SourceRecordCount.sum(), df.KZ_GrossSales.sum()
        print(f"  check vs original: lines {n_n:,} vs {o_n:,}; KZ {n_kz:,.0f} vs {o_kz:,.0f} "
              f"({(n_kz / o_kz - 1) * 100:+.3f}%)", flush=True)
        if not (bak / out.name).exists():
            out.replace(bak / out.name)
    df.to_parquet(out, index=False)
    for a, b in zip(edges[:-1], edges[1:]):
        for table in ["Fact_Sales_Details_New", "Fact_Sales_Details_Historical"]:
            (tmp / f"{table}_{a}_{b}.parquet").unlink(missing_ok=True)
    print(f"  saved {out.name}: {len(df):,} rows, KZ {df.KZ_GrossSales.sum():,.0f}", flush=True)


if __name__ == "__main__":
    plants = scope_plants()
    attrs = location_attrs(plants)
    months = []
    for arg in sys.argv[1:]:
        if ":" in arg:
            a, b = arg.split(":")
            months += [str(p) for p in pd.period_range(a, b, freq="M")]
        else:
            months.append(arg)
    for month in months:
        extract_month(month, plants, attrs)
