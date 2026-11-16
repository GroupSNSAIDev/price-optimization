"""Step 15 · Price optimisation for the 40 pilot SKUs (28 Sep - 27 Dec 2026, one chain-wide price per SKU)

 15.1 Demand model    own units = B (1 + d)^e (rise / cut elasticity), times the effect of each substitute's price
                      change (1 + s_j ((1 + d_j)^c - 1)), c = step 9 cross-elasticity, s_j = step 13 cap (rivals
                      recapture <= 60% of SKU j's own volume change, value-equivalent units). Cautious case: strong
                      elasticity (Low confidence: covers the sub-group prior - 1 SD); weak case: weak elasticity.
 15.2 Search          1% steps within the allowed set per SKU; substitute groups (soy oil, chicken legs, sausages, Delta
                      Q capsules, sugar, rice, Friboi beef) searched jointly by coordinate ascent, since raising all of
                      a group removes the in-store switching that a single-SKU simulation assumes
 15.3 Guardrails      analysis/pilot/optimisation_config.json: tested price range, max step, max volume loss per group
                      (cautious case for Low confidence), cautious GP must not fall, supply at risk -> no cuts, no cut
                      below cost, recently repriced -> no further rise, KVI -> hold, minimum gain, smallest move giving
                      >= 90% of the best gain
 15.4 Frontier        total GP gain vs volume loss for a range of volume caps (trade-off for management)
Outputs: clean/pilot/optimal_prices.parquet, analysis/pilot/price_optimisation.xlsx, analysis/pilot/optimisation/*.png
"""
import json
import os
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "pilot", ROOT / "analysis" / "pilot"
FIG = OUT / "optimisation"
FIG.mkdir(exist_ok=True)
PLAN = os.environ.get("PILOT_PLAN", "")                 # e.g. "sweetspot": own config and output files, current plan untouched
SFX = f"_{PLAN}" if PLAN else ""
CFG = json.load(open(OUT / f"optimisation_config{SFX}.json"))
ORIGIN = pd.Timestamp("2026-09-28")
z = lambda c: str(c).zfill(18)


def recent_repricing():
    """median weekly chain price of the last 4 weeks vs weeks 14-26 before the forecast date; weekly prices are
    unit-weighted per week, clearance weeks (price < cost / 1.5) excluded, median so one bad week cannot dominate"""
    f = pd.read_parquet(CL / "pilot_features.parquet", columns=["Week", "ArticleCode", "Units", "Price_KZ", "Unit_COGS_KZ"])
    f = f[f.Price_KZ >= f.Unit_COGS_KZ / 1.5]
    f["R"] = f.Units * f.Price_KZ
    w = f.groupby(["ArticleCode", "Week"])[["R", "Units"]].sum()
    w = (w.R / w.Units).rename("P").reset_index()

    def med(a, b):
        d = w[(w.Week >= ORIGIN - pd.Timedelta(weeks=a)) & (w.Week < ORIGIN - pd.Timedelta(weeks=b))]
        return d.groupby("ArticleCode").P.median()
    return (med(4, 0) / med(26, 13) - 1) * 100


def step_key(d):
    """grid key for a (possibly fractional) % change: elasticities depend on the direction only"""
    return 0 if d == 0 else int(np.sign(d) * max(1, round(abs(d))))


