"""All-SKU project, phase E: chain-level baseline demand (SKU x week) at today's prices, 52 weeks ahead.

E1  Models on the C2 feature sets: Linear, Random Forest, LightGBM, XGBoost, CatBoost (price monotone where supported),
    plus the structure test: one global model vs one model per MainGroup vs one small model per SKU (ridge on own lags).
E2  Training design (demo v2): target = demand relative to its 13-week level, recency weights (26-week half-life),
    level calibration on an internal 13-week fold, inputs frozen at the forecast origin (price at today's regular
    level, no markdown, cost / stores / macro as at the origin), forecast built week by week (recursive).
E3  Benchmark over 7 origins x 13 weeks: B1 last-13-week average, B2 B1 x seasonal path, B3 last year x trend,
    the ML champion, and blends ML / B2 = 30/70 and 50/50.
E4  Seasonal path from the analog years (2024, 2025; 2023 left out): chain vs MainGroup path, with / without SKU
    overrides where a SKU's own path repeats in both years; tested on the same origins.
E5  Final 52-week forecast from 9 Nov 2026 with 80% ranges from the back-test errors (coverage checked).
E6  Explainability: LightGBM gain importance, SHAP, permutation importance, price partial dependence vs phase D.

Outputs: clean/allsku/baseline_forecast.parquet, analysis/allsku/baseline.xlsx
"""
import json
import time
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
SEED, H, HALF_LIFE = 2026, 13, 26
CAL_CLIP = (0.9, 1.1)
ORIGINS = [pd.Timestamp(x) for x in ["2024-09-30", "2025-01-06", "2025-04-07", "2025-07-07", "2025-10-06", "2026-03-30", "2026-08-03"]]
MODEL_ORIGINS = ORIGINS[-3:]                  # all five model types compared on the three most recent origins
FINAL_ORIGIN = pd.Timestamp("2026-11-09")
PRICE_FEATS = ["ln_Price_vs_Usual", "ln_Relative_Price", "Price_Above_Usual", "Price_Below_Usual", "dln_Price_1w", "ln_Price_Real"]
HOLIDAYS = pd.to_datetime([*[f"{y}-{md}" for y in range(2023, 2029) for md in ["01-01", "02-04", "03-08", "03-23", "04-04", "05-01", "09-17", "11-02", "11-11", "12-25"]],
                           "2024-02-13", "2025-03-04", "2026-02-17", "2027-02-09", "2024-03-29", "2025-04-18", "2026-04-03", "2027-03-26"])
MEDIANS = {}
SEL = json.loads((OUT / "selected_features.json").read_text(encoding="utf-8")) if (OUT / "selected_features.json").exists() else {}


def calendar(weeks):
    c = pd.DataFrame({"Week": pd.to_datetime(weeks)})
    days = c.Week.apply(lambda w: pd.date_range(w, periods=7))
    c["Holidays_In_Week"] = days.apply(lambda d: d.isin(HOLIDAYS).sum())
    c["Payday_Week"] = days.apply(lambda d: bool(((d.day >= 25) | (d.day <= 3)).any())).astype(float)
    mid = c.Week + pd.Timedelta(days=3)
    c["Christmas_Season"] = ((mid.dt.month == 12) & (mid.dt.day >= 8)).astype(float)
    c["December"] = (c.Week.dt.month == 12).astype(float)
    woy = c.Week.dt.isocalendar().week.astype(int)
    c["Week_Sin"], c["Week_Cos"] = np.sin(2 * np.pi * woy / 52), np.cos(2 * np.pi * woy / 52)
    c["Month_Sin"], c["Month_Cos"] = np.sin(2 * np.pi * c.Week.dt.month / 12), np.cos(2 * np.pi * c.Week.dt.month / 12)
    xmas = pd.to_datetime(c.Week.dt.year.astype(str) + "-12-25")
    c["Weeks_To_Christmas"] = ((xmas - c.Week).dt.days / 7).clip(-2, 12)
    return c.set_index("Week")


