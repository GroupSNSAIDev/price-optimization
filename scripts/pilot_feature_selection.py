"""Step 6 · Feature selection for the 40 pilot SKUs, with rolling-origin cross-validation

Validation design (fixes 1 & 2): five rolling folds, each a 13-week window, trained on everything before it.
Two folds contain December (Q4 2024, Q4 2025), so seasonal features are judged on the Christmas peak too.
Apr-Jun 2026 (valid) and Jul-Sep 2026 (test) are NOT used here; they stay untouched for model tuning and testing.

Methods:
  1 correlation screen + VIF (linear models only; price features protected)
  2 SelectKBest  - F-test + mutual information
  3 Lasso (L1)   - LassoCV on time-ordered folds -> linear set
  4 RFE          - LightGBM, eliminated on the mean WAPE over the 5 rolling folds -> tree set
  5 confirmation - candidate tree sets compared fold by fold: RFE set, + calendar features, +/- stock cover

Stock cover (fix 5): missing before Jun 2024 and left missing for tree models (LightGBM handles it natively);
linear models get it filled with the training median plus a 'Stock_Data_Available' flag.
Cost (fix 6): only last week's unit cost and margin are candidates.
"""
import json
import warnings
from pathlib import Path

import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.feature_selection import f_regression, mutual_info_regression
from sklearn.linear_model import LassoCV, Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

from pilot_features import ID_COLS

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "pilot"
OUT.mkdir(parents=True, exist_ok=True)
PROTECTED = ["ln_Price_Real", "ln_Relative_Price", "Price_Above_Usual", "Price_Below_Usual"]
CALENDAR = ["Holidays_In_Week", "Payday_Week", "Christmas_Season", "December", "Month_Sin", "Month_Cos"]
STOCK = ["ln_Days_Of_Cover", "Stock_Data_Available"]
REFERENCE = ["Store_Class_A", "Zone_City", "Group_A"]
K_BEST = 25
FOLDS = [("Q4 2024", "2024-09-30", "2024-12-30"), ("Q1 2025", "2024-12-30", "2025-03-31"),
         ("Q3 2025", "2025-06-30", "2025-09-29"), ("Q4 2025", "2025-09-29", "2025-12-29"),
         ("Q1 2026", "2025-12-29", "2026-03-30")]
PARAMS = dict(n_estimators=300, learning_rate=0.07, num_leaves=63, min_child_samples=50, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)

FAMILY = {"Price": ["ln_Price_Real", "ln_Relative_Price", "ln_Price_vs_Usual", "Price_Above_Usual", "Price_Below_Usual",
                    "dln_Price_1w", "Temp_Price_Cut", "Discount_Pct", "ln_Category_Price_Index"],
          "Cost & margin": ["ln_Unit_Cost_Real_Lag1", "Margin_Pct_Lag1", "dln_Cost_4w_Lag1"],
          "Demand history": ["ln_Units_Lag1", "ln_Units_Lag2", "ln_Units_Lag4", "ln_Units_Roll4", "ln_Units_Roll13",
                             "ln_Units_Store_SKU_Mean", "Units_Trend_13w", "Weeks_Selling", "ln_Category_Demand_Lag1"],
          "Calendar": CALENDAR + ["Week_Sin", "Week_Cos", "Trend_Weeks"],
          "Stock": STOCK + ["Has_Stock_Record"],
          "Macro": ["ln_FX_BNA", "Inflation_YoY", "Inflation_MoM", "ln_Brent", "GDP_Growth"]}
fam = lambda c: next((k for k, v in FAMILY.items() if c in v),
                     "Store" if c.startswith(("Store", "Zone", "Channel", "ln_Store")) else "Product")
wape = lambda y, p: np.abs(y - p).sum() / y.sum() * 100