class Market:
    """precomputed per SKU and price step: elasticities, prices, costs; cross effects between substitutes"""

    def __init__(self, g, x):
        self.g = g
        self.skus = list(g.ArticleCode.unique())
        self.grid = np.sort(g["Price_Change_%"].unique())
        cur = g[g["Price_Change_%"] == 0].set_index("ArticleCode")
        self.B, self.P, self.C = cur.Baseline_Units_13w, cur.Current_Price_KZ, cur.Unit_Cost_KZ
        self.GP0 = self.B * (self.P - self.C)
        k = g.set_index(["ArticleCode", "Price_Change_%"])
        r = np.log1p(k.index.get_level_values(1) / 100)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.e_L = pd.Series(k.Elasticity_Used.values, k.index)
            self.e_S = pd.Series(np.where(r != 0, np.log(k.Units_Strong / k.Baseline_Units_13w) / r, 0), k.index)
            self.e_W = pd.Series(np.where(r != 0, np.log(k.Units_Weak / k.Baseline_Units_13w) / r, 0), k.index)
        x = x[x.Cross_Used > 0]
        self.cross = {(z(q), z(p)): c for q, p, c in zip(x.SKU_Quantity, x.SKU_Price, x.Cross_Used)}
        self.rivals = {}
        for (q, p) in self.cross:
            self.rivals.setdefault(p, []).append(q)

    def scale(self, j, d):
        """step 13 cap: rivals recapture at most 60% of SKU j's own (likely) volume change, value-equivalent"""
        if d == 0 or j not in self.rivals:
            return 1.0
        own = self.B[j] * ((1 + d / 100) ** self.e_L[(j, step_key(d))] - 1)
        equiv = sum(self.B[i] * ((1 + d / 100) ** self.cross[(i, j)] - 1) * self.P[i] / self.P[j] for i in self.rivals[j])
        return min(1.0, 0.6 * abs(own) / abs(equiv)) if equiv != 0 else 1.0

    def evaluate(self, ds):
        """ds: {sku: % change} for one substitute group (others at 0). Returns per-SKU units and GP (3 cases)"""
        rows = {}
        for i, d in ds.items():
            m = 1.0
            for j, dj in ds.items():
                if j != i and (i, j) in self.cross and dj != 0:
                    m *= 1 + self.scale(j, dj) * ((1 + dj / 100) ** self.cross[(i, j)] - 1)
            p = self.P[i] * (1 + d / 100)
            u = {c: self.B[i] * (1 + d / 100) ** e[(i, step_key(d))] * m for c, e in [("L", self.e_L), ("S", self.e_S), ("W", self.e_W)]}
            rows[i] = {"d": d, "U_L": u["L"], "U_S": u["S"], "U_W": u["W"], "Price": p,
                       "GP_L": u["L"] * (p - self.C[i]), "GP_S": u["S"] * (p - self.C[i]), "GP_W": u["W"] * (p - self.C[i])}
        return pd.DataFrame(rows).T


def allowed_steps(mk, e, supply, reprice, kvi):
    out, why = {}, {}
    for a in mk.skus:
        r = mk.g[mk.g.ArticleCode == a]
        steps = r["Price_Change_%"].values
        ok = np.abs(steps) <= CFG["max_price_step_pct"]
        notes = []
        if CFG["only_tested_price_range"]:
            ok &= r.Within_Tested_Range.values
        if supply.get(a, False):
            ok &= steps >= 0
            notes.append("supply at risk: no cut")
        if CFG["no_cut_below_unit_cost"]:
            ok &= ~((steps < 0) & (r.New_Price_KZ.values < r.Unit_Cost_KZ.values))
        if reprice.get(a, 0) > CFG["recently_repriced"]["threshold_pct"]:
            ok &= steps <= 0
            notes.append(f"repriced +{reprice[a]:.0f}% recently: no further rise")
        cap = {str(k).lstrip("0"): v for k, v in CFG.get("sku_max_rise_pct", {}).items()}.get(a.lstrip("0"))
        if cap is not None:
            ok &= steps <= cap
            notes.append(f"rise capped at +{cap}% (decision)")
        if a.lstrip("0") in [str(c).lstrip("0") for c in CFG["kvi_price_controlled"]["codes"]]:
            ok &= steps == 0
            notes.append("KVI: hold")
        ok |= steps == 0
        out[a], why[a] = list(steps[ok].astype(int)), "; ".join(notes)
    return out, why


def feasible(mk, res, e, vol_cap):
    """guardrails on a group result (all members)"""
    for i, r in res.iterrows():
        cap = vol_cap[e.at[i, "Group"]] / 100
        if str(e.at[i, "SubGroup"]).upper() in CFG.get("staple_subgroups", []):
            cap = min(cap, CFG["staple_volume_loss_pct"] / 100)
        scarce = i.lstrip("0") in CFG.get("scarcity_skus", [])      # supply-limited (import ban): current-plan guardrails
        if scarce:
            cap = CFG["scarcity_volume_loss_pct"][e.at[i, "Group"]] / 100
        if r.d > 0 and r.U_L / mk.B[i] - 1 < -cap - 1e-9:
            return False
        if (r.d > 0 and CFG["volume_check_on_cautious_case_for_low_confidence"]
                and e.at[i, "Confidence_Final"] == "Low" and r.U_S / mk.B[i] - 1 < -cap - 1e-9):
            return False
    if CFG["cautious_gp_must_not_fall"] and (res.d != 0).any():
        low = np.minimum(res.GP_S, res.GP_W).sum()
        if low < mk.GP0[res.index].sum() - 1e-6:
            return False
    return True


