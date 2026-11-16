"""Step 14 · Revenue and gross profit at every simulated price for the 40 pilot SKUs (28 Sep - 27 Dec 2026)

 14.1 Current position   13-week baseline revenue, gross profit (GP) and margin at the current price and unit cost
 14.2 Price grid         for each price point (-15..+15%): revenue = units x new price, GP = units x (new price - unit
                         cost), margin; change vs the current price; low / likely / high from the elasticity range
 14.3 Rival effect       GP gained or lost on substitute SKUs (step 13, capped at 60% of own volume change) ->
                         net GP change = own + rivals
 14.4 Cost drift         GP with unit cost rising at the latest monthly CPI inflation over the 13 weeks
 14.5 Break-even         largest volume loss a price rise can absorb and still keep GP: d / (m + d), m = margin
Prices are net sales prices (ex VAT/IVA), costs are COGS per base unit, both sales-weighted over the last 4 weeks.
USD at the latest BNA rate. Only points within the tested price range (step 13 fix 2) are eligible for step 15.
Outputs: clean/pilot/profit_grid.parquet, analysis/pilot/revenue_profit.xlsx, analysis/pilot/profit/*.png
"""
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
FIG = OUT / "profit"
FIG.mkdir(exist_ok=True)
H = 13


def macro():
    w = pd.read_parquet(ROOT / "clean" / "weekly_model.parquet", columns=["Week", "FX_BNA_Avg", "Inflation_MoM_Pct"])
    w = w.dropna().sort_values("Week").iloc[-1]
    return float(w.FX_BNA_Avg), float(w.Inflation_MoM_Pct) / 100, w.Week.date()


def cost_drift_factor(base, mom):
    """unit-weighted average cost multiplier over the horizon when cost rises mom per month from the forecast date"""
    b = base.groupby(["ArticleCode", "Week"]).Baseline_Units.sum().reset_index()
    t0 = b.Week.min()
    b["k"] = (1 + mom) ** (((b.Week - t0).dt.days + 3.5) / 30.4)
    return b.groupby("ArticleCode").apply(lambda d: np.average(d.k, weights=d.Baseline_Units))


