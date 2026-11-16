"""Profit & margin analysis tables for the Profit and Margin PDF -> analysis/rda/pm_*.parquet + pm_numbers.json

Builds on rda_analysis.load_panel (actual COGS, with impossible COGS rows corrected) and the analysis/rda tables.
"""
import json

import numpy as np
import pandas as pd

from rda_analysis import CL, L12, OUT, P12, fin, load_panel

NUM = {}


def save(df, name):
    df.to_parquet(OUT / f"pm_{name}.parquet")
    print(f"  saved pm_{name} ({len(df)})", flush=True)


def margin_change(s):
    """sub-group and article margin, L12M vs prior 12M"""
    rows = []
    for per, months in [("L12", L12), ("P12", P12)]:
        g = s[s.Month.isin(months)].groupby(["MainGroup", "SubGroup"])[["Net_KZ", "COGS_KZ"]].sum()
        g = fin(g)
        g.columns = [f"{c}_{per}" for c in g.columns]
        rows.append(g)
    m = pd.concat(rows, axis=1)
    m["Margin_Change_pp"] = m.Margin_Pct_L12 - m.Margin_Pct_P12
    m["GP_Effect_KZ"] = m.Margin_Change_pp / 100 * m.Net_KZ_L12      # GP gained/lost from the margin change alone
    save(m.reset_index(), "subgroup_margin_change")

    # margin bridge P12 -> L12 by main group: mix vs rate
    g = {}
    for per, months in [("0", P12), ("1", L12)]:
        x = fin(s[s.Month.isin(months)].groupby("MainGroup")[["Net_KZ", "COGS_KZ"]].sum())
        x["Share"] = x.Net_KZ / x.Net_KZ.sum()
        g[per] = x
    b = pd.DataFrame({"s0": g["0"].Share, "s1": g["1"].Share, "m0": g["0"].Margin_Pct, "m1": g["1"].Margin_Pct}).fillna(0)
    b["Rate_pp"] = b.s1 * (b.m1 - b.m0)
    m0_chain = (g["0"].GP_KZ.sum() / g["0"].Net_KZ.sum()) * 100
    b["Mix_pp"] = (b.s1 - b.s0) * (b.m0 - m0_chain)   # gaining share above the chain margin lifts it
    save(b.reset_index(), "margin_bridge")
    NUM["bridge"] = {"m0": float((g["0"].GP_KZ.sum() / g["0"].Net_KZ.sum()) * 100),
                     "m1": float((g["1"].GP_KZ.sum() / g["1"].Net_KZ.sum()) * 100),
                     "rate": float(b.Rate_pp.sum()), "mix": float(b.Mix_pp.sum())}


def group_monthly(s):
    m = fin(s.groupby(["Month", "MainGroup"])[["Net_KZ", "COGS_KZ"]].sum()).reset_index()
    save(m, "group_month")
    y = fin(s.assign(Year=s.Month.str[:4]).groupby(["Year", "MainGroup"])[["Net_KZ", "COGS_KZ", "GP_Real"]].sum())
    save(y.reset_index(), "group_year_gp")
    i = fin(s.assign(Q=pd.PeriodIndex(s.Month, freq="M").asfreq("Q").astype(str))
            .groupby(["Q", "PurchaseType"])[["Net_KZ", "COGS_KZ"]].sum())
    save(i.reset_index(), "import_quarter")


def stores(s):
    st = s[s.Channel.eq("STORE")]
    m = fin(st.groupby(["Plant", "Store_Name", "Month"])[["Net_KZ", "COGS_KZ"]].sum()).reset_index()
    save(m, "store_month")
    rows = []
    for per, months in [("L12", L12), ("P12", P12)]:
        x = st[st.Month.isin(months)]
        g = fin(x.groupby(["Plant", "Store_Name"])[["Net_KZ", "COGS_KZ"]].sum())
        g["Months"] = x.groupby(["Plant", "Store_Name"]).Month.nunique()
        g.columns = [f"{c}_{per}" for c in g.columns]
        rows.append(g)
    c = pd.concat(rows, axis=1)
    c = c[(c.Months_L12 == 12) & (c.Months_P12 == 12)]
    c["Margin_Change_pp"] = c.Margin_Pct_L12 - c.Margin_Pct_P12
    save(c.reset_index(), "store_margin_change")

    # store x main group margin vs the median store for that main group (L12M) -> benchmark gap
    x = st[st.Month.isin(L12)]
    g = fin(x.groupby(["Plant", "Store_Name", "Area_Zone", "MainGroup"])[["Net_KZ", "COGS_KZ"]].sum()).reset_index()
    g = g[g.Net_KZ > 2e7]
    g["Bench_Margin"] = g.groupby("MainGroup").Margin_Pct.transform("median")
    g["Gap_pp"] = g.Margin_Pct - g.Bench_Margin
    g["Uplift_KZ"] = np.where(g.Gap_pp < 0, -g.Gap_pp / 100 * g.Net_KZ, 0)
    save(g, "store_group_gap")
    NUM["bench_uplift_kz"] = float(g.Uplift_KZ.sum())
    NUM["bench_uplift_pp"] = float(g.Uplift_KZ.sum() / x.Net_KZ.sum() * 100)