# ---------------------------------------------------------------- models
class Model:
    def __init__(self, kind, feats):
        self.kind, self.feats, self.cal = kind, list(feats), 1.0

    def fit(self, X, y, w):
        f = self.feats
        if self.kind == "Linear":
            Z = X[f].to_numpy(float)
            self.mu, self.sd = Z.mean(0), Z.std(0) + 1e-9
            Z = np.column_stack([np.ones(len(Z)), (Z - self.mu) / self.sd])
            sw = np.sqrt(w)
            self.b = np.linalg.lstsq(Z * sw[:, None], y * sw, rcond=None)[0]
        elif self.kind == "LightGBM":
            mono = [-1 if c in PRICE_FEATS and c != "ln_Price_Real" else 0 for c in f] + [0]
            self.m = lgb.LGBMRegressor(n_estimators=700, learning_rate=0.04, num_leaves=63, min_child_samples=50, subsample=0.8,
                                       subsample_freq=1, colsample_bytree=0.8, monotone_constraints=mono, random_state=SEED, verbose=-1)
            self.m.fit(X[f + ["SubGroup"]], y, sample_weight=w, categorical_feature=["SubGroup"])
        elif self.kind == "XGBoost":
            import xgboost as xgb
            mono = "(" + ",".join("-1" if c in PRICE_FEATS and c != "ln_Price_Real" else "0" for c in f) + ")"
            self.m = xgb.XGBRegressor(n_estimators=600, learning_rate=0.05, max_depth=8, subsample=0.8, colsample_bytree=0.8,
                                      monotone_constraints=mono, tree_method="hist", random_state=SEED, n_jobs=-1)
            self.m.fit(X[f], y, sample_weight=w)
        elif self.kind == "CatBoost":
            from catboost import CatBoostRegressor
            mono = [-1 if c in PRICE_FEATS and c != "ln_Price_Real" else 0 for c in f]
            self.m = CatBoostRegressor(iterations=700, learning_rate=0.08, depth=8, monotone_constraints=mono, random_seed=SEED,
                                       verbose=0, thread_count=-1)
            self.m.fit(X[f], y, sample_weight=w)
        elif self.kind == "Random Forest":
            from sklearn.ensemble import RandomForestRegressor
            self.m = RandomForestRegressor(n_estimators=150, max_depth=18, min_samples_leaf=20, max_samples=0.5, n_jobs=-1, random_state=SEED)
            self.m.fit(X[f], y, sample_weight=w)
        return self

    def predict(self, X):
        f = self.feats
        if self.kind == "Linear":
            Z = (X[f].to_numpy(float) - self.mu) / self.sd
            return np.column_stack([np.ones(len(Z)), Z]) @ self.b
        if self.kind == "LightGBM":
            return self.m.predict(X[f + ["SubGroup"]])
        return self.m.predict(X[f])


def feats_for(kind):
    if kind == "Linear":
        return SEL.get("linear_features", [])
    return SEL.get("tree_features", [])


# ---------------------------------------------------------------- data
def load():
    f = pd.read_parquet(CL / "features.parquet")
    f["SubGroup"] = f.SubGroup.astype("category")
    cw = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Units", "Stores_Open", "Markdown_Week", "Spike_Week"])
    sc = pd.read_parquet(CL / "scope.parquet", columns=["Code", "MainGroup", "SubGroup", "ABC", "Segment", "in_scope"]).set_index("Code")
    allf = SEL.get("tree_features", []) + SEL.get("linear_features", [])
    num = list(dict.fromkeys([c for c in allf if c in f.columns]))
    f[num] = f[num].replace([np.inf, -np.inf], np.nan)
    MEDIANS.update(f[num].median().to_dict())
    f[num] = f[num].fillna(f[num].median())
    return f, cw, sc


