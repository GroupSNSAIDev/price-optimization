"""All-SKU project, step B9 (+ B6, B7): data understanding and the chain-level weekly table.

One row per ACTIVE SKU x week (Jan 2024 - last full week), chain level (stores + HDDS; HRCA left out):
units, sales (Kz, USD), cost, GP, tickets, stores selling, realised and real (CPI-deflated) price, unit cost,
stock-out share, calendar (holidays, payday, Christmas), plus flags:
  No_Sales_Week   week between first and last sale with no sale at all (filled with 0)
  Markdown_Week   chain price below the regular price (trailing 13-week median) by more than the chosen threshold;
                  thresholds 5 / 8 / 12% are tested: share of weeks flagged and unit lift in flagged weeks
  Price_Step      lasting price change: week-on-week move > 3% that holds (next 2 weeks within 2% of the new level)
  Transition_Week the step week and the week after (label / shelf lag)
  Spike_Week      units > 4 robust SDs above the trailing 13-week median (kept, flagged)
  Below_Cost_Week chain price below unit cost

Inputs: clean/weekly_model.parquet, clean/allsku/scope.parquet
Outputs: clean/allsku/chain_weekly.parquet, analysis/allsku/data_understanding.xlsx
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
HIST_FROM = "2024-01-01"
MD_TESTS = [0.05, 0.08, 0.12]


def z(c):
    return str(c).lstrip("0")


def roll_prev(s, n, f):
    """trailing statistic of the previous n weeks (current week excluded), per SKU"""
    return s.groupby(level=0).transform(lambda x: getattr(x.shift(1).rolling(n, min_periods=4), f)())


def main():
    sc = pd.read_parquet(CL / "scope.parquet").set_index("Code")
    cols = ["Week", "Plant", "ArticleCode", "Qty_Clean", "Sales_KZ", "Sales_USD", "KZ_COGS", "Txn_Count", "Channel",
            "Out_Of_Stock", "Price_Real_KZ", "Holidays_In_Week", "Payday_Week", "Christmas_Season", "CPI_Deflator"]
    w = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=cols)
    w = w[(w.Channel != "HRCA") & (w.Week >= HIST_FROM)]
    w["Code"] = w.ArticleCode.map(z)
    w = w[w.Code.isin(sc.index)]
    weeks = sorted(w.Week.unique())
    partial = weeks[-1]
    w = w[w.Week < partial]
    weeks = weeks[:-1]
    stores_wk = w.groupby("Week").Plant.nunique().rename("Stores_Open")
    cal = w.groupby("Week")[["Holidays_In_Week", "Payday_Week", "Christmas_Season", "CPI_Deflator"]].first()
    w["real_x_q"] = w.Price_Real_KZ * w.Qty_Clean
    w["oos"] = w.Out_Of_Stock.fillna(False).astype(float)

    c = w.groupby(["Code", "Week"]).agg(Units=("Qty_Clean", "sum"), Sales_KZ=("Sales_KZ", "sum"), Sales_USD=("Sales_USD", "sum"),
                                        COGS_KZ=("KZ_COGS", "sum"), Tickets=("Txn_Count", "sum"), Stores_Selling=("Plant", "nunique"),
                                        real_x_q=("real_x_q", "sum"), OOS_Share=("oos", "mean"))
    # full grid between first and last sale per SKU
    rng = c.reset_index().groupby("Code").Week.agg(["min", "max"])
    wk = pd.Series(weeks)
    grid = pd.concat([pd.DataFrame({"Code": k, "Week": wk[(wk >= r["min"]) & (wk <= r["max"])].values}) for k, r in rng.iterrows()])
    c = grid.set_index(["Code", "Week"]).join(c)
    c["No_Sales_Week"] = c.Units.isna() | (c.Units <= 0)
    for col in ["Units", "Sales_KZ", "Sales_USD", "COGS_KZ", "Tickets", "Stores_Selling"]:
        c[col] = c[col].fillna(0)
    c["Price_KZ"] = np.where(c.Units > 0, c.Sales_KZ / c.Units, np.nan)
    c["Unit_Cost_KZ"] = np.where(c.Units > 0, c.COGS_KZ / c.Units, np.nan)
    c["Price_Real_KZ"] = np.where(c.Units > 0, c.real_x_q / c.Units, np.nan)
    c["GP_KZ"] = c.Sales_KZ - c.COGS_KZ
    c["Margin_Pct"] = np.where(c.Sales_KZ > 0, c.GP_KZ / c.Sales_KZ * 100, np.nan)
    c = c.drop(columns="real_x_q").reset_index()
    c = c.join(stores_wk, on="Week").join(cal, on="Week")
    c["Reach_Pct"] = c.Stores_Selling / c.Stores_Open * 100
    c = c.sort_values(["Code", "Week"]).set_index(["Code", "Week"])

    # regular price and markdown tests
    p = c.Price_KZ.groupby(level=0).ffill()
    reg = roll_prev(p, 13, "median")
    c["Regular_Price_KZ"] = reg
    rel = c.Price_KZ / reg
    u_base = roll_prev(c.Units.where(~c.No_Sales_Week), 13, "median")
    lift = c.Units / u_base
    md_test = []
    for t in MD_TESTS:
        f = rel < 1 - t
        md_test.append({"Threshold_%": t * 100, "Weeks_Flagged": int(f.sum()), "Share_%": round(f.mean() * 100, 2),
                        "SKUs_With_Any": int(f.groupby(level=0).any().sum()),
                        "Median_Unit_Lift_Flagged": round(float(lift[f].median()), 2),
                        "Median_Unit_Lift_Other": round(float(lift[~f & rel.notna()].median()), 2)})
    md_test = pd.DataFrame(md_test)
    # all three thresholds show a real lift (1.26 / 1.31 / 1.35x); 8% chosen (Conzmo standard, keeps more training weeks)
    md_thr = 0.08
    c["Markdown_Week"] = rel < 1 - md_thr

    # lasting price steps and transition weeks
    lp = np.log(p)
    d = lp.groupby(level=0).diff()
    nxt1, nxt2 = lp.groupby(level=0).shift(-1), lp.groupby(level=0).shift(-2)
    holds = ((nxt1 - lp).abs() < 0.02) & ((nxt2 - lp).abs() < 0.02)
    c["Price_Step"] = (d.abs() > 0.03) & holds & ~c.Markdown_Week
    c["Price_Step_Pct"] = np.where(c.Price_Step, (np.exp(d) - 1) * 100, np.nan)
    c["Transition_Week"] = c.Price_Step | c.Price_Step.groupby(level=0).shift(1, fill_value=False)

    # spikes and below cost
    mad = roll_prev(c.Units, 13, "std")
    c["Spike_Week"] = (c.Units - u_base) > 4 * mad.clip(lower=1)
    c["Below_Cost_Week"] = c.Price_KZ < c.Unit_Cost_KZ
    c = c.reset_index()
    c.to_parquet(CL / "chain_weekly.parquet", index=False)

    # ---------- data understanding tables
    chain = c.groupby("Week").agg(SKUs_Selling=("Units", lambda x: int((x > 0).sum())), Stores_Open=("Stores_Open", "first"),
                                  Sales_USD=("Sales_USD", "sum"), Sales_KZ=("Sales_KZ", "sum"), GP_KZ=("GP_KZ", "sum"),
                                  Units=("Units", "sum"), Payday=("Payday_Week", "first"), Holidays=("Holidays_In_Week", "first"),
                                  Christmas=("Christmas_Season", "first"))
    chain["Margin_%"] = chain.GP_KZ / chain.Sales_KZ * 100
    chain["Sales_USD_per_Store"] = chain.Sales_USD / chain.Stores_Open
    norm = chain.Sales_USD_per_Store / chain.Sales_USD_per_Store.rolling(9, center=True, min_periods=5).median()
    cal_eff = pd.DataFrame({
        "Effect": ["Payday week", "Week with a public holiday", "Christmas season weeks"],
        "Sales per store vs normal week": [norm[chain.Payday.astype(bool)].mean() / norm[~chain.Payday.astype(bool)].mean() - 1,
                                           norm[chain.Holidays > 0].mean() / norm[chain.Holidays == 0].mean() - 1,
                                           norm[chain.Christmas.astype(bool)].mean() / norm[~chain.Christmas.astype(bool)].mean() - 1]})
    cal_eff["Sales per store vs normal week"] = (cal_eff["Sales per store vs normal week"] * 100).round(1)
    woy = chain.assign(WOY=chain.index.isocalendar().week.values, Y=chain.index.year)
    season = woy.pivot_table(index="WOY", columns="Y", values="Sales_USD_per_Store", aggfunc="sum")
    season = (season / season.mean() * 100).round(0)

    q = c.groupby("Code").agg(Weeks=("Week", "size"), First_Week=("Week", "min"), Last_Week=("Week", "max"),
                              No_Sales_Weeks=("No_Sales_Week", "sum"), Markdown_Weeks=("Markdown_Week", "sum"),
                              Price_Steps=("Price_Step", "sum"), Spike_Weeks=("Spike_Week", "sum"),
                              Below_Cost_Weeks=("Below_Cost_Week", "sum"), Avg_Reach_Pct=("Reach_Pct", "mean"),
                              Avg_OOS_Share=("OOS_Share", "mean"))
    q["Price_Up_Steps"] = c[c.Price_Step_Pct > 0].groupby("Code").size().reindex(q.index).fillna(0).astype(int)
    q["Price_Down_Steps"] = c[c.Price_Step_Pct < 0].groupby("Code").size().reindex(q.index).fillna(0).astype(int)
    q["Median_Step_%"] = c.groupby("Code").Price_Step_Pct.apply(lambda x: x.abs().median())
    q = q.join(sc[["Name", "MainGroup", "SubGroup", "Segment", "ABC", "Price sensitivity", "Insight", "in_scope", "Revenue_USD"]])
    q["History"] = pd.cut(q.Weeks, [0, 26, 52, 104, 1000], labels=["< 6 months", "6-12 months", "1-2 years", "2+ years"])
    q["Price_Evidence"] = np.select([q.Price_Steps >= 6, q.Price_Steps >= 2], ["Good (6+ steps)", "Some (2-5 steps)"], "Weak (0-1 step)")

    T = q.Revenue_USD.sum()
    def by(col):
        return q.groupby(col, observed=True).agg(SKUs=("Name", "size"), Rev_Pct=("Revenue_USD", lambda x: round(x.sum() / T * 100, 1)),
                                                 Median_Weeks=("Weeks", "median"), Median_Steps=("Price_Steps", "median"),
                                                 Markdown_Wk_Share=("Markdown_Weeks", "sum"), Weeks_Sum=("Weeks", "sum")).assign(
            Markdown_Wk_Share=lambda d: (d.Markdown_Wk_Share / d.Weeks_Sum * 100).round(1)).drop(columns="Weeks_Sum")

    summary = pd.DataFrame({"Item": [
        "Active SKUs in chain table", "Of which recommendation scope", "Weeks", "First week", "Last full week (partial week dropped)",
        "SKU-week rows", "Weeks with no sale (filled 0) %", "Markdown threshold chosen %", "Markdown weeks %", "Lasting price steps",
        "  up / down", "Transition weeks %", "Spike weeks %", "Below-cost weeks %", "Stores open (first / last week)"],
        "Value": [q.shape[0], int(q.in_scope.sum()), len(weeks), str(pd.Timestamp(weeks[0]).date()), str(pd.Timestamp(weeks[-1]).date()),
                  len(c), round(c.No_Sales_Week.mean() * 100, 2), md_thr * 100, round(c.Markdown_Week.mean() * 100, 2), int(c.Price_Step.sum()),
                  f"{int((c.Price_Step_Pct > 0).sum())} / {int((c.Price_Step_Pct < 0).sum())}", round(c.Transition_Week.mean() * 100, 2),
                  round(c.Spike_Week.mean() * 100, 2), round(c.Below_Cost_Week.mean() * 100, 2),
                  f"{int(chain.Stores_Open.iloc[0])} / {int(chain.Stores_Open.iloc[-1])}"]})
    with pd.ExcelWriter(OUT / "data_understanding.xlsx") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        md_test.to_excel(xw, sheet_name="Markdown threshold test", index=False)
        cal_eff.to_excel(xw, sheet_name="Calendar effects", index=False)
        chain.round(2).to_excel(xw, sheet_name="Chain weekly")
        season.to_excel(xw, sheet_name="Seasonality index")
        for col in ["History", "Price_Evidence", "Segment", "Price sensitivity", "Insight"]:
            by(col).to_excel(xw, sheet_name=f"By {col.replace('_', ' ')}"[:31])
        q.reset_index().to_excel(xw, sheet_name="SKUs", index=False)
    pd.set_option("display.width", 220)
    print(summary.to_string(index=False)); print(md_test.to_string(index=False)); print(cal_eff.to_string(index=False))
    for col in ["History", "Price_Evidence", "Segment", "Insight"]:
        print(by(col).to_string())
    yr = chain.groupby(chain.index.year).agg(Sales_USD=("Sales_USD", "sum"), Weeks=("Sales_USD", "size"), Stores=("Stores_Open", "mean"),
                                             GP=("GP_KZ", "sum"), S=("Sales_KZ", "sum"))
    yr["USD_per_week"] = yr.Sales_USD / yr.Weeks; yr["Margin_%"] = yr.GP / yr.S * 100
    print(yr[["Weeks", "Stores", "USD_per_week", "Margin_%"]].round(1).to_string())
    print("Top Dec weeks index:", season.loc[[49, 50, 51, 52]].to_dict())


if __name__ == "__main__":
    main()