def prepare():
    f = pd.read_parquet(ROOT / "clean" / "pilot" / "pilot_features.parquet")
    f = f[f.ln_Units_Store_SKU_Mean.notna() & (f.Split == "train")].copy()      # history needed; train period only
    f["GDP_Growth"] = f.sort_values("Week").GDP_Growth.ffill()
    for c in ["ln_Units_Lag1", "ln_Units_Lag2", "ln_Units_Lag4"]:
        f[c] = f[c].fillna(f.ln_Units_Roll4).fillna(f.ln_Units_Store_SKU_Mean)
    f["ln_Category_Demand_Lag1"] = f.ln_Category_Demand_Lag1.fillna(
        f.groupby(["Plant", "SubGroup"]).ln_Category_Demand_Lag1.transform("median"))
    f["ln_Unit_Cost_Real_Lag1"] = f.ln_Unit_Cost_Real_Lag1.fillna(
        f.groupby(["Plant", "ArticleCode"]).ln_Unit_Cost_Real_Lag1.transform("median"))
    f = f.fillna({"dln_Price_1w": 0, "dln_Cost_4w_Lag1": 0, "Units_Trend_13w": 0, "ln_Price_vs_Usual": 0,
                  "Price_Above_Usual": 0, "Price_Below_Usual": 0, "Margin_Pct_Lag1": f.Margin_Pct_Lag1.median()})
    feats = [c for c in f.columns if c not in ID_COLS and c not in REFERENCE]
    f = f.dropna(subset=[c for c in feats if c != "ln_Days_Of_Cover"] + ["ln_Units"])   # stock cover may stay NaN
    lin = f.copy()                                                        # linear copy: stock cover filled + flag
    lin["ln_Days_Of_Cover"] = lin.ln_Days_Of_Cover.fillna(lin.ln_Days_Of_Cover.median())
    return f.sort_values("Week").reset_index(drop=True), lin.sort_values("Week").reset_index(drop=True), feats


def cv_wape(f, cols, per_fold=False):
    """mean WAPE (units) of LightGBM over the rolling folds"""
    res = {}
    for name, s, e in FOLDS:
        tr, te = f[f.Week < s], f[(f.Week >= s) & (f.Week < e)]
        m = lgb.LGBMRegressor(**PARAMS).fit(tr[cols], tr.ln_Units)
        res[name] = wape(np.exp(te.ln_Units), np.exp(m.predict(te[cols])))
    return res if per_fold else float(np.mean(list(res.values())))


def cv_wape_linear(lin, cols):
    res = []
    for name, s, e in FOLDS:
        tr, te = lin[lin.Week < s], lin[(lin.Week >= s) & (lin.Week < e)]
        sc = StandardScaler().fit(tr[cols])
        r = Ridge(alpha=1.0).fit(sc.transform(tr[cols]), tr.ln_Units)
        res.append(wape(np.exp(te.ln_Units), np.exp(r.predict(sc.transform(te[cols])))))
    return float(np.mean(res))


def vif_screen(X, feats):
    Z = ((X - X.mean()) / X.std().replace(0, 1)).sample(min(60000, len(X)), random_state=1)
    kept, log = list(feats), []
    while True:
        A, vifs = Z[kept].to_numpy(), {}
        for i, c in enumerate(kept):
            D = np.column_stack([np.ones(len(A)), np.delete(A, i, axis=1)])
            beta, *_ = np.linalg.lstsq(D, A[:, i], rcond=None)
            r2 = 1 - (A[:, i] - D @ beta).var() / max(A[:, i].var(), 1e-12)
            vifs[c] = 1 / max(1 - r2, 1e-9)
        cand = {c: v for c, v in vifs.items() if c not in PROTECTED}
        worst = max(cand, key=cand.get)
        if cand[worst] <= 10:
            return kept, pd.DataFrame({"Feature": list(vifs), "VIF": list(vifs.values())}), pd.DataFrame(log)
        log.append({"Dropped": worst, "VIF": vifs[worst]})
        kept.remove(worst)