def train(kind, f, origin, feats):
    """fit on weeks before origin-13, calibrate on the recursive forecast of the last 13 weeks, refit on all weeks"""
    def fit_until(end):
        d = f[f.Usable & (f.Week < end)]
        age = (end - d.Week).dt.days / 7
        return Model(kind, feats).fit(d, d.y.to_numpy(), 0.5 ** (age.to_numpy() / HALF_LIFE))
    inner = origin - pd.Timedelta(weeks=H)
    m0 = fit_until(inner)
    fc = recursive(m0, f, inner, H)
    act = f[(f.Week >= inner) & (f.Week < origin)].groupby("Code").Units.sum()
    pr = fc.groupby("Code").Pred.sum()
    j = pd.concat([act, pr], axis=1).dropna()
    cal = float(np.clip(j.Units.sum() / max(j.Pred.sum(), 1e-9), CAL_CLIP[0], CAL_CLIP[1]))
    m = fit_until(origin)
    m.cal = cal
    return m


FEED = False       # E2 test: recursive (predictions feed the lags) drifted (+19% bias at the Oct 2025 origin); frozen lags won


def recursive(model, f, origin, horizon):
    """week-by-week forecast from origin, inputs frozen at the origin, demand lags fed by earlier predictions"""
    hist = f[f.Week < origin]
    last = hist.sort_values("Week").groupby("Code").tail(1).set_index("Code")
    recent = hist[hist.Week >= origin - pd.Timedelta(weeks=13)]
    alive = last.index[last.Week >= origin - pd.Timedelta(weeks=4)]            # sold in the last 4 weeks
    last = last.loc[alive]
    if last.empty:
        return pd.DataFrame(columns=["Code", "Week", "h", "Pred"])
    U = hist[hist.Code.isin(alive)].pivot_table(index="Code", columns="Week", values="Units", aggfunc="sum")
    U = U.reindex(index=last.index, columns=pd.date_range(U.columns.min(), origin - pd.Timedelta(weeks=1), freq="7D"))
    sub = last.SubGroup.astype(str)
    rel = recent.groupby("Code")[["ln_Relative_Price", "ln_Category_Price_Index"]].median().reindex(alive)
    weeks = pd.date_range(origin, periods=horizon, freq="7D")
    cal = calendar(weeks)
    out = []
    for h, wk in enumerate(weeks):
        X = last.copy()
        hv = U.to_numpy(float)
        def lag(k):
            return np.log1p(hv[:, -k]) if hv.shape[1] >= k else np.full(len(X), np.nan)
        X["ln_Units_Lag1"], X["ln_Units_Lag2"], X["ln_Units_Lag4"] = lag(1), lag(2), lag(4)
        X["ln_Units_Lag52"] = lag(52)
        r4 = np.nanmean(hv[:, -4:], axis=1); r13 = np.nanmean(hv[:, -13:], axis=1)
        X["ln_Units_Roll4"], X["ln_Units_Roll13"] = np.log1p(r4), np.log1p(r13)
        X["Units_Trend_13w"] = X.ln_Units_Roll4 - X.ln_Units_Roll13
        X["No_Sales_Lag1"] = (np.nan_to_num(hv[:, -1]) <= 0).astype(float)
        cat = pd.Series(np.nan_to_num(hv[:, -1]), index=X.index).groupby(sub).transform("sum")
        X["ln_Category_Demand_Lag1"] = np.log1p(cat)
        X["Weeks_Selling"] = last.Weeks_Selling + h + 1
        X["Trend_Weeks"] = last.Trend_Weeks + h + 1
        for c in cal.columns:
            X[c] = cal.loc[wk, c]
        # today's regular price: no markdown, no step, relative price at its recent level
        X["ln_Price_vs_Usual"] = 0.0; X["Price_Above_Usual"] = 0.0; X["Price_Below_Usual"] = 0.0; X["dln_Price_1w"] = 0.0
        X["Markdown_Week"] = 0.0; X["Transition_Week"] = 0.0
        X["ln_Relative_Price"], X["ln_Category_Price_Index"] = rel.ln_Relative_Price.fillna(0), rel.ln_Category_Price_Index.fillna(0)
        X = X.fillna(MEDIANS).fillna(0)                 # same fill as in training
        yhat = model.predict(X)
        pred = np.expm1(yhat + X.ln_Units_Roll13.to_numpy()).clip(min=0) * getattr(model, "cal", 1.0)
        if FEED:                                        # frozen mode: lags keep using the history up to the origin
            U[wk] = pred
        out.append(pd.DataFrame({"Code": X.index, "Week": wk, "h": h + 1, "Pred": pred}))
    return pd.concat(out, ignore_index=True)


