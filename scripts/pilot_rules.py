"""Step 17 · Business rule validation of the final price list (step 16)

Each rule is checked per SKU (and per store where it applies) and gets PASS / FLAG (decision or note) / FAIL (must fix):
 R1  New net price (ex IVA) above unit cost; a loss-maker's rise must reduce the loss
 R2  Step size <= 10% and inside the SKU's tested price range
 R3  Price endings follow Fresmart's convention (...9.99 / ...99.99)
 R4  Pack-size ladders (same product, per kg / litre): the bigger pack stays cheaper per unit
 R5  Substitute ordering: the per-kg / litre price order inside a substitute group does not flip
 R6  Store tiers kept: each store's gap to the chain price moves by <= 1 point after rounding
 R7  No new price points: stores in one tier still share one price
 R8  Psychological thresholds: crossing a round price (e.g. 25,000 / 150,000 Kz) -> option just below, with GP
 R9  Recent price change: a change in the 4 weeks before the effective date -> flag (customer confusion)
 R10 Active promotions: discounted share of sales in the last 4 weeks > 10% -> flag (promo and base price interact)
 R11 Regulated / price-controlled goods: staples flagged until the KVI / monitored-price list is confirmed
 R12 List vs realised price: realised net price far below list (discount leakage) -> impact may be overstated
 R13 Margin ceiling: new margin more than 10 points above the sub-group's average margin -> flag (price image)
 R14 Basket view: weighted price change of the pilot basket and of staples vs monthly inflation
 R15 Price lines: products outside the pilot at exactly the same shelf price today, same pack and the same brand / range
     (>= 4 shared name words incl. the pack size) move with the pilot SKU, store by store; their impact is an
     estimate (pilot SKU's elasticity, own volume, price and cost), not modelled
Outputs: analysis/pilot/business_rules.xlsx, clean/pilot/validated_prices.parquet, clean/pilot/line_moves.parquet
"""
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import pilot_optimise as O
import pilot_recommend as R

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "pilot", ROOT / "analysis" / "pilot"
z = O.z
# pack-size ladders: same brand / product, sizes in kg or litres per base unit
LADDERS = [("Sugar Kapanda", {"101241": 1, "101237": 1}, "kg"),        # 1 kg packs vs 50 kg bag (both priced per kg)
           ("Oil Boa Vista", {"117433": 1, "117443": 20}, "litre")]    # 1 L bottles vs 20 L bidon
# substitute groups compared per kg / litre (base unit size)
SUBST = [("Chicken legs", {"100501": 1, "100520": 1, "107637": 1, "107620": 1, "100423": 1}, "kg"),
         ("Soy oil 1 L", {"117433": 1, "110680": 1, "101304": 1}, "litre"),
         ("Rice", {"101249": 1, "101250": 1}, "kg"),
         ("Friboi beef", {"113475": 1, "113480": 1, "113484": 1}, "kg")]
THRESH = [1000, 2000, 2500, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000, 60000, 70000, 75000, 80000,
          90000, 100000, 125000, 150000, 175000, 200000]


