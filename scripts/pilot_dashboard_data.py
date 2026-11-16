"""Step 18 · Export the pilot results as JSON datasets for the interactive dashboard."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "pilot", ROOT / "analysis" / "pilot"
DST = Path(sys.argv[1])
DST.mkdir(parents=True, exist_ok=True)
short = lambda c: str(c).lstrip("0")
# PILOT_PLAN=sweetspot exports the plan-specific datasets as <name>__sweetspot.json (shared ones are skipped);
# the page switches between plans by swapping these datasets
PLAN = os.environ.get("PILOT_PLAN", "")
SFX = f"_{PLAN}" if PLAN else ""
PLAN_SETS = {"skus", "weekly", "test_pairs", "test_power", "test_plan", "rules", "flags", "line_moves", "basket", "frontier"}


def nice(n):
    n = " ".join(str(n).title().split())
    for a, b in [(" Kg", " kg"), ("Kgm", "kg"), ("Ltr", "L"), ("1Lt", "1L"), ("20Lt", "20L"), ("Ml", "ml")]:
        n = n.replace(a, b)
    return n


def dump(name, df):
    if PLAN:
        if name not in PLAN_SETS:
            return
        name = f"{name}__{PLAN}"
    df = df.replace([np.inf, -np.inf], np.nan)
    rows = json.loads(df.to_json(orient="records", double_precision=4))
    p = DST / f"{name}.json"
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(name, len(rows), f"{p.stat().st_size / 1024:.0f} KB")


v = pd.read_parquet(CL / f"validated_prices{SFX}.parquet").set_index("ArticleCode")
opt = pd.read_parquet(CL / f"optimal_prices{SFX}.parquet").set_index("ArticleCode")
e = pd.read_parquet(CL / "sku_elasticity.parquet").set_index("ArticleCode")
g = pd.read_parquet(CL / "profit_grid.parquet")
g["Step"] = g["Price_Change_%"].round().astype(int)
cur = g[g.Step == 0].set_index("ArticleCode")
share = (v.Units_Base / cur.Baseline_Units_13w).fillna(0)        # share of the 13 weeks left from 2 Nov

wave = v.Wave.str.replace(" (chicken legs, test stores only)", "", regex=False).str.replace(" (chain-wide)", "", regex=False)
s = pd.DataFrame({
    "Code": [short(a) for a in v.index], "Name": [nice(n) for n in v.ArticleName], "Group": v.Group,
    "SubGroup": v.SubGroup.str.title(), "Wave": wave, "Validation": v.Validation, "Rules_Flagged": v.Rules_Flagged,
    "Confidence": v.Confidence, "Supply_At_Risk": v.Supply_At_Risk, "Staple_Check": v.Confirm_Not_Price_Controlled,
    "Pack": v.Sales_UOM, "Shelf_Price": v.Shelf_Price_KZ, "New_Shelf_Price": v.New_Shelf_Price_KZ,
    "Change_Pct": v["Price_Change_%"], "Optimal_Pct": v["Optimal_Change_%"],
    "Tested_Down": cur["Tested_Down_%"].reindex(v.index), "Tested_Up": cur["Tested_Up_%"].reindex(v.index),
    "Elasticity": e.Elasticity_Final.reindex(v.index), "Rise_Elasticity": e.Rise_Final.reindex(v.index),
    "Cut_Elasticity": e.Cut_Final.reindex(v.index), "CI_Low": e.CI_Low.reindex(v.index),
    "CI_High": e.CI_High.reindex(v.index), "Margin_Now_Pct": opt["Current_Margin_%"].reindex(v.index),
    "Margin_New_Pct": ((1 - cur.Unit_Cost_KZ / (cur.Current_Price_KZ * (1 + v["Price_Change_%"] / 100))) * 100).reindex(v.index),
    "Units_Base": v.Units_Base, "Units_Change": v.Units_Change, "Units_Change_Pct": v["Units_Change_%"],
    "Units_Change_Cautious_Pct": v["Units_Change_Cautious_%"], "Revenue_Change": v.Revenue_Change_KZ,
    "GP_Change": v.GP_Change_KZ, "GP_Change_Cautious": v.GP_Change_Cautious_KZ,
    "GP_Change_Optimistic": v.GP_Change_Optimistic_KZ, "GP_Change_USD": v.GP_Change_USD,
    "Revenue_13w": cur.Revenue_Likely_KZ.reindex(v.index), "GP_13w": cur.GP_Likely_KZ.reindex(v.index),
    "Store_Coverage_Pct": v["Store_Coverage_%"], "Substitute_Group": opt.Substitute_Group.reindex(v.index),
    "Limited_By": opt.Limited_By.reindex(v.index), "Rationale": v.Rationale,
}).reset_index(drop=True)
s["Action"] = np.select([s.Change_Pct > 0, s.Change_Pct < 0], ["Raise", "Cut"], "Hold")
# current position per sales pack (ex-IVA net prices and cost), for the Current pricing page
upp = v.Units_Per_Pack.values
s["Units_Per_Pack"] = upp
s["IVA_Pct"] = v["IVA_%"].values
s["Net_List_Pack"] = v.Net_List_Per_Unit_KZ.values * upp
s["Net_Realised_Pack"] = v.Realised_Net_Per_Unit_KZ.values * upp
s["Cost_Pack"] = v.Unit_Cost_KZ.values * upp
s["Profit_Pack"] = s.Net_Realised_Pack - s.Cost_Pack
s["Margin_List_Pct"] = (1 - s.Cost_Pack / s.Net_List_Pack) * 100
s["Margin_Realised_Pct"] = (1 - s.Cost_Pack / s.Net_Realised_Pack) * 100
s["Realised_vs_List_Pct"] = v["Realised_vs_List_%"].values
s["Units_13w"] = cur.Baseline_Units_13w.reindex(v.index).values
s["Units_Week"] = s.Units_13w / 13
s["Packs_Week"] = s.Units_Week / s.Units_Per_Pack
s["Stores_Priced"] = v.Stores_Priced.values
s["Stores_Main_Price_Pct"] = v["Stores_At_Main_Price_%"].values
s["Last_Price_Record"] = pd.to_datetime(v.Last_Price_Record).dt.strftime("%Y-%m-%d").values
dump("skus", s)

# simulator grid, re-stated for the weeks from 2 Nov (same basis as the recommendations)
k = g.ArticleCode.map(share)
grid = pd.DataFrame({
    "Code": g.ArticleCode.map(short), "Step": g.Step,
    "Shelf_Price_Est": g.ArticleCode.map(v.Shelf_Price_KZ) * (1 + g.Step / 100),
    "Units": g.Units_Likely * k, "Units_Low": np.minimum(g.Units_Strong, g.Units_Weak) * k,
    "Units_High": np.maximum(g.Units_Strong, g.Units_Weak) * k, "Units_Change_Pct": g["Units_Change_%"],
    "Revenue": g.Revenue_Likely_KZ * k, "GP": g.GP_Likely_KZ * k, "GP_Change": g.GP_Change_KZ * k,
    "Rival_GP_Change": g.Rival_GP_Change_KZ * k, "Net_GP_Change": g.Net_GP_Change_KZ * k,
    "GP_Change_Low": g.GP_Change_Low_KZ * k, "GP_Change_High": g.GP_Change_High_KZ * k, "Margin_Pct": g["Margin_%"],
    "Tested": g.Within_Tested_Range.astype(bool)})
dump("grid", grid)

# weekly baseline and expected units at the new prices
b = pd.read_parquet(CL / "baseline_forecast.parquet").groupby(["ArticleCode", "Week"]).agg(
    Baseline=("Baseline_Units", "sum"), Season=("Season_Factor", "mean")).reset_index()
eff = pd.Timestamp("2026-11-02")
chg = b.ArticleCode.map(v["Units_Change_%"]) / 100
cau = np.minimum(b.ArticleCode.map(v["Units_Change_Cautious_%"]), b.ArticleCode.map(v["Units_Change_%"])) / 100
after = b.Week >= eff
w = pd.DataFrame({"Code": b.ArticleCode.map(short), "Week": b.Week.dt.strftime("%Y-%m-%d"), "Baseline": b.Baseline,
                  "Expected": np.where(after, b.Baseline * (1 + chg), b.Baseline),
                  "Low": np.where(after, b.Baseline * (1 + cau) * 0.78, b.Baseline * 0.78),
                  "High": np.where(after, b.Baseline * (1 + chg) * 1.22, b.Baseline * 1.22),
                  "New_Price": after.astype(bool), "Season": b.Season})
dump("weekly", w)

x = pd.ExcelFile(OUT / f"recommendations{SFX}.xlsx")
pairs = x.parse("Test-control pairs")
dump("test_pairs", pairs.rename(columns={"Test_Weekly_Units": "Test_Units_Wk", "Control_Weekly_Units": "Control_Units_Wk"}))
pw = x.parse("Test power (placebo)").rename(columns={"Placebo_SD_%": "Placebo_SD_Pct", "Min_Detectable_Change_%": "MDE_Pct"})
dump("test_power", pw)
dump("test_plan", x.parse("Chicken leg test plan"))

r = pd.ExcelFile(OUT / f"business_rules{SFX}.xlsx")
rs = r.parse("Rule summary")
rs["Code"] = rs.Rule.str.split(" ").str[0]
rs["Name"] = rs.Rule.str.split(" ", n=1).str[1]
rs["Order"] = rs.Code.str[1:].astype(int)
dump("rules", rs.sort_values("Order")[["Code", "Name", "PASS", "FLAG", "FAIL"]])
fl = r.parse("Flags and fails", dtype={"ArticleCode": str})
fl["Code"] = fl.ArticleCode.map(short)
fl["Name"] = fl.ArticleName.map(nice)
fl["RuleCode"] = fl.Rule.str.split(" ").str[0]
fl = fl.reset_index(drop=True)
fl["Id"] = fl.index + 1
dump("flags", fl[["Id", "RuleCode", "Rule", "Code", "Name", "Status", "Detail"]])
lm = pd.read_parquet(CL / f"line_moves{SFX}.parquet")
dump("line_moves", pd.DataFrame({"Product_Code": lm.ArticleCode.map(short), "Pilot": lm.Pilot_ArticleName.map(nice),
                                 "Product": lm.ArticleName.map(nice), "Shelf_Price": lm.Shelf_Price_KZ,
                                 "New_Shelf_Price": lm.New_Shelf_Price_KZ, "Change_Pct": lm["Price_Change_%"],
                                 "Units": lm.Units_Base_Remaining, "GP_Change_Est": lm.GP_Change_Est_KZ}))
bk = r.parse("Basket view")
dump("basket", pd.DataFrame({"Measure": ["basket", "staples", "cpi_month", "months"], "Label": bk.Measure,
                             "Value": bk.Value}))

fr = pd.read_excel(OUT / f"price_optimisation{SFX}.xlsx", sheet_name="Volume vs GP frontier")
dump("frontier", fr.rename(columns={"Volume_Cap_%": "Cap_Pct", "Units_Change_%": "Units_Change_Pct",
                                    "Revenue_Change_%": "Revenue_Change_Pct"}))
bm = pd.read_excel(OUT / "forecast_benchmark.xlsx", sheet_name="Summary (7 periods)")
bm = bm.rename(columns={"WAPE_mean": "WAPE", "WAPE_sd": "WAPE_SD", "WAPE_chain_month_mean": "WAPE_Chain_Month",
                        "Abs_Bias_mean": "Abs_Bias"})
dump("accuracy", bm[["Method", "Periods", "WAPE", "WAPE_SD", "WAPE_Chain_Month", "Abs_Bias", "Periods_Best"]])
sp = pd.read_excel(OUT / "simulation.xlsx", sheet_name="Seasonal path")
sp = sp.rename(columns={sp.columns[0]: "Week_Ahead"})
sp.columns = ["Y" + str(c) if str(c).isdigit() and len(str(c)) == 4 else str(c) for c in sp.columns]
dump("seasonal", sp)

# price corrections outside the pilot (report-flagged categories), shared by both plans
if not PLAN and (CL / "correction_prices.parquet").exists():
    c = pd.read_parquet(CL / "correction_prices.parquet")
    dump("corrections", pd.DataFrame({
        "Code": c.ArticleCode.map(short), "Name": c.ArticleName.map(nice), "Category": c.Scope, "Wave": c.Wave,
        "Diagnosis": c.Diagnosis, "Scarcity": c.Scarcity, "Staple": c.Staple, "Pack": c.Sales_UOM,
        "Shelf_Price": c.Shelf_Price_KZ, "New_Shelf_Price": c.New_Shelf_Price_KZ, "Change_Pct": c["Price_Change_%"],
        "Cost_YoY_Pct": c["Cost_Change_YoY_%"], "Price_YoY_Pct": c["Price_Change_YoY_%"], "GP_LY_Pct": c["GP_%_LY"],
        "GP_Now_Pct": c["GP_%_Now"], "GP_New_Pct": c["New_GP_%"], "Elasticity": c.Elasticity,
        "Units_Change_Pct": c["Units_Change_%"], "Units_Change_Cautious_Pct": c["Units_Change_Cautious_%"],
        "Sales_12m_USD": c.Sales_12m_USD, "GP_8w_USD": c.GP_Change_8w_USD, "GP_8w_Cautious_USD": c.GP_Change_8w_USD_Cautious,
        "GP_12m_USD": c.GP_Change_12m_USD, "GP_12m_Cautious_USD": c.GP_Change_12m_USD_Cautious,
        "Revenue_12m_USD": c.Revenue_Change_12m_USD, "Stores": c.Stores_Priced}))
