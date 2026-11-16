"""All-SKU project, new step: today's pricing performance (the "before" picture, Six Sigma baseline).

Per quarter, active SKUs, chain level, net of IVA:
  margin      net margin %, GP $, share of sales below cost / under 5% net margin (SKU-weeks weighted by sales)
  activity    lasting price changes (steps > 3% that hold), up vs down, median size, SKUs repriced
  pass-through  cost rises (4-week avg real cost +5% vs the 4 weeks before, held 4 more weeks): share followed by a price
              rise within 13 weeks, median weeks to follow, and the share of the cost rise passed on
  markdowns   share of sales in markdown weeks (8% below regular)
  accuracy    from price_accuracy.xlsx (selling vs system price, by IVA rate)
By MainGroup for the last 52 weeks.

Inputs: clean/allsku/chain_weekly.parquet, clean/allsku/scope.parquet, analysis/allsku/price_accuracy.xlsx
Output: analysis/allsku/performance_baseline.xlsx
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
FX = 1050.0
COST_JUMP, FOLLOW_WEEKS, STEP_MAX = 0.05, 13, 100


def load():
    c = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Units", "Sales_KZ", "Net_Sales_KZ", "GP_Net_KZ",
                                                               "Margin_Net_Pct", "Unit_Cost_KZ", "CPI_Deflator", "Regular_Price_KZ",
                                                               "Price_Step", "Price_Step_Pct", "Markdown_Week", "No_Sales_Week"])
    sc = pd.read_parquet(CL / "scope.parquet", columns=["Code", "MainGroup"]).set_index("Code")
    c = c.sort_values(["Code", "Week"]).reset_index(drop=True)
    c["MainGroup"] = c.Code.map(sc.MainGroup)
    c["Quarter"] = c.Week.dt.to_period("Q").astype(str)
    c["Step"] = c.Price_Step.fillna(False) & (c.Price_Step_Pct.abs() <= STEP_MAX)   # >100% = pack / unit change, not a price move
    return c


def pass_through(c):
    """cost-rise events and whether / how fast the regular price followed"""
    rows = []
    for code, g in c.groupby("Code", sort=False):
        g = g.set_index("Week")
        cost = (g.Unit_Cost_KZ / g.CPI_Deflator).where(g.Unit_Cost_KZ > 0)
        a4 = cost.rolling(4, min_periods=3).mean()
        prev, nxt = a4.shift(4), a4.shift(-4)
        ev = (a4 / prev - 1 >= COST_JUMP) & (nxt / prev - 1 >= COST_JUMP)
        last = None
        for w in ev[ev].index:
            if last is not None and (w - last).days < 13 * 7:        # one event per 13 weeks
                continue
            last = w
            k = g.index.get_loc(w)
            win = g.iloc[k: k + FOLLOW_WEEKS + 1]
            if len(win) < FOLLOW_WEEKS + 1:
                continue
            up = win[win.Step & (win.Price_Step_Pct > 0)]
            p0, p1 = g.Regular_Price_KZ.iloc[max(k - 1, 0)], win.Regular_Price_KZ.iloc[-1]
            rise_cost = float(a4.iloc[k] / prev.iloc[k] - 1)
            rows.append({"Code": code, "Week": w, "Quarter": g.Quarter.iloc[k], "MainGroup": g.MainGroup.iloc[k],
                         "Cost_rise_%": rise_cost * 100, "Followed": len(up) > 0,
                         "Weeks_to_follow": (up.index[0] - w).days / 7 if len(up) else np.nan,
                         "Price_change_13w_%": (p1 / p0 - 1) * 100 if p0 > 0 else np.nan})
    e = pd.DataFrame(rows)
    # real price change vs real cost change: share of the cost rise passed on
    e["Passed_on_%"] = (e["Price_change_13w_%"] / e["Cost_rise_%"] * 100).clip(-100, 300)
    return e


def by(c, e, key):
    g = c.groupby(key)
    sales = g.Sales_KZ.sum()
    out = pd.DataFrame({
        "SKUs_selling": g.apply(lambda x: x.loc[x.Units > 0, "Code"].nunique()),
        "Net_sales_$M": g.Net_Sales_KZ.sum() / FX / 1e6,
        "GP_net_$M": g.GP_Net_KZ.sum() / FX / 1e6,
        "Net_margin_%": g.GP_Net_KZ.sum() / g.Net_Sales_KZ.sum() * 100,
        "Sales_below_cost_%": c[c.GP_Net_KZ < 0].groupby(key).Sales_KZ.sum().reindex(sales.index).fillna(0) / sales * 100,
        "Sales_under_5pct_margin_%": c[c.Margin_Net_Pct < 5].groupby(key).Sales_KZ.sum().reindex(sales.index).fillna(0) / sales * 100,
        "Sales_in_markdown_weeks_%": c[c.Markdown_Week.fillna(False)].groupby(key).Sales_KZ.sum().reindex(sales.index).fillna(0) / sales * 100,
        "Price_changes": g.Step.sum(),
        "Price_rises": c[c.Step & (c.Price_Step_Pct > 0)].groupby(key).size().reindex(sales.index).fillna(0),
        "Price_cuts": c[c.Step & (c.Price_Step_Pct < 0)].groupby(key).size().reindex(sales.index).fillna(0),
        "Median_change_%": c[c.Step].groupby(key).Price_Step_Pct.apply(lambda x: x.abs().median()),
        "SKUs_repriced": c[c.Step].groupby(key).Code.nunique(),
    })
    eg = e.groupby(key)
    out = out.join(pd.DataFrame({"Cost_rises": eg.size(), "Followed_in_13w_%": eg.Followed.mean() * 100,
                                 "Median_weeks_to_follow": eg.Weeks_to_follow.median(), "Median_passed_on_%": eg["Passed_on_%"].median()}))
    return out


def main():
    c = load()
    e = pass_through(c)
    full_q = c.groupby("Quarter").Week.nunique()
    q = by(c, e, "Quarter")
    q.insert(0, "Weeks", full_q)
    end = c.Week.max()
    last = c[c.Week > end - pd.Timedelta(weeks=52)]
    el = e[e.Week > end - pd.Timedelta(weeks=52 + FOLLOW_WEEKS)]
    mg = by(last, el, "MainGroup").sort_values("Net_sales_$M", ascending=False)
    tot = by(last.assign(All="Last 52 weeks"), el.assign(All="Last 52 weeks"), "All")
    acc = pd.read_excel(OUT / "price_accuracy.xlsx", sheet_name="Accuracy by IVA")
    head = tot.iloc[0]
    kpi = pd.DataFrame([
        ("Net margin % (after IVA)", head["Net_margin_%"], "Six Sigma Y; spec limits to agree (charter)"),
        ("Share of sales sold below cost %", head["Sales_below_cost_%"], "defect rate"),
        ("Share of sales under 5% net margin %", head["Sales_under_5pct_margin_%"], "defect rate"),
        ("Lasting price changes per year", head["Price_changes"], "pricing activity"),
        ("  of which rises / cuts", f"{int(head['Price_rises'])} / {int(head['Price_cuts'])}", ""),
        ("Median size of a price change %", head["Median_change_%"], ""),
        ("Cost rises of 5%+ (held)", head["Cost_rises"], "events, last 52 weeks + 13"),
        ("  followed by a price rise within 13 weeks %", head["Followed_in_13w_%"], "speed of pass-through"),
        ("  median weeks to follow", head["Median_weeks_to_follow"], ""),
        ("  median share of the cost rise passed on %", head["Median_passed_on_%"], "real terms"),
        ("Share of sales in markdown weeks %", head["Sales_in_markdown_weeks_%"], ""),
    ], columns=["KPI (before picture)", "Value", "Note"])
    with pd.ExcelWriter(OUT / "performance_baseline.xlsx") as xw:
        kpi.to_excel(xw, sheet_name="Before picture", index=False)
        q.round(2).to_excel(xw, sheet_name="By quarter")
        mg.round(2).to_excel(xw, sheet_name="By MainGroup (52w)")
        acc.to_excel(xw, sheet_name="Price accuracy", index=False)
        e.round(2).to_excel(xw, sheet_name="Cost-rise events", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(kpi.to_string(index=False))
    print(q.round(1).to_string())
    print(mg.round(1).head(12).to_string())


if __name__ == "__main__":
    main()
