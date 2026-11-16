"""Retail Data Analysis (RDA): every table behind the RDA PDF report -> analysis/rda/*.parquet + numbers.json

Sources: clean/panel_monthly, clean/weekly_model, clean/sales_daily, analysis/article_elasticity, analysis/deep.
Money: net sales = KZ_NetsSales (after discount, excl. tax); gross profit = net sales - COGS (actual, from sales lines).
Real values are deflated by CPI (Jan 2023 = 100).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, A = ROOT / "clean", ROOT / "analysis"
OUT = A / "rda"
OUT.mkdir(parents=True, exist_ok=True)
NUM = {}
L12 = [str(p) for p in pd.period_range("2025-10", "2026-09", freq="M")]        # last 12 months
P12 = [str(p) for p in pd.period_range("2024-10", "2025-09", freq="M")]        # prior 12 months
YTD = lambda m: m.str[5:7].astype(int) <= 9                                     # Jan-Sep for year comparisons


def save(df, name):
    df = df.copy()
    for c in df.columns:
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(str)
    df.to_parquet(OUT / f"{name}.parquet")
    print(f"  saved {name} ({len(df)})", flush=True)


def fin(g):
    """standard money block for a grouped frame (sums already taken)"""
    g["GP_KZ"] = g.Net_KZ - g.COGS_KZ
    g["Margin_Pct"] = g.GP_KZ / g.Net_KZ * 100
    return g


def load_panel():
    cols = ["Month", "Plant", "ArticleCode", "Has_Sales", "Qty_Base", "Gross_Qty_Base", "KZ_NetsSales", "KZ_COGS",
            "KZ_Discount", "KZ_Tax", "USD_NetSales", "USD_COGS", "Sales_KZ", "Realized_Price_KZ", "Unit_COGS_KZ",
            "CPI_Deflator", "Days_Of_Cover", "Has_Stock_Record", "Out_Of_Stock", "Relative_Price", "Has_List_Price",
            "MainGroup", "SubGroup", "ArticleName", "BRAND_DESCR", "Store_Name", "Channel", "Area_Zone", "Store_Class",
            "Total_Sqm", "Open_Date", "Closing_Value_USD", "N_Below_Cost_Days", "Days_Sold", "Margin_Pct_COGS",
            "Discount_Pct_Of_Gross", "Price_Check_Flag", "Cost_Check_Flag"]
    p = pd.read_parquet(CL / "panel_monthly.parquet", columns=cols)
    art = pd.read_parquet(CL / "dim_article.parquet", columns=["ArticleCode", "PurchaseType"])
    p = p.merge(art, on="ArticleCode", how="left")
    p = p.rename(columns={"KZ_NetsSales": "Net_KZ", "KZ_COGS": "COGS_KZ", "KZ_Discount": "Disc_KZ", "KZ_Tax": "Tax_KZ",
                          "USD_NetSales": "Net_USD"})
    for c in ["Net_KZ", "COGS_KZ", "Disc_KZ", "Tax_KZ", "Net_USD", "USD_COGS"]:
        p[c] = p[c].fillna(0)
    # cost data errors: negative COGS or margin > 80% on a sale -> rebuild COGS from the article-store's normal unit cost
    raw_margin = (p.Net_KZ - p.COGS_KZ) / p.Net_KZ.where(p.Net_KZ > 0) * 100
    bad = p.Has_Sales & ((p.COGS_KZ < 0) | (raw_margin > 80))
    fix = bad & p.Unit_COGS_KZ.gt(0) & p.Qty_Base.gt(0)
    p["COGS_Raw_KZ"] = p.COGS_KZ
    p["COGS_Fixed"] = bad
    new = np.where(fix, p.Unit_COGS_KZ * p.Qty_Base, p.Net_KZ.clip(lower=0) * 0.8)
    p.loc[bad, "COGS_KZ"] = new[bad.to_numpy()]
    p.loc[bad, "USD_COGS"] = p.loc[bad, "COGS_KZ"] * (p.loc[bad, "Net_USD"] / p.loc[bad, "Net_KZ"]).fillna(0)
    NUM["cogs_fix"] = {"rows": int(bad.sum()), "rows_unit_cost": int(fix.sum()),
                       "raw_cogs_kz": float(p.loc[bad, "COGS_Raw_KZ"].sum()),
                       "fixed_cogs_kz": float(p.loc[bad, "COGS_KZ"].sum()),
                       "gp_change_kz": float(p.loc[bad, "COGS_Raw_KZ"].sum() - p.loc[bad, "COGS_KZ"].sum())}
    p["Defl"] = p.CPI_Deflator / 100
    p["Margin_Pct_COGS"] = ((p.Net_KZ - p.COGS_KZ) / p.Net_KZ * 100).where(p.Net_KZ > 0)
    p["Discount_Pct_Of_Gross"] = (p.Disc_KZ / (p.Net_KZ + p.Disc_KZ) * 100).where(p.Net_KZ > 0)
    p["Net_Real"] = p.Net_KZ / p.Defl
    p["GP_Real"] = (p.Net_KZ - p.COGS_KZ) / p.Defl
    return p


# ------------------------------------------------------------------ 1 data overview & quality
def data_overview(p):
    s = p[p.Has_Sales]
    y = s.assign(Year=s.Month.str[:4]).groupby("Year").agg(
        Rows=("ArticleCode", "size"), Price=("Realized_Price_KZ", lambda x: x.notna().mean() * 100),
        Unit_COGS=("Unit_COGS_KZ", lambda x: x.notna().mean() * 100),
        List_Price=("Has_List_Price", lambda x: x.mean() * 100),
        Stock=("Has_Stock_Record", lambda x: x.mean() * 100),
        Days_Of_Cover=("Days_Of_Cover", lambda x: x.notna().mean() * 100),
        Relative_Price=("Relative_Price", lambda x: x.notna().mean() * 100),
        Price_Flag=("Price_Check_Flag", lambda x: x.mean() * 100), Cost_Flag=("Cost_Check_Flag", lambda x: x.mean() * 100))
    save(y.reset_index(), "dq_completeness_year")
    dq = pd.read_excel(ROOT / "data_quality_report.xlsx", sheet_name="Cleaning checks")
    save(dq, "dq_checks")
    inv = [
        ("Sales lines (daily, cleaned)", int(sum(pd.read_parquet(f, columns=["Plant"]).shape[0]
                                                 for f in (CL / "sales_daily").glob("*.parquet")))),
        ("Monthly panel (month x location x article)", len(p)),
        ("  of which with sales", int(p.Has_Sales.sum())),
        ("Weekly model rows", int(pd.read_parquet(CL / "weekly_model.parquet", columns=["Week"]).shape[0])),
        ("Locations with sales", s.Plant.nunique()), ("Articles with sales", s.ArticleCode.nunique()),
        ("Months", s.Month.nunique())]
    save(pd.DataFrame(inv, columns=["Item", "Value"]), "dq_inventory")
    NUM["n_locations"], NUM["n_articles"] = int(s.Plant.nunique()), int(s.ArticleCode.nunique())


# ------------------------------------------------------------------ 2 sales, revenue & profit trends
def trends(p):
    s = p[p.Has_Sales]
    m = s.groupby("Month").agg(Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"), Disc_KZ=("Disc_KZ", "sum"),
                               Tax_KZ=("Tax_KZ", "sum"), Net_USD=("Net_USD", "sum"), COGS_USD=("USD_COGS", "sum"),
                               Net_Real=("Net_Real", "sum"), GP_Real=("GP_Real", "sum"), Qty=("Qty_Base", "sum"),
                               Locations=("Plant", "nunique"), Articles=("ArticleCode", "nunique"))
    m = fin(m)
    m["GP_USD"] = m.Net_USD - m.COGS_USD
    m["Disc_Pct"] = m.Disc_KZ / (m.Net_KZ + m.Disc_KZ) * 100
    mac = p.drop_duplicates("Month").set_index("Month")[["CPI_Deflator"]]
    macro = pd.read_parquet(CL / "macro_monthly.parquet").set_index("Month")
    m = m.join(mac).join(macro[["FX_BNA_Avg", "Inflation_YoY_Pct", "Brent_USD", "GDP_Real_YoY_Pct_Q"]])
    save(m.reset_index(), "monthly_chain")

    y = s[YTD(s.Month)].assign(Year=lambda d: d.Month.str[:4]).groupby("Year").agg(
        Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"), Net_USD=("Net_USD", "sum"), Net_Real=("Net_Real", "sum"),
        GP_Real=("GP_Real", "sum"), Locations=("Plant", "nunique"), Articles=("ArticleCode", "nunique"))
    y = fin(y)
    for c in ["Net_KZ", "Net_USD", "Net_Real", "GP_Real"]:
        y[c + "_Growth"] = y[c].pct_change() * 100
    save(y.reset_index(), "yearly_ytd")
    NUM["ytd"] = y.round(2).reset_index().to_dict("records")

    # like-for-like: locations with sales in every month Jan 2023 - Sep 2026
    full = s.groupby("Plant").Month.nunique()
    lfl = full[full == s.Month.nunique()].index
    l = s[s.Plant.isin(lfl)].groupby("Month").agg(Net_Real=("Net_Real", "sum"), GP_Real=("GP_Real", "sum"),
                                                  Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"))
    save(fin(l).reset_index(), "monthly_lfl")
    NUM["lfl_stores"] = len(lfl)

    g = s.assign(Year=s.Month.str[:4]).groupby(["MainGroup", "Year"]).agg(
        Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"), Net_Real=("Net_Real", "sum"))
    save(fin(g).reset_index(), "maingroup_year")
    q = s.assign(Q=pd.PeriodIndex(s.Month, freq="M").asfreq("Q").astype(str)).groupby(["MainGroup", "Q"]).agg(
        Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"))
    save(fin(q).reset_index(), "maingroup_quarter")
    sh = s.groupby(["Month", "MainGroup"]).Net_Real.sum().unstack().fillna(0)
    save(sh.reset_index(), "maingroup_month_real")


# ------------------------------------------------------------------ 3 product / category / store performance
def performance(p):
    s = p[p.Has_Sales]
    l12, p12 = s[s.Month.isin(L12)], s[s.Month.isin(P12)]
    ae = pd.read_parquet(A / "article_elasticity.parquet")[["ArticleCode", "Elasticity", "SE", "Shrink_Weight", "Class"]]

    # articles
    a = l12.groupby("ArticleCode").agg(Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"), Qty=("Qty_Base", "sum"),
                                       Net_Real=("Net_Real", "sum"), Locations=("Plant", "nunique"),
                                       Disc_KZ=("Disc_KZ", "sum"))
    a = fin(a)
    a["Prior_Net_Real"] = p12.groupby("ArticleCode").Net_Real.sum()
    a["Growth_Real_Pct"] = (a.Net_Real / a.Prior_Net_Real - 1) * 100
    info = s.drop_duplicates("ArticleCode").set_index("ArticleCode")[
        ["ArticleName", "MainGroup", "SubGroup", "BRAND_DESCR", "PurchaseType"]]
    a = a.join(info).reset_index().merge(ae, on="ArticleCode", how="left")
    a = a.sort_values("Net_KZ", ascending=False)
    a["Cum_Sales_Pct"] = a.Net_KZ.cumsum() / a.Net_KZ.sum() * 100
    a["Rank_Pct"] = np.arange(1, len(a) + 1) / len(a) * 100
    save(a, "article_l12m")
    gp = a.sort_values("GP_KZ", ascending=False)
    NUM["pareto"] = {
        "articles_l12m": len(a),
        "top20_sales_share": float(a.loc[a.Rank_Pct <= 20, "Net_KZ"].sum() / a.Net_KZ.sum() * 100),
        "top20_gp_share": float(gp.GP_KZ.head(int(len(gp) * .2)).sum() / gp.GP_KZ.sum() * 100),
        "n_for_80_sales": int((a.Cum_Sales_Pct <= 80).sum() + 1),
        "n_neg_gp": int((a.GP_KZ < 0).sum()), "neg_gp_kz": float(a.loc[a.GP_KZ < 0, "GP_KZ"].sum())}

    # sub-groups
    e = ae.merge(info[["SubGroup"]].reset_index(), on="ArticleCode").merge(
        a[["ArticleCode", "Net_KZ"]], on="ArticleCode", how="left")
    e = e[e.Net_KZ > 0].groupby("SubGroup").apply(
        lambda d: np.average(d.Elasticity, weights=d.Net_KZ), include_groups=False).rename("Elasticity")
    sg = l12.groupby(["MainGroup", "SubGroup"]).agg(Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"),
                                                     Net_Real=("Net_Real", "sum"), Articles=("ArticleCode", "nunique"),
                                                     Disc_KZ=("Disc_KZ", "sum"))
    sg = fin(sg)
    sg["Prior_Net_Real"] = p12.groupby(["MainGroup", "SubGroup"]).Net_Real.sum()
    sg["Growth_Real_Pct"] = (sg.Net_Real / sg.Prior_Net_Real - 1) * 100
    sg["Import_Share"] = l12[l12.PurchaseType.eq("Import")].groupby(["MainGroup", "SubGroup"]).Net_KZ.sum() / sg.Net_KZ * 100
    sg = sg.reset_index().merge(e.reset_index(), on="SubGroup", how="left")
    sg["Sales_Share"] = sg.Net_KZ / sg.Net_KZ.sum() * 100
    save(sg.sort_values("Net_KZ", ascending=False), "subgroup_l12m")

    mg = l12.groupby("MainGroup").agg(Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"), Net_Real=("Net_Real", "sum"),
                                      Disc_KZ=("Disc_KZ", "sum"), Articles=("ArticleCode", "nunique"))
    mg = fin(mg)
    mg["Prior_Net_Real"] = p12.groupby("MainGroup").Net_Real.sum()
    mg["Growth_Real_Pct"] = (mg.Net_Real / mg.Prior_Net_Real - 1) * 100
    mg["Sales_Share"] = mg.Net_KZ / mg.Net_KZ.sum() * 100
    mg["GP_Share"] = mg.GP_KZ / mg.GP_KZ.sum() * 100
    save(mg.sort_values("Net_KZ", ascending=False).reset_index(), "maingroup_l12m")

    imp = l12.groupby("PurchaseType").agg(Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"),
                                          Articles=("ArticleCode", "nunique"))
    save(fin(imp).reset_index(), "import_local_l12m")

    # stores
    st = l12.groupby("Plant").agg(Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum"), Net_Real=("Net_Real", "sum"),
                                  Articles=("ArticleCode", "nunique"), Months=("Month", "nunique"))
    st = fin(st)
    st["Prior_Net_Real"] = p12.groupby("Plant").Net_Real.sum()
    st["Prior_Months"] = p12.groupby("Plant").Month.nunique()
    st["Growth_Real_Pct"] = np.where(st.Prior_Months == 12, (st.Net_Real / st.Prior_Net_Real - 1) * 100, np.nan)
    loc = s.drop_duplicates("Plant").set_index("Plant")[["Store_Name", "Channel", "Area_Zone", "Store_Class",
                                                         "Total_Sqm", "Open_Date"]]
    st = st.join(loc)
    st["Sales_per_Sqm_Month_KZ"] = st.Net_KZ / st.Months / st.Total_Sqm
    st["GP_per_Sqm_Month_KZ"] = st.GP_KZ / st.Months / st.Total_Sqm
    st["Elasticity"] = pd.read_parquet(A / "deep" / "elasticity_store.parquet").set_index("Plant").Elasticity
    st["Price_Premium_Pct"] = pd.read_parquet(A / "deep" / "store_price_premium.parquet").set_index(
        "Plant").Price_Premium_pct
    save(st.reset_index().sort_values("Net_KZ", ascending=False), "store_l12m")

    # margin heatmaps
    for dim, name in [("Area_Zone", "margin_group_zone"), ("Store_Class", "margin_group_class")]:
        h = l12[l12.Channel.eq("STORE")].groupby(["MainGroup", dim])[["Net_KZ", "COGS_KZ"]].sum()
        save(fin(h).reset_index(), name)

    # sales-weighted margin distribution across articles
    save(a[a.Net_KZ > 0][["ArticleCode", "Margin_Pct", "Net_KZ", "MainGroup"]], "article_margin_dist")


# ------------------------------------------------------------------ 4 price & cost indices, pass-through
def price_cost(p):
    s = p[p.Has_Sales & p.Realized_Price_KZ.gt(0)].sort_values(["Plant", "ArticleCode", "Month"])
    s = s[["Month", "Plant", "ArticleCode", "MainGroup", "Realized_Price_KZ", "Unit_COGS_KZ", "Net_KZ"]].copy()
    per = pd.PeriodIndex(s.Month, freq="M")
    s["mi"] = per.year * 12 + per.month
    g = s.groupby(["Plant", "ArticleCode"])
    cons = g.mi.diff() == 1
    s["dp"] = np.log(s.Realized_Price_KZ).groupby([s.Plant, s.ArticleCode]).diff()
    s["dc"] = np.log(s.Unit_COGS_KZ).groupby([s.Plant, s.ArticleCode]).diff()
    s["w"] = (s.Net_KZ + g.Net_KZ.shift(1)) / 2
    ok = cons & s.dp.abs().lt(np.log(3)) & s.dc.abs().lt(np.log(3)) & s.w.gt(0)
    d = s[ok]

    def chain(x):
        r = x.groupby("Month").apply(lambda z: pd.Series({"dp": np.average(z.dp, weights=z.w),
                                                         "dc": np.average(z.dc, weights=z.w)}), include_groups=False)
        return np.exp(r.cumsum()) * 100
    idx = chain(d)
    first = pd.DataFrame({"dp": [100.0], "dc": [100.0]}, index=["2023-01"])
    idx = pd.concat([first, idx]).rename(columns={"dp": "Price_Index", "dc": "Cost_Index"})
    macro = pd.read_parquet(CL / "macro_monthly.parquet").set_index("Month")
    idx = idx.join(macro[["CPI_Rebased_Jan2023", "FX_BNA_Avg"]])
    idx["FX_Index"] = idx.FX_BNA_Avg / idx.FX_BNA_Avg.iloc[0] * 100
    save(idx.reset_index().rename(columns={"index": "Month"}), "price_cost_index")
    NUM["idx_last"] = idx.iloc[-1].round(1).to_dict()
    NUM["idx_month_last"] = idx.index[-1]

    gi = []
    for mgp, x in d.groupby("MainGroup"):
        if len(x) < 5000:
            continue
        r = chain(x)
        r["MainGroup"] = mgp
        gi.append(r.reset_index())
    save(pd.concat(gi), "price_cost_index_group")

    # quarterly pass-through of unit-cost changes into selling prices, per main group
    s["Q"] = per.asfreq("Q").astype(str)
    q = s.groupby(["Plant", "ArticleCode", "MainGroup", "Q"]).agg(P=("Realized_Price_KZ", "median"),
                                                                  C=("Unit_COGS_KZ", "median"), W=("Net_KZ", "sum"))
    q = q.reset_index().sort_values(["Plant", "ArticleCode", "Q"])
    qi = pd.PeriodIndex(q.Q, freq="Q")
    q["qi"] = qi.year * 4 + qi.quarter
    q["dP"] = np.log(q.P).groupby([q.Plant, q.ArticleCode]).diff()
    q["dC"] = np.log(q.C).groupby([q.Plant, q.ArticleCode]).diff()
    q["dC1"] = q.groupby(["Plant", "ArticleCode"]).dC.shift(1)
    q["cons"] = q.groupby(["Plant", "ArticleCode"]).qi.diff() == 1
    q["cons1"] = q.groupby(["Plant", "ArticleCode"]).cons.shift(1).fillna(False).astype(bool)
    q = q[q.cons & q.cons1]
    q = q[q.dP.abs().lt(np.log(3)) & q.dC.abs().lt(np.log(3)) & q.dC1.abs().lt(np.log(3)) & q.W.gt(0)]
    rows = []
    for mgp, x in list(q.groupby("MainGroup")) + [("ALL", q)]:
        if len(x) < 2000:
            continue
        X = np.column_stack([np.ones(len(x)), x.dC, x.dC1])
        sw = np.sqrt(x.W.to_numpy())
        b = np.linalg.lstsq(X * sw[:, None], x.dP.to_numpy() * sw, rcond=None)[0]
        corr = np.corrcoef(x.dC, x.dP)[0, 1]
        rows.append({"MainGroup": mgp, "Same_Quarter": b[1] * 100, "Next_Quarter": b[2] * 100,
                     "Cumulative": (b[1] + b[2]) * 100, "Corr": corr, "Obs": len(x)})
    pt = pd.DataFrame(rows)
    save(pt, "cost_passthrough")
    NUM["cost_pt_all"] = pt[pt.MainGroup == "ALL"].round(1).to_dict("records")[0]


# ------------------------------------------------------------------ 5 correlations
def correlations(p):
    s = p[p.Has_Sales & p.Realized_Price_KZ.gt(0) & p.Unit_COGS_KZ.gt(0) & p.Qty_Base.gt(0)].copy()
    s["ln Real price"] = np.log(s.Realized_Price_KZ / s.Defl)
    s["ln Real unit cost"] = np.log(s.Unit_COGS_KZ / s.Defl)
    s["ln Units sold"] = np.log(s.Qty_Base)
    s["ln Real net sales"] = np.log(s.Net_Real.clip(lower=1))
    s["Gross margin %"] = s.Margin_Pct_COGS.clip(-50, 80)
    s["Discount %"] = s.Discount_Pct_Of_Gross.clip(0, 50).fillna(0)
    s["ln Relative price"] = np.log(s.Relative_Price)
    s["ln Days of cover"] = np.log1p(s.Days_Of_Cover.clip(0, 365))
    s["Days sold"] = s.Days_Sold
    v = ["ln Real price", "ln Units sold", "ln Real net sales", "Gross margin %", "ln Real unit cost", "Discount %",
         "ln Relative price", "ln Days of cover", "Days sold"]
    x = s[["Plant", "ArticleCode"] + v].replace([np.inf, -np.inf], np.nan)
    within = x[v] - x.groupby(["Plant", "ArticleCode"])[v].transform("mean")
    save(within.corr().reset_index(), "corr_within")
    NUM["corr_n"] = int(within.dropna().shape[0])

    a = pd.read_parquet(OUT / "subgroup_l12m.parquet")
    pc = pd.read_parquet(OUT / "price_cost_index_group.parquet")
    sgv = a[a.Net_KZ > 5e8].rename(columns={"Margin_Pct": "Gross margin %", "Growth_Real_Pct": "Real growth %",
                                            "Elasticity": "Elasticity", "Import_Share": "Import share %"})
    sgv["ln Net sales"] = np.log(sgv.Net_KZ)
    sgv["Discount %"] = sgv.Disc_KZ / (sgv.Net_KZ + sgv.Disc_KZ) * 100
    cv = ["Gross margin %", "Elasticity", "Real growth %", "Import share %", "ln Net sales", "Discount %"]
    save(sgv[cv].corr(method="spearman").reset_index(), "corr_subgroup")
    NUM["corr_subgroup_n"] = len(sgv)

    m = pd.read_parquet(OUT / "monthly_chain.parquet").set_index("Month")
    ix = pd.read_parquet(OUT / "price_cost_index.parquet").set_index("Month")
    mm = pd.DataFrame({"Real net sales": m.Net_Real, "Real gross profit": m.GP_Real, "Gross margin %": m.Margin_Pct,
                       "Price index": ix.Price_Index, "Cost index": ix.Cost_Index, "FX (BNA)": m.FX_BNA_Avg,
                       "Inflation YoY": m.Inflation_YoY_Pct, "Brent USD": m.Brent_USD,
                       "Real GDP YoY": m.GDP_Real_YoY_Pct_Q, "Locations": m.Locations})
    save(mm.corr().reset_index(), "corr_macro_monthly")


# ------------------------------------------------------------------ 6 discounts & temporary price reductions
def discounts(p):
    s = p[p.Has_Sales]
    d = s.groupby("MainGroup").agg(Net_KZ=("Net_KZ", "sum"), Disc_KZ=("Disc_KZ", "sum"),
                                   Rows=("ArticleCode", "size"), Disc_Rows=("Disc_KZ", lambda x: (x > 0).sum()))
    d["Disc_Pct"] = d.Disc_KZ / (d.Net_KZ + d.Disc_KZ) * 100
    d["Share_Rows_Discounted"] = d.Disc_Rows / d.Rows * 100
    save(d.reset_index().sort_values("Disc_KZ", ascending=False), "discount_group")
    NUM["disc_total_pct"] = float(s.Disc_KZ.sum() / (s.Net_KZ.sum() + s.Disc_KZ.sum()) * 100)
    NUM["disc_rows_pct"] = float((s.Disc_KZ > 0).mean() * 100)

    # discount depth vs volume, within article-store (month level)
    x = s[s.Qty_Base.gt(0)][["Plant", "ArticleCode", "Qty_Base", "Disc_KZ", "Net_KZ", "Margin_Pct_COGS"]].copy()
    x["dp"] = (x.Disc_KZ / (x.Net_KZ + x.Disc_KZ) * 100).clip(0, 50)
    x["lq"] = np.log(x.Qty_Base)
    x["lq_dev"] = x.lq - x.groupby(["Plant", "ArticleCode"]).lq.transform("mean")
    x["mc"] = x.Margin_Pct_COGS.clip(-50, 80)
    x["m_dev"] = x.mc - x.groupby(["Plant", "ArticleCode"]).mc.transform("mean")
    x["Bucket"] = pd.cut(x.dp, [-.01, 0, 1, 3, 5, 10, 50], labels=["0%", "0-1%", "1-3%", "3-5%", "5-10%", ">10%"])
    b = x.groupby("Bucket", observed=True).agg(Rows=("lq", "size"), Volume_vs_Usual_Pct=("lq_dev", "mean"),
                                               Margin_vs_Usual_pp=("m_dev", "mean"))
    b["Volume_vs_Usual_Pct"] = (np.exp(b.Volume_vs_Usual_Pct) - 1) * 100
    save(b.reset_index(), "discount_depth_volume")


def tpr():
    """Temporary price reductions (promotion proxy) from the weekly model sample."""
    cols = ["Week", "Plant", "ArticleCode", "MainGroup", "SubGroup", "Qty_Clean", "Realized_Price_KZ", "KZ_NetsSales",
            "KZ_COGS", "In_Model_Sample"]
    w = pd.read_parquet(CL / "weekly_model.parquet", columns=cols)
    w = w[w.In_Model_Sample].drop(columns="In_Model_Sample").sort_values(["Plant", "ArticleCode", "Week"])
    w["GP"] = w.KZ_NetsSales - w.KZ_COGS
    w = w.reset_index(drop=True)
    g = w.groupby(["Plant", "ArticleCode"], sort=False)
    for c in ["Realized_Price_KZ", "Qty_Clean", "GP"]:   # median of the previous 6 weeks
        sh = g[c].shift(1)
        r = sh.groupby([w.Plant, w.ArticleCode], sort=False).rolling(6, min_periods=4).median()
        w[f"base_{c}"] = r.reset_index(level=[0, 1], drop=True).sort_index()
        print(f"  baseline {c}", flush=True)
    w["nxt_p"] = g.Realized_Price_KZ.shift(-2)
    w["nxt_q"] = g.Qty_Clean.shift(-1)
    w["depth"] = 1 - w.Realized_Price_KZ / w.base_Realized_Price_KZ
    w["lift"] = w.Qty_Clean / w.base_Qty_Clean - 1
    is_tpr = (w.depth >= .10) & (w.depth <= .60) & (w.nxt_p >= .95 * w.base_Realized_Price_KZ)
    normal = w.depth.abs() < .02
    # control: median lift of normally-priced articles in the same sub-group and week
    ctrl = w[normal].groupby(["SubGroup", "Week"]).lift.median().rename("ctrl")
    e = w[is_tpr].join(ctrl, on=["SubGroup", "Week"])
    e["Adj_Lift"] = (1 + e.lift) / (1 + e.ctrl.fillna(0)) - 1
    e["GP_Change"] = e.GP - e.base_GP
    e["Post_Week_Vol"] = e.nxt_q / e.base_Qty_Clean - 1
    e["Depth_Bucket"] = pd.cut(e.depth, [.1, .15, .2, .3, .6], labels=["10-15%", "15-20%", "20-30%", "30-60%"],
                               include_lowest=True)
    e["Promo_Elasticity"] = np.log1p(e.Adj_Lift) / np.log(1 - e.depth)
    e = e.replace([np.inf, -np.inf], np.nan)
    keep = ["Week", "Plant", "ArticleCode", "MainGroup", "SubGroup", "depth", "lift", "Adj_Lift", "GP", "base_GP",
            "GP_Change", "Post_Week_Vol", "Depth_Bucket", "Promo_Elasticity", "KZ_NetsSales"]
    save(e[keep], "tpr_events")
    summ = lambda d: pd.Series({
        "Events": len(d), "Median_Depth_Pct": d.depth.median() * 100, "Median_Raw_Lift_Pct": d.lift.median() * 100,
        "Median_Adj_Lift_Pct": d.Adj_Lift.median() * 100, "Median_Promo_Elasticity": d.Promo_Elasticity.median(),
        "Share_GP_Up_Pct": (d.GP_Change > 0).mean() * 100, "Median_Post_Week_Vol_Pct": d.Post_Week_Vol.median() * 100,
        "Total_GP_Change_KZ": d.GP_Change.sum()})
    save(e.groupby("Depth_Bucket", observed=True).apply(summ, include_groups=False).reset_index(), "tpr_by_depth")
    mg = e.groupby("MainGroup").apply(summ, include_groups=False)
    save(mg[mg.Events >= 100].reset_index().sort_values("Events", ascending=False), "tpr_by_group")
    NUM["tpr"] = summ(e).round(2).to_dict()
    NUM["tpr_share_weeks"] = float(is_tpr.mean() * 100)


# ------------------------------------------------------------------ 7 demand curves & price-response simulation
def demand_curves():
    w = pd.read_parquet(CL / "weekly_model.parquet", columns=["Plant", "ArticleCode", "Week", "SubGroup", "ln_Qty",
                                                              "ln_Relative_Price", "In_Model_Sample"])
    w = w[w.In_Model_Sample]
    k = ["Plant", "ArticleCode"]
    w["x"] = w.ln_Relative_Price - w.groupby(k).ln_Relative_Price.transform("mean")
    w["y"] = w.ln_Qty - w.groupby(k).ln_Qty.transform("mean")
    w["y"] = w.y - w.groupby(["SubGroup", "Week"]).y.transform("mean")      # remove category-week demand swings
    w = w[w.x.abs() < np.log(1.5)]
    out = []
    top = pd.read_parquet(OUT / "subgroup_l12m.parquet").nlargest(8, "Net_KZ").SubGroup.tolist()
    for name, d in [("ALL", w)] + [(sg, w[w.SubGroup == sg]) for sg in top]:
        d = d.copy()
        d["bin"] = pd.qcut(d.x, 20, duplicates="drop")
        b = d.groupby("bin", observed=True).agg(x=("x", "mean"), y=("y", "mean"), n=("y", "size"))
        slope = np.polyfit(d.x, d.y, 1)[0]
        b["SubGroup"], b["Slope"] = name, slope
        out.append(b.reset_index(drop=True))
    save(pd.concat(out), "demand_binscatter")


def simulate():
    sg = pd.read_parquet(OUT / "subgroup_l12m.parquet").dropna(subset=["Elasticity"]).nlargest(10, "Net_KZ")
    d = np.linspace(-.2, .2, 41)
    rows = []
    for _, r in sg.iterrows():
        m, e = r.Margin_Pct / 100, r.Elasticity
        vol = (1 + d) ** e
        rev = (1 + d) * vol
        gp = ((1 + d) - (1 - m)) / m * vol
        for di, v, rv, g in zip(d, vol, rev, gp):
            rows.append({"SubGroup": r.SubGroup, "Price_Change": di * 100, "Volume_Index": v * 100,
                         "Revenue_Index": rv * 100, "GP_Index": g * 100, "Elasticity": e, "Margin_Pct": r.Margin_Pct})
    save(pd.DataFrame(rows), "simulation_curves")


# ------------------------------------------------------------------ 8 opportunities
def opportunities():
    a = pd.read_parquet(OUT / "article_l12m.parquet")
    a = a[a.Elasticity.between(-6, 0) & a.Net_KZ.gt(0) & a.Margin_Pct.between(1, 80) & a.Locations.ge(10)].copy()
    m = a.Margin_Pct / 100
    for step, col in [(.05, "GP_Chg_Up5_Pct"), (-.05, "GP_Chg_Dn5_Pct")]:
        a[col] = (((1 + step) - (1 - m)) / m * (1 + step) ** a.Elasticity - 1) * 100
    a["GP_Chg_Up5_KZ"] = a.GP_Chg_Up5_Pct / 100 * a.GP_KZ
    a["GP_Chg_Dn5_KZ"] = a.GP_Chg_Dn5_Pct / 100 * a.GP_KZ
    a["Optimal_Margin_Pct"] = np.where(a.Elasticity < -1, -100 / a.Elasticity, np.nan)
    rise = a[(a.Elasticity > -0.8) & (a.Shrink_Weight >= .3) & (a.Margin_Pct < 30)].nlargest(25, "GP_Chg_Up5_KZ")
    cut = a[(a.Elasticity < -2.5) & (a.Shrink_Weight >= .3)].nlargest(25, "GP_Chg_Dn5_KZ")
    save(rise, "opp_price_rise")
    save(cut[cut.GP_Chg_Dn5_KZ > 0], "opp_price_cut")
    NUM["opp"] = {"rise_n": int(len(rise)), "rise_gp_kz": float(rise.GP_Chg_Up5_KZ.sum()),
                  "cut_n": int((cut.GP_Chg_Dn5_KZ > 0).sum()), "cut_gp_kz": float(cut.GP_Chg_Dn5_KZ.clip(lower=0).sum()),
                  "all_rise_candidates": int(((a.Elasticity > -0.8) & (a.Shrink_Weight >= .3) & (a.Margin_Pct < 30)).sum())}


# ------------------------------------------------------------------ 9 anomalies
def anomalies(p):
    rows = []
    for f in sorted((CL / "sales_daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["Month", "Plant", "ArticleCode", "Sales_KZ", "KZ_COGS", "Price_Outlier",
                                        "Cost_Outlier", "Below_Cost_50", "Is_Return"])
        rows.append(pd.DataFrame({
            "Month": [d.Month.iloc[0]], "Rows": [len(d)], "Price_Outliers": [d.Price_Outlier.sum()],
            "Cost_Outliers": [d.Cost_Outlier.sum()], "Below_Cost_Rows": [d.Below_Cost_50.sum()],
            "Below_Cost_Sales_KZ": [d.loc[d.Below_Cost_50, "Sales_KZ"].sum()],
            "Below_Cost_Loss_KZ": [(d.loc[d.Below_Cost_50, "Sales_KZ"] - d.loc[d.Below_Cost_50, "KZ_COGS"]).sum()],
            "Returns": [d.Is_Return.sum()], "Sales_KZ": [d.Sales_KZ.sum()]}))
    an = pd.concat(rows)
    save(an, "anomaly_monthly")
    NUM["below_cost_loss_kz"] = float(an.Below_Cost_Loss_KZ.sum())
    NUM["below_cost_share"] = float(an.Below_Cost_Sales_KZ.sum() / an.Sales_KZ.sum() * 100)

    a = pd.read_parquet(OUT / "article_l12m.parquet")
    save(a[a.GP_KZ < 0].nsmallest(20, "GP_KZ"), "neg_gp_articles")
    f = p[p.COGS_Fixed].groupby(["ArticleCode", "ArticleName", "SubGroup"]).agg(
        Months=("Month", "nunique"), Locations=("Plant", "nunique"), Net_KZ=("Net_KZ", "sum"),
        Raw_COGS_KZ=("COGS_Raw_KZ", "sum"), Fixed_COGS_KZ=("COGS_KZ", "sum")).reset_index()
    f["Raw_Margin_Pct"] = (1 - f.Raw_COGS_KZ / f.Net_KZ) * 100
    save(f.sort_values("Raw_COGS_KZ").head(15), "cogs_fixed_articles")

    # store-month real sales vs the store's own trend (robust z-score)
    s = p[p.Has_Sales & p.Channel.eq("STORE")].groupby(["Plant", "Store_Name", "Month"]).agg(
        Net_Real=("Net_Real", "sum"), Net_KZ=("Net_KZ", "sum"), COGS_KZ=("COGS_KZ", "sum")).reset_index()
    s = fin(s).sort_values(["Plant", "Month"])
    s["ln"] = np.log(s.Net_Real.clip(lower=1))
    s["trend"] = s.groupby("Plant").ln.transform(lambda x: x.rolling(7, center=True, min_periods=4).median())
    s["dev"] = s.ln - s.trend
    mad = s.groupby("Plant").dev.transform(lambda x: (x - x.median()).abs().median()) * 1.4826
    s["z"] = s.dev / mad.replace(0, np.nan)
    s["Margin_dev"] = s.Margin_Pct - s.groupby("Plant").Margin_Pct.transform("median")
    save(s, "store_month_anomaly")
    save(s[(s.z.abs() > 3.5) | (s.Margin_dev.abs() > 6)].sort_values("z"), "store_month_flags")


def main():
    print("panel ...", flush=True)
    p = load_panel()
    data_overview(p)
    trends(p)
    performance(p)
    price_cost(p)
    correlations(p)
    discounts(p)
    anomalies(p)
    del p
    tpr()
    demand_curves()
    simulate()
    opportunities()
    json.dump(NUM, open(OUT / "numbers.json", "w"), indent=1, default=float)
    print("RDA analysis done")


if __name__ == "__main__":
    main()
