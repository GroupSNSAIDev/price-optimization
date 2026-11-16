"""Step 16 · Recommendation engine: from optimal % changes to shelf prices, rollout plan, test design and monitoring

 16.1 Shelf price     current shelf price incl. IVA per sales pack (latest price record, store mode; no change since
                      the forecast date). Target = shelf x (1 + optimal change), rounded to Fresmart's price endings
                      (...9 below 10,000 Kz, ...99 above, shown as X.99 like the price file). The rounded change must
                      stay in the SKU's allowed steps and pass the step 15 guardrails for its substitute group;
                      otherwise it moves one price point toward the current price.
 16.2 Timing          effective Mon 2 Nov 2026; impact re-stated for the 8 remaining forecast weeks (2 Nov - 27 Dec).
 16.3 Rollout         TEST: chicken legs (61% of the gain, Low-confidence category response) in matched test stores
                      only; WAVE 1: other rises chain-wide (staples flagged to confirm they are not price-controlled);
                      REVIEW: recent price change near the 15% line; HOLD: with the reason.
 16.4 Test design     matched store pairs (channel, zone, chicken-leg volume), random assignment within pairs;
                      power from placebo tests on 2025-26 history (difference-in-differences of log units).
 16.5 Monitoring      expected weekly units per SKU with cautious / optimistic band; roll-back trigger.
Outputs: clean/pilot/recommendations.parquet, analysis/pilot/recommendations.xlsx, analysis/pilot/recommend/*.png
"""
import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import pilot_optimise as O

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "pilot", ROOT / "analysis" / "pilot"
FIG = OUT / "recommend"
FIG.mkdir(exist_ok=True)
EFFECTIVE = pd.Timestamp("2026-11-02")
TEST_SKUS = ["100501", "100423", "107620", "100520", "107637"]          # all chicken leg quarters in the pilot
STAPLES = ["RICE", "OIL", "SUGAR", "MILK", "EGGS", "FLOUR"]
B2B = ["HRCA"]                                       # hotel / restaurant channel: negotiated prices, not in scope
WHOLESALE = ["HDDS", "HDS2", "HDS3", "HDS4"]         # traders: no staple rises, not in the chicken leg test
OFF_TIER_PCT = 12                                    # store price this far from the chain price: check first
SEED = 2026


def shelf_prices(codes):
    p = pd.read_parquet(ROOT / "clean" / "price_changes.parquet")
    p["c"] = p.ArticleCode.astype(str).str.lstrip("0")
    q = p[p.c.isin(codes) & p.Primary_UOM & ~p.Is_Spike].sort_values("EffectiveTS")
    last = q.groupby(["Plant", "c"]).tail(1)
    g = last.groupby("c")
    s = pd.DataFrame({"Sales_UOM": g.SalesUOM.agg(lambda x: x.mode()[0]), "Units_Per_Pack": g.Factor.median(),
                      "IVA_%": g.IVA.median(), "Shelf_Price_KZ": g.PriceIVA.agg(lambda x: x.mode()[0]),
                      "Stores_Priced": g.Plant.nunique(), "Last_Price_Record": g.EffectiveTS.max()})
    s["Stores_At_Main_Price_%"] = g.apply(lambda d: (d.PriceIVA == d.PriceIVA.mode()[0]).mean() * 100)
    return s, last


def price_points(t):
    """Fresmart endings: ...9.99-style below 10,000 Kz (step 10), ...99.99-style above (step 100)"""
    step = 10 if t < 10000 else 100
    k = np.floor(t / step)
    return [(k + i) * step - 0.01 for i in (-1, 0, 1, 2)]


def round_shelf(cur, d):
    """nearest price point to the target, never on the other side of the current price"""
    t = cur * (1 + d / 100)
    pts = [x for x in price_points(t) if (x > cur if d > 0 else x < cur)]
    return min(pts, key=lambda x: abs(x - t)) if pts else cur


