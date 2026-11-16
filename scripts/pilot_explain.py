"""Step 12 · Model explainability for the 40 pilot SKUs (final LightGBM inside the 30/70 baseline blend)

The model predicts weekly units RELATIVE to the store-SKU's recent 13-week level, so explanations answer:
"what pushes this week's demand above or below its normal recent level?"
 12.1 Global drivers     mean |SHAP| per feature and per driver family (price, recent demand, season & calendar,
                         stock, cost, discount, macro)
 12.2 Price effect       SHAP of all price features summed per row; SHAP dependence on price vs usual level
 12.3 Permutation        WAPE increase on Jul-Sep 2026 when each family is shuffled (model-agnostic check)
 12.4 Partial dependence price grid -15%..+15% per SKU: predicted units must fall as price rises; implied slope
                         compared with the step 9 elasticity
 12.5 Per-SKU drivers    share of |SHAP| by family, top 3 drivers with direction, plain-language sentence
 12.6 Local examples     SHAP waterfall for three store-weeks
Outputs: analysis/pilot/explain/*.png, analysis/pilot/explainability.xlsx
"""
import json
import pickle
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap

import pilot_train_eval as T
from pilot_models import PRICE_FEATS, prepare

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "pilot"
EXP = OUT / "explain"
EXP.mkdir(exist_ok=True)
FAMILY = {"Price": PRICE_FEATS, "Discount": ["Discount_Pct"], "Cost": ["ln_Unit_Cost_Real_Lag1"],
          "Recent demand": T.REL_FEATS, "Stock": ["ln_Days_Of_Cover"],
          "Season & calendar": ["Week_Sin", "Holidays_In_Week", "Payday_Week", "Christmas_Season", "December",
                                "Month_Sin", "Month_Cos"],
          "Macro": ["Macro_PC1", "Macro_PC2", "Macro_PC3", "Macro_PC4"]}
fam_of = {c: k for k, v in FAMILY.items() for c in v}
PLAIN = {"ln_Price_Real": "real price level", "ln_Relative_Price": "price vs category",
         "ln_Price_vs_Usual": "price vs its usual level", "Price_Above_Usual": "price above usual",
         "Price_Below_Usual": "price below usual", "dln_Price_1w": "price change this week",
         "Discount_Pct": "discounts", "ln_Unit_Cost_Real_Lag1": "unit cost", "Lag1_rel": "last week's sales",
         "Lag2_rel": "sales 2 weeks ago", "Lag4_rel": "sales 4 weeks ago", "Roll4_rel": "last 4 weeks' trend",
         "EWM_rel": "smoothed recent level", "Weeks_Selling": "weeks on shelf", "ln_Days_Of_Cover": "stock cover",
         "Week_Sin": "time of year", "Holidays_In_Week": "public holidays", "Payday_Week": "payday week",
         "Christmas_Season": "Christmas season", "December": "December", "Month_Sin": "month", "Month_Cos": "month",
         "Macro_PC1": "economy (FX/inflation)", "Macro_PC2": "economy (oil/FX)", "Macro_PC3": "economy (GDP)",
         "Macro_PC4": "economy (other)"}
C = ["#156082", "#E97132", "#196B24", "#A02B93", "#0F9ED5", "#7F8781", "#E8B200"]