def leakage():
    """below-cost sales (COGS > 1.5x sales) by main group and store, L12M"""
    p = pd.read_parquet(CL / "panel_monthly.parquet", columns=["Plant", "ArticleCode", "MainGroup", "SubGroup",
                                                               "Store_Name"]).drop_duplicates(["Plant", "ArticleCode"])
    parts = []
    for f in sorted((CL / "sales_daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["Month", "Plant", "ArticleCode", "Sales_KZ", "KZ_COGS", "Below_Cost_50"])
        if d.Month.iloc[0] not in L12:
            continue
        d = d[d.Below_Cost_50]
        parts.append(d.groupby(["Plant", "ArticleCode"]).agg(Sales_KZ=("Sales_KZ", "sum"), COGS_KZ=("KZ_COGS", "sum"),
                                                            Rows=("Month", "size")))
    b = pd.concat(parts).groupby(level=[0, 1]).sum().reset_index()
    b["Loss_KZ"] = b.Sales_KZ - b.COGS_KZ
    b = b.merge(p, on=["Plant", "ArticleCode"], how="left")
    save(b.groupby("MainGroup")[["Sales_KZ", "Loss_KZ", "Rows"]].sum().reset_index().sort_values("Loss_KZ"),
         "below_cost_group")
    save(b.groupby(["Plant", "Store_Name"])[["Sales_KZ", "Loss_KZ", "Rows"]].sum().reset_index().sort_values("Loss_KZ"),
         "below_cost_store")
    a = b.groupby(["ArticleCode", "SubGroup"])[["Sales_KZ", "Loss_KZ", "Rows"]].sum().reset_index()
    names = pd.read_parquet(CL / "dim_article.parquet", columns=["ArticleCode", "ArticleName"])
    save(a.merge(names, on="ArticleCode", how="left").sort_values("Loss_KZ").head(20), "below_cost_article")
    NUM["below_cost_l12_kz"] = float(b.Loss_KZ.sum())


def articles():
    a = pd.read_parquet(OUT / "article_l12m.parquet")
    a = a[a.Net_KZ > 0].copy()
    a["Decile"] = pd.qcut(a.Net_KZ.rank(method="first"), 10, labels=[f"D{i}" for i in range(1, 11)])
    d = a.groupby("Decile", observed=True).agg(Articles=("ArticleCode", "size"), Net_KZ=("Net_KZ", "sum"),
                                               COGS_KZ=("COGS_KZ", "sum"), Loss_Makers=("GP_KZ", lambda x: (x < 0).sum()))
    save(fin(d).reset_index(), "decile")
    neg = a[a.GP_KZ < 0].groupby(["MainGroup", "SubGroup"]).agg(Articles=("ArticleCode", "size"),
                                                                 Loss_KZ=("GP_KZ", "sum"), Net_KZ=("Net_KZ", "sum"))
    save(neg.reset_index().sort_values("Loss_KZ").head(20), "loss_subgroups")
    NUM["n_articles"] = int(len(a))


def discount_cost(s):
    l = s[s.Month.isin(L12)]
    g = fin(l.groupby("MainGroup")[["Net_KZ", "COGS_KZ", "Disc_KZ"]].sum())
    g["Disc_of_GP_Pct"] = g.Disc_KZ / g.GP_KZ * 100
    save(g.reset_index(), "discount_cost")
    NUM["disc_l12_kz"] = float(l.Disc_KZ.sum())
    NUM["disc_l12_of_gp"] = float(l.Disc_KZ.sum() / (l.Net_KZ.sum() - l.COGS_KZ.sum()) * 100)


def main():
    p = load_panel()
    s = p[p.Has_Sales]
    margin_change(s)
    group_monthly(s)
    stores(s)
    discount_cost(s)
    del p, s
    leakage()
    articles()
    json.dump(NUM, open(OUT / "pm_numbers.json", "w"), indent=1, default=float)
    print(NUM)


if __name__ == "__main__":
    main()
