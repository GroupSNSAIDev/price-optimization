"""Step 10 · Demand prediction models for the 40 pilot SKUs

Target: ln(units) per store x SKU x week (weeks with sales). Features from steps 6-7:
  linear model -> linear set (VIF + Lasso); tree models -> tree set + macro principal components.
Models: 1 Linear (ridge, log-log with controls) 2 Random Forest 3 XGBoost 4 LightGBM 5 CatBoost 6 Ensemble
  - tree boosters get a monotone constraint on price features: a higher price never raises predicted demand
  - early stopping / ridge alpha chosen on the validation period (Apr-Jun 2026); test (Jul-Sep 2026) untouched here
  - log -> units back-transformation with each model's smearing factor (Duan), so forecasts are not biased low
  - ensemble = validation-WAPE-weighted average of the best models
Zero-sales weeks (open item 3): models predict demand in weeks the SKU sells; P(sell) per store-SKU (share of the
last 13 training weeks with a sale) is saved so expected weekly units = P(sell) x predicted units.
Price-response check: every model's implied elasticity (+5% price) compared with the step 9 elasticity.
Outputs: analysis/pilot/models/*.pkl, model_validation.xlsx, clean/pilot/p_sell.parquet
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

from pilot_features import ID_COLS
from pilot_pca import macro_block

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, AN = ROOT / "clean", ROOT / "analysis"
OUT = AN / "pilot"
MOD = OUT / "models"
MOD.mkdir(parents=True, exist_ok=True)
PRICE_FEATS = ["ln_Price_Real", "ln_Relative_Price", "ln_Price_vs_Usual", "Price_Above_Usual", "Price_Below_Usual",
               "dln_Price_1w"]
MACRO = ["ln_FX_BNA", "Inflation_YoY", "Inflation_MoM", "ln_Brent", "GDP_Growth"]


def prepare():
    f = pd.read_parquet(CL / "pilot" / "pilot_features.parquet")
    # need history, a clean target and a clean own price (never imputed): weeks where every day was a price
    # outlier have neither and are dropped
    f = f[f.ln_Units_Store_SKU_Mean.notna() & f.ln_Units.notna() & f.ln_Price_Real.notna()
          & f.ln_Relative_Price.notna()].sort_values("Week").reset_index(drop=True)
    tr = f.Split == "train"
    f[MACRO] = f[MACRO].ffill()          # latest months not yet published: carry the last known value forward
    for c in ["ln_Units_Lag1", "ln_Units_Lag2", "ln_Units_Lag4"]:
        f[c] = f[c].fillna(f.ln_Units_Roll4).fillna(f.ln_Units_Store_SKU_Mean)
    f["ln_Category_Demand_Lag1"] = f.ln_Category_Demand_Lag1.fillna(
        f.groupby(["Plant", "SubGroup"]).ln_Category_Demand_Lag1.transform("median"))
    f["ln_Unit_Cost_Real_Lag1"] = f.ln_Unit_Cost_Real_Lag1.fillna(
        f.groupby(["Plant", "ArticleCode"]).ln_Unit_Cost_Real_Lag1.transform("median"))
    f = f.fillna({"dln_Price_1w": 0, "dln_Cost_4w_Lag1": 0, "Units_Trend_13w": 0, "ln_Price_vs_Usual": 0,
                  "Price_Above_Usual": 0, "Price_Below_Usual": 0, "Margin_Pct_Lag1": f[tr].Margin_Pct_Lag1.median()})
    msc, mpca, mn, *_ = macro_block()
    Z = mpca.transform(msc.transform(f[MACRO]))
    for i in range(mn):
        f[f"Macro_PC{i + 1}"] = Z[:, i]
    f["ln_Days_Of_Cover_Filled"] = f.ln_Days_Of_Cover.fillna(f[tr].ln_Days_Of_Cover.median())
    return f, (msc, mpca, mn)


def metrics(y, p):
    e = p - y
    return {"MAE": np.abs(e).mean(), "RMSE": np.sqrt((e ** 2).mean()), "WAPE_%": np.abs(e).sum() / y.sum() * 100,
            "Bias_%": e.sum() / y.sum() * 100}


def smear(resid):
    return float(np.mean(np.exp(resid)))


def bump_price(X, cols, pct=0.05):
    """+5% own price applied consistently to every price feature present"""
    X = X.copy()
    d = np.log(1 + pct)
    for c in ["ln_Price_Real", "ln_Relative_Price", "ln_Price_vs_Usual", "dln_Price_1w"]:
        if c in cols:
            X[c] = X[c] + d
    if "ln_Price_vs_Usual" in X:
        X["Price_Above_Usual"] = X.ln_Price_vs_Usual.clip(lower=0) if "Price_Above_Usual" in cols else None
        X["Price_Below_Usual"] = X.ln_Price_vs_Usual.clip(upper=0) if "Price_Below_Usual" in cols else None
    elif {"Price_Above_Usual", "Price_Below_Usual"} <= set(cols):
        v = X.Price_Above_Usual + X.Price_Below_Usual + d
        X["Price_Above_Usual"], X["Price_Below_Usual"] = v.clip(lower=0), v.clip(upper=0)
    return X[cols]


def main():
    f, macro = prepare()
    pca_dec = json.load(open(OUT / "pca_decision.json"))
    tree_cols = pca_dec["tree_features"]
    lin_cols = [("ln_Days_Of_Cover_Filled" if c == "ln_Days_Of_Cover" else c) for c in pca_dec["linear_features"]]
    trm = f[f.Split == "train"][lin_cols].median()
    na = f[lin_cols].isna().sum()
    print("linear features with gaps (filled with training median):", na[na > 0].to_dict(), flush=True)
    f[lin_cols] = f[lin_cols].fillna(trm)
    tr, va = f[f.Split == "train"], f[f.Split == "valid"]
    ytr, yva = tr.ln_Units, va.ln_Units
    units_va = np.exp(yva)
    print(f"train {len(tr):,}  valid {len(va):,}  tree features {len(tree_cols)}  linear features {len(lin_cols)}",
          flush=True)
    mono = [-1 if c in PRICE_FEATS else 0 for c in tree_cols]
    models, preds, info = {}, {}, []

    def done(name, model, p_tr_log, p_va_log, extra, t0, cols):
        s = smear(ytr.values - p_tr_log)
        p = np.exp(p_va_log) * s
        preds[name] = p
        models[name] = {"model": model, "smear": s, "features": cols, **extra}
        info.append({"Model": name, "Fit_seconds": round(time.time() - t0, 1), "Smearing": s,
                     **metrics(units_va.values, p), **{k: v for k, v in extra.items() if k != "scaler"}})
        print(f"  {name:14s} valid WAPE {info[-1]['WAPE_%']:.2f}%  bias {info[-1]['Bias_%']:+.2f}%  "
              f"({info[-1]['Fit_seconds']}s)", flush=True)

    # 1 linear (ridge, log-log with controls)
    t0 = time.time()
    sc = StandardScaler().fit(tr[lin_cols])
    best = min([(a, Ridge(alpha=a).fit(sc.transform(tr[lin_cols]), ytr)) for a in [0.1, 1, 10, 100]],
               key=lambda am: np.abs(np.exp(am[1].predict(sc.transform(va[lin_cols]))) - units_va).sum())
    a, rid = best
    done("Linear", rid, rid.predict(sc.transform(tr[lin_cols])), rid.predict(sc.transform(va[lin_cols])),
         {"alpha": a, "scaler": sc}, t0, lin_cols)

    Xtr, Xva = tr[tree_cols], va[tree_cols]
    # 2 random forest (no native monotone constraint; NaN filled)
    t0 = time.time()
    med = Xtr.median()
    rf = RandomForestRegressor(n_estimators=300, max_depth=18, min_samples_leaf=20, max_features=0.5, n_jobs=-1,
                               random_state=0).fit(Xtr.fillna(med), ytr)
    done("RandomForest", rf, rf.predict(Xtr.fillna(med)), rf.predict(Xva.fillna(med)), {"fill": med.to_dict()},
         t0, tree_cols)

    # 3 XGBoost
    t0 = time.time()
    xg = xgb.XGBRegressor(n_estimators=3000, learning_rate=0.03, max_depth=8, min_child_weight=20, subsample=0.8,
                          colsample_bytree=0.8, tree_method="hist", monotone_constraints=tuple(mono),
                          early_stopping_rounds=100, eval_metric="rmse", n_jobs=-1, random_state=0)
    xg.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    done("XGBoost", xg, xg.predict(Xtr), xg.predict(Xva), {"best_iteration": int(xg.best_iteration)}, t0, tree_cols)

    # 4 LightGBM
    t0 = time.time()
    lg = lgb.LGBMRegressor(n_estimators=5000, learning_rate=0.03, num_leaves=63, min_child_samples=50, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, monotone_constraints=mono,
                           monotone_constraints_method="advanced", verbose=-1, random_state=0)
    lg.fit(Xtr, ytr, eval_set=[(Xva, yva)], callbacks=[lgb.early_stopping(100, verbose=False)])
    done("LightGBM", lg, lg.predict(Xtr), lg.predict(Xva), {"best_iteration": int(lg.best_iteration_)}, t0, tree_cols)

    # 5 CatBoost
    t0 = time.time()
    cbm = cb.CatBoostRegressor(iterations=5000, learning_rate=0.05, depth=8, loss_function="RMSE",
                               monotone_constraints=mono, od_type="Iter", od_wait=100, verbose=0, random_seed=0,
                               thread_count=-1)
    cbm.fit(Xtr, ytr, eval_set=(Xva, yva), use_best_model=True)
    done("CatBoost", cbm, cbm.predict(Xtr), cbm.predict(Xva), {"best_iteration": int(cbm.get_best_iteration())},
         t0, tree_cols)

    # 6 ensemble: weight the 3 best by 1 / validation WAPE
    res = pd.DataFrame(info).set_index("Model")
    top = res.WAPE_pct if "WAPE_pct" in res else res["WAPE_%"]
    top = top.nsmallest(3)
    w = (1 / top) / (1 / top).sum()
    p_ens = sum(w[m] * preds[m] for m in w.index)
    preds["Ensemble"] = p_ens
    models["Ensemble"] = {"members": w.to_dict()}
    info.append({"Model": "Ensemble", "Fit_seconds": 0, "Smearing": np.nan, **metrics(units_va.values, p_ens),
                 "members": ", ".join(f"{m} {v:.2f}" for m, v in w.items())})
    print(f"  {'Ensemble':14s} valid WAPE {info[-1]['WAPE_%']:.2f}%  ({info[-1]['members']})", flush=True)
    res = pd.DataFrame(info)

    # per-group validation WAPE
    grp = []
    for g, idx in va.groupby("Pilot_Group").groups.items():
        m = va.index.get_indexer(idx)
        for name, p in preds.items():
            grp.append({"Group": g, "Model": name, **metrics(units_va.values[m], p[m])})
    grp = pd.DataFrame(grp).pivot(index="Group", columns="Model", values="WAPE_%")

    # price-response check: implied elasticity of a +5% price change, per SKU, vs step 9
    e9 = pd.read_parquet(CL / "pilot" / "sku_elasticity.parquet").set_index("ArticleCode")
    resp = []
    samp = va.sample(frac=1, random_state=0).groupby("ArticleCode").head(300)
    for name, mobj in models.items():
        if name == "Ensemble":
            continue
        cols = mobj["features"]
        X0 = samp[cols].copy()
        X1 = bump_price(samp.copy(), cols)
        if name == "Linear":
            p0, p1 = (mobj["model"].predict(mobj["scaler"].transform(X0)),
                      mobj["model"].predict(mobj["scaler"].transform(X1)))
        elif name == "RandomForest":
            p0, p1 = mobj["model"].predict(X0.fillna(mobj["fill"])), mobj["model"].predict(X1.fillna(mobj["fill"]))
        else:
            p0, p1 = mobj["model"].predict(X0), mobj["model"].predict(X1)
        imp = pd.Series((p1 - p0) / np.log(1.05), index=samp.index).groupby(samp.ArticleCode).mean()
        for code, v in imp.items():
            resp.append({"Model": name, "ArticleCode": code, "Implied_Elasticity": v})
    resp = pd.DataFrame(resp).pivot(index="ArticleCode", columns="Model", values="Implied_Elasticity")
    resp = e9[["Group", "ArticleName", "Elasticity_Final"]].join(resp)
    agree = pd.DataFrame({m: {"Median implied elasticity": resp[m].median(),
                              "SKUs with wrong sign (>0)": int((resp[m] > 0.02).sum()),
                              "Correlation with step 9": resp[m].corr(resp.Elasticity_Final)}
                          for m in [c for c in resp.columns if c in models]}).T
    print(agree.round(3).to_string(), flush=True)

    # P(sell): share of the last 13 training weeks with a sale, per store-SKU (zero-sales weeks)
    wm = pd.read_parquet(CL / "weekly_model.parquet", columns=["Week", "Plant", "ArticleCode"])
    wm = wm[wm.ArticleCode.isin(f.ArticleCode.unique()) & (wm.Week < pd.Timestamp("2026-03-30"))
            & (wm.Week >= pd.Timestamp("2025-12-29"))]
    ps = (wm.groupby(["Plant", "ArticleCode"]).Week.nunique() / 13).clip(upper=1).rename("P_Sell").reset_index()
    ps.to_parquet(CL / "pilot" / "p_sell.parquet", index=False)

    for name, mobj in models.items():
        pickle.dump(mobj, open(MOD / f"{name}.pkl", "wb"))
    va_pred = va[["Week", "Plant", "ArticleCode", "Pilot_Group", "Units"]].assign(**preds)
    va_pred.to_parquet(OUT / "valid_predictions.parquet", index=False)
    with pd.ExcelWriter(OUT / "model_validation.xlsx") as xw:
        res.round(3).to_excel(xw, sheet_name="Validation metrics", index=False)
        grp.round(2).to_excel(xw, sheet_name="WAPE by group")
        agree.round(3).to_excel(xw, sheet_name="Price response summary")
        resp.round(3).to_excel(xw, sheet_name="Price response per SKU")
        pd.DataFrame({"Feature": tree_cols, "Monotone": mono}).to_excel(xw, sheet_name="Tree features", index=False)
        pd.DataFrame({"Feature": lin_cols}).to_excel(xw, sheet_name="Linear features", index=False)
        ps.describe().round(3).to_excel(xw, sheet_name="P(sell) summary")
    json.dump({"validation": res.drop(columns=["members"], errors="ignore").round(4).to_dict("records"),
               "ensemble_members": w.round(4).to_dict()}, open(OUT / "model_summary.json", "w"), indent=1, default=str)
    print(res[["Model", "MAE", "RMSE", "WAPE_%", "Bias_%"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
