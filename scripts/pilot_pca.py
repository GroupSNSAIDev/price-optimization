"""Step 7 · Dimensionality reduction (PCA) for the pilot, kept only if it improves forecasts

  A  macro block   : FX, inflation YoY/MoM, Brent, GDP -> principal components (fit on training weeks)
  B  store profiles: size, age, productivity, margin, price premium, category mix, import share
                     -> PCA -> k-means store segments
  C  product profiles (40 SKUs): elasticity, margin, volume, volatility, price activity, store reach, import
                     -> PCA -> k-means product segments
  D  gain check    : add each block to the tree (LightGBM) and linear (ridge) models selected in step 6,
                     same 5 rolling folds; keep a block only if CV WAPE improves by >= 0.2 pt.
Profiles use the training period only (to Mar 2026). Components kept: cumulative explained variance >= 90%
(macro) / >= 80% (profiles, then k-means on those components, k by silhouette).
Outputs: analysis/pilot/pca.xlsx, pca_decision.json, charts; clean/pilot/store_segments.parquet,
product_segments.parquet.
"""
import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from pilot_feature_selection import FOLDS, cv_wape, cv_wape_linear, prepare

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, AN = ROOT / "clean", ROOT / "analysis"
OUT = AN / "pilot"
TRAIN_END = "2026-03"
SEL = json.load(open(OUT / "selected_features.json"))
GAIN_MIN = 0.2
C1, C2, INK = "#156082", "#E97132", "#0E2841"


def pca_block(X, threshold):
    sc = StandardScaler().fit(X)
    p = PCA().fit(sc.transform(X))
    n = int(np.searchsorted(np.cumsum(p.explained_variance_ratio_), threshold) + 1)
    p_n = PCA(n_components=n).fit(sc.transform(X))
    load = pd.DataFrame(p_n.components_.T, index=X.columns, columns=[f"PC{i + 1}" for i in range(n)])
    var = pd.DataFrame({"Component": [f"PC{i + 1}" for i in range(len(p.explained_variance_ratio_))],
                        "Explained_%": p.explained_variance_ratio_ * 100,
                        "Cumulative_%": np.cumsum(p.explained_variance_ratio_) * 100})
    return sc, p_n, n, load, var


def kmeans_best(Z, ks=range(3, 7)):
    res = {k: KMeans(k, n_init=20, random_state=0).fit(Z) for k in ks}
    sil = {k: silhouette_score(Z, m.labels_) for k, m in res.items()}
    k = max(sil, key=sil.get)
    return res[k], k, sil


# ------------------------------------------------------------------ A macro
def macro_block():
    m = pd.read_parquet(CL / "macro_monthly.parquet")
    m = m[m.Month <= TRAIN_END].copy()
    m["GDP_Real_YoY_Pct_Q"] = m.GDP_Real_YoY_Pct_Q.ffill()
    X = pd.DataFrame({"ln_FX_BNA": np.log(m.FX_BNA_Avg), "Inflation_YoY": m.Inflation_YoY_Pct,
                      "Inflation_MoM": m.Inflation_MoM_Pct, "ln_Brent": np.log(m.Brent_USD),
                      "GDP_Growth": m.GDP_Real_YoY_Pct_Q}).dropna()
    sc, p, n, load, var = pca_block(X, .90)
    return sc, p, n, load, var, X.corr()


