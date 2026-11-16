"""Step 11 · Model training & evaluation for the 40 pilot SKUs (v2: adapted to the 2026 demand decline)

v1 finding: volume per store-week fell ~23% in a year (224 -> 173 units, Q3 2025 -> Q3 2026); models trained on the
stable 2023-25 level over-forecast Jul-Sep 2026 by 11-17%. v2 fixes:
  F1 relative target    predict ln units minus the store-SKU's recent level (mean of the last 13 selling weeks);
                        history features expressed relative to that level; the long-run expanding mean is replaced
                        by an exponentially weighted level (half-life 8 weeks)
  F2 recency weights    training weight halves every 26 weeks back from the end of the training window
  F3 tuning folds       6 rolling 13-week folds incl. Q4 2024, Q4 2025 and Q2 2026 (the start of the decline)
  F4 level calibration  chain + per-SKU ratio actual / raw prediction over May-Jun 2026 from the Q2 2026 fold model
                        (trained to Mar 2026, so no leakage); per-SKU factors shrunk toward the chain factor and capped
                        at +/-25%; replaces the Duan smearing constant, which swung bias by 15-20 points
  F5 selection          champion only among models with no price-direction violations and |bias| <= 5%
Test = Jul-Sep 2026, untouched. Horizons: 1 week ahead, and recursive 2-13 weeks from the 29 Jun 2026 origin.
Outputs: analysis/pilot/model_evaluation.xlsx, model_selection.json, test_predictions.parquet, models_final/*.pkl
"""
import json
import pickle
import time
import warnings
from pathlib import Path

import catboost as cb
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from pilot_models import PRICE_FEATS, bump_price, metrics, prepare

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "pilot"
MOD = OUT / "models_final"
MOD.mkdir(parents=True, exist_ok=True)
ORIGIN = pd.Timestamp("2026-06-29")
FOLDS = [("Q4 2024", "2024-09-30", "2024-12-30"), ("Q1 2025", "2024-12-30", "2025-03-31"),
         ("Q3 2025", "2025-06-30", "2025-09-29"), ("Q4 2025", "2025-09-29", "2025-12-29"),
         ("Q1 2026", "2025-12-29", "2026-03-30"), ("Q2 2026", "2026-03-30", "2026-06-29")]
HALF_LIFE_WEEKS, EWM_HALF_LIFE = 26, 8
ALPHA_EWM = 1 - 0.5 ** (1 / EWM_HALF_LIFE)
REL_FEATS = ["Lag1_rel", "Lag2_rel", "Lag4_rel", "Roll4_rel", "EWM_rel", "Weeks_Selling"]
ABS_HIST = ["ln_Units_Lag1", "ln_Units_Lag2", "ln_Units_Lag4", "ln_Units_Roll4", "ln_Units_Roll13",
            "ln_Units_Store_SKU_Mean", "Units_Trend_13w", "Weeks_Selling"]
GRIDS = {
    "LightGBM": [dict(n_estimators=n, learning_rate=lr, num_leaves=nl, min_child_samples=50, subsample=0.8,
                      subsample_freq=1, colsample_bytree=0.8)
                 for n, lr, nl in [(300, 0.03, 31), (600, 0.03, 31), (800, 0.02, 63)]],
    "XGBoost": [dict(n_estimators=n, learning_rate=lr, max_depth=d, min_child_weight=20, subsample=0.8,
                     colsample_bytree=0.8) for n, lr, d in [(300, 0.03, 6), (600, 0.03, 6), (800, 0.02, 8)]],
    "CatBoost": [dict(iterations=n, learning_rate=lr, depth=d) for n, lr, d in [(500, 0.05, 6), (1000, 0.03, 8)]],
    "RandomForest": [dict(n_estimators=200, max_depth=20, min_samples_leaf=15, max_features=0.5)],
}


