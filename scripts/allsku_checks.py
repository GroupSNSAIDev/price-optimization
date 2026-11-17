"""All-SKU project: automated checks, run after the pipeline (and after any code change).

Part A, unit checks on small made-up data (the logic itself):
  A1 stock-outs: gap runs of 1-8 weeks kept, longer or still-open runs dropped
  A2 pooling: shrinkage lands between the SKU's own estimate and the group prior; equal inputs combine to themselves
  A3 hold-out slope score: a perfect prediction scores calibration 1 and error 0
  A4 optimiser: SubGroup rise limit (60%, at least 1), no rise after a recent big rise even on the thin-tail rule,
     rise <= 8%, Low-confidence rise <= 5%, no change when not on shelf
  A5 demand model: no change -> today's units; a rise lowers own units
Part B, checks on the real outputs:
  B1 run order: stock-outs -> price effects -> optimiser -> price list (file times)
  B2 no SKU silently dropped: every SKU has a price effect, rise and cut
  B3 price effects inside the bounds; chosen pooling is not a reference row
  B4 stock-out filter really applied to the price-effect panel (--deep: reloads the panel, ~1-2 GB memory)
  B5 price list obeys the rules: 0 rule FAILs, rise <= 8%, Low confidence <= 5%, not on shelf unchanged, no rise after a
     recent big rise, no cut on supply risk, no cut below cost, basket <= 1.8%, <= 60% of a SubGroup raised
  B6 totals reconcile: profit bridge lines add up, waves add up to the plan, plan = sum over SKUs, waterfall end = plan
  B7 store prices: every changed SKU has store rows, store wave = SKU wave
  B8 store test: control and changed stores do not overlap, size = the chosen row, GP change detectable at 4 weeks
  B9 sanity (WARN only): event-check calibration 0.5-1.5, lost sales from stock-outs 0-20% of sales

Usage: python scripts/allsku_checks.py [--deep]
Output: analysis/allsku/checks.xlsx; exit code 1 if any check FAILs
"""
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
RESULTS = []


def check(cid, name, level="FAIL"):
    """decorator: run the check, record PASS / FAIL / WARN with a short detail"""
    def wrap(fn):
        try:
            ok, detail = fn()
            RESULTS.append((cid, name, "PASS" if ok else level, detail))
        except Exception as e:                                         # a crash is a failure, never a silent pass
            RESULTS.append((cid, name, "FAIL", f"error: {e!r}"))
            traceback.print_exc()
        return fn
    return wrap


# ---------------------------------------------------------------- part A: logic on made-up data
@check("A1", "Stock-outs: gap runs 1-8 weeks kept, longer / open-ended runs dropped")
def _():
    import allsku_stockouts as S
    g = np.zeros((30, 3), bool)
    g[5:8, 0] = True            # 3-week gap, closed -> kept
    g[5:15, 1] = True           # 10-week gap -> dropped (delisting)
    g[26:30, 2] = True          # open at the end -> dropped
    k = S.gap_runs(g)
    ok = k[5:8, 0].all() and not k[:, 1].any() and not k[:, 2].any() and k.sum() == 3
    return ok, f"kept {int(k.sum())} of {int(g.sum())} gap weeks (expected 3)"


@check("A2", "Pooling: shrunk value between own estimate and prior; equal inputs combine to themselves")
def _():
    import allsku_elasticity as E
    est, se, prior, tau = np.array([-2.0, -0.3]), np.array([0.5, 0.2]), np.array([-1.0, -1.0]), np.array([0.4, 0.4])
    e, _, w = E.eb(est, se, prior, tau)
    between = ((e - est) * (e - prior) <= 1e-12).all() and ((0 < w) & (w < 1)).all()
    m, s_, _ = E.dersimonian_laird([-1.2, -1.2, -1.2], [0.3, 0.3, 0.3])
    return between and abs(m + 1.2) < 1e-9, f"shrunk {np.round(e, 3)}, combined {m:.3f}"


@check("A3", "Hold-out slope score: perfect prediction -> calibration 1, error 0")
def _():
    import allsku_elasticity as E
    idx = [str(i) for i in range(50)]
    b = pd.Series(np.linspace(-3, -0.3, 50), index=idx)
    ho = pd.DataFrame({"Combined": b, "Combined_SE": 0.1})
    r = E.score_slopes(ho, b, pd.Series(1.0, index=idx))
    return abs(r["Calib_slope_hold"] - 1) < 1e-6 and r["Pred_error_RMSE"] < 1e-6, f"calib {r['Calib_slope_hold']:.3f}, error {r['Pred_error_RMSE']:.3f}"