# ------------------------------------------------------------------ B stores
def store_profiles():
    p = pd.read_parquet(CL / "panel_monthly.parquet", columns=[
        "Month", "Plant", "Store_Name", "Channel", "Total_Sqm", "Open_Date", "Has_Sales", "KZ_NetsSales", "KZ_COGS",
        "MainGroup", "ArticleCode", "Relative_Price"])
    p = p[p.Has_Sales & (p.Month <= TRAIN_END) & p.Channel.eq("STORE")]
    art = pd.read_parquet(CL / "dim_article.parquet", columns=["ArticleCode", "PurchaseType"])
    p = p.merge(art, on="ArticleCode", how="left")
    g = p.groupby("Plant")
    s = pd.DataFrame({"Store_Name": g.Store_Name.first(), "Sqm": g.Total_Sqm.first(),
                      "Months": g.Month.nunique(), "Net": g.KZ_NetsSales.sum(), "COGS": g.KZ_COGS.sum()})
    s = s[s.Months >= 6]
    s["ln_Sqm"] = np.log(s.Sqm)
    s["Age_Months"] = ((pd.Timestamp("2026-03-31") - g.Open_Date.first()).dt.days / 30.44).reindex(s.index)
    last6 = p[p.Month > "2025-09"].groupby("Plant").KZ_NetsSales.sum() / 6
    s["ln_Sales_per_Sqm"] = np.log((last6 / s.Sqm).reindex(s.index))
    s["Margin_Pct"] = (1 - s.COGS / s.Net) * 100
    rp = p.dropna(subset=["Relative_Price"])
    s["Price_Level"] = np.exp(np.log(rp.Relative_Price).groupby(rp.Plant).mean()).reindex(s.index)
    s["Import_Share"] = (p[p.PurchaseType.eq("Import")].groupby("Plant").KZ_NetsSales.sum() / s.Net) * 100
    mix = p.groupby(["Plant", "MainGroup"]).KZ_NetsSales.sum().unstack(fill_value=0)
    top = mix.sum().nlargest(8).index
    mix = mix[top].div(mix.sum(axis=1), axis=0) * 100
    mix.columns = [f"Mix_{c.title().replace(' ', '_')}" for c in mix.columns]
    s = s.join(mix)
    s["Articles_Sold"] = g.ArticleCode.nunique().reindex(s.index)
    cols = ["ln_Sqm", "Age_Months", "ln_Sales_per_Sqm", "Margin_Pct", "Price_Level", "Import_Share",
            "Articles_Sold"] + list(mix.columns)
    s = s.dropna(subset=cols)
    sc, pca, n, load, var = pca_block(s[cols], .80)
    Z = pca.transform(sc.transform(s[cols]))
    km, k, sil = kmeans_best(Z)
    s[[f"PC{i + 1}" for i in range(n)]] = Z
    s["Store_Segment"] = km.labels_
    return s.reset_index(), cols, n, load, var, k, sil


# ------------------------------------------------------------------ C products
def product_profiles(f):
    tr = f[f.Split == "train"] if "Split" in f else f
    g = tr.groupby("ArticleCode")
    e = pd.read_parquet(AN / "article_elasticity.parquet").set_index("ArticleCode")
    wk = tr.groupby(["ArticleCode", "Week"]).Units.sum()
    d = pd.DataFrame({
        "ArticleName": g.ArticleName.first(), "Pilot_Group": g.Pilot_Group.first(),
        "Elasticity": e.Elasticity.reindex(g.size().index),
        "Margin_Pct": g.Margin_Pct_Lag1.median(),
        "ln_Weekly_Units": np.log(wk.groupby(level=0).mean()),
        "Volatility_CV": wk.groupby(level=0).std() / wk.groupby(level=0).mean(),
        "Price_Change_Freq": g.dln_Price_1w.apply(lambda x: (x.abs() > .03).mean() * 100),
        "Temp_Cut_Share": g.Temp_Price_Cut.mean() * 100,
        "Store_Reach": g.Plant.nunique(),
        "Imported": g.Imported.max(),
        "Relative_Price": np.exp(g.ln_Relative_Price.mean()),
        "Trend": g.Units_Trend_13w.mean()})
    cols = ["Elasticity", "Margin_Pct", "ln_Weekly_Units", "Volatility_CV", "Price_Change_Freq", "Temp_Cut_Share",
            "Store_Reach", "Imported", "Relative_Price", "Trend"]
    d = d.dropna(subset=cols)
    sc, pca, n, load, var = pca_block(d[cols], .80)
    Z = pca.transform(sc.transform(d[cols]))
    km, k, sil = kmeans_best(Z, range(3, 6))
    d[[f"PC{i + 1}" for i in range(n)]] = Z
    d["Product_Segment"] = km.labels_
    return d.reset_index(), cols, n, load, var, k, sil


# ------------------------------------------------------------------ D gain check
def add_blocks(f, lin, msc, mpca, mn, stores, sn, prods, pn):
    for df in (f, lin):
        X = df[["ln_FX_BNA", "Inflation_YoY", "Inflation_MoM", "ln_Brent", "GDP_Growth"]]
        Z = mpca.transform(msc.transform(X))
        for i in range(mn):
            df[f"Macro_PC{i + 1}"] = Z[:, i]
        sm = stores.set_index("Plant")
        for i in range(sn):
            df[f"Store_PC{i + 1}"] = df.Plant.map(sm[f"PC{i + 1}"])
        df["Store_Segment"] = df.Plant.map(sm.Store_Segment)
        pm = prods.set_index("ArticleCode")
        for i in range(pn):
            df[f"Product_PC{i + 1}"] = df.ArticleCode.map(pm[f"PC{i + 1}"])
        df["Product_Segment"] = df.ArticleCode.map(pm.Product_Segment)
    return f, lin


