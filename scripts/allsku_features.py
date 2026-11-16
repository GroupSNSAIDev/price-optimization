"""All-SKU project, phase C: features (C1), feature selection (C2) and PCA test (C3), chain level (SKU x week).

C1  Demo feature set rebuilt at chain level (store-only features dropped, distribution features added):
    price (real, vs usual, vs SubGroup, steps, markdown), cost (lagged real unit cost, cost change, net margin),
    demand lags and rolling means, distribution (reach, stores selling, stores open, stock-outs), calendar,
    macro, SKU attributes (IVA, imported, approved groupings, SubGroup).
    Every feature is known at the decision week (lags shifted; no same-week outcome like spikes).
    Target (demo v2): ln(units + 1) minus ln(13-week mean + 1), i.e. demand relative to its recent level.
    Split by time: train < 6 Apr 2026, validation 6 Apr - 5 Jul 2026, test from 6 Jul 2026.
C2  Linear set: VIF (drop > 10) then Lasso with time-ordered CV. Tree set: LightGBM recursive elimination
    (drop the weakest 10% while validation WAPE stays within 0.2 pt of the best). Both scored on validation WAPE (units).
C3  PCA: calendar, macro and demand-lag blocks replaced by components (90% variance); kept only if WAPE improves.

Inputs: clean/allsku/chain_weekly.parquet, clean/allsku/scope.parquet, checkpoints/macro_monthly.parquet, dim_article_master
Outputs: clean/allsku/features.parquet, analysis/allsku/feature_selection.xlsx, analysis/allsku/selected_features.json
"""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import LassoCV, LinearRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
TRAIN_END, VALID_END = pd.Timestamp("2026-04-06"), pd.Timestamp("2026-07-06")
SEED = 2026


def z(c):
    return str(c).lstrip("0")


