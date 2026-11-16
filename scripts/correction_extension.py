"""Sweet-spot plan, part 2: price corrections on articles outside the 40-article pilot.

Selection comes from the price-correction review (analysis/price_correction/correction.xlsx), which checked the
categories flagged in the Retail Performance Insights YTD Sep-26 report: articles whose cost rose faster than their
price, sell below cost or at a very low margin. The recommended (sweet-spot) rise is kept: back toward last year's
margin, max +10%, units loss <= 5% (staples <= 3%). Here it becomes a shelf price on the Fresmart price endings, and
the impact is re-done on the rounded price for 2 Nov - 27 Dec (8 weeks, as the pilot) and for 12 months.

Outputs: clean/pilot/correction_prices.parquet, analysis/pilot/correction_prices.xlsx
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import pilot_optimise as O
import pilot_recommend as R

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "pilot", ROOT / "analysis" / "pilot"
NEED = ["Selling below cost", "Cost rose, price did not follow", "Very low margin", "Margin down (other)", "More discounting"]
WEEKS = 8                                        # 2 Nov - 27 Dec, same window as the pilot plan
MIN_RISE = 1.0                                   # below +1% the change is not worth a shelf-label change
STAPLES = R.STAPLES
FX = json.load(open(ROOT / "analysis" / "price_correction" / "correction.json"))["fx"]   # Kz per USD, as in the review


def main():
    a = pd.read_excel(ROOT / "analysis" / "price_correction" / "correction.xlsx", sheet_name="articles", dtype={"ArticleCode": str})
    a["ArticleCode"] = a.ArticleCode.map(O.z)
    pilot = set(pd.read_parquet(CL / "validated_prices.parquet").ArticleCode)
    # chicken legs are supply-limited by the import ban: full correction within the current-plan volume limit (15%)
    leg = a.ScopeID.isin(["A1", "A6", "C4"]) & a.ArticalName.str.contains("COXA|PERNA")
    a["rise_%"] = np.where(leg, a["rise_full_%"], a["rise_capped_%"])
    a["Scarcity"] = leg
    sel = a[a.diagnosis.isin(NEED) & ~a.ArticleCode.isin(pilot) & (a["rise_%"] >= MIN_RISE)].copy()
    shelf, _ = R.shelf_prices([c.lstrip("0") for c in sel.ArticleCode])
    shelf.index = [O.z(c) for c in shelf.index]
    sel = sel.join(shelf, on="ArticleCode")
    sel = sel[sel.Shelf_Price_KZ.notna()]
    sel["New_Shelf_Price_KZ"] = [R.round_shelf(p, d) for p, d in zip(sel.Shelf_Price_KZ, sel["rise_%"])]
    sel["Price_Change_%"] = (sel.New_Shelf_Price_KZ / sel.Shelf_Price_KZ - 1) * 100
    # rounding can overshoot the volume limit: step back one price point while it does
    m = pd.read_parquet(ROOT / "checkpoints" / "dim_article_master.parquet")
    m["ArticleCode"] = m.ArticalCode.astype(str).map(O.z)
    sel["SubGroup"] = sel.ArticleCode.map(m.drop_duplicates("ArticleCode").set_index("ArticleCode").SubGroup)
    staple = sel.SubGroup.fillna("").str.upper().apply(lambda s: any(k in s for k in STAPLES))
    cap = np.where(sel.Scarcity, 0.15, np.where(staple, 0.03, 0.05))
    for i in range(len(sel)):
        idx = sel.index[i]
        while True:
            d = sel.at[idx, "Price_Change_%"] / 100
            if d <= 0 or (1 + d) ** sel.at[idx, "elasticity"] - 1 >= -cap[i] - 1e-9:
                break
            cur, new = sel.at[idx, "Shelf_Price_KZ"], sel.at[idx, "New_Shelf_Price_KZ"]
            lower = [p for p in R.price_points(new) if cur < p < new]
            sel.at[idx, "New_Shelf_Price_KZ"] = max(lower) if lower else cur
            sel.at[idx, "Price_Change_%"] = (sel.at[idx, "New_Shelf_Price_KZ"] / cur - 1) * 100
    # price ladder with the pilot legs (same brand / pack): keep Koch Black one price point above the new Koch Orange
    vp = pd.read_parquet(CL / "validated_prices_sweetspot.parquet").set_index("ArticleCode").New_Shelf_Price_KZ
    LADDER = {O.z("100498"): (O.z("107637"), 100)}
    for code, (ref, gap) in LADDER.items():
        idx = sel.index[sel.ArticleCode == code]
        if len(idx) and ref in vp.index:
            i0 = idx[0]
            sel.at[i0, "New_Shelf_Price_KZ"] = min(sel.at[i0, "New_Shelf_Price_KZ"], vp[ref] + gap)
            sel.at[i0, "Price_Change_%"] = (sel.at[i0, "New_Shelf_Price_KZ"] / sel.at[i0, "Shelf_Price_KZ"] - 1) * 100
    sel = sel[sel["Price_Change_%"] >= MIN_RISE - 1e-9]
    sel["Staple"] = staple.reindex(sel.index)
    # impact on the rounded change; recent run rate (Jul-Sep 2026) x 4 = 12 months
    d = sel["Price_Change_%"] / 100
    e = sel.elasticity
    U = sel.sales_12m_usd / (sel.price / FX)                     # 12-month base units (price is Kz per base unit)
    gp_unit_now = sel.price - sel.cost
    for tag, ee in (("", e), ("_Cautious", e * 1.5)):
        U2 = U * (1 + d) ** ee
        sel[f"GP_Change_12m_USD{tag}"] = (U2 * (sel.price * (1 + d) - sel.cost) - U * gp_unit_now) / FX
    sel["Units_Change_%"] = ((1 + d) ** e - 1) * 100
    sel["Units_Change_Cautious_%"] = ((1 + d) ** (e * 1.5) - 1) * 100
    sel["Revenue_Change_12m_USD"] = (U * (1 + d) ** e * sel.price * (1 + d) - U * sel.price) / FX
    for c in ("GP_Change_12m_USD", "GP_Change_12m_USD_Cautious", "Revenue_Change_12m_USD"):
        sel[c.replace("12m", "8w")] = sel[c] * WEEKS / 52
    sel["New_GP_%"] = (1 - sel.cost / (sel.price * (1 + d))) * 100
    sel["Effective_Date"] = pd.Timestamp("2026-11-02")
    wave = {"A1": "Wave 1", "A6": "Wave 1", "C4": "Wave 1", "A3": "Wave 2", "A4": "Wave 2", "B5": "Wave 2", "A2": "Wave 2"}
    sel["Wave"] = sel.ScopeID.map(wave).fillna("Wave 3")
    cols = ["ArticleCode", "ArticalName", "Scope", "ScopeID", "Wave", "diagnosis", "Sales_UOM", "Shelf_Price_KZ", "New_Shelf_Price_KZ",
            "Price_Change_%", "Scarcity", "cost_chg_%", "price_chg_%", "gp_pct_ly", "gp_pct", "New_GP_%", "elasticity", "Staple",
            "Units_Change_%", "Units_Change_Cautious_%", "sales_12m_usd", "GP_Change_8w_USD", "GP_Change_8w_USD_Cautious",
            "GP_Change_12m_USD", "GP_Change_12m_USD_Cautious", "Revenue_Change_12m_USD", "Stores_Priced", "Effective_Date"]
    out = sel[cols].rename(columns={"ArticalName": "ArticleName", "diagnosis": "Diagnosis", "cost_chg_%": "Cost_Change_YoY_%",
                                    "price_chg_%": "Price_Change_YoY_%", "gp_pct_ly": "GP_%_LY", "gp_pct": "GP_%_Now",
                                    "elasticity": "Elasticity", "sales_12m_usd": "Sales_12m_USD"}).sort_values("GP_Change_12m_USD", ascending=False)
    out.to_parquet(CL / "correction_prices.parquet", index=False)
    summ = out.groupby(["Wave", "Scope"]).agg(Articles=("ArticleCode", "size"), Sales_12m_USD=("Sales_12m_USD", "sum"),
                                              Avg_Rise_pct=("Price_Change_%", "mean"), GP_8w_USD=("GP_Change_8w_USD", "sum"),
                                              GP_12m_USD=("GP_Change_12m_USD", "sum"), GP_12m_Cautious_USD=("GP_Change_12m_USD_Cautious", "sum"))
    with pd.ExcelWriter(OUT / "correction_prices.xlsx") as xw:
        summ.round(1).to_excel(xw, sheet_name="Summary")
        out.round(2).to_excel(xw, sheet_name="Price list", index=False)
    pd.set_option("display.width", 250)
    print(summ.round(0).to_string())
    print("articles", len(out), "| GP 8w $", round(out.GP_Change_8w_USD.sum()), "| 12m $", round(out.GP_Change_12m_USD.sum()),
          "cautious", round(out.GP_Change_12m_USD_Cautious.sum()), "| units (sales-weighted) %",
          round((out["Units_Change_%"] * out.Sales_12m_USD).sum() / out.Sales_12m_USD.sum(), 1),
          "| revenue 12m $", round(out.Revenue_Change_12m_USD.sum()))
    print(out[["ArticleName", "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Price_Change_%", "Units_Change_%", "GP_Change_12m_USD"]].head(25).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
