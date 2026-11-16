"""All-SKU step 1: SKUs selling below cost (or at a very thin margin) on the refreshed data, and the price fix.

Window: the last 8 full weeks of clean/weekly_model.parquet (the partial last week is left out), chain level.
For every SKU still on the shelf it diagnoses why the margin is gone and proposes a new shelf price:
  target margin = the SKU's SubGroup median margin (healthy SKUs), between 5% and 15%;
  one step is at most +15%; larger gaps are split and flagged for a second step.
Volume impact uses the Phase 1 shrunk elasticity (clipped -3..-0.5; SubGroup median if missing), cautious = 1.5x.

Margins, prices and GP are NET of IVA (user decision 2026-11-15): sales are scaled by the SKU's recorded tax share
in the same weeks (clean/allsku/chain_weekly.parquet). Shelf prices stay incl. IVA; the % change is the same.

Outputs: clean/allsku/below_cost.parquet, analysis/allsku/below_cost_review.xlsx
"""
from pathlib import Path

import numpy as np
import pandas as pd

import pilot_recommend as R

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
WEEKS = 8
THIN = 5.0              # % margin under which a SKU is reviewed
TARGET_MIN, TARGET_MAX = 5.0, 15.0
MAX_STEP = 15.0         # % rise in one step
FX = 1050.0             # internal Kz per USD (sales data, Oct-Nov 2026)


def z(c):
    return str(c).lstrip("0")