def main():
    f, lin, _ = prepare()                      # training period, same preparation as step 6
    feat = pd.read_parquet(CL / "pilot" / "pilot_features.parquet")
    feat = feat[feat.Split == "train"]

    msc, mpca, mn, mload, mvar, mcorr = macro_block()
    stores, scols, sn, sload, svar, sk, ssil = store_profiles()
    prods, pcols, pn, pload, pvar, pk, psil = product_profiles(feat)
    print(f"macro: {mn} PCs ({mvar['Cumulative_%'].iloc[mn - 1]:.0f}%) | stores: {len(stores)} -> {sn} PCs, "
          f"{sk} segments | products: {len(prods)} -> {pn} PCs, {pk} segments", flush=True)

    f, lin = add_blocks(f, lin, msc, mpca, mn, stores, sn, prods, pn)
    for df in (f, lin):        # stores / SKUs without a profile (opened late, short history) -> segment -1, PCs 0
        for c in [c for c in df.columns if c.startswith(("Store_PC", "Product_PC"))]:
            df[c] = df[c].fillna(0)
        df["Store_Segment"] = df.Store_Segment.fillna(-1)
        df["Product_Segment"] = df.Product_Segment.fillna(-1)
    seg_dummies = []
    for col in ["Store_Segment", "Product_Segment"]:
        for v in sorted(lin[col].unique())[1:]:
            name = f"{col}_{int(v)}"
            lin[name] = (lin[col] == v).astype(int)
            f[name] = (f[col] == v).astype(int)
            seg_dummies.append(name)

    macro_pcs = [f"Macro_PC{i + 1}" for i in range(mn)]
    store_pcs = [f"Store_PC{i + 1}" for i in range(sn)]
    prod_pcs = [f"Product_PC{i + 1}" for i in range(pn)]
    tree0, lin0 = SEL["tree_features"], SEL["linear_features"]
    lin_nomacro = [c for c in lin0 if c not in ("Inflation_YoY",)]
    tests = [
        ("Tree", "Selected set (baseline)", tree0),
        ("Tree", "+ macro PCs", tree0 + macro_pcs),
        ("Tree", "+ store PCs", tree0 + store_pcs),
        ("Tree", "+ store segment", tree0 + ["Store_Segment"]),
        ("Tree", "+ product PCs", tree0 + prod_pcs),
        ("Tree", "+ product segment", tree0 + ["Product_Segment"]),
        ("Linear", "Selected set (baseline)", lin0),
        ("Linear", "macro PCs instead of inflation", lin_nomacro + macro_pcs),
        ("Linear", "+ store PCs", lin0 + store_pcs),
        ("Linear", "+ store segments", lin0 + [c for c in seg_dummies if c.startswith("Store")]),
        ("Linear", "+ product PCs", lin0 + prod_pcs),
        ("Linear", "+ product segments", lin0 + [c for c in seg_dummies if c.startswith("Product")]),
    ]
    rows = []
    for fam, name, cols in tests:
        cols = list(dict.fromkeys(cols))
        r = cv_wape(f, cols) if fam == "Tree" else cv_wape_linear(lin, cols)
        rows.append({"Model": fam, "Test": name, "Features": len(cols), "CV_WAPE": r})
        print(f"  {fam:6s} {name:34s} {r:.2f}%", flush=True)
    gain = pd.DataFrame(rows)
    gain["Gain_pt"] = gain.groupby("Model").CV_WAPE.transform(lambda x: x.iloc[0]) - gain.CV_WAPE
    gain["Keep"] = gain.Gain_pt >= GAIN_MIN

    decision = {fam: gain[(gain.Model == fam) & gain.Keep].Test.tolist() for fam in ["Tree", "Linear"]}
    final_tree, final_lin = list(tree0), list(lin0)
    block = {"+ macro PCs": macro_pcs, "+ store PCs": store_pcs, "+ store segment": ["Store_Segment"],
             "+ product PCs": prod_pcs, "+ product segment": ["Product_Segment"],
             "+ store segments": [c for c in seg_dummies if c.startswith("Store")],
             "+ product segments": [c for c in seg_dummies if c.startswith("Product")]}
    for t in decision["Tree"]:
        final_tree += block[t]
    for t in decision["Linear"]:
        final_lin = (lin_nomacro + macro_pcs) if t == "macro PCs instead of inflation" else final_lin + block[t]
    final_tree, final_lin = list(dict.fromkeys(final_tree)), list(dict.fromkeys(final_lin))
    print("kept:", decision, flush=True)

    # outputs
    stores.to_parquet(CL / "pilot" / "store_segments.parquet", index=False)
    prods.to_parquet(CL / "pilot" / "product_segments.parquet", index=False)
    seg_s = stores.groupby("Store_Segment")[scols].mean().round(2)
    seg_s.insert(0, "Stores", stores.groupby("Store_Segment").size())
    seg_s["Example_Stores"] = stores.groupby("Store_Segment").Store_Name.apply(
        lambda x: ", ".join(s.replace(" FRESMART", "").replace(" EXPRESS", "").title() for s in x.head(4)))
    seg_p = prods.groupby("Product_Segment")[pcols].mean().round(2)
    seg_p.insert(0, "SKUs", prods.groupby("Product_Segment").size())
    seg_p["SKUs_List"] = prods.groupby("Product_Segment").ArticleName.apply(lambda x: "; ".join(str(n).title()[:28] for n in x))
    with pd.ExcelWriter(OUT / "pca.xlsx") as xw:
        gain.round(2).to_excel(xw, sheet_name="Gain check", index=False)
        pd.DataFrame({"Block": ["Macro", "Store profiles", "Product profiles"],
                      "Inputs": [5, len(scols), len(pcols)], "Rows": [len(mcorr), len(stores), len(prods)],
                      "Components kept": [mn, sn, pn],
                      "Variance explained %": [mvar["Cumulative_%"].iloc[mn - 1], svar["Cumulative_%"].iloc[sn - 1],
                                               pvar["Cumulative_%"].iloc[pn - 1]],
                      "Segments (k-means)": ["–", sk, pk],
                      "Silhouette": ["–", round(ssil[sk], 3), round(psil[pk], 3)],
                      "Kept for trees": ["+ macro PCs" in decision["Tree"],
                                         any("store" in t for t in decision["Tree"]),
                                         any("product" in t for t in decision["Tree"])],
                      "Kept for linear": ["macro PCs instead of inflation" in decision["Linear"],
                                          any("store" in t for t in decision["Linear"]),
                                          any("product" in t for t in decision["Linear"])]}
                     ).round(2).to_excel(xw, sheet_name="Summary", index=False)
        mcorr.round(3).to_excel(xw, sheet_name="A Macro correlation")
        mvar.round(2).to_excel(xw, sheet_name="A Macro variance", index=False)
        mload.round(3).to_excel(xw, sheet_name="A Macro loadings")
        svar.round(2).to_excel(xw, sheet_name="B Store variance", index=False)
        sload.round(3).to_excel(xw, sheet_name="B Store loadings")
        seg_s.to_excel(xw, sheet_name="B Store segments")
        stores.drop(columns=["Net", "COGS"]).round(3).to_excel(xw, sheet_name="B Store profiles", index=False)
        pvar.round(2).to_excel(xw, sheet_name="C Product variance", index=False)
        pload.round(3).to_excel(xw, sheet_name="C Product loadings")
        seg_p.to_excel(xw, sheet_name="C Product segments")
        prods.round(3).to_excel(xw, sheet_name="C Product profiles", index=False)
    json.dump({"tree_features": final_tree, "linear_features": final_lin, "kept_blocks": decision,
               "macro_components": mn, "store_components": sn, "store_segments": sk,
               "product_components": pn, "product_segments": pk, "gain_threshold_pt": GAIN_MIN},
              open(OUT / "pca_decision.json", "w"), indent=1)

    # charts: scree plots, store and product segment maps
    fig, axs = plt.subplots(1, 3, figsize=(11, 3))
    for ax, (v, title, th) in zip(axs, [(mvar, "Macro block", 90), (svar, "Store profiles", 80),
                                        (pvar, "Product profiles", 80)]):
        ax.bar(range(1, len(v) + 1), v["Explained_%"], color=C1)
        ax.plot(range(1, len(v) + 1), v["Cumulative_%"], color=C2, marker="o", ms=3)
        ax.axhline(th, color=INK, ls="--", lw=.8)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("component")
    axs[0].set_ylabel("variance explained %")
    fig.tight_layout()
    fig.savefig(OUT / "pca_scree.png", dpi=180)
    for d, name, lab in [(stores, "store", "Store_Name"), (prods, "product", "ArticleName")]:
        seg = "Store_Segment" if name == "store" else "Product_Segment"
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.scatter(d.PC1, d.PC2, c=d[seg], cmap="tab10", s=40, alpha=.85)
        for _, r in d.iterrows():
            ax.annotate(str(r[lab]).replace(" FRESMART", "").replace(" EXPRESS", "").title()[:16], (r.PC1, r.PC2),
                        fontsize=5.5, xytext=(3, 2), textcoords="offset points")
        ax.set_xlabel("PC1")
        ax.set_ylabel("PC2")
        ax.set_title(f"{name.title()} segments (k-means on principal components)")
        fig.savefig(OUT / f"pca_{name}_segments.png", dpi=180, bbox_inches="tight")


if __name__ == "__main__":
    main()