def seasonal_path(cw, sc, origin, horizon, level="chain", sku_override=False):
    """index per SKU and step: units per store in the analog years at origin+h vs their 13 weeks before origin"""
    d = cw.copy()
    d["UpS"] = d.Units / d.Stores_Open
    d["grp"] = "All" if level == "chain" else d.Code.map(sc.MainGroup)
    paths = []
    for back in (1, 2):
        o = origin - pd.Timedelta(weeks=52 * back)
        if o - pd.Timedelta(weeks=13) < pd.Timestamp("2024-01-01"):
            continue
        g = d[(d.Week >= o - pd.Timedelta(weeks=13)) & (d.Week < o + pd.Timedelta(weeks=horizon))]
        gw = g.groupby(["grp", "Week"]).UpS.sum().unstack()
        base = gw.loc[:, gw.columns < o].mean(axis=1)
        fut = gw.loc[:, gw.columns >= o]
        fut.columns = range(1, fut.shape[1] + 1)
        paths.append(fut.div(base, axis=0))
        if sku_override:
            s = g.pivot_table(index="Code", columns="Week", values="UpS", aggfunc="sum")
            sb = s.loc[:, s.columns < o].mean(axis=1)
            sf = s.loc[:, s.columns >= o]
            sf.columns = range(1, sf.shape[1] + 1)
            paths.append(("sku", back, sf.div(sb, axis=0)))
    grp_paths = [p for p in paths if not isinstance(p, tuple)]
    if not grp_paths:
        return None
    gp = sum(p.reindex(columns=range(1, horizon + 1)) for p in grp_paths) / len(grp_paths)
    gp = gp.T.ffill().T.fillna(1.0)
    codes = cw.Code.unique()
    key = pd.Series("All", index=codes) if level == "chain" else pd.Series(codes, index=codes).map(sc.MainGroup)
    idx = gp.reindex(key.values).set_axis(codes)
    if sku_override:
        sk = [p[2] for p in paths if isinstance(p, tuple)]
        if len(sk) == 2:
            a, b = sk[0].reindex(columns=range(1, horizon + 1)), sk[1].reindex(columns=range(1, horizon + 1))
            common = a.index.intersection(b.index)
            a, b = a.loc[common], b.loc[common]
            corr = pd.Series([np.corrcoef(np.nan_to_num(a.loc[c]), np.nan_to_num(b.loc[c]))[0, 1] if a.loc[c].notna().sum() > 6 and b.loc[c].notna().sum() > 6 else np.nan
                              for c in common], index=common)
            rep = corr.index[corr > 0.6]
            avg = ((a.loc[rep] + b.loc[rep]) / 2).clip(0.2, 5)
            idx.loc[rep] = avg.reindex(columns=idx.columns).fillna(1.0).values
    return idx


