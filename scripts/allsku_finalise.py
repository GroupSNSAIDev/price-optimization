"""All-SKU project, phase H (+ I1 price list): from optimal % changes to shelf prices, rules, reasons, waves and tests.

H1  Shelf price: latest price record, store mode, incl. IVA per sales pack; rounded to Fresmart endings (...9.99 below
    10,000 Kz, ...99.99 above) on the same side of today's price; guardrails re-checked after rounding (one price point
    back when the unit-loss cap or cost is broken); rounding impact on GP reported; key thresholds (1,000 / 5,000 /
    10,000 / 50,000 / 100,000 Kz) flagged when crossed, with the just-below price and the share of the gain it keeps.
H2  Store rules: each store keeps its own tier (the chain % change is applied to its own price); HRCA left out;
    wholesale (HDDS, HDS2-4) get no rises on staples; stores > 12% off the chain price are listed for pricing.
H3  Business rules check against the A2 catalogue (R1-R20; ladders / price lines need pack data -> short description phase).
H4  Plain-language reason per SKU.
H5  Waves: Wave 1 (High / Medium confidence, rise <= 8%), Review (Low confidence, big moves, rule flags), Test (Danger zone
    rises, chicken legs), Hold; label changes per store per wave.
H7  Holdout stores: matched retail store pairs (volume, different zone); control stores keep old prices;
    minimum detectable change in GP (net of IVA), units and sales over 4-16 weeks from placebo runs, vs the expected change.
H8  Rollback rules: pause / roll back limits per wave and SKU, set from the same placebo noise.
H6  Impact for any date window from the weekly 52-week table: --start / --end.

Usage: python scripts/allsku_finalise.py [--start 2026-11-30 --end 2027-01-31]
Outputs: clean/allsku/price_list.parquet, clean/allsku/store_prices.parquet, analysis/allsku/price_list.xlsx
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import pilot_recommend as R

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
FX, SEED = 1050.0, 2026
THRESHOLDS = [1000, 5000, 10000, 50000, 100000, 250000]
STAPLES = ["RICE", "OIL", "SUGAR", "MILK", "EGG", "FLOUR"]
WHOLESALE = ["HDDS", "HDS2", "HDS3", "HDS4"]
OFF_TIER = 12
CPI_MONTHLY = 0.6


def shelf_prices(codes):
    """as pilot_recommend.shelf_prices, robust to SKUs whose price records are blank"""
    p = pd.read_parquet(ROOT / "clean" / "price_changes.parquet")
    p["c"] = p.ArticleCode.astype(str).str.lstrip("0")
    q = p[p.c.isin(codes) & p.Primary_UOM & ~p.Is_Spike & (p.PriceIVA > 0)].sort_values("EffectiveTS")
    last = q.groupby(["Plant", "c"]).tail(1)
    g = last.groupby("c")
    mode = lambda x: x.mode().iloc[0] if len(x.mode()) else np.nan
    s = pd.DataFrame({"Sales_UOM": g.SalesUOM.agg(mode), "Units_Per_Pack": g.Factor.median(), "IVA_%": g.IVA.median(),
                      "Shelf_Price_KZ": g.PriceIVA.agg(mode), "Stores_Priced": g.Plant.nunique(), "Last_Price_Record": g.EffectiveTS.max()})
    s["Stores_At_Main_Price_%"] = g.apply(lambda d: (d.PriceIVA == mode(d.PriceIVA)).mean() * 100)
    return s, last


def impact(weekly, start, end):
    w = weekly[(weekly.Week >= pd.Timestamp(start)) & (weekly.Week <= pd.Timestamp(end))]
    s = w.sum(numeric_only=True)
    return {"Start": str(pd.Timestamp(start).date()), "End": str(pd.Timestamp(end).date()), "Weeks": w.Week.nunique(),
            "GP_now_$": s.GP_now_KZ / FX, "GP_gain_likely_$": (s.GP_new_L_KZ - s.GP_now_KZ) / FX,
            "GP_gain_cautious_$": (s.GP_new_S_KZ - s.GP_now_KZ) / FX, "GP_gain_optimistic_$": (s.GP_new_O_KZ - s.GP_now_KZ) / FX,
            "Revenue_change_$": (s.Rev_new_L_KZ - s.Rev_now_KZ) / FX, "Units_change_%": (s.Units_new_L / s.Units_now - 1) * 100}


def own_gp(r, d):
    e = r.Rise if d > 0 else r.Cut
    u = r.Base_52w * (1 + d) ** e
    return u * (r.P * (1 + d) - r.C), u


def holdout(changed, expected):
    """matched retail store pairs on the SKUs that change; placebo minimum detectable change for GP (net of IVA), units
    and sales over 4-16 weeks, compared with the change the plan expects; rollback limits from the same placebo noise"""
    w = pd.read_parquet(CL / "model_weekly.parquet", columns=["Week", "Plant", "Code", "Qty_Clean", "Sales_KZ", "KZ_COGS", "Channel", "Area_Zone"])
    w = w[w.Code.isin(changed) & (w.Channel == "STORE")]
    iva = pd.read_parquet(CL / "iva_by_sku.parquet").set_index("Code").IVA_Pct
    w["GP_KZ"] = w.Sales_KZ / (1 + w.Code.map(iva).fillna(0) / 100) - w.KZ_COGS
    tabs = {m: w.groupby(["Plant", "Week"])[col].sum().unstack(fill_value=0) for m, col in [("GP", "GP_KZ"), ("Units", "Qty_Clean"), ("Sales", "Sales_KZ")]}
    s = tabs["Sales"]
    end = s.columns.max()
    recent = s.loc[:, s.columns > end - pd.Timedelta(weeks=13)]
    info = pd.DataFrame({"Weekly_Sales_13w": recent.mean(axis=1), "Zone": w.drop_duplicates("Plant").set_index("Plant").Area_Zone})
    info = info[(recent > 0).sum(axis=1) >= 12].sort_values("Weekly_Sales_13w")
    rng = np.random.default_rng(SEED)
    pairs, ids = [], list(info.index)
    while len(ids) >= 2:
        a = ids.pop(0)
        cand = ids[:4]
        other = [c for c in cand if info.at[c, "Zone"] != info.at[a, "Zone"]]
        b = other[0] if other else cand[0]
        ids.remove(b)
        t, c = (a, b) if rng.random() < 0.5 else (b, a)
        pairs.append({"Pair": len(pairs) + 1, "Changed_Store": t, "Holdout_Store": c, "Changed_Zone": info.at[t, "Zone"],
                      "Holdout_Zone": info.at[c, "Zone"], "Changed_Weekly_Sales_$": info.at[t, "Weekly_Sales_13w"] / FX,
                      "Holdout_Weekly_Sales_$": info.at[c, "Weekly_Sales_13w"] / FX})
    pairs = pd.DataFrame(pairs)
    weeks = [c for c in s.columns if pd.Timestamp("2025-06-02") <= c <= end - pd.Timedelta(weeks=16)]
    tr, ct = pairs.Changed_Store.to_numpy(), pairs.Holdout_Store.to_numpy()
    power = []
    for metric, t in tabs.items():
        for n in (4, 8, 12, 16):
            est = []
            for s0 in weeks:
                pre = t.loc[:, (t.columns >= s0 - pd.Timedelta(weeks=8)) & (t.columns < s0)].sum(axis=1)
                post = t.loc[:, (t.columns >= s0) & (t.columns < s0 + pd.Timedelta(weeks=n))].sum(axis=1) * 8 / n
                # pooled ratio-of-sums difference-in-differences (robust to small or negative store GP); random relabelling = placebo
                for _ in range(20):
                    flip = rng.random(len(pairs)) < 0.5
                    a, b = np.where(flip, ct, tr), np.where(flip, tr, ct)
                    est.append(np.log(post.reindex(a).sum() / pre.reindex(a).sum()) - np.log(post.reindex(b).sum() / pre.reindex(b).sum()))
            sd = float(np.std(est))
            power.append({"Metric": metric, "Weeks": n, "Pairs": len(pairs), "Placebo_SD_%": sd * 100,
                          "Min_Detectable_Change_%": 2.8 * sd * 100, "Expected_change_%": expected[metric],
                          "Detectable": abs(expected[metric]) >= 2.8 * sd * 100})
    power = pd.DataFrame(power)
    sd = power.set_index(["Metric", "Weeks"])["Placebo_SD_%"]
    rollback = pd.DataFrame([
        {"Level": "Wave", "Check": "GP of changed SKUs, changed vs holdout stores (difference-in-differences)", "When": "every week from week 2",
         "Pause next wave if": f"below {expected['GP'] - 2 * sd[('GP', 4)]:+.1f}% after 4 weeks (expected {expected['GP']:+.1f}% minus 2 noise SD)",
         "Roll back the wave if": f"below {-2 * sd[('GP', 4)]:+.1f}% after 4 weeks, or below {-2 * sd[('GP', 8)]:+.1f}% after 8 weeks (GP clearly falling)"},
        {"Level": "Wave", "Check": "Units of changed SKUs, changed vs holdout stores", "When": "every week from week 2",
         "Pause next wave if": f"below {expected['Units'] - 2 * sd[('Units', 4)]:+.1f}% after 4 weeks",
         "Roll back the wave if": f"below {expected['Units'] - 3 * sd[('Units', 4)]:+.1f}% after 4 weeks (units fall far more than planned)"},
        {"Level": "SKU", "Check": "Units of one SKU in changed stores vs holdout stores", "When": "weekly, 3-week rolling",
         "Pause next wave if": "units fall more than 2x the planned loss and more than 15% for 3 weeks",
         "Roll back the wave if": "same for 4 weeks in a row, or an Everyday KVI family loses more than 10%: return to the old price"},
        {"Level": "SKU", "Check": "Hard stops", "When": "every release",
         "Pause next wave if": "price at the till differs from the approved price",
         "Roll back the wave if": "new price below cost, wrong IVA or a pricing error: correct at once"}])
    return pairs, power, rollback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start"); ap.add_argument("--end")
    a = ap.parse_args()
    op = pd.read_parquet(CL / "optimal_prices.parquet").set_index("Code")
    weekly = pd.read_parquet(CL / "weekly_impact.parquet")
    if a.start and a.end:
        print(pd.Series(impact(weekly, a.start, a.end)).round(1).to_string())
        return
    acc = pd.read_excel(OUT / "price_accuracy.xlsx", sheet_name="Accuracy by SKU", dtype={"Code": str}).set_index("Code")
    cw = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Markdown_Week"])
    md_now = cw[cw.Week >= cw.Week.max() - pd.Timedelta(weeks=1)].groupby("Code").Markdown_Week.any()

    # ---- H1 shelf prices
    shelf, last = shelf_prices(list(op.index[op.in_scope.fillna(False)]))
    op = op.join(shelf[["Sales_UOM", "Shelf_Price_KZ", "Stores_Priced", "Stores_At_Main_Price_%"]])
    op["Change_%"] = op["Change_%"].fillna(0)
    new, note = [], []
    for code, r in op.iterrows():
        cur, dpc = r.Shelf_Price_KZ, r["Change_%"]
        if not (cur > 0) or dpc == 0:
            new.append(cur); note.append(""); continue
        p = R.round_shelf(cur, dpc)
        d = p / cur - 1
        cap = 0.15 if r.ABC != "A" else 0.10
        while d > 0 and ((1 + d) ** r.Rise - 1 < -cap - 1e-9):
            lower = [x for x in R.price_points(p) if cur < x < p]
            p = max(lower) if lower else cur
            d = p / cur - 1
        while d < 0 and r.P * (1 + d) < r.C:
            higher = [x for x in R.price_points(p) if p < x < cur]
            p = min(higher) if higher else cur
            d = p / cur - 1
        new.append(p); note.append("stepped back after rounding" if abs(d * 100 - dpc) > 2.5 else "")
    op["New_Shelf_Price_KZ"] = new
    op["Rounding_Note"] = note
    op["Final_Change_%"] = (op.New_Shelf_Price_KZ / op.Shelf_Price_KZ - 1) * 100
    op.loc[op.Shelf_Price_KZ.isna(), "Final_Change_%"] = 0
    # rounding impact (own response, 52 weeks)
    gp_opt = [own_gp(r, r["Change_%"] / 100)[0] for _, r in op.iterrows()]
    gp_rnd = [own_gp(r, (r["Final_Change_%"] if r["Final_Change_%"] == r["Final_Change_%"] else 0) / 100)[0] for _, r in op.iterrows()]
    op["Rounding_GP_effect_$"] = (np.array(gp_rnd) - np.array(gp_opt)) / FX
    # thresholds
    thr, keep = [], []
    for code, r in op.iterrows():
        cur, p = r.Shelf_Price_KZ, r.New_Shelf_Price_KZ
        crossed = [t for t in THRESHOLDS if cur < t <= p] if cur == cur and p == p else []
        if crossed:
            below = crossed[0] - 0.01
            g0 = own_gp(r, 0)[0]; gfull = own_gp(r, p / cur - 1)[0]; gb = own_gp(r, below / cur - 1)[0]
            thr.append(f"crosses {crossed[0]:,} Kz; {below:,.2f} keeps {((gb - g0) / max(gfull - g0, 1e-9)) * 100:.0f}% of the gain")
        else:
            thr.append("")
    op["Threshold_Flag"] = thr

    # ---- H3 business rules
    sub_p90 = op.groupby("SubGroup")["Margin_now_%"].quantile(0.9)
    fr = op["Final_Change_%"].fillna(0)
    units = op["Units_chg_%"].fillna(0)
    rules = pd.DataFrame(index=op.index)
    below = op.P * (1 + fr / 100) < op.C
    rules["R1 never below cost"] = np.select([below & (fr < 0), below & (fr > 0)], ["FAIL", "FLAG"], "PASS")   # rise still short of cost: 2nd step
    rules["R2 step and tested range"] = np.where(fr.abs() > 10.5, "FAIL", "PASS")
    rules["R3 endings"] = np.where((fr != 0) & ~op.New_Shelf_Price_KZ.apply(lambda p: p == p and round((p + 0.01) % 10, 2) == 0), "FLAG", "PASS")
    rules["R7 thresholds"] = np.where(op.Threshold_Flag != "", "FLAG", "PASS")
    rules["R8 recent big rise"] = np.where((fr > 0) & (op["Repriced_26w_%"] >= 15), "FAIL", "PASS")
    rules["R9 markdown running now"] = np.where((fr != 0) & op.index.map(md_now).fillna(False).astype(bool), "FLAG", "PASS")
    rules["R10 Everyday KVI"] = np.where((fr != 0) & (op.Insight == "Everyday KVI"), "FLAG", "PASS")
    rules["R11 selling vs system price"] = np.where((fr != 0) & op.index.map(acc.Accuracy_Flag).fillna("").str.contains(">5%"), "FLAG", "PASS")
    rules["R12 margin ceiling"] = np.where((fr > 0) & (op["Margin_new_%"] > op.SubGroup.map(sub_p90)), "FLAG", "PASS")
    rules["R14 unit-loss guardrail"] = np.where((fr > 0) & (units < -np.where(op.ABC == "A", 10, 15) - 0.5), "FAIL", "PASS")
    rules["R16 supply at risk: no cut"] = np.where((fr < 0) & op.Supply_Risk.fillna(False), "FAIL", "PASS")
    rules["R19 not on shelf: no change"] = np.where((fr != 0) & ~op.in_scope.fillna(False), "FAIL", "PASS")
    rules["R4/R5/R15 ladders, order, price lines"] = "not checked (needs pack data: short description phase)"
    op["Rule_FAILs"] = (rules == "FAIL").sum(axis=1)
    op["Rule_FLAGs"] = (rules == "FLAG").sum(axis=1)
    basket = (op["Final_Change_%"].fillna(0) * op.Revenue_USD.fillna(0)).sum() / op.Revenue_USD.fillna(0).sum()

    # ---- H4 reasons
    def reason(r):
        if r["Final_Change_%"] == 0 or r["Final_Change_%"] != r["Final_Change_%"]:
            return "Hold: " + (r.Hold_Reason if isinstance(r.Hold_Reason, str) else "no rise or cut pays within the guardrails")
        sens = "low price sensitivity" if r.Elasticity > -1 else "high price sensitivity" if r.Elasticity <= -2 else "moderate price sensitivity"
        parts = [("Raise" if r["Final_Change_%"] > 0 else "Cut") + f" {r['Final_Change_%']:+.1f}%", sens + f" ({r.Elasticity:.2f})",
                 f"margin {r['Margin_now_%']:.1f}% -> {r['Margin_new_%']:.1f}%"]
        if r["Cost_chg_26w_%"] == r["Cost_chg_26w_%"] and r["Cost_chg_26w_%"] - r["Price_chg_26w_%"] > 3:
            parts.append(f"cost +{r['Cost_chg_26w_%']:.0f}% vs price {r['Price_chg_26w_%']:+.0f}% in 26 weeks")
        if r.Diversion > 0.2:
            parts.append(f"{r.Diversion * 100:.0f}% of lost sales stay with SubGroup rivals")
        parts.append(f"units {r['Units_chg_%']:+.1f}%, GP {r['GP_gain_52w_$']:+,.0f} $/yr")
        return "; ".join(parts)
    op["Reason"] = op.apply(reason, axis=1)

    # ---- H5 waves
    rise = op["Final_Change_%"] > 0
    cut = op["Final_Change_%"] < 0
    test = (op.Insight == "Danger zone") & (op["Final_Change_%"] != 0) | op.index.isin(["100501", "100423", "107620", "107637", "100520"]) & (op["Final_Change_%"] != 0)
    # review: low evidence, big moves, any FAIL, or flags that need a person (thresholds, markdown running, still below cost);
    # selling-vs-system-price (R11, the open 14% IVA question) and margin-ceiling (R12) flags are notes, not a stop
    stop_flags = (rules[["R1 never below cost", "R7 thresholds", "R9 markdown running now"]] == "FLAG").any(axis=1)
    review = (op["Final_Change_%"] != 0) & ((op.Confidence == "Low") | (op["Final_Change_%"].abs() > 8) | (op.Rule_FAILs > 0) | stop_flags)
    op["Wave"] = np.select([op["Final_Change_%"].fillna(0) == 0, test, review], ["Hold", "Test", "Review then Wave 1"], "Wave 1")

    # ---- H2 store prices
    st = last.copy()
    st["Code"] = st.c
    st = st[st.Code.isin(op.index[op["Final_Change_%"] != 0])]
    st = st.join(op[["Shelf_Price_KZ", "Final_Change_%", "SubGroup", "Wave"]], on="Code")
    st["Store_vs_Chain_%"] = (st.PriceIVA / st.Shelf_Price_KZ - 1) * 100
    staple = st.SubGroup.fillna("").str.upper().apply(lambda s: any(k in s for k in STAPLES))
    st["Store_Rule"] = np.select([st.Plant.eq("HRCA"), st.Plant.isin(WHOLESALE) & staple & (st["Final_Change_%"] > 0),
                                  st["Store_vs_Chain_%"].abs() > OFF_TIER], ["HRCA: excluded", "wholesale staple: no rise", "store >12% off chain: check first"], "")
    st["New_Store_Price_KZ"] = np.where(st.Store_Rule == "", [R.round_shelf(p, d) for p, d in zip(st.PriceIVA, st["Final_Change_%"])], st.PriceIVA)
    st = st[["Code", "Plant", "SalesUOM", "PriceIVA", "New_Store_Price_KZ", "Store_vs_Chain_%", "Store_Rule", "Wave"]].rename(columns={"PriceIVA": "Store_Price_KZ"})
    st.to_parquet(CL / "store_prices.parquet", index=False)
    labels = st[st.New_Store_Price_KZ != st.Store_Price_KZ].groupby(["Wave", "Plant"]).size().groupby(level=0).agg(["median", "max"])

    # ---- H7 holdout stores, H6 windows
    chg = op["Final_Change_%"].fillna(0) != 0
    e = op[chg].sum(numeric_only=True)
    expected = {"GP": (e.GP_L / e.GP_now - 1) * 100, "Units": (e.Units_L / e.Units_now - 1) * 100, "Sales": (e.Rev_L / e.Rev_now - 1) * 100}
    pairs, power, rollback = holdout(set(op.index[chg]), expected)
    wins = pd.DataFrame([impact(weekly, s, e) for s, e in [("2026-11-30", "2027-01-31"), ("2026-12-01", "2026-12-31"), ("2027-01-01", "2027-03-31"),
                                                          ("2026-11-09", "2027-11-01")]])
    op.index.name = "Code"
    op.reset_index().to_parquet(CL / "price_list.parquet", index=False)
    pl = op.reset_index()[["Code", "Name", "MainGroup", "SubGroup", "Segment", "ABC", "Insight", "Confidence", "Wave", "Sales_UOM",
                           "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Final_Change_%", "Elasticity", "Units_chg_%", "Margin_now_%",
                           "Margin_new_%", "GP_gain_52w_$", "GP_gain_52w_cautious_$", "Rounding_GP_effect_$", "Threshold_Flag",
                           "Rule_FAILs", "Rule_FLAGs", "Reason"]]
    op["Recommendation_scope"] = np.where(op.in_scope.fillna(False), "In scope (on shelf)", "Not on shelf / no stock")
    wv = op.groupby(["Wave", "Recommendation_scope"]).agg(SKUs=("Name", "size"), Avg_change=("Final_Change_%", "mean"), GP_gain_52w=("GP_gain_52w_$", "sum"),
                                                 GP_gain_cautious=("GP_gain_52w_cautious_$", "sum"))
    g2 = pd.read_excel(OUT / "optimisation.xlsx", sheet_name="G2 optimiser test")
    milp = float(g2.loc[g2.Optimiser.str.startswith("MILP"), "GP_gain_likely_$"].iloc[0])
    by_wave = op.groupby("Wave")["GP_gain_52w_$"].sum()
    net = op["GP_gain_52w_$"].sum()
    bridge = pd.DataFrame([
        ("MILP optimiser, best price per SKU", milp),
        ("Trim: smallest move keeping 90% of each SKU's gain, minimum-gain rule", net - milp),
        ("= Plan gain, likely (headline)", net),
        ("   of which Wave 1", by_wave.get("Wave 1", 0)),
        ("   of which Review then Wave 1", by_wave.get("Review then Wave 1", 0)),
        ("   of which Test", by_wave.get("Test", 0)),
        ("   of which Hold (unchanged SKUs gaining from shoppers switching to them)", by_wave.get("Hold", 0)),
        ("Shelf-price rounding", op["Rounding_GP_effect_$"].sum()),
        ("= Plan gain after rounding", net + op["Rounding_GP_effect_$"].sum()),
        ("Cautious case (customers react 1.5x)", op["GP_gain_52w_cautious_$"].sum())],
        columns=["Item", "GP_gain_52w_$"]).round(0)
    with pd.ExcelWriter(OUT / "price_list.xlsx") as xw:
        pd.DataFrame({"Item": ["SKUs priced", "Raise", "Cut", "Hold", "Rule FAILs", "SKUs with FLAGs", "Basket price change % (sales weighted)",
                               "Basket change in months of CPI (0.6%/month)", "Rounding effect on GP $/yr", "Store price rows"],
                      "Value": [int(op.Shelf_Price_KZ.notna().sum()), int(rise.sum()), int(cut.sum()), int((op["Final_Change_%"].fillna(0) == 0).sum()),
                                int(op.Rule_FAILs.sum()), int((op.Rule_FLAGs > 0).sum()), round(basket, 2), round(basket / CPI_MONTHLY, 1),
                                round(op["Rounding_GP_effect_$"].sum()), len(st)]}).to_excel(xw, sheet_name="Summary", index=False)
        wins.round(1).to_excel(xw, sheet_name="H6 impact windows", index=False)
        wv.round(1).to_excel(xw, sheet_name="H5 waves")
        labels.to_excel(xw, sheet_name="H5 labels per store")
        pl[pl["Final_Change_%"].fillna(0) != 0].round(2).to_excel(xw, sheet_name="Price list (changes)", index=False)
        pl.round(2).to_excel(xw, sheet_name="All SKUs", index=False)
        rules.reset_index().to_excel(xw, sheet_name="H3 rules", index=False)
        (rules == "FAIL").sum().to_frame("FAIL").join((rules == "FLAG").sum().to_frame("FLAG")).to_excel(xw, sheet_name="H3 rule counts")
        st[st.Store_Rule != ""].to_excel(xw, sheet_name="H2 store exceptions", index=False)
        pairs.round(0).to_excel(xw, sheet_name="H7 holdout pairs", index=False)
        power.round(2).to_excel(xw, sheet_name="H7 holdout power", index=False)
        rollback.to_excel(xw, sheet_name="H8 rollback rules", index=False)
        bridge.to_excel(xw, sheet_name="Profit bridge", index=False)
    pd.set_option("display.width", 220)
    print(f"raise {int(rise.sum())} cut {int(cut.sum())} | FAIL {int(op.Rule_FAILs.sum())} | flagged SKUs {int((op.Rule_FLAGs > 0).sum())} | basket {basket:+.2f}% "
          f"({basket / CPI_MONTHLY:.1f} months CPI) | rounding {op['Rounding_GP_effect_$'].sum():+,.0f} $/yr")
    print(wv.round(1).to_string()); print(wins.round(1).to_string(index=False)); print(power.round(2).to_string(index=False)); print(rollback.to_string(index=False)); print(bridge.to_string(index=False))
    print((rules == "FAIL").sum()[lambda x: x > 0].to_string()); print((rules == "FLAG").sum()[lambda x: x > 0].to_string())


if __name__ == "__main__":
    main()