def toy_sku(**kw):
    base = dict(in_scope=True, P=100.0, C=80.0, Base_52w=1000.0, Insight="Other", Range_Up=0.15, Range_Down=0.15,
                Confidence="High", Supply_Risk=False, Overstock=False, ABC="B", SubGroup="X", **{"Repriced_26w_%": 0.0,
                "Cost_chg_26w_%": 0.0, "Price_chg_26w_%": 0.0})
    base.update({k.replace("__", "%").replace("_pct", "_%"): v for k, v in kw.items()})
    return base


@check("A4", "Optimiser: rise limits, tail rule respects rise bans, not on shelf held")
def _():
    import allsku_optimise as O
    lim = [O.rise_limit(m) for m in (1, 2, 5, 10)]
    d = pd.DataFrame({
        "ok": toy_sku(),
        "low": toy_sku(Confidence="Low"),
        "tail_recent_rise": toy_sku(Confidence="Low", ABC="C", **{"Repriced_26w_%": 40.0, "Cost_chg_26w_%": 30.0}),
        "tail_cost_up": toy_sku(Confidence="Low", ABC="C", P=100.0, C=97.0, **{"Cost_chg_26w_%": 30.0}),
        "off_shelf": toy_sku(in_scope=False)}).T
    for c in ["P", "C", "Base_52w", "Range_Up", "Range_Down", "Repriced_26w_%", "Cost_chg_26w_%", "Price_chg_26w_%"]:
        d[c] = d[c].astype(float)
    al, _ = O.allowed_moves(d)
    checks = {
        "rise_limit 1/2/5/10 -> 1/1/3/6": lim == [1, 1, 3, 6],
        "max rise 8%": max(al["ok"]) <= O.MAX_RISE + 1e-9 and abs(O.MAX_RISE - 0.08) < 1e-9,
        "Low confidence rise <= 5%": max(al["low"]) <= 0.05 + 1e-9,
        "tail + recent big rise: no rise": max(al["tail_recent_rise"]) <= 0,
        "tail + cost up: catch-up rise allowed": max(al["tail_cost_up"]) > 0,
        "not on shelf: hold": al["off_shelf"] == [0.0]}
    bad = [k for k, v in checks.items() if not v]
    return not bad, "all ok" if not bad else "failed: " + "; ".join(bad)


@check("A5", "Demand model: no change keeps today's units, a rise lowers own units")
def _():
    import allsku_optimise as O
    g = pd.DataFrame({"Base_52w": [100.0, 200.0], "P": [10.0, 12.0], "C": [8.0, 9.0], "Rise": [-1.0, -1.5], "Cut": [-1.0, -1.2],
                      "Cautious": [-1.5, -2.0], "Elasticity": [-1.0, -1.4], "Diversion": [0.3, 0.3], "Revenue_USD": [1.0, 1.0]},
                     index=["a", "b"])
    G = O.Group(g)
    u0 = G.units(np.zeros(2))
    u1 = G.units(np.array([0.05, 0.0]))
    return np.allclose(u0, G.B) and u1[0] < G.B[0] and u1[1] > G.B[1], f"no change {np.round(u0, 1)}, a +5% {np.round(u1, 1)}"


# ---------------------------------------------------------------- part B: real outputs
def mtime(p):
    return p.stat().st_mtime


@check("B1", "Run order: stock-outs -> price effects -> optimiser -> price list")
def _():
    f = [CL / "stockout_weeks.parquet", CL / "elasticity.parquet", CL / "optimal_prices.parquet", CL / "price_list.parquet"]
    t = [mtime(x) for x in f]
    return all(a <= b for a, b in zip(t, t[1:])), " <= ".join(pd.Timestamp(x, unit="s").strftime("%d %b %H:%M") for x in t)


el = pd.read_parquet(CL / "elasticity.parquet")
pl = pd.read_parquet(CL / "price_list.parquet").set_index("Code")