def optimise_group(mk, members, allowed, e, vol_cap, rounds=12):
    ds = {a: 0 for a in members}
    base = mk.evaluate(ds).GP_L.sum()
    for _ in range(rounds):
        changed = False
        for a in members:
            best, best_d = None, ds[a]
            for d in allowed[a]:
                trial = {**ds, a: d}
                res = mk.evaluate(trial)
                if not feasible(mk, res, e, vol_cap):
                    continue
                v = res.GP_L.sum()
                if best is None or v > best + 1e-6:
                    best, best_d = v, d
            if best_d != ds[a]:
                ds[a], changed = best_d, True
        if not changed:
            break
    opt = mk.evaluate(ds).GP_L.sum()
    gain = opt - base
    # smallest move: shrink each SKU toward 0 while the group keeps >= X% of the best gain and stays feasible
    keep = CFG["smallest_move_within_pct_of_best_gain"] / 100
    for a in members:
        while ds[a] != 0:
            trial = {**ds, a: ds[a] - np.sign(ds[a])}
            res = mk.evaluate(trial)
            if feasible(mk, res, e, vol_cap) and res.GP_L.sum() - base >= keep * gain:
                ds[a] = int(trial[a])
            else:
                break
    # minimum gain per SKU group: below the threshold the change is not worth making (loss-makers exempt)
    res = mk.evaluate(ds)
    gain = res.GP_L.sum() - base
    thr = max(CFG["min_gain"]["kz"], CFG["min_gain"]["pct_of_current_gp"] / 100 * abs(mk.GP0[members].sum()))
    loss_making = (mk.GP0[members] < 0).any()          # fixing a loss is worth doing however small the SKU
    if gain < thr and not (loss_making and gain > 0):
        ds = {a: 0 for a in members}
    return ds


def run(mk, groups, allowed, e, vol_cap):
    ds = {}
    for members in groups:
        ds.update(optimise_group(mk, members, allowed, e, vol_cap))
    rows = []
    for members in groups:
        rows.append(mk.evaluate({a: ds[a] for a in members}).assign(Substitute_Group=" + ".join(
            str(e.at[a, "ArticleName"])[:14].title() for a in members) if len(members) > 1 else ""))
    return pd.concat(rows)


