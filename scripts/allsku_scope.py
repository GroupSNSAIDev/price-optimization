"""All-SKU project, step 1: scope and data check (pure SKU lens).

Scope: every ACTIVE SKU sold in the last 52 weeks is modelled. A price recommendation goes only to SKUs on the
shelf now: sold in >= 10 stores in the last 4 weeks, in >= 10 of the last 13 weeks, and stock on hand (latest stock
month). The rest are listed as "hold, not on shelf".
Every SKU carries the three approved groupings (contribution segment, price sensitivity group, insight group)
and data-quality flags. The modelling table holds its store x week rows from Jan 2024 (2023 is devaluation-distorted).

Margins are net of IVA (user decision 2026-11-15).
Inputs: clean/allsku/portfolio.json, clean/allsku/sku_behaviour.parquet, clean/weekly_model.parquet, clean/stock_monthly.parquet
Outputs: clean/allsku/scope.parquet, clean/allsku/model_weekly.parquet, analysis/allsku/scope.xlsx
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
HIST_FROM = "2024-01-01"


def z(c):
    return str(c).lstrip("0")


def main():
    pf = pd.DataFrame(json.loads((CL / "portfolio.json").read_text(encoding="utf-8"))).set_index("Code")
    chain_margin = json.loads((CL / "portfolio_meta.json").read_text(encoding="utf-8"))[0]["Chain_Margin_Pct"]   # net of IVA
    bh = pd.read_parquet(CL / "sku_behaviour.parquet").set_index("Code")
    st = pd.read_parquet(ROOT / "clean" / "stock_monthly.parquet", columns=["Month", "ArticleCode", "Plant", "Closing_Qty_Base"])
    last_m = st.Month.max()
    st = st[st.Month == last_m]
    st["c"] = st.ArticleCode.map(z)
    stock = st.groupby("c").agg(stock_qty=("Closing_Qty_Base", "sum"), stock_stores=("Closing_Qty_Base", lambda x: int((x > 0).sum())))

    a = pf.copy()
    a = a.join(stock)
    a["has_stock"] = a.stock_qty.fillna(0) > 0
    a["in_scope"] = a.On_Shelf & a.has_stock
    a["reason_out"] = np.select([~a.On_Shelf, ~a.has_stock], ["not on shelf (stores / weeks)", "no stock on hand"], "")

    # approved groupings
    lens = bh[["elasticity", "measured", "Price sensitivity", "Purchase frequency", "Store reach", "Price vs inflation", "Margin direction",
               "Trend", "Seasonality", "Demand stability"]]
    a = a.join(lens)
    kvi = (a["Purchase frequency"] == "Daily-need") & (a["Store reach"] == "Everywhere")
    raise_c = a["Price sensitivity"].isin(["Inelastic", "Moderate"]) & (a.Margin_Pct < chain_margin)
    danger = a["Price sensitivity"] == "Highly elastic"
    erode = a["Price vs inflation"].isin(["Below inflation", "Price cut"]) & (a["Margin direction"] == "Margin down")
    a["Insight"] = np.select([kvi, danger, raise_c, erode], ["Everyday KVI", "Danger zone", "Raise candidate", "Margin eroding"], "Other")
    a["Is_KVI"], a["Is_Raise_Candidate"], a["Is_Danger"], a["Is_Eroding"] = kvi, raise_c, danger, erode

    # data checks on the modelling rows
    cols = ["Week", "Plant", "ArticleCode", "Qty_Clean", "Sales_KZ", "KZ_COGS", "Realized_Price_KZ", "Unit_COGS_KZ", "Txn_Count",
            "Channel", "Store_Class", "Area_Zone", "In_Model_Sample", "Below_Cost_Week", "Out_Of_Stock", "Days_Of_Cover",
            "Holidays_In_Week", "Payday_Week", "Christmas_Season", "Week_Of_Year", "Month_Of_Year", "CPI_Deflator",
            "Price_Real_KZ", "Relative_Price", "ln_Qty", "ln_Price_Real", "ln_Relative_Price", "Category_Price_Index", "SubGroup"]
    w = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=cols)
    w = w[(w.Channel != "HRCA") & (w.Week >= HIST_FROM)]
    w["c"] = w.ArticleCode.map(z)
    w = w[w.c.isin(set(a.index))]
    full = sorted(w.Week.unique())[:-1]
    w = w[w.Week.isin(full)]
    end = pd.Timestamp(full[-1])
    g = w.groupby("c")
    chk = pd.DataFrame({
        "rows": g.size(), "model_rows": g.In_Model_Sample.sum(), "weeks": g.Week.nunique(), "stores": g.Plant.nunique(),
        "first_week": g.Week.min(), "below_cost_weeks_pct": g.Below_Cost_Week.mean() * 100,
        "missing_cost_pct": g.Unit_COGS_KZ.apply(lambda x: x.isna().mean() * 100),
    })
    # price moves (chain weekly price, last 104 weeks) and the size of the biggest step
    ch = w[w.Week > end - pd.Timedelta(weeks=104)].groupby(["c", "Week"]).agg(q=("Qty_Clean", "sum"), s=("Sales_KZ", "sum"))
    lp = np.log(ch.s / ch.q)
    d = lp.groupby(level=0).diff().abs()
    chk["price_moves_3pct"] = (d > 0.03).groupby(level=0).sum()
    chk["max_step_pct"] = (np.exp(d.groupby(level=0).max()) - 1) * 100
    a = a.join(chk)
    a["history_weeks_ok"] = a.weeks >= 52
    a["flag"] = np.select(
        [a.in_scope & (a.weeks < 52), a.in_scope & (a.missing_cost_pct > 10), a.in_scope & (a.price_moves_3pct < 2),
         a.in_scope & (a.below_cost_weeks_pct > 10)],
        ["under 1 year of history", "cost missing on >10% of rows", "price barely moved: borrow from group", "often sold below cost"], "")
    a.index.name = "Code"
    a.reset_index().to_parquet(CL / "scope.parquet", index=False)
    w.drop(columns=["ArticleCode"]).rename(columns={"c": "Code"}).to_parquet(CL / "model_weekly.parquet", index=False)

    s = a[a.in_scope]
    T = pf.Revenue_USD.sum()
    def tab(col, order=None):
        t = s.groupby(col).agg(SKUs=("Name", "size"), Rev_Pct=("Revenue_USD", lambda x: x.sum() / T * 100),
                               GP=("GP_USD", "sum"), Rev=("Revenue_USD", "sum"))
        t["Margin_Pct"] = t.GP / t.Rev * 100
        t = t.drop(columns=["GP", "Rev"])
        return t.reindex(order).dropna(how="all") if order else t.sort_values("Rev_Pct", ascending=False)
    seg = tab("Segment"); sens = tab("Price sensitivity", ["Highly elastic", "Elastic", "Moderate", "Inelastic", "Unclear (+)", "Not measured"])
    ins = tab("Insight", ["Everyday KVI", "Raise candidate", "Danger zone", "Margin eroding", "Other"])
    with pd.ExcelWriter(OUT / "scope.xlsx") as xw:
        pd.DataFrame({"Item": ["Active SKUs", "Recommendation scope (on shelf + stock)", "Out: not on shelf", "Out: no stock", "Revenue share in scope %",
                               "Model rows", "Weeks", "Stores", "Stock month"],
                      "Value": [len(a), len(s), int((a.reason_out == "not on shelf (stores / weeks)").sum()), int((a.reason_out == "no stock on hand").sum()),
                                round(s.Revenue_USD.sum() / T * 100, 1), int(len(w)), w.Week.nunique(), w.Plant.nunique(), str(last_m)]}).to_excel(xw, sheet_name="Summary", index=False)
        seg.round(1).to_excel(xw, sheet_name="By segment"); sens.round(1).to_excel(xw, sheet_name="By sensitivity"); ins.round(1).to_excel(xw, sheet_name="By insight")
        a.reset_index().to_excel(xw, sheet_name="SKUs", index=False)
    pd.set_option("display.width", 220)
    print(f"active {len(a)} | recommendation scope {len(s)} ({s.Revenue_USD.sum() / T * 100:.1f}% of active revenue) | out: "
          f"{a.reason_out.value_counts().drop('', errors='ignore').to_dict()}")
    print(f"model table: {len(w):,} rows, {w.Week.min().date()} to {end.date()}, {w.Plant.nunique()} stores; stock month {last_m}")
    print(seg.round(1).to_string()); print(sens.round(1).to_string()); print(ins.round(1).to_string())
    print("flags:", s.flag.value_counts().to_dict())
    print("history weeks: median", int(s.weeks.median()), "| price moves (104w) median", int(s.price_moves_3pct.median()),
          "| missing cost >10%:", int((s.missing_cost_pct > 10).sum()))
    print("out of scope (biggest):"); print(a[~a.in_scope].nlargest(8, "Revenue_USD")[["Name", "reason_out", "Stores_4w", "stock_qty"]].to_string())


if __name__ == "__main__":
    main()