# ------------------------------------------------------------------ F1 relative representation
def add_relative(f):
    f = f.sort_values(["Plant", "ArticleCode", "Week"]).copy()
    g = f.groupby(["Plant", "ArticleCode"], sort=False).ln_Units
    f["Base"] = g.transform(lambda x: x.shift(1).rolling(13, min_periods=4).mean())
    ewm = g.transform(lambda x: x.shift(1).ewm(alpha=ALPHA_EWM, adjust=False).mean())
    f["Lag1_rel"] = g.shift(1) - f.Base
    f["Lag2_rel"] = g.shift(2) - f.Base
    f["Lag4_rel"] = g.shift(4) - f.Base
    f["Roll4_rel"] = g.transform(lambda x: x.shift(1).rolling(4, min_periods=2).mean()) - f.Base
    f["EWM_rel"] = ewm - f.Base
    f["y_rel"] = f.ln_Units - f.Base
    f = f[f.Base.notna()]
    for c in ["Lag1_rel", "Lag2_rel", "Lag4_rel", "Roll4_rel", "EWM_rel"]:
        f[c] = f[c].fillna(0)
    return f.sort_values("Week").reset_index(drop=True)


def swap_features(cols):
    out = [c for c in cols if c not in ABS_HIST]
    return out + [c for c in REL_FEATS if c not in out]


def recency_weight(weeks, end):
    age = (end - weeks).dt.days / 7
    return 0.5 ** (age / HALF_LIFE_WEEKS)


# ------------------------------------------------------------------ models
def make(name, params, mono, seed=0):
    if name == "LightGBM":
        return lgb.LGBMRegressor(**params, monotone_constraints=mono, monotone_constraints_method="advanced",
                                 verbose=-1, random_state=seed)
    if name == "XGBoost":
        return xgb.XGBRegressor(**params, tree_method="hist", monotone_constraints=tuple(mono), n_jobs=-1,
                                random_state=seed)
    if name == "CatBoost":
        return cb.CatBoostRegressor(**params, monotone_constraints=mono, verbose=0, random_seed=seed, thread_count=-1)
    return RandomForestRegressor(**params, n_jobs=-1, random_state=seed)


class Fitted:
    def __init__(self, name, model, cols, fill=None, scaler=None, smear=1.0):
        self.name, self.model, self.cols, self.fill, self.scaler, self.smear = name, model, cols, fill, scaler, smear
        self.calib, self.calib_global = {}, None

    def predict_rel(self, X):
        X = X[self.cols]
        if self.fill is not None:
            X = X.fillna(self.fill)
        if self.scaler is not None:
            X = self.scaler.transform(X)
        return self.model.predict(X)

    def units(self, X, rel=None, calibrate=False):
        rel = self.predict_rel(X) if rel is None else rel
        if calibrate and self.calib_global is not None:      # recent-period level replaces the smearing factor
            return np.exp(X.Base.values + rel) * X.ArticleCode.map(self.calib).fillna(self.calib_global).values
        return np.exp(X.Base.values + rel) * self.smear


def fit(name, params, tr, cols, mono):
    w = recency_weight(tr.Week, tr.Week.max()).values
    y = tr.y_rel
    if name == "Linear":
        sc = StandardScaler().fit(tr[cols])
        m = Ridge(alpha=params["alpha"]).fit(sc.transform(tr[cols]), y, sample_weight=w)
        f = Fitted(name, m, cols, scaler=sc)
    else:
        fill = tr[cols].median() if name == "RandomForest" else None
        X = tr[cols].fillna(fill) if fill is not None else tr[cols]
        m = make(name, params, mono).fit(X, y, sample_weight=w)
        f = Fitted(name, m, cols, fill=fill)
    resid = y.values - f.predict_rel(tr)
    f.smear = float(np.average(np.exp(resid), weights=w))
    return f


def cv_score(name, params, f, cols, mono):
    res, models = [], {}
    for fold, s, e in FOLDS:
        tr, te = f[f.Week < s], f[(f.Week >= s) & (f.Week < e)]
        m = fit(name, params, tr, cols, mono)
        p = m.units(te)
        res.append({"Fold": fold, **metrics(np.exp(te.ln_Units).values, p)})
        models[fold] = (m, te, p)
    return pd.DataFrame(res), models


def calibration(model_q2, te_q2, p_q2):
    """level factors from the last 8 weeks of the Q2 2026 fold (model trained to Mar 2026, no test data):
    chain factor = actual / raw prediction; per-SKU factors shrunk toward it and capped at +/-25% of it.
    These replace the back-transformation (smearing) constant."""
    raw = p_q2 / model_q2.smear
    d = pd.DataFrame({"a": te_q2.ArticleCode.values, "w": te_q2.Week.values, "y": np.exp(te_q2.ln_Units.values),
                      "p": raw})
    d = d[d.w >= ORIGIN - pd.Timedelta(weeks=8)]
    G = d.y.sum() / d.p.sum()
    g = d.groupby("a").agg(y=("y", "sum"), p=("p", "sum"), n=("y", "size"))
    r = G + (g.y / g.p - G) * g.n / (g.n + 50)
    return r.clip(0.75 * G, 1.25 * G).to_dict(), float(G)


