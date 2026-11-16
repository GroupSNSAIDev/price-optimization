"""Clean all source data and link it into one month x location x article panel.

Inputs (checkpoints/ unless noted):
  sales_article_level_YYYY_MM.parquet, dim_article_master.parquet, article_list.parquet,
  price_changes.parquet, stock_monthly.parquet, macro_monthly.parquet,
  ../Formal Location Master.xlsx

Outputs (clean/):
  dim_location.parquet        locations (59 stores, 4 HDDS, HRCA, 9 planned YTO) with open dates, zone, class, size
  dim_dc.parquet              distribution-centre capacity table from the location master
  dim_article.parquet         DB article master, de-duplicated, normalised UOMs, kg per base unit, scope flag
  uom_conversion.parquet      (article, UOM) -> base units, from observed sales with master as fallback
  sales_daily/YYYY_MM.parquet cleaned daily sales, in-scope locations x articles, base-unit quantities
  sales_monthly.parquet       monthly sales per location x article
  price_changes.parquet       cleaned price-change log, converted to price per base unit
  price_monthly.parquet       list price per base unit at month start / end, min / max, number of changes
  stock_monthly.parquet       cleaned opening / closing stock (base units, USD at cost)
  macro_monthly.parquet       FX, inflation, Brent, GDP
  panel_monthly.parquet       everything above joined at month x location x article
  ../data_quality_report.xlsx every check, rows affected and the action taken
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
CP = ROOT / "checkpoints"
OUT = ROOT / "clean"
(OUT / "sales_daily").mkdir(parents=True, exist_ok=True)

PANEL_START = "2023-01"
PANEL_END = sorted(CP.glob("sales_article_level_*.parquet"))[-1].stem[-7:].replace("_", "-")  # last sales month
FIN = ["KZ_COGS", "KZ_Discount", "KZ_NetsSales", "KZ_GrossProfit", "KZ_Tax", "USD_COGS", "USD_Discount",
       "USD_NetSales", "USD_GrossProfit", "USD_Tax"]  # from scripts/extract_sales.py
# In the source, NetsSales = GrossSales (already after discount, excl. tax) and GrossProfit = NetsSales - COGS.
UOM_MAP = {"PC": "ST", "KGM": "KG"}           # master codes -> sales/price codes
SPIKE = 3.0                                   # price / unit-price outlier ratio

DQ = []  # (dataset, check, rows, action)


def dq(dataset, check, rows, action):
    DQ.append({"Dataset": dataset, "Check": check, "Rows": int(rows), "Action": action})
    print(f"  [{dataset}] {check}: {int(rows):,} -> {action}", flush=True)


def num(df, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


# --------------------------------------------------------------------------- locations
def build_dim_location():
    print("Locations ...", flush=True)
    raw = pd.read_excel(ROOT / "Formal Location Master.xlsx")
    loc = raw.iloc[:, :9].copy()
    loc.columns = ["Plant", "Store_Name", "Type", "Area_Zone", "Store_Class", "Floor_Sqm", "DC_Rest_Sqm",
                   "Total_Sqm", "Open_Date_Raw"]
    loc = loc.dropna(subset=["Plant"])
    for c in ["Plant", "Store_Name", "Type", "Area_Zone", "Store_Class"]:
        loc[c] = loc[c].astype(str).str.replace("�", "", regex=False).str.strip()
    bad_names = raw.iloc[:, 1].astype(str).str.contains("�").sum()
    dq("location", "store names with broken characters", bad_names, "removed the bad character")

    loc["Open_Date"] = pd.to_datetime(loc.Open_Date_Raw, errors="coerce")
    loc["Planned_Open"] = np.where(loc.Open_Date.isna(), loc.Open_Date_Raw.astype(str), None)
    loc["Type"] = loc.Type.str.replace(r"^\d+\.\s*", "", regex=True)
    loc["Channel"] = loc.Type.map({"STORE": "STORE", "HD": "HDDS", "YTO": "STORE"})
    loc["Status"] = np.where(loc.Type.eq("YTO") | loc.Open_Date.isna(), "PLANNED", "OPEN")
    dq("location", "planned (YTO) stores without an open date", (loc.Status == "PLANNED").sum(), "kept, Status=PLANNED")

    # add HRCA (HORECA) from the sales data - it is not in the location master
    s = pd.read_parquet(sorted(CP.glob("sales_article_level_*.parquet"))[-1],
                        columns=["PLANTNAME", "StoreName", "City", "Region", "Area/Zone", "Store Class"])
    attrs = s.drop_duplicates("PLANTNAME").set_index("PLANTNAME")
    if "HRCA" not in set(loc.Plant):
        first = pd.read_parquet(CP / "sales_article_level_2025_09.parquet", columns=["PLANTNAME", "DateConverted"])
        loc = pd.concat([loc, pd.DataFrame([{
            "Plant": "HRCA", "Store_Name": "HORECA", "Type": "HRCA", "Area_Zone": "CITY", "Store_Class": None,
            "Open_Date": first[first.PLANTNAME == "HRCA"].DateConverted.min(), "Channel": "HRCA", "Status": "OPEN"}])],
            ignore_index=True)
        dq("location", "HRCA missing from location master", 1, "added from sales data (Channel=HRCA)")
    loc["City"] = loc.Plant.map(attrs["City"])
    loc["Region"] = loc.Plant.map(attrs["Region"])
    loc = loc.drop(columns="Open_Date_Raw")
    loc.to_parquet(OUT / "dim_location.parquet", index=False)

    dc = raw[["DC", "Capacity inTon", "Type.1"]].dropna(subset=["DC"])
    dc.columns = ["DC", "Capacity_Ton", "Storage_Type"]
    dc[dc.DC != "Total"].to_parquet(OUT / "dim_dc.parquet", index=False)
    return loc


# --------------------------------------------------------------------------- articles
def build_dim_article():
    print("Articles ...", flush=True)
    d = pd.read_parquet(CP / "dim_article_master.parquet")
    d = d.rename(columns={"ArticalCode": "ArticleCode", "ArticalName": "ArticleName",
                          "ProcurmentLeadTime": "ProcurementLeadTime"})
    for c in d.select_dtypes("object").columns:
        d[c] = d[c].astype("string").str.strip().replace("", pd.NA)
    d["Active_status"] = d.Active_status.fillna("BLANK")
    dups = d.ArticleCode.duplicated(keep=False).sum()
    d["_rank"] = d.Active_status.map({"ACTIVE": 0, "Purchase Blocked": 1}).fillna(2)
    d = d.sort_values("_rank").drop_duplicates("ArticleCode").drop(columns="_rank")
    dq("article", "duplicate article codes in DB master", dups, "kept one row per code (ACTIVE preferred)")

    d = num(d, ["SalesUOMConversion", "SalesUOMNetWeight", "ContainerConversion", "ProcurementLeadTime"])
    d["PurchaseRotationDays"] = pd.to_numeric(d.PurchaseRotationDays, errors="coerce")
    for c in ["Creation_Date", "First_Date_Of_Sales"]:
        d[c] = pd.to_datetime(d[c], format="%Y%m%d", errors="coerce")
    for c in ["BaseUOM", "SalesUOM"]:
        d[c] = d[c].replace(UOM_MAP)
    bad_conv = (d.SalesUOMConversion.isna() | (d.SalesUOMConversion <= 0)).sum()
    d.loc[d.SalesUOMConversion <= 0, "SalesUOMConversion"] = np.nan
    dq("article", "missing / zero sales-UOM conversion", bad_conv, "set to NaN, observed sales conversion used instead")

    # kg per base unit: net weight is per sales UOM
    d["KG_per_Base"] = np.where(d.BaseUOM.eq("KG"), 1.0, d.SalesUOMNetWeight / d.SalesUOMConversion)
    d.loc[d.KG_per_Base <= 0, "KG_per_Base"] = np.nan

    lst = pd.read_parquet(CP / "article_list.parquet", columns=["ArticleCode", "Inclusion"])
    d = d.merge(lst, on="ArticleCode", how="left")
    d["In_Scope"] = d.Inclusion.notna()
    d.to_parquet(OUT / "dim_article.parquet", index=False)
    return d


# --------------------------------------------------------------------------- sales
def clean_sales(scope_plants, scope_articles):
    print("Sales ...", flush=True)
    cols = ["DateConverted", "PLANTNAME", "ArticleCode", "SalesUOM", "BaseUOM", "SourceRecordCount",
            "SalesQty", "SalesQtyAsPerBaseUOM", "KZ_GrossSales", "USD_GrossSales"]
    tot = dict(rows=0, out_plant=0, out_article=0, dup=0, ret=0, zero=0, valnoqty=0, outlier=0,
               cogs_miss=0, cogs_zero=0, below_cost=0, cost_outlier=0)
    monthly, conv = [], []
    for f in sorted(CP.glob("sales_article_level_*.parquet")):
        fin = [c for c in FIN if c in pq.read_schema(f).names]
        s = pd.read_parquet(f, columns=cols + fin)
        for c in FIN:
            if c not in s:
                s[c] = np.nan
        s = num(s, ["SalesQty", "SalesQtyAsPerBaseUOM", "KZ_GrossSales", "USD_GrossSales"] + FIN)
        tot["rows"] += len(s)
        # observed UOM conversion (all articles, before scope filter)
        ok = (s.SalesQty > 0) & (s.SalesQtyAsPerBaseUOM > 0)
        conv.append(s[ok].assign(f=s.SalesQtyAsPerBaseUOM / s.SalesQty)
                    .groupby(["ArticleCode", "SalesUOM"]).f.agg(["median", "size"]).reset_index())

        m_pl = s.PLANTNAME.isin(scope_plants)
        tot["out_plant"] += (~m_pl).sum()
        m_ar = s.ArticleCode.isin(scope_articles)
        tot["out_article"] += (m_pl & ~m_ar).sum()
        s = s[m_pl & m_ar]

        key = ["DateConverted", "PLANTNAME", "ArticleCode", "SalesUOM", "BaseUOM"]
        tot["dup"] += s.duplicated(key).sum()
        s = s.groupby(key, as_index=False)[["SourceRecordCount", "SalesQty", "SalesQtyAsPerBaseUOM",
                                            "KZ_GrossSales", "USD_GrossSales"] + FIN].sum(min_count=1)
        s.columns = ["Date", "Plant", "ArticleCode", "SalesUOM", "BaseUOM", "Txn_Count", "Qty", "Qty_Base",
                     "Sales_KZ", "Sales_USD"] + FIN
        tot["zero"] += ((s.Qty == 0) & (s.Sales_KZ == 0)).sum()
        s = s[~((s.Qty == 0) & (s.Sales_KZ == 0))]
        tot["valnoqty"] += ((s.Qty == 0) & (s.Sales_KZ != 0)).sum()
        s["Is_Return"] = (s.Qty < 0) | (s.Sales_KZ < 0)
        tot["ret"] += s.Is_Return.sum()

        s["Unit_Price_KZ"] = np.where(s.Qty_Base > 0, s.Sales_KZ / s.Qty_Base, np.nan)
        s.loc[s.Is_Return, "Unit_Price_KZ"] = np.nan
        med = s.groupby(["Plant", "ArticleCode"]).Unit_Price_KZ.transform("median")
        r = s.Unit_Price_KZ / med
        s["Price_Outlier"] = (r > SPIKE) | (r < 1 / SPIKE)
        tot["outlier"] += s.Price_Outlier.sum()

        # cost of goods: unit cost per base unit and checks
        sale = ~s.Is_Return & (s.Qty_Base > 0)
        tot["cogs_miss"] += (sale & s.KZ_COGS.isna()).sum()
        tot["cogs_zero"] += (sale & (s.KZ_COGS <= 0)).sum()
        s["Unit_COGS_KZ"] = np.where(sale & (s.KZ_COGS > 0), s.KZ_COGS / s.Qty_Base, np.nan)
        cmed = s.groupby(["Plant", "ArticleCode"]).Unit_COGS_KZ.transform("median")
        cr = s.Unit_COGS_KZ / cmed
        s["Cost_Outlier"] = (cr > SPIKE) | (cr < 1 / SPIKE)
        tot["cost_outlier"] += s.Cost_Outlier.sum()
        s["Below_Cost_50"] = sale & (s.KZ_COGS > 1.5 * s.Sales_KZ)
        tot["below_cost"] += s.Below_Cost_50.sum()
        s["Month"] = s.Date.dt.to_period("M").astype(str)
        s.to_parquet(OUT / "sales_daily" / f.name.replace("sales_article_level_", ""), index=False)

        pos = s[~s.Is_Return & (s.Qty_Base > 0)]
        clean_p = pos[~pos.Price_Outlier]
        clean_c = pos[~pos.Cost_Outlier & pos.Unit_COGS_KZ.notna()]
        g = s.groupby(["Month", "Plant", "ArticleCode"]).agg(
            Qty_Base=("Qty_Base", "sum"), Sales_KZ=("Sales_KZ", "sum"), Sales_USD=("Sales_USD", "sum"),
            Txn_Count=("Txn_Count", "sum"))
        g = g.join(s.groupby(["Month", "Plant", "ArticleCode"])[FIN].sum(min_count=1))
        g = g.join(s[s.Is_Return].groupby(["Month", "Plant", "ArticleCode"]).Qty_Base.sum()
                   .abs().rename("Return_Qty_Base"))
        g = g.join(pos.groupby(["Month", "Plant", "ArticleCode"]).agg(
            Days_Sold=("Date", "nunique"), Gross_Qty_Base=("Qty_Base", "sum"), Gross_Sales_KZ=("Sales_KZ", "sum"),
            Gross_Sales_USD=("Sales_USD", "sum")))
        g = g.join(clean_p.groupby(["Month", "Plant", "ArticleCode"]).agg(
            Median_Daily_Price_KZ=("Unit_Price_KZ", "median"),
            Min_Daily_Price_KZ=("Unit_Price_KZ", "min"), Max_Daily_Price_KZ=("Unit_Price_KZ", "max")))
        g = g.join(s.groupby(["Month", "Plant", "ArticleCode"]).Price_Outlier.sum().rename("N_Price_Outlier_Days"))
        g = g.join(clean_c.groupby(["Month", "Plant", "ArticleCode"]).agg(
            Cost_Qty_Base=("Qty_Base", "sum"), Cost_COGS_KZ=("KZ_COGS", "sum"), Cost_COGS_USD=("USD_COGS", "sum"),
            Median_Daily_Unit_COGS_KZ=("Unit_COGS_KZ", "median")))
        g = g.join(s.groupby(["Month", "Plant", "ArticleCode"]).agg(
            N_Cost_Outlier_Days=("Cost_Outlier", "sum"), N_Below_Cost_Days=("Below_Cost_50", "sum")))
        monthly.append(g.reset_index())
        print(f"  {f.stem[-7:]}: {len(s):,} clean rows", flush=True)

    dq("sales", "rows read", tot["rows"], "-")
    dq("sales", "rows outside scope locations", tot["out_plant"], "dropped")
    dq("sales", "rows for out-of-scope articles", tot["out_article"], "dropped")
    dq("sales", "duplicate date x location x article x UOM rows", tot["dup"], "summed into one row")
    dq("sales", "rows with zero quantity and zero value", tot["zero"], "dropped")
    dq("sales", "rows with value but zero quantity", tot["valnoqty"], "kept; excluded from unit price")
    dq("sales", "return rows (negative qty or value)", tot["ret"], "kept, Is_Return=True; netted in totals")
    dq("sales", f"daily unit price >{SPIKE}x or <1/{SPIKE} of the location-article median", tot["outlier"],
       "flagged Price_Outlier; excluded from median/min/max price")
    dq("sales", "sale rows with missing COGS", tot["cogs_miss"], "kept; no unit cost")
    dq("sales", "sale rows with zero / negative COGS", tot["cogs_zero"], "kept in totals; excluded from unit cost")
    dq("sales", f"daily unit COGS >{SPIKE}x or <1/{SPIKE} of the location-article median", tot["cost_outlier"],
       "flagged Cost_Outlier; excluded from unit cost")
    dq("sales", "sale rows with COGS > 1.5x sales value (sold far below cost)", tot["below_cost"],
       "flagged Below_Cost_50; kept")
    dq("sales", "source check: NetsSales equals GrossSales; GrossProfit = NetsSales - COGS", 0,
       "margin computed on net sales (ex tax, after discount)")

    m = pd.concat(monthly, ignore_index=True)
    m["Realized_Price_KZ"] = m.Gross_Sales_KZ / m.Gross_Qty_Base
    m["Realized_Price_USD"] = m.Gross_Sales_USD / m.Gross_Qty_Base
    m["FX_Internal"] = m.Gross_Sales_KZ / m.Gross_Sales_USD
    m["Discount_Pct_Of_Gross"] = m.KZ_Discount / m.Sales_KZ * 100
    m["Margin_Pct_COGS"] = (m.KZ_NetsSales - m.KZ_COGS) / m.KZ_NetsSales * 100
    m["Unit_COGS_KZ"] = m.Cost_COGS_KZ / m.Cost_Qty_Base
    m["Unit_COGS_USD"] = m.Cost_COGS_USD / m.Cost_Qty_Base
    m = m.drop(columns=["Cost_Qty_Base", "Cost_COGS_KZ", "Cost_COGS_USD"])
    m["Markup_Pct"] = (m.Realized_Price_KZ / m.Unit_COGS_KZ - 1) * 100
    m["Tax_Pct_Of_Net"] = m.KZ_Tax / m.KZ_NetsSales * 100
    m.to_parquet(OUT / "sales_monthly.parquet", index=False)

    c = pd.concat(conv).groupby(["ArticleCode", "SalesUOM"]).apply(
        lambda x: pd.Series({"Factor_Observed": np.average(x["median"], weights=x["size"]),
                             "N_Obs": x["size"].sum()}), include_groups=False).reset_index()
    return m, c.rename(columns={"SalesUOM": "UOM"})


# --------------------------------------------------------------------------- UOM conversion
def build_uom(art, observed):
    print("UOM conversion ...", flush=True)
    base = art[["ArticleCode", "BaseUOM"]].rename(columns={"BaseUOM": "UOM"}).assign(Factor_Master=1.0)
    su = art[["ArticleCode", "SalesUOM", "SalesUOMConversion"]].rename(
        columns={"SalesUOM": "UOM", "SalesUOMConversion": "Factor_Master"})
    master = pd.concat([su, base]).dropna().drop_duplicates(["ArticleCode", "UOM"], keep="last")
    u = master.merge(observed, on=["ArticleCode", "UOM"], how="outer")
    u["Factor"] = u.Factor_Observed.fillna(u.Factor_Master)
    u["Source"] = np.where(u.Factor_Observed.notna(), "observed_sales", "article_master")
    disagree = (u.Factor_Observed.notna() & u.Factor_Master.notna()
                & ((u.Factor_Observed / u.Factor_Master - 1).abs() > 0.05))
    u["Master_Disagrees"] = disagree
    dq("uom", "article-UOM pairs where master conversion differs >5% from sales", disagree.sum(),
       "used the observed sales conversion")
    u.to_parquet(OUT / "uom_conversion.parquet", index=False)
    return u[["ArticleCode", "UOM", "Factor"]]


# --------------------------------------------------------------------------- prices
def clean_prices(scope_plants, scope_articles, uom):
    print("Prices ...", flush=True)
    p = pd.read_parquet(CP / "price_changes.parquet")
    n0 = len(p)
    p = p[p.PlantName.isin(scope_plants) & p.ArticleCode.isin(scope_articles)]
    dq("price", "price rows outside scope locations/articles", n0 - len(p), "dropped")
    bad = p.Price.isna() | (p.Price <= 0) | p.EffectiveTS.isna()
    dq("price", "zero / missing price or timestamp", bad.sum(), "dropped")
    p = p[~bad]
    key = ["PlantName", "ArticleCode", "SalesUOM", "EffectiveTS"]
    dq("price", "several prices at the same timestamp", p.duplicated(key).sum(), "kept the last one")
    p = p.drop_duplicates(key, keep="last")

    p = p.merge(uom, left_on=["ArticleCode", "SalesUOM"], right_on=["ArticleCode", "UOM"], how="left")
    dq("price", "price rows with no UOM conversion", p.Factor.isna().sum(), "dropped")
    p = p.dropna(subset=["Factor"])
    p["Price_Base_KZ"] = p.Price / p.Factor
    p["PriceIVA_Base_KZ"] = p.PriceIVA / p.Factor

    p = p.sort_values(key).reset_index(drop=True)
    g = p.groupby(["PlantName", "ArticleCode", "SalesUOM"]).Price_Base_KZ
    prev, nxt = g.shift(1), g.shift(-1)
    up = (p.Price_Base_KZ / prev > SPIKE) & (p.Price_Base_KZ / nxt > SPIKE)
    dn = (p.Price_Base_KZ / prev < 1 / SPIKE) & (p.Price_Base_KZ / nxt < 1 / SPIKE)
    p["Is_Spike"] = up | dn
    dq("price", f"one-off price spikes (>{SPIKE}x then back)", p.Is_Spike.sum(), "flagged; excluded from monthly price")

    # one price series per location-article: the UOM with the most price records
    n = p.groupby(["PlantName", "ArticleCode", "SalesUOM"]).size().rename("n").reset_index()
    prim = n.sort_values("n").drop_duplicates(["PlantName", "ArticleCode"], keep="last")
    multi = (n.groupby(["PlantName", "ArticleCode"]).size() > 1).sum()
    dq("price", "location-articles priced in more than one UOM", multi,
       "all converted to base unit; monthly table uses the UOM with most records")
    p = p.merge(prim[["PlantName", "ArticleCode", "SalesUOM"]].assign(Primary_UOM=True),
                on=["PlantName", "ArticleCode", "SalesUOM"], how="left")
    p["Primary_UOM"] = p.Primary_UOM.fillna(False).astype(bool)
    p = p.rename(columns={"PlantName": "Plant"}).drop(columns=["UOM"])
    p.to_parquet(OUT / "price_changes.parquet", index=False)

    q = p[p.Primary_UOM & ~p.Is_Spike]
    k = ["Plant", "ArticleCode"]
    out = []
    for m in pd.period_range(PANEL_START, pd.Timestamp.today().to_period("M"), freq="M"):
        s, e = m.start_time, m.end_time
        before = q[q.EffectiveTS < s].groupby(k).tail(1).set_index(k)
        inm = q[(q.EffectiveTS >= s) & (q.EffectiveTS <= e)]
        upto = q[q.EffectiveTS <= e].groupby(k).tail(1).set_index(k)
        df = pd.DataFrame(index=upto.index)
        df["Month"] = str(m)
        df["List_Price_Start_KZ"] = before.Price_Base_KZ
        df["List_Price_End_KZ"] = upto.Price_Base_KZ
        df["List_PriceIVA_End_KZ"] = upto.PriceIVA_Base_KZ
        df["IVA_Pct"] = upto.IVA
        df["Price_UOM"] = upto.SalesUOM
        agg = inm.groupby(k).Price_Base_KZ.agg(["min", "max", "size"])
        df["List_Price_Min_KZ"] = pd.concat([df.List_Price_Start_KZ, agg["min"].reindex(df.index)], axis=1).min(axis=1)
        df["List_Price_Max_KZ"] = pd.concat([df.List_Price_Start_KZ, agg["max"].reindex(df.index)], axis=1).max(axis=1)
        df["N_Price_Changes"] = agg["size"].reindex(df.index).fillna(0).astype(int)
        df["Last_Price_Change"] = upto.EffectiveTS
        out.append(df.reset_index())
    pm = pd.concat(out, ignore_index=True)
    pm["List_Price_Change_Pct"] = (pm.List_Price_End_KZ / pm.List_Price_Start_KZ - 1) * 100
    pm.to_parquet(OUT / "price_monthly.parquet", index=False)
    return pm


# --------------------------------------------------------------------------- stock
def clean_stock(scope_plants, scope_articles):
    print("Stock ...", flush=True)
    s = pd.read_parquet(CP / "stock_monthly.parquet")
    n0 = len(s)
    s = s[s.Plant.isin(scope_plants) & s.ArticleCode.isin(scope_articles)].copy()
    dq("stock", "stock rows outside scope locations/articles", n0 - len(s), "dropped")
    for side in ["Opening", "Closing"]:
        miss = s[f"{side}_Qty"].isna()
        dq("stock", f"{side.lower()} stock missing (no record that day)", miss.sum(), "set to 0")
        s[f"{side}_Missing"] = miss
        neg = (s[f"{side}_Qty"] < 0) | (s[f"{side}_Value"] < 0)
        dq("stock", f"negative {side.lower()} stock", neg.sum(), "set to 0, flagged")
        s[f"{side}_Negative"] = neg
        for c in ["Qty", "Value"]:
            s[f"{side}_{c}"] = s[f"{side}_{c}"].fillna(0).clip(lower=0)
    s = s.rename(columns={"Opening_Value": "Opening_Value_USD", "Closing_Value": "Closing_Value_USD",
                          "Opening_Qty": "Opening_Qty_Base", "Closing_Qty": "Closing_Qty_Base"})
    s["Unit_Cost_USD"] = np.where(s.Closing_Qty_Base > 0, s.Closing_Value_USD / s.Closing_Qty_Base,
                                  np.where(s.Opening_Qty_Base > 0, s.Opening_Value_USD / s.Opening_Qty_Base, np.nan))
    s = s.sort_values(["Plant", "ArticleCode", "Month"])
    prev_close = s.groupby(["Plant", "ArticleCode"]).Closing_Qty_Base.shift(1)
    prev_m = s.groupby(["Plant", "ArticleCode"]).Month.shift(1)
    consecutive = pd.PeriodIndex(prev_m.fillna("1900-01"), freq="M") + 1 == pd.PeriodIndex(s.Month, freq="M")
    s["Continuity_Break"] = consecutive & ~np.isclose(prev_close.fillna(0), s.Opening_Qty_Base)
    dq("stock", "opening differs from previous month closing", s.Continuity_Break.sum(), "flagged only")
    part = (~s.Opening_Is_Month_Start) | (~s.Closing_Is_Month_End)
    dq("stock", "months without a true month-start / month-end snapshot", part.sum(),
       "flagged (Jun 2024 has closing only, Oct 2026 is partial)")
    s.to_parquet(OUT / "stock_monthly.parquet", index=False)
    return s


# --------------------------------------------------------------------------- panel
def build_panel(sales, price, stock, loc, art):
    print("Panel ...", flush=True)
    k = ["Month", "Plant", "ArticleCode"]
    st = stock[(stock.Month >= PANEL_START) & (stock.Month <= PANEL_END)]
    st_cols = ["Opening_Qty_Base", "Closing_Qty_Base", "Opening_Value_USD", "Closing_Value_USD", "Unit_Cost_USD",
               "Opening_Negative", "Closing_Negative", "Continuity_Break"]
    p = sales.merge(st[k + st_cols], on=k, how="outer", indicator="_src")
    p["Has_Sales"] = p._src.isin(["both", "left_only"])
    p["Has_Stock_Record"] = p._src.isin(["both", "right_only"])
    p = p.drop(columns="_src")
    p = p.merge(price, on=k, how="left")
    p["Has_List_Price"] = p.List_Price_End_KZ.notna()

    macro = pd.read_parquet(CP / "macro_monthly.parquet")
    macro.to_parquet(OUT / "macro_monthly.parquet", index=False)
    p = p.merge(macro, on="Month", how="left")

    l = loc[["Plant", "Store_Name", "Channel", "Area_Zone", "Store_Class", "Total_Sqm", "Open_Date", "Status", "City"]]
    p = p.merge(l, on="Plant", how="left")
    a = art[["ArticleCode", "ArticleName", "MainGroup", "SubGroup", "Category", "BRAND_DESCR", "Import",
             "IsFrozen", "BaseUOM", "KG_per_Base", "Active_status", "Inclusion", "Product_Stage"]]
    p = p.merge(a, on="ArticleCode", how="left")

    for c in ["Qty_Base", "Sales_KZ", "Sales_USD", "Txn_Count", "Return_Qty_Base", "Days_Sold"]:
        p[c] = p[c].fillna(0)
    mstart = pd.PeriodIndex(p.Month, freq="M").start_time
    days = pd.PeriodIndex(p.Month, freq="M").days_in_month
    p["Store_Age_Months"] = ((mstart - p.Open_Date).dt.days / 30.44).round(1)
    p["Sales_KG"] = p.Qty_Base * p.KG_per_Base
    p["Discount_vs_List_Pct"] = (1 - p.Realized_Price_KZ / p.List_Price_End_KZ) * 100
    p["Realized_Price_Real_KZ"] = p.Realized_Price_KZ / p.CPI_Rebased_Jan2023 * 100
    p["Unit_COGS_Real_KZ"] = p.Unit_COGS_KZ / p.CPI_Rebased_Jan2023 * 100
    p["Gross_Margin_KZ"] = p.KZ_NetsSales - p.KZ_COGS
    p["Gross_Margin_USD"] = p.USD_NetSales - p.USD_COGS
    # stock-valuation estimate kept for comparison with the actual COGS margin
    p["Margin_USD_Est"] = p.Gross_Sales_USD - p.Gross_Qty_Base * p.Unit_Cost_USD
    p["Margin_Pct_Est"] = p.Margin_USD_Est / p.Gross_Sales_USD * 100
    p["Avg_Stock_Qty_Base"] = (p.Opening_Qty_Base + p.Closing_Qty_Base) / 2
    p["Days_Of_Cover"] = p.Closing_Qty_Base / (p.Qty_Base / days).replace(0, np.nan)
    p["Out_Of_Stock"] = p.Has_Stock_Record & (p.Opening_Qty_Base <= 0) & (p.Closing_Qty_Base <= 0)
    p["Stock_Data_Available"] = p.Month >= stock.Month.min()

    disc = p.Discount_vs_List_Pct
    dq("panel", "realized price >50% below list (possible UOM or promo issue)", (disc > 50).sum(), "flagged only")
    dq("panel", "realized price >20% above list", (disc < -20).sum(), "flagged only")
    p["Price_Check_Flag"] = (disc > 50) | (disc < -20)
    dq("panel", "monthly margin < -50% or > 80% (possible cost issue)",
       ((p.Margin_Pct_COGS < -50) | (p.Margin_Pct_COGS > 80)).sum(), "flagged Cost_Check_Flag")
    p["Cost_Check_Flag"] = (p.Margin_Pct_COGS < -50) | (p.Margin_Pct_COGS > 80)
    p = p.sort_values(k).reset_index(drop=True)
    p.to_parquet(OUT / "panel_monthly.parquet", index=False)
    return p


def coverage(p):
    c = p[p.Has_Sales].groupby("Month").agg(
        Rows=("ArticleCode", "size"), Sales_USD=("Sales_USD", "sum"),
        With_List_Price=("Has_List_Price", "mean"), With_Stock=("Has_Stock_Record", "mean"),
        Price_Flagged=("Price_Check_Flag", "mean"), With_COGS=("Unit_COGS_KZ", lambda x: x.notna().mean()),
        Net_KZ=("KZ_NetsSales", "sum"), COGS_KZ=("KZ_COGS", "sum"))
    c["Margin_Pct"] = ((1 - c.COGS_KZ / c.Net_KZ) * 100).round(1)
    for col in ["With_List_Price", "With_Stock", "Price_Flagged", "With_COGS"]:
        c[col] = (c[col] * 100).round(1)
    return c


def main():
    loc = build_dim_location()
    art = build_dim_article()
    plants = set(loc.Plant)
    arts = set(art.loc[art.In_Scope, "ArticleCode"])
    sales, observed = clean_sales(plants, arts)
    uom = build_uom(art, observed)
    price = clean_prices(plants, arts, uom)
    stock = clean_stock(plants, arts)
    panel = build_panel(sales, price, stock, loc, art)

    cov = coverage(panel)
    summary = pd.DataFrame([
        ("Panel rows (month x location x article)", len(panel)),
        ("  with sales", int(panel.Has_Sales.sum())),
        ("  stock only (no sales that month)", int((~panel.Has_Sales).sum())),
        ("Locations", panel.Plant.nunique()),
        ("Articles", panel.ArticleCode.nunique()),
        ("Months", panel.Month.nunique()),
        ("Sales USD", round(panel.Sales_USD.sum(), 0)),
        ("Net sales KZ", round(panel.KZ_NetsSales.sum(), 0)),
        ("COGS KZ", round(panel.KZ_COGS.sum(), 0)),
        ("Gross margin % (net sales - COGS)", round((1 - panel.KZ_COGS.sum() / panel.KZ_NetsSales.sum()) * 100, 1)),
        ("% sales rows with unit COGS", round(panel.loc[panel.Has_Sales, "Unit_COGS_KZ"].notna().mean() * 100, 1)),
        ("% sales rows with a list price", round(panel.loc[panel.Has_Sales, "Has_List_Price"].mean() * 100, 1)),
        ("Median realized / list price", round((panel.Realized_Price_KZ / panel.List_Price_End_KZ).median(), 3)),
    ], columns=["Metric", "Value"])
    with pd.ExcelWriter(ROOT / "data_quality_report.xlsx") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        pd.DataFrame(DQ).to_excel(xw, sheet_name="Cleaning checks", index=False)
        cov.to_excel(xw, sheet_name="Coverage by month")
    print(summary.to_string(index=False))
    print(cov.to_string())

    import add_price_indices  # inflation-adjusted and category-relative prices
    add_price_indices.main()


if __name__ == "__main__":
    main()