def main():
    CL.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    cols = ["Week", "Plant", "ArticleCode", "Qty_Clean", "Sales_KZ", "KZ_COGS", "Channel", "ArticleName", "SubGroup",
            "MainGroup", "Import", "BRAND_DESCR"]
    w = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=cols)
    w["c"] = w.ArticleCode.map(z)
    w = w[w.Channel != "HRCA"]                                  # negotiated B2B prices, not shelf prices
    full = sorted(w.Week.unique())[:-1]                         # drop the partial last week
    end = full[-1]
    win = w[w.Week.isin(full[-WEEKS:])]
    prev = w[w.Week.isin(full[-WEEKS - 26:-26])]                # same 8 weeks, 6 months earlier

    cwt = pd.read_parquet(ROOT / "clean" / "allsku" / "chain_weekly.parquet", columns=["Code", "Week", "Sales_KZ", "Tax_KZ"])

    def agg(d):
        g = d.groupby("c").agg(sales=("Sales_KZ", "sum"), cogs=("KZ_COGS", "sum"), qty=("Qty_Clean", "sum"),
                               stores=("Plant", "nunique"), weeks=("Week", "nunique"))
        tx = cwt[cwt.Week.isin(d.Week.unique())].groupby("Code")[["Sales_KZ", "Tax_KZ"]].sum()
        g["sales"] = g.sales * (1 - (tx.Tax_KZ / tx.Sales_KZ).reindex(g.index).fillna(0))     # net of IVA
        g["gp_pct"] = (g.sales - g.cogs) / g.sales * 100
        g["price"] = g.sales / g.qty
        g["cost"] = g.cogs / g.qty
        return g

    now, old = agg(win), agg(prev)
    info = win.groupby("c")[["ArticleName", "SubGroup", "MainGroup", "Import", "BRAND_DESCR"]].first()
    nw = cwt.set_index(["Code", "Week"])
    wk = win.groupby(["c", "Week"]).agg(s=("Sales_KZ", "sum"), k=("KZ_COGS", "sum"))
    share = (nw.Tax_KZ / nw.Sales_KZ).reindex(wk.index).fillna(0).values
    below_wks = (wk.s * (1 - share) < wk.k).groupby(level=0).sum().rename("weeks_below_cost")
    l4 = w[w.Week.isin(full[-4:])].groupby("c").Plant.nunique().rename("stores_4w")
    l13 = w[w.Week.isin(full[-13:])].groupby("c").Week.nunique().rename("weeks_13")
    d = now.join(info).join(below_wks).join(l4).join(l13).join(old[["gp_pct", "price", "cost"]].add_suffix("_6m_ago"))
    d = d[d.sales > 0]

    # healthy SubGroup margin (SKUs >= 10% margin, sales weighted)
    h = d[d.gp_pct >= 10]
    sg = (h.sales - h.cogs).groupby(h.SubGroup).sum() / h.sales.groupby(h.SubGroup).sum() * 100
    d["subgroup_margin"] = d.SubGroup.map(sg)

    rev = d[d.gp_pct < THIN].copy()
    # availability (feedback rule) and stock on hand
    st = pd.read_parquet(ROOT / "clean" / "stock_monthly.parquet", columns=["Month", "ArticleCode", "Closing_Qty_Base"])
    st = st[st.Month == st.Month.max()]
    st["c"] = st.ArticleCode.map(z)
    rev["stock_now"] = rev.index.map(st.groupby("c").Closing_Qty_Base.sum()).fillna(0)
    rev["weeks_cover"] = rev.stock_now / (rev.qty / WEEKS)
    al = pd.read_parquet(ROOT / "checkpoints" / "article_list.parquet", columns=["ArticleCode", "Inclusion"])
    al["c"] = al.ArticleCode.map(z)
    rev["status"] = rev.index.map(al.set_index("c").Inclusion).fillna("not in list")
    rev["on_shelf"] = (rev.stores_4w >= 10) & (rev.weeks_13 >= 10) & (rev.stock_now > 0)

    cost_chg = (rev.cost / rev.cost_6m_ago - 1) * 100
    price_chg = (rev.price / rev.price_6m_ago - 1) * 100
    rev["cost_chg_6m_%"], rev["price_chg_6m_%"] = cost_chg, price_chg
    blocked = rev.status.str.startswith("PURCHASE BLOCKED")
    # order matters: a deep markdown or a cost jump explains the loss before any pricing diagnosis
    rev["diagnosis"] = np.select(
        [rev.SubGroup.eq("PACKING MATERIAL"),
         ~rev.on_shelf,
         blocked,
         price_chg <= -25,
         (cost_chg >= 50) & (price_chg < 25),
         rev.gp_pct < -50,
         (cost_chg - price_chg) >= 5,
         rev.gp_pct < 0],
        ["Carrier bags / packing: not priced for margin",
         "Not on shelf / low supply: no price change",
         "Purchase blocked: run-out, no price change",
         "Clearance markdown (price down >25% in 6 months): check intent",
         "Cost jumped >50%: check cost data first",
         "Margin below -50%: check cost data first",
         "Cost rose, price did not follow",
         "Priced below cost"],
        "Very thin margin (0-5%)")
    act = rev.diagnosis.isin(["Cost rose, price did not follow", "Priced below cost", "Very thin margin (0-5%)"])

    # price fix
    rev["target_margin"] = rev.subgroup_margin.clip(TARGET_MIN, TARGET_MAX).fillna(TARGET_MIN * 2)
    need = (rev.cost / (1 - rev.target_margin / 100) / rev.price - 1) * 100
    rev["rise_needed_%"] = need
    rev["rise_step_%"] = need.clip(upper=MAX_STEP)
    rev["second_step"] = need > MAX_STEP
    shelf, _ = R.shelf_prices(list(rev.index[act]))
    rev = rev.join(shelf[["Sales_UOM", "Shelf_Price_KZ", "Stores_Priced", "Stores_At_Main_Price_%"]])
    rev["New_Shelf_Price_KZ"] = np.nan
    m = act & rev.Shelf_Price_KZ.notna() & (rev["rise_step_%"] > 0)
    rev.loc[m, "New_Shelf_Price_KZ"] = [R.round_shelf(p, r) for p, r in zip(rev.Shelf_Price_KZ[m], rev["rise_step_%"][m])]
    rev["Change_%"] = (rev.New_Shelf_Price_KZ / rev.Shelf_Price_KZ - 1) * 100

    # elasticity (Phase 1, shrunk) and impact over 8 weeks at the current run rate
    e = pd.read_parquet(ROOT / "analysis" / "article_elasticity.parquet", columns=["ArticleCode", "Elasticity", "SubGroup"])
    e["c"] = e.ArticleCode.map(z)
    em = e.set_index("c").Elasticity
    rev["elasticity"] = rev.index.map(em)
    rev["elasticity"] = rev.elasticity.fillna(rev.SubGroup.map(e.groupby("SubGroup").Elasticity.median())).fillna(-1.0).clip(-3, -0.5)
    dlt = rev["Change_%"].fillna(0) / 100
    for tag, ee in (("", rev.elasticity), ("_cautious", rev.elasticity * 1.5)):
        q2 = rev.qty * (1 + dlt) ** ee
        rev[f"units_chg{tag}_%"] = ((1 + dlt) ** ee - 1) * 100
        rev[f"gp_gain_8w{tag}_usd"] = ((q2 * (rev.price * (1 + dlt) - rev.cost)) - rev.qty * (rev.price - rev.cost)) / FX
    rev["new_gp_%"] = (1 - rev.cost / (rev.price * (1 + dlt))) * 100
    rev["gp_now_8w_usd"] = (rev.sales - rev.cogs) / FX
    rev["sales_8w_usd"] = rev.sales / FX

    # overlap with work already done
    pilot = set(pd.read_parquet(ROOT / "clean" / "pilot" / "validated_prices.parquet").ArticleCode.map(z))
    corr = set(pd.read_parquet(ROOT / "clean" / "pilot" / "correction_prices.parquet").ArticleCode.map(z))
    rev["already_in"] = np.where(rev.index.isin(pilot), "Pilot 40", np.where(rev.index.isin(corr), "Corrections 54", ""))
    rev["action"] = np.where(~act, "No change", np.where(rev.already_in != "", "Covered by " + rev.already_in,
                             np.where(rev.New_Shelf_Price_KZ.notna(), "Raise", "Raise: no shelf price record")))
    rev.index.name = "ArticleCode"
    rev = rev.sort_values("gp_gain_8w_usd", ascending=False)
    rev.reset_index().to_parquet(CL / "below_cost.parquet", index=False)

    keep = ["ArticleCode", "ArticleName", "MainGroup", "SubGroup", "Import", "status", "diagnosis", "action", "already_in",
            "stores_4w", "weeks_13", "weeks_below_cost", "weeks_cover", "gp_pct", "gp_pct_6m_ago", "cost_chg_6m_%",
            "price_chg_6m_%", "subgroup_margin", "target_margin", "rise_needed_%", "second_step", "Sales_UOM",
            "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Change_%", "new_gp_%", "elasticity", "units_chg_%",
            "units_chg_cautious_%", "sales_8w_usd", "gp_now_8w_usd", "gp_gain_8w_usd", "gp_gain_8w_cautious_usd"]
    x = rev.reset_index()[keep]
    summ = x.groupby(["diagnosis", "action"]).agg(SKUs=("ArticleCode", "size"), Sales_8w_USD=("sales_8w_usd", "sum"),
                                                 GP_now_8w_USD=("gp_now_8w_usd", "sum"),
                                                 GP_gain_8w_USD=("gp_gain_8w_usd", "sum"),
                                                 GP_gain_8w_cautious_USD=("gp_gain_8w_cautious_usd", "sum"))
    raise_ = x[x.action == "Raise"]
    bymg = raise_.groupby("MainGroup").agg(SKUs=("ArticleCode", "size"), Avg_rise=("Change_%", "mean"),
                                           GP_gain_8w_USD=("gp_gain_8w_usd", "sum")).sort_values("GP_gain_8w_USD", ascending=False)
    with pd.ExcelWriter(OUT / "below_cost_review.xlsx") as xw:
        summ.round(0).to_excel(xw, sheet_name="Summary")
        bymg.round(1).to_excel(xw, sheet_name="Raise by MainGroup")
        x.round(2).to_excel(xw, sheet_name="SKUs", index=False)
    pd.set_option("display.width", 250)
    print("window", pd.Timestamp(full[-WEEKS]).date(), "to", (pd.Timestamp(end) + pd.Timedelta(days=6)).date())
    print("SKUs sold", len(d), "| under", THIN, "% margin", len(rev))
    print(summ.round(0).to_string())
    print(bymg.round(1).to_string())
    print("Raise:", len(raise_), "SKUs, avg rise %.1f%%, second step needed %d, units %.1f%%, GP +$%.0f / 8w (cautious $%.0f), x6.5 = $%.0f a year"
          % (raise_["Change_%"].mean(), raise_.second_step.sum(),
             (raise_["units_chg_%"] * raise_.sales_8w_usd).sum() / raise_.sales_8w_usd.sum(),
             raise_.gp_gain_8w_usd.sum(), raise_.gp_gain_8w_cautious_usd.sum(), raise_.gp_gain_8w_usd.sum() * 6.5))
    print(raise_[["ArticleName", "gp_pct", "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Change_%", "units_chg_%", "gp_gain_8w_usd", "diagnosis"]].head(20).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