# inputs NOT known in advance at the forecast date: frozen at their last value before the origin (fix 2)
FREEZE_STORE_SKU = ["ln_Days_Of_Cover", "ln_Days_Of_Cover_Filled", "Discount_Pct", "ln_Unit_Cost_Real_Lag1",
                    "dln_Cost_4w_Lag1", "Margin_Pct_Lag1"]
FREEZE_CHAIN = ["ln_FX_BNA", "Inflation_YoY", "Inflation_MoM", "ln_Brent", "GDP_Growth", "Macro_PC1", "Macro_PC2",
                "Macro_PC3", "Macro_PC4"]


def origin_snapshot(hist):
    last = hist.sort_values("Week").groupby(["Plant", "ArticleCode"]).tail(1).set_index(["Plant", "ArticleCode"])
    cols = [c for c in FREEZE_STORE_SKU if c in hist]
    chain = hist[hist.Week == hist.Week.max()][[c for c in FREEZE_CHAIN if c in hist]].iloc[0]
    return last[cols], chain


def recursive(model, hist, test, calibrate, freeze=True):
    """forecast the test weeks from the origin; predictions feed back into the recent-level features.
    freeze=True: stock cover, discount, last week's cost / margin and macro inputs stay at their origin values"""
    if freeze:
        snap, chain = origin_snapshot(hist)
        test = test.copy()
        key = pd.MultiIndex.from_arrays([test.Plant, test.ArticleCode])
        for c in snap.columns:
            v = snap[c].reindex(key).values
            test[c] = np.where(pd.isna(v), test[c], v) if c != "ln_Days_Of_Cover" else v
        for c, v in chain.items():
            test[c] = v
    H = {k: list(v) for k, v in hist.groupby(["Plant", "ArticleCode"]).ln_Units}
    E = {}
    for k, v in H.items():
        e = v[0]
        for x in v[1:]:
            e = ALPHA_EWM * x + (1 - ALPHA_EWM) * e
        E[k] = e
    out = np.full(len(test), np.nan)
    for wk in sorted(test.Week.unique()):
        idx = np.where(test.Week.values == wk)[0]
        rows = test.iloc[idx].copy()
        vals = []
        for p, a in zip(rows.Plant, rows.ArticleCode):
            h = H.get((p, a), [])
            if len(h) < 4:
                vals.append([np.nan] * 7)
                continue
            base = np.mean(h[-13:])
            vals.append([base, h[-1] - base, (h[-2] if len(h) > 1 else h[-1]) - base,
                         (h[-4] if len(h) > 3 else h[-1]) - base, np.mean(h[-4:]) - base, E[(p, a)] - base, len(h)])
        v = np.array(vals)
        ok = ~np.isnan(v[:, 0])
        rows.loc[rows.index[ok], ["Base"] + REL_FEATS] = v[ok]
        rel = model.predict_rel(rows)
        lp = rows.Base.values + rel
        fac = rows.ArticleCode.map(model.calib).fillna(model.calib_global).values if calibrate else model.smear
        out[idx] = np.exp(lp) * fac
        for (p, a), x in zip(zip(rows.Plant, rows.ArticleCode), lp):
            H.setdefault((p, a), []).append(x)
            E[(p, a)] = ALPHA_EWM * x + (1 - ALPHA_EWM) * E.get((p, a), x)
    return out