@check("B2", "No SKU silently dropped: every SKU with model data has a price effect, rise and cut")
def _():
    nan = el[["Elasticity", "Rise", "Cut"]].isna().any(axis=1)
    in_panel = el.Rows.fillna(0) > 0
    no_data = el[nan & ~in_panel]
    return not (nan & in_panel).any(), (f"{int(in_panel.sum())} SKUs with data, {int((nan & in_panel).sum())} of them without a price "
                                        f"effect; {len(no_data)} SKUs have no model data ({int(no_data.in_scope.fillna(False).astype(bool).sum())} "
                                        "on shelf: held, see B2b)")


@check("B2b", "On-shelf SKUs with no model data are held (no price change without a price effect)")
def _():
    nan = el.set_index("Code")[["Elasticity", "Rise", "Cut"]].isna().any(axis=1)
    codes = nan.index[nan]
    moved = (pl.loc[pl.index.intersection(codes), "Final_Change_%"].fillna(0) != 0).sum()
    return moved == 0, f"{len(codes)} SKUs without a price effect, {int(moved)} of them changed"


@check("B3", "Price effects inside the bounds; chosen pooling is not a reference")
def _():
    import allsku_elasticity as E
    b = E.BOUNDS
    out = ((el.Elasticity < b["overall"][0] - 1e-9) | (el.Elasticity > b["overall"][1] + 1e-9) | (el.Rise < b["rise"][0] - 1e-9) |
           (el.Rise > b["rise"][1] + 1e-9) | (el.Cut < b["cut"][0] - 1e-9) | (el.Cut > b["cut"][1] + 1e-9)).sum()
    sm = pd.read_excel(OUT / "elasticity.xlsx", sheet_name="Summary").set_index("Item").Value
    choice = str(sm.get("Pooling chosen (D3/D7b)", ""))
    return out == 0 and "reference" not in choice and choice != "", f"{int(out)} out of bounds; chosen: {choice}; spread c: {sm.get('Spread calibration c (D7c)')}"


if "--deep" in sys.argv:
    @check("B4", "Stock-out filter applied: no mid-week stock-out rows in the price-effect panel")
    def _():
        import allsku_elasticity as E
        sc = pd.read_parquet(CL / "scope.parquet").set_index("Code")
        d = E.load(set(sc.index))[["Plant", "Code", "Week"]]
        so = pd.read_parquet(CL / "stockout_weeks.parquet", columns=["Plant", "Code", "Week", "Flag"])
        n = len(d.merge(so[so.Flag == "edge"], on=["Plant", "Code", "Week"]))
        return n == 0, f"panel {len(d):,} rows, {n} stock-out edge rows left in"
else:
    RESULTS.append(("B4", "Stock-out filter applied (needs --deep)", "SKIP", "run with --deep"))


@check("B5", "Price list obeys the rules")
def _():
    import allsku_optimise as O
    fr = pl["Final_Change_%"].fillna(0)
    valid = (pl.Base_52w > 0) & (pl.P > 0) & (pl.C > 0) & pl[["Rise", "Cut", "Elasticity"]].notna().all(axis=1)
    sub = pl[valid].assign(r=fr[valid] > 0).groupby("SubGroup").agg(n=("r", "size"), r=("r", "sum"))
    w = pl.Revenue_USD.fillna(0)
    basket = float((fr * w).sum() / w.sum())
    checks = {
        "0 rule FAILs": int(pl.Rule_FAILs.sum()) == 0,
        "rise <= 8% (+0.5 rounding, unless no ending fits)": ((fr <= 8.5) | ((fr > 8.5) & (pl.Rounding_Note.fillna("") == "no ending under the limit"))).all(),
        "Low confidence rise <= 5% (+0.5)": fr[pl.Confidence == "Low"].max() <= 5.5,
        "not on shelf: unchanged": (fr[~pl.in_scope.fillna(False).astype(bool)] == 0).all(),
        "no rise after a >= 15% rise in 26 weeks": not ((fr > 0) & (pl["Repriced_26w_%"] >= 15)).any(),
        "no cut on supply risk": not ((fr < 0) & pl.Supply_Risk.fillna(False).astype(bool)).any(),
        "no cut below cost": not ((fr < 0) & (pl.P * (1 + fr / 100) < pl.C)).any(),
        "basket <= 1.8%": basket <= 1.8,
        "<= 60% of a SubGroup raised": (sub.r <= sub.n.map(O.rise_limit)).all()}
    bad = [k for k, v in checks.items() if not v]
    return not bad, (f"all ok (basket {basket:.2f}%, max rise {fr.max():.1f}%)" if not bad else "failed: " + "; ".join(bad))