def build():
    c = pd.read_parquet(CL / "chain_weekly.parquet").sort_values(["Code", "Week"]).reset_index(drop=True)
    sc = pd.read_parquet(CL / "scope.parquet").set_index("Code")
    g = c.groupby("Code")
    lu = np.log1p(c.Units)
    sh = lambda s, k=1: s.groupby(c.Code).shift(k)
    roll = lambda s, n: s.groupby(c.Code).transform(lambda x: x.shift(1).rolling(n, min_periods=1).mean())
    f = c[["Code", "Week", "Units"]].copy()
    # demand history
    f["ln_Units_Lag1"], f["ln_Units_Lag2"], f["ln_Units_Lag4"] = sh(lu, 1), sh(lu, 2), sh(lu, 4)
    f["ln_Units_Lag52"] = sh(lu, 52)
    f["ln_Units_Roll4"], f["ln_Units_Roll13"] = np.log1p(roll(c.Units, 4)), np.log1p(roll(c.Units, 13))
    f["Units_Trend_13w"] = f.ln_Units_Roll4 - f.ln_Units_Roll13
    f["Weeks_Selling"] = g.cumcount()
    f["No_Sales_Lag1"] = sh(c.No_Sales_Week.astype(float))
    # price (net of IVA, real = CPI deflated)
    pr = c.Price_Real_KZ.groupby(c.Code).ffill()
    lpr = np.log(pr)
    f["ln_Price_Real"] = lpr
    f["ln_Price_vs_Usual"] = np.log(c.Price_KZ / c.Regular_Price_KZ)
    f["Price_Above_Usual"] = f.ln_Price_vs_Usual.clip(lower=0)
    f["Price_Below_Usual"] = f.ln_Price_vs_Usual.clip(upper=0)
    f["dln_Price_1w"] = lpr.groupby(c.Code).diff()
    f["Markdown_Week"] = c.Markdown_Week.astype(float)
    f["Transition_Week"] = c.Transition_Week.astype(float)
    # SubGroup price index (leave-one-out, sales weighted) and relative price
    sub = c.Code.map(sc.SubGroup)
    f["SubGroup"] = sub.astype("category")
    tmp = pd.DataFrame({"sub": sub, "Week": c.Week, "x": f.ln_Price_vs_Usual.fillna(0) * c.Sales_KZ, "w": c.Sales_KZ})
    tot = tmp.groupby(["sub", "Week"])[["x", "w"]].transform("sum")
    f["ln_Category_Price_Index"] = ((tot.x - tmp.x) / (tot.w - tmp.w).replace(0, np.nan)).fillna(0)
    f["ln_Relative_Price"] = f.ln_Price_vs_Usual - f.ln_Category_Price_Index
    cd = c.groupby([sub, c.Week]).Units.transform("sum")
    f["ln_Category_Demand_Lag1"] = np.log1p(cd.groupby(c.Code).shift(1))
    # cost and margin (net of IVA)
    cost_real = (c.Unit_Cost_KZ / c.CPI_Deflator).groupby(c.Code).ffill()
    f["ln_Unit_Cost_Real_Lag1"] = np.log(sh(cost_real))
    f["dln_Cost_4w_Lag1"] = np.log(sh(cost_real) / sh(cost_real, 5))
    f["Margin_Net_Lag1"] = sh(c.Margin_Net_Pct)
    # distribution
    f["Reach_Lag1"] = sh(c.Reach_Pct)
    f["ln_Stores_Selling_Lag1"] = np.log1p(sh(c.Stores_Selling))
    f["ln_Stores_Open"] = np.log(c.Stores_Open)
    f["OOS_Share_Lag1"] = sh(c.OOS_Share)
    # calendar
    woy = c.Week.dt.isocalendar().week.astype(int).values
    f["Holidays_In_Week"], f["Payday_Week"] = c.Holidays_In_Week, c.Payday_Week.astype(float)
    f["Christmas_Season"] = c.Christmas_Season.astype(float)
    f["December"] = (c.Week.dt.month == 12).astype(float)
    f["Week_Sin"], f["Week_Cos"] = np.sin(2 * np.pi * woy / 52), np.cos(2 * np.pi * woy / 52)
    f["Month_Sin"], f["Month_Cos"] = np.sin(2 * np.pi * c.Week.dt.month / 12), np.cos(2 * np.pi * c.Week.dt.month / 12)
    xmas = pd.to_datetime(c.Week.dt.year.astype(str) + "-12-25")
    f["Weeks_To_Christmas"] = ((xmas - c.Week).dt.days / 7).clip(-2, 12)
    f["Trend_Weeks"] = (c.Week - c.Week.min()).dt.days / 7
    # macro (monthly; months not yet published carry the last value)
    mm = pd.read_parquet(ROOT / "checkpoints" / "macro_monthly.parquet")
    mm["Month"] = mm.Month.astype(str)
    mm = mm.set_index("Month")[["FX_BNA_Avg", "Inflation_YoY_Pct", "Inflation_MoM_Pct", "Brent_USD"]].ffill()
    mon = (c.Week + pd.Timedelta(days=3)).dt.to_period("M").astype(str)
    mac = mm.reindex(mon.values).set_axis(c.index)
    f["ln_FX_BNA"], f["Inflation_YoY"], f["Inflation_MoM"], f["ln_Brent"] = np.log(mac.FX_BNA_Avg), mac.Inflation_YoY_Pct, mac.Inflation_MoM_Pct, np.log(mac.Brent_USD)
    # SKU attributes and approved groupings
    m = pd.read_parquet(ROOT / "checkpoints" / "dim_article_master.parquet", columns=["ArticalCode", "PurchaseType"])
    m["c"] = m.ArticalCode.map(z)
    imp = m.drop_duplicates("c").set_index("c").PurchaseType.eq("Import")
    f["Imported"] = c.Code.map(imp).fillna(False).astype(float)
    f["IVA_Pct"] = c.IVA_Pct
    for col, vals in [("Segment", ["Stars", "Traffic drivers", "Margin broken", "Core"]), ("Insight", ["Everyday KVI", "Raise candidate", "Danger zone"])]:
        s = c.Code.map(sc[col])
        for v in vals:
            f[f"{col[:3]}_{v.replace(' ', '_')}"] = (s == v).astype(float)
    f["ABC_A"] = (c.Code.map(sc.ABC) == "A").astype(float)
    # target and split
    f["y"] = np.log1p(c.Units) - f.ln_Units_Roll13
    f["Split"] = np.where(c.Week < TRAIN_END, "train", np.where(c.Week < VALID_END, "valid", "test"))
    f["Usable"] = f.ln_Units_Roll13.notna() & (f.Weeks_Selling >= 4) & f.ln_Price_Real.notna() & ~c.Spike_Week
    return f