def main():
    g = pd.read_parquet(CL / "profit_grid.parquet")
    g["Price_Change_%"] = g["Price_Change_%"].round().astype(int)
    x = pd.read_parquet(CL / "cross_elasticity.parquet")
    e = pd.read_parquet(CL / "sku_elasticity.parquet").set_index("ArticleCode")
    supply = pd.read_parquet(CL / "supply_risk.parquet").Supply_At_Risk.to_dict()
    reprice = recent_repricing().to_dict()
    mk = Market(g, x)
    allowed, why = allowed_steps(mk, e, supply, reprice, CFG)
    # substitute groups: connected SKUs through any cross effect in use
    groups, seen = [], set()
    for a in mk.skus:
        if a in seen:
            continue
        comp, stack = set(), [a]
        while stack:
            s = stack.pop()
            if s in comp:
                continue
            comp.add(s)
            stack += [q for (q, p) in mk.cross if p == s] + [p for (q, p) in mk.cross if q == s]
        comp = [c for c in comp if c in mk.skus]
        seen |= set(comp)
        groups.append(sorted(comp))
    vol_cap = CFG["max_volume_loss_pct"]
    res = run(mk, groups, allowed, e, vol_cap)

    # recommendation table -------------------------------------------------------------------------------------------
    out = pd.DataFrame(index=res.index)
    out["ArticleName"] = e.ArticleName.reindex(out.index)
    out["Group"] = e.Group.reindex(out.index)
    out["Confidence"] = e.Confidence_Final.reindex(out.index)
    out["Current_Price_KZ"], out["Unit_Cost_KZ"] = mk.P, mk.C
    out["Price_Change_%"] = res.d.astype(float)
    out["New_Price_KZ"] = res.Price.astype(float)
    out["Current_Margin_%"] = (mk.P - mk.C) / mk.P * 100
    out["New_Margin_%"] = (out.New_Price_KZ - mk.C) / out.New_Price_KZ * 100
    out["Units_Base_13w"], out["Units_New_13w"] = mk.B, res.U_L.astype(float)
    out["Units_Change_%"] = (out.Units_New_13w / out.Units_Base_13w - 1) * 100
    out["Units_Change_Cautious_%"] = (res.U_S.astype(float) / mk.B - 1) * 100
    out["Revenue_Base_KZ"], out["Revenue_New_KZ"] = mk.B * mk.P, res.U_L.astype(float) * out.New_Price_KZ
    out["GP_Base_KZ"], out["GP_New_KZ"] = mk.GP0, res.GP_L.astype(float)
    out["GP_Change_KZ"] = out.GP_New_KZ - out.GP_Base_KZ
    out["GP_Change_Cautious_KZ"] = np.minimum(res.GP_S, res.GP_W).astype(float) - mk.GP0
    out["GP_Change_Optimistic_KZ"] = np.maximum(res.GP_S, res.GP_W).astype(float) - mk.GP0
    out["Substitute_Group"] = res.Substitute_Group
    out["Supply_At_Risk"] = out.index.map(lambda a: bool(supply.get(a, False)))
    out["Recent_Price_Change_%"] = out.index.map(reprice)
    thr = CFG["recently_repriced"]["threshold_pct"]
    out["Repricing_Borderline"] = out["Recent_Price_Change_%"].between(thr - 3, thr + 3)
    out["Allowed_Range_%"] = [f"{min(allowed[a])}..{max(allowed[a])}" for a in out.index]
    out["Constraints"] = out.index.map(why)
    out.loc[out.Repricing_Borderline, "Constraints"] = out.loc[out.Repricing_Borderline, "Constraints"].map(
        lambda c: (c + "; " if c else "") + f"recent price change near the {thr}% repricing line: review")
    # what limits the move: the next 1% step further would break which guardrail?
    lim = []
    for a, r in out.iterrows():
        d = int(r["Price_Change_%"])
        nxt = d + (1 if d >= 0 else -1)
        members = next(m for m in groups if a in m)
        if nxt not in allowed[a]:
            lim.append("range / rule" if d != 0 else "no gain or rule")
            continue
        trial = {m: int(out.at[m, "Price_Change_%"]) for m in members}
        trial[a] = nxt
        t = mk.evaluate(trial)
        if not feasible(mk, t, e, vol_cap):
            lim.append("volume or downside guardrail")
        elif t.GP_L.sum() <= mk.evaluate({**trial, a: d}).GP_L.sum():
            lim.append("GP optimum")
        else:
            lim.append("smallest move / min gain")
    out["Limited_By"] = lim
    out["Action"] = np.select([out["Price_Change_%"] > 0, out["Price_Change_%"] < 0], ["Raise", "Cut"], "Hold")
    out = out.reset_index().rename(columns={"index": "ArticleCode"}).sort_values(["Group", "ArticleName"])
    out.to_parquet(CL / f"optimal_prices{SFX}.parquet", index=False)

    tot = out.groupby("Group").agg(SKUs=("ArticleCode", "size"), Raise=("Action", lambda s: (s == "Raise").sum()),
                                   Cut=("Action", lambda s: (s == "Cut").sum()), Hold=("Action", lambda s: (s == "Hold").sum()),
                                   Units_Base=("Units_Base_13w", "sum"), Units_New=("Units_New_13w", "sum"),
                                   Revenue_Base=("Revenue_Base_KZ", "sum"), Revenue_New=("Revenue_New_KZ", "sum"),
                                   GP_Base=("GP_Base_KZ", "sum"), GP_New=("GP_New_KZ", "sum"),
                                   GP_Change_Cautious=("GP_Change_Cautious_KZ", "sum"))
    tot.loc["Total"] = tot.sum()
    tot["Units_Change_%"] = (tot.Units_New / tot.Units_Base - 1) * 100
    tot["Revenue_Change_%"] = (tot.Revenue_New / tot.Revenue_Base - 1) * 100
    tot["GP_Change_KZ"] = tot.GP_New - tot.GP_Base
    tot["GP_Change_%"] = tot.GP_Change_KZ / tot.GP_Base * 100
    tot["Margin_Base_%"], tot["Margin_New_%"] = tot.GP_Base / tot.Revenue_Base * 100, tot.GP_New / tot.Revenue_New * 100

    # 15.4 frontier: same rules, different volume caps ---------------------------------------------------------------
    fr = []
    for cap in CFG["frontier_volume_caps_pct"]:
        r = run(mk, groups, allowed, e, {k: cap for k in vol_cap})
        u, gp = r.U_L.astype(float), r.GP_L.astype(float)
        fr.append({"Volume_Cap_%": cap, "SKUs_Changed": int((r.d != 0).sum()),
                   "Units_Change_%": (u.sum() / mk.B.sum() - 1) * 100,
                   "Revenue_Change_%": ((u * r.Price.astype(float)).sum() / (mk.B * mk.P).sum() - 1) * 100,
                   "GP_Change_KZ": gp.sum() - mk.GP0.sum(),
                   "GP_Change_Cautious_KZ": (np.minimum(r.GP_S, r.GP_W).astype(float) - mk.GP0[r.index]).sum()})
        print(f"cap {cap}%: {fr[-1]}", flush=True)
    fr = pd.DataFrame(fr)

    print(tot.round(1).to_string(), flush=True)
    show = out[["Group", "ArticleName", "Confidence", "Price_Change_%", "Units_Change_%", "Units_Change_Cautious_%",
                "GP_Change_KZ", "GP_Change_Cautious_KZ", "Limited_By", "Constraints"]].copy()
    show["ArticleName"] = show.ArticleName.str[:34]
    show[["GP_Change_KZ", "GP_Change_Cautious_KZ"]] /= 1e6
    print(show.round(1).to_string(index=False), flush=True)

    with pd.ExcelWriter(OUT / f"price_optimisation{SFX}.xlsx") as xw:
        tot.round(1).to_excel(xw, sheet_name="Summary by group")
        out.round(2).to_excel(xw, sheet_name="Recommended prices", index=False)
        fr.round(2).to_excel(xw, sheet_name="Volume vs GP frontier", index=False)
        pd.DataFrame({"Substitute group": [" + ".join(str(e.at[a, "ArticleName"])[:30] for a in m)
                                           for m in groups if len(m) > 1]}).to_excel(xw, sheet_name="Joint groups", index=False)
        pd.Series({k: json.dumps(v) for k, v in CFG.items()}).to_frame("Setting").to_excel(xw, sheet_name="Guardrails")

    # charts ---------------------------------------------------------------------------------------------------------
    col = {"A": "#156082", "B": "#E97132", "C": "#196B24", "D": "#A02B93"}
    s = out.sort_values("Price_Change_%")
    fig, ax = plt.subplots(figsize=(9, 10))
    ax.barh([str(n).title()[:36] for n in s.ArticleName], s["Price_Change_%"], color=[col[x] for x in s.Group])
    for i, (_, r) in enumerate(s.iterrows()):
        ax.text(r["Price_Change_%"] + (0.2 if r["Price_Change_%"] >= 0 else -0.2), i,
                f"{r.GP_Change_KZ/1e6:+.1f}m", va="center", ha="left" if r["Price_Change_%"] >= 0 else "right", fontsize=6)
    ax.axvline(0, color="k", lw=.6)
    ax.set_xlabel("recommended price change, % (label: GP change over 13 weeks, Kz)")
    ax.tick_params(labelsize=7)
    fig.savefig(FIG / f"15_recommended_changes{SFX}.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(-fr["Units_Change_%"], fr.GP_Change_KZ / 1e6, marker="o", color="#156082", label="likely")
    ax.plot(-fr["Units_Change_%"], fr.GP_Change_Cautious_KZ / 1e6, marker="o", ls="--", color="#E97132", label="cautious")
    for _, r in fr.iterrows():
        ax.annotate(f"cap {r['Volume_Cap_%']:.0f}%", (-r["Units_Change_%"], r.GP_Change_KZ / 1e6), fontsize=7,
                    xytext=(4, -10), textcoords="offset points")
    ax.set_xlabel("volume lost across the 40 SKUs, %")
    ax.set_ylabel("GP gain over 13 weeks, m Kz")
    ax.legend()
    ax.set_title("GP gain vs volume given up")
    fig.savefig(FIG / f"15_frontier{SFX}.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
