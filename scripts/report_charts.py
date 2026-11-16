"""Render every chart for the PDF report into report/pdf_charts/*.png (and print key numbers)."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

ROOT = Path(__file__).resolve().parents[1]
A, DEEP, CL = ROOT / "analysis", ROOT / "analysis" / "deep", ROOT / "clean"
OUT = ROOT / "report" / "pdf_charts"
OUT.mkdir(parents=True, exist_ok=True)
J = json.load(open(ROOT / "report" / "data.json"))

INK, INK2, MUTED, GRID, AXIS = "#15201b", "#4d5751", "#7f8781", "#e3e6e2", "#c4cac3"
S1, S2, S3, S4, S5 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#4a3aa7"
ACC, NEG, POS, MID = "#0f6b55", "#d03b3b", "#2a78d6", "#f0efec"
DIV = LinearSegmentedColormap.from_list("div", [NEG, "#f2b8b5", MID, "#a9c9f0", POS])
SEQ = LinearSegmentedColormap.from_list("seq", ["#f4f8fd", "#9ec5f4", "#3987e5", "#1c5cab", "#0d366b"])
plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": .6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 8,
    "figure.dpi": 200, "savefig.bbox": "tight", "savefig.pad_inches": .05, "text.color": INK})
TITLE = lambda s: str(s).title().replace("Fnv", "FNV").replace("Hdds", "HDDS")
NUM = {}


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", facecolor="white")
    plt.close(fig)


def heat(ax, df, cmap, fmt="{:.0f}", center=None, vmin=None, vmax=None, cbar_label=None):
    v = df.to_numpy(dtype=float)
    norm = TwoSlopeNorm(vcenter=center, vmin=vmin if vmin is not None else np.nanmin(v),
                        vmax=vmax if vmax is not None else np.nanmax(v)) if center is not None else None
    im = ax.imshow(v, cmap=cmap, aspect="auto", norm=norm, vmin=None if norm else vmin, vmax=None if norm else vmax)
    ax.set_xticks(range(df.shape[1]), [str(c) for c in df.columns])
    ax.set_yticks(range(df.shape[0]), [str(i) for i in df.index])
    ax.grid(False)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    lo, hi = im.norm.vmin, im.norm.vmax
    for i in range(v.shape[0]):
        for j in range(v.shape[1]):
            if np.isnan(v[i, j]):
                continue
            r, g, b, _ = im.cmap(im.norm(v[i, j]))
            dark = 0.299 * r + 0.587 * g + 0.114 * b < 0.55
            ax.text(j, i, fmt.format(v[i, j]), ha="center", va="center", fontsize=7.2,
                    color="white" if dark else INK)
    cb = plt.colorbar(im, ax=ax, fraction=.03, pad=.015)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7, length=0)
    if cbar_label:
        cb.set_label(cbar_label, fontsize=7.5, color=INK2)
    return im


def dots(ax, names, est, se, color=S1, ref=None):
    y = np.arange(len(names))
    ax.hlines(y, est - 1.96 * se, est + 1.96 * se, color=color, lw=2, alpha=.55)
    ax.scatter(est, y, s=34, color=color, zorder=3, edgecolor="white", linewidth=1.2)
    for yi, e, h in zip(y, est, est + 1.96 * se):
        ax.annotate(f"{e:.2f}", (h, yi), xytext=(4, 0), textcoords="offset points", va="center", fontsize=7,
                    color=INK2)
    ax.margins(x=.12)
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    if ref is not None:
        ax.axvline(ref, color=INK2, lw=.8, ls="--")
    ax.axvline(0, color=AXIS, lw=.8)


# ---------------------------------------------------------------- 1 market & sales
def sales_charts():
    m = pd.Index(pd.to_datetime(J["months"]))
    idx = lambda a: np.array(a, dtype=float) / a[0] * 100
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    for lab, key, c, lw in [("Sales, kwanza", "chain_kz", S2, 1.6), ("Sales, USD", "chain_usd", S4, 1.6),
                            ("Sales, real kwanza", "chain_real", S1, 1.6), ("Like-for-like stores, real", "lfl_real", S3, 2.4)]:
        ax.plot(m, idx(J[key]), color=c, lw=lw, label=lab)
    ax.axhline(100, color=AXIS, lw=.8)
    ax.set_ylabel("Index, Jan 2023 = 100")
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, 1.13))
    save(fig, "01_sales_index")

    lm = pd.read_parquet(DEEP / "lfl_monthly_macro.parquet")
    r = lm.Real.copy()
    r.index = pd.PeriodIndex(r.index, freq="M")
    t = pd.DataFrame({"Year": r.index.year, "Mon": r.index.month, "v": r.values / 1e9})
    t = t.pivot(index="Year", columns="Mon", values="v")
    t.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][:t.shape[1]]
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    heat(ax, t, SEQ, "{:.1f}", cbar_label="bn Kz (Jan 2023 prices)")
    ax.set_title("Like-for-like real sales by month (32 stores open throughout)")
    save(fig, "02_calendar_heat")

    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    mn = list("JFMAMJJASOND")
    s = np.array(J["season"])
    ax.bar(range(12), s, color=[S1 if v >= 100 else AXIS for v in s], width=.75)
    ax.axhline(100, color=INK2, lw=.8, ls="--")
    ax.set_xticks(range(12), mn)
    ax.set_ylim(70, 160)
    ax.set_title("Seasonality (average month = 100)")
    ax.grid(axis="x", visible=False)
    save(fig, "03_seasonality")

    dm = pd.read_parquet(DEEP / "day_of_month.parquet")
    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    ax.bar(dm.index, dm["mean"], color=[S2 if (d >= 25 or d <= 3) else S1 for d in dm.index], width=.8)
    ax.axhline(100, color=INK2, lw=.8, ls="--")
    ax.set_ylim(80, max(120, dm["mean"].max() + 3))
    ax.set_title("Sales by day of month (month avg = 100)")
    ax.set_xticks([1, 5, 10, 15, 20, 25, 31])
    ax.grid(axis="x", visible=False)
    save(fig, "04_day_of_month")
    NUM["payday_days"] = dm.loc[[25, 26, 27, 28, 29, 30, 31, 1, 2, 3], "mean"].mean()
    NUM["mid_days"] = dm.loc[10:20, "mean"].mean()

    wd = pd.read_parquet(DEEP / "weekday_by_group.parquet")
    wd.columns = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    wd.index = [TITLE(i) for i in wd.index]
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    heat(ax, wd, DIV, "{:.0f}", center=100, cbar_label="index, week avg = 100")
    ax.set_title("Weekday pattern by category")
    save(fig, "05_weekday_heat")
    NUM["weekday"] = wd.mean().round(1).to_dict()

    gy = pd.read_parquet(DEEP / "group_year_volume.parquet")["Real"]
    g = (gy.pct_change(axis=1) * 100).iloc[:, 1:]
    g.index = [TITLE(i) for i in g.index]
    g.columns = [f"{c} vs {int(c) - 1}" for c in g.columns]
    fig, ax = plt.subplots(figsize=(6.4, 2.9))
    heat(ax, g, DIV, "{:+.0f}%", center=0, vmin=-40, vmax=40, cbar_label="real sales change, Jan-Sep")
    ax.set_title("Like-for-like real sales growth by category (Jan-Sep each year, inflation-adjusted)")
    save(fig, "06_group_year_volume")
    NUM["group_year"] = g.round(1).to_dict()


# ---------------------------------------------------------------- 2 prices & macro
def price_macro_charts():
    pm = pd.to_datetime(J["pi_months"])
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    for lab, key, c, lw in [("Fresmart price index", "pi_Fresmart_Price_Index", S1, 2.4),
                            ("Consumer prices (CPI)", "pi_CPI", S2, 1.6), ("Kwanza per USD (BNA)", "pi_FX_BNA", S3, 1.6)]:
        ax.plot(pm, J[key], color=c, lw=lw, label=lab)
    ax.axhline(100, color=AXIS, lw=.8)
    ax.set_ylabel("Index, Feb 2023 = 100")
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.13))
    save(fig, "10_price_vs_cpi_fx")

    ci = pd.read_parquet(DEEP / "category_price_index.parquet")
    ci.index = pd.to_datetime(ci.index)
    cpi = pd.Series(J["pi_CPI"], index=pm)
    groups = [c for c in ["POULTRY", "CATTLE", "DRY-COMMODITY", "BEVERAGES", "DAIRY PRODUCTS", "DRY DIVISION",
                          "FNV", "CHARCUTARIA", "PERSONAL CARE", "HOUSEHOLD"] if c in ci]
    fig, axs = plt.subplots(2, 5, figsize=(7.4, 3.3), sharex=True, sharey=True)
    for ax, gname in zip(axs.flat, groups):
        s = ci[gname] / ci[gname].iloc[0] * 100
        ax.plot(cpi.index, cpi / cpi.iloc[0] * 100, color=AXIS, lw=1.2)
        ax.plot(s.index, s, color=S1, lw=1.6)
        ax.set_title(TITLE(gname), fontsize=8)
        ax.text(s.index[-1], s.iloc[-1], f" {s.iloc[-1]:.0f}", fontsize=6.5, va="center", color=INK2)
        ax.tick_params(labelsize=6.5)
        ax.xaxis.set_major_locator(matplotlib.dates.YearLocator())
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%y"))
    fig.suptitle("Category price index (blue) vs consumer prices (grey), Feb 2023 = 100", x=.01, ha="left",
                 fontsize=9, fontweight="bold")
    fig.tight_layout()
    save(fig, "11_category_index_multiples")

    pt = pd.read_parquet(DEEP / "passthrough.parquet")
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 3.2), sharey=True)
    for ax, drv, title in zip(axs, ["FX", "Brent"], ["Exchange rate (BNA, kwanza per USD)", "Brent oil (USD)"]):
        d = pt[pt.Driver == drv].pivot(index="Group", columns="Lag", values="Cumulative_PassThrough")
        d = d.reindex(["ALL"] + [g for g in d.index if g != "ALL"]) * 100
        d.index = ["All Fresmart" if i == "ALL" else TITLE(i) for i in d.index]
        v = np.clip(d.to_numpy(), -150, 150)
        im = ax.imshow(v, cmap=DIV, norm=TwoSlopeNorm(0, -100, 100) if drv != "Brent" else TwoSlopeNorm(0, -30, 30),
                       aspect="auto")
        for i in range(v.shape[0]):
            for j in range(v.shape[1]):
                r, g, b, _ = im.cmap(im.norm(v[i, j]))
                ax.text(j, i, f"{d.iat[i, j]:.0f}", ha="center", va="center", fontsize=6.5,
                        color="white" if 0.299 * r + 0.587 * g + 0.114 * b < 0.55 else INK)
        ax.set_xticks(range(7), [f"{k}" for k in range(7)])
        ax.set_yticks(range(len(d)), d.index)
        ax.set_xlabel("months after the change")
        ax.set_title(title, fontsize=8.5)
        ax.grid(False)
        ax.tick_params(length=0, labelsize=7)
    fig.suptitle("Price pass-through: cumulative % of a 1% move that reaches Fresmart prices", x=.01, ha="left",
                 fontsize=9, fontweight="bold")
    fig.tight_layout()
    save(fig, "12_passthrough_heat")
    fx6 = pt[(pt.Driver == "FX") & (pt.Lag == 6)].set_index("Group").Cumulative_PassThrough * 100
    fx1 = pt[(pt.Driver == "FX") & (pt.Lag == 1)].set_index("Group").Cumulative_PassThrough * 100
    cpi6 = pt[(pt.Driver == "CPI") & (pt.Lag == 6)].set_index("Group").Cumulative_PassThrough * 100
    br6 = pt[(pt.Driver == "Brent") & (pt.Lag == 6)].set_index("Group").Cumulative_PassThrough * 100
    NUM["pt_fx6"], NUM["pt_fx1"], NUM["pt_cpi6"], NUM["pt_br6"] = (s.round(0).to_dict() for s in (fx6, fx1, cpi6, br6))

    lm = pd.read_parquet(DEEP / "lfl_monthly_macro.parquet")
    lm["KG_YoY"] = lm.KG.pct_change(12, fill_method=None) * 100
    lm["Real_YoY"] = lm.Real.pct_change(12, fill_method=None) * 100
    lm["FX_YoY"] = lm.FX_BNA_Avg.pct_change(12, fill_method=None) * 100
    d = lm.dropna(subset=["KG_YoY"])
    fig, axs = plt.subplots(1, 4, figsize=(7.4, 2.2), sharey=True)
    corr = {}
    for ax, (col, lab) in zip(axs, [("FX_YoY", "Kwanza depreciation, % YoY"), ("Inflation_YoY_Pct", "Inflation, % YoY"),
                                    ("Brent_USD", "Brent, USD/bbl"), ("GDP_Real_YoY_Pct_Q", "Real GDP growth, %")]):
        dd = d[[col, "KG_YoY"]].dropna()
        ax.scatter(dd[col], dd.KG_YoY, s=14, color=S1, alpha=.85, edgecolor="white", linewidth=.5)
        b = np.polyfit(dd[col], dd.KG_YoY, 1)
        xs = np.linspace(dd[col].min(), dd[col].max(), 10)
        ax.plot(xs, np.polyval(b, xs), color=S2, lw=1.4)
        r = dd.corr().iat[0, 1]
        corr[col] = r
        ax.set_title(f"r = {r:+.2f}", fontsize=8)
        ax.set_xlabel(lab, fontsize=7.2)
        ax.tick_params(labelsize=6.5)
    axs[0].set_ylabel("LFL volume, % YoY", fontsize=7.5)
    fig.tight_layout()
    save(fig, "13_volume_vs_macro")
    NUM["macro_corr_vol"] = {k: round(v, 2) for k, v in corr.items()}

    cm = d[["Real_YoY", "KG_YoY", "FX_YoY", "Inflation_YoY_Pct", "Brent_USD", "GDP_Real_YoY_Pct_Q"]].corr()
    names = ["Real sales YoY", "Volume YoY", "Depreciation YoY", "Inflation", "Brent", "GDP growth"]
    cm.index, cm.columns = names, names
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    heat(ax, cm, DIV, "{:+.2f}", center=0, vmin=-1, vmax=1)
    ax.set_xticklabels(names, rotation=30, ha="right")
    ax.set_title("Correlation: like-for-like sales vs macro (monthly)")
    save(fig, "14_macro_corr")

    pcy = J["pcy"]
    vals = np.array(pcy["vals"])
    cols = [NEG, "#f2b8b5", AXIS, "#a9c9f0", POS]
    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    left = np.zeros(len(vals))
    for k, c in enumerate(cols):
        ax.barh(pcy["years"], vals[:, k], left=left, color=c, edgecolor="white", label=pcy["cols"][k], height=.65)
        for i, v in enumerate(vals[:, k]):
            if v > 8:
                ax.text(left[i] + v / 2, i, f"{v:.0f}", ha="center", va="center", fontsize=6.5,
                        color="white" if k in (0, 4) else INK)
        left += vals[:, k]
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_title("Monthly price moves (% of article-stores)")
    ax.legend(ncol=3, fontsize=6, loc="upper left", bbox_to_anchor=(0, -.08))
    ax.grid(False)
    save(fig, "15_price_change_freq")

    pc = J["pi_months"]
    cats = ["CATTLE", "DRY-COMMODITY", "POULTRY", "FNV", "BEVERAGES", "DAIRY PRODUCTS", "DRY DIVISION"]
    last = lambda a: [v for v in a if v is not None][-1]
    rows = sorted([(TITLE(c), last(J["pi_" + c]) - 100) for c in cats] +
                  [("All Fresmart", last(J["pi_Fresmart_Price_Index"]) - 100), ("Consumer prices", last(J["pi_CPI"]) - 100)],
                  key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    ax.barh([r[0] for r in rows], [r[1] for r in rows],
            color=[S2 if r[0] == "Consumer prices" else INK2 if r[0] == "All Fresmart" else S1 for r in rows], height=.65)
    for i, r in enumerate(rows):
        ax.text(r[1] + 2, i, f"+{r[1]:.0f}%", va="center", fontsize=7, color=INK2)
    ax.set_title("Price rise, Feb 2023 → Aug 2026")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(r[1] for r in rows) * 1.18)
    save(fig, "16_category_inflation")


# ---------------------------------------------------------------- 3 stock x price
def stock_charts():
    h = pd.read_parquet(DEEP / "stock_cover_vs_next_price.parquet")
    fig, ax = plt.subplots(figsize=(5.6, 2.5))
    heat(ax, h, SEQ, "{:.1f}%", cbar_label="% of article-store months")
    ax.set_xlabel("relative price change in the following month")
    ax.set_ylabel("stock cover this month")
    ax.set_title("Do prices move when stock is high or low?")
    save(fig, "20_cover_vs_price_move")
    NUM["cover_cut10"] = h["cut >10%"].round(1).to_dict() if "cut >10%" in h else {}
    NUM["cover_rise"] = (h.get("rise 3-10%", 0) + h.get("rise >10%", 0)).round(1).to_dict()
    NUM["cover_cut"] = (h.get("cut 3-10%", 0) + h.get("cut >10%", 0)).round(1).to_dict()

    o = pd.read_parquet(DEEP / "oos_next_by_relprice.parquet")
    o.index = [TITLE(i) for i in o.index]
    fig, ax = plt.subplots(figsize=(5.6, 2.8))
    heat(ax, o, SEQ, "{:.1f}%", cbar_label="% out of stock next month")
    ax.set_xlabel("relative price vs category this month (1.0 = in line)")
    ax.set_title("Stock-outs next month by how cheap the article is")
    save(fig, "21_oos_by_relprice")
    NUM["oos_rel"] = o.mean().round(2).to_dict()


# ---------------------------------------------------------------- 4 location
def location_charts():
    st = pd.read_parquet(DEEP / "store_price_premium.parquet").sort_values("Price_Premium_pct")
    zones = sorted(st.Area_Zone.unique())
    zc = dict(zip(zones, [S1, S2, S3, S4, "#e87ba4", "#008300", S5, NEG, MUTED, "#8d6e63", "#00838f"]))
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.bar(range(len(st)), st.Price_Premium_pct, color=[zc[z] for z in st.Area_Zone], width=.8)
    ax.axhline(0, color=INK2, lw=.8)
    ax.set_xticks(range(len(st)), [n.replace(" FRESMART EXPRESS", "").replace(" FRESMART", " (LF)")[:16].title()
                                   for n in st.Store_Name], rotation=90, fontsize=5.6)
    ax.set_ylabel("% vs chain median price")
    ax.grid(axis="x", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=zc[z]) for z in zones]
    ax.legend(handles, [TITLE(z) for z in zones], ncol=6, fontsize=6.3, loc="upper left", bbox_to_anchor=(0, 1.2))
    save(fig, "30_store_premium")
    NUM["premium_range"] = (st.Price_Premium_pct.min(), st.Price_Premium_pct.max())
    NUM["premium_by_zone"] = st.groupby("Area_Zone").Price_Premium_pct.mean().round(1).to_dict()
    NUM["premium_by_class"] = st.groupby("Store_Class").Price_Premium_pct.mean().round(1).to_dict()

    fig, axs = plt.subplots(1, 2, figsize=(7.4, 2.6))
    for cls, c in zip(["A", "B", "C", "P"], [S1, S3, S4, S2]):
        d = st[st.Store_Class == cls]
        axs[0].scatter(d.Price_Premium_pct, d.USD_per_Sqm_Month, s=22, color=c, label=f"Class {cls}",
                       edgecolor="white", linewidth=.6)
        axs[1].scatter(d.Total_Sqm, d.USD_per_Month / 1e3, s=22, color=c, edgecolor="white", linewidth=.6)
    axs[0].set_xlabel("price premium vs chain, %")
    axs[0].set_ylabel("sales per m² per month, USD")
    axs[0].legend(fontsize=6.5, ncol=2)
    axs[0].set_title("Price level vs productivity", fontsize=8.5)
    axs[1].set_xlabel("store size, m²")
    axs[1].set_ylabel("sales per month, USD k")
    axs[1].set_title("Store size vs sales", fontsize=8.5)
    fig.tight_layout()
    save(fig, "31_premium_vs_productivity")
    NUM["corr_premium_sqm"] = round(st[["Price_Premium_pct", "USD_per_Sqm_Month"]].corr().iat[0, 1], 2)

    zg = pd.read_parquet(DEEP / "zone_group_premium.parquet")
    zg.index, zg.columns = [TITLE(i) for i in zg.index], [TITLE(c) for c in zg.columns]
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    heat(ax, zg, DIV, "{:+.1f}", center=0, vmin=-6, vmax=6, cbar_label="% vs chain median")
    ax.set_xticklabels(zg.columns, rotation=30, ha="right")
    ax.set_title("Price level by zone and category (% vs chain median for the same article and month)")
    save(fig, "32_zone_group_premium")

    ez = pd.read_parquet(DEEP / "elasticity_zone_group.parquet")
    ez = ez[ez.SE < .5].pivot(index="Area_Zone", columns="MainGroup", values="Elasticity")
    ez.index, ez.columns = [TITLE(i) for i in ez.index], [TITLE(c) for c in ez.columns]
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    heat(ax, ez.clip(-3, 0.5), LinearSegmentedColormap.from_list("e", [NEG, "#f2b8b5", MID, "#a9c9f0"]), "{:.2f}",
         center=-1, vmin=-3, vmax=0.5, cbar_label="elasticity (red = more sensitive)")
    ax.set_xticklabels(ez.columns, rotation=30, ha="right")
    ax.set_title("Price elasticity by zone and category")
    save(fig, "33_zone_group_elasticity")

    es = pd.read_parquet(DEEP / "elasticity_store.parquet").sort_values("Elasticity")
    fig, ax = plt.subplots(figsize=(7.4, 2.8))
    cc = {"A": S1, "B": S3, "C": S4, "P": S2}
    ax.bar(range(len(es)), es.Elasticity, color=[cc.get(c, MUTED) for c in es.Store_Class], width=.8)
    ax.errorbar(range(len(es)), es.Elasticity, yerr=1.96 * es.SE, fmt="none", ecolor=INK2, lw=.6, capsize=0)
    ax.axhline(-1, color=INK2, lw=.8, ls="--")
    ax.set_xticks(range(len(es)), [n.replace(" FRESMART EXPRESS", "").replace(" FRESMART", " (LF)")[:16].title()
                                   for n in es.Store_Name], rotation=90, fontsize=5.6)
    ax.set_ylabel("elasticity")
    ax.grid(axis="x", visible=False)
    ax.legend([plt.Rectangle((0, 0), 1, 1, color=v) for v in cc.values()], [f"Class {k}" for k in cc], ncol=4,
              fontsize=6.5, loc="lower right")
    save(fig, "34_store_elasticity")
    NUM["store_el_range"] = (es.Elasticity.min(), es.Elasticity.max(), es.Store_Name.iloc[0], es.Store_Name.iloc[-1])

    mix = pd.read_parquet(DEEP / "zone_category_mix.parquet")
    mix.index, mix.columns = [TITLE(i) for i in mix.index], [TITLE(c) for c in mix.columns]
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    heat(ax, mix, SEQ, "{:.0f}%", cbar_label="% of zone sales (top 10 categories)")
    ax.set_xticklabels(mix.columns, rotation=30, ha="right")
    ax.set_title("Category mix by zone")
    save(fig, "35_zone_mix")

    seg = pd.DataFrame(J["seg"])
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 2.6), gridspec_kw={"width_ratios": [1, 1.6]})
    for ax, s in zip(axs, ["Store_Class", "Area_Zone"]):
        d = seg[seg.Segment == s].sort_values("Estimate")
        dots(ax, [("Class " + v) if s == "Store_Class" else TITLE(v) for v in d.Value], d.Estimate.values,
             d["Std. Error"].values, S1, ref=-1)
        ax.set_title("By store class" if s == "Store_Class" else "By zone", fontsize=8.5)
    fig.tight_layout()
    save(fig, "36_class_zone_elasticity")


# ---------------------------------------------------------------- 5 elasticity
def elasticity_charts():
    P = pd.DataFrame(J["pooled"])
    g = lambda m, t: P[P.Model.str.startswith(m) & (P.Term == t)].iloc[0]
    rows = [("Raw kwanza price", g("M0", "ln_Price_Nominal"), MUTED), ("Inflation-adjusted", g("M1", "ln_Price_Real"), S1),
            ("Relative to category", g("M2", "ln_Relative_Price"), ACC), ("Price above usual", g("M3", "ln_Rel_Above"), NEG),
            ("Price below usual", g("M3", "ln_Rel_Below"), POS)]
    fig, ax = plt.subplots(figsize=(5.6, 2.3))
    for i, (n, r, c) in enumerate(rows):
        ax.barh(i, r.Estimate, color=c, height=.6)
        ax.errorbar(r.Estimate, i, xerr=1.96 * r["Std. Error"], color=INK, lw=1, capsize=2)
        ax.text(r.Estimate - .05, i, f"{r.Estimate:.2f}", ha="right", va="center", fontsize=7.5, color=INK)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.axvline(0, color=AXIS)
    ax.set_xlim(-1.6, 0.05)
    ax.grid(axis="y", visible=False)
    ax.set_title("Chain elasticity by price measure (95% interval)")
    save(fig, "40_bias_asym")

    seg = pd.DataFrame(J["seg"])
    d = seg[(seg.Segment == "MainGroup") & (seg.Articles >= 5)].sort_values("Estimate")
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    dots(ax, [TITLE(v) for v in d.Value], d.Estimate.values, d["Std. Error"].values, S1, ref=-1)
    ax.set_title("Elasticity by category (95% interval)")
    save(fig, "41_group_elasticity")

    sp = pd.read_parquet(DEEP / "elasticity_splits.parquet")
    infl = {"2023": "infl. 13-20%", "2024": "infl. 22-31%", "2025": "infl. 16-26%", "2026": "infl. 9-15%"}
    fig, axs = plt.subplots(1, 3, figsize=(7.4, 2.4), gridspec_kw={"width_ratios": [1, 1.25, 1]})
    for ax, dim, title in zip(axs, ["Year", "Stock cover", "Price tier"], ["By year", "By stock cover", "By price tier"]):
        d = sp[sp.Dimension == dim]
        if dim == "Year":
            names = [f"{v} ({infl.get(v, '')})" for v in d.Value]
        else:
            names = list(d.Value)
        dots(ax, names, d.Elasticity.values, d.SE.values, S5 if dim == "Year" else S1, ref=-1)
        ax.set_title(title, fontsize=8.5)
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    save(fig, "42_splits")
    NUM["splits"] = sp[["Dimension", "Value", "Elasticity", "SE"]].round(2).to_dict("records")

    a = pd.read_parquet(A / "article_elasticity.parquet")
    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    bins = np.arange(-5, 2.01, .25)
    n, b, patches = ax.hist(a.Elasticity.clip(-5, 2), bins=bins, color=S1, edgecolor="white", linewidth=.5)
    for p_, left in zip(patches, b[:-1]):
        p_.set_facecolor(S2 if left < -1 else S1 if left < 0 else MUTED)
    ax.axvline(-1, color=INK2, lw=.8, ls="--")
    ax.set_title(f"{len(a):,} article elasticities")
    ax.grid(axis="x", visible=False)
    save(fig, "43_article_hist")

    mv = pd.read_parquet(DEEP / "margin_vs_elasticity.parquet").dropna()
    mv = mv[(mv.Articles >= 8)]
    mv = mv.sort_values("Sales_KZ", ascending=False).head(45)
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    size = mv.Sales_KZ / mv.Sales_KZ.max() * 600 + 12
    ax.scatter(mv.Elasticity, mv.Margin_pct, s=size, color=S1, alpha=.55, edgecolor="white", linewidth=.8)
    xs = np.linspace(-6, -1.05, 50)
    ax.plot(xs, -100 / xs, color=S2, lw=1.4, label="margin where price is profit-maximising (−1/elasticity)")
    for _, r in mv.head(18).iterrows():
        ax.annotate(TITLE(r.SubGroup), (r.Elasticity, r.Margin_pct), fontsize=6.3, color=INK2,
                    xytext=(4, 2), textcoords="offset points")
    ax.set_xlim(-6, 0.5)
    ax.set_ylim(0, max(60, mv.Margin_pct.max() + 5))
    ax.set_xlabel("price elasticity (sales-weighted, sub-category)")
    ax.set_ylabel("estimated gross margin, %")
    ax.axvline(-1, color=AXIS, lw=.8)
    ax.legend(loc="upper left", fontsize=7)
    ax.set_title("Margin vs price sensitivity by sub-category (bubble = sales)")
    save(fig, "44_margin_vs_elasticity")
    mv["Headroom"] = mv.Margin_pct < -100 / mv.Elasticity.clip(upper=-1.01)
    NUM["headroom_share"] = round(mv.loc[mv.Headroom, "Sales_KZ"].sum() / mv.Sales_KZ.sum() * 100, 0)
    NUM["over_priced"] = mv.loc[~mv.Headroom, "SubGroup"].tolist()


# ---------------------------------------------------------------- 6 price-change impact
def event_charts():
    ev = pd.DataFrame(J["events"])
    ev = ev[ev.Events >= 100]
    lab = [f"{'Cut' if d == 'price cut' else 'Rise'} {s}" for d, s in zip(ev.Direction, ev.Size)]
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 2.4))
    axs[0].barh(lab, ev.Median_Volume_Change_pct, color=[POS if d == "price cut" else NEG for d in ev.Direction],
                height=.6)
    for i, v in enumerate(ev.Median_Volume_Change_pct):
        axs[0].text(v + (1 if v > 0 else -1), i, f"{v:+.0f}%", va="center", ha="left" if v > 0 else "right",
                    fontsize=7, color=INK2)
    axs[0].axvline(0, color=AXIS)
    axs[0].invert_yaxis()
    axs[0].set_xlim(-38, 50)
    axs[0].set_title("Median volume change, 4 weeks after vs before", fontsize=8.5)
    axs[0].grid(axis="y", visible=False)
    pe = pd.read_parquet(A / "price_events.parquet")
    pe = pe[pe["Price_Change_%"].between(-30, 30)]
    bins = np.arange(-30, 31, 5)
    pe["b"] = pd.cut(pe["Price_Change_%"], bins)
    m = pe.groupby("b", observed=True)["Volume_Change_%"].median()
    centers = [i.mid for i in m.index]
    axs[1].plot(centers, m.values, color=S1, lw=2, marker="o", ms=3.5)
    axs[1].axhline(0, color=AXIS)
    axs[1].axvline(0, color=AXIS)
    axs[1].set_xlabel("price change, %")
    axs[1].set_ylabel("median volume change, %")
    axs[1].set_title("Response curve across all price changes", fontsize=8.5)
    fig.tight_layout()
    save(fig, "50_events")

    mg = pd.DataFrame(J["events_mg"])
    t = mg.pivot(index="MainGroup", columns="Direction", values="Median_Volume_Change_pct").dropna()
    t = t.loc[mg.groupby("MainGroup").Events.sum().loc[t.index].sort_values(ascending=False).index[:12]]
    t.index = [TITLE(i) for i in t.index]
    t.columns = ["After a cut", "After a rise"]
    fig, ax = plt.subplots(figsize=(4.2, 3.0))
    heat(ax, t, DIV, "{:+.0f}%", center=0, vmin=-25, vmax=25, cbar_label="median volume change")
    ax.set_title("Volume response by category")
    save(fig, "51_events_group_heat")


def main():
    for f in [sales_charts, price_macro_charts, stock_charts, location_charts, elasticity_charts, event_charts]:
        f()
        print(f"{f.__name__} done", flush=True)
    json.dump(NUM, open(ROOT / "report" / "pdf_numbers.json", "w"), default=str, indent=1)
    print(json.dumps(NUM, default=str, indent=1)[:6000])


if __name__ == "__main__":
    main()