def main():
    fx, mom, macro_week = macro()
    g = pd.read_parquet(CL / "simulation_grid.parquet")
    base = pd.read_parquet(CL / "baseline_forecast.parquet")
    drift = cost_drift_factor(base, mom)

    p, c = g.New_Price_KZ, g.Unit_Cost_KZ
    for lab in ["Likely", "Strong", "Weak"]:
        g[f"Revenue_{lab}_KZ"] = g[f"Units_{lab}"] * p
        g[f"GP_{lab}_KZ"] = g[f"Units_{lab}"] * (p - c)
    g["Margin_%"] = (p - c) / p * 100
    cur = g[g["Price_Change_%"] == 0].set_index("ArticleCode")
    k = g.ArticleCode
    g["Revenue_Change_KZ"] = g.Revenue_Likely_KZ - k.map(cur.Revenue_Likely_KZ)
    g["GP_Change_KZ"] = g.GP_Likely_KZ - k.map(cur.GP_Likely_KZ)
    g["GP_Change_Low_KZ"] = np.minimum(g.GP_Strong_KZ, g.GP_Weak_KZ) - k.map(cur.GP_Likely_KZ)
    g["GP_Change_High_KZ"] = np.maximum(g.GP_Strong_KZ, g.GP_Weak_KZ) - k.map(cur.GP_Likely_KZ)
    g["Net_GP_Change_KZ"] = g.GP_Change_KZ + g.Rival_GP_Change_KZ
    g["Net_Revenue_Change_KZ"] = g.Revenue_Change_KZ + g.Rival_Revenue_Change_KZ
    base_gp = k.map(cur.GP_Likely_KZ)
    g["GP_Change_%"] = np.where(base_gp.abs() > 0, g.GP_Change_KZ / base_gp.abs() * 100, np.nan)
    g["Revenue_Change_%"] = g.Revenue_Change_KZ / k.map(cur.Revenue_Likely_KZ) * 100
    # cost drift: unit cost rising with CPI over the horizon, price held at the grid level
    g["Unit_Cost_Drift_KZ"] = c * k.map(drift)
    g["GP_Likely_CostDrift_KZ"] = g.Units_Likely * (p - g.Unit_Cost_Drift_KZ)
    g["Net_GP_Change_CostDrift_KZ"] = (g.GP_Likely_CostDrift_KZ - k.map(
        g[g["Price_Change_%"] == 0].set_index("ArticleCode").GP_Likely_CostDrift_KZ)) + g.Rival_GP_Change_KZ
    # break-even volume loss for a price rise d at the current margin m: units may fall by d / (m + d)
    m0 = k.map(cur["Margin_%"]) / 100
    d = g["Price_Change_%"] / 100
    g["BreakEven_Volume_Change_%"] = np.where(d != 0, -d / (m0 + d) * 100, 0.0)
    g.loc[(m0 + d) <= 0, "BreakEven_Volume_Change_%"] = np.nan     # still loss-making at the new price
    for col in ["Revenue_Likely_KZ", "GP_Likely_KZ", "Revenue_Change_KZ", "GP_Change_KZ", "Net_GP_Change_KZ",
                "Rival_GP_Change_KZ", "GP_Change_Low_KZ", "GP_Change_High_KZ", "Net_GP_Change_CostDrift_KZ"]:
        g[col.replace("_KZ", "_USD")] = g[col] / fx
    g.to_parquet(CL / "profit_grid.parquet", index=False)

    # 14.1 current position -----------------------------------------------------------------------------------------
    pos = g[g["Price_Change_%"] == 0].reset_index(drop=True)[["ArticleCode", "ArticleName", "Group", "Confidence", "Supply_At_Risk", "Current_Price_KZ",
                             "Unit_Cost_KZ", "Margin_%", "Units_Likely", "Revenue_Likely_KZ", "GP_Likely_KZ",
                             "GP_Likely_CostDrift_KZ", "Tested_Down_%", "Tested_Up_%"]]
    pos = pos.rename(columns={"Units_Likely": "Units_13w", "Revenue_Likely_KZ": "Revenue_13w_KZ",
                              "GP_Likely_KZ": "GP_13w_KZ", "GP_Likely_CostDrift_KZ": "GP_13w_CostDrift_KZ"})
    pos["Revenue_13w_USD"], pos["GP_13w_USD"] = pos.Revenue_13w_KZ / fx, pos.GP_13w_KZ / fx
    grp = pos.groupby("Group").agg(SKUs=("ArticleCode", "size"), Revenue_13w_KZ=("Revenue_13w_KZ", "sum"),
                                   GP_13w_KZ=("GP_13w_KZ", "sum"), GP_13w_CostDrift_KZ=("GP_13w_CostDrift_KZ", "sum"))
    grp.loc["Total"] = grp.sum()
    grp["Margin_%"] = grp.GP_13w_KZ / grp.Revenue_13w_KZ * 100
    grp["Revenue_13w_USD"], grp["GP_13w_USD"] = grp.Revenue_13w_KZ / fx, grp.GP_13w_KZ / fx

    # 14.2 / 14.3 views at the standard points -----------------------------------------------------------------------
    pts = [-10, -5, 5, 10]
    sel = g[g["Price_Change_%"].isin(pts)]
    net = sel.pivot_table(index=["Group", "ArticleName"], columns="Price_Change_%", values="Net_GP_Change_KZ")
    tested = sel.pivot_table(index=["Group", "ArticleName"], columns="Price_Change_%", values="Within_Tested_Range")
    net_m = (net / 1e6).round(2)
    net_m = net_m.where(tested.astype(bool), other=np.nan)          # untested points left blank
    gpp = sel.pivot_table(index=["Group", "ArticleName"], columns="Price_Change_%", values="GP_Change_%").round(1)
    rev = sel.pivot_table(index=["Group", "ArticleName"], columns="Price_Change_%", values="Revenue_Change_%").round(1)
    be = sel[sel["Price_Change_%"] > 0].pivot_table(index=["Group", "ArticleName"], columns="Price_Change_%",
                                                    values=["BreakEven_Volume_Change_%", "Units_Change_%"]).round(1)
    # direction: which side of the current price GP rises on, within the tested range (input to step 15)
    t = g[g.Within_Tested_Range]
    dirn = t.groupby("ArticleCode").apply(lambda x: pd.Series({
        "Net_GP_Best_Rise_KZ": x[x["Price_Change_%"] > 0].Net_GP_Change_KZ.max(),
        "Net_GP_Best_Cut_KZ": x[x["Price_Change_%"] < 0].Net_GP_Change_KZ.max()}))
    dirn["GP_Direction"] = np.select(
        [(dirn.Net_GP_Best_Rise_KZ > 0) & (dirn.Net_GP_Best_Rise_KZ >= dirn.Net_GP_Best_Cut_KZ.fillna(-np.inf)),
         dirn.Net_GP_Best_Cut_KZ > 0], ["Rise", "Cut"], "Hold")
    pos = pos.merge(dirn.reset_index(), on="ArticleCode", how="left")
    # rule of thumb check: GP rises with price when |elasticity| < 1 / margin
    e_rise = g[g["Price_Change_%"] == 1].set_index("ArticleCode").Elasticity_Used
    pos["Rise_Elasticity"] = pos.ArticleCode.map(e_rise)
    pos["Max_Elasticity_For_Rise"] = np.where(pos["Margin_%"] > 0, -100 / pos["Margin_%"], np.nan)
    print(f"FX {fx:.1f} Kz/USD, CPI {mom*100:.2f}%/month (macro to {macro_week})", flush=True)
    print(grp.round(0).to_string(), flush=True)
    print(pos.groupby(["Group", "GP_Direction"]).size().unstack(fill_value=0).to_string(), flush=True)

    with pd.ExcelWriter(OUT / "revenue_profit.xlsx") as xw:
        grp.round(1).to_excel(xw, sheet_name="Group totals (13w)")
        pos.round(2).to_excel(xw, sheet_name="Current position per SKU", index=False)
        net_m.to_excel(xw, sheet_name="Net GP change (m Kz)")
        gpp.to_excel(xw, sheet_name="Own GP change %")
        rev.to_excel(xw, sheet_name="Own revenue change %")
        be.to_excel(xw, sheet_name="Break-even volume")
        g.round(3).to_excel(xw, sheet_name="Full grid", index=False)
        pd.DataFrame({"Item": ["Horizon", "Revenue", "Gross profit", "Range", "Rivals", "Net GP", "Cost drift",
                               "Break-even", "FX", "Untested points", "Supply at risk"],
                      "Value": ["28 Sep - 27 Dec 2026, 62 stores, chain-wide price change per SKU",
                                "units x new net price (ex VAT)", "units x (new price - unit COGS), cost fixed",
                                "low / high from the 95% elasticity interval",
                                "GP change on substitute SKUs (step 13 cross effects, capped at 60%)",
                                "own GP change + rival GP change",
                                f"unit cost rising {mom*100:.2f}%/month (CPI, {macro_week}) over the horizon",
                                "volume loss a rise can absorb at constant GP = d / (margin + d)",
                                f"{fx:.2f} Kz per USD (BNA, {macro_week})",
                                "outside the tested price range: blank in the summary, not eligible in step 15",
                                "7 SKUs selling in < 70% of usual stores; baseline uses the last 4 weeks"]}).to_excel(
            xw, sheet_name="Method", index=False)

    # charts ---------------------------------------------------------------------------------------------------------
    skus = pos.sort_values(["Group", "ArticleName"])
    col = {"A": "#156082", "B": "#E97132", "C": "#196B24", "D": "#A02B93"}
    fig, axs = plt.subplots(5, 8, figsize=(20, 12), sharex=True)
    for ax, (_, s) in zip(axs.flat, skus.iterrows()):
        d = g[g.ArticleCode == s.ArticleCode]
        ax.fill_between(d["Price_Change_%"], d.GP_Change_Low_KZ / 1e6, d.GP_Change_High_KZ / 1e6,
                        color=col[s.Group], alpha=.15)
        ax.plot(d["Price_Change_%"], d.Net_GP_Change_KZ / 1e6, color=col[s.Group], lw=1, ls="--")
        dt = d[d.Within_Tested_Range]
        ax.plot(dt["Price_Change_%"], dt.Net_GP_Change_KZ / 1e6, color=col[s.Group], lw=2.2)
        ax.axhline(0, color="#7F8781", lw=.6)
        ax.axvline(0, color="#7F8781", lw=.6)
        ax.set_title(f"{s.Group} · {str(s.ArticleName).title()[:26]}" + (" ⚠" if s.Supply_At_Risk else ""),
                     fontsize=7, color="#C00000" if s.Supply_At_Risk else "k")
        ax.tick_params(labelsize=6)
    fig.supxlabel("price change, %")
    fig.supylabel("net GP change over 13 weeks, m Kz (own + rivals); band = elasticity range; dashed = untested")
    fig.tight_layout()
    fig.savefig(FIG / "14_gp_curves_40.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 9))
    s = pos.sort_values("GP_13w_KZ")
    ax.barh([str(n).title()[:34] for n in s.ArticleName], s.GP_13w_KZ / 1e6, color=[col[x] for x in s.Group])
    ax.axvline(0, color="k", lw=.6)
    ax.set_xlabel("gross profit at current price, 28 Sep - 27 Dec 2026, m Kz")
    ax.tick_params(labelsize=7)
    fig.savefig(FIG / "14_current_gp.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(net_m.to_string(), flush=True)


if __name__ == "__main__":
    main()