def remaining_share(base):
    b = base.groupby(["ArticleCode", "Week"]).Baseline_Units.sum().reset_index()
    tot = b.groupby("ArticleCode").Baseline_Units.sum()
    rem = b[b.Week >= EFFECTIVE].groupby("ArticleCode").Baseline_Units.sum()
    return (rem / tot).fillna(0), b


def test_design(f, members):
    """matched pairs and placebo power for the chicken leg test"""
    z = O.z
    d = f[f.ArticleCode.isin([z(c) for c in members])]
    w = d.groupby(["Plant", "Week"]).Units.sum().unstack(fill_value=0)
    recent = w.loc[:, w.columns >= O.ORIGIN - pd.Timedelta(weeks=13)]
    vol = recent.mean(axis=1)
    st = f.drop_duplicates("Plant").set_index("Plant")
    zone_cols = [c for c in f.columns if c.startswith("Zone_")]
    info = pd.DataFrame({"Weekly_Units_13w": vol,
                         "Zone": st[zone_cols].idxmax(axis=1).str.replace("Zone_", "").reindex(vol.index),
                         "Channel": np.where(st.Channel_HDDS.reindex(vol.index) == 1, "HDDS", "Store")})
    info = info[(recent > 0).sum(axis=1) >= 10]                     # stores selling chicken legs steadily
    info = info[~info.index.isin(B2B + WHOLESALE)]                  # retail stores only
    rng = np.random.default_rng(SEED)
    pairs, used = [], set()
    for ch, grp in info.groupby("Channel"):
        grp = grp.sort_values("Weekly_Units_13w")
        ids = list(grp.index)
        while len(ids) >= 2:
            a = ids.pop(0)
            # partner: nearest in volume from a DIFFERENT zone (within the next 4), so neighbouring stores share a
            # price and customers cannot switch between a test and its control store
            cand = ids[:4]
            other = [c for c in cand if grp.at[c, "Zone"] != grp.at[a, "Zone"]]
            b = other[0] if other else cand[0]
            ids.remove(b)
            t, c = (a, b) if rng.random() < 0.5 else (b, a)
            pairs.append({"Pair": len(pairs) + 1, "Channel": ch, "Test_Store": t, "Control_Store": c,
                          "Test_Zone": grp.at[t, "Zone"], "Control_Zone": grp.at[c, "Zone"],
                          "Test_Weekly_Units": grp.at[t, "Weekly_Units_13w"],
                          "Control_Weekly_Units": grp.at[c, "Weekly_Units_13w"]})
    pairs = pd.DataFrame(pairs)
    # placebo power: random pairings' assignment flips on past windows (no price test happened)
    # 2026 windows only: in 2025 the chain was opening stores, whose ramp-up is not representative of a test now
    weeks = [c for c in w.columns if pd.Timestamp("2026-01-05") <= c <= O.ORIGIN - pd.Timedelta(weeks=8)]
    power = []
    for n_post in (4, 6, 8):
        est, used = [], []
        for s0 in weeks:
            # log change of average weekly units, post vs pre (period totals: robust to single zero weeks)
            pre = w.loc[:, (w.columns >= s0 - pd.Timedelta(weeks=8)) & (w.columns < s0)].mean(axis=1)
            post = w.loc[:, (w.columns >= s0) & (w.columns < s0 + pd.Timedelta(weeks=n_post))].mean(axis=1)
            ch = np.log((post + 1) / (pre + 1))
            # stock-gap rule (also used when the real test is read): a store with any week below 25% of its usual
            # level in the window is left out with its pair
            win = w.loc[:, (w.columns >= s0 - pd.Timedelta(weeks=8)) & (w.columns < s0 + pd.Timedelta(weeks=n_post))]
            clean = win.min(axis=1) >= 0.25 * win.median(axis=1)
            ok = pairs[pairs.Test_Store.isin(ch.index) & pairs.Control_Store.isin(ch.index)]
            ok = ok[ok.Test_Store.map(clean).fillna(False) & ok.Control_Store.map(clean).fillna(False)]
            used.append(len(ok))
            diff = ch.reindex(ok.Test_Store).values - ch.reindex(ok.Control_Store).values
            for _ in range(40):
                v = diff * rng.choice([-1, 1], size=len(diff))
                lo, hi = np.quantile(v, [0.1, 0.9])
                est.append(v[(v >= lo) & (v <= hi)].mean())          # 10% trimmed mean, the reading rule
        sd = np.std(est)
        power.append({"Test_Weeks": n_post, "Pairs": len(pairs), "Pairs_Usable_Avg": np.mean(used),
                      "Placebo_SD_%": sd * 100,
                      "Min_Detectable_Change_%": 2.8 * sd * 100, "Placebo_Runs": len(est)})
    return pairs, pd.DataFrame(power), info


