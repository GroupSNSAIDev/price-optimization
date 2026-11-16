"""All-SKU project, step B8: price accuracy (MSA proxy) and the IVA correction.

Finding: KZ_GrossSales (= KZ_NetsSales) INCLUDES IVA. KZ_Tax is the IVA inside it (5% items: tax = 5% of gross,
14% items: tax = 14% of gross), and the source GP = gross - COGS counts the tax as profit.
Correction: Net_Sales = gross - KZ_Tax (as recorded by the sales system), GP_Net = Net_Sales - COGS.

Price accuracy: the realised shelf price (gross / units, incl. IVA) per store-week is compared with the system price
incl. IVA in effect that week (price log, as-of the week's Thursday). Target: >= 98% within 2%.

Inputs: checkpoints/sales_article_level_*.parquet, clean/price_changes.parquet, clean/allsku/model_weekly.parquet,
        clean/allsku/chain_weekly.parquet
Outputs: chain_weekly.parquet gets Tax_KZ, Net_Sales_KZ, GP_Net_KZ, Margin_Net_Pct, IVA_Pct;
         clean/allsku/iva_by_sku.parquet; analysis/allsku/price_accuracy.xlsx
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"


def z(c):
    return str(c).lstrip("0")


def tax_by_week(codes):
    parts = []
    for f in sorted((ROOT / "checkpoints").glob("sales_article_level_202[4-6]_*.parquet")):
        d = pd.read_parquet(f, columns=["DateConverted", "PLANTNAME", "ArticleCode", "KZ_GrossSales", "KZ_Tax"])
        d = d[d.PLANTNAME != "HRCA"]
        d["Code"] = d.ArticleCode.astype(str).str.strip().map(z)
        d = d[d.Code.isin(codes)]
        for c in ["KZ_GrossSales", "KZ_Tax"]:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
        dt = pd.to_datetime(d.DateConverted)
        d["Week"] = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.normalize()
        parts.append(d.groupby(["Code", "Week"])[["KZ_GrossSales", "KZ_Tax"]].sum())
    return pd.concat(parts).groupby(level=[0, 1]).sum()


def main():
    cw = pd.read_parquet(CL / "chain_weekly.parquet")
    codes = set(cw.Code)

    # --- IVA correction
    t = tax_by_week(codes)
    t["tax_share"] = t.KZ_Tax / t.KZ_GrossSales
    cw = cw.drop(columns=[c for c in ["Tax_KZ", "Net_Sales_KZ", "GP_Net_KZ", "Margin_Net_Pct", "IVA_Pct"] if c in cw], errors="ignore")
    cw = cw.join(t.tax_share, on=["Code", "Week"])
    # SKU-level tax share (sales weighted) fills weeks where the daily file had no row
    sk = t.groupby(level=0).apply(lambda d: d.KZ_Tax.sum() / d.KZ_GrossSales.sum())
    cw["tax_share"] = cw.tax_share.fillna(cw.Code.map(sk)).fillna(0).clip(0, 0.2)
    cw["Tax_KZ"] = cw.Sales_KZ * cw.tax_share
    cw["Net_Sales_KZ"] = cw.Sales_KZ - cw.Tax_KZ
    cw["GP_Net_KZ"] = cw.Net_Sales_KZ - cw.COGS_KZ
    cw["Margin_Net_Pct"] = np.where(cw.Net_Sales_KZ > 0, cw.GP_Net_KZ / cw.Net_Sales_KZ * 100, np.nan)
    cw["Net_Price_KZ"] = np.where(cw.Units > 0, cw.Net_Sales_KZ / cw.Units, np.nan)
    cw["Below_Cost_Net_Week"] = cw.Net_Price_KZ < cw.Unit_Cost_KZ
    cw = cw.drop(columns="tax_share")

    p = pd.read_parquet(ROOT / "clean" / "price_changes.parquet",
                        columns=["Plant", "ArticleCode", "EffectiveTS", "PriceIVA_Base_KZ", "IVA", "Primary_UOM", "Is_Spike"])
    p = p[p.Primary_UOM & ~p.Is_Spike]
    p["Code"] = p.ArticleCode.astype(str).map(z)
    iva = p.groupby("Code").IVA.median().rename("IVA_Pct")
    cw["IVA_Pct"] = cw.Code.map(iva)
    cw.to_parquet(CL / "chain_weekly.parquet", index=False)
    iva.reset_index().to_parquet(CL / "iva_by_sku.parquet", index=False)

    # --- price accuracy, last 13 full weeks, store level
    w = pd.read_parquet(CL / "model_weekly.parquet", columns=["Week", "Plant", "Code", "Qty_Clean", "Sales_KZ", "Channel"])
    end = cw.Week.max()
    w = w[(w.Week > end - pd.Timedelta(weeks=13)) & (w.Week <= end) & (w.Qty_Clean > 0)].copy()
    w["rp"] = w.Sales_KZ / w.Qty_Clean
    w["t"] = w.Week + pd.Timedelta(days=3)
    m = pd.merge_asof(w.sort_values("t"), p.sort_values("EffectiveTS")[["EffectiveTS", "Plant", "Code", "PriceIVA_Base_KZ", "IVA"]],
                      left_on="t", right_on="EffectiveTS", by=["Plant", "Code"]).dropna(subset=["PriceIVA_Base_KZ"])
    m["ratio"] = m.rp / m.PriceIVA_Base_KZ
    m["within2"] = (m.ratio - 1).abs() <= 0.02
    m["band"] = pd.cut(m.ratio, [0, 0.8, 0.95, 0.98, 1.02, 1.05, 1.2, 1e9],
                       labels=["< -20%", "-20 to -5%", "-5 to -2%", "within 2%", "+2 to +5%", "+5 to +20%", "> +20%"])
    acc_iva = m.groupby("IVA").agg(Store_Weeks=("ratio", "size"), Median_Ratio=("ratio", "median"),
                                   Within_2pct=("within2", lambda x: x.mean() * 100))
    bands = m.groupby(["IVA", "band"], observed=True).size().unstack(fill_value=0)
    bands = (bands.T / bands.sum(axis=1)).T * 100
    acc_store = m.groupby(["Plant", "Channel"]).agg(Store_Weeks=("ratio", "size"), Median_Ratio=("ratio", "median"),
                                                    Within_2pct=("within2", lambda x: x.mean() * 100)).sort_values("Within_2pct")
    sku = m.groupby("Code").agg(Median_Ratio=("ratio", "median"), Within_2pct=("within2", lambda x: x.mean() * 100), IVA=("IVA", "median"))
    sku["Accuracy_Flag"] = np.select([(sku.Median_Ratio - 1).abs() > 0.05, sku.Within_2pct < 50],
                                     ["selling price >5% off system price", "selling price often off"], "")

    yr = cw.groupby(cw.Week.dt.year).agg(Gross=("Sales_KZ", "sum"), Tax=("Tax_KZ", "sum"), COGS=("COGS_KZ", "sum"))
    yr["Margin_incl_IVA_%"] = (yr.Gross - yr.COGS) / yr.Gross * 100
    yr["Margin_net_%"] = (yr.Gross - yr.Tax - yr.COGS) / (yr.Gross - yr.Tax) * 100
    yr["Tax_share_%"] = yr.Tax / yr.Gross * 100
    l52 = cw[cw.Week > end - pd.Timedelta(weeks=52)]
    sk52 = l52.groupby("Code").agg(g=("Sales_KZ", "sum"), n=("Net_Sales_KZ", "sum"), k=("COGS_KZ", "sum"))
    sk52["m_old"] = (sk52.g - sk52.k) / sk52.g * 100
    sk52["m_new"] = (sk52.n - sk52.k) / sk52.n * 100
    below = pd.DataFrame({"Measure": ["SKUs with margin < 0 (incl. IVA, old)", "SKUs with margin < 0 (net of IVA, correct)",
                                      "SKUs with margin < 5% (old)", "SKUs with margin < 5% (correct)",
                                      "Chain margin 52 wk, old %", "Chain margin 52 wk, correct %"],
                          "Value": [int((sk52.m_old < 0).sum()), int((sk52.m_new < 0).sum()), int((sk52.m_old < 5).sum()),
                                    int((sk52.m_new < 5).sum()), round((sk52.g.sum() - sk52.k.sum()) / sk52.g.sum() * 100, 1),
                                    round((sk52.n.sum() - sk52.k.sum()) / sk52.n.sum() * 100, 1)]})
    with pd.ExcelWriter(OUT / "price_accuracy.xlsx") as xw:
        pd.DataFrame({"Finding": [
            "Sales value (KZ_GrossSales = KZ_NetsSales) includes IVA; KZ_Tax is the IVA inside it.",
            "Source GP (= sales - COGS) therefore counts IVA as profit.",
            "From now on: Net sales = sales - KZ_Tax; GP = net sales - COGS (both in chain_weekly).",
            "5% IVA items: selling price matches the system price incl. IVA (median ratio 1.00).",
            "14% IVA items: selling price is ~9% below the system price incl. IVA; to check with finance / IT.",
        ]}).to_excel(xw, sheet_name="Findings", index=False)
        yr.round(2).to_excel(xw, sheet_name="Margin incl vs net IVA")
        below.to_excel(xw, sheet_name="Effect on SKUs", index=False)
        acc_iva.round(3).to_excel(xw, sheet_name="Accuracy by IVA")
        bands.round(1).to_excel(xw, sheet_name="Price gap bands")
        acc_store.round(2).to_excel(xw, sheet_name="Accuracy by store")
        sku.round(3).to_excel(xw, sheet_name="Accuracy by SKU")
    pd.set_option("display.width", 220)
    print(yr.round(2).to_string()); print(below.to_string(index=False)); print(acc_iva.round(3).to_string()); print(bands.round(1).to_string())
    print("stores lowest accuracy:\n", acc_store.head(6).round(2).to_string())
    print("SKU flags:", sku.Accuracy_Flag.value_counts().to_dict())


if __name__ == "__main__":
    main()
