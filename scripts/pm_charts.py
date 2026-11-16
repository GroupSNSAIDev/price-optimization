"""Extra charts for the Profit & Margin PDF -> report/rda_charts/p*.png (the r*.png charts come from rda_charts.py)."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from rda_charts import OUT, PAL, R, main_groups, months, save
from report_charts import AXIS, DIV, INK2, NEG, S1, S2, S3, S4, S5, TITLE, heat

rd = lambda n: pd.read_parquet(R / f"pm_{n}.parquet")
N = json.load(open(R / "pm_numbers.json"))
NAME = lambda s: str(s).replace(" FRESMART EXPRESS", " Exp").replace(" FRESMART", "").title().replace(" Exp", " Exp.")


def label_sub(d):
    d = d.copy()
    dup = d.SubGroup.duplicated(keep=False)
    d["Label"] = np.where(dup, d.SubGroup.str.title() + " (" + d.MainGroup.str.title().str[:9] + ")", d.SubGroup.str.title())
    return d


def overview():
    m = pd.read_parquet(R / "monthly_chain.parquet").set_index("Month")
    t = months(m.index)
    fig, ax = plt.subplots(figsize=(7.4, 2.9))
    i = lambda s: s / s.iloc[0] * 100
    for lab, s, c, lw in [("Gross profit, kwanza", m.GP_KZ, S2, 1.6), ("Gross profit, USD", m.GP_USD, S4, 1.6),
                          ("Gross profit, real (CPI-deflated)", m.GP_Real, S5, 2.2)]:
        ax.plot(t, i(s), color=c, lw=lw, label=lab)
    ax.axhline(100, color=AXIS, lw=.8)
    ax.set_yscale("log")
    ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_yticks([50, 100, 200, 400, 800], ["50", "100", "200", "400", "800"])
    ax.set_ylabel("index, Jan 2023 = 100 (log)")
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.13))
    save(fig, "p01_gp_index")

    y = pd.read_parquet(R / "yearly_ytd.parquet").set_index("Year")
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    x = np.arange(len(y))
    b = ax.bar(x, y.GP_KZ / 1e9, color=S1, width=.55)
    ax.bar_label(b, labels=[f"{v / 1e9:.1f} bn\n{mp:.1f}%" for v, mp in zip(y.GP_KZ, y.Margin_Pct)], fontsize=7,
                 padding=2)
    ax.set_xticks(x, y.index)
    ax.set_ylabel("gross profit Jan–Sep, bn Kz")
    ax.margins(y=.22)
    ax.grid(axis="x", visible=False)
    save(fig, "p02_gp_ytd")

    g = rd("group_year_gp")
    g = g[g.MainGroup.isin(main_groups())]
    pv = g.pivot(index="Year", columns="MainGroup", values="GP_KZ").fillna(0) / 1e9
    pv = pv[pv.sum().sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    bottom = np.zeros(len(pv))
    cols = PAL + ["#b0bec5", "#90a4ae", "#ffcc80", "#a5d6a7"]
    for k, c in enumerate(pv.columns):
        ax.bar(pv.index, pv[c], bottom=bottom, color=cols[k % len(cols)], label=TITLE(c), width=.6)
        bottom += pv[c].to_numpy()
    for xi, v in enumerate(bottom):
        ax.annotate(f"{v:.1f} bn", (xi, v), ha="center", xytext=(0, 3), textcoords="offset points", fontsize=7.5)
    ax.set_ylabel("gross profit, bn Kz (2026 = Jan–Sep)")
    ax.legend(ncol=2, fontsize=6.6, loc="upper left", bbox_to_anchor=(1.01, 1))
    ax.grid(axis="x", visible=False)
    save(fig, "p03_gp_group_year")


def category():
    gm = rd("group_month")
    top = main_groups()[:8]
    fig, axs = plt.subplots(2, 4, figsize=(7.6, 3.8), sharex=True, sharey=True)
    chain = pd.read_parquet(R / "monthly_chain.parquet").set_index("Month").Margin_Pct
    for ax, g in zip(axs.flat, top):
        d = gm[gm.MainGroup == g].set_index("Month").Margin_Pct
        ax.plot(months(chain.index), chain, color=AXIS, lw=1, label="chain")
        ax.plot(months(d.index), d, color=S1, lw=1.6, label=TITLE(g))
        ax.set_title(TITLE(g), fontsize=8)
        ax.set_ylim(0, 40)
        ax.tick_params(labelsize=6)
        ax.xaxis.set_major_locator(matplotlib.dates.YearLocator())
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%y"))
    axs.flat[0].legend(["chain", "group"], fontsize=6, loc="lower right")
    fig.supylabel("gross margin %", fontsize=7.5, color=INK2)
    fig.tight_layout()
    save(fig, "p04_group_margin_lines")

    b = rd("margin_bridge")
    b = b[(b.s1 > .003) | (b.s0 > .003)]
    big = b.assign(tot=(b.Rate_pp + b.Mix_pp).abs()).nlargest(8, "tot")
    other = b.drop(big.index)
    steps = [("Prior 12M margin", N["bridge"]["m0"], "base")]
    for _, r in big.sort_values("tot", ascending=False).iterrows():
        steps.append((f"{TITLE(r.MainGroup)}: rate", r.Rate_pp, "d"))
        steps.append((f"{TITLE(r.MainGroup)}: mix", r.Mix_pp, "d"))
    steps.append(("Other groups", (other.Rate_pp + other.Mix_pp).sum(), "d"))
    steps.append(("Last 12M margin", N["bridge"]["m1"], "base"))
    steps = [s for s in steps if s[2] == "base" or abs(s[1]) >= .02]
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    run = 0
    for k, (lab, v, kind) in enumerate(steps):
        if kind == "base":
            ax.bar(k, v, color=INK2, width=.6)
            ax.annotate(f"{v:.2f}%", (k, v), ha="center", xytext=(0, 3), textcoords="offset points", fontsize=7)
            run = v
        else:
            ax.bar(k, v, bottom=run, color=S3 if v >= 0 else NEG, width=.6)
            ax.annotate(f"{v:+.2f}", (k, run + max(v, 0)), ha="center", xytext=(0, 3), textcoords="offset points",
                        fontsize=6.5)
            run += v
    ax.set_xticks(range(len(steps)), [s[0] for s in steps], rotation=60, ha="right", fontsize=6.6)
    ax.set_ylim(N["bridge"]["m0"] - 1.2, N["bridge"]["m1"] + 1.0)
    ax.set_ylabel("gross margin %")
    ax.grid(axis="x", visible=False)
    save(fig, "p05_margin_bridge")

    c = label_sub(rd("subgroup_margin_change"))
    c = c[c.Net_KZ_L12 > 8e8].sort_values("GP_Effect_KZ")
    d = pd.concat([c.head(10), c.tail(10)])
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    y = np.arange(len(d))
    ax.barh(y, d.GP_Effect_KZ / 1e6, color=[NEG if v < 0 else S3 for v in d.GP_Effect_KZ], height=.65)
    for yi, v, a, b2 in zip(y, d.GP_Effect_KZ / 1e6, d.Margin_Pct_P12, d.Margin_Pct_L12):
        ax.annotate(f"{a:.1f}% → {b2:.1f}%", (v, yi), xytext=(4 if v >= 0 else -4, 0), textcoords="offset points",
                    va="center", ha="left" if v >= 0 else "right", fontsize=6.4, color=INK2)
    ax.set_yticks(y, d.Label, fontsize=7)
    ax.axvline(0, color=INK2, lw=.8)
    ax.set_xlabel("gross profit effect of the margin change, million Kz (L12M sales × change in margin)")
    ax.margins(x=.25)
    ax.grid(axis="y", visible=False)
    save(fig, "p06_subgroup_margin_change")

    iq = rd("import_quarter")
    iq = iq[iq.PurchaseType.isin(["Import", "Local"])].pivot(index="Q", columns="PurchaseType", values="Margin_Pct")
    fig, ax = plt.subplots(figsize=(4.6, 2.7))
    x = np.arange(len(iq))
    ax.plot(x, iq.Import, color=S2, lw=2, marker="o", ms=3, label="imported")
    ax.plot(x, iq.Local, color=S1, lw=2, marker="o", ms=3, label="local")
    ax.set_xticks(x[::2], [q.replace("Q", " Q") for q in iq.index[::2]], rotation=45, fontsize=6.5)
    ax.set_ylabel("gross margin %")
    ax.legend()
    save(fig, "p07_import_local")


def articles():
    a = pd.read_parquet(R / "article_l12m.parquet")
    a = a[(a.Net_KZ > 1e6) & a.Margin_Pct.between(-60, 70) & a.MainGroup.isin(main_groups())]
    gl = a.groupby("MainGroup").Net_KZ.sum().sort_values(ascending=False).index
    cmap = {g: (PAL + ["#b0bec5", "#ffcc80", "#a5d6a7", "#ef9a9a"])[i] for i, g in enumerate(gl)}
    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    ax.scatter(a.Net_KZ / 1e6, a.Margin_Pct, s=6 + a.GP_KZ.clip(lower=0) / a.GP_KZ.max() * 300,
               c=[cmap[g] for g in a.MainGroup], alpha=.5, edgecolor="none")
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.axhline(0, color=NEG, lw=.9)
    ax.axhline(np.average(a.Margin_Pct, weights=a.Net_KZ), color=INK2, lw=.8, ls="--")
    ax.set_xlabel("article net sales, million Kz, L12M (log)")
    ax.set_ylabel("gross margin %")
    for g in list(cmap)[:10]:
        ax.scatter([], [], color=cmap[g], label=TITLE(g), s=20)
    ax.legend(ncol=5, fontsize=6.5, loc="upper left", bbox_to_anchor=(0, 1.16))
    save(fig, "p08_article_scatter")

    d = rd("decile")
    fig, ax = plt.subplots(figsize=(4.6, 2.8))
    ax.bar(d.Decile.astype(str), d.Margin_Pct.clip(lower=-20), color=[NEG if v < 0 else S1 for v in d.Margin_Pct])
    for i, (v, n) in enumerate(zip(d.Margin_Pct, d.Loss_Makers)):
        ax.annotate(f"{v:.0f}%\n{n} loss", (i, max(v, -20)), ha="center", va="bottom" if v >= 0 else "top",
                    xytext=(0, 2 if v >= 0 else -2), textcoords="offset points", fontsize=6)
    ax.axhline(0, color=INK2, lw=.8)
    ax.set_xlabel("article sales decile (D1 = smallest 10% of articles)")
    ax.set_ylabel("gross margin %")
    ax.set_ylim(-32, 34)
    ax.grid(axis="x", visible=False)
    save(fig, "p09_decile")

    l = label_sub(rd("loss_subgroups").head(12))[::-1]
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ax.barh(l.Label, l.Loss_KZ / 1e6, color=NEG, height=.6)
    for yi, (v, n) in enumerate(zip(l.Loss_KZ / 1e6, l.Articles)):
        ax.annotate(f"{v:.0f}m · {n} art.", (v, yi), xytext=(-3, 0), textcoords="offset points", ha="right",
                    va="center", fontsize=6.3, color=INK2)
    ax.tick_params(axis="y", labelsize=6.8)
    ax.set_xlabel("gross loss of loss-making articles, million Kz")
    ax.margins(x=.35)
    ax.grid(axis="y", visible=False)
    save(fig, "p10_loss_subgroups")


def stores():
    sm = rd("store_month")
    sm = sm[sm.Month >= "2024-01"]
    p = sm.pivot(index="Store_Name", columns="Month", values="Margin_Pct")
    p = p[p.notna().sum(axis=1) == p.shape[1]]          # stores trading in every month since Jan 2024
    order = p.loc[:, "2025-10":].mean(axis=1).sort_values(ascending=False).index
    p = p.loc[order]
    p.index = [NAME(i)[:20] for i in p.index]
    p.columns = [c[2:] for c in p.columns]
    fig, ax = plt.subplots(figsize=(7.6, 5.4))
    heat(ax, p, DIV, "", center=20, vmin=12, vmax=28, cbar_label="gross margin %")
    ax.tick_params(axis="x", labelsize=6, rotation=90)
    ax.tick_params(axis="y", labelsize=6.5)
    ax.set_title(f"Gross margin % by store and month ({len(p)} stores trading since Jan 2024; sorted by L12M margin)")
    save(fig, "p11_store_margin_heat")

    c = rd("store_margin_change").sort_values("Margin_Change_pp")
    fig, ax = plt.subplots(figsize=(7.4, 2.9))
    x = np.arange(len(c))
    ax.bar(x, c.Margin_Change_pp, color=[NEG if v < 0 else S3 for v in c.Margin_Change_pp])
    ax.set_xticks(x, [NAME(s)[:16] for s in c.Store_Name], rotation=90, fontsize=5.8)
    ax.axhline(0, color=INK2, lw=.8)
    ax.set_ylabel("margin change, pp\n(L12M vs prior 12M)")
    ax.grid(axis="x", visible=False)
    ax.margins(x=.01)
    save(fig, "p12_store_margin_change")

    st = pd.read_parquet(R / "store_l12m.parquet")
    st = st[st.Channel.eq("STORE") & st.Months.eq(12)].sort_values("GP_KZ", ascending=False)
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    x = np.arange(len(st))
    ax.bar(x, st.GP_KZ / 1e9, color=S1)
    ax.set_ylabel("gross profit, bn Kz (L12M)")
    a2 = ax.twinx()
    a2.plot(x, st.Margin_Pct, color=S2, marker="o", ms=2.5, lw=0)
    a2.set_ylim(14, 26)
    a2.set_ylabel("gross margin %", color=S2)
    a2.grid(False)
    a2.spines["right"].set_visible(True)
    ax.set_xticks(x, [NAME(s)[:16] for s in st.Store_Name], rotation=90, fontsize=5.8)
    ax.grid(axis="x", visible=False)
    ax.margins(x=.01)
    save(fig, "p13_store_gp")

    g = rd("store_group_gap")
    g = g[g.MainGroup.isin(main_groups()[:10])]
    pv = g.pivot(index="Store_Name", columns="MainGroup", values="Gap_pp")
    up = g.groupby("Store_Name").Uplift_KZ.sum()
    pv = pv.loc[up.sort_values(ascending=False).index[:25]]
    pv.index = [f"{NAME(i)[:20]} ({up[i] / 1e6:.0f}m)" for i in pv.index]
    pv.columns = [TITLE(c) for c in pv.columns]
    fig, ax = plt.subplots(figsize=(7.6, 5.2))
    heat(ax, pv, DIV, "{:+.0f}", center=0, vmin=-6, vmax=6, cbar_label="margin vs median store, pp")
    ax.tick_params(axis="x", labelsize=7, rotation=40)
    plt.setp(ax.get_xticklabels(), ha="right")
    ax.tick_params(axis="y", labelsize=6.8)
    ax.set_title("25 stores with the largest gap to the median store, by main group (L12M)")
    save(fig, "p14_store_group_gap")

    ug = g.groupby("MainGroup").Uplift_KZ.sum().sort_values()
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    ax.barh([TITLE(i) for i in ug.index], ug / 1e6, color=S3)
    for yi, v in enumerate(ug / 1e6):
        ax.annotate(f"{v:.0f}m", (v, yi), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6.5)
    ax.set_xlabel("GP if below-median stores reached the median, million Kz")
    ax.tick_params(axis="y", labelsize=7)
    ax.margins(x=.18)
    ax.grid(axis="y", visible=False)
    save(fig, "p15_gap_uplift_group")


def leakage():
    m = pd.read_parquet(R / "anomaly_monthly.parquet").set_index("Month")
    fig, ax = plt.subplots(figsize=(7.4, 2.6))
    ax.bar(months(m.index), -m.Below_Cost_Loss_KZ / 1e6, width=22, color=NEG, alpha=.85)
    ax.set_ylabel("loss on below-cost sales,\nmillion Kz")
    ax.grid(axis="x", visible=False)
    save(fig, "p16_below_cost_month")

    for name, col, out, lab in [("below_cost_group", "MainGroup", "p17_below_cost_group", TITLE),
                                ("below_cost_store", "Store_Name", "p18_below_cost_store", lambda s: NAME(s)[:16])]:
        d = rd(name).head(12)[::-1]
        fig, ax = plt.subplots(figsize=(3.7, 3.0))
        ax.barh([lab(s) for s in d[col]], -d.Loss_KZ / 1e6, color=NEG, height=.6)
        for yi, v in enumerate(-d.Loss_KZ / 1e6):
            ax.annotate(f"{v:.0f}m", (v, yi), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6.3)
        ax.tick_params(axis="y", labelsize=6.6)
        ax.set_xlabel("loss, million Kz, L12M")
        ax.margins(x=.2)
        ax.grid(axis="y", visible=False)
        save(fig, out)

    d = rd("discount_cost")
    d = d[d.MainGroup.isin(main_groups())].sort_values("Disc_KZ")
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ax.barh([TITLE(g) for g in d.MainGroup], d.Disc_KZ / 1e6, color=S4, height=.6)
    for yi, (v, pg) in enumerate(zip(d.Disc_KZ / 1e6, d.Disc_of_GP_Pct)):
        ax.annotate(f"{v:.0f}m · {pg:.1f}% of GP", (v, yi), xytext=(3, 0), textcoords="offset points", va="center",
                    fontsize=6.2)
    ax.tick_params(axis="y", labelsize=6.8)
    ax.set_xlabel("recorded discount, million Kz, L12M")
    ax.margins(x=.45)
    ax.grid(axis="y", visible=False)
    save(fig, "p19_discount_cost")

    t = pd.read_parquet(R / "tpr_by_group.parquet")
    t = t[t.MainGroup.isin(main_groups())].sort_values("Total_GP_Change_KZ")
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ax.barh([TITLE(g) for g in t.MainGroup], t.Total_GP_Change_KZ / 1e6,
            color=[NEG if v < 0 else S3 for v in t.Total_GP_Change_KZ], height=.6)
    ax.axvline(0, color=INK2, lw=.8)
    ax.tick_params(axis="y", labelsize=6.8)
    ax.set_xlabel("GP change in temporary-cut weeks vs baseline,\nmillion Kz (Jan 2023 – Sep 2026)")
    ax.grid(axis="y", visible=False)
    save(fig, "p20_tpr_gp_group")


def main():
    overview()
    category()
    articles()
    stores()
    leakage()
    print("pm charts done")


if __name__ == "__main__":
    main()
