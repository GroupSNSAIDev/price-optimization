"""Assemble the Profit & Margin PDF -> output/Profit_Margin_Report/Fresmart_Profit_and_Margin_Report.pdf

Inputs: analysis/rda (rda_analysis.py, pm_analysis.py), report/rda_charts (rda_charts.py, pm_charts.py).
Price elasticity and demand drivers are in the companion Phase 1 EDA report; here they only size margin opportunities.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image as RLImage, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
R, CH_NEW, CH_OLD = ROOT / "analysis" / "rda", ROOT / "report" / "rda_charts", ROOT / "report" / "pdf_charts"
OUTD = ROOT / "output" / "Profit_Margin_Report"
OUTD.mkdir(parents=True, exist_ok=True)
OUTF = OUTD / "Fresmart_Profit_and_Margin_Report.pdf"
N = json.load(open(R / "numbers.json"))
J = json.load(open(ROOT / "report" / "data.json"))
PN = json.load(open(ROOT / "report" / "pdf_numbers.json"))
rd = lambda n: pd.read_parquet(R / f"{n}.parquet")

F = "C:/Windows/Fonts/"
for name, file in [("Body", "segoeui.ttf"), ("Body-Bold", "segoeuib.ttf"), ("Body-Italic", "segoeuii.ttf"),
                   ("Head", "georgiab.ttf"), ("Head-Reg", "georgia.ttf")]:
    pdfmetrics.registerFont(TTFont(name, F + file))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")

INK, INK2, MUTED, RULE = (colors.HexColor(c) for c in ("#15201b", "#4d5751", "#7f8781", "#dfe3de"))
ACC, SOFT, WARN = colors.HexColor("#0f6b55"), colors.HexColor("#e3efea"), colors.HexColor("#fbeee6")
W, H = A4
M = 17 * mm
CW = W - 2 * M
ST = {
    "h1": ParagraphStyle("h1", fontName="Head", fontSize=18, leading=23, textColor=INK, spaceAfter=7),
    "h2": ParagraphStyle("h2", fontName="Body-Bold", fontSize=11, leading=14.5, textColor=INK, spaceBefore=9,
                         spaceAfter=3),
    "body": ParagraphStyle("body", fontName="Body", fontSize=9.1, leading=13.1, textColor=INK, spaceAfter=5),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=9.1, leading=12.9, textColor=INK, leftIndent=12,
                             bulletIndent=2, spaceAfter=2.5),
    "cap": ParagraphStyle("cap", fontName="Body", fontSize=7.9, leading=10.4, textColor=INK2, spaceBefore=2,
                          spaceAfter=4),
    "insight": ParagraphStyle("insight", fontName="Body", fontSize=8.6, leading=12, textColor=INK, spaceAfter=9,
                              leftIndent=6, borderPadding=0),
    "kicker": ParagraphStyle("kicker", fontName="Body-Bold", fontSize=8, leading=10, textColor=ACC, spaceAfter=2),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=7.4, leading=9.4, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=7.4, leading=9.4, textColor=INK2),
    "box": ParagraphStyle("box", fontName="Body", fontSize=8.8, leading=12.6, textColor=INK),
    "num": ParagraphStyle("num", fontName="Head", fontSize=14, leading=17, textColor=ACC),
    "kpi_v": ParagraphStyle("kpi_v", fontName="Head", fontSize=15, leading=18, textColor=ACC, alignment=1),
    "kpi_l": ParagraphStyle("kpi_l", fontName="Body", fontSize=7.4, leading=9.2, textColor=INK2, alignment=1),
}
story = []
P = lambda t, s="body": story.append(Paragraph(t, ST[s]))
SECTION = [0]
FIGNO = [0]
TOC = []

title = lambda s: str(s).title().replace("Fnv", "FNV").replace("Hdds", "HDDS")
store = lambda s: str(s).replace(" FRESMART", "").replace(" EXPRESS", " Exp.").title()
bnk = lambda v: f"{v / 1e9:,.1f} bn Kz"
mnk = lambda v: f"{v / 1e6:,.0f}m Kz"
pc = lambda v, d=1: f"{v:.{d}f}%"
sp = lambda v, d=1: f"{v:+.{d}f}%"


def h1(t):
    SECTION[0] += 1
    TOC.append((str(SECTION[0]), t))
    story.append(PageBreak())
    story.append(Paragraph(f"Section {SECTION[0]}", ST["kicker"]))
    story.append(Paragraph(t, ST["h1"]))


def h2(t):
    story.append(CondPageBreak(70 * mm))     # never leave a sub-heading alone at the foot of a page
    story.append(Paragraph(t, ST["h2"]))


def bullets(items, style="bullet"):
    for t in items:
        story.append(Paragraph(t, ST[style], bulletText="•"))


def _img(name, width):
    path = (CH_NEW if name[0] in "rp" else CH_OLD) / f"{name}.png"
    w, h = Image.open(path).size
    img = RLImage(str(path), width=width, height=width * h / w)
    img.hAlign = "LEFT"
    return img


def fig(name, caption, insight, width=1.0):
    FIGNO[0] += 1
    parts = [_img(name, CW * width), Paragraph(f"<b>Figure {FIGNO[0]}.</b> {caption}", ST["cap"])]
    if insight:
        parts.append(_insight(insight))
    story.append(KeepTogether(parts))


def fig_pair(a, b, caption, insight):
    FIGNO[0] += 1
    t = Table([[_img(a, CW / 2 - 3 * mm), _img(b, CW / 2 - 3 * mm)]], colWidths=[CW / 2, CW / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    parts = [t, Paragraph(f"<b>Figure {FIGNO[0]}.</b> {caption}", ST["cap"])]
    if insight:
        parts.append(_insight(insight))
    story.append(KeepTogether(parts))


def _insight(text):
    t = Table([[Paragraph(f"<b>What it shows.</b> {text}", ST["insight"])]], colWidths=[CW])
    t.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, -1), 2, ACC), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def table(head, rows, widths, num_cols=(), caption=None):
    data = [[Paragraph(h, ST["cellb"]) for h in head]] + [[Paragraph(str(c), ST["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=[CW * w for w in widths], repeatRows=1)
    style = [("LINEBELOW", (0, 0), (-1, 0), .8, INK2), ("LINEBELOW", (0, 1), (-1, -1), .3, RULE),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.2),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2), ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
             ("RIGHTPADDING", (0, 0), (-1, -1), 3.5)]
    for c in num_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    cap = [Paragraph(f"<b>Table.</b> {caption}", ST["cap"])] if caption else []
    if len(rows) <= 25:          # short tables stay on one page with their caption
        story.append(KeepTogether(cap + [t, Spacer(1, 7)]))
    else:
        story.extend(cap + [t, Spacer(1, 7)])


def box(text, bg=SOFT):
    t = Table([[Paragraph(text, ST["box"])]], colWidths=[CW])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.append(KeepTogether([t, Spacer(1, 7)]))


def kpis(items):
    cells = [[Paragraph(v, ST["kpi_v"]) for v, _ in items], [Paragraph(l, ST["kpi_l"]) for _, l in items]]
    t = Table(cells, colWidths=[CW / len(items)] * len(items))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("LINEAFTER", (0, 0), (-2, -1), 1.5, colors.white),
                           ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 7)]))
    story.append(t)
    story.append(Spacer(1, 9))



# ------------------------------------------------------------------ data
PM = json.load(open(R / "pm_numbers.json"))
pm = lambda n: pd.read_parquet(R / f"pm_{n}.parquet")
mc = rd("monthly_chain").set_index("Month")
ytd = rd("yearly_ytd").set_index("Year")
mg = rd("maingroup_l12m")
mg_main = mg[mg.Sales_Share >= 0.3]
mgi = mg.set_index("MainGroup")
sg = rd("subgroup_l12m")
st = rd("store_l12m")
st_full = st[st.Channel.eq("STORE") & st.Months.eq(12)]
ix = rd("price_cost_index").set_index("Month")
pt = rd("cost_passthrough").set_index("MainGroup")
tpr_d = rd("tpr_by_depth").set_index("Depth_Bucket")
imp = rd("import_local_l12m").set_index("PurchaseType")
gm = pm("group_month")
L12 = mc.loc["2025-10":"2026-09"]
P12 = mc.loc["2024-10":"2025-09"]
L12_net, L12_gp = L12.Net_KZ.sum(), L12.GP_KZ.sum()
P12_net, P12_gp = P12.Net_KZ.sum(), P12.GP_KZ.sum()
L12_m, P12_m = L12_gp / L12_net * 100, P12_gp / P12_net * 100
gp_real_g = (L12.GP_Real.sum() / P12.GP_Real.sum() - 1) * 100
TOT_net, TOT_gp = mc.Net_KZ.sum(), mc.GP_KZ.sum()
y26, y25, y24, y23 = (ytd.loc[y] for y in ["2026", "2025", "2024", "2023"])
P_ = N["pareto"]
TP = N["tpr"]
cfix = N["cogs_fix"]
BR = PM["bridge"]
minm, maxm = mc.Margin_Pct.idxmin(), mc.Margin_Pct.idxmax()
smc = pm("store_margin_change")
gap = pm("store_group_gap")
gap_store = gap.groupby("Store_Name").Uplift_KZ.sum().sort_values(ascending=False)
gap_group = gap.groupby("MainGroup").Uplift_KZ.sum().sort_values(ascending=False)
bc_g, bc_s, bc_a = pm("below_cost_group"), pm("below_cost_store"), pm("below_cost_article")
dec = pm("decile").set_index("Decile")
smch = pm("subgroup_margin_change")
smch = smch[smch.Net_KZ_L12 > 8e8].sort_values("GP_Effect_KZ")
poultry_m = gm[gm.MainGroup == "POULTRY"].set_index("Month").Margin_Pct
disc = pm("discount_cost").set_index("MainGroup")
sub_lab = lambda r: title(r.SubGroup) + (f" ({title(r.MainGroup)})" if r.SubGroup in ("PORK", "FROZEN") else "")


# ------------------------------------------------------------------ page templates
def cover(c, d):
    c.saveState()
    c.setFillColor(colors.HexColor("#0f3d31"))
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#4fc1a0"))
    c.rect(M, H - 62 * mm, 28 * mm, 1.6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#9fd9c7"))
    c.setFont("Body-Bold", 10)
    c.drawString(M, H - 55 * mm, "FRESMART · ANGOLA · PROFITABILITY ANALYSIS")
    c.setFillColor(colors.white)
    c.setFont("Head", 32)
    c.drawString(M, H - 84 * mm, "Profit & Margin")
    c.drawString(M, H - 97 * mm, "Analysis Report")
    c.setFont("Head-Reg", 13.5)
    c.setFillColor(colors.HexColor("#cfe8df"))
    c.drawString(M, H - 111 * mm, "Gross profit, margin, cost pressure, leakage and opportunities")
    c.setFont("Body", 10.2)
    y = H - 138 * mm
    for k, v in [("Period", "January 2023 – September 2026 (45 months)"),
                 ("Scope", f"{N['n_locations']} locations with sales · {N['n_articles']:,} articles"),
                 ("Gross profit", f"{TOT_gp / 1e9:,.1f} bn Kz over the period · {L12_gp / 1e9:,.1f} bn Kz in the last 12 months"),
                 ("Gross margin", f"{TOT_gp / TOT_net * 100:.1f}% over the period · {L12_m:.1f}% in the last 12 months"),
                 ("Cost basis", "Actual COGS on every sales line (Azure SQL), corrected for posting errors"),
                 ("Companion", "Price elasticity & demand drivers: see the Phase 1 EDA report")]:
        c.setFillColor(colors.HexColor("#9fd9c7"))
        c.drawString(M, y, k.upper())
        c.setFillColor(colors.white)
        c.drawString(M + 36 * mm, y, v)
        y -= 7.5 * mm
    c.setFont("Body", 9)
    c.setFillColor(colors.HexColor("#9fd9c7"))
    c.drawString(M, 22 * mm, "Prepared 13 October 2026 · Newaco / Fresmart pricing analytics · based only on actual data")
    c.restoreState()


def page(c, d):
    c.saveState()
    c.setFont("Body", 7.4)
    c.setFillColor(MUTED)
    c.drawString(M, 10 * mm, "Fresmart · Profit & Margin Analysis Report · Oct 2026")
    c.drawRightString(W - M, 10 * mm, f"{d.page}")
    c.setStrokeColor(RULE)
    c.line(M, 13.5 * mm, W - M, 13.5 * mm)
    c.restoreState()


# ================================================================== 1 executive summary
h1("Executive summary")
P(f"This report looks only at profitability: how much gross profit Fresmart earns, where its margin comes from, what "
  f"is squeezing it and where it leaks, by month, category, article and store, from January 2023 to September 2026. "
  f"It uses the actual cost of goods (COGS) recorded on every sales line. Price elasticity and demand drivers are "
  f"covered in the separate Phase 1 EDA report and are used here only to size margin opportunities.")
kpis([(f"{L12_gp / 1e9:,.1f} bn", "gross profit, last 12 months (Kz)"),
      (pc(L12_m), f"gross margin, last 12 months (prior 12M {P12_m:.1f}%)"),
      (sp(gp_real_g, 0), "real gross-profit growth, L12M vs prior 12M"),
      (f"{P_['top20_gp_share']:.0f}%", "of gross profit from the top 20% of articles"),
      (mnk(-PM["below_cost_l12_kz"]), "lost on below-cost sales, L12M")])
key = [
    (pc(L12_m), f"<b>Margin is stable and slightly up.</b> {L12_m:.1f}% in the last 12 months vs {P12_m:.1f}% the year "
                f"before. Most of the gain is rate ({BR['rate']:+.2f} pp, mainly cattle) and a little is mix "
                f"({BR['mix']:+.2f} pp): poultry's lower share of sales lifted the average."),
    (f"{mc.Margin_Pct.min():.0f}%", f"<b>The 2023 devaluation is the big margin event.</b> Margin fell to "
                                    f"{mc.Margin_Pct.min():.1f}% in {minm} as costs rose ahead of prices, recovered to "
                                    f"{mc.Margin_Pct.max():.1f}% in {maxm}, and has held at 19–23% since 2024."),
    (pc(mgi.loc['CATTLE', 'Margin_Pct'], 0), f"<b>Cattle is the profit engine; poultry and dry commodities are the "
                                             f"volume engines.</b> Cattle earns {mgi.loc['CATTLE', 'GP_Share']:.0f}% "
                                             f"of gross profit on {mgi.loc['CATTLE', 'Sales_Share']:.0f}% of sales. "
                                             f"Poultry ({mgi.loc['POULTRY', 'Margin_Pct']:.0f}%) and dry commodities "
                                             f"({mgi.loc['DRY-COMMODITY', 'Margin_Pct']:.0f}%) carry 38% of sales at "
                                             f"thin margins."),
    (f"{ix.Cost_Index.iloc[-1]:.0f} vs {ix.Price_Index.iloc[-1]:.0f}", f"<b>Costs have outrun prices since 2023.</b> "
                                    f"Unit-cost index {ix.Cost_Index.iloc[-1]:.0f}, selling-price index "
                                    f"{ix.Price_Index.iloc[-1]:.0f} (Jan 2023 = 100). Only "
                                    f"{N['cost_pt_all']['Cumulative']:.0f}% of a cost increase reaches the shelf "
                                    f"within two quarters; dairy, dry grocery and charcuterie absorb the most."),
    (f"{P_['n_neg_gp']}", f"<b>Loss-making articles and below-cost selling leak profit.</b> {P_['n_neg_gp']} articles "
                          f"had negative gross profit in the last 12 months ({mnk(P_['neg_gp_kz'])}); below-cost "
                          f"transactions lost {mnk(-PM['below_cost_l12_kz'])}, and the losses are growing in 2026."),
    (mnk(PM["bench_uplift_kz"]), f"<b>Store execution gap.</b> If every store reached the median store's margin in each "
                                 f"category, gross profit would rise by about {mnk(PM['bench_uplift_kz'])} a year "
                                 f"(+{PM['bench_uplift_pp']:.2f} pp of margin), concentrated in Golf, Benfica and Fubu "
                                 f"large formats and poultry, dry commodities and dairy."),
    (f"{TP['Share_GP_Up_Pct']:.0f}%", f"<b>Temporary price cuts mostly cost profit.</b> Only "
                                      f"{TP['Share_GP_Up_Pct']:.0f}% of {TP['Events']:,.0f} temporary cuts raised gross "
                                      f"profit; together they cost {mnk(-TP['Total_GP_Change_KZ'])} versus normal weeks. "
                                      f"Recorded line discounts cost {mnk(PM['disc_l12_kz'])} (L12M), "
                                      f"{PM['disc_l12_of_gp']:.1f}% of gross profit."),
]
rows = [[Paragraph(a, ST["num"]), Paragraph(b, ST["box"])] for a, b in key]
t = Table(rows, colWidths=[30 * mm, CW - 30 * mm])
t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), .3, RULE),
                       ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                       ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
story.append(t)
h2("Priority actions to improve margin")
bullets([
    "<b>Re-price where cost has outrun price</b> (dairy, dry division, charcuterie): apply a cost-trigger rule so a "
    "unit-cost rise is reflected within one quarter.",
    f"<b>Close store margin gaps</b> to the median store, category by category (worth about {mnk(PM['bench_uplift_kz'])} "
    "a year): start with the large formats (Golf, Benfica, Fubu) and with poultry and dry commodities.",
    "<b>Fix or exit loss-makers</b>: the 20 worst articles account for most of the loss (carrier bags, butter, cheese, "
    "cream, processed chicken, chocolates).",
    "<b>Stop below-cost leakage</b>: weekly exception report on sales below cost, and validation of COGS postings "
    "(negative or >80% margin).",
    "<b>Promote less deeply</b>: keep temporary cuts at 10–15%, supplier-funded, on traffic lines only.",
    "<b>Lift thin-margin staples in small steps</b> where customers are least price-sensitive (Section 10 list), "
    "tested in a subset of stores first.",
])

# ================================================================== 2 data & definitions
h1("Data, definitions and cost quality")
P("Gross profit is measured from Fresmart's own sales lines, which carry net sales, COGS, discount and tax for every "
  "day × store × article. These were cleaned and linked to the article and location masters, stock and the "
  "consumer price index.")
box("<b>Definitions.</b> <b>Net sales</b> = sales after line discount, excluding tax. <b>Gross profit (GP)</b> = net "
    "sales − COGS. <b>Gross margin</b> = GP ÷ net sales. <b>Real</b> = deflated by CPI (Jan 2023 = 100). <b>L12M</b> = "
    "Oct 2025 – Sep 2026; <b>prior 12M</b> = Oct 2024 – Sep 2025. <b>Rate effect</b> = margin change within a "
    "category; <b>mix effect</b> = change caused by a shift in sales between categories.")
fig("r33_completeness", "Share of sales rows where each field is available, by year.",
    "Unit cost (COGS) is available on effectively 100% of sales rows in every year, so profit and margin can be "
    "measured for the full period, every category, article and store. Stock data start in June 2024.")
h2("Cost-data correction")
fx_tab = rd("cogs_fixed_articles").head(6)
P(f"{cfix['rows']:,} month × location × article rows had a negative COGS or a margin above 80% on a positive sale, "
  f"which cannot happen on a normal sale. Their COGS was rebuilt from that article's normal unit cost at that store "
  f"({cfix['rows_unit_cost']:,} rows) or at the chain-average 80% cost ratio. This lowers gross profit by "
  f"{mnk(cfix['gp_change_kz'])} versus the raw data, almost all from one posting of −257m Kz (frozen peas, Kikagil "
  f"store, April 2026). Without the correction, April 2026 margin and FNV margin would be overstated.")
table(["Article", "Sub-group", "Net sales", "Raw COGS", "Corrected COGS"],
      [[title(r.ArticleName)[:42], title(r.SubGroup), f"{r.Net_KZ / 1e6:,.2f}m Kz", f"{r.Raw_COGS_KZ / 1e6:,.2f}m Kz",
        f"{r.Fixed_COGS_KZ / 1e6:,.2f}m Kz"] for r in fx_tab.itertuples()], [.4, .15, .15, .15, .15], num_cols=(2, 3, 4),
      caption="Largest cost corrections.")

# ================================================================== 3 overview
h1("Gross profit and margin overview")
fig("r01_sales_gp_margin", "Monthly net sales and gross profit (bars, nominal kwanza) and gross margin % (line).",
    f"Monthly gross profit rose from {mc.GP_KZ.iloc[0] / 1e9:.2f} bn Kz in Jan 2023 to {mc.GP_KZ.iloc[-1] / 1e9:.2f} bn "
    f"Kz in Sep 2026, peaking every December. Margin fell to {mc.Margin_Pct.min():.1f}% in {minm} after the June 2023 "
    f"devaluation, recovered to {mc.Margin_Pct.max():.1f}% by {maxm}, dipped to 18–19% around the 2024 and 2025 "
    f"Christmas seasons, and was {mc.Margin_Pct.iloc[-1]:.1f}% in Sep 2026.")
fig("p01_gp_index", "Gross profit index in kwanza, USD and real (CPI-deflated) terms (log scale, Jan 2023 = 100).",
    f"Gross profit grew about {mc.GP_KZ.iloc[-1] / mc.GP_KZ.iloc[0]:.1f}× in kwanza, "
    f"{mc.GP_USD.iloc[-1] / mc.GP_USD.iloc[0]:.1f}× in USD and {mc.GP_Real.iloc[-1] / mc.GP_Real.iloc[0]:.1f}× in real "
    f"terms. In USD it fell by almost half between April and July 2023 as the kwanza devalued and margin collapsed, "
    f"and only regained its early-2023 level in November 2023.")
fig("p02_gp_ytd", "Gross profit and margin, January–September of each year.",
    f"Jan–Sep gross profit grew from {y23.GP_KZ / 1e9:.1f} bn Kz (2023) to {y26.GP_KZ / 1e9:.1f} bn Kz (2026). The "
    f"biggest step was 2024, when margin recovered from {y23.Margin_Pct:.1f}% to {y24.Margin_Pct:.1f}%. Since then "
    f"margin has been 20–21% and profit growth has come from sales growth.", width=.6)
table(["Jan–Sep", "Net sales", "Gross profit", "Margin", "GP growth (Kz)", "Real GP", "Real GP growth", "Locations"],
      [[y, bnk(r.Net_KZ), bnk(r.GP_KZ), pc(r.Margin_Pct),
        "–" if y == "2023" else sp((r.GP_KZ / ytd.GP_KZ.shift(1)[y] - 1) * 100, 0), bnk(r.GP_Real),
        "–" if np.isnan(r.GP_Real_Growth) else sp(r.GP_Real_Growth, 0), f"{r.Locations:.0f}"]
       for y, r in ytd.iterrows()], [.09, .13, .13, .09, .14, .13, .14, .15], num_cols=range(1, 8),
      caption="Year-to-date profit comparison (same nine months each year).")
fig("p03_gp_group_year", "Gross profit by main group and year (2026 = January–September).",
    "Poultry and cattle together make 35–47% of gross profit each year. Dry division, dairy and FNV have grown from "
    "0.5–0.7 bn Kz each in 2023 to 1.5–2.6 bn Kz in 2025, and 2026 is on track to exceed that.")

# ================================================================== 4 category
h1("Category profitability")
top = mg_main.iloc[0]
fig("r05_group_share_margin", "Share of net sales and gross profit by main group (bars) and gross margin (dots), L12M.",
    f"{title(top.MainGroup)} is {top.Sales_Share:.0f}% of sales but {top.GP_Share:.0f}% of profit at "
    f"{top.Margin_Pct:.0f}% margin. Cattle, FNV, charcuterie, personal care, dry division and bakery earn a larger "
    f"share of profit than of sales; dry commodities ({mgi.loc['DRY-COMMODITY', 'Margin_Pct']:.0f}%), beverages "
    f"({mgi.loc['BEVERAGES', 'Margin_Pct']:.0f}%) and baby food ({mgi.loc['BABY FOOD', 'Margin_Pct']:.0f}%) earn less.")
table(["Main group", "Net sales", "Gross profit", "Margin", "Margin prior 12M", "Change", "Sales share", "GP share"],
      [[title(r.MainGroup), bnk(r.Net_KZ), bnk(r.GP_KZ), pc(r.Margin_Pct),
        pc(gm[(gm.MainGroup == r.MainGroup) & gm.Month.between("2024-10", "2025-09")].pipe(
            lambda d: (1 - d.COGS_KZ.sum() / d.Net_KZ.sum()) * 100)),
        f"{r.Margin_Pct - gm[(gm.MainGroup == r.MainGroup) & gm.Month.between('2024-10', '2025-09')].pipe(lambda d: (1 - d.COGS_KZ.sum() / d.Net_KZ.sum()) * 100):+.1f} pp",
        pc(r.Sales_Share), pc(r.GP_Share)] for r in mg_main.itertuples()],
      [.18, .12, .12, .09, .13, .1, .12, .12], num_cols=range(1, 8), caption="Main-group profitability, L12M vs prior 12M.")
fig("r06_margin_group_quarter", "Gross margin by main group and quarter.",
    "Poultry (6–9%) and dry commodities (3–11%) were hit hardest by the 2023 devaluation. Cattle has risen to "
    "33–36% in 2026; bakery jumped to 36% in Q3 2026; baby food has slipped to 13–15%; poultry has eased from 19% to "
    "18% in 2026.")
fig("p04_group_margin_lines", "Monthly gross margin by main group (blue) against the chain (grey).",
    f"Cattle, charcuterie and FNV run consistently above the chain; dry commodities and beverages below. Poultry "
    f"margin fell from {poultry_m.loc['2026-04']:.1f}% in April to {poultry_m.iloc[-1]:.1f}% in September 2026, the "
    f"main recent drag given poultry's weight.")
fig("p05_margin_bridge", "Margin bridge from the prior 12 months to the last 12 months: rate effects (margin change "
    "within each group) and mix effects (shift of sales between groups).",
    f"Chain margin rose from {BR['m0']:.2f}% to {BR['m1']:.2f}%. Rate effects (margin changes inside each group) added "
    f"{BR['rate']:+.2f} pp, led by cattle (+0.38 pp), partly offset by lower margins in dry division, beverages and "
    f"seafood. Mix added {BR['mix']:+.2f} pp: poultry, a below-average-margin group, fell from 27% to 24% of sales "
    f"while above-average groups (dry division, FNV, personal care) gained share.")
fig("p06_subgroup_margin_change", "Sub-categories with the largest gross-profit effect from their margin change, L12M vs "
    "prior 12M (sub-categories above 0.8 bn Kz of sales).",
    f"Cattle pork margin rose 6 points, worth about 450m Kz; eggs, FNV frozen and bread also improved. Chocolates "
    f"(−6.1 pp) and oil (−1.6 pp) lost about 130m Kz each; seafood frozen, cereals, snacks and hot drinks also slipped.")
table(["Sub-group", "Net sales", "Margin", "Prior 12M", "Change", "Real growth", "Sales share"],
      [[sub_lab(r), bnk(r.Net_KZ), pc(r.Margin_Pct),
        pc(smch.set_index(["MainGroup", "SubGroup"]).Margin_Pct_P12.get((r.MainGroup, r.SubGroup), np.nan)),
        f"{r.Margin_Pct - smch.set_index(['MainGroup', 'SubGroup']).Margin_Pct_P12.get((r.MainGroup, r.SubGroup), np.nan):+.1f} pp",
        sp(r.Growth_Real_Pct, 0), pc(r.Sales_Share)] for r in sg.head(20).itertuples()],
      [.25, .13, .1, .11, .12, .13, .12], num_cols=range(1, 7), caption="Top 20 sub-categories by net sales, L12M.")
fig("r12_subgroup_quadrant", "Sub-categories by gross margin (x) and real sales growth (y), L12M; bubble = sales.",
    "Pork, beef, sauces, body care, fresh produce and frozen combine above-average margin and growth. Chicken, eggs, "
    "rice, pasta and sugar are large, thin-margin and slow-growing: small margin gains there are worth the most.")

# ================================================================== 5 article
h1("Article profitability")
fig_pair("r09_pareto", "r08_margin_distribution", "Left: cumulative share of sales and gross profit by ranked article. "
         "Right: distribution of article margin, weighted by sales (L12M).",
         f"{P_['n_for_80_sales']} of {P_['articles_l12m']:,} articles make 80% of sales and the top 20% make "
         f"{P_['top20_gp_share']:.0f}% of gross profit. Most sales sit at 10–30% margin.")
fig("p08_article_scatter", "Every article: L12M net sales (log) vs gross margin; bubble = gross profit; dashed line = "
    "sales-weighted average.",
    "The biggest sellers (chicken, oil, rice, sugar) sit at 8–18% margin, below average; the biggest profit bubbles "
    "are beef and pork cuts at 30–45%. Negative-margin articles are almost all small sellers.")
fig("p09_decile", "Gross margin and number of loss-making articles by sales decile (L12M).",
    f"The smallest 10% of articles lose money overall ({dec.loc['D1', 'Margin_Pct']:.0f}% margin, "
    f"{dec.loc['D1', 'Loss_Makers']:.0f} loss-makers) and the next decile earns only "
    f"{dec.loc['D2', 'Margin_Pct']:.0f}%. Mid-sized articles earn 22–23%; the top decile "
    f"{dec.loc['D10', 'Margin_Pct']:.0f}%, pulled down by thin-margin staples. The tail is a range-review "
    f"candidate.", width=.62)
fig("r10_top_gp", "Top 15 articles by gross profit, L12M (label: gross profit · margin).",
    "Chicken leg quarters and eggs at 10–16% margin and pork and beef cuts at around 30% generate the most profit. "
    "A 1-point margin change on the top chicken lines is worth 20–30m Kz a year each.")
fig("r11_bottom_gp", "Bottom 15 articles by gross profit, L12M.",
    "The Fresmart carrier bag is the single largest loss. Butter, cheese, cream, processed chicken and chocolates "
    "follow: these are priced below their cost, or their cost postings are wrong.")
fig("p10_loss_subgroups", "Sub-categories with the largest combined loss from loss-making articles, L12M.",
    "Chocolates (72 loss-making articles), packing material, chicken, cheese, cream and butter account for most of the "
    "loss. In chocolates the problem is breadth (many small loss-makers); in butter and packing material it is a few "
    "large lines.", width=.62)
ng = rd("neg_gp_articles").head(15)
table(["Article", "Sub-group", "Net sales", "Gross profit", "Margin"],
      [[title(r.ArticleName)[:44], title(r.SubGroup), mnk(r.Net_KZ), mnk(r.GP_KZ), pc(r.Margin_Pct)]
       for r in ng.itertuples()], [.44, .17, .13, .13, .13], num_cols=(2, 3, 4),
      caption=f"Largest loss-making articles, L12M ({P_['n_neg_gp']} articles with negative gross profit, total "
              f"{mnk(P_['neg_gp_kz'])}).")

# ================================================================== 6 store
h1("Store profitability")
fig("p13_store_gp", "Gross profit (bars) and gross margin (dots) by store, L12M (stores open all 12 months).",
    f"The three large formats in Kilamba and Fubu each earn about 1.7–1.8 bn Kz of gross profit; the median store "
    f"earns {st_full.GP_KZ.median() / 1e9:.2f} bn Kz. Margins range only from {st_full.Margin_Pct.min():.1f}% to "
    f"{st_full.Margin_Pct.max():.1f}%.")
fig("r13_store_scatter", "Net sales per m² per month vs gross margin by store, L12M; bubble = sales; colour = zone.",
    "Province stores (grey) combine above-average margin with good space productivity. Cazenga, Cuca and Golf "
    "stores have the lowest margins; Benfica Fresmart and Moxico have the lowest sales per m².")
fig("r14_store_gp_sqm", "Gross profit per m² per month by store, L12M.",
    "Gross profit per m² varies about 3.5× between the top and bottom quartile of stores, far more than margin does: "
    "store profitability is driven by space productivity first and margin second.")
fig("p11_store_margin_heat", "Gross margin by store and month, January 2024 onward, for stores trading in every month "
    "(sorted by L12M margin).",
    "All stores moved together through the March–July 2024 recovery and the December dips, confirming that margin is "
    "set centrally. Province stores (Saurimo, Moxico, Namibe, Lubango) stay in the top band; Cazenga, Cuca, Golf "
    "Fresmart and Benfica Fresmart stay in the bottom band every month.")
fig("p12_store_margin_change", "Margin change by store, L12M vs prior 12M (stores open in both periods).",
    f"{(smc.Margin_Change_pp > 0).sum()} of {len(smc)} stores improved margin; Saurimo (+{smc.set_index('Store_Name').loc['SAURIMO FRESMART EXPRESS', 'Margin_Change_pp']:.1f} pp) "
    f"and Moxico led. The few declines are small (at most {smc.Margin_Change_pp.min():.1f} pp).")
fig("r07_margin_group_zone", "Gross margin by main group and zone, stores only, L12M.",
    "Province stores earn the highest margin in nearly every category (they price 2–4% above the chain). Cazenga and "
    "Golf earn the lowest, especially in cattle, charcuterie and poultry.")
fig("r07_margin_group_class", "Gross margin by main group and store class (P = province), L12M.",
    "Store class matters little outside the province: class C stores run about 1 point below class A.", width=.62)
fig("r15_premium_margin", "Store price premium vs chain and store gross margin (L12M).",
    f"A higher price level goes with higher margin (r = {N['store_premium_margin_r']:.2f}). Province stores price "
    "above the chain and earn more per sale; the companion EDA report shows they are also the most price-sensitive, "
    "so the premium should be reviewed store by store.", width=.58)
cols = ["Store", "Zone", "Class", "Net sales", "Gross profit", "Margin", "Margin prior 12M", "GP per m² per month",
        "Price premium"]
pm12 = smc.set_index("Store_Name").Margin_Pct_P12
fmt = lambda r: [store(r.Store_Name), title(r.Area_Zone), r.Store_Class, bnk(r.Net_KZ), bnk(r.GP_KZ),
                 pc(r.Margin_Pct), "–" if r.Store_Name not in pm12 else pc(pm12[r.Store_Name]),
                 f"{r.GP_per_Sqm_Month_KZ / 1e3:,.0f}k", sp(r.Price_Premium_Pct)]
w = [.21, .1, .06, .1, .1, .08, .11, .12, .12]
table(cols, [fmt(r) for r in st_full.sort_values("GP_KZ", ascending=False).itertuples()], w, num_cols=range(3, 9),
      caption="All stores open for the full last 12 months, ranked by gross profit.")

# ================================================================== 7 cost pressure
h1("Cost and margin pressure")
fig("r16_price_cost_index", "Chain selling-price and unit-cost indices (same article, same store), against CPI and the "
    "exchange rate.",
    f"Unit cost ({ix.Cost_Index.iloc[-1]:.0f}) has risen more than selling price ({ix.Price_Index.iloc[-1]:.0f}) since "
    f"January 2023. The gap opened in the 2023 devaluation, when unit cost rose about 45% in two months (May–July 2023), and has never "
    f"fully closed.")
fig("r17_price_cost_groups", "Selling price vs unit cost index by main group (Feb 2023 = 100).",
    "Dry division (cost +65% vs price +41%), dairy (+105% vs +55%) and charcuterie (+83% vs +66%) have absorbed the "
    "most cost; beverages slightly. Poultry, cattle and FNV prices have kept pace with or exceeded cost.")
fig("r18_cost_passthrough", "Share of a unit-cost change passed into the selling price, same and following quarter.",
    f"Overall {N['cost_pt_all']['Same_Quarter']:.0f}% of a cost change reaches the price in the same quarter and "
    f"{N['cost_pt_all']['Cumulative']:.0f}% within two. Cattle, charcuterie and pet pass through only about half: "
    f"every cost increase there comes straight out of margin until prices are reviewed.")
fig("r19_fx_margin", "Monthly chain margin vs the change in the kwanza over the previous three months.",
    f"Margin falls when the kwanza devalues quickly (r = {N['fx3_margin_r']:.2f}), as in June–August 2023. Imported "
    f"categories need an exchange-rate-linked repricing rule to protect margin in the next devaluation.", width=.58)
fig("p07_import_local", "Gross margin of imported vs locally sourced articles, by quarter.",
    f"Imported articles were hit harder in 2023 but now earn more ({imp.loc['Import', 'Margin_Pct']:.1f}% vs "
    f"{imp.loc['Local', 'Margin_Pct']:.1f}% in L12M), helped by imported beef and pork. Local staples (eggs, sugar, "
    f"rice, oil) are the thin-margin core.", width=.62)
table(["Sourcing", "Net sales", "Gross profit", "Margin", "Articles"],
      [[k, bnk(r.Net_KZ), bnk(r.GP_KZ), pc(r.Margin_Pct), f"{r.Articles:,.0f}"] for k, r in imp.iterrows()],
      [.2, .2, .2, .2, .2], num_cols=(1, 2, 3, 4), caption="Imported vs locally sourced articles, L12M.")

# ================================================================== 8 discounts & promotions
h1("Discounts, promotions and margin")
fig("p19_discount_cost", "Recorded line discounts by main group, L12M (label: amount · % of the group's gross profit).",
    f"Recorded discounts cost {mnk(PM['disc_l12_kz'])} in the last 12 months, {PM['disc_l12_of_gp']:.1f}% of gross "
    f"profit. Seafood is the exception: discounts take {disc.loc['SEA FOOD', 'Disc_of_GP_Pct']:.0f}% of its gross "
    f"profit, which points to markdowns of short-dated stock.", width=.62)
fig("r29_tpr_depth", "Temporary price reductions: unit lift and share of events where gross profit rose, by depth.",
    f"Temporary cuts (a price 10–60% below the previous six weeks that returns within two weeks) lift units a median "
    f"{TP['Median_Adj_Lift_Pct']:.0f}%, but gross profit rose in only {TP['Share_GP_Up_Pct']:.0f}% of "
    f"{TP['Events']:,.0f} events, and only {tpr_d.loc['30-60%', 'Share_GP_Up_Pct']:.0f}% of cuts deeper than 30%.")
fig("p20_tpr_gp_group", "Gross-profit change during temporary-cut weeks vs the previous six weeks, by main group, "
    "Jan 2023 – Sep 2026.",
    f"Across all categories temporary cuts cost {mnk(-TP['Total_GP_Change_KZ'])} of gross profit relative to normal "
    f"weeks. Dairy, poultry and beverages lost the most; only dry commodities came out roughly even.", width=.62)
table(["Cut depth", "Events", "Median cut", "Unit lift", "GP rose in", "Total GP change"],
      [[k, f"{r.Events:,.0f}", pc(r.Median_Depth_Pct, 0), sp(r.Median_Adj_Lift_Pct, 0), pc(r.Share_GP_Up_Pct, 0),
        mnk(r.Total_GP_Change_KZ)] for k, r in tpr_d.iterrows()], [.15, .15, .15, .15, .15, .25], num_cols=range(1, 6),
      caption="Temporary price reductions by depth.")
P("Promotions are measured from shelf-price changes because the source has no promotion flag; displays, leaflets and "
  "supplier-funded promotions cannot be separated, so the real net cost of supplier-funded events may be lower.")

# ================================================================== 9 leakage
h1("Margin leakage")
fig("p16_below_cost_month", "Loss on sales made far below cost (COGS above 1.5× sales value), by month.",
    f"Below-cost losses were 10–30m Kz a month in 2024 but 80–110m Kz a month in March–June 2026: "
    f"{mnk(-PM['below_cost_l12_kz'])} in the last 12 months alone.")
fig_pair("p17_below_cost_group", "p18_below_cost_store", "Loss on below-cost sales, L12M: by main group (left) and by "
         "store (right, 12 largest).",
         f"Dairy ({mnk(-bc_g.iloc[0].Loss_KZ)}) and dry division ({mnk(-bc_g.iloc[1].Loss_KZ)}) account for half of "
         f"the loss. By store it concentrates in the large formats (Fubu, Centralidade Kilamba, Kilamba, Benfica), "
         f"where clearance and shrink handling are heaviest.")
table(["Article", "Sub-group", "Below-cost sales", "Loss"],
      [[title(r.ArticleName)[:46], title(r.SubGroup), mnk(r.Sales_KZ), mnk(r.Loss_KZ)] for r in bc_a.head(12).itertuples()],
      [.5, .18, .16, .16], num_cols=(2, 3),
      caption="Articles with the largest losses on below-cost sales, L12M. Where the loss exceeds the sales value, "
              "the sale was below a third of cost: either deep clearance or a cost/unit error to investigate.")
fig("r31_anomalies", "Below-cost losses (bars) and the rate of price and cost outliers per 1,000 sales rows (lines).",
    "Price and cost outlier rates are stable at 1–2 per 1,000 rows, so the growth in below-cost losses is a real "
    "trading issue, not a data-quality artefact.")

# ================================================================== 10 opportunities
h1("Margin improvement opportunities")
P("Three sources of margin improvement are quantified below. The first is measured directly from actual store margins; "
  "the second and third use the price elasticities from the Phase 1 EDA report and are model-implied.")
h2("1. Close store margin gaps (measured)")
fig("p14_store_group_gap", "Margin vs the median store, by main group, for the 25 stores with the largest gap (L12M); in "
    "brackets, gross profit gained if the store reached the median in every group where it is below.",
    f"Reaching the median store margin in every store and category would add about {mnk(PM['bench_uplift_kz'])} of "
    f"gross profit a year (+{PM['bench_uplift_pp']:.2f} pp). Golf Fresmart alone accounts for "
    f"{mnk(gap_store.iloc[0])}, Benfica Fresmart {mnk(gap_store.iloc[1])} and Fubu {mnk(gap_store.iloc[2])}. Province "
    f"stores sit above the median in almost every category.")
fig("p15_gap_uplift_group", "Gross profit available from closing store gaps, by main group.",
    f"Poultry ({mnk(gap_group['POULTRY'])}), dry commodities ({mnk(gap_group['DRY-COMMODITY'])}) and dairy "
    f"({mnk(gap_group['DAIRY PRODUCTS'])}) hold the most: the same articles earn less in some stores, through "
    f"local price overrides, markdowns or shrink.", width=.6)
h2("2. Pricing headroom on low-sensitivity, thin-margin lines (model-implied)")
fig("r26_margin_vs_elasticity", "Sub-categories: price elasticity (from the EDA report) vs actual gross margin, L12M. "
    "The curve is the margin at which price maximises gross profit (−1/elasticity).",
    "Every major sub-category sits below the curve, so on short-run elasticities careful price rises would add "
    "profit. Competitor reactions and price image make long-run demand more sensitive, so this shows direction, not "
    "a target margin.")
fig("r25_simulation", "Simulated units and gross profit for a price change, ten largest sub-categories (e = elasticity, "
    "m = actual margin).",
    "At thin margins a small price rise adds gross profit even after the volume loss (chicken: +5% price, about −8% "
    "units, about +17% gross profit), while cuts destroy profit fast. <i>Model-implied; assumes competitors and costs "
    "do not change.</i>")
o = rd("opp_price_rise")
table(["Article", "Sub-group", "Net sales", "Margin", "Elasticity", "GP change at +5%", "GP change, Kz"],
      [[title(r.ArticleName)[:40], title(r.SubGroup), mnk(r.Net_KZ), pc(r.Margin_Pct), f"{r.Elasticity:.2f}",
        sp(r.GP_Chg_Up5_Pct), mnk(r.GP_Chg_Up5_KZ)] for r in o.head(20).itertuples()],
      [.33, .12, .11, .09, .1, .12, .13], num_cols=range(2, 7),
      caption=f"Price-rise test candidates (elasticity above −0.8, margin below 30%, sold in 10+ stores). Model-implied "
              f"gain for the top 25 at +5%: {mnk(N['opp']['rise_gp_kz'])} a year.")
h2("3. Fix leakage (measured)")
P(f"Eliminating losses on below-cost sales ({mnk(-PM['below_cost_l12_kz'])} in L12M), re-pricing or delisting the "
  f"worst loss-making articles ({mnk(P_['neg_gp_kz'])}) and restricting temporary cuts to 10–15% would each recover "
  f"part of these amounts; the actual recovery depends on how much is clearance of stock that would otherwise be "
  f"written off.")
summary = [
    ["Close store margin gaps to the median store", mnk(PM["bench_uplift_kz"]), "Measured (actual store margins)"],
    ["Price rises on 25 low-sensitivity, thin-margin articles (+5%)", mnk(N["opp"]["rise_gp_kz"]),
     "Model-implied; test first"],
    ["Below-cost sales", mnk(-PM["below_cost_l12_kz"]), "Measured loss; recoverable share unknown"],
    ["Loss-making articles", mnk(-P_["neg_gp_kz"]), "Measured loss; re-price, renegotiate or delist"],
    ["Recorded discounts", mnk(PM["disc_l12_kz"]), "Measured cost; partly unavoidable"],
]
table(["Opportunity", "Size, last 12 months", "Basis"], summary, [.5, .2, .3], num_cols=(1,),
      caption="Margin opportunity summary. Amounts overlap partly and should not be added together.")

# ================================================================== 11 findings & recommendations
h1("Key findings and recommendations")
h2("Key findings")
bullets([
    f"<b>Profit:</b> {bnk(L12_gp)} gross profit in the last 12 months at {pc(L12_m)} margin; real gross profit "
    f"{sp(gp_real_g, 0)} vs the prior 12 months.",
    f"<b>Margin history:</b> {mc.Margin_Pct.min():.0f}% low in {minm} (devaluation), {mc.Margin_Pct.max():.0f}% peak in "
    f"{maxm}, stable at 19–23% since; the last-12-month gain ({BR['m0']:.2f}% → {BR['m1']:.2f}%) is mostly cattle "
    f"margin.",
    "<b>Categories:</b> cattle (32%), FNV, bakery, charcuterie and personal care carry high margins; dry commodities "
    "(13%), baby food (14%), beverages (17%) and poultry (18%) thin ones. Chocolates and oil lost margin in the last "
    "year; pork, eggs and frozen gained.",
    f"<b>Cost pressure:</b> cost index {ix.Cost_Index.iloc[-1]:.0f} vs price index {ix.Price_Index.iloc[-1]:.0f}; "
    f"{N['cost_pt_all']['Cumulative']:.0f}% pass-through, about half in cattle, charcuterie and pet.",
    "<b>Stores:</b> margins vary little (17–24%) and move together; productivity per m² varies 3.5×; province stores "
    "lead on margin, Cazenga, Cuca, Golf and Benfica Fresmart trail.",
    f"<b>Leakage:</b> {mnk(-PM['below_cost_l12_kz'])} below-cost losses (rising), {P_['n_neg_gp']} loss-making articles, "
    f"temporary cuts that cost {mnk(-TP['Total_GP_Change_KZ'])} over the period, and cost-posting errors large enough "
    "to distort monthly margins.",
])
h2("Recommendations")
table(["#", "Action", "Evidence", "Expected effect"], [
    ["1", "Cost-trigger repricing: review any article whose unit cost rises >3% within the same quarter, starting with "
          "dairy, dry division and charcuterie", "Section 7", "Recover margin absorbed since 2023"],
    ["2", "Store margin gap programme: target each below-median store × category, investigating local price overrides, "
          "markdowns and shrink", "Section 10.1", f"Up to {mnk(PM['bench_uplift_kz'])} a year"],
    ["3", "Loss-maker review: re-price, renegotiate or delist the 20 worst loss-making articles; charge or re-cost "
          "carrier bags", "Section 5", f"Recover part of {mnk(-P_['neg_gp_kz'])}"],
    ["4", "Weekly below-cost exception report and COGS posting validation", "Section 9",
     f"Recover part of {mnk(-PM['below_cost_l12_kz'])}"],
    ["5", "Promotion rules: max 15% temporary cut, traffic lines only, supplier-funded", "Section 8",
     "Fewer profit-losing promotions"],
    ["6", "Test +3–5% on low-sensitivity, thin-margin staples in matched stores", "Section 10.2",
     "Model-implied gains; confirm with test"],
    ["7", "Exchange-rate-linked repricing rule for imported categories", "Section 7", "Protect margin in devaluations"],
    ["8", "Range review of the smallest 10–20% of articles (negative to 12% margin)", "Section 5",
     "Simplify range, lift average margin"],
], [.04, .5, .16, .3])

# ================================================================== 12 limitations
h1("Limitations")
bullets([
    "<b>COGS is the average stock cost</b> recorded on the sales line, not the latest purchase price. In fast "
    "inflation it lags replacement cost, so margins look better for a few months after cost increases.",
    "<b>Gross margin only.</b> Rebates, supplier income, shrink, wastage, logistics and store costs are not in the data, "
    "so net profitability by category and store may rank differently.",
    "<b>No promotion flag or supplier funding data.</b> Promotional cost is measured from shelf-price changes and may "
    "overstate the net cost of supplier-funded events.",
    "<b>Below-cost sales</b> include genuine clearance as well as possible cost or unit-of-measure errors; each large "
    "case needs checking before action.",
    "<b>Model-implied figures</b> (Section 10.2) use short-run elasticities from the EDA report and assume no competitor "
    "response; they must be validated with controlled store tests.",
    f"<b>Data corrections</b>: {cfix['rows']:,} rows with impossible COGS were rebuilt (Section 2); September 2026 CPI "
    "is estimated for the real-terms figures.",
])
h2("Glossary")
table(["Term", "Meaning"], [
    ["Gross profit (GP)", "Net sales − COGS"],
    ["Gross margin", "GP ÷ net sales"],
    ["Rate / mix effect", "Margin change within categories / from a change in the category mix"],
    ["Pass-through", "% of a unit-cost change that appears in the selling price"],
    ["Below-cost sale", "A day's sales of an article at a store where COGS exceeded 1.5× the sales value"],
    ["Temporary price reduction", "Price 10–60% below the previous six-week median, back to normal two weeks later"],
    ["Median-store gap", "Store margin minus the median store's margin for the same main group"],
    ["L12M / prior 12M", "Oct 2025 – Sep 2026 / Oct 2024 – Sep 2025"],
], [.25, .75])


# ------------------------------------------------------------------ build
def build():
    doc = BaseDocTemplate(str(OUTF), pagesize=A4, leftMargin=M, rightMargin=M, topMargin=15 * mm,
                          bottomMargin=18 * mm, title="Fresmart Profit & Margin Analysis Report",
                          author="Newaco pricing analytics", subject="Gross profit and margin analysis, Jan 2023 - Sep 2026")
    frame = Frame(M, 18 * mm, CW, H - 33 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate("cover", [Frame(0, 0, W, H)], onPage=cover),
                          PageTemplate("body", [frame], onPage=page)])
    head = [NextPageTemplate("body"), PageBreak(), Paragraph("Contents", ST["h1"])]
    data = [[Paragraph(a, ST["cell"]), Paragraph(b, ST["cell"])] for a, b in TOC]
    tt = Table(data, colWidths=[CW * .07, CW * .93])
    tt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), .3, RULE), ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    head += [tt, Spacer(1, 10),
             Paragraph(f"{FIGNO[0]} figures with interpretation, plus supporting tables. Every number is computed from "
                       "Fresmart's actual sales and COGS; model-implied estimates are marked. Price elasticity and "
                       "demand drivers are covered in the companion Phase 1 EDA report.", ST["body"])]
    doc.build(head + story)
    print(OUTF)


build()