def wape(units, pred_y, roll13):
    pred_units = np.expm1(pred_y + roll13).clip(min=0)
    return float(np.abs(units - pred_units).sum() / units.sum() * 100)


def main():
    f = build()
    f.to_parquet(CL / "features.parquet", index=False)
    feats = [x for x in f.columns if x not in ("Code", "Week", "Units", "y", "Split", "Usable", "SubGroup")]
    d = f[f.Usable].copy()
    num = d[feats].replace([np.inf, -np.inf], np.nan)
    d[feats] = num.fillna(num.median())
    tr, va = d[d.Split == "train"], d[d.Split == "valid"]
    log = []

    # ---- C2 linear: VIF then Lasso
    keep = [x for x in feats if tr[x].std() > 0]
    sc = StandardScaler().fit(tr[keep])
    X = pd.DataFrame(sc.transform(tr[keep]), columns=keep).sample(min(len(tr), 40000), random_state=SEED)
    while True:
        vif = {}
        for col in keep:
            others = [k for k in keep if k != col]
            r2 = LinearRegression().fit(X[others], X[col]).score(X[others], X[col])
            vif[col] = 1 / max(1 - r2, 1e-6)
        worst = max(vif, key=vif.get)
        if vif[worst] <= 10:
            break
        log.append({"Stage": "VIF drop", "Feature": worst, "Value": round(vif[worst], 1)})
        keep.remove(worst)
        X = X[keep]
    sc = StandardScaler().fit(tr[keep])
    las = LassoCV(cv=TimeSeriesSplit(5), alphas=30, random_state=SEED, max_iter=5000).fit(sc.transform(tr[keep]), tr.y)
    lin = [k for k, b in zip(keep, las.coef_) if abs(b) > 1e-6]
    def lin_wape(cols):
        s = StandardScaler().fit(tr[cols]); m = LinearRegression().fit(s.transform(tr[cols]), tr.y)
        return wape(va.Units.values, m.predict(s.transform(va[cols])), va.ln_Units_Roll13.values)
    res = [{"Model": "Linear, all features", "Features": len(feats), "Valid_WAPE_%": lin_wape(feats)},
           {"Model": "Linear, VIF", "Features": len(keep), "Valid_WAPE_%": lin_wape(keep)},
           {"Model": "Linear, VIF + Lasso", "Features": len(lin), "Valid_WAPE_%": lin_wape(lin)}]

    # ---- C2 trees: LightGBM recursive elimination
    params = dict(n_estimators=600, learning_rate=0.05, num_leaves=63, min_child_samples=50, subsample=0.8, subsample_freq=1,
                  colsample_bytree=0.8, random_state=SEED, verbose=-1)
    def lgb_fit(cols):
        cols2 = cols + ["SubGroup"]
        m = lgb.LGBMRegressor(**params).fit(tr[cols2], tr.y, categorical_feature=["SubGroup"])
        return m, wape(va.Units.values, m.predict(va[cols2]), va.ln_Units_Roll13.values)
    cur = list(feats); curve = []
    m, best = lgb_fit(cur); curve.append((len(cur), best)); best_set, best_w = list(cur), best
    while len(cur) > 10:
        imp = pd.Series(m.booster_.feature_importance("gain"), index=m.booster_.feature_name()).drop("SubGroup", errors="ignore")
        drop = list(imp.reindex(cur).fillna(0).nsmallest(max(1, len(cur) // 10)).index)
        trial = [x for x in cur if x not in drop]
        m2, w2 = lgb_fit(trial)
        curve.append((len(trial), w2))
        log.extend({"Stage": "RFE drop", "Feature": x, "Value": round(w2, 2)} for x in drop)
        if w2 > best_w + 0.2:
            break
        cur, m = trial, m2
        if w2 <= best_w + 0.2:
            best_set = list(cur)
            best_w = min(best_w, w2)
    tree = best_set
    res += [{"Model": "LightGBM, all features", "Features": len(feats), "Valid_WAPE_%": curve[0][1]},
            {"Model": "LightGBM, RFE set", "Features": len(tree), "Valid_WAPE_%": lgb_fit(tree)[1]}]

    # ---- C3 PCA on blocks
    blocks = {"calendar": ["Holidays_In_Week", "Payday_Week", "Christmas_Season", "December", "Week_Sin", "Week_Cos", "Month_Sin", "Month_Cos", "Weeks_To_Christmas"],
              "macro": ["ln_FX_BNA", "Inflation_YoY", "Inflation_MoM", "ln_Brent"],
              "demand_lags": ["ln_Units_Lag1", "ln_Units_Lag2", "ln_Units_Lag4", "ln_Units_Roll4", "ln_Units_Roll13", "ln_Units_Lag52"]}
    pca_res = []
    for name, cols in blocks.items():
        cols = [x for x in cols if x in feats]
        s = StandardScaler().fit(tr[cols]); p = PCA(0.9, random_state=SEED).fit(s.transform(tr[cols]))
        pcs = [f"PC_{name}_{i}" for i in range(p.n_components_)]
        for part in (tr, va):
            part[pcs] = p.transform(s.transform(part[cols]))
        base = [x for x in tree if x not in cols] + pcs
        if name == "demand_lags":
            base += ["ln_Units_Roll13"]          # still needed to rebuild units from the target
        w_ = lgb_fit(base)[1]
        pca_res.append({"Block": name, "Components": p.n_components_, "Valid_WAPE_%": round(w_, 2),
                        "vs RFE set": round(w_ - res[-1]["Valid_WAPE_%"], 2), "Keep": w_ < res[-1]["Valid_WAPE_%"] - 0.1})
    res = pd.DataFrame(res).round(2)
    sel = {"linear_features": lin, "tree_features": tree, "categorical": ["SubGroup"],
           "pca_blocks_kept": [r["Block"] for r in pca_res if r["Keep"]], "target": "ln(units+1) - ln(13-week mean+1)",
           "split": {"train_end": str(TRAIN_END.date()), "valid_end": str(VALID_END.date())}}
    (OUT / "selected_features.json").write_text(json.dumps(sel, indent=1), encoding="utf-8")
    with pd.ExcelWriter(OUT / "feature_selection.xlsx") as xw:
        pd.DataFrame({"Item": ["SKU-weeks usable", "train / valid / test rows", "features built"],
                      "Value": [len(d), f"{len(tr):,} / {len(va):,} / {int((d.Split == 'test').sum()):,}", len(feats)]}).to_excel(xw, sheet_name="Summary", index=False)
        res.to_excel(xw, sheet_name="C2 comparison", index=False)
        pd.DataFrame(curve, columns=["Features", "Valid_WAPE_%"]).round(2).to_excel(xw, sheet_name="C2 RFE curve", index=False)
        pd.DataFrame(pca_res).to_excel(xw, sheet_name="C3 PCA test", index=False)
        pd.DataFrame(log).to_excel(xw, sheet_name="Drop log", index=False)
        pd.DataFrame({"Linear set": pd.Series(lin), "Tree set": pd.Series(tree)}).to_excel(xw, sheet_name="Selected", index=False)
    print(f"usable {len(d):,} rows | train {len(tr):,} valid {len(va):,} | features {len(feats)}")
    print(res.to_string(index=False)); print(pd.DataFrame(pca_res).to_string(index=False))
    print("linear:", lin); print("tree:", tree)


if __name__ == "__main__":
    main()
