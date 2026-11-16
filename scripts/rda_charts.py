"""Charts for the RDA PDF report -> report/rda_charts/*.png (tables from analysis/rda)."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from report_charts import (ACC, AXIS, DIV, GRID, INK, INK2, MUTED, NEG, POS, S1, S2, S3, S4, S5, SEQ, TITLE, heat)

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "analysis" / "rda"
OUT = ROOT / "report" / "rda_charts"
OUT.mkdir(parents=True, exist_ok=True)
N = json.load(open(R / "numbers.json"))
rd = lambda n: pd.read_parquet(R / f"{n}.parquet")
MIN_SHARE = 0.3          # main groups below this share of L12M sales are left out of group charts
PAL = [S1, S2, S3, S4, S5, "#9b4dca", "#7a8b99", "#c2185b", "#00897b", "#6d4c41"]
bn = lambda v: v / 1e9


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", facecolor="white")
    plt.close(fig)


def main_groups():
    mg = rd("maingroup_l12m")
    return mg[mg.Sales_Share >= MIN_SHARE].MainGroup.tolist()


def months(idx):
    return pd.PeriodIndex(idx, freq="M").to_timestamp()


# ---------------------------------------------------------------- sales & profit
def sales_profit():
    m = rd("monthly_chain").set_index("Month")
    t = months(m.index)
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.bar(t, bn(m.Net_KZ), width=22, color="#bcd6f5", label="Net sales, bn Kz")
    ax.bar(t, bn(m.GP_KZ), width=22, color=S1, label="Gross profit, bn Kz")
    ax.set_ylabel("bn Kz (nominal)")
    a2 = ax.twinx()
    a2.plot(t, m.Margin_Pct, color=S2, lw=1.8, marker="o", ms=2.5, label="Gross margin % (right)")
    a2.set_ylim(0, 30)
    a2.grid(False)
    a2.spines["right"].set_visible(True)
    a2.set_ylabel("gross margin %", color=S2)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = a2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.14))
    save(fig, "r01_sales_gp_margin")

    l = rd("monthly_lfl").set_index("Month")
    fig, ax = plt.subplots(figsize=(7.4, 2.9))
    i = lambda s: s / s.iloc[0] * 100
    for lab, s, c, lw in [("Net sales, kwanza", m.Net_KZ, S2, 1.4), ("Net sales, USD", m.Net_USD, S4, 1.4),
                          ("Net sales, real (CPI-deflated)", m.Net_Real, S1, 1.8),
                          ("Gross profit, real", m.GP_Real, S5, 1.8),
                          (f"Like-for-like real sales ({N['lfl_stores']} stores)", l.Net_Real, S3, 2.4)]:
        ax.plot(t, i(s), color=c, lw=lw, label=lab)
    ax.axhline(100, color=AXIS, lw=.8)
    ax.set_yscale("log")
    ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_yticks([50, 100, 200, 400, 800], ["50", "100", "200", "400", "800"])
    ax.set_ylabel("index, Jan 2023 = 100 (log)")
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.2))
    save(fig, "r02_growth_index")

    y = rd("yearly_ytd").set_index("Year").iloc[1:]
    fig, ax = plt.subplots(figsize=(4.2, 2.6))
    x = np.arange(len(y))
    for k, (col, lab, c) in enumerate([("Net_KZ_Growth", "Net sales, Kz", S2), ("Net_Real_Growth", "Net sales, real", S1),
                                       ("GP_Real_Growth", "Gross profit, real", S5)]):
        b = ax.bar(x + (k - 1) * .26, y[col], width=.25, color=c, label=lab)
        ax.bar_label(b, fmt="%.0f%%", fontsize=6.5, padding=1.5, color=INK2)
    ax.set_xticks(x, [f"{a}\nvs {int(a) - 1}" for a in y.index])
    ax.set_ylabel("growth, Jan-Sep vs prior year, %")
    ax.legend(loc="upper right", fontsize=7)
    ax.grid(axis="x", visible=False)
    save(fig, "r03_ytd_growth")

    sh = rd("maingroup_month_real").set_index("Month")
    keep = sh.sum().nlargest(8).index
    sh = pd.concat([sh[keep], sh.drop(columns=keep).sum(axis=1).rename("OTHER")], axis=1)
    sh = sh.div(sh.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.stackplot(months(sh.index), sh.T.values, labels=[TITLE(c) for c in sh.columns], colors=PAL[:sh.shape[1]],
                 alpha=.9)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of real net sales")
    ax.legend(ncol=5, loc="upper left", bbox_to_anchor=(0, 1.22), fontsize=7)
    ax.margins(x=0)
    save(fig, "r04_group_mix")


# ---------------------------------------------------------------- category performance & margin
def category():
    mg = rd("maingroup_l12m")
    mg = mg[mg.MainGroup.isin(main_groups())].sort_values("Net_KZ")
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    y = np.arange(len(mg))
    ax.barh(y + .2, mg.Sales_Share, height=.38, color="#bcd6f5", label="share of net sales %")
    ax.barh(y - .2, mg.GP_Share, height=.38, color=S1, label="share of gross profit %")
    ax.set_yticks(y, [TITLE(g) for g in mg.MainGroup])
    ax.set_xlabel("% of chain total, Oct 2025 - Sep 2026")
    a2 = ax.twiny()
    a2.scatter(mg.Margin_Pct, y, color=S2, zorder=4, s=22, label="gross margin % (top axis)")
    for yi, v in zip(y, mg.Margin_Pct):
        a2.annotate(f"{v:.0f}%", (v, yi), xytext=(5, -3), textcoords="offset points", fontsize=6.5, color=S2)
    a2.set_xlim(0, 45)
    a2.grid(False)
    a2.spines["top"].set_visible(True)
    a2.tick_params(colors=S2)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = a2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="lower right", fontsize=7)
    ax.grid(axis="y", visible=False)
    save(fig, "r05_group_share_margin")

    q = rd("maingroup_quarter")
    q = q[q.MainGroup.isin(main_groups())].pivot(index="MainGroup", columns="Q", values="Margin_Pct")
    q = q.loc[mg.MainGroup[::-1]]
    q.index = [TITLE(i) for i in q.index]
    q.columns = [c.replace("Q", " Q") for c in q.columns]
    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    heat(ax, q, DIV, "{:.0f}", center=20, vmin=5, vmax=35, cbar_label="gross margin %")
    ax.tick_params(axis="x", labelsize=6.3, rotation=90)
    ax.set_title("Gross margin % by main group and quarter")
    save(fig, "r06_margin_group_quarter")

    for name, dim, w in [("margin_group_zone", "Area_Zone", 7.6), ("margin_group_class", "Store_Class", 4.6)]:
        h = rd(name)
        h = h[h.MainGroup.isin(main_groups())].pivot(index="MainGroup", columns=dim, values="Margin_Pct")
        h = h.loc[[g for g in mg.MainGroup[::-1] if g in h.index]]
        h.index = [TITLE(i) for i in h.index]
        h.columns = [TITLE(c) for c in h.columns]
        fig, ax = plt.subplots(figsize=(w, 3.9))
        heat(ax, h, DIV, "{:.0f}", center=20, vmin=5, vmax=35, cbar_label="gross margin %")
        ax.tick_params(axis="x", labelsize=7, rotation=45 if dim == "Area_Zone" else 0)
        ax.set_title("Gross margin % by main group and " + ("zone" if dim == "Area_Zone" else "store class")
                     + " (stores, L12M)")
        save(fig, "r07_" + name)

    d = rd("article_margin_dist")
    d = d[d.Margin_Pct.between(-30, 70)]
    fig, ax = plt.subplots(figsize=(4.4, 2.7))
    ax.hist(d.Margin_Pct, bins=np.arange(-30, 71, 2.5), weights=d.Net_KZ / d.Net_KZ.sum() * 100, color=S1,
            edgecolor="white", lw=.4)
    wavg = np.average(d.Margin_Pct, weights=d.Net_KZ)
    ax.axvline(wavg, color=S2, lw=1.4, ls="--")
    ax.annotate(f"sales-weighted\naverage {wavg:.1f}%", (wavg, ax.get_ylim()[1] * .85), xytext=(6, 0),
                textcoords="offset points", fontsize=7, color=S2)
    ax.axvline(0, color=NEG, lw=1)
    ax.set_xlabel("article gross margin %, L12M")
    ax.set_ylabel("% of net sales")
    ax.grid(axis="x", visible=False)
    save(fig, "r08_margin_distribution")

    a = rd("article_l12m")
    s = a.sort_values("Net_KZ", ascending=False)
    g = a.sort_values("GP_KZ", ascending=False)
    fig, ax = plt.subplots(figsize=(3.6, 2.7))
    r = np.arange(1, len(s) + 1) / len(s) * 100
    ax.plot(r, s.Net_KZ.cumsum() / s.Net_KZ.sum() * 100, color=S1, lw=2, label="net sales")
    ax.plot(r, g.GP_KZ.cumsum() / g.GP_KZ.sum() * 100, color=S2, lw=2, label="gross profit")
    ax.axvline(20, color=AXIS, ls="--", lw=.8)
    ax.axhline(100, color=AXIS, lw=.8)
    ax.set_xlabel("% of articles (ranked)")
    ax.set_ylabel("cumulative % of total")
    ax.set_xlim(0, 100)
    ax.legend(loc="lower right")
    save(fig, "r09_pareto")

    for name, d, col, c in [("r10_top_gp", g.head(15), "GP_KZ", S1), ("r11_bottom_gp", g.tail(15)[::-1], "GP_KZ", NEG)]:
        fig, ax = plt.subplots(figsize=(7.4, 3.4))
        y = np.arange(len(d))
        ax.barh(y, d[col] / 1e6, color=c, height=.65)
        ax.set_yticks(y, [f"{str(n)[:38].title()}  ·  {TITLE(sg)[:14]}" for n, sg in zip(d.ArticleName, d.SubGroup)],
                      fontsize=7)
        ax.invert_yaxis()
        for yi, v, m in zip(y, d[col] / 1e6, d.Margin_Pct):
            ax.annotate(f"{v:,.0f}m · {m:.0f}%", (v, yi), xytext=(4 if v >= 0 else -4, 0), textcoords="offset points",
                        va="center", ha="left" if v >= 0 else "right", fontsize=6.5, color=INK2)
        ax.set_xlabel("gross profit, million Kz, L12M (label: GP · margin)")
        ax.margins(x=.18)
        ax.grid(axis="y", visible=False)
        save(fig, name)

    sg = rd("subgroup_l12m")
    sg = sg[(sg.Net_KZ > 1.5e9) & sg.Growth_Real_Pct.notna()].copy()
    dup = sg.SubGroup.duplicated(keep=False)
    sg.loc[dup, "SubGroup"] = sg.SubGroup + " (" + sg.MainGroup.str.title() + ")"
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    cmap = {g: PAL[i % len(PAL)] for i, g in enumerate(sg.groupby("MainGroup").Net_KZ.sum().sort_values(ascending=False).index)}
    ax.scatter(sg.Margin_Pct, sg.Growth_Real_Pct.clip(-40, 120), s=sg.Net_KZ / sg.Net_KZ.max() * 900,
               c=[cmap[g] for g in sg.MainGroup], alpha=.6, edgecolor="white", lw=.8)
    for _, r in sg.nlargest(22, "Net_KZ").iterrows():
        ax.annotate(TITLE(r.SubGroup)[:16], (r.Margin_Pct, min(r.Growth_Real_Pct, 120)), fontsize=6.3, color=INK2,
                    xytext=(4, 3), textcoords="offset points")
    wm = (1 - sg.COGS_KZ.sum() / sg.Net_KZ.sum()) * 100
    wg = (sg.Net_Real.sum() / sg.Prior_Net_Real.sum() - 1) * 100
    ax.axvline(wm, color=AXIS, ls="--", lw=.9)
    ax.axhline(wg, color=AXIS, ls="--", lw=.9)
    ax.set_xlabel("gross margin %, L12M")
    ax.set_ylabel("real sales growth %, L12M vs prior 12M")
    for g, c in list(cmap.items())[:8]:
        ax.scatter([], [], color=c, label=TITLE(g), s=25)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, 1.15), fontsize=7)
    save(fig, "r12_subgroup_quadrant")


# ---------------------------------------------------------------- stores
def stores():
    st = rd("store_l12m")
    st = st[st.Channel.eq("STORE") & st.Months.eq(12)]
    zones = st.Area_Zone.unique()
    zc = {z: PAL[i % len(PAL)] for i, z in enumerate(sorted(zones))}
    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    ax.scatter(st.Sales_per_Sqm_Month_KZ / 1e3, st.Margin_Pct, s=st.Net_KZ / st.Net_KZ.max() * 400,
               c=[zc[z] for z in st.Area_Zone], alpha=.7, edgecolor="white", lw=.8)
    lab = pd.concat([st.nlargest(6, "Margin_Pct"), st.nsmallest(6, "Margin_Pct"), st.nlargest(6, "Sales_per_Sqm_Month_KZ"),
                     st.nsmallest(3, "Sales_per_Sqm_Month_KZ"), st.nlargest(4, "Net_KZ")]).drop_duplicates("Plant")
    for _, r in lab.iterrows():
        ax.annotate(str(r.Store_Name).replace(" FRESMART", "").replace(" EXPRESS", "").title()[:14],
                    (r.Sales_per_Sqm_Month_KZ / 1e3, r.Margin_Pct), fontsize=6.3, color=INK2, xytext=(3, 2),
                    textcoords="offset points")
    for z, c in zc.items():
        ax.scatter([], [], color=c, label=TITLE(z), s=25)
    ax.legend(ncol=6, loc="upper left", bbox_to_anchor=(0, 1.17), fontsize=7)
    ax.set_xlabel("net sales per m² per month, thousand Kz (L12M)")
    ax.set_ylabel("gross margin %")
    save(fig, "r13_store_scatter")

    st = st.sort_values("GP_per_Sqm_Month_KZ", ascending=False)
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    x = np.arange(len(st))
    ax.bar(x, st.GP_per_Sqm_Month_KZ / 1e3, color=[zc[z] for z in st.Area_Zone])
    ax.set_xticks(x, [str(s).replace(" FRESMART", "").replace(" EXPRESS", "").title()[:12] for s in st.Store_Name],
                  rotation=90, fontsize=5.6)
    ax.set_ylabel("gross profit per m² per month,\nthousand Kz")
    ax.grid(axis="x", visible=False)
    ax.margins(x=.01)
    save(fig, "r14_store_gp_sqm")

    s = st.dropna(subset=["Elasticity", "Price_Premium_Pct"])
    fig, ax = plt.subplots(figsize=(4.4, 3.0))
    ax.scatter(s.Price_Premium_Pct, s.Margin_Pct, c=[zc[z] for z in s.Area_Zone], s=30, alpha=.8, edgecolor="white")
    b = np.polyfit(s.Price_Premium_Pct, s.Margin_Pct, 1)
    xs = np.linspace(s.Price_Premium_Pct.min(), s.Price_Premium_Pct.max(), 10)
    ax.plot(xs, np.polyval(b, xs), color=INK2, lw=1, ls="--")
    r = np.corrcoef(s.Price_Premium_Pct, s.Margin_Pct)[0, 1]
    ax.set_title(f"Store price premium vs margin (r = {r:.2f})")
    ax.set_xlabel("price premium vs chain, %")
    ax.set_ylabel("gross margin %")
    save(fig, "r15_premium_margin")
    N["store_premium_margin_r"] = r


# ---------------------------------------------------------------- price & cost
def price_cost():
    ix = rd("price_cost_index").set_index("Month")
    t = months(ix.index)
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    for lab, col, c, lw in [("Selling price index", "Price_Index", S1, 2.2), ("Unit cost (COGS) index", "Cost_Index", S2, 2.2),
                            ("CPI", "CPI_Rebased_Jan2023", S3, 1.4), ("Exchange rate Kz/USD (BNA)", "FX_Index", S4, 1.4)]:
        ax.plot(t, ix[col], color=c, lw=lw, label=lab)
    ax.axhline(100, color=AXIS, lw=.8)
    ax.set_ylabel("index, Jan 2023 = 100")
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, 1.13))
    save(fig, "r16_price_cost_index")

    g = rd("price_cost_index_group")
    top = [x for x in main_groups() if x in g.MainGroup.unique()][:8]
    fig, axs = plt.subplots(2, 4, figsize=(7.6, 3.8), sharex=True)
    for ax, mgp in zip(axs.flat, top):
        d = g[g.MainGroup == mgp].set_index("Month")
        tt = months(d.index)
        ax.plot(tt, d.dp, color=S1, lw=1.6, label="price")
        ax.plot(tt, d.dc, color=S2, lw=1.6, label="unit cost")
        ax.set_title(TITLE(mgp), fontsize=8)
        ax.tick_params(labelsize=6)
        ax.xaxis.set_major_locator(matplotlib.dates.YearLocator())
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%y"))
    axs.flat[0].legend(fontsize=6.5, loc="upper left")
    fig.supylabel("index, Feb 2023 = 100", fontsize=7.5, color=INK2)
    fig.tight_layout()
    save(fig, "r17_price_cost_groups")

    pt = rd("cost_passthrough")
    pt = pt[pt.MainGroup.isin(main_groups() + ["ALL"])].sort_values("Cumulative")
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    y = np.arange(len(pt))
    ax.barh(y, pt.Same_Quarter, color=S1, label="same quarter")
    ax.barh(y, pt.Next_Quarter, left=pt.Same_Quarter, color="#9ec5f4", label="following quarter")
    for yi, v, s in zip(y, pt.Cumulative, pt.Same_Quarter):
        ax.annotate(f"{v:.0f}%", (max(v, s), yi), xytext=(4, 0), textcoords="offset points", va="center", fontsize=7)
    ax.axvline(100, color=INK2, lw=.8, ls="--")
    ax.set_yticks(y, [("All articles" if g == "ALL" else TITLE(g)) for g in pt.MainGroup])
    ax.set_xlabel("% of a unit-cost change passed into the selling price")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)
    save(fig, "r18_cost_passthrough")

    m = rd("monthly_chain").set_index("Month")
    fx3 = (m.FX_BNA_Avg / m.FX_BNA_Avg.shift(3) - 1) * 100
    fig, ax = plt.subplots(figsize=(4.2, 2.8))
    ax.scatter(fx3, m.Margin_Pct, color=S1, s=22, alpha=.8)
    for mo in ["2023-06", "2023-07", "2023-08"]:
        ax.annotate(mo, (fx3[mo], m.Margin_Pct[mo]), fontsize=6.5, xytext=(4, 0), textcoords="offset points")
    ok = fx3.notna()
    r = np.corrcoef(fx3[ok], m.Margin_Pct[ok])[0, 1]
    ax.set_title(f"Devaluation squeezes margin (r = {r:.2f})")
    ax.set_xlabel("Kz/USD change over previous 3 months, %")
    ax.set_ylabel("gross margin %")
    save(fig, "r19_fx_margin")
    N["fx3_margin_r"] = r


# ---------------------------------------------------------------- correlations
def correlations():
    for name, out, title, w in [("corr_within", "r20_corr_within",
                                 "Within article-store correlations (monthly, each item vs its own average)", 7.0),
                                ("corr_macro_monthly", "r21_corr_macro", "Chain monthly drivers (Jan 2023 - Sep 2026)", 7.0),
                                ("corr_subgroup", "r22_corr_subgroup", "Sub-category correlations (Spearman, L12M)", 5.0)]:
        c = rd(name).set_index("index")
        mask = np.triu(np.ones_like(c, dtype=bool), 1)
        c = c.mask(mask)
        fig, ax = plt.subplots(figsize=(w, w * .62))
        heat(ax, c, DIV, "{:.2f}", center=0, vmin=-1, vmax=1, cbar_label="correlation")
        ax.tick_params(axis="x", rotation=40, labelsize=7)
        plt.setp(ax.get_xticklabels(), ha="right")
        ax.set_title(title)
        save(fig, out)


# ---------------------------------------------------------------- price response
def response():
    b = rd("demand_binscatter")
    al = b[b.SubGroup == "ALL"]
    fig, ax = plt.subplots(figsize=(4.0, 2.9))
    ax.scatter(np.exp(al.x) * 100 - 100, np.exp(al.y) * 100 - 100, color=S1, s=26, zorder=3)
    xs = np.linspace(al.x.min(), al.x.max(), 20)
    ax.plot(np.exp(xs) * 100 - 100, np.exp(al.Slope.iloc[0] * xs) * 100 - 100, color=S2, lw=1.4,
            label=f"fitted slope {al.Slope.iloc[0]:.2f}")
    ax.axhline(0, color=AXIS, lw=.8)
    ax.axvline(0, color=AXIS, lw=.8)
    ax.set_xlabel("price vs article's usual relative price, %")
    ax.set_ylabel("units vs usual, %")
    ax.legend()
    ax.set_title("Demand curve, all articles (20 bins)")
    save(fig, "r23_demand_all")

    sgs = [s for s in b.SubGroup.unique() if s != "ALL"]
    fig, axs = plt.subplots(2, 4, figsize=(7.6, 3.9), sharex=True, sharey=True)
    for ax, sg in zip(axs.flat, sgs):
        d = b[b.SubGroup == sg]
        ax.scatter(np.exp(d.x) * 100 - 100, np.exp(d.y) * 100 - 100, color=S1, s=12)
        xs = np.linspace(d.x.min(), d.x.max(), 10)
        ax.plot(np.exp(xs) * 100 - 100, np.exp(d.Slope.iloc[0] * xs) * 100 - 100, color=S2, lw=1.2)
        ax.set_title(f"{TITLE(sg)[:16]} ({d.Slope.iloc[0]:.2f})", fontsize=7.5)
        ax.axhline(0, color=AXIS, lw=.6)
        ax.axvline(0, color=AXIS, lw=.6)
        ax.tick_params(labelsize=6)
    fig.supxlabel("price vs usual relative price, %", fontsize=7.5, color=INK2)
    fig.supylabel("units vs usual, %", fontsize=7.5, color=INK2)
    fig.tight_layout()
    save(fig, "r24_demand_subgroups")

    s = rd("simulation_curves")
    fig, axs = plt.subplots(1, 2, figsize=(7.6, 3.1))
    for i, (sg, d) in enumerate(s.groupby("SubGroup", sort=False)):
        lab = f"{TITLE(sg)[:14]} (e {d.Elasticity.iloc[0]:.1f}, m {d.Margin_Pct.iloc[0]:.0f}%)"
        axs[0].plot(d.Price_Change, d.Volume_Index, color=PAL[i % 10], lw=1.3)
        axs[1].plot(d.Price_Change, d.GP_Index, color=PAL[i % 10], lw=1.3, label=lab)
    for ax, t in zip(axs, ["Units sold (index)", "Gross profit (index)"]):
        ax.axhline(100, color=INK2, lw=.8)
        ax.axvline(0, color=INK2, lw=.8)
        ax.set_title(t, fontsize=8.5)
        ax.set_xlabel("price change, %")
    axs[1].set_ylim(40, 160)
    axs[1].legend(fontsize=5.8, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    save(fig, "r25_simulation")

    sg = rd("subgroup_l12m").dropna(subset=["Elasticity"])
    sg = sg[sg.Net_KZ > 1e9]
    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    ax.scatter(sg.Elasticity, sg.Margin_Pct, s=sg.Net_KZ / sg.Net_KZ.max() * 800, color=S1, alpha=.5,
               edgecolor="white")
    xs = np.linspace(-6, -1.05, 60)
    ax.plot(xs, -100 / xs, color=S2, lw=1.4, label="profit-maximising margin = −1 / elasticity")
    for _, r in sg.nlargest(20, "Net_KZ").iterrows():
        ax.annotate(TITLE(r.SubGroup)[:15], (r.Elasticity, r.Margin_Pct), fontsize=6.2, color=INK2, xytext=(4, 2),
                    textcoords="offset points")
    ax.set_xlim(-6, 0.2)
    ax.set_ylim(0, 60)
    ax.set_xlabel("sub-category price elasticity")
    ax.set_ylabel("actual gross margin %, L12M")
    ax.legend(loc="upper left")
    save(fig, "r26_margin_vs_elasticity")


# ---------------------------------------------------------------- discount & promotion
def promo():
    m = rd("monthly_chain").set_index("Month")
    d = rd("discount_group")
    d = d[d.MainGroup.isin(main_groups())].sort_values("Disc_Pct")
    fig, axs = plt.subplots(1, 2, figsize=(7.6, 2.9), gridspec_kw={"width_ratios": [1.2, 1]})
    axs[0].plot(months(m.index), m.Disc_Pct, color=S1, lw=1.8)
    axs[0].set_ylabel("discount, % of gross sales")
    axs[0].set_title("Recorded discount by month", fontsize=8.5)
    axs[0].xaxis.set_major_locator(matplotlib.dates.YearLocator())
    axs[0].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y"))
    axs[1].barh(range(len(d)), d.Disc_Pct, color=S1)
    axs[1].set_yticks(range(len(d)), [TITLE(g) for g in d.MainGroup], fontsize=6.5)
    axs[1].set_title("Recorded discount by main group, %", fontsize=8.5)
    axs[1].grid(axis="y", visible=False)
    fig.tight_layout()
    save(fig, "r27_discount")

    b = rd("discount_depth_volume")
    fig, ax = plt.subplots(figsize=(4.2, 2.6))
    ax.bar(b.Bucket.astype(str), b.Volume_vs_Usual_Pct, color=[S1 if v >= 0 else NEG for v in b.Volume_vs_Usual_Pct])
    for i, (v, n) in enumerate(zip(b.Volume_vs_Usual_Pct, b.Rows)):
        ax.annotate(f"{v:+.0f}%\nn={n / 1e3:,.0f}k", (i, v), ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=6, xytext=(0, 2 if v >= 0 else -2), textcoords="offset points")
    ax.axhline(0, color=INK2, lw=.8)
    ax.set_xlabel("recorded discount depth in the month")
    ax.set_ylabel("units vs article-store usual, %")
    ax.margins(y=.25)
    ax.grid(axis="x", visible=False)
    save(fig, "r28_discount_depth")

    t = rd("tpr_by_depth")
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 2.7))
    x = np.arange(len(t))
    axs[0].bar(x, t.Median_Adj_Lift_Pct, color=S1)
    axs[0].bar_label(axs[0].containers[0], fmt="+%.0f%%", fontsize=7)
    axs[0].set_xticks(x, t.Depth_Bucket.astype(str))
    axs[0].set_title("Median unit lift in the reduced-price week", fontsize=8.5)
    axs[0].set_xlabel("temporary price cut")
    axs[1].bar(x, t.Share_GP_Up_Pct, color=S2)
    axs[1].bar_label(axs[1].containers[0], fmt="%.0f%%", fontsize=7)
    axs[1].axhline(50, color=INK2, ls="--", lw=.8)
    axs[1].set_xticks(x, t.Depth_Bucket.astype(str))
    axs[1].set_ylim(0, 60)
    axs[1].set_title("Share of events where gross profit rose", fontsize=8.5)
    axs[1].set_xlabel("temporary price cut")
    for ax in axs:
        ax.grid(axis="x", visible=False)
    fig.tight_layout()
    save(fig, "r29_tpr_depth")

    g = rd("tpr_by_group")
    g = g[g.MainGroup.isin(main_groups())].sort_values("Median_Adj_Lift_Pct")
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    y = np.arange(len(g))
    ax.barh(y, g.Median_Adj_Lift_Pct, color=S1, height=.6)
    for yi, v, e, s, n in zip(y, g.Median_Adj_Lift_Pct, g.Median_Promo_Elasticity, g.Share_GP_Up_Pct, g.Events):
        ax.annotate(f"+{v:.0f}% · e {e:.1f} · GP up in {s:.0f}% · n={n:,.0f}", (v, yi), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=6.4, color=INK2)
    ax.set_yticks(y, [TITLE(m) for m in g.MainGroup])
    ax.set_xlabel("median category-adjusted unit lift during a temporary price cut, %")
    ax.margins(x=.45)
    ax.grid(axis="y", visible=False)
    save(fig, "r30_tpr_group")


# ---------------------------------------------------------------- anomalies & data quality
def anomalies():
    a = rd("anomaly_monthly").set_index("Month")
    t = months(a.index)
    fig, ax = plt.subplots(figsize=(7.4, 2.7))
    ax.bar(t, -a.Below_Cost_Loss_KZ / 1e6, width=22, color=NEG, alpha=.8, label="loss on below-cost sales, million Kz")
    ax.set_ylabel("million Kz")
    a2 = ax.twinx()
    a2.plot(t, a.Price_Outliers / a.Rows * 1000, color=S1, lw=1.5, label="price outliers per 1,000 rows (right)")
    a2.plot(t, a.Cost_Outliers / a.Rows * 1000, color=S4, lw=1.5, label="cost outliers per 1,000 rows (right)")
    a2.grid(False)
    a2.spines["right"].set_visible(True)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = a2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.15), fontsize=7)
    save(fig, "r31_anomalies")

    s = rd("store_month_anomaly")
    s = s[s.Month >= "2024-01"]
    p = s.pivot(index="Store_Name", columns="Month", values="Margin_dev")
    p = p.loc[p.abs().max(axis=1).sort_values(ascending=False).index[:22]]
    p.index = [str(i).replace(" FRESMART", "").replace(" EXPRESS", "").title()[:18] for i in p.index]
    p.columns = [c[2:] for c in p.columns]
    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    heat(ax, p, DIV, "", center=0, vmin=-8, vmax=8, cbar_label="margin vs store's own median, pp")
    ax.tick_params(axis="x", labelsize=5.5, rotation=90)
    ax.tick_params(axis="y", labelsize=6.5)
    ax.set_title("Store-month margin deviations (22 most volatile stores, 2024 onward)")
    save(fig, "r32_store_margin_dev")

    c = rd("dq_completeness_year").set_index("Year")
    c = c[["Price", "Unit_COGS", "Relative_Price", "Stock", "Days_Of_Cover", "List_Price"]]
    c.columns = ["Selling price", "Unit cost", "Relative price", "Stock record", "Days of cover", "List price"]
    fig, ax = plt.subplots(figsize=(6.0, 1.9))
    heat(ax, c, SEQ, "{:.0f}%", vmin=0, vmax=100, cbar_label="% of sales rows")
    ax.set_title("Field completeness on sales rows (month x location x article)")
    save(fig, "r33_completeness")


def main():
    sales_profit()
    category()
    stores()
    price_cost()
    correlations()
    response()
    promo()
    anomalies()
    json.dump(N, open(R / "numbers.json", "w"), indent=1, default=float)
    print("charts:", len(list(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