def main():
    cfg = O.CFG
    opt = pd.read_parquet(CL / "optimal_prices.parquet").set_index("ArticleCode")
    g = pd.read_parquet(CL / "profit_grid.parquet")
    g["Price_Change_%"] = g["Price_Change_%"].round().astype(int)
    x = pd.read_parquet(CL / "cross_elasticity.parquet")
    e = pd.read_parquet(CL / "sku_elasticity.parquet").set_index("ArticleCode")
    base = pd.read_parquet(CL / "baseline_forecast.parquet")
    f = pd.read_parquet(CL / "pilot_features.parquet")
    supply = pd.read_parquet(CL / "supply_risk.parquet").Supply_At_Risk.to_dict()
    mk = O.Market(g, x)
    allowed, why = O.allowed_steps(mk, e, supply, O.recent_repricing().to_dict(), cfg)
    codes = [a.lstrip("0") for a in opt.index]
    shelf, store_prices = shelf_prices(codes)
    shelf.index = [O.z(c) for c in shelf.index]

    # 16.1 rounding to shelf price points, then re-check the guardrails per substitute group --------------------------
    groups = {}
    for a in opt.index:
        sg = opt.at[a, "Substitute_Group"]
        groups.setdefault(sg if sg else a, []).append(a)
    final = {}
    for key, members in groups.items():
        new = {}
        for a in members:
            d = float(opt.at[a, "Price_Change_%"])
            cur = shelf.at[a, "Shelf_Price_KZ"]
            new[a] = round_shelf(cur, d) if d != 0 else cur
        for _ in range(10):
            ds = {a: (new[a] / shelf.at[a, "Shelf_Price_KZ"] - 1) * 100 for a in members}
            bad = [a for a in members if ds[a] != 0 and (not (min(allowed[a]) - 0.5 <= ds[a] <= max(allowed[a]) + 0.5)
                                                       or abs(ds[a]) > cfg["max_price_step_pct"])]
            res = mk.evaluate(ds)
            if not bad and O.feasible(mk, res, e, cfg["max_volume_loss_pct"]):
                break
            # move the largest change one price point toward the current price
            a = bad[0] if bad else max(members, key=lambda m: abs(ds[m]))
            cur = shelf.at[a, "Shelf_Price_KZ"]
            lower = [p for p in price_points(new[a]) if cur < p < new[a]] if new[a] > cur else \
                [p for p in price_points(new[a]) if new[a] < p < cur]
            new[a] = (max(lower) if new[a] > cur else min(lower)) if lower else cur
        # step 17 decisions: fixed shelf prices (price order, thresholds) replace the rounded ones
        ov = {O.z(k): v for k, v in cfg.get("shelf_price_overrides", {}).items()}
        for a in members:
            if a in ov:
                new[a] = ov[a]
        ds = {a: (new[a] / shelf.at[a, "Shelf_Price_KZ"] - 1) * 100 for a in members}
        final.update({a: (new[a], ds[a]) for a in members})

    rec = pd.DataFrame(index=opt.index)
    rec["ArticleName"], rec["Group"], rec["Confidence"] = opt.ArticleName, opt.Group, opt.Confidence
    rec["SubGroup"] = e.SubGroup.reindex(rec.index)
    rec = rec.join(shelf)
    rec["Optimal_Change_%"] = opt["Price_Change_%"]
    rec["New_Shelf_Price_KZ"] = [final[a][0] for a in rec.index]
    rec["Price_Change_%"] = [final[a][1] for a in rec.index]
    rec["Price_Change_Per_Pack_KZ"] = rec.New_Shelf_Price_KZ - rec.Shelf_Price_KZ
    rec["New_Shelf_Price_Per_Unit_KZ"] = rec.New_Shelf_Price_KZ / rec.Units_Per_Pack

    # impact of the rounded changes, by substitute group, for the weeks from the effective date
    share, weekly = remaining_share(base)
    rows = []
    for members in groups.values():
        r = mk.evaluate({a: rec.at[a, "Price_Change_%"] for a in members})
        rows.append(r)
    r = pd.concat(rows)
    sh = share.reindex(rec.index).fillna(0)
    rec["Weeks_Remaining"] = int(((pd.Timestamp("2026-12-28") - EFFECTIVE).days) // 7)
    rec["Units_Base"] = mk.B * sh
    rec["Units_Change_%"] = (r.U_L.astype(float) / mk.B - 1) * 100
    rec["Units_Change_Cautious_%"] = (r.U_S.astype(float) / mk.B - 1) * 100
    rec["Units_Change"] = (r.U_L.astype(float) - mk.B) * sh
    rec["Revenue_Change_KZ"] = (r.U_L.astype(float) * r.Price.astype(float) - mk.B * mk.P) * sh
    rec["GP_Change_KZ"] = (r.GP_L.astype(float) - mk.GP0) * sh
    rec["GP_Change_Cautious_KZ"] = (np.minimum(r.GP_S, r.GP_W).astype(float) - mk.GP0) * sh
    rec["GP_Change_Optimistic_KZ"] = (np.maximum(r.GP_S, r.GP_W).astype(float) - mk.GP0) * sh
    fx = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=["FX_BNA_Avg"]).dropna().FX_BNA_Avg.iloc[-1]
    rec["GP_Change_USD"] = rec.GP_Change_KZ / fx

    # 16.3 rollout ----------------------------------------------------------------------------------------------------
    is_test = rec.index.str.lstrip("0").isin(TEST_SKUS)
    staple = rec.SubGroup.fillna("").str.upper().apply(lambda s: any(k in s for k in STAPLES))
    review = opt.Repricing_Borderline.reindex(rec.index).fillna(False)
    rec["Wave"] = np.select([rec["Price_Change_%"] == 0, is_test, review],
                            ["Hold", "Test (chicken legs, test stores only)", "Review then Wave 1"], "Wave 1 (chain-wide)")
    rec.loc[is_test & (rec["Price_Change_%"] == 0), "Wave"] = "Hold"
    rec["Confirm_Not_Price_Controlled"] = staple & (rec["Price_Change_%"] != 0)
    rec["Supply_At_Risk"] = opt.Supply_At_Risk
    rec["Effective_Date"] = np.where(rec.Wave == "Hold", "", str(EFFECTIVE.date()))

    def reason(a, r):
        if r["Price_Change_%"] == 0:
            c = str(opt.at[a, "Constraints"])
            if "repriced" in c:
                return "Hold: " + c.split(";")[[i for i, s in enumerate(c.split(";")) if "repriced" in s][0]].strip()
            if r.Supply_At_Risk:
                return "Hold: short of stock (no cut) and a rise does not add profit"
            return "Hold: profit falls with a price move in either direction (price-sensitive at a healthy margin)"
        el = e.at[a, "Rise_Final"]
        m = opt.at[a, "Current_Margin_%"]
        txt = (f"+{r['Price_Change_%']:.1f}%: margin {m:.0f}%, customers lose about {-r['Units_Change_%']:.0f}% of units "
               f"(elasticity {el:.1f}, {r.Confidence.lower()} confidence); a rise pays while volume falls less than "
               f"{r['Price_Change_%'] / (m + r['Price_Change_%']) * 100:.0f}%")
        if r.Confidence == "Low":
            txt += f"; cautious case {r['Units_Change_Cautious_%']:.0f}% units"
        return txt
    rec["Rationale"] = [reason(a, r) for a, r in rec.iterrows()]
    rec = rec.reset_index().rename(columns={"index": "ArticleCode"}).sort_values(["Wave", "Group", "ArticleName"])
    rec.to_parquet(CL / "recommendations.parquet", index=False)

    # per-store new shelf prices (stores off the main price keep their own level, same % change, same endings)
    sp = store_prices[["Plant", "c", "SalesUOM", "PriceIVA"]].rename(columns={"c": "ArticleCode", "PriceIVA": "Shelf_Price_KZ"})
    sp["ArticleCode"] = sp.ArticleCode.map(O.z)
    sp = sp.merge(rec[["ArticleCode", "ArticleName", "Price_Change_%", "Wave"]], on="ArticleCode")
    sp = sp[(sp.Wave != "Hold") & ~sp.Plant.isin(B2B)]
    sp["New_Shelf_Price_KZ"] = [round_shelf(p, d) for p, d in zip(sp.Shelf_Price_KZ, sp["Price_Change_%"])]
    main = sp.ArticleCode.map(rec.set_index("ArticleCode").Shelf_Price_KZ)
    sp["Vs_Chain_Price_%"] = (sp.Shelf_Price_KZ / main - 1) * 100
    is_staple = sp.ArticleCode.map(rec.set_index("ArticleCode").Confirm_Not_Price_Controlled).fillna(False)
    rules = [(sp.Plant.isin(WHOLESALE) & is_staple, "No change: wholesale store, staple"),
             (sp["Vs_Chain_Price_%"].abs() > OFF_TIER_PCT,
              f"No change: store price over {OFF_TIER_PCT}% from the chain price - check with pricing first")]
    sp["Store_Note"] = ""
    for m, txt in rules:
        sp.loc[m & (sp.Store_Note == ""), "Store_Note"] = txt
    sp.loc[sp.Store_Note != "", "New_Shelf_Price_KZ"] = sp.loc[sp.Store_Note != "", "Shelf_Price_KZ"]
    sp["Change"] = sp.Store_Note == ""
    # impacts only where prices change: share of each SKU's remaining baseline in the changing stores
    bw = base[base.Week >= EFFECTIVE].groupby(["ArticleCode", "Plant"]).Baseline_Units.sum().reset_index()
    chg = sp[sp.Change][["ArticleCode", "Plant"]].assign(c=True)
    bw = bw.merge(chg, on=["ArticleCode", "Plant"], how="left")
    cov = bw.assign(u=bw.Baseline_Units * bw.c.fillna(False)).groupby("ArticleCode").u.sum() /         bw.groupby("ArticleCode").Baseline_Units.sum()
    k = rec.set_index("ArticleCode")
    cov = cov.reindex(k.index).fillna(0).where(k["Price_Change_%"] != 0, 1.0)
    rec["Store_Coverage_%"] = rec.ArticleCode.map(cov * 100)
    for c in ["Units_Change", "Revenue_Change_KZ", "GP_Change_KZ", "GP_Change_Cautious_KZ", "GP_Change_Optimistic_KZ",
              "GP_Change_USD"]:
        rec[c] = rec[c] * rec.ArticleCode.map(cov)
    rec.to_parquet(CL / "recommendations.parquet", index=False)

    # 16.4 test design ------------------------------------------------------------------------------------------------
    pairs, power, sinfo = test_design(f, TEST_SKUS)
    t = rec[rec.Wave.str.startswith("Test")]
    exp_l = (t.Units_Base * t["Units_Change_%"] / 100).sum() / t.Units_Base.sum() * 100
    exp_c = (t.Units_Base * t["Units_Change_Cautious_%"] / 100).sum() / t.Units_Base.sum() * 100
    test_sp = sp[sp.Plant.isin(pairs.Test_Store) & sp.ArticleCode.str.lstrip("0").isin(TEST_SKUS) & sp.Change]
    decision = pd.DataFrame({"Item": [
        "Stores", "Duration", "Primary KPI", "Secondary KPIs", "Expected effect", "Detectable effect",
        "Roll out if", "Roll back if", "Christmas", "Stock gaps"], "Rule": [
        f"{len(pairs)} matched pairs: {len(pairs)} test stores get the new chicken leg prices, {len(pairs)} control "
        "stores keep current prices (random within pairs)",
        "4 weeks: 2 - 29 Nov 2026 (8 weeks before as the comparison); a longer test does not detect more because "
        "store trends drift apart",
        "chicken leg units and GP per store-week: per pair, log change (4 test weeks vs 8 weeks before) in the test "
        "store minus the control store; 10% trimmed mean across pairs",
        "chicken leg revenue; other chicken / protein units (switching); store transactions",
        f"likely {exp_l:.1f}% units, cautious {exp_c:.1f}%",
        f"about {power.set_index('Test_Weeks').at[4, 'Min_Detectable_Change_%']:.1f}% after 4 weeks (80% power, 5% test)",
        "the test-control difference is not below the detectable limit (no collapse) and GP per store-week is up; "
        "the test confirms no large loss, it cannot measure a 2% change",
        "test-control difference below -15% after 2 weeks, or a supply problem distorts the test",
        "decide on 30 Nov; if passed roll out chain-wide from 7 Dec for the Christmas weeks, else return test stores",
        "a pair is left out of the reading if either store has a week below 25% of its usual chicken leg units"]})

    # 16.5 monitoring: expected weekly units at the new prices, from the effective date --------------------------------
    w = weekly[weekly.Week >= EFFECTIVE].copy()
    k = rec.set_index("ArticleCode")
    w["Expected_Units"] = w.Baseline_Units * (1 + w.ArticleCode.map(k["Units_Change_%"]) / 100)
    w["Low_Band"] = w.Baseline_Units * (1 + np.minimum(w.ArticleCode.map(k["Units_Change_Cautious_%"]),
                                                       w.ArticleCode.map(k["Units_Change_%"])) / 100) * 0.78
    w["High_Band"] = w.Baseline_Units * (1 + w.ArticleCode.map(k["Units_Change_%"]) / 100) * 1.22
    w["ArticleName"] = w.ArticleCode.map(k.ArticleName)
    w["Wave"] = w.ArticleCode.map(k.Wave)
    mon_rule = pd.DataFrame({"Rule": [
        "Weekly: actual chain units per SKU vs Expected_Units; the band = cautious elasticity case and the baseline "
        "error (about +/-22% per SKU-month)",
        "Below Low_Band 2 weeks in a row (and stock available): review the price; 3 weeks: roll back",
        "Above High_Band: check stock and competitor moves; no action on price",
        "Cost change > 5% or a competitor move on a staple: re-run steps 13-15 for that SKU"]})

    # summary ----------------------------------------------------------------------------------------------------------
    summ = rec.groupby("Wave").agg(SKUs=("ArticleCode", "size"), Units_Base=("Units_Base", "sum"),
                                   Units_Change=("Units_Change", "sum"), Revenue_Change_KZ=("Revenue_Change_KZ", "sum"),
                                   GP_Change_KZ=("GP_Change_KZ", "sum"), GP_Change_Cautious_KZ=("GP_Change_Cautious_KZ", "sum"))
    summ.loc["Total"] = summ.sum()
    summ["Units_Change_%"] = summ.Units_Change / summ.Units_Base * 100
    summ["GP_Change_USD"] = summ.GP_Change_KZ / fx
    print(summ.round(0).to_string(), flush=True)
    print(power.round(2).to_string(index=False), flush=True)
    print(f"test SKUs expected units: likely {exp_l:.1f}%, cautious {exp_c:.1f}%", flush=True)
    print(pairs.head(8).to_string(index=False), flush=True)
    show = rec[["Wave", "ArticleName", "Sales_UOM", "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Optimal_Change_%",
                "Price_Change_%", "GP_Change_KZ", "Confirm_Not_Price_Controlled"]].copy()
    show["ArticleName"] = show.ArticleName.str[:30]
    show["GP_Change_KZ"] /= 1e6
    print(show.round(2).to_string(index=False), flush=True)

    with pd.ExcelWriter(OUT / "recommendations.xlsx") as xw:
        summ.round(0).to_excel(xw, sheet_name="Summary by wave")
        cols = ["Wave", "Effective_Date", "ArticleCode", "ArticleName", "Group", "Sales_UOM", "Units_Per_Pack", "IVA_%",
                "Shelf_Price_KZ", "New_Shelf_Price_KZ", "Price_Change_Per_Pack_KZ", "Price_Change_%", "Optimal_Change_%",
                "Stores_At_Main_Price_%", "Store_Coverage_%", "Confirm_Not_Price_Controlled", "Supply_At_Risk", "Confidence", "Rationale"]
        rec[cols].round(2).to_excel(xw, sheet_name="Price change list", index=False)
        rec[["Wave", "ArticleCode", "ArticleName", "Group", "Confidence", "Price_Change_%", "Weeks_Remaining",
             "Units_Base", "Units_Change", "Units_Change_%", "Units_Change_Cautious_%", "Revenue_Change_KZ",
             "GP_Change_KZ", "GP_Change_Cautious_KZ", "GP_Change_Optimistic_KZ", "GP_Change_USD"]].round(2).to_excel(
            xw, sheet_name="Impact (2 Nov - 27 Dec)", index=False)
        sp.round(2).to_excel(xw, sheet_name="Store price list", index=False)
        decision.to_excel(xw, sheet_name="Chicken leg test plan", index=False)
        pairs.round(1).to_excel(xw, sheet_name="Test-control pairs", index=False)
        power.round(2).to_excel(xw, sheet_name="Test power (placebo)", index=False)
        test_sp.round(2).to_excel(xw, sheet_name="Test store prices", index=False)
        w.round(1).to_excel(xw, sheet_name="Monitoring weekly", index=False)
        mon_rule.to_excel(xw, sheet_name="Monitoring rules", index=False)

    # charts
    col = {"A": "#156082", "B": "#E97132", "C": "#196B24", "D": "#A02B93"}
    s = rec[rec["Price_Change_%"] != 0].sort_values("GP_Change_KZ")
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.barh([str(n).title()[:34] for n in s.ArticleName], s.GP_Change_KZ / 1e6, color=[col[x] for x in s.Group])
    ax.errorbar(s.GP_Change_KZ / 1e6, range(len(s)), xerr=[(s.GP_Change_KZ - s.GP_Change_Cautious_KZ) / 1e6,
                (s.GP_Change_Optimistic_KZ - s.GP_Change_KZ).clip(lower=0) / 1e6], fmt="none", ecolor="#555", lw=.8)
    for i, (_, r) in enumerate(s.iterrows()):
        ax.text(0, i, f" {r['Price_Change_%']:+.1f}%  {r.Wave.split(' ')[0]}", va="center", fontsize=6, color="white"
                if r.GP_Change_KZ / 1e6 > 8 else "k")
    ax.set_xlabel("GP change 2 Nov - 27 Dec 2026, m Kz (bar = likely, line = cautious to optimistic)")
    ax.tick_params(labelsize=7)
    fig.savefig(FIG / "16_recommendations.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