@check("B6", "Totals reconcile: bridge, waves, SKUs, waterfall")
def _():
    br = pd.read_excel(OUT / "price_list.xlsx", sheet_name="Profit bridge").set_index("Item")["GP_gain_52w_$"]
    def line(start):
        k = [i for i in br.index if str(i).startswith(start)]
        return float(br[k[0]])
    milp, trim, plan = line("MILP"), line("Trim"), line("Plan gain, likely")
    waves = sum(line(f"   of which {w}") for w in ["Wave 1", "Review then Wave 1", "Test", "Hold"])
    rnd, after = line("Shelf-price rounding"), line("Plan gain after rounding")
    sku_sum = float(pl["GP_gain_52w_$"].sum())
    wf = pd.read_excel(OUT / "optimisation.xlsx", sheet_name="G6 limits waterfall")["GP_gain_likely_$"].iloc[-1]
    checks = {"MILP + trim = plan": abs(milp + trim - plan) <= 2, "waves = plan": abs(waves - plan) <= 2,
              "plan + rounding = after rounding": abs(plan + rnd - after) <= 2, "plan = sum over SKUs": abs(plan - sku_sum) <= 2,
              "waterfall end = plan": abs(wf - plan) <= 2}
    bad = [k for k, v in checks.items() if not v]
    return not bad, (f"plan ${plan:,.0f}, after rounding ${after:,.0f}" if not bad else "failed: " + "; ".join(bad))


@check("B7", "Store prices: every changed SKU has store rows, store wave = SKU wave")
def _():
    st = pd.read_parquet(CL / "store_prices.parquet")
    chg = pl.index[pl["Final_Change_%"].fillna(0) != 0]
    missing = set(chg) - set(st.Code)
    wave_bad = (st.Wave != st.Code.map(pl.Wave)).sum()
    return not missing and wave_bad == 0, f"{len(chg)} changed SKUs, {len(missing)} without store rows, {int(wave_bad)} wave mismatches"


@check("B8", "Store test: groups do not overlap, size as chosen, GP detectable at 4 weeks")
def _():
    hs = pd.read_excel(OUT / "price_list.xlsx", sheet_name="H7 holdout stores")
    size = pd.read_excel(OUT / "price_list.xlsx", sheet_name="H7 holdout size")
    power = pd.read_excel(OUT / "price_list.xlsx", sheet_name="H7 holdout power")
    ctrl = set(hs.Store[hs.Role.str.startswith("Control")]); chg = set(hs.Store[hs.Role.str.startswith("Changed")])
    k = int(size.loc[size.Chosen, "Control_stores"].iloc[0])
    det = bool(power[(power.Metric == "GP") & (power.Weeks == 4)].Detectable.iloc[0])
    return not (ctrl & chg) and len(ctrl) == k and det, f"{len(ctrl)} control, {len(chg)} changed, chosen {k}, GP 4w detectable {det}"


@check("B9a", "Event check: model size match 0.5-1.5 (lasting price changes)", level="WARN")
def _():
    s = pd.read_excel(OUT / "event_check.xlsx", sheet_name="Summary")
    r = s[(s.Control == "clean") & (s.Window_weeks == 8) & (s.Direction == "All")].iloc[0]
    return 0.5 <= r.Calibration_slope <= 1.5, f"calibration {r.Calibration_slope:.2f} +- {r.Calibration_SE:.2f}"


@check("B9b", "Stock-outs: lost sales 0-20% of sales", level="WARN")
def _():
    s = pd.read_excel(OUT / "stockouts.xlsx", sheet_name="Summary")
    v = float(s[s.iloc[:, 0].str.contains("as % of sales", regex=False)].Value.iloc[0])
    return 0 < v < 20, f"lost sales {v:.1f}% of sales"


def main():
    r = pd.DataFrame(RESULTS, columns=["Check", "What", "Result", "Detail"])
    r.to_excel(OUT / "checks.xlsx", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 110)
    print(r.to_string(index=False))
    n = r.Result.value_counts()
    print(" | ".join(f"{k} {v}" for k, v in n.items()))
    sys.exit(1 if (r.Result == "FAIL").any() else 0)


if __name__ == "__main__":
    main()