def benchmarks(cw, sc, origin, horizon):
    h = cw[cw.Week < origin]
    l13 = h[h.Week >= origin - pd.Timedelta(weeks=13)].groupby("Code").Units.mean()
    alive = h[h.Week >= origin - pd.Timedelta(weeks=4)].Code.unique()
    l13 = l13.reindex(alive).fillna(0)
    weeks = pd.date_range(origin, periods=horizon, freq="7D")
    res = {}
    res["B1 last-13-week avg"] = pd.DataFrame({c: l13 for c in range(1, horizon + 1)})
    for name, lev, ov in [("B2 x chain path", "chain", False), ("B2 x MainGroup path", "main", False), ("B2 x chain path + SKU override", "chain", True)]:
        p = seasonal_path(cw, sc, origin, horizon, lev, ov)
        res[name] = res["B1 last-13-week avg"] * (p.reindex(alive).fillna(1.0).values if p is not None else 1.0)
    # B3: same week last year x trend (last 13 weeks vs the same 13 weeks last year)
    ly = cw.pivot_table(index="Code", columns="Week", values="Units", aggfunc="sum").reindex(alive)
    lyw = [w - pd.Timedelta(weeks=52) for w in weeks]
    l13ly = ly.loc[:, [c for c in ly.columns if origin - pd.Timedelta(weeks=65) <= c < origin - pd.Timedelta(weeks=52)]].mean(axis=1)
    tr = (l13 / l13ly).replace([np.inf, -np.inf], np.nan).clip(0.3, 3).fillna(1.0)
    b3 = ly.reindex(columns=lyw).set_axis(range(1, horizon + 1), axis=1).mul(tr, axis=0)
    res["B3 last year x trend"] = b3.fillna(res["B1 last-13-week avg"])
    return {k: v.stack().rename("Pred").reset_index().rename(columns={"level_0": "Code", "level_1": "h"}).assign(
        Week=lambda d: origin + pd.to_timedelta((d.h - 1) * 7, unit="D")) for k, v in res.items()}


def metrics(fc, cw, sc):
    act = cw[["Code", "Week", "Units"]]
    j = fc.merge(act, on=["Code", "Week"], how="left").fillna({"Units": 0})
    j["Month"] = j.Week.dt.to_period("M")
    w = np.abs(j.Units - j.Pred).sum() / j.Units.sum() * 100
    m = j.groupby(["Code", "Month"])[["Units", "Pred"]].sum()
    wm = np.abs(m.Units - m.Pred).sum() / m.Units.sum() * 100
    q = j.groupby("Code")[["Units", "Pred"]].sum()
    wq = np.abs(q.Units - q.Pred).sum() / q.Units.sum() * 100
    bias = (j.Pred.sum() / j.Units.sum() - 1) * 100
    a = j[j.Code.map(sc.ABC) == "A"]
    wa = np.abs(a.Units - a.Pred).sum() / max(a.Units.sum(), 1) * 100
    return {"WAPE_SKU_week": w, "WAPE_SKU_month": wm, "WAPE_SKU_13w": wq, "Bias_%": bias, "WAPE_SKU_week_classA": wa}