def main():
    rec = pd.read_parquet(CL / f"recommendations{O.SFX}.parquet").set_index("ArticleCode")
    rec["Substitute_Group"] = pd.read_parquet(CL / f"optimal_prices{O.SFX}.parquet").set_index("ArticleCode").Substitute_Group
    g = pd.read_parquet(CL / "profit_grid.parquet")
    g["Price_Change_%"] = g["Price_Change_%"].round().astype(int)
    cur = g[g["Price_Change_%"] == 0].set_index("ArticleCode")
    e = pd.read_parquet(CL / "sku_elasticity.parquet").set_index("ArticleCode")
    x = pd.read_parquet(CL / "cross_elasticity.parquet")
    f = pd.read_parquet(CL / "pilot_features.parquet")
    sp = pd.read_excel(OUT / f"recommendations{O.SFX}.xlsx", sheet_name="Store price list", dtype={"ArticleCode": str})
    sp["ArticleCode"] = sp.ArticleCode.map(z)
    mk = O.Market(g, x)
    changed = rec["Price_Change_%"] != 0
    res = []                                                                  # (rule, sku, status, detail)

    def add(rule, a, status, detail):
        res.append({"Rule": rule, "ArticleCode": a, "ArticleName": rec.at[a, "ArticleName"] if a in rec.index else "",
                    "Status": status, "Detail": detail})

    # net price per base unit implied by the shelf price, and the realised price
    rec["Net_List_Per_Unit_KZ"] = rec.Shelf_Price_KZ / (1 + rec["IVA_%"] / 100) / rec.Units_Per_Pack
    rec["New_Net_List_Per_Unit_KZ"] = rec.New_Shelf_Price_KZ / (1 + rec["IVA_%"] / 100) / rec.Units_Per_Pack
    rec["Realised_Net_Per_Unit_KZ"] = cur.Current_Price_KZ
    rec["Unit_Cost_KZ"] = cur.Unit_Cost_KZ
    rec["Realised_vs_List_%"] = (rec.Realised_Net_Per_Unit_KZ / rec.Net_List_Per_Unit_KZ - 1) * 100

    for a, r in rec[changed].iterrows():
        # R1 cost
        new_net = r.Realised_Net_Per_Unit_KZ * (1 + r["Price_Change_%"] / 100)
        if new_net <= r.Unit_Cost_KZ:
            st = "FLAG" if r["Price_Change_%"] > 0 else "FAIL"
            add("R1 Above cost", a, st, f"new net {new_net:,.0f} Kz <= cost {r.Unit_Cost_KZ:,.0f} Kz"
                + (" (rise reduces the loss)" if st == "FLAG" else ""))
        else:
            add("R1 Above cost", a, "PASS", f"new margin {(1 - r.Unit_Cost_KZ / new_net) * 100:.1f}%")
        # R2 step and tested range
        rng = g[(g.ArticleCode == a) & g.Within_Tested_Range]["Price_Change_%"]
        ok = abs(r["Price_Change_%"]) <= O.CFG["max_price_step_pct"] + 1e-9 and \
            rng.min() - 0.5 <= r["Price_Change_%"] <= rng.max() + 0.5
        add("R2 Step & tested range", a, "PASS" if ok else "FAIL",
            f"{r['Price_Change_%']:+.2f}% (tested {rng.min()}..{rng.max()}%)")
        # R3 ending
        p = r.New_Shelf_Price_KZ
        ok = abs((p + 0.01) % (10 if p < 10000 else 100)) < 1e-6 or abs((p + 0.01) % (10 if p < 10000 else 100) - (10 if p < 10000 else 100)) < 1e-6
        add("R3 Price ending", a, "PASS" if ok else "FAIL", f"{p:,.2f}")
        # R8 thresholds
        crossed = [t for t in THRESH if r.Shelf_Price_KZ < t <= p]
        if crossed:
            t = max(crossed)
            below = t - (10 if t <= 10000 else 100) - 0.01
            d_b = (below / r.Shelf_Price_KZ - 1) * 100
            members = [m for m in rec.index if rec.at[m, "Substitute_Group"] == r.Substitute_Group] \
                if r.Substitute_Group else [a]
            base_ds = {m: rec.at[m, "Price_Change_%"] for m in members}
            gp = lambda ds: mk.evaluate(ds).GP_L.sum()
            g0 = gp({m: 0 for m in members})
            g_rec, g_alt = gp(base_ds) - g0, gp({**base_ds, a: d_b}) - g0 if d_b > 0 else 0
            if d_b <= 0:
                txt = (f"crosses {t:,.0f} Kz ({r.Shelf_Price_KZ:,.2f} -> {p:,.2f}); already just below it, so the "
                       "only alternative is to hold")
            else:
                txt = (f"crosses {t:,.0f} Kz ({r.Shelf_Price_KZ:,.2f} -> {p:,.2f}); option {below:,.2f} ({d_b:+.1f}%) "
                       f"keeps {g_alt / g_rec * 100:.0f}% of the GP gain")
            add("R8 Price threshold", a, "FLAG", txt)
        else:
            add("R8 Price threshold", a, "PASS", "no round price crossed")
        # R11 regulated
        add("R11 Price-controlled", a, "FLAG" if r.Confirm_Not_Price_Controlled else "PASS",
            "staple: confirm not under the KVI / monitored-price list" if r.Confirm_Not_Price_Controlled else "not a staple")
        # R12 leakage
        st = "FLAG" if r["Realised_vs_List_%"] < -8 else "PASS"
        add("R12 List vs realised", a, st, f"realised net price {r['Realised_vs_List_%']:+.1f}% vs list"
            + (" - discounts / tiers: the list change passes through partly" if st == "FLAG" else ""))

    # R4 pack ladders and R5 substitute order (per kg / litre, net list)
    for name, members, unit in LADDERS + SUBST:
        codes = [z(c) for c in members if z(c) in rec.index]
        before = pd.Series({a: rec.at[a, "Net_List_Per_Unit_KZ"] / members[a.lstrip("0")] for a in codes})
        after = pd.Series({a: rec.at[a, "New_Net_List_Per_Unit_KZ"] / members[a.lstrip("0")] for a in codes})
        rule = "R4 Pack ladder" if (name, members, unit) in LADDERS else "R5 Substitute order"
        flips = before.rank().ne(after.rank()).any()
        txt = "; ".join(f"{str(rec.at[a, 'ArticleName'])[:22]}: {before[a]:,.0f} -> {after[a]:,.0f} Kz/{unit}" for a in codes)
        for a in codes:
            add(rule, a, "FAIL" if flips else "PASS", (f"{name} order changes: " if flips else f"{name} order kept: ") + txt)

    # R6 / R7 store tiers
    s = sp[sp.Change].copy()
    main_old = s.ArticleCode.map(rec.Shelf_Price_KZ)
    main_new = s.ArticleCode.map(rec.New_Shelf_Price_KZ)
    s["Gap_Before_%"] = (s.Shelf_Price_KZ / main_old - 1) * 100
    s["Gap_After_%"] = (s.New_Shelf_Price_KZ / main_new - 1) * 100
    s["Gap_Move_pt"] = s["Gap_After_%"] - s["Gap_Before_%"]
    for a, d in s.groupby("ArticleCode"):
        mv = d.Gap_Move_pt.abs().max()
        add("R6 Store tiers kept", a, "PASS" if mv <= 1 else "FLAG", f"max tier gap move {mv:.2f} pt")
        n_old, n_new = d.Shelf_Price_KZ.nunique(), d.New_Shelf_Price_KZ.nunique()
        add("R7 No new price points", a, "PASS" if n_new <= n_old else "FLAG", f"{n_old} store prices -> {n_new}")

    # R9 recent price change (actual price moves, not re-records)
    p = pd.read_parquet(ROOT / "clean" / "price_changes.parquet")
    p["c"] = p.ArticleCode.astype(str).str.lstrip("0")
    p = p[p.Primary_UOM & ~p.Is_Spike & p.c.isin([a.lstrip("0") for a in rec.index])].sort_values("EffectiveTS")
    p["moved"] = p.groupby(["Plant", "c"]).PriceIVA.diff().abs() > 0.5
    last_move = p[p.moved].groupby("c").EffectiveTS.max()
    for a in rec[changed].index:
        lm = last_move.get(a.lstrip("0"))
        days = (R.EFFECTIVE - lm).days if lm is not None else 999
        add("R9 Recent price change", a, "FLAG" if days < 28 else "PASS",
            f"last shelf price move {lm.date() if lm is not None else 'none'} ({days} days before 2 Nov)")
    # R10 promotions
    rec4 = f[(f.Week >= O.ORIGIN - pd.Timedelta(weeks=4)) & (f.Week < O.ORIGIN)]
    promo = rec4.assign(D=(rec4.Discount_Pct > 1) * rec4.Units).groupby("ArticleCode").apply(
        lambda d: d.D.sum() / d.Units.sum() * 100)
    for a in rec[changed].index:
        v = promo.get(a, 0)
        add("R10 Active promotion", a, "FLAG" if v > 10 else "PASS", f"{v:.0f}% of units sold with a discount (4 weeks)")
    # R13 margin ceiling vs sub-group (step 3 shortlist reference)
    sl = pd.read_parquet(ROOT / "analysis" / "rda" / "sku_shortlist.parquet")
    sl["ArticleCode"] = sl.ArticleCode.astype(str).map(z)
    p90 = sl.set_index("ArticleCode").SubGroup_Margin
    for a, r in rec[changed].iterrows():
        new_m = (1 - r.Unit_Cost_KZ / (r.Realised_Net_Per_Unit_KZ * (1 + r["Price_Change_%"] / 100))) * 100
        ref = p90.get(a, np.nan)
        st = "FLAG" if pd.notna(ref) and new_m > ref + 10 else "PASS"
        add("R13 Margin ceiling", a, st, f"new margin {new_m:.1f}% vs sub-group {ref:.1f}%")

    # R15 price lines ---------------------------------------------------------------------------------------------
    allp = pd.read_parquet(ROOT / "clean" / "price_changes.parquet")
    allp["c"] = allp.ArticleCode.astype(str).str.lstrip("0")
    allp = allp[allp.Primary_UOM & ~allp.Is_Spike & allp.PriceIVA.notna()].sort_values("EffectiveTS")
    st_last = allp.groupby(["Plant", "c"]).tail(1)
    md = lambda v: v.mode().iloc[0] if len(v.mode()) else np.nan
    chain_p = st_last.groupby("c").agg(P=("PriceIVA", md), U=("SalesUOM", md))
    wk = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet",
                         columns=["Week", "ArticleCode", "ArticleName", "Qty_Clean", "KZ_NetsSales", "KZ_COGS"])
    wk["c"] = wk.ArticleCode.astype(str).str.lstrip("0")
    r13 = wk[wk.Week >= O.ORIGIN - pd.Timedelta(weeks=13)].groupby("c").agg(
        Name=("ArticleName", "first"), Units_13w=("Qty_Clean", "sum"), Net=("KZ_NetsSales", "sum"), COGS=("KZ_COGS", "sum"))
    r13 = r13[r13.Units_13w > 0]
    tok = lambda n: {w for w in re.split(r"[ ,()]+", str(n).upper()) if len(w) > 3}
    pilot = set(a.lstrip("0") for a in rec.index)
    lines = []
    for a, r in rec[changed].iterrows():
        same = chain_p[(chain_p.P - r.Shelf_Price_KZ).abs().lt(0.5) & (chain_p.U == r.Sales_UOM)].index
        mine = tok(r.ArticleName)
        sibs = []
        for c in same:
            if c in pilot or c not in r13.index:
                continue
            shared = mine & tok(r13.at[c, "Name"])
            if len(shared) >= 4 and any(ch.isdigit() for w in shared for ch in w):
                sibs.append(c)
        if not sibs:
            add("R15 Price lines", a, "PASS", "no other product shares its price line")
            continue
        add("R15 Price lines", a, "PASS", "line moved together: " + "; ".join(str(r13.at[c, "Name"])[:30] for c in sibs))
        sw = (pd.Timestamp("2026-12-28") - R.EFFECTIVE).days / 7 / 13
        for c in sibs:
            d = r["Price_Change_%"] / 100
            u = r13.at[c, "Units_13w"] * sw
            pr, cs = r13.at[c, "Net"] / r13.at[c, "Units_13w"], r13.at[c, "COGS"] / r13.at[c, "Units_13w"]
            u_new = u * (1 + d) ** e.at[a, "Rise_Final"]
            lines.append({"Pilot_ArticleCode": a, "Pilot_ArticleName": r.ArticleName, "ArticleCode": c,
                          "ArticleName": r13.at[c, "Name"], "Sales_UOM": r.Sales_UOM, "Shelf_Price_KZ": r.Shelf_Price_KZ,
                          "New_Shelf_Price_KZ": r.New_Shelf_Price_KZ, "Price_Change_%": r["Price_Change_%"],
                          "Units_Base_Remaining": u, "Units_Change_Est": u_new - u,
                          "GP_Change_Est_KZ": u_new * (pr * (1 + d) - cs) - u * (pr - cs),
                          "Basis": "estimate: pilot SKU's rise elasticity, own volume / price / cost; not modelled"})
    lines = pd.DataFrame(lines)
    line_store = pd.DataFrame()
    if len(lines):
        ls = st_last[st_last.c.isin(lines.ArticleCode) & ~st_last.Plant.isin(R.B2B)][["Plant", "c", "SalesUOM", "PriceIVA"]]
        ls = ls.merge(lines[["ArticleCode", "ArticleName", "Price_Change_%"]], left_on="c", right_on="ArticleCode")
        ls["New_Shelf_Price_KZ"] = [R.round_shelf(pv, dv) for pv, dv in zip(ls.PriceIVA, ls["Price_Change_%"])]
        off = (ls.PriceIVA / ls.c.map(chain_p.P) - 1).abs() * 100 > R.OFF_TIER_PCT
        ls.loc[off, "New_Shelf_Price_KZ"] = ls.loc[off, "PriceIVA"]
        ls["Store_Note"] = np.where(off, "No change: store price far from the chain price - check first", "")
        line_store = ls.drop(columns="c").rename(columns={"PriceIVA": "Shelf_Price_KZ"})
    lines.to_parquet(CL / f"line_moves{O.SFX}.parquet", index=False)

    out = pd.DataFrame(res)
    # R14 basket view
    w = rec.Units_Base * rec.Realised_Net_Per_Unit_KZ
    basket = np.average(rec["Price_Change_%"], weights=w)
    st_mask = rec.SubGroup.fillna("").str.upper().apply(lambda s: any(k in s for k in R.STAPLES))
    staples = np.average(rec.loc[st_mask, "Price_Change_%"], weights=w[st_mask])
    cpi = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=["Inflation_MoM_Pct"]).dropna().iloc[-1, 0]
    basket_tbl = pd.DataFrame({"Measure": ["Pilot basket (40 SKUs, sales-weighted)", "Staples in the pilot",
                                           "CPI monthly inflation (latest)", "Months of inflation the basket rise equals"],
                               "Value": [basket, staples, cpi, basket / cpi]})

    # SKU status ---------------------------------------------------------------------------------------------------
    piv = out.pivot_table(index="ArticleCode", columns="Rule", values="Status", aggfunc="first")
    rank = {"FAIL": 2, "FLAG": 1, "PASS": 0}
    worst = out.assign(r=out.Status.map(rank)).groupby("ArticleCode").r.max()
    flags = out[out.Status != "PASS"].groupby("ArticleCode").Rule.apply(lambda s: ", ".join(sorted(set(x.split(" ")[0] for x in s))))
    v = rec.copy()
    v["Validation"] = worst.map({0: "Ready", 1: "Ready - decision / note", 2: "Fix needed"}).reindex(v.index)
    v.loc[~changed, "Validation"] = "Hold (no change)"
    v["Rules_Flagged"] = flags.reindex(v.index).fillna("")
    v = v.reset_index()
    v.to_parquet(CL / f"validated_prices{O.SFX}.parquet", index=False)
    summ = out.groupby(["Rule", "Status"]).size().unstack(fill_value=0)
    for c in ["PASS", "FLAG", "FAIL"]:
        if c not in summ:
            summ[c] = 0
    summ = summ[["PASS", "FLAG", "FAIL"]]
    print(summ.to_string(), flush=True)
    print(basket_tbl.round(2).to_string(index=False), flush=True)
    if len(lines):
        print(lines[["Pilot_ArticleName", "ArticleName", "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Units_Base_Remaining",
                     "GP_Change_Est_KZ"]].round(0).to_string(index=False), flush=True)
        print("line moves GP estimate (m Kz):", round(lines.GP_Change_Est_KZ.sum() / 1e6, 2), "| store rows:",
              len(line_store), flush=True)
    print(v.Validation.value_counts().to_string(), flush=True)
    nz = out[out.Status != "PASS"].copy()
    nz["ArticleName"] = nz.ArticleName.str[:30]
    print(nz[["Rule", "ArticleName", "Status", "Detail"]].to_string(index=False), flush=True)

    with pd.ExcelWriter(OUT / f"business_rules{O.SFX}.xlsx") as xw:
        summ.to_excel(xw, sheet_name="Rule summary")
        v[["Wave", "ArticleCode", "ArticleName", "Group", "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Price_Change_%",
           "Validation", "Rules_Flagged", "GP_Change_KZ"]].round(2).to_excel(xw, sheet_name="Validated list", index=False)
        nz.to_excel(xw, sheet_name="Flags and fails", index=False)
        out.to_excel(xw, sheet_name="All checks", index=False)
        s.round(2).to_excel(xw, sheet_name="Store tier check", index=False)
        basket_tbl.round(2).to_excel(xw, sheet_name="Basket view", index=False)
        lines.round(2).to_excel(xw, sheet_name="Price line moves", index=False)
        line_store.round(2).to_excel(xw, sheet_name="Price line store prices", index=False)
        pd.DataFrame({"Note": [
            "Substitutes outside the pilot (Fula and Sanodia oil, Koch Black and Seara small chicken legs) are not in "
            "the model: switching to them is counted as lost volume although the sale stays in Fresmart, so the GP "
            "gains are on the safe side.",
            "Primavera 12x1L (+1.8%) is priced like Fula 12x1L today and will be slightly above it; different brands, "
            "not a fixed price line.",
            "No competitor prices in the data: before 2 Nov, check shelf prices at Shoprite, Kero and Candando for "
            "the staples and chicken legs in the list (rice, oils, sugar, flour, milk, eggs, chicken legs).",
            "Final list = this file / clean/pilot/validated_prices.parquet (step 15 file shows pre-rule prices)."]}).to_excel(
            xw, sheet_name="Notes", index=False)
        pd.DataFrame({"Rule": [l.strip() for l in __doc__.splitlines() if re.match(r"\s*R\d+", l)]}).to_excel(
            xw, sheet_name="Rules", index=False)


if __name__ == "__main__":
    main()
