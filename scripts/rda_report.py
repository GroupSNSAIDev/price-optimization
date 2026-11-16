"""Assemble the Retail Data Analysis (RDA) PDF -> output/RDA_Report/Fresmart_Retail_Data_Analysis_Report.pdf

Inputs: analysis/rda/*.parquet + numbers.json (rda_analysis.py), report/rda_charts (rda_charts.py),
        report/pdf_charts + report/data.json + report/pdf_numbers.json (elasticity and deep-analysis charts).
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
from reportlab.platypus import (BaseDocTemplate, Frame, Image as RLImage, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
R, CH_NEW, CH_OLD = ROOT / "analysis" / "rda", ROOT / "report" / "rda_charts", ROOT / "report" / "pdf_charts"
OUTD = ROOT / "output" / "RDA_Report"
OUTD.mkdir(parents=True, exist_ok=True)
OUTF = OUTD / "Fresmart_Retail_Data_Analysis_Report.pdf"
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
    story.append(Paragraph(t, ST["h2"]))


def bullets(items, style="bullet"):
    for t in items:
        story.append(Paragraph(t, ST[style], bulletText="•"))


def _img(name, width):
    path = (CH_NEW if name.startswith("r") else CH_OLD) / f"{name}.png"
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
mc = rd("monthly_chain").set_index("Month")
ytd = rd("yearly_ytd").set_index("Year")
mg = rd("maingroup_l12m")
mg_main = mg[mg.Sales_Share >= 0.3]
sg = rd("subgroup_l12m")
art = rd("article_l12m")
st = rd("store_l12m")
st_full = st[st.Channel.eq("STORE") & st.Months.eq(12)]
ix = rd("price_cost_index").set_index("Month")
pt = rd("cost_passthrough").set_index("MainGroup")
tpr_d, tpr_g = rd("tpr_by_depth"), rd("tpr_by_group").set_index("MainGroup")
dd = rd("discount_depth_volume").set_index("Bucket")
cw = rd("corr_within").set_index("index")
cm = rd("corr_macro_monthly").set_index("index")
csg = rd("corr_subgroup").set_index("index")
an = rd("anomaly_monthly")
imp = rd("import_local_l12m").set_index("PurchaseType")
bins = rd("demand_binscatter").groupby("SubGroup").Slope.first()
L12 = mc.loc["2025-10":"2026-09"]
L12_net, L12_gp = L12.Net_KZ.sum(), L12.GP_KZ.sum()
L12_margin = L12_gp / L12_net * 100
TOT_net, TOT_gp = mc.Net_KZ.sum(), mc.GP_KZ.sum()
y26, y25, y24, y23 = (ytd.loc[y] for y in ["2026", "2025", "2024", "2023"])
pooled = {r["Term"]: r for r in J["pooled"]}
e_head, e_raw = pooled["ln_Relative_Price"]["Estimate"], pooled["ln_Price_Nominal"]["Estimate"]
e_up, e_dn = pooled["ln_Rel_Above"]["Estimate"], pooled["ln_Rel_Below"]["Estimate"]
TP = N["tpr"]
P_ = N["pareto"]
minm, maxm = mc.Margin_Pct.idxmin(), mc.Margin_Pct.idxmax()
cfix = N["cogs_fix"]

# ------------------------------------------------------------------ page templates
def cover(c, d):
    c.saveState()
    c.setFillColor(colors.HexColor("#0f3d31"))
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#4fc1a0"))
    c.rect(M, H - 62 * mm, 28 * mm, 1.6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#9fd9c7"))
    c.setFont("Body-Bold", 10)
    c.drawString(M, H - 55 * mm, "FRESMART · ANGOLA · RETAIL DATA ANALYSIS")
    c.setFillColor(colors.white)
    c.setFont("Head", 32)
    c.drawString(M, H - 84 * mm, "Retail Data Analysis")
    c.drawString(M, H - 97 * mm, "Report")
    c.setFont("Head-Reg", 13.5)
    c.setFillColor(colors.HexColor("#cfe8df"))
    c.drawString(M, H - 111 * mm, "Sales, pricing, profit, promotions and price elasticity")
    c.setFont("Body", 10.2)
    y = H - 138 * mm
    for k, v in [("Period", "January 2023 – September 2026 (45 months)"),
                 ("Scope", f"{N['n_locations']} locations with sales · {N['n_articles']:,} articles"),
                 ("Net sales", f"{TOT_net / 1e9:,.0f} bn Kz over the period · {L12_net / 1e9:,.1f} bn Kz in the last 12 months"),
                 ("Gross profit", f"{TOT_gp / 1e9:,.1f} bn Kz · margin {TOT_gp / TOT_net * 100:.1f}% (actual COGS)"),
                 ("Sources", "Azure SQL sales, COGS, prices, stock; BNA, INE, IMF, EIA macro series")]:
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
    c.drawString(M, 10 * mm, "Fresmart · Retail Data Analysis Report · Oct 2026")
    c.drawRightString(W - M, 10 * mm, f"{d.page}")
    c.setStrokeColor(RULE)
    c.line(M, 13.5 * mm, W - M, 13.5 * mm)
    c.restoreState()


# ================================================================== 1 executive summary
h1("Executive summary")
P(f"This report analyses every sale Fresmart made from January 2023 to September 2026 across {N['n_locations']} "
  f"locations and {N['n_articles']:,} articles, with the actual cost of goods (COGS) on every sales line, selling and "
  f"list prices, stock, and Angola's exchange rate, inflation, oil price and GDP. All figures come from the data; where "
  f"a number is a model estimate rather than a measured value, it is labelled as such.")
kpis([(f"{L12_net / 1e9:,.1f} bn", "net sales, last 12 months (Kz)"),
      (f"{L12_gp / 1e9:,.1f} bn", "gross profit, last 12 months (Kz)"),
      (pc(L12_margin), "gross margin, last 12 months"),
      (sp(y26.Net_Real_Growth, 0), "real sales growth, Jan–Sep 2026 vs 2025"),
      (f"{e_head:.2f}", "chain price elasticity (relative price)")])
key = [
    (sp(y26.Net_KZ_Growth, 0), f"<b>Sales keep growing well ahead of inflation.</b> Jan–Sep net sales rose "
                               f"{y26.Net_KZ_Growth:.0f}% in kwanza and {y26.Net_Real_Growth:.0f}% after inflation in 2026, "
                               f"and real gross profit rose {y26.GP_Real_Growth:.0f}%. New stores carry much of it: the "
                               f"{N['lfl_stores']} stores open throughout grew far less (Section 4)."),
    (pc(L12_margin), f"<b>Margin recovered from the 2023 devaluation and is stable near 21%.</b> It fell to "
                     f"{mc.Margin_Pct.min():.1f}% in {minm} when the kwanza lost ~40% and costs moved faster than "
                     f"prices; it has held at 19–23% since 2024. Over three months, a weaker kwanza goes with lower margin "
                     f"(r = {N['fx3_margin_r']:.2f})."),
    (f"{P_['top20_sales_share']:.0f}%", f"<b>Sales and profit are concentrated.</b> The top 20% of articles earn "
                                        f"{P_['top20_sales_share']:.0f}% of sales and {P_['top20_gp_share']:.0f}% of "
                                        f"gross profit; {P_['n_for_80_sales']} articles make 80% of sales. Chicken alone "
                                        f"is {sg.iloc[0].Sales_Share:.0f}% of sales at {sg.iloc[0].Margin_Pct:.0f}% margin."),
    (f"{N['cost_pt_all']['Cumulative']:.0f}%", f"<b>Only three-quarters of cost increases reach the shelf.</b> Over two "
                                               f"quarters, {N['cost_pt_all']['Cumulative']:.0f}% of a unit-cost change "
                                               f"passes into the selling price. The cost index ended at "
                                               f"{ix.Cost_Index.iloc[-1]:.0f} vs price {ix.Price_Index.iloc[-1]:.0f} "
                                               f"(Jan 2023 = 100): dairy, dry grocery and charcuterie have absorbed cost."),
    (f"{e_head:.2f}", f"<b>Customers are price-sensitive, more to rises than cuts.</b> A 10% price rise relative to the "
                      f"category costs about {abs(e_head) * 10:.0f}% of units; rises lose {abs(e_up):.2f}, cuts gain "
                      f"{abs(e_dn):.2f}. Measured on raw kwanza prices it looks like {e_raw:.2f}, so inflation hides half "
                      f"the true sensitivity."),
    (f"{TP['Share_GP_Up_Pct']:.0f}%", f"<b>Temporary price cuts sell more but usually earn less.</b> "
                                      f"{TP['Events']:,.0f} short price reductions (median {TP['Median_Depth_Pct']:.0f}% "
                                      f"off) lifted units a median {TP['Median_Adj_Lift_Pct']:.0f}%, yet gross profit "
                                      f"rose in only {TP['Share_GP_Up_Pct']:.0f}% of them; deeper cuts do worse."),
    (f"{N['disc_total_pct']:.2f}%", "<b>Recorded discounts are negligible.</b> Line discounts are "
                                    f"{N['disc_total_pct']:.2f}% of gross sales; promotional activity happens through "
                                    "shelf-price changes, which this report measures directly."),
    (mnk(-N["below_cost_loss_kz"]), f"<b>Below-cost selling and cost errors need control.</b> Sales at less than "
                                    f"two-thirds of cost lost {mnk(-N['below_cost_loss_kz'])} over the period; "
                                    f"{P_['n_neg_gp']} articles lost money in the last 12 months; one cost posting of "
                                    f"−257m Kz (Apr 2026) was corrected before analysis."),
]
rows = [[Paragraph(a, ST["num"]), Paragraph(b, ST["box"])] for a, b in key]
t = Table(rows, colWidths=[30 * mm, CW - 30 * mm])
t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), .3, RULE),
                       ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                       ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
story.append(t)
h2("Priority recommendations")
bullets([
    "<b>Close the cost-to-price gap</b> in dairy, dry grocery, charcuterie and beverages, where the unit-cost index has "
    "outrun the price index since 2023; re-price on cost triggers within one quarter.",
    "<b>Test small price rises (3–5%) on low-sensitivity, low-margin lines</b> (Section 13 lists 25 named articles); "
    "on the measured elasticities these add gross profit even after the volume loss. Validate in test stores first.",
    "<b>Keep traffic items sharp</b>: water, juice, carbonated drinks, alcohol, oil and milk are highly elastic; price "
    "rises here lose volume fast and they drive basket visits.",
    "<b>Redesign temporary price cuts</b>: keep them shallow (10–15%), concentrate them on highly elastic lines, and "
    "fund them with supplier support; 30%+ cuts raised gross profit in only "
    f"{tpr_d.set_index('Depth_Bucket').loc['30-60%', 'Share_GP_Up_Pct']:.0f}% of cases.",
    "<b>Stop below-cost leakage</b>: monitor the loss-making articles and the below-cost transactions monthly; "
    "add automated checks on COGS postings (negative or >80% margin).",
])

# ================================================================== 2 data overview & quality
h1("Data overview and data quality")
P("All data come from Fresmart's Azure SQL database (sales lines with COGS, discount and tax; price-change log; daily "
  "stock) and official statistics (BNA exchange rate, INE/IMF CPI and GDP, EIA Brent). The sources were cleaned, "
  "converted to each article's base unit, and linked by month, week and day × location × article.")
inv = rd("dq_inventory")
table(["Dataset / level", "Rows / count"], [[r.Item.strip(), f"{r.Value:,.0f}"] for r in inv.itertuples()],
      [.7, .3], num_cols=(1,), caption="Data inventory after cleaning.")
table(["Source", "Coverage", "Used for"], [
    ["Sales lines (daily)", "Jan 2023 – Sep 2026", "Units, net sales, actual selling price, COGS, discount, tax, gross profit"],
    ["Article master (DB)", "8,385 in-scope articles", "Category hierarchy, base unit, import/local, status"],
    ["Location master + HORECA", "59 stores, 4 dark stores (HDDS), HORECA", "Zone, class, floor area, opening date"],
    ["Stock (daily → monthly)", "Jun 2024 – Oct 2026", "Opening/closing stock, days of cover, stock-outs"],
    ["List-price change log", "sparse before Feb 2026", "Cross-check of shelf prices"],
    ["Macro: FX, CPI, Brent, GDP", "Jan 2023 – Sep 2026", "Inflation adjustment and macro drivers"],
], [.26, .3, .44])
fig("r33_completeness", "Share of sales rows (month × location × article) where each field is available, by year.",
    "Selling price, unit cost and relative price are available on effectively 100% of sales rows in every year, so "
    "price, cost and margin analysis covers the full period. Stock is available only from June 2024 (the source starts "
    "then), and list prices are sparse until 2026; stock analyses therefore use Jun 2024 onward and the actual selling "
    "price is the primary price signal throughout.")
h2("Cleaning checks and actions")
dq = rd("dq_checks")
dq = dq[dq.Rows.astype(float) > 0]
table(["Dataset", "Check", "Rows", "Action"], [[r.Dataset, r.Check, f"{float(r.Rows):,.0f}", r.Action]
                                              for r in dq.itertuples()], [.09, .43, .1, .38], num_cols=(2,))
h2("Cost-data correction applied in this report")
fx_tab = rd("cogs_fixed_articles").head(6)
P(f"{cfix['rows']:,} month × location × article rows had a negative COGS or a margin above 80% on a positive sale, "
  f"which is not possible for a normal sale. Their recorded COGS summed to {mnk(cfix['raw_cogs_kz'])}. COGS was rebuilt "
  f"from that article's normal unit cost at that store × units sold ({cfix['rows_unit_cost']:,} rows), or at the "
  f"chain-average 80% cost ratio where no unit cost existed. This lowers gross profit by "
  f"{mnk(cfix['gp_change_kz'])} versus the raw data; almost all of it is one posting:")
table(["Article", "Sub-group", "Net sales", "Raw COGS", "Corrected COGS"],
      [[title(r.ArticleName)[:42], title(r.SubGroup), f"{r.Net_KZ / 1e6:,.2f}m Kz", f"{r.Raw_COGS_KZ / 1e6:,.2f}m Kz",
        f"{r.Fixed_COGS_KZ / 1e6:,.2f}m Kz"]
       for r in fx_tab.itertuples()], [.4, .15, .15, .15, .15], num_cols=(2, 3, 4))
box("<b>Definitions used throughout.</b> <b>Net sales</b> = sales after line discount, excluding tax (in the source, "
    "net sales equal gross sales). <b>Gross profit (GP)</b> = net sales − COGS. <b>Gross margin</b> = GP ÷ net sales. "
    "<b>Real</b> values are deflated by CPI (Jan 2023 = 100). <b>L12M</b> = Oct 2025 – Sep 2026; <b>prior 12M</b> = "
    "Oct 2024 – Sep 2025. <b>Selling price</b> = net sales ÷ units in the base unit (kg, litre or piece).")

# ================================================================== 3 methodology
h1("Methodology")
h2("Analytical approach")
bullets([
    "<b>Descriptive analysis</b> of sales, gross profit and margin by month, year, category, article and store, in "
    "nominal kwanza, USD and real (inflation-adjusted) terms; like-for-like on the stores open in all 45 months.",
    "<b>Price and cost indices</b>: sales-weighted chain indices of month-on-month changes in each article-store's "
    "selling price and unit COGS, so new products and new stores do not distort them.",
    "<b>Cost pass-through</b>: quarterly regression of the change in selling price on the change in unit cost (same "
    "and previous quarter), weighted by sales, per main group.",
    "<b>Price elasticity</b>: weekly fixed-effects regressions (8.76 million article-store-weeks) of log units on log "
    "price relative to the article's sub-category in the same store and week, with article-store and week effects; "
    "article estimates are shrunk towards their sub-category (empirical Bayes). Price-change event study on 33,154 "
    "permanent price moves.",
    "<b>Promotion proxy</b>: a <i>temporary price reduction</i> (TPR) is a week whose price is 10–60% below the median of "
    "the previous six weeks and returns to within 5% of that level two weeks later. Lift is measured against the "
    "previous six weeks and adjusted by the change for normally priced articles in the same sub-category and week.",
    "<b>Correlations</b>: Pearson correlations computed <i>within</i> each article-store (each value minus its own "
    "average) so that differences between products do not dominate; Spearman correlations across sub-categories; "
    "Pearson across months for macro drivers.",
    "<b>Price-response simulation</b>: for a price change d, units change by (1+d)<super>e</super> and gross profit by "
    "[(1+d) − (1−m)] / m × (1+d)<super>e</super>, using each item's measured elasticity e and actual margin m.",
])
h2("Correlation vs causation")
P("Correlations and descriptive comparisons in this report describe how variables move together; they do not by "
  "themselves prove cause. The elasticity estimates come closest to causal estimates because they compare the same "
  "article in the same store over time, against its own category in the same week, removing inflation, seasonality, "
  "store openings and category-wide demand swings. They can still be affected by things the data do not record: "
  "competitor prices, unrecorded promotions (in-store displays, leaflets), and supply shortages.")
h2("Key assumptions")
bullets([
    "Unit COGS is the actual cost recorded on the sales line; it reflects Fresmart's average stock cost, not the "
    "latest purchase price.",
    "Months where an article sold out at a store, store ramp-up weeks and articles with fewer than 20 usable weeks are "
    "excluded from elasticity models (88.5% of sales remain).",
    "September 2026 CPI is not yet published and is estimated from the trend for deflation.",
    "Simulated gross-profit effects assume other prices, competitor behaviour and costs stay unchanged; they are "
    "indicative and must be validated with controlled price tests.",
])

# ================================================================== 4 sales & revenue
h1("Sales and revenue trends")
fig("r01_sales_gp_margin", "Monthly net sales, gross profit (bars, nominal kwanza) and gross margin % (line).",
    f"Net sales grew from {mc.Net_KZ.iloc[0] / 1e9:.1f} bn Kz in Jan 2023 to {mc.Net_KZ.iloc[-1] / 1e9:.1f} bn Kz in "
    f"Sep 2026, with December peaks every year ({mc.Net_KZ.idxmax()} is the record month at "
    f"{mc.Net_KZ.max() / 1e9:.1f} bn Kz). Margin fell to {mc.Margin_Pct.min():.1f}% in {minm} after the June 2023 "
    f"devaluation, recovered to {mc.Margin_Pct.max():.1f}% by {maxm}, and has been stable at 19–23% since.")
fig("r02_growth_index", "Growth index of net sales in kwanza, USD and real terms, real gross profit, and "
    "like-for-like real sales (log scale, Jan 2023 = 100).",
    f"Kwanza sales rose about {mc.Net_KZ.iloc[-1] / mc.Net_KZ.iloc[0]:.1f}× but much of that is inflation: in real "
    f"terms sales rose {mc.Net_Real.iloc[-1] / mc.Net_Real.iloc[0]:.1f}×, and like-for-like (same {N['lfl_stores']} "
    f"stores) about {rd('monthly_lfl').Net_Real.iloc[-1] / rd('monthly_lfl').Net_Real.iloc[0]:.1f}×. Real gross "
    f"profit outgrew real sales because margin rose from 2023 levels. Since early 2025 like-for-like real sales are "
    f"flat, so recent growth comes from new stores.")
fig("r03_ytd_growth", "Year-on-year growth, January–September of each year.",
    f"2024 was the strongest year for profit (real GP {sp(y24.GP_Real_Growth, 0)}) as margins recovered. Real sales "
    f"growth has slowed each year ({sp(y24.Net_Real_Growth, 0)}, {sp(y25.Net_Real_Growth, 0)}, "
    f"{sp(y26.Net_Real_Growth, 0)}) as the store count rose from {y24.Locations:.0f} to {y26.Locations:.0f}.", width=.62)
table(["Jan–Sep", "Net sales", "Gross profit", "Margin", "Net sales growth (Kz)", "Real growth", "USD growth",
       "Locations", "Articles"],
      [[y, bnk(r.Net_KZ), bnk(r.GP_KZ), pc(r.Margin_Pct), "–" if np.isnan(r.Net_KZ_Growth) else sp(r.Net_KZ_Growth, 0),
        "–" if np.isnan(r.Net_Real_Growth) else sp(r.Net_Real_Growth, 0),
        "–" if np.isnan(r.Net_USD_Growth) else sp(r.Net_USD_Growth, 0), f"{r.Locations:.0f}", f"{r.Articles:,.0f}"]
       for y, r in ytd.iterrows()], [.08, .13, .13, .08, .14, .1, .1, .11, .13], num_cols=range(1, 9),
      caption="Year-to-date comparison (same nine months each year).")
fig("r04_group_mix", "Share of real net sales by main group, monthly.",
    "Poultry is consistently the largest category (24–30% of real sales). Cattle rose from 9% to about 13% of sales "
    "during 2023–24; dry division has grown steadily from 7% (early 2024) to 11%, while dairy fell from 14% in "
    "early 2023 to about 10%.")
fig_pair("03_seasonality", "04_day_of_month", "Left: monthly seasonality (average month = 100). Right: daily sales by "
         "day of month (month average = 100; orange = payday window 25th–3rd).",
         f"December runs {J['season'][11] - 100:.0f}% above an average month; January–February are the weakest. Daily "
         f"sales in the payday window average {PN['payday_days']:.0f} vs {PN['mid_days']:.0f} mid-month, a "
         f"{(PN['payday_days'] / PN['mid_days'] - 1) * 100:.0f}% uplift: price and promotion timing should follow pay "
         f"cycles.")
fig("05_weekday_heat", "Sales by weekday and category (week average = 100).",
    f"Saturday is the peak day for every category ({PN['weekday']['Sat']:.0f}), Friday second "
    f"({PN['weekday']['Fri']:.0f}); Monday–Tuesday are the quietest ({PN['weekday']['Mon']:.0f}–"
    f"{PN['weekday']['Tue']:.0f}).")

# ================================================================== 5 category & product
h1("Category and product performance")
top = mg_main.iloc[0]
fig("r05_group_share_margin", "Share of net sales and gross profit by main group (bars) and gross margin (dots), L12M.",
    f"{title(top.MainGroup)} earns {top.Sales_Share:.0f}% of sales but {top.GP_Share:.0f}% of gross profit at "
    f"{top.Margin_Pct:.0f}% margin. Cattle is the profit engine: {mg.set_index('MainGroup').loc['CATTLE', 'Sales_Share']:.0f}% "
    f"of sales but {mg.set_index('MainGroup').loc['CATTLE', 'GP_Share']:.0f}% of profit at "
    f"{mg.set_index('MainGroup').loc['CATTLE', 'Margin_Pct']:.0f}% margin. Dry commodities "
    f"({mg.set_index('MainGroup').loc['DRY-COMMODITY', 'Margin_Pct']:.0f}%) and baby food "
    f"({mg.set_index('MainGroup').loc['BABY FOOD', 'Margin_Pct']:.0f}%) are the thinnest.")
table(["Main group", "Net sales", "Share", "Gross profit", "GP share", "Margin", "Real growth", "Articles"],
      [[title(r.MainGroup), bnk(r.Net_KZ), pc(r.Sales_Share), bnk(r.GP_KZ), pc(r.GP_Share), pc(r.Margin_Pct),
        sp(r.Growth_Real_Pct, 0), f"{r.Articles:,.0f}"] for r in mg_main.itertuples()],
      [.19, .12, .09, .12, .09, .09, .11, .09], num_cols=range(1, 8),
      caption="Main-group performance, L12M (growth: real net sales vs prior 12 months).")
fig("r12_subgroup_quadrant", "Sub-categories by gross margin (x) and real sales growth (y), L12M; bubble = net sales; "
    "dashed lines = chain averages.",
    "Top-right (above-average margin and growth): pork, beef (vaca), sauces, body care, fresh produce, frozen. "
    "Bottom-left (thin margin, slow growth): chicken, eggs, rice, pasta and sugar, the largest-volume staples. Oil, "
    "alcohol and chocolates grow fast on below-average margins.")
table(["Sub-group", "Main group", "Net sales", "Share", "Margin", "Real growth", "Elasticity", "Import share"],
      [[title(r.SubGroup), title(r.MainGroup), bnk(r.Net_KZ), pc(r.Sales_Share), pc(r.Margin_Pct),
        sp(r.Growth_Real_Pct, 0), "–" if np.isnan(r.Elasticity) else f"{r.Elasticity:.2f}",
        "–" if np.isnan(r.Import_Share) else pc(r.Import_Share, 0)] for r in sg.head(20).itertuples()],
      [.18, .15, .12, .08, .08, .1, .1, .1], num_cols=range(2, 8), caption="Top 20 sub-categories by net sales, L12M.")
fig_pair("r09_pareto", "r08_margin_distribution", "Left: cumulative share of sales and gross profit by ranked "
         "article. Right: distribution of article gross margin, weighted by sales (L12M).",
         f"{P_['articles_l12m']:,} articles sold in the last 12 months; {P_['n_for_80_sales']} of them "
         f"({P_['n_for_80_sales'] / P_['articles_l12m'] * 100:.0f}%) generate 80% of sales. Most sales sit at 10–30% "
         f"margin; {P_['n_neg_gp']} articles had negative gross profit (total {mnk(P_['neg_gp_kz'])}).")
fig("r10_top_gp", "Top 15 articles by gross profit, L12M (label: gross profit · margin).",
    "The top profit earners are high-volume staples on thin margins (chicken leg quarters and eggs at 10–16%) and "
    "pork and beef cuts at around 30%. Small margin changes on the chicken lines move chain profit materially.")
fig("r11_bottom_gp", "Bottom 15 articles by gross profit, L12M (largest losses).",
    "The largest loss is the Fresmart carrier bag (packing material), sold below cost, followed by dairy (butter, "
    "cheese, cream) and chicken processed lines. These need cost or price review, or a deliberate decision to "
    "keep them as service items.")

# ================================================================== 6 profit & margin
h1("Profit and gross margin analysis")
fig("r06_margin_group_quarter", "Gross margin by main group and quarter (actual COGS).",
    "The 2023 devaluation hit poultry (6–9%) and dry commodities (3–11%) hardest, as imported costs repriced faster "
    "than shelf prices. Margins recovered through 2024. Cattle margins have risen steadily to the mid-30s in 2026; "
    "baby food has drifted down to 13–15%.")
fig("r07_margin_group_zone", "Gross margin by main group and zone, stores only, L12M.",
    "Province stores earn the highest margins in most categories, consistent with their 2–4% price premium "
    "(Section 10). Cazenga and Golf earn the lowest, in line with their below-chain prices.")
fig("r07_margin_group_class", "Gross margin by main group and store class (P = province), stores only, L12M.",
    "Store class makes little difference: class C stores typically run about 1 point below class A; province (P) "
    "stores are highest in most categories.", width=.62)
fig("r19_fx_margin", "Monthly chain gross margin vs the change in the kwanza (Kz per USD) over the previous three "
    "months.",
    f"Margin and devaluation move together (r = {N['fx3_margin_r']:.2f}): when the kwanza falls quickly, cost rises "
    f"before prices follow, as in June–August 2023. This is a correlation over 45 months dominated by that episode.",
    width=.58)
table(["Sourcing", "Net sales", "Gross profit", "Margin", "Articles"],
      [[k, bnk(r.Net_KZ), bnk(r.GP_KZ), pc(r.Margin_Pct), f"{r.Articles:,.0f}"] for k, r in imp.iterrows()],
      [.2, .2, .2, .2, .2], num_cols=(1, 2, 3, 4), caption="Imported vs locally sourced articles, L12M.")
P(f"Imported articles earn a higher margin ({imp.loc['Import', 'Margin_Pct']:.1f}%) than local ones "
  f"({imp.loc['Local', 'Margin_Pct']:.1f}%), mainly because imported meat (beef, pork) carries ~30% margins, while "
  f"local staples (eggs, sugar, rice, oil) run at 10–15%.")

# ================================================================== 7 pricing: price & cost
h1("Pricing analysis: prices, costs and pass-through")
fig("r16_price_cost_index", "Chain selling-price and unit-cost indices (same article, same store, month on month), "
    "against CPI and the exchange rate.",
    f"By Sep 2026 the selling-price index stood at {ix.Price_Index.iloc[-1]:.0f} and the unit-cost index at "
    f"{ix.Cost_Index.iloc[-1]:.0f} (Jan 2023 = 100): unit costs rose more than prices. Both jumped with the June 2023 "
    f"devaluation (FX index {ix.FX_Index.loc['2023-07']:.0f} by July) and have risen slowly since the kwanza "
    f"stabilised in 2024.")
fig("r17_price_cost_groups", "Selling price vs unit cost index by main group (Feb 2023 = 100).",
    "Poultry, cattle and FNV prices have kept pace with or exceeded cost. Dry division (cost +65% vs price +41%), "
    "dairy (+105% vs +55%) and charcuterie (+83% vs +66%) show a persistent gap, and beverages a small one: these "
    "categories have absorbed cost and their margins carry the risk.")
fig("r18_cost_passthrough", "Share of a unit-cost change passed into the selling price, same and following quarter.",
    f"Across all articles {N['cost_pt_all']['Same_Quarter']:.0f}% of a cost change reaches the price in the same "
    f"quarter and {N['cost_pt_all']['Cumulative']:.0f}% within two quarters. Dry commodities, bakery and FNV pass "
    f"through nearly fully; cattle, charcuterie and pet only about half, which protects volume but compresses "
    f"margin when costs rise.")
fig("12_passthrough_heat", "Pass-through of exchange-rate and oil-price moves into Fresmart prices, by months after "
    "the change.",
    f"About {PN['pt_fx6']['ALL']:.0f}% of a devaluation reaches shelf prices within six months. Poultry "
    f"({PN['pt_fx6']['POULTRY']:.0f}%) and dry commodities ({PN['pt_fx6']['DRY-COMMODITY']:.0f}%) are fully "
    "FX-linked; beverages, dairy, personal care and FNV barely respond to FX. Oil prices have little effect.")

# ================================================================== 8 price-volume & elasticity
h1("Price–volume relationships and price elasticity")
fig("r23_demand_all", "Demand curve across all articles: units vs price, each relative to the article-store's usual "
    "level and the category week (20 equal-size bins).",
    f"Units fall steadily as relative price rises (binned slope {bins['ALL']:.2f}): about 10% fewer units for a 10% "
    f"higher relative price, with a slightly steeper response to cuts below −15%.", width=.55)
fig("41_group_elasticity", "Elasticity by main group (weekly model, 95% interval).",
    "Poultry, charcuterie, pet, dairy and beverages are the most price-sensitive groups (−1.3 to −1.6); bakery, FNV "
    "and seafood the least (−0.4 to −0.8). Intervals are narrow for the large groups.", width=.72)
fig("r24_demand_subgroups", "Demand curves for the eight largest sub-categories (slope in brackets).",
    "Milk, alcohol, chicken and pork lose volume fastest when their price rises against the category; fresh produce "
    "and beef barely react. Oil shows a step pattern: volume collapses once its price moves above competing "
    "oil brands.")
table(["Model", "Elasticity", "Std. error"],
      [[r["Model"], f"{r['Estimate']:.3f}", f"{r['Std. Error']:.3f}"] for r in J["pooled"]], [.66, .17, .17],
      num_cols=(1, 2), caption="Pooled elasticity models (8.76M article-store-weeks, article-store and week fixed "
                               "effects).")
P(f"The headline estimate is {e_head:.2f}: a 10% rise in an article's price relative to its category reduces units by "
  f"about {abs(e_head) * 10:.0f}%. Using raw kwanza prices gives {e_raw:.2f}, because general inflation raises prices "
  f"while nominal demand keeps growing; comparing prices without adjusting for inflation would understate sensitivity "
  f"by half. Rises above the usual price are punished more ({e_up:.2f}) than cuts below it are rewarded ({e_dn:.2f}).")
ac = pd.DataFrame(J["art_class"])
table(["Article elasticity class", "Articles", "Net sales (estimation period)", "Share"],
      [[r.Class, f"{r.Articles:,}", bnk(r.Sales_KZ), pc(r.Sales_KZ / ac.Sales_KZ.sum() * 100)] for r in ac.itertuples()],
      [.4, .15, .3, .15], num_cols=(1, 2, 3), caption=f"{J['n_articles_est']:,} articles with an individual "
                                                       "elasticity (shrunk towards their sub-category).")
fig("50_events", "33,154 permanent price changes: median volume change four weeks after vs before, relative to the "
    "category in the same store.",
    "The event study confirms the regressions without modelling assumptions: a 5–10% cut lifted volume a median 12%, "
    "a 5–10% rise cut it 9%; larger moves scale up.")
fig("42_splits", "Elasticity by year, by stock cover and by price tier.",
    "Sensitivity has been stable at about −1.0 to −1.1 every year despite very different inflation rates. "
    "Overstocked articles (more than two months of cover) barely respond to price (−0.54), so markdowns on slow "
    "movers have limited volume effect.")

# ================================================================== 9 discount & promotion
h1("Discount and promotion effectiveness")
P(f"Recorded line discounts total {N['disc_total_pct']:.2f}% of gross sales and appear on "
  f"{N['disc_rows_pct']:.1f}% of article-store-months. There is no promotion flag in the source; promotional activity "
  f"is therefore measured from the price data as temporary price reductions (Section 3), which occur in "
  f"{N['tpr_share_weeks']:.1f}% of article-store-weeks.")
fig("r27_discount", "Recorded discount as % of gross sales: by month (left) and by main group (right).",
    "Recorded discounts spiked in early 2023 (1.5% in March) and have stayed at 0.1–0.3% since. Seafood and bakery "
    "carry the most (end-of-day and fresh markdowns).")
fig("r28_discount_depth", "Units sold vs the article-store's usual level, by recorded discount depth in the month.",
    f"Months with small discounts (0–5%) coincide with higher volume (+24% to +55%): these are busy months where some "
    f"transactions received a discount, so the link is not causal. Months with discounts above 10% sell "
    f"{abs(dd.loc['>10%', 'Volume_vs_Usual_Pct']):.0f}% <i>fewer</i> units at "
    f"{abs(dd.loc['>10%', 'Margin_vs_Usual_pp']):.0f} points lower margin, typical of clearance of slow or "
    f"short-dated stock.", width=.62)
fig("r29_tpr_depth", "Temporary price reductions: median category-adjusted unit lift and share of events where gross "
    "profit rose, by depth.",
    f"Across {TP['Events']:,.0f} events (median {TP['Median_Depth_Pct']:.0f}% off), units rose a median "
    f"{TP['Median_Adj_Lift_Pct']:.0f}% (implied promotional elasticity {TP['Median_Promo_Elasticity']:.1f}, about "
    f"twice the regular-price elasticity). But gross profit rose in only {TP['Share_GP_Up_Pct']:.0f}% of events, "
    f"and the deeper the cut the worse: 37% of 10–15% cuts vs 12% of 30–60% cuts. The week after a cut, units are "
    f"still a median {TP['Median_Post_Week_Vol_Pct']:.0f}% above the old baseline, so there is no sign of a large "
    f"pull-forward dip.")
fig("r30_tpr_group", "Temporary price reductions by main group: median category-adjusted lift, implied elasticity, "
    "share of events with higher gross profit, number of events.",
    "Dry commodities, beverages, dairy and poultry respond most strongly (60–90% lift); FNV, bakery and seafood "
    "respond least. Even in the best categories fewer than half of cuts paid back in gross profit, so promotions "
    "are justified only as traffic drivers or when suppliers fund the discount.")
table(["Cut depth", "Events", "Median cut", "Median lift (adj.)", "Promo elasticity", "GP rose in", "Week after",
       "Total GP change"],
      [[r.Depth_Bucket, f"{r.Events:,.0f}", pc(r.Median_Depth_Pct, 0), sp(r.Median_Adj_Lift_Pct, 0),
        f"{r.Median_Promo_Elasticity:.1f}", pc(r.Share_GP_Up_Pct, 0), sp(r.Median_Post_Week_Vol_Pct, 0),
        mnk(r.Total_GP_Change_KZ)] for r in tpr_d.itertuples()], [.1, .1, .1, .14, .13, .1, .11, .22],
      num_cols=range(1, 8), caption="Temporary price reductions by depth (GP change vs the previous six weeks).")

# ================================================================== 10 stores
h1("Store performance")
best = st_full.nlargest(1, "GP_per_Sqm_Month_KZ").iloc[0]
fig("r13_store_scatter", "Stores: net sales per m² per month (x) vs gross margin (y), L12M; bubble = net sales; "
    "colour = zone.",
    f"Margins cluster tightly at 17–24%; productivity varies far more, from under 100k to "
    f"{st_full.Sales_per_Sqm_Month_KZ.max() / 1e3:,.0f}k Kz per m² per month ({store(best.Store_Name)}). Province "
    f"stores (grey) combine above-average margin with good productivity; Cazenga, Cuca and Golf stores have the "
    f"lowest margins.")
fig("r14_store_gp_sqm", "Gross profit per m² per month by store, L12M (colour = zone).",
    "Space productivity is the main difference between stores: the top quartile earns about 3.5 times the "
    "gross profit per m² of the bottom quartile. The bottom includes the two largest-floor stores, Benfica "
    "Fresmart (2,947 m²) and Moxico (1,531 m²), whose space is under-used relative to their sales.")
fig("r15_premium_margin", "Store price premium vs chain average, and store gross margin (L12M).",
    f"Stores that price higher earn higher margins (r = {N['store_premium_margin_r']:.2f}), driven by the province "
    f"stores, which are also the most price-sensitive (elasticity about −1.4): the premium holds margin but costs "
    f"volume.", width=.58)
fig("20_cover_vs_price_move", "Relative price move in the following month by current stock cover (Jun 2024 onward).",
    "Price moves hardly depend on stock: articles with more than four months of cover are cut by more than 10% only "
    "slightly more often (8.9% vs 6.1%), so stock levels are not yet used systematically in pricing.", width=.8)
cols = ["Store", "Zone", "Class", "Net sales", "Margin", "Sales per m² per month", "GP per m² per month",
        "Real growth", "Elasticity", "Price premium"]
fmt = lambda r: [store(r.Store_Name), title(r.Area_Zone), r.Store_Class, bnk(r.Net_KZ), pc(r.Margin_Pct),
                 f"{r.Sales_per_Sqm_Month_KZ / 1e3:,.0f}k", f"{r.GP_per_Sqm_Month_KZ / 1e3:,.0f}k",
                 "–" if np.isnan(r.Growth_Real_Pct) else sp(r.Growth_Real_Pct, 0),
                 "–" if np.isnan(r.Elasticity) else f"{r.Elasticity:.2f}", sp(r.Price_Premium_Pct)]
w = [.2, .1, .06, .1, .08, .1, .09, .09, .09, .09]
table(cols, [fmt(r) for r in st_full.nlargest(12, "GP_KZ").itertuples()], w, num_cols=range(3, 10),
      caption="Top 12 stores by gross profit, L12M (stores open all 12 months; growth only for stores also open in "
              "all of the prior 12 months).")
table(cols, [fmt(r) for r in st_full.nsmallest(10, "GP_per_Sqm_Month_KZ").itertuples()], w, num_cols=range(3, 10),
      caption="Bottom 10 stores by gross profit per m², L12M.")

# ================================================================== 11 correlations
h1("Correlation analysis")
fig("r20_corr_within", "Correlations within each article-store over time (monthly; "
    f"{N['corr_n'] / 1e6:.1f} million rows).",
    f"When an article's real price is higher than its usual level, units are lower (r = "
    f"{cw.loc['ln Units sold', 'ln Real price']:.2f}) and margin is higher ({cw.loc['Gross margin %', 'ln Real price']:.2f}). "
    f"Higher unit cost goes with lower margin ({cw.loc['Gross margin %', 'ln Real unit cost']:.2f}): cost increases are "
    f"not fully passed on. Discounts go with lower price and lower margin. More days of stock cover go with lower "
    f"sales ({cw.loc['ln Units sold', 'ln Days of cover']:.2f}), i.e. slow sellers accumulate stock, not the reverse.")
fig("r21_corr_macro", "Correlations across the 45 months between chain results, price and cost indices, and macro "
    "variables.",
    f"Real sales and real gross profit track the number of locations (r = {cm.loc['Real net sales', 'Locations']:.2f}) "
    f"and the price index. Price and cost indices move almost one-for-one with the exchange rate (r = "
    f"{cm.loc['Price index', 'FX (BNA)']:.2f} and {cm.loc['Cost index', 'FX (BNA)']:.2f}). Brent and GDP show weak "
    f"links. With only 45 trending monthly points, these correlations reflect shared trends and are not causal.")
fig("r22_corr_subgroup", f"Spearman correlations across {N['corr_subgroup_n']} sub-categories with more than 0.5 bn Kz "
    "of L12M sales.",
    f"Higher-margin sub-categories tend to be <i>less</i> price-sensitive (elasticity closer to zero; r = "
    f"{csg.loc['Gross margin %', 'Elasticity']:.2f}) and more import-based (r = "
    f"{csg.loc['Gross margin %', 'Import share %']:.2f}). Growth is only weakly related to margin "
    f"(r = {csg.loc['Gross margin %', 'Real growth %']:.2f}). Discounting is concentrated in the less price-sensitive "
    f"sub-categories (r = {csg.loc['Discount %', 'Elasticity']:.2f}), i.e. where it buys the least volume.", width=.72)

# ================================================================== 12 anomalies
h1("Anomalies and risk areas")
fig("r31_anomalies", "Loss on sales made far below cost (COGS above 1.5× sales value; bars) and the rate of price and "
    "cost outliers per 1,000 sales rows (lines).",
    f"Below-cost transactions are {N['below_cost_share']:.2f}% of sales value but lost {mnk(-N['below_cost_loss_kz'])} "
    f"over 45 months, and the problem is growing: losses ran at 80–110m Kz a month in March–June 2026 against "
    f"10–30m in 2024. Price and cost outlier rates are stable at 1–2 per 1,000 sales rows.")
ng = rd("neg_gp_articles").head(12)
table(["Article", "Sub-group", "Net sales", "Gross profit", "Margin"],
      [[title(r.ArticleName)[:44], title(r.SubGroup), mnk(r.Net_KZ), mnk(r.GP_KZ), pc(r.Margin_Pct)]
       for r in ng.itertuples()], [.44, .17, .13, .13, .13], num_cols=(2, 3, 4),
      caption=f"Largest loss-making articles, L12M ({P_['n_neg_gp']} articles with negative gross profit, total "
              f"{mnk(P_['neg_gp_kz'])}).")
fig("r32_store_margin_dev", "Store-month margin minus each store's own median margin (22 most volatile stores, "
    "2024 onward).",
    "The whole chain moved together in March–July 2024 (+3 to +6 points, margin recovery) and December 2024 (−2 to "
    "−6, Christmas pricing). Store-specific outliers are rare (Porto Amboim's opening month, May 2026, is the "
    "clearest); a +8-point spike at Kikagil in April 2026 in the raw data was the cost-posting error corrected in "
    "Section 2. Store margin is therefore set centrally and local deviations are small.")

# ================================================================== 13 opportunities
h1("Pricing opportunities")
fig("r26_margin_vs_elasticity", "Sub-categories: price elasticity vs actual gross margin, L12M; bubble = net sales. "
    "The curve is the margin at which price maximises gross profit (−1/elasticity).",
    "Every major sub-category sits below the profit-maximising curve: on the measured short-run elasticities, "
    "current margins are lower than profit maximisation would imply. In practice competitor responses, price image "
    "and longer-run customer switching make demand more elastic than a short-run estimate, so this indicates the "
    "direction (careful increases on low-sensitivity lines), not a target margin.")
fig("r25_simulation", "Simulated effect of a price change on units and gross profit for the ten largest "
    "sub-categories, using their measured elasticity (e) and actual margin (m).",
    "Because margins are thin, a small price rise raises gross profit even when volume falls: at a 18% margin and "
    "elasticity −1.7 (chicken), a 5% rise loses about 8% of units but adds gross profit. Cuts destroy gross profit "
    "quickly for the same reason: a 10% cut on chicken would need roughly 2× the volume to break even. "
    "<i>Model-implied, not measured; assumes competitors and costs do not change.</i>")
o = rd("opp_price_rise")
table(["Article", "Sub-group", "Net sales", "Margin", "Elasticity", "GP change at +5%", "GP change, Kz"],
      [[title(r.ArticleName)[:40], title(r.SubGroup), mnk(r.Net_KZ), pc(r.Margin_Pct), f"{r.Elasticity:.2f}",
        sp(r.GP_Chg_Up5_Pct), mnk(r.GP_Chg_Up5_KZ)] for r in o.head(15).itertuples()],
      [.33, .12, .11, .09, .1, .12, .13], num_cols=range(2, 7),
      caption=f"Price-rise test candidates: low sensitivity (elasticity above −0.8, reliable estimate), margin below "
              f"30%, sold in 10+ stores. Top 15 of {N['opp']['all_rise_candidates']:,} qualifying articles; model-implied "
              f"gross-profit gain for the top 25 at +5%: {mnk(N['opp']['rise_gp_kz'])} a year.")
oc = rd("opp_price_cut")
if len(oc):
    table(["Article", "Sub-group", "Margin", "Elasticity", "GP change at −5%", "GP change, Kz"],
          [[title(r.ArticleName)[:42], title(r.SubGroup), pc(r.Margin_Pct), f"{r.Elasticity:.2f}",
            sp(r.GP_Chg_Dn5_Pct), mnk(r.GP_Chg_Dn5_KZ)] for r in oc.head(10).itertuples()],
          [.4, .14, .1, .11, .13, .12], num_cols=range(2, 6),
          caption="Price-investment candidates: highly elastic (below −2.5) with margins high enough that a 5% cut is "
                  "model-implied to raise gross profit. Few qualify, and their gains are small.")
box("<b>How to use these lists.</b> They rank where the data say a change is most likely to pay, not what prices "
    "should be. Each candidate should be tested: raise the price in a matched set of stores for 6–8 weeks, keep "
    "control stores unchanged, and compare units and gross profit, before rolling out. Key value items that shape "
    "price perception (chicken, oil, rice, sugar, milk) should be checked against competitor prices first.", WARN)

# ================================================================== 14 findings & recommendations
h1("Key findings and recommendations")
h2("Key findings")
bullets([
    f"<b>Growth:</b> net sales {bnk(L12_net)} and gross profit {bnk(L12_gp)} in the last 12 months; Jan–Sep 2026 real "
    f"sales {sp(y26.Net_Real_Growth, 0)}, real gross profit {sp(y26.GP_Real_Growth, 0)}. Like-for-like real sales have "
    f"been flat since early 2025.",
    f"<b>Margin:</b> {pc(L12_margin)} in the last 12 months, recovered from {mc.Margin_Pct.min():.0f}% at the 2023 low; "
    f"cattle (32%), FNV, bakery and charcuterie carry the highest margins; dry commodities (13%) and baby food (14%) "
    f"the lowest.",
    f"<b>Cost:</b> unit cost rose more than price since 2023 (index {ix.Cost_Index.iloc[-1]:.0f} vs "
    f"{ix.Price_Index.iloc[-1]:.0f}); {N['cost_pt_all']['Cumulative']:.0f}% of a cost change passes through within "
    f"two quarters, only about half in cattle, charcuterie and pet.",
    f"<b>Price sensitivity:</b> chain elasticity {e_head:.2f}; rises hurt more ({e_up:.2f}) than cuts help "
    f"({e_dn:.2f}); drinks, oil, milk and chicken are most sensitive; beef, fresh produce, cheese and body care least.",
    f"<b>Promotions:</b> temporary cuts lift units about {TP['Median_Adj_Lift_Pct']:.0f}% but raise gross profit in "
    f"only {TP['Share_GP_Up_Pct']:.0f}% of cases; recorded discounts are negligible.",
    "<b>Stores:</b> margins are uniform (17–24%), productivity is not; province stores price 2–4% higher, earn the best "
    "margins and are the most price-sensitive.",
    f"<b>Leakage:</b> {mnk(-N['below_cost_loss_kz'])} lost on below-cost sales, {P_['n_neg_gp']} loss-making articles, "
    "and cost-posting errors large enough to distort monthly results.",
])
h2("Recommendations")
table(["#", "Action", "Evidence", "Expected effect"], [
    ["1", "Re-price categories where cost has outrun price (dairy, dry division, charcuterie, beverages) using a "
          "cost-trigger rule", "Section 7; pass-through 49–78%", "Restores margin lost since 2023"],
    ["2", "Test +3–5% on low-sensitivity, thin-margin articles in matched test stores",
     "Section 13 list; elasticity > −0.8", f"Model-implied up to {mnk(N['opp']['rise_gp_kz'])}/yr on top 25"],
    ["3", "Keep highly elastic traffic items (water, juice, soft drinks, alcohol, oil, milk) at or below market",
     "Elasticity −2 to −5", "Protects visits and basket"],
    ["4", "Limit temporary cuts to 10–15%, on elastic lines, supplier-funded; stop deep cuts",
     "Section 9", "Fewer profit-losing promotions"],
    ["5", "Review the province price premium store by store", "Section 10; elasticity −1.4",
     "Balance margin and volume"],
    ["6", "Monthly control of below-cost sales and negative-margin articles; automated COGS validation",
     "Section 12", "Stops leakage; reliable reporting"],
    ["7", "Time price changes and promotions to payday (25th–3rd), Saturdays and December", "Section 4",
     "Higher promotional return"],
    ["8", "Link imported-category prices to the exchange rate with a defined lag", "Section 7",
     "Faster margin protection in devaluations"],
], [.04, .46, .26, .24])

# ================================================================== 15 limitations
h1("Limitations")
bullets([
    "<b>No competitor prices.</b> Elasticities measure response to Fresmart's own price relative to its category; they "
    "cannot separate a customer switching brands within Fresmart from switching to another retailer.",
    "<b>No promotion flag.</b> Promotions are inferred from temporary price reductions; displays, leaflets and "
    "multi-buy offers without a shelf-price change are not captured, and some TPRs may be price corrections.",
    "<b>COGS is the average stock cost on the sales line</b>, not the replacement cost; in fast inflation it lags "
    "purchase prices, which flatters margin briefly after cost increases.",
    "<b>Stock data start in June 2024</b> and are monthly snapshots; daily stock-outs are not observed, so some "
    "low-sales weeks may reflect empty shelves.",
    "<b>Simulations and opportunity sizes are model-implied</b>, short-run and partial-equilibrium; they must be "
    "validated with controlled tests.",
    "<b>Correlations are not causal.</b> Cross-month macro correlations rest on 45 trending observations; "
    "cross-category correlations on 44 sub-categories.",
    f"<b>Data corrections</b>: {cfix['rows']:,} rows with impossible COGS were corrected (Section 2); September 2026 "
    "CPI is estimated.",
])
h2("Glossary")
table(["Term", "Meaning"], [
    ["Elasticity", "% change in units for a 1% change in price; −1.0 means a 10% rise loses 10% of units"],
    ["Relative price", "Article price ÷ price index of its sub-category in the same store and week"],
    ["Pass-through", "% of a cost (or exchange-rate) change that appears in the selling price"],
    ["TPR", "Temporary price reduction: 10–60% below the 6-week median, back to normal two weeks later"],
    ["Like-for-like (LFL)", f"The {N['lfl_stores']} locations with sales in all 45 months"],
    ["L12M", "Last 12 months: Oct 2025 – Sep 2026"],
], [.22, .78])

# ------------------------------------------------------------------ build (two passes: contents page needs the TOC)
def build():
    doc = BaseDocTemplate(str(OUTF), pagesize=A4, leftMargin=M, rightMargin=M, topMargin=15 * mm,
                          bottomMargin=18 * mm, title="Fresmart Retail Data Analysis Report",
                          author="Newaco pricing analytics", subject="EDA, pricing, profit, promotion and elasticity")
    frame = Frame(M, 18 * mm, CW, H - 33 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate("cover", [Frame(0, 0, W, H)], onPage=cover),
                          PageTemplate("body", [frame], onPage=page)])
    head = [NextPageTemplate("body"), PageBreak(), Paragraph("Contents", ST["h1"])]
    data = [[Paragraph(a, ST["cell"]), Paragraph(b, ST["cell"])] for a, b in TOC]
    tt = Table(data, colWidths=[CW * .07, CW * .93])
    tt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), .3, RULE), ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    head += [tt, Spacer(1, 10),
             Paragraph(f"{FIGNO[0]} figures and their interpretation, plus supporting tables. Every number is computed "
                       "from Fresmart's own data or published macro statistics; model-based estimates are marked.",
                       ST["body"])]
    doc.build(head + story)
    print(OUTF)


build()