def main():
    f, lin, feats = prepare()
    print(f"rows {len(f):,} (train period)  candidates {len(feats)}  folds {[x[0] for x in FOLDS]}", flush=True)
    const = [c for c in feats if lin[c].std() < 1e-6]
    feats = [c for c in feats if c not in const]

    # 1 correlation + VIF (linear only) -----------------------------------------------------------------
    corr = lin[feats].corr()
    pairs = pd.DataFrame([(a, b, corr.loc[a, b]) for i, a in enumerate(feats) for b in feats[i + 1:]
                          if abs(corr.loc[a, b]) > .9], columns=["Feature 1", "Feature 2", "Correlation"])
    kept, vif, vif_log = vif_screen(lin[feats], feats)
    print(f"VIF screen (linear): {len(feats)} -> {len(kept)}", flush=True)
    Z = pd.DataFrame(StandardScaler().fit_transform(lin[kept]), columns=kept)
    samp = np.random.default_rng(7).choice(len(Z), size=min(60000, len(Z)), replace=False)

    # 2 SelectKBest -------------------------------------------------------------------------------------
    F, pF = f_regression(Z.iloc[samp], lin.ln_Units.iloc[samp])
    MI = mutual_info_regression(Z.iloc[samp], lin.ln_Units.iloc[samp], random_state=0)
    kb = pd.DataFrame({"Feature": kept, "F_score": F, "F_pvalue": pF, "Mutual_Info": MI})
    kb["Rank_Avg"] = (kb.F_score.rank(ascending=False) + kb.Mutual_Info.rank(ascending=False)) / 2
    kb["KBest"] = kb.Rank_Avg.rank() <= K_BEST
    kb = kb.sort_values("Rank_Avg")

    # 3 Lasso -> linear set -----------------------------------------------------------------------------
    step = max(1, len(Z) // 80000)
    las = LassoCV(cv=TimeSeriesSplit(5), alphas=40, max_iter=5000, n_jobs=-1, random_state=0).fit(
        Z.iloc[::step], lin.ln_Units.iloc[::step])
    lasso = pd.DataFrame({"Feature": kept, "Coefficient": las.coef_}).assign(
        Abs=lambda d: d.Coefficient.abs()).sort_values("Abs", ascending=False)
    lasso["Lasso"] = lasso.Abs > 1e-4
    linear_set = [c for c in kept if lasso.set_index("Feature").Lasso[c] or c in PROTECTED]
    print(f"Lasso: {len(linear_set)} features", flush=True)

    # 4 RFE on rolling-CV WAPE -> tree set --------------------------------------------------------------
    cur, path = list(feats), []
    while len(cur) >= 8:
        folds = cv_wape(f, cur, per_fold=True)
        full = lgb.LGBMRegressor(**PARAMS).fit(f[cur], f.ln_Units)
        imp = pd.Series(full.booster_.feature_importance("gain"), index=cur)
        path.append({"N_Features": len(cur), "CV_WAPE": np.mean(list(folds.values())), **folds, "Features": list(cur)})
        print(f"  RFE {len(cur)}: CV WAPE {path[-1]['CV_WAPE']:.2f}%  (Q4 2024 {folds['Q4 2024']:.1f}, "
              f"Q4 2025 {folds['Q4 2025']:.1f})", flush=True)
        drop = [c for c in imp.sort_values().index if c not in PROTECTED][:2 if len(cur) <= 30 else 4]
        cur = [c for c in cur if c not in drop]
    rfe = pd.DataFrame(path)
    best = rfe.CV_WAPE.min()
    chosen = rfe[rfe.CV_WAPE <= best + 0.4].sort_values("N_Features").iloc[0]    # smallest within the fold noise (0.4 pt)
    rfe_set = list(chosen.Features)

    # 5 confirmation: calendar and stock cover tested explicitly ----------------------------------------
    base = [c for c in rfe_set if c not in STOCK]
    cands = {"RFE set": rfe_set,
             "RFE set + calendar": list(dict.fromkeys(rfe_set + CALENDAR)),
             "RFE set + calendar, no stock cover": list(dict.fromkeys(base + CALENDAR)),
             "RFE set + calendar + stock cover": list(dict.fromkeys(base + CALENDAR + STOCK)),
             "All candidate features": feats}
    rows = []
    for name, cols in cands.items():
        r = cv_wape(f, cols, per_fold=True)
        rows.append({"Feature set": name, "Features": len(cols), "CV_WAPE": np.mean(list(r.values())), **r})
        print(f"  {name}: {rows[-1]['CV_WAPE']:.2f}%", flush=True)
    conf = pd.DataFrame(rows)
    bestc = conf.CV_WAPE.min()
    pick = conf[conf.CV_WAPE <= bestc + 0.1].sort_values("Features").iloc[0]     # smaller set if within 0.1 pt
    tree_set = cands[pick["Feature set"]]
    lin_check = pd.DataFrame([("All features after VIF", len(kept), cv_wape_linear(lin, kept)),
                              ("Linear set (Lasso)", len(linear_set), cv_wape_linear(lin, linear_set))],
                             columns=["Feature set", "Features", "CV_WAPE"])
    print(lin_check.round(2).to_string(index=False))

    votes = pd.DataFrame({"Feature": feats})
    votes["Family"] = votes.Feature.map(fam)
    votes["Passed_VIF"] = votes.Feature.isin(kept)
    votes["KBest"] = votes.Feature.map(kb.set_index("Feature").KBest).fillna(False).astype(bool)
    votes["Lasso"] = votes.Feature.map(lasso.set_index("Feature").Lasso).fillna(False).astype(bool)
    votes["RFE"] = votes.Feature.isin(rfe_set)
    votes["Linear_Set"], votes["Tree_Set"] = votes.Feature.isin(linear_set), votes.Feature.isin(tree_set)
    votes = votes.sort_values(["Tree_Set", "Linear_Set", "RFE", "Lasso", "KBest"], ascending=False)

    with pd.ExcelWriter(OUT / "feature_selection.xlsx") as xw:
        pd.DataFrame({"Item": ["Rows (training period)", "Candidate features", "Validation", "After VIF (linear)",
                               "Linear set (Lasso)", "RFE set", "Tree set (after confirmation)",
                               "Tree set CV WAPE", "Linear set CV WAPE (ridge)", "Fixes applied"],
                      "Value": [f"{len(f):,}", len(feats), "5 rolling 13-week folds incl. Q4 2024 and Q4 2025",
                                len(kept), len(linear_set), len(rfe_set), f"{len(tree_set)} ({pick['Feature set']})",
                                f"{pick.CV_WAPE:.2f}%", f"{lin_check.iloc[1, 2]:.2f}%",
                                "rolling CV with December; calendar & stock cover tested; stock cover not imputed "
                                "for trees; lagged cost only"]}).to_excel(xw, sheet_name="Summary", index=False)
        conf.round(2).to_excel(xw, sheet_name="5 Confirmation (trees)", index=False)
        lin_check.round(2).to_excel(xw, sheet_name="Linear check", index=False)
        votes.to_excel(xw, sheet_name="Feature votes", index=False)
        pairs.round(3).to_excel(xw, sheet_name="1 Correlation > 0.9", index=False)
        vif.round(2).sort_values("VIF", ascending=False).to_excel(xw, sheet_name="1 VIF (kept)", index=False)
        vif_log.round(1).to_excel(xw, sheet_name="1 VIF drops", index=False)
        kb.round(4).to_excel(xw, sheet_name="2 SelectKBest", index=False)
        lasso.round(4).to_excel(xw, sheet_name="3 Lasso", index=False)
        rfe.assign(Features=rfe.Features.str.join(", ")).round(2).to_excel(xw, sheet_name="4 RFE path", index=False)
    json.dump({"linear_features": linear_set, "tree_features": tree_set, "rfe_features": rfe_set,
               "protected": PROTECTED, "folds": FOLDS, "confirmation": conf.round(3).to_dict("records"),
               "linear_check": lin_check.round(3).to_dict("records")},
              open(OUT / "selected_features.json", "w"), indent=1)

    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(rfe.N_Features, rfe.CV_WAPE, marker="o", color="#156082", label="mean of 5 folds")
    ax.plot(rfe.N_Features, rfe["Q4 2025"], marker=".", color="#E97132", lw=1, label="Q4 2025 fold (December)")
    ax.axvline(chosen.N_Features, color="#4D5751", ls="--", label=f"RFE choice: {int(chosen.N_Features)}")
    ax.set_xlabel("number of features")
    ax.set_ylabel("WAPE %")
    ax.invert_xaxis()
    ax.legend(fontsize=8)
    fig.savefig(OUT / "rfe_curve.png", dpi=180, bbox_inches="tight")
    print("linear:", linear_set)
    print("tree:", tree_set)


if __name__ == "__main__":
    main()