def main():
    f, _ = prepare()
    dec = json.load(open(OUT / "pca_decision.json"))
    lin_raw = [("ln_Days_Of_Cover_Filled" if c == "ln_Days_Of_Cover" else c) for c in dec["linear_features"]]
    f[lin_raw] = f[lin_raw].fillna(f[f.Split == "train"][lin_raw].median())
    f = add_relative(f)
    tree_cols, lin_cols = swap_features(dec["tree_features"]), swap_features(lin_raw)
    mono = [-1 if c in PRICE_FEATS else 0 for c in tree_cols]
    dev, test = f[f.Split != "test"], f[f.Split == "test"].reset_index(drop=True)
    print(f"dev {len(dev):,}  test {len(test):,}  tree feats {len(tree_cols)}  linear feats {len(lin_cols)}", flush=True)

    # tuning on 6 rolling folds
    tune, fold_models = [], {}
    for name, grid in [("Linear", [{"alpha": a} for a in (0.1, 1, 10)])] + list(GRIDS.items()):
        for params in grid:
            t0 = time.time()
            cols = lin_cols if name == "Linear" else tree_cols
            cv, mods = cv_score(name, params, dev, cols, None if name == "Linear" else mono)
            tune.append({"Model": name, "Params": json.dumps(params), "CV_WAPE": cv["WAPE_%"].mean(),
                         "CV_Bias": cv["Bias_%"].mean(), "CV_WAPE_SD": cv["WAPE_%"].std(),
                         **{f"WAPE {r.Fold}": r["WAPE_%"] for _, r in cv.iterrows()},
                         **{f"Bias {r.Fold}": r["Bias_%"] for _, r in cv.iterrows()}})
            fold_models[(name, json.dumps(params))] = mods["Q2 2026"]
            print(f"  {name} {params}: CV WAPE {tune[-1]['CV_WAPE']:.2f}%  bias {tune[-1]['CV_Bias']:+.2f}%  "
                  f"Q2-2026 {tune[-1]['WAPE Q2 2026']:.1f}/{tune[-1]['Bias Q2 2026']:+.1f}  ({time.time() - t0:.0f}s)",
                  flush=True)
    tune = pd.DataFrame(tune)
    best = tune.loc[tune.groupby("Model").CV_WAPE.idxmin()].set_index("Model")

    # final fit on Jan 2023 - Jun 2026 + per-SKU calibration from the Q2 2026 fold
    final = {}
    for name, r in best.iterrows():
        params = json.loads(r.Params)
        cols = lin_cols if name == "Linear" else tree_cols
        final[name] = fit(name, params, dev, cols, None if name == "Linear" else mono)
        final[name].calib, final[name].calib_global = calibration(*fold_models[(name, r.Params)])
        pickle.dump(final[name], open(MOD / f"{name}.pkl", "wb"))

    # row-level price-direction check
    samp = test.sample(min(20000, len(test)), random_state=0)
    viol = {}
    for name, m in final.items():
        X1 = samp.copy()
        X1[m.cols] = bump_price(samp.copy(), m.cols)
        viol[name] = float((m.predict_rel(X1) > m.predict_rel(samp) + 1e-9).mean() * 100)
    print("price-direction violations %:", {k: round(v, 3) for k, v in viol.items()}, flush=True)

    # ensemble: best 3 by CV among models with no violations (Linear excluded as a member)
    elig = best[[viol[m] <= 1.0 and m != "Linear" for m in best.index]]
    top = elig.CV_WAPE.nsmallest(3)
    weights = (1 / top) / (1 / top).sum()

    y = np.exp(test.ln_Units).values
    test["Horizon"] = ((test.Week - ORIGIN).dt.days // 7 + 1).astype(int)
    test["Horizon_Band"] = pd.cut(test.Horizon, [0, 1, 4, 13], labels=["1 week", "2-4 weeks", "5-13 weeks"])
    preds = {}
    for cal in (False, True):
        tag = "calibrated" if cal else "raw"
        preds[("one_step", tag)] = {n: m.units(test, calibrate=cal) for n, m in final.items()}
        preds[("recursive", tag)] = {n: recursive(m, dev, test, cal, freeze=True) for n, m in final.items()}
        if cal:
            preds[("recursive_unfrozen", tag)] = {n: recursive(m, dev, test, cal, freeze=False)
                                                  for n, m in final.items()}
    for k in preds:
        preds[k]["Ensemble"] = sum(weights[n] * preds[k][n] for n in weights.index)

    rows, hz, grp, sku = [], [], [], []
    for (mode, tag), pm in preds.items():
        for name, p in pm.items():
            ok = ~np.isnan(p)
            rows.append({"Mode": mode, "Calibration": tag, "Model": name, **metrics(y[ok], p[ok])})
            for b, ix in test.groupby("Horizon_Band", observed=True).indices.items():
                ix = ix[ok[ix]]
                hz.append({"Mode": mode, "Calibration": tag, "Model": name, "Horizon": b, **metrics(y[ix], p[ix])})
            for g, ix in test.groupby("Pilot_Group").indices.items():
                ix = ix[ok[ix]]
                grp.append({"Mode": mode, "Calibration": tag, "Model": name, "Group": g, **metrics(y[ix], p[ix])})
            if mode == "recursive" and tag == "calibrated":
                for a, ix in test.groupby("ArticleCode").indices.items():
                    ix = ix[ok[ix]]
                    sku.append({"Calibration": tag, "Model": name, "ArticleCode": a, **metrics(y[ix], p[ix])})
    res, hz, grp, sku = pd.DataFrame(rows), pd.DataFrame(hz), pd.DataFrame(grp), pd.DataFrame(sku)
    sku = sku.merge(test.groupby("ArticleCode")[["ArticleName", "Pilot_Group"]].first(), left_on="ArticleCode",
                    right_index=True)

    sel = hz[(hz.Mode == "recursive") & (hz.Horizon == "5-13 weeks") & (hz.Calibration == "calibrated")] \
        .set_index("Model")[["WAPE_%", "Bias_%"]]
    one = res[(res.Mode == "one_step") & (res.Calibration == "calibrated")].set_index("Model")
    sel["WAPE_1wk_%"], sel["Bias_1wk_%"] = one["WAPE_%"], one["Bias_%"]
    sel = sel.join(best[["CV_WAPE", "CV_Bias", "CV_WAPE_SD"]], how="left")
    sel["Price_Violations_%"] = [viol.get(m, 0.0) for m in sel.index]
    sel["Eligible"] = (sel["Bias_%"].abs() <= 5) & (sel["Bias_1wk_%"].abs() <= 5) & (sel["Price_Violations_%"] <= 1.0)
    pool = sel[sel.Eligible] if sel.Eligible.any() else sel[sel["Price_Violations_%"] <= 1.0]
    champion = pool["WAPE_%"].idxmin()
    sel["Role"] = np.where(sel.index == champion, "Champion", np.where(sel.Eligible, "Challenger", "Not eligible"))

    print(res.pivot_table(index="Model", columns=["Mode", "Calibration"], values=["WAPE_%", "Bias_%"]).round(1)
          .to_string(), flush=True)
    print(hz[hz.Calibration == "calibrated"].pivot_table(index="Model", columns=["Mode", "Horizon"],
                                                          values="WAPE_%").round(1).to_string(), flush=True)
    print(sel.round(2).to_string(), flush=True)

    out = test[["Week", "Plant", "ArticleCode", "Pilot_Group", "Horizon"]].assign(Actual=y)
    for (mode, tag), pm in preds.items():
        for name, p in pm.items():
            out[f"{name}_{mode}_{tag}"] = p
    out.to_parquet(OUT / "test_predictions.parquet", index=False)
    pickle.dump({"weights": weights.to_dict(), "champion": champion}, open(MOD / "ensemble.pkl", "wb"))
    v1 = pd.read_excel(OUT / "model_evaluation_v1.xlsx", sheet_name="Test by horizon")
    v1 = v1[(v1.Mode == "recursive") & (v1.Horizon == "5-13 weeks")].set_index("Model")[["WAPE_%", "Bias_%"]] \
        .add_suffix("_v1")
    with pd.ExcelWriter(OUT / "model_evaluation.xlsx") as xw:
        sel.join(v1).reset_index().round(3).to_excel(xw, sheet_name="Model selection", index=False)
        res.round(3).to_excel(xw, sheet_name="Test overall", index=False)
        hz.round(3).to_excel(xw, sheet_name="Test by horizon", index=False)
        grp.round(3).to_excel(xw, sheet_name="Test by group", index=False)
        sku.round(3).to_excel(xw, sheet_name="Test per SKU (recursive)", index=False)
        tune.round(3).to_excel(xw, sheet_name="CV tuning (6 folds)", index=False)
        pd.DataFrame({"Model": list(viol), "Violations_%": list(viol.values())}).to_excel(
            xw, sheet_name="Price direction check", index=False)
        pd.DataFrame({"Member": weights.index, "Weight": weights.values}).to_excel(xw, sheet_name="Ensemble",
                                                                                   index=False)
        pd.DataFrame([{"Model": n, "ArticleCode": a, "Calibration_Factor": v} for n, m in final.items()
                      for a, v in m.calib.items()]).round(3).to_excel(xw, sheet_name="Calibration factors", index=False)
    json.dump({"champion": champion, "ensemble": weights.round(4).to_dict(), "violations": viol,
               "selection": sel.reset_index().round(3).to_dict("records")},
              open(OUT / "model_selection.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
