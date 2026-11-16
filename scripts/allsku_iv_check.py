"""All-SKU project: independent check of the price effects (endogeneity test, step D10).

Prices are partly set in response to demand, which can bias the per-SKU elasticities. Here price changes are
"instrumented" with changes in unit cost (and FX for imported articles), which move price for supply reasons, not demand.

Data: chain weekly, in-scope SKUs, 4-week log differences (units, real price), week fixed effects (demeaned by week),
markdown and spike weeks out. Instruments: real unit-cost change lagged 1 week (t-1 vs t-5); FX change x imported.
Per group (behaviour cluster, elasticity band, all): OLS slope, IV (2SLS) slope with SE clustered by SKU, first-stage F,
and the sales-weighted elasticity the optimiser uses for the same SKUs.

Inputs: clean/allsku/chain_weekly.parquet, clean/allsku/elasticity.parquet, checkpoints/macro_monthly.parquet, dim_article_master
Validity test (exclusion): in rows where the price did NOT change, the cost instrument must not predict units.
If it does, cost is linked to demand (unit cost = COGS / units moves with receipts and sales) and the IV is invalid.

Output: analysis/allsku/iv_check.xlsx
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
LAG = 4


def band(e):
    return pd.cut(e, [-99, -2, -1, -0.5, 0], labels=["Highly elastic", "Elastic", "Moderate", "Inelastic"]).astype(str)


def load():
    el = pd.read_parquet(CL / "elasticity.parquet").set_index("Code")
    el = el[el.in_scope]
    c = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Units", "Price_Real_KZ", "Unit_Cost_KZ", "CPI_Deflator",
                                                               "Markdown_Week", "Spike_Week"])
    c = c[c.Code.isin(el.index) & (c.Week >= "2024-01-01")].sort_values(["Code", "Week"]).reset_index(drop=True)
    mm = pd.read_parquet(ROOT / "checkpoints" / "macro_monthly.parquet")
    fx = mm.assign(Month=mm.Month.astype(str)).set_index("Month").FX_BNA_Avg.ffill()
    mon = (c.Week + pd.Timedelta(days=3)).dt.to_period("M").astype(str)
    c["lnFX"] = np.log(fx.reindex(mon.values).to_numpy())
    m = pd.read_parquet(ROOT / "checkpoints" / "dim_article_master.parquet", columns=["ArticalCode", "PurchaseType"])
    imp = m.assign(c=m.ArticalCode.astype(str).str.lstrip("0")).drop_duplicates("c").set_index("c").PurchaseType.eq("Import")
    c["Imported"] = c.Code.map(imp).fillna(False).astype(float)

    g = c.groupby("Code")
    lnq = np.log(c.Units.where(c.Units > 0))
    lnp = np.log(c.Price_Real_KZ)
    lnc = np.log((c.Unit_Cost_KZ / c.CPI_Deflator).where(c.Unit_Cost_KZ > 0)).groupby(c.Code).ffill()
    sh = lambda s, k: s.groupby(c.Code).shift(k)
    d = pd.DataFrame({"Code": c.Code, "Week": c.Week,
                      "dq": lnq - sh(lnq, LAG), "dp": lnp - sh(lnp, LAG),
                      "dz_cost": sh(lnc, 1) - sh(lnc, 1 + LAG),
                      "dz_fx": (sh(c.lnFX, 1) - sh(c.lnFX, 1 + LAG)) * c.Imported})
    bad = (c.Markdown_Week | c.Spike_Week).fillna(False)
    bad = bad | sh(bad.astype(float), LAG).fillna(1).astype(bool)
    d = d[~bad].replace([np.inf, -np.inf], np.nan).dropna()
    # trim extreme moves (data errors, pack changes)
    d = d[(d.dp.abs() < 0.4) & (d.dq.abs() < 2) & (d.dz_cost.abs() < 0.4)]
    for col in ["dq", "dp", "dz_cost", "dz_fx"]:          # week fixed effects
        d[col] = d[col] - d.groupby("Week")[col].transform("mean")
    d["Cluster"] = d.Code.map(el.Behaviour_Cluster)
    d["Band"] = d.Code.map(band(el.Elasticity))
    return d, el


def iv(d):
    """2SLS of dq on dp with instruments dz_cost, dz_fx; SE clustered by SKU"""
    Z = d[["dz_cost", "dz_fx"]].to_numpy()
    Z = Z[:, np.abs(Z).sum(axis=0) > 0]
    x, y, codes = d.dp.to_numpy(), d.dq.to_numpy(), d.Code.to_numpy()
    ols = float(x @ y / (x @ x))
    pi, *_ = np.linalg.lstsq(Z, x, rcond=None)
    xh = Z @ pi
    b = float(xh @ y / (xh @ x))
    u, e1 = y - b * x, x - xh
    s = pd.DataFrame({"c": codes, "a": xh * u, "f": Z[:, 0] * e1})
    sa = s.groupby("c")[["a", "f"]].sum()
    se = float(np.sqrt((sa.a ** 2).sum()) / abs(xh @ x))
    # first stage F on the cost instrument (cluster-robust t squared)
    zc = Z[:, 0]
    g1 = float(zc @ x / (zc @ zc))
    se1 = float(np.sqrt(((s.assign(v=zc * (x - g1 * zc)).groupby("c").v.sum()) ** 2).sum()) / (zc @ zc))
    return {"Rows": len(d), "SKUs": d.Code.nunique(), "OLS_slope": ols, "IV_slope": b, "IV_SE": se,
            "IV_95_low": b - 1.96 * se, "IV_95_high": b + 1.96 * se, "First_stage_F_cost": (g1 / se1) ** 2,
            "Cost_passthrough_4w": g1}


def model_view(el, codes):
    e = el.loc[el.index.isin(codes) & el.Elasticity.notna()]
    w = e.Revenue_USD.fillna(0).clip(lower=0) + 1e-9
    return {"Model_elasticity_wtd": float(np.average(e.Elasticity, weights=w)), "Model_rise_wtd": float(np.average(e.Rise, weights=w))}


def main():
    d, el = load()
    rows = [{"Group": "All in-scope SKUs", **iv(d), **model_view(el, d.Code.unique())}]
    for col in ["Band", "Cluster"]:
        for k, g in d.groupby(col):
            if g.Code.nunique() < 20:
                continue
            rows.append({"Group": f"{col}: {k}", **iv(g), **model_view(el, g.Code.unique())})
    r = pd.DataFrame(rows)
    q = d[d.dp.abs() < 0.005]
    k = float(q.dz_cost @ q.dq / (q.dz_cost @ q.dz_cost))
    res = q.dq - k * q.dz_cost
    se_k = float(np.sqrt(((q.dz_cost * res).groupby(q.Code).sum() ** 2).sum()) / (q.dz_cost @ q.dz_cost))
    valid = abs(k / se_k) < 1.96
    excl = pd.DataFrame([{"Test": "Cost change -> units, in rows with no price change (should be 0)", "Rows": len(q),
                          "Slope": k, "SE": se_k, "t": k / se_k, "Passed": valid}])
    r["Verdict"] = np.where(not valid, "Invalid: cost moves with demand", np.where(r.First_stage_F_cost < 10, "Weak instrument: no conclusion",
                   np.where((r.Model_elasticity_wtd >= r.IV_95_low) & (r.Model_elasticity_wtd <= r.IV_95_high),
                            "Model inside IV range: consistent",
                            np.where(r.Model_elasticity_wtd < r.IV_95_low, "Model stronger than IV", "Model weaker than IV"))))
    notes = pd.DataFrame({"Note": [
        "IV = price change explained only by cost / FX changes (supply side), so demand-driven pricing cannot bias it.",
        "OLS = plain slope on the same data, for comparison (biased toward zero if prices follow demand).",
        "First-stage F < 10 = cost moves too little of the price to give a reliable answer.",
        "Model = sales-weighted elasticity the optimiser uses for the same SKUs.",
        "Result: the validity test fails, so this IV check cannot be trusted with the current cost data. A clean test needs "
        "supplier invoice prices (purchase price per unit by date), which do not depend on store sales.",
        f"4-week log differences, week fixed effects, markdown and spike weeks out, data from Jan 2024; SE clustered by SKU."]})
    with pd.ExcelWriter(OUT / "iv_check.xlsx") as xw:
        r.round(3).to_excel(xw, sheet_name="IV check", index=False)
        excl.round(3).to_excel(xw, sheet_name="Validity test", index=False)
        notes.to_excel(xw, sheet_name="Notes", index=False)
    pd.set_option("display.width", 250)
    print(excl.round(3).to_string(index=False))
    print(r[["Group", "SKUs", "OLS_slope", "IV_slope", "IV_95_low", "IV_95_high", "First_stage_F_cost", "Model_elasticity_wtd", "Verdict"]]
          .round(2).to_string(index=False))


if __name__ == "__main__":
    main()
