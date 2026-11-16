"""Step 11 wrap-up · is the ML forecast worth it, and how accurate is it across many periods?

For 7 forecast origins (the 6 rolling CV periods + Jul-Sep 2026), each forecasting the next 13 weeks from data before
the origin only, with the same honest rules (stock cover, discount, cost, margin and macro frozen at the origin):
  ML  LightGBM champion (relative-level target, recency weights), recursive, level-calibrated on the 8 weeks before
      the origin with a model trained before those 8 weeks (no look-ahead)
  B1  last-13-week average of the store-SKU's units
  B2  B1 x seasonal index (SKU chain monthly profile from history before the origin)
  B3  same week last year (3-week average) x trend (last 13 weeks vs the same 13 weeks a year earlier); B1 if missing
  Blends: 50% ML + 50% B1, and 30% ML + 70% B1
Metrics on identical rows: store-SKU-week WAPE / bias, chain SKU-month WAPE. Jul-Sep 2026 also split into weeks with
healthy vs low stock cover (< 7 days of cover, actual).
Outputs: analysis/pilot/forecast_benchmark.xlsx
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import pilot_train_eval as T
from pilot_models import PRICE_FEATS, metrics, prepare

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "pilot"
PERIODS = T.FOLDS + [("Q3 2026 (test)", "2026-06-29", "2026-09-28")]


def lgb_params():
    tune = pd.read_excel(OUT / "model_evaluation.xlsx", sheet_name="CV tuning (6 folds)")
    lg = tune[tune.Model == "LightGBM"].sort_values("CV_WAPE").iloc[0]
    return json.loads(lg.Params)


def ml_forecast(f, cols, mono, params, start, end):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    cal_start = s - pd.Timedelta(weeks=8)
    pre, cal = f[f.Week < cal_start], f[(f.Week >= cal_start) & (f.Week < s)]
    m_cal = T.fit("LightGBM", params, pre, cols, mono)
    raw = m_cal.units(cal) / m_cal.smear
    d = pd.DataFrame({"a": cal.ArticleCode.values, "y": np.exp(cal.ln_Units.values), "p": raw})
    G = d.y.sum() / d.p.sum()
    g = d.groupby("a").agg(y=("y", "sum"), p=("p", "sum"), n=("y", "size"))
    r = (G + (g.y / g.p - G) * g.n / (g.n + 50)).clip(0.75 * G, 1.25 * G)
    m = T.fit("LightGBM", params, f[f.Week < s], cols, mono)
    m.calib, m.calib_global = r.to_dict(), float(G)
    te = f[(f.Week >= s) & (f.Week < e)].reset_index(drop=True)
    return te, T.recursive(m, f[f.Week < s], te, calibrate=True, freeze=True)


def benchmarks(f, te, start):
    s = pd.Timestamp(start)
    hist = f[f.Week < s].copy()
    hist["U"] = np.exp(hist.ln_Units)
    key = ["Plant", "ArticleCode"]
    last13 = hist.sort_values("Week").groupby(key).tail(13).groupby(key).U.mean()
    b1 = pd.MultiIndex.from_arrays([te.Plant, te.ArticleCode]).map(last13).values.astype(float)
    # B2 seasonal index per SKU and calendar month (chain, history before the origin)
    hist["Mon"] = hist.Week.dt.month
    sku_mon = hist.groupby(["ArticleCode", "Mon"]).U.mean()
    sku_all = hist.groupby("ArticleCode").U.mean()
    idx = (sku_mon / sku_all.reindex(sku_mon.index.get_level_values(0)).values).clip(0.5, 2.0)
    recent = hist[hist.Week >= s - pd.Timedelta(weeks=13)]
    base_idx = recent.groupby("ArticleCode").Mon.agg(
        lambda m: np.mean([idx.get((m.name, x), 1.0) for x in m]))
    tgt = np.array([idx.get((a, mo), 1.0) for a, mo in zip(te.ArticleCode, te.Week.dt.month)])
    b2 = b1 * tgt / te.ArticleCode.map(base_idx).fillna(1.0).values
    # B3 same week last year x trend
    U = hist.set_index(key + ["Week"]).U
    ly = []
    for p, a, w in zip(te.Plant, te.ArticleCode, te.Week):
        v = [U.get((p, a, w - pd.Timedelta(weeks=52 + k)), np.nan) for k in (-1, 0, 1)]
        ly.append(np.nanmean(v) if not np.all(np.isnan(v)) else np.nan)
    ly = np.array(ly)
    prev = hist[(hist.Week >= s - pd.Timedelta(weeks=65)) & (hist.Week < s - pd.Timedelta(weeks=52))]
    trend = (recent.groupby(key).U.mean() / prev.groupby(key).U.mean()).clip(0.5, 2.0)
    tr = pd.MultiIndex.from_arrays([te.Plant, te.ArticleCode]).map(trend).values.astype(float)
    b3 = np.where(np.isnan(ly) | np.isnan(tr), b1, ly * tr)
    return {"B1 last-13-week avg": b1, "B2 13-week avg x season": b2, "B3 last year x trend": b3}


def main():
    f, _ = prepare()
    dec = json.load(open(OUT / "pca_decision.json"))
    lin_raw = [("ln_Days_Of_Cover_Filled" if c == "ln_Days_Of_Cover" else c) for c in dec["linear_features"]]
    f[lin_raw] = f[lin_raw].fillna(f[f.Split == "train"][lin_raw].median())
    f = T.add_relative(f)
    cols = T.swap_features(dec["tree_features"])
    mono = [-1 if c in PRICE_FEATS else 0 for c in cols]
    params = lgb_params()
    rows, stock_rows = [], []
    for name, s, e in PERIODS:
        te, p_ml = ml_forecast(f, cols, mono, params, s, e)
        preds = {"ML LightGBM": p_ml, **benchmarks(f, te, s)}
        b1 = preds["B1 last-13-week avg"]
        preds["Blend 50% ML + 50% B1"] = 0.5 * p_ml + 0.5 * b1
        preds["Blend 30% ML + 70% B1"] = 0.3 * p_ml + 0.7 * b1
        y = np.exp(te.ln_Units).values
        ok = np.all([~np.isnan(v) for v in preds.values()], axis=0) & (y > 0)
        mon = te.Week.dt.to_period("M")
        for meth, p in preds.items():
            m = metrics(y[ok], p[ok])
            cm = pd.DataFrame({"a": te.ArticleCode[ok], "m": mon[ok], "y": y[ok], "p": p[ok]}).groupby(["a", "m"]).sum()
            rows.append({"Period": name, "Method": meth, "Rows": int(ok.sum()), "WAPE_store_week_%": m["WAPE_%"],
                         "Bias_%": m["Bias_%"], "WAPE_chain_SKU_month_%": np.abs(cm.p - cm.y).sum() / cm.y.sum() * 100})
            if name.startswith("Q3 2026"):
                cover = np.expm1(te.ln_Days_Of_Cover.values)
                for lab, mask in [("Healthy stock (>= 7 days cover)", cover >= 7), ("Low stock (< 7 days cover)", cover < 7),
                                  ("No stock data", np.isnan(cover))]:
                    mk = ok & mask
                    if mk.sum() > 50:
                        mm = metrics(y[mk], p[mk])
                        stock_rows.append({"Method": meth, "Stock": lab, "Rows": int(mk.sum()),
                                           "WAPE_%": mm["WAPE_%"], "Bias_%": mm["Bias_%"]})
        print(f"{name}: " + "  ".join(f"{r['Method'].split()[0]} {r['WAPE_store_week_%']:.1f}/{r['Bias_%']:+.1f}"
                                      for r in rows[-6:]), flush=True)
    res = pd.DataFrame(rows)
    summ = res.groupby("Method").agg(Periods=("Period", "size"), WAPE_mean=("WAPE_store_week_%", "mean"),
                                     WAPE_sd=("WAPE_store_week_%", "std"),
                                     WAPE_chain_month_mean=("WAPE_chain_SKU_month_%", "mean"),
                                     Abs_Bias_mean=("Bias_%", lambda b: b.abs().mean()),
                                     Wins=("WAPE_store_week_%", lambda w: 0))
    best = res.loc[res.groupby("Period")["WAPE_store_week_%"].idxmin()].Method.value_counts()
    summ["Periods_Best"] = best.reindex(summ.index).fillna(0).astype(int)
    summ = summ.drop(columns="Wins").sort_values("WAPE_mean")
    ml = summ.loc["ML LightGBM"]
    summ["ML_Gain_vs_Method_pt"] = summ.WAPE_mean - ml.WAPE_mean
    stock = pd.DataFrame(stock_rows)
    print(summ.round(2).to_string(), flush=True)
    print(stock.round(2).to_string(index=False), flush=True)
    with pd.ExcelWriter(OUT / "forecast_benchmark.xlsx") as xw:
        summ.reset_index().round(2).to_excel(xw, sheet_name="Summary (7 periods)", index=False)
        res.pivot(index="Period", columns="Method", values="WAPE_store_week_%").round(2).to_excel(
            xw, sheet_name="WAPE by period")
        res.pivot(index="Period", columns="Method", values="Bias_%").round(2).to_excel(xw, sheet_name="Bias by period")
        res.pivot(index="Period", columns="Method", values="WAPE_chain_SKU_month_%").round(2).to_excel(
            xw, sheet_name="Chain SKU-month WAPE")
        stock.round(2).to_excel(xw, sheet_name="Q3 2026 by stock", index=False)
        res.round(3).to_excel(xw, sheet_name="All results", index=False)


if __name__ == "__main__":
    main()
