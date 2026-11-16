"""SKU portfolio for the dashboard: every ACTIVE SKU grouped by revenue and margin role.

Window: last 52 full weeks of clean/weekly_model.parquet (the partial last week is left out), stores + HDDS
(HRCA left out: negotiated B2B prices). ACTIVE = Active_status 'ACTIVE' in the refreshed article master.

Segments (one per SKU), on revenue rank (A = top 80% of revenue, B = next 15%, C = last 5%) and margin:
  Stars            A, margin >= chain average
  Traffic drivers  A, margin 5% to chain average
  Margin broken    A, margin < 5%
  Profit gems      B/C, margin >= 30%
  Fix or delist    B/C, margin < 5%
  Core             B, rest
  Long tail        C, rest

Revenue and GP are NET of IVA (user decision 2026-11-15): net sales = sales - recorded KZ_Tax, GP = net sales - COGS,
from clean/allsku/chain_weekly.parquet.

Output: <dest>/portfolio.json (one row per SKU; default clean/allsku, the dashboard copy is left alone),
analysis/allsku/sku_portfolio.xlsx
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "allsku"
CL = ROOT / "clean" / "allsku"
WEEKS = 52
FX = 1050.0
SEG_ORDER = ["Stars", "Traffic drivers", "Margin broken", "Profit gems", "Fix or delist", "Core", "Long tail"]
ACTION = {"Stars": "Protect: small rises only where sensitivity is low",
          "Traffic drivers": "Careful rises: biggest lever, watch volume",
          "Margin broken": "Fix first: cost pass-through",
          "Profit gems": "Push: space, visibility, keep price",
          "Fix or delist": "Fix price or review the range",
          "Core": "Optimise with group sensitivity",
          "Long tail": "Rules only: cost pass-through, review range"}


def z(c):
    return str(c).lstrip("0")


def main(dest):
    OUT.mkdir(parents=True, exist_ok=True)
    m = pd.read_parquet(ROOT / "checkpoints" / "dim_article_master.parquet",
                        columns=["ArticalCode", "Active_status", "ArticalName", "MainGroup", "SubGroup", "Import", "BRAND_DESCR"])
    m["c"] = m.ArticalCode.map(z)
    m = m.drop_duplicates("c").set_index("c")
    active = set(m.index[m.Active_status.eq("ACTIVE")])

    cols = ["Week", "Plant", "ArticleCode", "Qty_Clean", "Sales_KZ", "KZ_COGS", "Sales_USD", "Channel"]
    w = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=cols)
    w = w[w.Channel != "HRCA"]
    w["c"] = w.ArticleCode.map(z)
    weeks = sorted(w.Week.unique())
    full = weeks[:-1]
    win = w[w.Week.isin(full[-WEEKS:])]
    all_sold = win.c.nunique()
    win = win[win.c.isin(active)]

    g = win.groupby("c").agg(stores=("Plant", "nunique"), weeks=("Week", "nunique"))
    cw = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Sales_USD", "Sales_KZ", "Net_Sales_KZ", "COGS_KZ"])
    cw = cw[cw.Week.isin(full[-WEEKS:])].groupby("Code").sum(numeric_only=True)
    g = g.join(cw)
    g = g[g.Net_Sales_KZ > 0]
    g["rev"] = g.Sales_USD * g.Net_Sales_KZ / g.Sales_KZ          # net-of-IVA revenue in USD
    g["gp"] = g.rev * (g.Net_Sales_KZ - g.COGS_KZ) / g.Net_Sales_KZ
    g["margin"] = (g.Net_Sales_KZ - g.COGS_KZ) / g.Net_Sales_KZ * 100
    T, TG = g.rev.sum(), g.gp.sum()
    avg = TG / T * 100
    g = g.sort_values("rev", ascending=False)
    g["rank"] = np.arange(1, len(g) + 1)
    g["cum"] = g.rev.cumsum() / T * 100
    g["abc"] = np.where(g.cum - g.rev / T * 100 < 80, "A", np.where(g.cum - g.rev / T * 100 < 95, "B", "C"))
    gp = g.sort_values("gp", ascending=False)
    pos = gp.gp.clip(lower=0)
    gcum = pos.cumsum() / pos.sum() * 100
    g["gp_rank"] = g.index.map(pd.Series(np.arange(1, len(gp) + 1), index=gp.index))
    g["top_gp"] = g.index.map((gcum - pos / pos.sum() * 100) < 80)

    g["segment"] = np.select(
        [(g.abc == "A") & (g.margin >= avg), (g.abc == "A") & (g.margin >= 5), g.abc == "A",
         g.margin >= 30, g.margin < 5, g.abc == "B"],
        SEG_ORDER[:5] + ["Core"], "Long tail")

    # on shelf now: >= 10 stores in the last 4 weeks and sold in >= 10 of the last 13 weeks
    l4 = w[w.Week.isin(full[-4:])].groupby("c").Plant.nunique()
    l13 = w[w.Week.isin(full[-13:])].groupby("c").Week.nunique()
    g["stores_4w"] = g.index.map(l4).fillna(0).astype(int)
    g["on_shelf"] = (g.stores_4w >= 10) & (g.index.map(l13).fillna(0) >= 10)

    # price history: chain weekly price over 104 weeks, moves > 3%
    h = w[w.Week.isin(full[-104:]) & w.c.isin(g.index)].groupby(["c", "Week"]).agg(q=("Qty_Clean", "sum"), s=("Sales_KZ", "sum"))
    h = h[h.q > 0]
    lp = np.log(h.s / h.q)
    n = lp.groupby(level=0).size()
    moves = lp.groupby(level=0).apply(lambda x: int((x.diff().abs() > 0.03).sum()))
    g["price_history"] = np.select([(n.reindex(g.index) >= 52) & (moves.reindex(g.index) >= 4),
                                    (n.reindex(g.index) >= 26) & (moves.reindex(g.index) >= 2)], ["Rich", "Some"], "Thin")

    # last 8 weeks margin, for "below cost now"
    r8 = pd.read_parquet(CL / "chain_weekly.parquet", columns=["Code", "Week", "Net_Sales_KZ", "COGS_KZ"])
    r8 = r8[r8.Week.isin(full[-8:])].groupby("Code").agg(s=("Net_Sales_KZ", "sum"), k=("COGS_KZ", "sum"))
    g["margin_8w"] = g.index.map((r8.s - r8.k) / r8.s * 100)

    info = m.reindex(g.index)
    sd = info.Import.fillna("").str.strip()
    g["short_desc"] = np.where((sd == "") | (sd == "Others"), info.SubGroup.fillna("?") + " (other)", sd)
    g["short_desc_real"] = ~((sd == "") | (sd == "Others"))
    out = pd.DataFrame({
        "Code": g.index, "Name": info.ArticalName.str.strip(), "MainGroup": info.MainGroup, "SubGroup": info.SubGroup,
        "ShortDesc": g.short_desc, "ShortDesc_Real": g.short_desc_real, "Brand": info.BRAND_DESCR,
        "Segment": g.segment, "Action": g.segment.map(ACTION), "ABC": g.abc, "Rank": g["rank"], "GP_Rank": g.gp_rank,
        "Top80_GP": g.top_gp, "Revenue_USD": g.rev.round(0), "GP_USD": g.gp.round(0), "Margin_Pct": g.margin.round(1),
        "Margin_8w_Pct": g.margin_8w.round(1), "Rev_Share_Pct": (g.rev / T * 100).round(4), "Cum_Rev_Pct": g.cum.round(2),
        "GP_Share_Pct": (g.gp / TG * 100).round(4), "Stores": g.stores, "Stores_4w": g.stores_4w,
        "On_Shelf": g.on_shelf, "Price_History": g.price_history,
    }).reset_index(drop=True)
    out = out.replace({np.nan: None})
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "portfolio.json").write_text(json.dumps(out.to_dict("records"), separators=(",", ":")), encoding="utf-8")
    meta = {"Start": str(pd.Timestamp(full[-WEEKS]).date()), "End": str((pd.Timestamp(full[-1]) + pd.Timedelta(days=6)).date()),
            "Active_SKUs": len(out), "All_Sold_SKUs": int(all_sold), "Chain_Margin_Pct": round(avg, 1),
            "Revenue_USD": round(T), "GP_USD": round(TG)}
    (dest / "portfolio_meta.json").write_text(json.dumps([meta]), encoding="utf-8")

    seg = out.groupby("Segment").agg(SKUs=("Code", "size"), On_Shelf=("On_Shelf", "sum"), Revenue_USD=("Revenue_USD", "sum"),
                                     GP_USD=("GP_USD", "sum")).reindex(SEG_ORDER)
    seg["Rev_%"] = seg.Revenue_USD / T * 100
    seg["GP_%"] = seg.GP_USD / TG * 100
    seg["Margin_%"] = seg.GP_USD / seg.Revenue_USD * 100
    with pd.ExcelWriter(OUT / "sku_portfolio.xlsx") as xw:
        seg.round(1).to_excel(xw, sheet_name="Segments")
        out.groupby(["MainGroup", "Segment"]).Revenue_USD.sum().unstack().reindex(columns=SEG_ORDER).round(0).to_excel(xw, sheet_name="MainGroup x Segment")
        out.to_excel(xw, sheet_name="SKUs", index=False)
    print(meta)
    print(seg.round(1).to_string())
    print("A SKUs", (out.ABC == "A").sum(), "| top-80% GP SKUs", int(out.Top80_GP.sum()), "| on shelf", int(out.On_Shelf.sum()),
          "| real short desc", int(out.ShortDesc_Real.sum()), "| price history", out.Price_History.value_counts().to_dict())


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else CL)
