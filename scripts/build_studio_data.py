"""Pricing Studio (all active SKUs): data for dashboard/studio/ from the all-SKU pipeline outputs.

Writes dashboard/studio/data/:
  meta.json     plan totals, bridge, waves, scenarios, frontier, limits, timing, store test, rules, stock-outs, tests, checks,
                forecast accuracy, price-sensitivity bands, the before picture, gain by MainGroup
  skus.json     every active SKU (columns + rows): prices, change, wave, reason, price effects, margins, gains, flags
  weekly.json   chain totals by week (now / likely / cautious / optimistic units and GP) and by wave
  weekly_sku.json  week-by-week units now vs new for every changed SKU
  flags.json    rule FLAGs / FAILs per SKU
  history/gNN.json  weekly price history per SKU (one file per MainGroup): regular and selling price, cost (with IVA, per
                sales pack) and units, Jan 2024 on
Money in US dollars at 1,050 Kz, gross profit after IVA.

Run after the pipeline, allsku_checks.py and allsku_event_check.py:  python scripts/build_studio_data.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, A = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
OUT = ROOT / "dashboard" / "studio" / "data"
FX = 1050.0


def rec(df):
    return json.loads(df.to_json(orient="records", double_precision=4))


def xl(f, sheet, **kw):
    return pd.read_excel(A / f, sheet_name=sheet, **kw)


def skus():
    pl = pd.read_parquet(CL / "price_list.parquet")
    so = xl("stockouts.xlsx", "By SKU", dtype={"Code": str}).set_index("Code")
    usd = lambda c: pl[c] / FX
    d = pd.DataFrame({
        "code": pl.Code, "name": pl.Name, "group": pl.MainGroup, "sub": pl.SubGroup, "sd": pl.ShortDesc.fillna("Other"), "brand": pl.Brand, "segment": pl.Segment,
        "insight": pl.Insight, "abc": pl.ABC, "shelf": pl.in_scope.fillna(False).astype(bool), "conf": pl.Confidence,
        "wave": pl.Wave, "price": pl.Shelf_Price_KZ, "new_price": pl.New_Shelf_Price_KZ, "chg": pl["Final_Change_%"].fillna(0),
        "opt": pl["Change_%"].fillna(0), "p_net": pl.P, "cost": pl.C, "units": pl.Base_52w, "e": pl.Elasticity, "e_rise": pl.Rise,
        "e_cut": pl.Cut, "e_caut": pl.Cautious, "div": pl.Diversion, "m_now": pl["Margin_now_%"], "m_new": pl["Margin_new_%"],
        "gp_now": usd("GP_now"), "gain": pl["GP_gain_52w_$"], "gain_c": pl["GP_gain_52w_cautious_$"], "units_chg": pl["Units_chg_%"],
        "rev": pl.Revenue_USD, "reason": pl.Reason.fillna(""), "fails": pl.Rule_FAILs.fillna(0), "flags": pl.Rule_FLAGs.fillna(0),
        "supply_risk": pl.Supply_Risk.fillna(False).astype(bool), "stockout": pl["Stockout_13w_%"],
        "up": pl.Range_Up, "down": pl.Range_Down, "repriced": pl["Repriced_26w_%"], "stores": pl.Stores_Priced,
        "kvi": pl.Insight.eq("Everyday KVI"), "lost_sales": pl.Code.map(so.Lost_sales_USD)})
    d["gp_now"] = d.gp_now.where(d.units > 0)
    num = d.select_dtypes("number").columns
    d[num] = d[num].replace([np.inf, -np.inf], np.nan).round(4)
    return {"columns": list(d.columns), "rows": json.loads(d.to_json(orient="values", double_precision=4))}


def weekly():
    w = pd.read_parquet(CL / "weekly_impact.parquet")
    wave = pd.read_parquet(CL / "price_list.parquet", columns=["Code", "Wave"]).set_index("Code").Wave
    w["Wave"] = w.Code.map(wave).fillna("Hold")
    cols = ["Units_now", "Units_new_L", "Units_new_S", "Units_new_O", "GP_now_KZ", "GP_new_L_KZ", "GP_new_S_KZ", "GP_new_O_KZ"]
    t = w.groupby("Week")[cols].sum().reset_index()
    for c in cols[4:]:
        t[c] = t[c] / FX
    t["Week"] = t.Week.dt.strftime("%Y-%m-%d")
    bw = w.groupby(["Wave", "Week"])[["GP_now_KZ", "GP_new_L_KZ"]].sum().reset_index()
    bw["gain"] = (bw.GP_new_L_KZ - bw.GP_now_KZ) / FX
    bw["Week"] = bw.Week.dt.strftime("%Y-%m-%d")
    chg = pd.read_parquet(CL / "price_list.parquet", columns=["Code", "Final_Change_%"])
    changed = set(chg.Code[chg["Final_Change_%"].fillna(0) != 0])
    ws = w[w.Code.isin(changed)].sort_values(["Code", "Week"])
    per = {c: {"now": g.Units_now.round(1).tolist(), "new": g.Units_new_L.round(1).tolist(), "low": g.Units_new_S.round(1).tolist(),
               "high": g.Units_new_O.round(1).tolist()} for c, g in ws.groupby("Code")}
    return ({"weeks": t.Week.tolist(), "chain": rec(t.drop(columns="Week")),
             "by_wave": {k: g.gain.round(0).tolist() for k, g in bw.groupby("Wave")}},
            {"weeks": sorted(ws.Week.dt.strftime("%Y-%m-%d").unique().tolist()), "skus": per})


def history():
    """weekly price history per SKU, Jan 2024 on, split by MainGroup: shelf-equivalent regular and selling price, cost, units.
    Chain prices are per base unit; they are scaled to the sales pack with today's shelf price / the last 4 weeks' regular price."""
    pl = pd.read_parquet(CL / "price_list.parquet", columns=["Code", "MainGroup", "Shelf_Price_KZ"]).set_index("Code")
    iva = pd.read_parquet(CL / "iva_by_sku.parquet").set_index("Code").IVA_Pct
    cw = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Units", "Price_KZ", "Regular_Price_KZ", "Unit_Cost_KZ"])
    cw = cw[cw.Code.isin(pl.index)].sort_values(["Code", "Week"])
    weeks = pd.date_range(cw.Week.min(), cw.Week.max(), freq="7D")
    out = {}
    for code, g in cw.groupby("Code"):
        g = g.set_index("Week").reindex(weeks)
        last = g.Regular_Price_KZ.dropna().tail(4).median()
        shelf = pl.at[code, "Shelf_Price_KZ"]
        k = shelf / last if shelf == shelf and shelf > 0 and last == last and last > 0 else float("nan")
        if k != k:
            continue
        cost_pack = g.Unit_Cost_KZ * k * (1 + iva.get(code, 0) / 100)      # cost on the same footing as the shelf price (with IVA)
        rnd = lambda x: [None if v != v else round(float(v), 2) for v in x]
        out.setdefault(pl.at[code, "MainGroup"], {})[code] = {"reg": rnd(g.Regular_Price_KZ * k), "sell": rnd(g.Price_KZ * k),
                                                               "cost": rnd(cost_pack), "units": rnd(g.Units.fillna(0))}
    return [d.strftime("%Y-%m-%d") for d in weeks], out


def flags():
    r = xl("price_list.xlsx", "H3 rules", dtype={"Code": str}).set_index("Code")
    r = r.drop(columns=[c for c in r.columns if c.startswith("R4/")])
    out = {}
    for code, row in r.iterrows():
        f = [[k, v] for k, v in row.items() if v in ("FLAG", "FAIL")]
        if f:
            out[code] = f
    return out


def meta():
    pl = pd.read_parquet(CL / "price_list.parquet")
    br = xl("price_list.xlsx", "Profit bridge")
    sm = xl("price_list.xlsx", "Summary").set_index("Item").Value
    t = pl.sum(numeric_only=True)
    chg = pl["Final_Change_%"].fillna(0)
    m = {"as_of": "2 Nov 2026", "fx": FX}
    m["plan"] = {"gain": float(br.iloc[8, 1]), "gain_before_rounding": float(br.iloc[2, 1]), "cautious": float(br.iloc[9, 1]),
                 "optimistic": float(xl("optimisation.xlsx", "G4 scenarios").iloc[0]["GP_gain_optimistic_$"]),
                 "gp_now": float(t.GP_now / FX), "units_pct": float((t.Units_L / t.Units_now - 1) * 100),
                 "rev_pct": float((t.Rev_L / t.Rev_now - 1) * 100), "rises": int((chg > 0).sum()), "cuts": int((chg < 0).sum()),
                 "held": int((chg == 0).sum()), "skus": int(len(pl)), "on_shelf": int(pl.in_scope.fillna(False).sum()),
                 "basket": float(sm["Basket price change % (sales weighted)"]), "basket_months": float(sm["Basket change in months of CPI (0.6%/month)"]),
                 "fails": int(sm["Rule FAILs"]), "flagged": int(sm["SKUs with FLAGs"]), "rounding": float(sm["Rounding effect on GP $/yr"]),
                 "median_rise": float(chg[chg > 0].median()), "max_rise": float(chg.max()),
                 "revenue": float(pl.Revenue_USD.sum())}
    m["bridge"] = [{"item": str(i), "usd": float(v)} for i, v in zip(br.iloc[:, 0], br.iloc[:, 1])]
    m["waves"] = rec(xl("price_list.xlsx", "H5 waves").fillna({"Wave": "Hold"}))
    m["labels"] = rec(xl("price_list.xlsx", "H5 labels per store"))
    m["windows"] = rec(xl("price_list.xlsx", "H6 impact windows"))
    m["by_group"] = rec(xl("optimisation.xlsx", "By MainGroup").sort_values("GP_gain_52w", ascending=False))
    m["frontier"] = rec(xl("optimisation.xlsx", "G3 frontier"))
    m["scenarios"] = rec(xl("optimisation.xlsx", "G4 scenarios"))
    m["timing"] = rec(xl("optimisation.xlsx", "G5 timing"))
    m["limits"] = rec(xl("optimisation.xlsx", "G6 limits waterfall"))
    m["holds"] = rec(xl("optimisation.xlsx", "Hold reasons"))
    m["store_size"] = rec(xl("price_list.xlsx", "H7 holdout size"))
    m["store_list"] = rec(xl("price_list.xlsx", "H7 holdout stores"))
    m["store_power"] = rec(xl("price_list.xlsx", "H7 holdout power"))
    m["rollback"] = rec(xl("price_list.xlsx", "H8 rollback rules"))
    rc = xl("price_list.xlsx", "H3 rule counts").rename(columns={"Unnamed: 0": "Rule"})
    m["rules"] = rec(rc[~rc.Rule.str.startswith("R4/")])
    so = xl("stockouts.xlsx", "Summary")
    m["stockouts"] = dict(zip(["selling_weeks", "gap_weeks", "gap_pct", "edge_weeks", "edge_pct", "lost_units_pct", "lost_sales_m",
                               "lost_sales_pct", "lost_gp_m", "lost_gp_pct", "scope_sales_m", "skus"], so.iloc[:, 1].astype(float).tolist()))
    m["stock_groups"] = rec(xl("stockouts.xlsx", "By MainGroup").head(10))
    m["stock_skus"] = rec(xl("stockouts.xlsx", "By SKU", dtype={"Code": str}).head(40))
    m["checks"] = rec(xl("checks.xlsx", 0))
    h = xl("elasticity.xlsx", "D7b hold-out slope test").rename(columns={"Unnamed: 0": "Method"})
    esm = xl("elasticity.xlsx", "Summary").set_index("Item").Value
    chosen = f"{esm['Pooling chosen (D3/D7b)']}, spread calibrated (cross-fitted)"
    h = h[~h.Method.str.startswith("Phase 1")]
    m["holdout"] = rec(h.assign(Chosen=h.Method.eq(chosen)))
    e = xl("event_check.xlsx", "Summary")
    m["events"] = rec(e[e.Control == "clean"])
    m["bands"] = rec(xl("elasticity.xlsx", "Bands"))
    m["conf"] = rec(xl("elasticity.xlsx", "Confidence").rename(columns={"Unnamed: 0": "Confidence"}) if "Unnamed: 0" in xl("elasticity.xlsx", "Confidence").columns else xl("elasticity.xlsx", "Confidence"))
    m["forecast"] = rec(xl("baseline.xlsx", "E3-E4 benchmark").head(8))
    m["forecast_summary"] = rec(xl("baseline.xlsx", "Summary"))
    bp = xl("performance_baseline.xlsx", "Before picture")
    m["before"] = rec(bp.rename(columns={"KPI (before picture)": "KPI"}).astype({"Value": str}))
    m["by_quarter"] = rec(xl("performance_baseline.xlsx", "By quarter").rename(columns={"Unnamed: 0": "Quarter"}))
    steps = [("Start", A / "_before_stockout"), ("Stock-outs fixed", A / "_before_step2"), ("Price effects re-checked", A / "_before_step3"),
             ("Limits + checks (now)", A)]
    m["steps"] = []
    for name, folder in steps:
        b = pd.read_excel(folder / "price_list.xlsx", sheet_name="Profit bridge").iloc[:, 1].tolist()
        s2 = pd.read_excel(folder / "price_list.xlsx", sheet_name="Summary").set_index("Item").Value
        m["steps"].append({"stage": name, "gain": b[8], "cautious": b[9], "rises": int(s2["Raise"]),
                           "basket": float(s2["Basket price change % (sales weighted)"])})
    return m


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wk, wk_sku = weekly()
    hw, hist = history()
    hdir = OUT / "history"
    hdir.mkdir(exist_ok=True)
    groups = {}
    for i, (grp, d) in enumerate(sorted(hist.items())):
        f = f"g{i:02d}.json"
        (hdir / f).write_text(json.dumps({"weeks": hw, "skus": d}, separators=(",", ":")), encoding="utf-8")
        groups[grp] = f
    print(f"history          {len(groups)} group files, {sum(len(d) for d in hist.values())} SKUs")
    m = meta()
    m["history_files"] = groups
    for name, obj in [("meta", m), ("skus", skus()), ("weekly", wk), ("weekly_sku", wk_sku), ("flags", flags())]:
        p = OUT / f"{name}.json"
        p.write_text(json.dumps(obj, separators=(",", ":"), default=str), encoding="utf-8")
        print(f"{p.name:16s} {p.stat().st_size / 1024:8.0f} KB")


if __name__ == "__main__":
    main()
