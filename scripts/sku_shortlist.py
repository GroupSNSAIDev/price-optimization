"""Pilot SKU shortlist for price optimisation: 10 SKUs in each of four groups -> output/SKU_Shortlist/*.xlsx

  A  top sellers, highly price-sensitive            (protect / grow volume)
  B  top sellers whose margin is eroding            (recover margin)
  C  SKUs where a small reprice protects margin and volume (low sensitivity + thin margin -> rise;
     priced above category + high sensitivity -> cut)
  D  loss-makers with real sales and clean cost data

Every SKU must have a reliable elasticity, confirmed by its own past price changes, and no cost-posting corrections.
Each SKU is placed in one group only (priority D, B, A, C). Period: L12M = Oct 2025 - Sep 2026.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from rda_analysis import CL, L12, OUT, load_panel

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "output" / "SKU_Shortlist"
DEST.mkdir(parents=True, exist_ok=True)
N_PER_GROUP = 10
# availability rule (added 2026-10-19): the SKU must be on the shelf now
AVAIL_MIN_STORES_LAST_MONTH, AVAIL_MIN_WEEKS_LAST_13 = 10, 10
LAST_MONTH, LAST_13W_START = "2026-09", pd.Timestamp("2026-07-01")
# agreed shortlist kept as is; only these unavailable SKUs are replaced (discontinued / out of supply Apr-Sep 2026)
REPLACED = ["104932", "105005", "100474", "112671", "100479",   # discontinued / out of supply (user decision)
            "115675", "116442"]                                  # Gouda (no stock), duck wings (import prohibited)
D_REPLACE_MAX_MARGIN, D_REPLACE_MIN_SALES = 5.0, 8e6            # replacements: loss-making or near-loss, on shelf
L12_WEEKS = (pd.Timestamp("2025-09-29"), pd.Timestamp("2026-09-27"))


def article_metrics():
    a = pd.read_parquet(OUT / "article_l12m.parquet").set_index("ArticleCode")
    mc = pd.read_parquet(OUT / "pm_article_margin_change.parquet")
    a["Margin_P12"] = mc.Margin_Pct_P12
    a["Margin_Change_pp"] = a.Margin_Pct - a.Margin_P12
    sg = pd.read_parquet(OUT / "subgroup_l12m.parquet").set_index(["MainGroup", "SubGroup"]).Margin_Pct
    a["SubGroup_Margin"] = [sg.get((m, s), np.nan) for m, s in zip(a.MainGroup, a.SubGroup)]
    a["Gap_to_SubGroup_pp"] = a.Margin_Pct - a.SubGroup_Margin

    e = pd.read_parquet(ROOT / "analysis" / "article_elasticity.parquet").set_index("ArticleCode")
    a["Est_Obs"], a["Est_Locations"], a["Price_Variation_SD"] = e.Obs, e.Locations, e.Price_Variation_SD

    # the SKU's own past price changes: do volumes move against price, as the elasticity says?
    ev = pd.read_parquet(ROOT / "analysis" / "price_events.parquet")
    ev["Consistent"] = np.sign(ev["Price_Change_%"]) != np.sign(ev["Volume_Change_%"])
    g = ev.groupby("ArticleCode")
    a["Events"] = g.size()
    a["Events_Consistent_Pct"] = g.Consistent.mean() * 100
    a["Events_Median_Arc_Elasticity"] = g.Arc_Elasticity.median()
    a["Events"] = a.Events.fillna(0)

    # current weekly position (L12M): units per week, price, unit cost, price vs category
    w = pd.read_parquet(CL / "weekly_model.parquet", columns=["Week", "ArticleCode", "Qty_Base", "Sales_KZ", "KZ_COGS",
                                                              "Relative_Price"])
    w = w[w.Week.between(*L12_WEEKS)]
    ww = w.groupby("ArticleCode")
    weeks = w.Week.nunique()
    a["Units_per_Week"] = ww.Qty_Base.sum() / weeks
    a["Avg_Price_KZ"] = ww.Sales_KZ.sum() / ww.Qty_Base.sum()
    a["Unit_COGS_KZ"] = ww.KZ_COGS.sum() / ww.Qty_Base.sum()
    w["wr"] = w.Relative_Price * w.Sales_KZ
    a["Relative_Price"] = ww.wr.sum() / w[w.Relative_Price.notna()].groupby("ArticleCode").Sales_KZ.sum()

    # data quality: cost corrections and stock-outs in L12M
    p = load_panel()
    p = p[p.Month.isin(L12)]
    a["Cost_Fixed_Rows"] = p[p.COGS_Fixed].groupby("ArticleCode").size()
    a["Cost_Fixed_Rows"] = a.Cost_Fixed_Rows.fillna(0)
    st = p[p.Has_Stock_Record]
    a["OOS_Month_Pct"] = st.groupby("ArticleCode").Out_Of_Stock.mean() * 100
    return a.reset_index()


def availability(a):
    """stores selling in the last month, weeks with any sale in the last 13 weeks, closing stock at the last month"""
    parts = []
    for f in sorted((ROOT / "clean" / "sales_daily").glob("2026_0[789].parquet")):
        d = pd.read_parquet(f, columns=["Date", "Plant", "ArticleCode", "Qty_Base"])
        parts.append(d[d.ArticleCode.isin(a.ArticleCode) & (d.Qty_Base > 0)])
    d = pd.concat(parts)
    d = d[d.Date >= LAST_13W_START]
    st = pd.read_parquet(ROOT / "clean" / "stock_monthly.parquet", columns=["Month", "ArticleCode", "Closing_Qty_Base"])
    st = st[st.Month == LAST_MONTH].groupby("ArticleCode").Closing_Qty_Base.sum()
    a = a.set_index("ArticleCode")
    a["Stores_Last_Month"] = d[d.Date.dt.strftime("%Y-%m") == LAST_MONTH].groupby("ArticleCode").Plant.nunique()
    a["Weeks_Sold_Last_13"] = d.assign(W=d.Date.dt.to_period("W")).groupby("ArticleCode").W.nunique()
    a["Closing_Stock_Last_Month"] = st
    a[["Stores_Last_Month", "Weeks_Sold_Last_13", "Closing_Stock_Last_Month"]] =         a[["Stores_Last_Month", "Weeks_Sold_Last_13", "Closing_Stock_Last_Month"]].fillna(0)
    a["Available"] = (a.Stores_Last_Month >= AVAIL_MIN_STORES_LAST_MONTH) &                      (a.Weeks_Sold_Last_13 >= AVAIL_MIN_WEEKS_LAST_13) & (a.Closing_Stock_Last_Month > 0)
    return a.reset_index()


def gp_change(m, e, d):
    """model-implied % change in gross profit for a price change d, margin m (fraction), elasticity e"""
    return (((1 + d) - (1 - m)) / m * (1 + d) ** e - 1) * 100


def select(a):
    stable_cost = a.Margin_P12.isna() | a.Margin_P12.between(-60, 80)     # prior-year cost also plausible
    reliable = (a.Elasticity.between(-6, -0.05) & a.Shrink_Weight.ge(.5) & a.Est_Locations.ge(10)
                & a.Events.ge(3) & a.Events_Consistent_Pct.ge(60) & a.Cost_Fixed_Rows.eq(0)
                & a.Net_KZ.gt(0) & a.Margin_Pct.between(-60, 80) & stable_cost)
    top = a.Rank_Pct <= 20
    a["Reliable"] = reliable
    picked, groups = set(), []

    def take(mask, sort, asc, gname, why):
        d = a[mask & ~a.ArticleCode.isin(picked)].sort_values(sort, ascending=asc).head(N_PER_GROUP).copy()
        d["Group"] = gname
        d["Why_Selected"] = d.apply(why, axis=1)
        picked.update(d.ArticleCode)
        groups.append(d)

    # D: loss-makers with real sales (reliability relaxed on events: loss-makers rarely change price)
    d_mask = (a.Margin_Pct < 2) & a.Net_KZ.ge(15e6) & a.Cost_Fixed_Rows.eq(0) & a.Margin_Pct.gt(-60) & stable_cost \
        & a.Elasticity.between(-6, -0.05) & a.Shrink_Weight.ge(.4) & a.Est_Locations.ge(8)
    take(d_mask & a.Available, "GP_KZ", True, "D · Loss-maker with real sales",
         lambda r: f"Margin {r.Margin_Pct:.1f}% on {r.Net_KZ / 1e6:,.0f}m Kz sales; GP {r.GP_KZ / 1e6:,.1f}m Kz"
                   + (f"; margin fell {r.Margin_Change_pp:.0f} pp: verify cost with procurement"
                      if r.Margin_Change_pp <= -15 else ""))

    # B: top sellers whose margin eroded (vs last year, or vs their own sub-group)
    a["Erosion_KZ"] = np.maximum(-a.Margin_Change_pp.fillna(0), -a.Gap_to_SubGroup_pp.fillna(0)).clip(lower=0) / 100 * a.Net_KZ
    b_mask = reliable & top & ((a.Margin_Change_pp <= -2) | (a.Gap_to_SubGroup_pp <= -5))
    take(b_mask, "Erosion_KZ", False, "B · Top seller, margin eroding",
         lambda r: f"Margin {r.Margin_P12:.1f}% → {r.Margin_Pct:.1f}% ({r.Margin_Change_pp:+.1f} pp); "
                   f"sub-group {r.SubGroup_Margin:.1f}%")

    # A: top sellers, highly price-sensitive
    a_mask = reliable & top & (a.Elasticity <= -1.5)
    take(a_mask, "Net_KZ", False, "A · Top seller, highly price-sensitive",
         lambda r: f"Elasticity {r.Elasticity:.2f}; sales rank top {r.Rank_Pct:.1f}%; price vs category "
                   f"{r.Relative_Price:.2f}")

    # C: reprice to protect margin and volume
    m = a.Margin_Pct / 100
    a["GP_Up5_Pct"] = gp_change(m, a.Elasticity, .05)
    a["GP_Dn5_Pct"] = gp_change(m, a.Elasticity, -.05)
    rise = reliable & (a.Elasticity > -0.8) & (a.Margin_Pct < np.minimum(a.SubGroup_Margin, 25)) & a.Margin_Pct.gt(2)
    cut = reliable & (a.Relative_Price > 1.05) & (a.Elasticity < -1.5) & (a.GP_Dn5_Pct > 0)
    a["C_Gain_KZ"] = np.where(rise, a.GP_Up5_Pct, np.where(cut, a.GP_Dn5_Pct, np.nan)) / 100 * a.GP_KZ
    take((rise | cut) & a.Net_KZ.ge(50e6), "C_Gain_KZ", False, "C · Reprice to protect margin & volume",
         lambda r: (f"Low sensitivity ({r.Elasticity:.2f}) on thin margin {r.Margin_Pct:.1f}% (sub-group "
                    f"{r.SubGroup_Margin:.1f}%) → small rise" if r.Elasticity > -0.8 else
                    f"Priced {(r.Relative_Price - 1) * 100:.0f}% above category, elasticity {r.Elasticity:.2f} → small cut"))
    return pd.concat(groups, ignore_index=True), a


def main():
    a = availability(article_metrics())
    s_new, a = select(a)
    prev = OUT / "sku_shortlist.parquet"
    if prev.exists():
        # keep the agreed shortlist exactly (groups and reasons); replace only the unavailable SKUs with the next
        # available Group D loss-makers
        old = pd.read_parquet(prev)
        old["ArticleCode"] = old.ArticleCode.str.zfill(18)
        repl = [c.zfill(18) for c in REPLACED]
        keep = old[~old.ArticleCode.isin(repl)][["ArticleCode", "Group", "Why_Selected"]]
        s = a.drop(columns=["Group", "Why_Selected"], errors="ignore").merge(keep, on="ArticleCode")
        stable_cost = a.Margin_P12.isna() | a.Margin_P12.between(-60, 80)
        d_all = a[(a.Margin_Pct < D_REPLACE_MAX_MARGIN) & a.Net_KZ.ge(D_REPLACE_MIN_SALES) & a.Cost_Fixed_Rows.eq(0)
                  & a.Margin_Pct.gt(-40) & stable_cost & a.Elasticity.between(-6, -0.05) & a.Shrink_Weight.ge(.4)
                  & a.Est_Locations.ge(8) & a.Available & ~a.ArticleCode.isin(old.ArticleCode)].copy()
        d_all["Shortfall_KZ"] = (d_all.SubGroup_Margin - d_all.Margin_Pct).clip(lower=0) / 100 * d_all.Net_KZ
        d_all = d_all.sort_values("Shortfall_KZ", ascending=False)
        print(f"available D candidates: {len(d_all)}")
        need = N_PER_GROUP - (s.Group.str[0] == "D").sum()
        new_d = d_all.head(need).assign(Group="D · Loss-maker with real sales")
        new_d["Why_Selected"] = new_d.apply(
            lambda r: f"Margin {r.Margin_Pct:.1f}% (sub-group {r.SubGroup_Margin:.1f}%) on {r.Net_KZ / 1e6:,.0f}m Kz sales;"
                      f" shortfall {r.Shortfall_KZ / 1e6:,.1f}m Kz; on shelf in {r.Stores_Last_Month:.0f} stores"
                      + (f"; margin fell {r.Margin_Change_pp:.0f} pp: verify cost" if r.Margin_Change_pp <= -8 else ""),
            axis=1)
        s = pd.concat([s, new_d], ignore_index=True)
        s["Replacement"] = s.ArticleCode.isin(new_d.ArticleCode)
        s = s.sort_values("Group").reset_index(drop=True)
        print("replaced:", REPLACED, "-> new D:", new_d.ArticleName.tolist())
    else:
        s = s_new
    cols = ["Group", "ArticleCode", "ArticleName", "MainGroup", "SubGroup", "Why_Selected", "Net_KZ", "GP_KZ",
            "Margin_Pct", "Margin_P12", "Margin_Change_pp", "SubGroup_Margin", "Units_per_Week", "Avg_Price_KZ",
            "Unit_COGS_KZ", "Relative_Price", "Elasticity", "SE", "Shrink_Weight", "Est_Locations", "Events",
            "Events_Consistent_Pct", "Events_Median_Arc_Elasticity", "OOS_Month_Pct", "Locations", "Rank_Pct",
            "Stores_Last_Month", "Weeks_Sold_Last_13", "Closing_Stock_Last_Month", "Available"] +            (["Replacement"] if "Replacement" in s else [])
    s = s[cols]
    s["ArticleCode"] = s.ArticleCode.str.lstrip("0")
    counts = s.Group.value_counts().sort_index()
    print(counts.to_string())
    print("reliable SKUs available:", int(a.Reliable.sum()))
    with pd.ExcelWriter(DEST / "Fresmart_Pilot_SKU_Shortlist.xlsx") as xw:
        s.to_excel(xw, sheet_name="Shortlist (40)", index=False)
        pd.DataFrame({"Rule": [
            "Period: last 12 months, Oct 2025 – Sep 2026; money in Kz",
            "Reliable elasticity: between −6 and 0, shrink weight ≥ 0.5, estimated in ≥ 10 stores",
            "Confirmed by own price changes: ≥ 3 past events, ≥ 60% moved volume against price (not required for D)",
            "Clean cost data: no cost-posting corrections in the period; margin between −60% and 80%",
            "A: top 20% by sales and elasticity ≤ −1.5; ranked by sales",
            "B: top 20% by sales and margin down ≥ 2 pp vs prior 12M or ≥ 5 pp below sub-group; ranked by profit eroded",
            "C: elasticity > −0.8 and margin below sub-group (max 25%) → small rise; or priced > 5% above category "
            "with elasticity < −1.5 and a 5% cut raising GP → small cut; sales ≥ 50m Kz; ranked by model-implied GP gain",
            "D: margin < 2% with sales ≥ 15m Kz, elasticity estimated in ≥ 8 stores; ranked by loss",
            "Availability (all new picks): sold in ≥ 10 stores in Sep 2026, in ≥ 10 of the last 13 weeks, stock on hand "
            "end Sep 2026",
            "19 Oct 2026: 7 unavailable D SKUs replaced (Copacol, Perdix, Seara mortadella; Ferrero T16; Nuggets; "
            "Gouda slices; duck wings). Replacements: margin -40% to 5%, sales >= 8m Kz, on shelf; ranked by profit "
            "shortfall vs sub-group margin",
            "Each SKU appears in one group only (priority D, B, A, C)"]}).to_excel(xw, sheet_name="Selection rules",
                                                                                  index=False)
    s.to_parquet(OUT / "sku_shortlist.parquet")
    print(DEST / "Fresmart_Pilot_SKU_Shortlist.xlsx")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 38)
    print(s[["Group", "ArticleName", "SubGroup", "Net_KZ", "Margin_Pct", "Margin_Change_pp", "Elasticity",
             "Events", "Relative_Price"]].round(2).to_string())


if __name__ == "__main__":
    main()
