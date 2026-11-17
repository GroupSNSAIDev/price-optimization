"""All-SKU project, new step: do lasting price changes move sales as much as the model says? (re-check of D7)

Events: lasting chain price steps (3-30%, no other step of the same SKU within 9 weeks, no markdown / spike weeks in
the windows), Jan 2024 - Oct 2026. Response = change in units per selling store, 8 weeks after (skipping the week of
the step and the next) vs 8 weeks before, minus the same change for a control:
  clean     the SubGroup's other SKUs whose price did NOT step within 9 weeks either side (dropped if they make
            < 20% of the SubGroup's units before the step)
  all       all other SKUs of the SubGroup (the D7 back-test control, for comparison)
Step = change in the average selling price, same windows.
Per event the model predicts response = model elasticity x step (Rise for rises, Cut for cuts, plus the uncalibrated
and chain-wide candidates). Scored with volume weights (sqrt of the pre-period units, capped):
  event elasticity  weighted slope of response on step (what lasting changes really did, on average)
  calibration       weighted slope of response on the model's prediction (1 = right size)
  by band           the same per model sensitivity band, rises and cuts apart, 4-week windows as a check
SE: bootstrap over SKUs (200 draws).

The model is not changed here; the result says whether the likely case should be scaled.

Inputs: clean/allsku/chain_weekly.parquet, clean/allsku/elasticity.parquet, clean/allsku/scope.parquet
Output: analysis/allsku/event_check.xlsx
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
SEED, WIN, GAP, QUIET = 2026, 8, 2, 9
MIN_STEP, MAX_STEP, MIN_CTRL_SHARE = 0.03, 0.30, 0.20


def load():
    c = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Units", "Stores_Selling", "Price_KZ", "Price_Step",
                                                               "Price_Step_Pct", "Markdown_Week", "Spike_Week"])
    sc = pd.read_parquet(CL / "scope.parquet", columns=["Code", "SubGroup"]).set_index("Code")
    c["SubGroup"] = c.Code.map(sc.SubGroup)
    c = c[c.SubGroup.notna()]
    weeks = pd.date_range(c.Week.min(), c.Week.max(), freq="7D")
    codes = sorted(c.Code.unique())
    piv = lambda col, fill: c.pivot(index="Week", columns="Code", values=col).reindex(index=weeks, columns=codes).fillna(fill)
    U, S, P = piv("Units", 0.0), piv("Stores_Selling", 0.0), piv("Price_KZ", np.nan)
    flag = lambda col: piv(col, False).fillna(False).astype(bool)
    step = flag("Price_Step") & (piv("Price_Step_Pct", 0.0).abs() <= 100)        # > 100% = pack / unit change
    bad = flag("Markdown_Week") | flag("Spike_Week")
    return c, U, S, P, step, bad, sc


def events(c, U, S, P, step, bad, sc, win=WIN):
    T = len(U)
    busy = step.astype(int).rolling(2 * QUIET + 1, center=True, min_periods=1).max().astype(bool)   # step within +-9 weeks
    sub = sc.SubGroup.reindex(U.columns)
    rows = []
    for sg, cols in sub.groupby(sub).groups.items():
        cols = list(cols)
        u, s, p, st, bz, bd = (x[cols].to_numpy() for x in (U, S, P, step, busy, bad))
        for j, code in enumerate(cols):
            for t in np.where(st[:, j])[0]:
                a0, a1, b0, b1 = t - win, t, t + GAP, t + GAP + win
                if a0 < 0 or b1 > T:
                    continue
                own_steps = st[a0:b1, j].sum()
                if own_steps != 1 or bd[a0:b1, j].any():
                    continue
                up_, sp_, uq, sq = u[a0:a1, j].sum(), s[a0:a1, j].sum(), u[b0:b1, j].sum(), s[b0:b1, j].sum()
                if min(up_, sp_, uq, sq) <= 0:
                    continue
                pp, pq = np.nanmean(p[a0:a1, j]), np.nanmean(p[b0:b1, j])
                if not (pp > 0 and pq > 0):
                    continue
                stp = np.log(pq / pp)
                if not (MIN_STEP <= abs(stp) <= MAX_STEP):
                    continue
                own = np.log((uq / sq) / (up_ / sp_))
                others = np.arange(len(cols)) != j
                res = {"Code": code, "Week": U.index[t], "SubGroup": sg, "Step_ln": stp, "Pre_units": up_}
                for name, m in [("all", others), ("clean", others & ~bz[t, :])]:
                    cu_p, cu_q = u[a0:a1, m].sum(), u[b0:b1, m].sum()
                    share = cu_p / max(u[a0:a1, others].sum(), 1e-9)
                    ok = cu_p > 0 and cu_q > 0 and (name == "all" or share >= MIN_CTRL_SHARE)
                    res[f"Resp_{name}"] = own - np.log(cu_q / cu_p) if ok else np.nan
                    res[f"Ctrl_share_{name}"] = share
                rows.append(res)
    return pd.DataFrame(rows)


def wls(x, y, w):
    X = np.column_stack([np.ones(len(x)), x])
    return np.linalg.solve(X.T @ (X * w[:, None]), X.T @ (w * y))[1]


def fit(ev, resp, pred=None, boot=200):
    """event elasticity (slope of response on step) or calibration (slope on predicted), with SKU-bootstrap SE"""
    e = ev[ev[resp].notna() & (ev[pred].notna() if pred else True)]
    if len(e) < 30:
        return {"Events": len(e), "Slope": np.nan, "SE": np.nan, "SKUs": e.Code.nunique()}
    w = np.sqrt(e.Pre_units.clip(upper=e.Pre_units.quantile(0.95))).to_numpy()
    x = (e[pred] if pred else e.Step_ln).to_numpy()
    y = e[resp].clip(-1.5, 1.5).to_numpy()                       # a few broken weeks should not drive the slope
    b = wls(x, y, w)
    rng = np.random.default_rng(SEED)
    codes = e.Code.unique()
    groups = e.groupby("Code").indices
    bs = []
    for _ in range(boot):
        idx = np.concatenate([groups[k] for k in rng.choice(codes, len(codes))])
        bs.append(wls(x[idx], y[idx], w[idx]))
    return {"Events": len(e), "SKUs": len(codes), "Slope": b, "SE": float(np.std(bs))}


def main():
    c, U, S, P, step, bad, sc = load()
    el = pd.read_parquet(CL / "elasticity.parquet").set_index("Code")
    out = {}
    for win in (WIN, 4):
        ev = events(c, U, S, P, step, bad, sc, win)
        up = ev.Step_ln > 0
        ev["Dir"] = np.where(up, "Rise", "Cut")
        ev["Model_e"] = np.where(up, ev.Code.map(el.Rise), ev.Code.map(el.Cut))
        ev["Pred_model"] = ev.Model_e * ev.Step_ln
        ev["Pred_uncalibrated"] = ev.Code.map(el.Pooled_Uncalibrated).clip(-4, -0.2) * ev.Step_ln
        ev["Pred_chainwide"] = ev.Code.map(el["Cand_One_chain-wide_number_reference"]) * ev.Step_ln
        ev["Band"] = pd.cut(ev.Model_e, [-10, -2, -1, -0.5, 0], labels=["Highly elastic", "Elastic", "Moderate", "Inelastic"])
        out[win] = ev
    ev = out[WIN]

    rows = []
    for ctrl in ("clean", "all"):
        for win, e in out.items():
            for d in ("All", "Rise", "Cut"):
                x = e if d == "All" else e[e.Dir == d]
                el_ = fit(x, f"Resp_{ctrl}")
                cal = fit(x, f"Resp_{ctrl}", "Pred_model")
                rows.append({"Control": ctrl, "Window_weeks": win, "Direction": d, "Events": el_["Events"], "SKUs": el_["SKUs"],
                             "Event_elasticity": el_["Slope"], "Event_elasticity_SE": el_["SE"],
                             "Model_avg_elasticity": float(np.average(x.Model_e.dropna(), weights=np.sqrt(x.loc[x.Model_e.notna(), "Pre_units"]))) if x.Model_e.notna().any() else np.nan,
                             "Calibration_slope": cal["Slope"], "Calibration_SE": cal["SE"]})
    summary = pd.DataFrame(rows)

    cands = []
    for name, col in [("Model used (Rise / Cut, calibrated)", "Pred_model"), ("Before spread calibration", "Pred_uncalibrated"),
                      ("One chain-wide number", "Pred_chainwide")]:
        r = fit(ev, "Resp_clean", col)
        cands.append({"Model": name, **r})
    cands = pd.DataFrame(cands)

    bands = []
    for (b, d), x in ev.groupby(["Band", "Dir"], observed=True):
        r = fit(x, "Resp_clean")
        bands.append({"Model band": b, "Direction": d, "Events": r["Events"], "Event_elasticity": r["Slope"], "SE": r["SE"],
                      "Model_median": x.Model_e.median()})
    bands = pd.DataFrame(bands)
    ev["Year"] = ev.Week.dt.year
    years = pd.DataFrame([{"Year": y, **fit(x, "Resp_clean")} for y, x in ev.groupby("Year")])
    share = pd.DataFrame({"Item": ["Lasting steps found (8-week windows)", "  with a clean control (>= 20% of SubGroup units unchanged)",
                                   "Median share of SubGroup units that also stepped within 9 weeks %"],
                          "Value": [len(ev), int(ev.Resp_clean.notna().sum()), float((1 - ev.Ctrl_share_clean).median() * 100)]})
    notes = pd.DataFrame({"Note": [
        "Event elasticity: weighted slope of the sales response on the price step; compare with Model_avg_elasticity.",
        "Calibration slope 1 = the model's predicted response is the right size; 0.5 = real responses are half the size.",
        "Clean control = SubGroup SKUs whose price did not step within 9 weeks; 'all' = every other SKU (the old D7 control).",
        "Responses clipped to +-1.5 log points; weights = sqrt of pre-period units (capped at the 95th percentile).",
        "Lasting steps chosen by Fresmart are not random (often cost-driven, with rivals moving), so this is a check, not proof."]})
    with pd.ExcelWriter(OUT / "event_check.xlsx") as xw:
        summary.round(3).to_excel(xw, sheet_name="Summary", index=False)
        cands.round(3).to_excel(xw, sheet_name="Model candidates", index=False)
        bands.round(3).to_excel(xw, sheet_name="By band", index=False)
        years.round(3).to_excel(xw, sheet_name="By year", index=False)
        share.round(1).to_excel(xw, sheet_name="Events", index=False)
        ev.round({c: 4 for c in ev.select_dtypes("number").columns}).to_excel(xw, sheet_name="Event rows", index=False)
        notes.to_excel(xw, sheet_name="Notes", index=False)
    pd.set_option("display.width", 220)
    print(share.round(1).to_string(index=False)); print(summary.round(3).to_string(index=False))
    print(cands.round(3).to_string(index=False)); print(bands.round(3).to_string(index=False)); print(years.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