def main():
    f, _ = prepare()
    f = T.add_relative(f)
    import __main__
    __main__.Fitted = T.Fitted                     # models were pickled from pilot_train_eval run as __main__
    model = pickle.load(open(OUT / "models_final" / "LightGBM.pkl", "rb"))
    cols = model.cols
    test = f[f.Split == "test"].reset_index(drop=True)
    samp = test.sample(min(20000, len(test)), random_state=0).reset_index(drop=True)
    X = samp[cols]

    # 12.1 SHAP
    expl = shap.TreeExplainer(model.model)
    sv = expl.shap_values(X)
    S = pd.DataFrame(sv, columns=cols)
    glob = pd.DataFrame({"Feature": cols, "Plain": [PLAIN.get(c, c) for c in cols],
                         "Family": [fam_of.get(c, "Other") for c in cols],
                         "Mean_abs_SHAP": np.abs(sv).mean(0)}).sort_values("Mean_abs_SHAP", ascending=False)
    glob["Share_%"] = glob.Mean_abs_SHAP / glob.Mean_abs_SHAP.sum() * 100
    famS = pd.DataFrame({k: S[[c for c in v if c in S]].sum(axis=1) for k, v in FAMILY.items()})
    fam_glob = famS.abs().mean().sort_values(ascending=False)
    fam_glob = (fam_glob / fam_glob.sum() * 100).rename("Share_%")
    print(fam_glob.round(1).to_string(), flush=True)

    # 12.3 permutation importance by family on the test sample (WAPE in units)
    y = np.exp(samp.ln_Units).values
    base_p = model.units(samp)
    wape = lambda p: np.abs(p - y).sum() / y.sum() * 100
    w0 = wape(base_p)
    rng = np.random.default_rng(0)
    perm = []
    for k, v in FAMILY.items():
        Xp = samp.copy()
        idx = rng.permutation(len(Xp))
        for c in [c for c in v if c in cols]:
            Xp[c] = Xp[c].values[idx]
        perm.append({"Family": k, "WAPE_when_shuffled_%": wape(model.units(Xp)), "WAPE_increase_pt": wape(model.units(Xp)) - w0})
    perm = pd.DataFrame(perm).sort_values("WAPE_increase_pt", ascending=False)

    # 12.4 partial dependence on price, per SKU
    e9 = pd.read_parquet(ROOT / "clean" / "pilot" / "sku_elasticity.parquet").set_index("ArticleCode")
    grid = np.linspace(-0.15, 0.15, 13)
    pdp_rows = []
    for a, d in samp.groupby("ArticleCode"):
        d = d.head(400)
        base = model.predict_rel(d)
        curve = []
        for g in grid:
            Xg = d.copy()
            dl = np.log(1 + g)
            for c in ["ln_Price_Real", "ln_Relative_Price", "ln_Price_vs_Usual"]:
                Xg[c] = Xg[c] + dl
            Xg["Price_Above_Usual"], Xg["Price_Below_Usual"] = Xg.ln_Price_vs_Usual.clip(lower=0), \
                Xg.ln_Price_vs_Usual.clip(upper=0)
            curve.append(np.mean(np.exp(model.predict_rel(Xg) - base)))
        curve = np.array(curve)
        slope = np.polyfit(np.log(1 + grid), np.log(curve), 1)[0]
        pdp_rows.append({"ArticleCode": a, "ArticleName": d.ArticleName.iloc[0], "Group": d.Pilot_Group.iloc[0],
                         "Units_at_-10%": curve[np.argmin(abs(grid + .10))] * 100 - 100,
                         "Units_at_+10%": curve[np.argmin(abs(grid - .10))] * 100 - 100,
                         "Monotone_Down": bool(np.all(np.diff(curve) <= 1e-9)), "ML_Slope": slope,
                         "Step9_Elasticity": e9.Elasticity_Final.get(a, np.nan), "_curve": curve})
    pdp = pd.DataFrame(pdp_rows)
    corr = pdp[["ML_Slope", "Step9_Elasticity"]].corr().iloc[0, 1]
    print(f"PDP monotone down: {pdp.Monotone_Down.sum()}/{len(pdp)}; ML slope vs step 9 corr {corr:.2f}", flush=True)

    # 12.5 per-SKU driver shares + plain-language sentence
    famS["ArticleCode"] = samp.ArticleCode.values
    sku_share = famS.drop(columns="ArticleCode").abs().groupby(famS.ArticleCode).mean()
    sku_share = sku_share.div(sku_share.sum(axis=1), axis=0) * 100
    S["ArticleCode"] = samp.ArticleCode.values
    rows = []
    for a, d in S.groupby("ArticleCode"):
        m = d.drop(columns="ArticleCode")
        imp = m.abs().mean().sort_values(ascending=False)
        top = imp.index[:3]
        parts = []
        for c in top:
            corr_sign = np.corrcoef(samp.loc[d.index, c], m[c])[0, 1] if samp.loc[d.index, c].std() > 0 else 0
            direction = "higher" if corr_sign >= 0 else "lower"
            parts.append(f"{PLAIN.get(c, c)} (higher value -> {direction} demand)")
        sh = sku_share.loc[a]
        name = samp[samp.ArticleCode == a].ArticleName.iloc[0]
        sentence = (f"{str(name).title()}: weekly demand moves mainly with "
                    f"{', '.join(f'{k.lower()} {v:.0f}%' for k, v in sh.sort_values(ascending=False).head(3).items())}"
                    f". Top drivers: {'; '.join(parts)}.")
        rows.append({"ArticleCode": a, "ArticleName": name, "Group": samp[samp.ArticleCode == a].Pilot_Group.iloc[0],
                     **{f"{k}_%": sh[k] for k in sh.index}, "Top_1": PLAIN.get(top[0], top[0]),
                     "Top_2": PLAIN.get(top[1], top[1]), "Top_3": PLAIN.get(top[2], top[2]), "Explanation": sentence})
    sku = pd.DataFrame(rows).sort_values(["Group", "ArticleName"])

    # ---- charts
    fig, ax = plt.subplots(figsize=(7, 3.4))
    fg = fam_glob.sort_values()
    ax.barh(fg.index, fg.values, color=C[0])
    for i, v in enumerate(fg.values):
        ax.text(v + .4, i, f"{v:.0f}%", va="center", fontsize=9)
    ax.set_xlabel("share of the model's explanation (mean |SHAP|), Jul-Sep 2026")
    ax.set_title("What moves weekly demand away from its recent level")
    fig.savefig(EXP / "12_1_driver_families.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    plt.figure()
    shap.summary_plot(sv, X.rename(columns=PLAIN), show=False, max_display=15, plot_size=(8, 6))
    plt.title("SHAP summary (each dot = one store-week)")
    plt.savefig(EXP / "12_1_shap_beeswarm.png", dpi=180, bbox_inches="tight")
    plt.close("all")
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    ax.scatter(samp.ln_Price_vs_Usual.clip(-.3, .3) * 100, famS.Price, s=3, alpha=.25, color=C[0])
    ax.axhline(0, color="#4D5751", lw=.8)
    ax.axvline(0, color="#4D5751", lw=.8)
    ax.set_xlabel("price vs the SKU's usual level, %")
    ax.set_ylabel("SHAP of all price features (log units)")
    ax.set_title("Price effect learnt by the model: above usual -> fewer units")
    fig.savefig(EXP / "12_2_price_dependence.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    fig, axs = plt.subplots(2, 4, figsize=(11, 5), sharex=True, sharey=True)
    for ax, (_, r) in zip(axs.flat, pdp.sort_values("Group").groupby("Group").head(2).iterrows()):
        ax.plot(grid * 100, r._curve * 100, color=C[0], lw=2, label="ML")
        ax.plot(grid * 100, (1 + grid) ** r.Step9_Elasticity * 100, color=C[1], lw=1.5, ls="--", label="step 9")
        ax.axhline(100, color="#7F8781", lw=.6)
        ax.axvline(0, color="#7F8781", lw=.6)
        ax.set_title(f"{r.Group} · {str(r.ArticleName).title()[:24]}", fontsize=8)
        ax.tick_params(labelsize=7)
    axs.flat[0].legend(fontsize=7)
    fig.supxlabel("price change %")
    fig.supylabel("units, index (current = 100)")
    fig.tight_layout()
    fig.savefig(EXP / "12_4_partial_dependence.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    pp = perm.sort_values("WAPE_increase_pt")
    ax.barh(pp.Family, pp.WAPE_increase_pt, color=C[2])
    ax.set_xlabel(f"WAPE increase when the family is shuffled (base {w0:.1f}%), points")
    ax.set_title("Permutation importance (model-agnostic check)")
    fig.savefig(EXP / "12_3_permutation.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    ex = [samp[samp.Pilot_Group == g].index[0] for g in ["A", "B", "C"]]
    for i, ix in enumerate(ex):
        plt.figure()
        shap.plots.waterfall(shap.Explanation(values=sv[ix], base_values=expl.expected_value,
                                              data=X.iloc[ix].values, feature_names=[PLAIN.get(c, c) for c in cols]),
                             max_display=10, show=False)
        plt.title(f"{samp.ArticleName[ix].title()[:40]} · store {samp.Plant[ix]} · {samp.Week[ix].date()}", fontsize=9)
        plt.savefig(EXP / f"12_6_waterfall_{i + 1}.png", dpi=170, bbox_inches="tight")
        plt.close("all")

    with pd.ExcelWriter(OUT / "explainability.xlsx") as xw:
        fam_glob.round(2).reset_index().rename(columns={"index": "Family"}).to_excel(xw, sheet_name="Driver families",
                                                                                     index=False)
        glob.round(4).to_excel(xw, sheet_name="Feature SHAP", index=False)
        perm.round(3).to_excel(xw, sheet_name="Permutation importance", index=False)
        pdp.drop(columns="_curve").round(3).to_excel(xw, sheet_name="Price PDP per SKU", index=False)
        sku.round(1).to_excel(xw, sheet_name="Drivers per SKU", index=False)
    json.dump({"families": fam_glob.round(2).to_dict(), "pdp_monotone": int(pdp.Monotone_Down.sum()),
               "pdp_vs_step9_corr": float(corr), "base_wape_sample": float(w0)},
              open(OUT / "explainability.json", "w"), indent=1)
    print(perm.round(2).to_string(index=False))
    print(sku[["Group", "ArticleName", "Top_1", "Top_2", "Top_3"]].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