def main():
    t0 = time.time()
    f, cw, sc = load()
    rows, store = [], {}
    cache = CL / "_baseline_e1_cache.pkl"
    if cache.exists():
        rows, store, e2_cached = pd.read_pickle(cache)
    # ---- E1 model types on the recent origins
    for origin in (MODEL_ORIGINS if not rows else []):
        for kind in ["Linear", "LightGBM", "XGBoost", "CatBoost", "Random Forest"]:
            tt = time.time()
            m = train(kind, f, origin, feats_for(kind))
            fc = recursive(m, f, origin, H)
            store[(kind, origin)] = fc
            rows.append({"Origin": origin.date(), "Method": kind, **metrics(fc, cw, sc), "Calibration": m.cal, "Seconds": round(time.time() - tt)})
            print(rows[-1], flush=True)
    e1 = pd.DataFrame(rows)
    # E2 design test: recursive vs frozen demand lags (LightGBM)
    global FEED
    e2 = [] if not cache.exists() else e2_cached
    for origin in (MODEL_ORIGINS if not e2 else []):
        for feed in (True, False):
            FEED = feed
            m = train("LightGBM", f, origin, feats_for("LightGBM"))
            e2.append({"Origin": origin.date(), "Mode": "recursive (lags fed by forecasts)" if feed else "frozen lags at origin",
                       **metrics(recursive(m, f, origin, H), cw, sc), "Calibration": m.cal})
    FEED = False
    pd.to_pickle((rows, store, e2), cache)
    e2 = pd.DataFrame(e2)
    print(e2.round(2).to_string(index=False), flush=True)
    champ = e1.groupby("Method").WAPE_SKU_week.mean().drop("Linear", errors="ignore").idxmin()
    print("ML champion:", champ, flush=True)

    # ---- E1 structure test (latest model origin): global vs per MainGroup vs per SKU
    o = MODEL_ORIGINS[-1]
    struct = [{"Structure": f"One global {champ}", **metrics(store[(champ, o)], cw, sc)}]
    parts = []
    for mg, codes in sc.groupby("MainGroup").groups.items():
        sub = f[f.Code.isin(codes)]
        if sub[sub.Usable & (sub.Week < o)].shape[0] < 3000:
            continue
        m = train("LightGBM", sub, o, feats_for("LightGBM"))
        parts.append(recursive(m, sub, o, H))
    struct.append({"Structure": "One LightGBM per MainGroup", **metrics(pd.concat(parts), cw, sc)})
    lin_own = ["ln_Units_Lag1", "ln_Units_Lag2", "ln_Units_Lag4", "ln_Units_Roll4", "Week_Sin", "Week_Cos", "Christmas_Season", "Payday_Week"]
    per_sku = []
    usable = f[f.Usable & (f.Week < o)]
    for code, g in usable.groupby("Code"):
        if len(g) < 30:
            continue
        m = Model("Linear", lin_own).fit(g, g.y.to_numpy(), np.ones(len(g)))
        fc_ = recursive(m, f[f.Code == code], o, H)
        if len(fc_):
            per_sku.append(fc_)
    struct.append({"Structure": "One small model per SKU (own lags)", **metrics(pd.concat(per_sku), cw, sc)})
    struct = pd.DataFrame(struct)
    print(struct.round(2).to_string(index=False), flush=True)

    # ---- E3 / E4 benchmark over 7 origins
    bench = []
    errs = []
    for origin in ORIGINS:
        b = benchmarks(cw, sc, origin, H)
        m = train(champ, f, origin, feats_for(champ)) if (champ, origin) not in store else None
        ml = store.get((champ, origin)) if m is None else recursive(m, f, origin, H)
        b[f"ML {champ}"] = ml
        best_b2 = "B2 x chain path"
        for k, v in b.items():
            bench.append({"Origin": origin.date(), "Method": k, **metrics(v, cw, sc)})
        for w in (0.3, 0.5):
            for b2name in ["B2 x chain path", "B2 x MainGroup path", "B2 x chain path + SKU override"]:
                j = b[b2name].merge(ml, on=["Code", "Week"], how="left", suffixes=("", "_ml"))
                j["Pred"] = (1 - w) * j.Pred + w * j.Pred_ml.fillna(j.Pred)
                bench.append({"Origin": origin.date(), "Method": f"Blend {int(w * 100)}% ML + {b2name}", **metrics(j[["Code", "Week", "h", "Pred"]], cw, sc)})
        print(origin.date(), "done", round(time.time() - t0), "s", flush=True)
    bench = pd.DataFrame(bench)
    summ = bench.groupby("Method").agg(Mean_WAPE_week=("WAPE_SKU_week", "mean"), SD_WAPE_week=("WAPE_SKU_week", "std"),
                                       Mean_WAPE_month=("WAPE_SKU_month", "mean"), Mean_WAPE_13w=("WAPE_SKU_13w", "mean"),
                                       Mean_abs_bias=("Bias_%", lambda x: x.abs().mean()), Mean_WAPE_classA=("WAPE_SKU_week_classA", "mean"))
    wins = bench.loc[bench.groupby("Origin").WAPE_SKU_week.idxmin()].Method.value_counts()
    summ["Best_in_origins"] = wins.reindex(summ.index).fillna(0).astype(int)
    summ = summ.sort_values("Mean_WAPE_week")
    winner = summ.index[0]
    print(summ.round(2).to_string(), "\nwinner:", winner, flush=True)

    # ---- E5 final 52-week forecast from 9 Nov 2026
    h52 = 52
    b = benchmarks(cw, sc, FINAL_ORIGIN, h52)
    if winner.startswith("Blend"):
        wgt = int(winner.split("%")[0].split()[-1]) / 100
        b2name = winner.split("ML + ")[1]
    elif winner.startswith("ML"):
        wgt, b2name = 1.0, "B2 x chain path"
    else:
        wgt, b2name = 0.0, winner
    base = b[b2name] if b2name in b else b["B2 x chain path"]
    if wgt > 0:
        m = train(champ, f, FINAL_ORIGIN, feats_for(champ))
        ml = recursive(m, f, FINAL_ORIGIN, 26)
        base = base.merge(ml[["Code", "Week", "Pred"]], on=["Code", "Week"], how="left", suffixes=("", "_ml"))
        # ML weight as tested for weeks 1-13, tapering to 0 by week 26 (ML not tested beyond 13 weeks)
        taper = np.where(base.h <= 13, wgt, np.where(base.h <= 26, wgt * (26 - base.h) / 13, 0))
        base["Pred"] = (1 - taper) * base.Pred + taper * base.Pred_ml.fillna(base.Pred)
        base = base.drop(columns="Pred_ml")
    # ranges from back-test errors of the winner by horizon block (SKU-week log ratio)
    err = []
    for origin in ORIGINS:
        bb = benchmarks(cw, sc, origin, H)
        j = bb[b2name].merge(cw[["Code", "Week", "Units"]], on=["Code", "Week"], how="left").fillna({"Units": 0})
        j["lr"] = np.log1p(j.Units) - np.log1p(j.Pred)
        j["ABC"] = j.Code.map(sc.ABC)
        err.append(j.assign(Origin=origin))
    err = pd.concat(err)
    q = err.groupby("ABC").lr.quantile([0.1, 0.9]).unstack()
    last_o = err[err.Origin == ORIGINS[-1]]
    cov_q = err[err.Origin < ORIGINS[-1]].groupby("ABC").lr.quantile([0.1, 0.9]).unstack()
    lo, hi = last_o.ABC.map(cov_q[0.1]), last_o.ABC.map(cov_q[0.9])
    coverage = float(((last_o.lr >= lo) & (last_o.lr <= hi)).mean() * 100)
    base["ABC"] = base.Code.map(sc.ABC)
    widen = np.sqrt(base.h / 13).clip(1, 1.5)                               # back-tested over 13 weeks; at most 1.5x wider by week 52
    base["Low"] = (np.expm1(np.log1p(base.Pred) + base.ABC.map(q[0.1]) * widen.clip(lower=1))).clip(lower=0)
    base["High"] = np.expm1(np.log1p(base.Pred) + base.ABC.map(q[0.9]) * widen.clip(lower=1))
    base["Method"] = winner
    base = base.drop(columns="ABC")
    base.to_parquet(CL / "baseline_forecast.parquet", index=False)

    # ---- E6 explainability on the LightGBM model at the latest origin
    lg = train("LightGBM", f, MODEL_ORIGINS[-1], feats_for("LightGBM"))
    imp = pd.Series(lg.m.booster_.feature_importance("gain"), index=lg.m.booster_.feature_name()).sort_values(ascending=False)
    imp = (imp / imp.sum() * 100).round(2)
    sample = f[f.Usable & (f.Week >= MODEL_ORIGINS[-1] - pd.Timedelta(weeks=26)) & (f.Week < MODEL_ORIGINS[-1])].sample(20000, random_state=SEED)
    try:
        import shap
        sv = shap.TreeExplainer(lg.m).shap_values(sample[lg.feats + ["SubGroup"]])
        shap_imp = pd.Series(np.abs(sv).mean(0), index=lg.feats + ["SubGroup"]).sort_values(ascending=False)
        shap_imp = (shap_imp / shap_imp.sum() * 100).round(2)
    except Exception as e:
        shap_imp = pd.Series({"SHAP failed": str(e)[:80]})
    base_pred = lg.predict(sample)
    perm = {}
    rng = np.random.default_rng(SEED)
    act = sample.Units.to_numpy()
    def wp(p):
        return np.abs(act - np.expm1(p + sample.ln_Units_Roll13.to_numpy()).clip(min=0)).sum() / act.sum() * 100
    w0 = wp(base_pred)
    for c in lg.feats:
        s2 = sample.copy(); s2[c] = rng.permutation(s2[c].to_numpy())
        perm[c] = wp(lg.predict(s2)) - w0
    perm = pd.Series(perm).sort_values(ascending=False).round(2)
    # price partial dependence -> implied elasticity, compared with phase D
    el = pd.read_parquet(CL / "elasticity.parquet").set_index("Code") if (CL / "elasticity.parquet").exists() else None
    pdp = []
    s3 = sample.drop_duplicates("Code").head(800)
    for dp in (-0.10, 0.10):
        s4 = s3.copy(); s4["ln_Price_vs_Usual"] = np.log(1 + dp); s4["Price_Above_Usual"] = max(np.log(1 + dp), 0); s4["Price_Below_Usual"] = min(np.log(1 + dp), 0)
        s4["ln_Relative_Price"] = s3.ln_Relative_Price + np.log(1 + dp)
        pdp.append(lg.predict(s4))
    impl = pd.Series((pdp[1] - pdp[0]) / (np.log(1.1) - np.log(0.9)), index=s3.Code)
    pdp_cmp = pd.DataFrame({"ML_implied": impl})
    if el is not None:
        pdp_cmp["PhaseD"] = el.Elasticity.reindex(pdp_cmp.index)
    corr = pdp_cmp.corr().iloc[0, 1] if el is not None else np.nan

    # ---- outputs
    fut = base.groupby(base.Week.dt.to_period("M")).agg(Units=("Pred", "sum"), Low=("Low", "sum"), High=("High", "sum"))
    with pd.ExcelWriter(OUT / "baseline.xlsx") as xw:
        pd.DataFrame({"Item": ["ML champion (E1)", "Benchmark winner (E3/E4)", "ML weight in final (weeks 1-13, taper to 26)", "Seasonal path used",
                               "Final origin", "Horizon (weeks)", "SKUs forecast", "80% range coverage on the latest origin %",
                               "ML implied price slope vs phase D (corr)", "Run time (min)"],
                      "Value": [champ, winner, wgt, b2name, str(FINAL_ORIGIN.date()), h52, base.Code.nunique(), round(coverage, 1),
                                round(corr, 2) if corr == corr else "n/a", round((time.time() - t0) / 60, 1)]}).to_excel(xw, sheet_name="Summary", index=False)
        e1.round(2).to_excel(xw, sheet_name="E1 model types", index=False)
        e2.round(2).to_excel(xw, sheet_name="E2 recursive vs frozen", index=False)
        struct.round(2).to_excel(xw, sheet_name="E1 global vs cluster vs SKU", index=False)
        summ.round(2).to_excel(xw, sheet_name="E3-E4 benchmark")
        bench.round(2).to_excel(xw, sheet_name="E3 by origin", index=False)
        q.round(3).to_excel(xw, sheet_name="E5 range quantiles")
        fut.round(0).to_excel(xw, sheet_name="E5 forecast by month")
        pd.DataFrame({"Gain_%": imp}).to_excel(xw, sheet_name="E6 gain importance")
        pd.DataFrame({"SHAP_%": shap_imp}).to_excel(xw, sheet_name="E6 SHAP")
        pd.DataFrame({"WAPE_increase_pts": perm}).to_excel(xw, sheet_name="E6 permutation")
        pdp_cmp.round(3).to_excel(xw, sheet_name="E6 price PDP vs D")
    print(f"coverage {coverage:.1f}% | ML price slope vs D corr {corr:.2f} | {base.Code.nunique()} SKUs | {(time.time() - t0) / 60:.1f} min")
    print(fut.round(0).head(14).to_string())


if __name__ == "__main__":
    main()
