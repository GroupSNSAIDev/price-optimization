"""Behaviour lenses for every ACTIVE SKU: price sensitivity, frequency, reach, stability, trend, seasonality,
price vs inflation and margin direction. Each lens is a set of rule-based groups (like the portfolio segments).

Price sensitivity is an early estimate on the refreshed data (to 8 Nov 2026), not the final pricing model:
  per SKU, log units on log category-relative price, store and week fixed effects (two-way within),
  model-sample rows of the last 104 full weeks, below-cost (clearance) weeks left out, HRCA left out;
  shrunk towards the SubGroup mean (empirical Bayes). SKUs with too little price movement get the SubGroup
  mean and are marked "not measured".

Margins are NET of IVA (user decision 2026-11-15): each SKU's sales are scaled by its recorded tax share.

Inputs: clean/weekly_model.parquet, <dest>/portfolio.json (revenue, GP, segments), clean/allsku/chain_weekly.parquet
Outputs: clean/allsku/sku_behaviour.parquet, analysis/allsku/sku_behaviour.xlsx, <dest>/behaviour.json (default clean/allsku)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from elasticity import demean2

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
CPI_YOY = 8.43            # Angola CPI, Sep 2026 vs Sep 2025 (IMF / INE)


def z(c):
    return str(c).lstrip("0")


LENSES = {
    "Price sensitivity": [
        ("Highly elastic", "elasticity -2 or below: a 10% rise loses 20%+ of units"),
        ("Elastic", "elasticity -2 to -1: units fall faster than price rises"),
        ("Moderate", "elasticity -1 to -0.5"),
        ("Inelastic", "elasticity -0.5 to 0: price barely moves units"),
        ("Unclear (+)", "units rose with price: supply or mix effect, needs a test"),
        ("Not measured", "too little price movement: SubGroup value used"),
    ],
    "Purchase frequency": [
        ("Daily-need", "top 10% by tickets per store-week"),
        ("Frequent", "next 25%"),
        ("Occasional", "next 35%"),
        ("Rare", "last 30%"),
    ],
    "Store reach": [
        ("Everywhere", "sold in 90%+ of stores each week"),
        ("Wide", "60-90% of stores"),
        ("Partial", "25-60% of stores"),
        ("Niche", "under 25% of stores"),
    ],
    "Demand stability": [
        ("Steady", "typical week-to-week change under 15%"),
        ("Variable", "15-35%"),
        ("Erratic", "over 35%"),
    ],
    "Trend": [
        ("Growing fast", "units per store, last 13 weeks +25% or more vs same weeks last year (same stores)"),
        ("Growing", "+5% to +25%"),
        ("Flat", "-5% to +5%"),
        ("Declining", "-5% to -25%"),
        ("Falling fast", "-25% or worse"),
        ("New", "not sold a year ago"),
    ],
    "Seasonality": [
        ("December peaker", "Dec 2025 weekly units 40%+ above Oct-Nov 2025"),
        ("December lift", "+15% to +40%"),
        ("Not seasonal", "within +-15%"),
        ("December dip", "15%+ below"),
        ("No history", "not sold in Q4 2025"),
    ],
    "Price vs inflation": [
        ("Above inflation", f"price up more than CPI ({CPI_YOY:.1f}%) + 5 pts in a year"),
        ("With inflation", "within 5 pts of CPI"),
        ("Below inflation", "price up less than CPI - 5 pts: real price falling"),
        ("Price cut", "price lower than a year ago"),
        ("No history", "not sold a year ago"),
    ],
    "Margin direction": [
        ("Margin up", "last 13 weeks 3+ pts above same weeks last year"),
        ("Margin stable", "within 3 pts"),
        ("Margin down", "3+ pts below"),
        ("No history", "not sold a year ago"),
    ],
}


def elasticities(w):
    rows = []
    for c, g in w.groupby("c", sort=False):
        if len(g) < 40:
            continue
        g1 = g.Plant.astype("category").cat.codes.to_numpy()
        g2 = g.Week.astype("category").cat.codes.to_numpy()
        n1, n2 = int(g1.max()) + 1, int(g2.max()) + 1
        x = demean2(g.ln_Relative_Price.to_numpy(), g1, g2, n1, n2)
        y = demean2(g.ln_Qty.to_numpy(), g1, g2, n1, n2)
        sxx = (x * x).sum()
        sd = np.sqrt(sxx / len(g))
        if sd < 0.02:
            continue
        b = (x * y).sum() / sxx
        e = y - b * x
        dof = max(len(g) - n1 - n2, 1)
        se = np.sqrt((x * x * e * e).sum() / sxx ** 2 * len(g) / dof)
        rows.append((c, len(g), sd, b, se))
    return pd.DataFrame(rows, columns=["c", "obs", "price_sd", "e_raw", "se"]).set_index("c")


def main(dest):
    CL.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    pf = pd.DataFrame(json.loads((dest / "portfolio.json").read_text(encoding="utf-8"))).set_index("Code")
    cols = ["Week", "Plant", "ArticleCode", "Qty_Clean", "Sales_KZ", "KZ_COGS", "Txn_Count", "Channel", "In_Model_Sample",
            "Below_Cost_Week", "ln_Qty", "ln_Relative_Price", "Realized_Price_KZ"]
    w = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=cols)
    w = w[w.Channel != "HRCA"]
    w["c"] = w.ArticleCode.map(z)
    w = w[w.c.isin(pf.index)]
    full = sorted(w.Week.unique())[:-1]
    w = w[w.Week.isin(full)]
    end = pd.Timestamp(full[-1])

    # ---- price sensitivity
    m = w[w.In_Model_Sample & ~w.Below_Cost_Week.fillna(False) & (w.Week > end - pd.Timedelta(weeks=104))
          & np.isfinite(w.ln_Qty) & np.isfinite(w.ln_Relative_Price)]
    a = elasticities(m)
    a["SubGroup"] = pf.SubGroup.reindex(a.index)
    a["prec"] = 1 / a.se.clip(lower=0.01) ** 2
    g = a.groupby("SubGroup")
    gm = g.apply(lambda d: np.average(d.e_raw.clip(-6, 2), weights=d.prec), include_groups=False)
    tau2 = g.apply(lambda d: max(np.var(d.e_raw.clip(-6, 2)) - np.mean(d.se ** 2), 0.05), include_groups=False)
    a["group_mean"] = a.SubGroup.map(gm)
    wt = a.SubGroup.map(tau2) / (a.SubGroup.map(tau2) + a.se ** 2)
    # final value capped at -4 (as in the pilot): beyond that the estimate is brand switching inside the category
    a["elasticity"] = (wt * a.e_raw.clip(-6, 2) + (1 - wt) * a.group_mean).clip(upper=None, lower=-4)
    a["shrink_wt"] = wt
    overall = np.average(a.e_raw.clip(-6, 2), weights=a.prec)
    b = pf[["Name", "SubGroup", "MainGroup", "ShortDesc", "Segment", "ABC", "On_Shelf", "Revenue_USD", "GP_USD",
            "Margin_Pct", "Rev_Share_Pct", "GP_Share_Pct"]].copy()
    b = b.join(a[["obs", "price_sd", "e_raw", "se", "shrink_wt", "elasticity"]])
    b["measured"] = b.elasticity.notna()
    b["elasticity"] = b.elasticity.fillna(b.SubGroup.map(gm)).fillna(overall)
    b["e_ci_low"] = b.e_raw - 1.96 * b.se
    b["e_ci_high"] = b.e_raw + 1.96 * b.se

    # ---- behaviour measures (last 52 weeks unless stated)
    l52 = w[w.Week > end - pd.Timedelta(weeks=52)]
    stores_wk = l52.groupby("Week").Plant.nunique()
    sw = l52.groupby(["c", "Week"]).agg(q=("Qty_Clean", "sum"), st=("Plant", "nunique"), t=("Txn_Count", "sum"))
    sw = sw.join(stores_wk.rename("all_st"), on="Week")
    b["tickets_per_store_wk"] = (sw.t / sw.st).groupby(level=0).mean()
    b["reach_pct"] = (sw.st / sw.all_st * 100).groupby(level=0).mean()
    b["weeks_sold_52"] = sw.groupby(level=0).size()
    cu = sw.q.unstack(fill_value=0)
    cu = cu.loc[:, cu.columns > end - pd.Timedelta(weeks=52)]
    b["cv_pct"] = (cu.std(axis=1) / cu.mean(axis=1) * 100)
    # stability: typical week-to-week change of chain units, weeks with sales only
    lq = np.log(cu.where(cu > 0))
    b["wow_change_pct"] = (np.exp(lq.diff(axis=1).abs().median(axis=1)) - 1) * 100
    # trend: last 13 weeks vs the same 13 weeks a year earlier (chain units)
    t0, t1, l0, l1 = end - pd.Timedelta(weeks=13), end, end - pd.Timedelta(weeks=65), end - pd.Timedelta(weeks=52)
    lfl = set(w[(w.Week > t0) & (w.Week <= t1)].Plant) & set(w[(w.Week > l0) & (w.Week <= l1)].Plant)

    cwt = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Sales_KZ", "Tax_KZ"])

    def window(a0, a1):
        d = w[(w.Week > a0) & (w.Week <= a1) & w.Plant.isin(lfl)].groupby("c").agg(q=("Qty_Clean", "sum"), s=("Sales_KZ", "sum"), k=("KZ_COGS", "sum"))
        tx = cwt[(cwt.Week > a0) & (cwt.Week <= a1)].groupby("Code")[["Sales_KZ", "Tax_KZ"]].sum()
        d["net"] = d.s * (1 - (tx.Tax_KZ / tx.Sales_KZ).reindex(d.index).fillna(0))
        d["p"] = d.s / d.q
        d["mg"] = (d.net - d.k) / d.net * 100
        return d
    now, ly = window(t0, t1), window(l0, l1)
    print(f"like-for-like stores for trend: {len(lfl)}")
    b["units_yoy_pct"] = (now.q / ly.q - 1) * 100
    b["price_yoy_pct"] = (now.p / ly.p - 1) * 100
    b["margin_yoy_pts"] = now.mg - ly.mg
    b["had_ly"] = b.index.isin(ly.index[ly.q > 0])
    # seasonality: Dec 2025 vs Oct-Nov 2025 average weekly units
    q4 = w[(w.Week >= "2025-10-06") & (w.Week <= "2025-12-28")].copy()
    q4["dec"] = q4.Week >= "2025-12-01"
    s = q4.groupby(["c", "dec"]).agg(q=("Qty_Clean", "sum"), n=("Week", "nunique")).unstack()
    b["dec_vs_octnov_pct"] = ((s["q"][True] / s["n"][True]) / (s["q"][False] / s["n"][False]) - 1) * 100

    # ---- lens assignment
    e = b.elasticity
    b["Price sensitivity"] = np.select([~b.measured, e <= -2, e <= -1, e <= -0.5], ["Not measured", "Highly elastic", "Elastic", "Moderate"],
                                     "Inelastic")
    b.loc[b.measured & (e > 0), "Price sensitivity"] = "Unclear (+)"
    tk = b.tickets_per_store_wk.rank(pct=True)
    b["Purchase frequency"] = np.select([tk >= 0.9, tk >= 0.65, tk >= 0.3], ["Daily-need", "Frequent", "Occasional"], "Rare")
    b["Store reach"] = np.select([b.reach_pct >= 90, b.reach_pct >= 60, b.reach_pct >= 25], ["Everywhere", "Wide", "Partial"], "Niche")
    b["Demand stability"] = np.select([b.wow_change_pct < 15, b.wow_change_pct <= 35], ["Steady", "Variable"], "Erratic")
    u = b.units_yoy_pct
    b["Trend"] = np.select([~b.had_ly | u.isna(), u >= 25, u >= 5, u > -5, u > -25], ["New", "Growing fast", "Growing", "Flat", "Declining"], "Falling fast")
    d = b.dec_vs_octnov_pct
    b["Seasonality"] = np.select([d.isna(), d >= 40, d >= 15, d > -15], ["No history", "December peaker", "December lift", "Not seasonal"], "December dip")
    p = b.price_yoy_pct
    b["Price vs inflation"] = np.select([~b.had_ly | p.isna(), p < 0, p > CPI_YOY + 5, p >= CPI_YOY - 5], ["No history", "Price cut", "Above inflation", "With inflation"], "Below inflation")
    mg = b.margin_yoy_pts
    b["Margin direction"] = np.select([~b.had_ly | mg.isna(), mg >= 3, mg > -3], ["No history", "Margin up", "Margin stable"], "Margin down")

    # ---- summary tables
    TR, TG = b.Revenue_USD.sum(), b.GP_USD.sum()
    tabs = []
    for lens, groups in LENSES.items():
        for name, rule in groups:
            d = b[b[lens] == name]
            rev, gp = d.Revenue_USD.sum(), d.GP_USD.sum()
            tabs.append({"Lens": lens, "Group": name, "Rule": rule, "SKUs": len(d), "On_Shelf": int(d.On_Shelf.sum()),
                         "Rev_Pct": round(rev / TR * 100, 2), "GP_Pct": round(gp / TG * 100, 2),
                         "Margin_Pct": round(gp / rev * 100, 1) if rev else None,
                         "Avg_Elasticity": round(float(np.average(d.elasticity, weights=d.Revenue_USD.clip(lower=1))), 2) if len(d) else None})
    tabs = pd.DataFrame(tabs)

    out = b.reset_index().rename(columns={"index": "Code"})
    out.to_parquet(CL / "sku_behaviour.parquet", index=False)
    lens_cols = list(LENSES)
    keep = ["Code", "elasticity", "measured", "e_ci_low", "e_ci_high", "tickets_per_store_wk", "reach_pct", "cv_pct",
            "wow_change_pct", "units_yoy_pct", "price_yoy_pct", "margin_yoy_pts", "dec_vs_octnov_pct"] + lens_cols
    j = out[keep].round(3).replace({np.nan: None})
    (dest / "behaviour.json").write_text(json.dumps(j.to_dict("records"), separators=(",", ":")), encoding="utf-8")
    (dest / "behaviour_lenses.json").write_text(json.dumps(tabs.replace({np.nan: None}).to_dict("records")), encoding="utf-8")
    with pd.ExcelWriter(OUT / "sku_behaviour.xlsx") as xw:
        tabs.to_excel(xw, sheet_name="Lenses", index=False)
        pd.crosstab(b["Price sensitivity"], b.Segment, values=b.Revenue_USD, aggfunc="sum").div(TR / 100).round(1).to_excel(xw, sheet_name="Sensitivity x Segment")
        out.to_excel(xw, sheet_name="SKUs", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    print(f"measured {int(b.measured.sum())} of {len(b)} SKUs ({b.Revenue_USD[b.measured].sum() / TR * 100:.1f}% of revenue); "
          f"overall {overall:.2f}; median measured {b.elasticity[b.measured].median():.2f}; "
          f"positive raw {int((b.e_raw > 0).sum())}, positive after shrink {int((b.elasticity > 0).sum())}")
    print(tabs.to_string(index=False))
    sel = b[b.measured & b.On_Shelf & (b.ABC == "A")]
    print("\nMOST elastic A on shelf\n", sel.nsmallest(12, "elasticity")[["Name", "Segment", "elasticity", "e_raw", "se", "Margin_Pct"]].round(2).to_string())
    print("\nLEAST elastic A on shelf\n", sel.nlargest(12, "elasticity")[["Name", "Segment", "elasticity", "e_raw", "se", "Margin_Pct"]].round(2).to_string())
    print("\nSensitivity x Segment (% revenue)\n", pd.crosstab(b["Price sensitivity"], b.Segment, values=b.Revenue_USD, aggfunc="sum").div(TR / 100).round(1).to_string())


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else CL)
