"""Assemble the full PDF report: report/Fresmart_Price_Elasticity_Report.pdf"""
import json
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image as RLImage, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
CH = ROOT / "report" / "pdf_charts"
OUTF = ROOT / "report" / "Fresmart_Price_Elasticity_Report.pdf"
J = json.load(open(ROOT / "report" / "data.json"))
N = json.load(open(ROOT / "report" / "pdf_numbers.json"))

F = "C:/Windows/Fonts/"
for name, file in [("Body", "segoeui.ttf"), ("Body-Bold", "segoeuib.ttf"), ("Body-Italic", "segoeuii.ttf"),
                   ("Body-Light", "segoeuil.ttf"), ("Head", "georgiab.ttf"), ("Head-Reg", "georgia.ttf")]:
    pdfmetrics.registerFont(TTFont(name, F + file))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")

INK, INK2, MUTED, RULE = colors.HexColor("#15201b"), colors.HexColor("#4d5751"), colors.HexColor("#7f8781"), colors.HexColor("#dfe3de")
ACC, SOFT = colors.HexColor("#0f6b55"), colors.HexColor("#e3efea")
W, H = A4
M = 18 * mm
CW = W - 2 * M

ST = {
    "h1": ParagraphStyle("h1", fontName="Head", fontSize=19, leading=24, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Body-Bold", fontSize=11.5, leading=15, textColor=INK, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Body", fontSize=9.4, leading=13.6, textColor=INK, spaceAfter=6),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=9.4, leading=13.4, textColor=INK, leftIndent=12,
                             bulletIndent=2, spaceAfter=3),
    "cap": ParagraphStyle("cap", fontName="Body", fontSize=8, leading=10.5, textColor=INK2, spaceBefore=2, spaceAfter=10),
    "kicker": ParagraphStyle("kicker", fontName="Body-Bold", fontSize=8, leading=10, textColor=ACC, spaceAfter=2),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=7.8, leading=10, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=7.8, leading=10, textColor=INK2),
    "box": ParagraphStyle("box", fontName="Body", fontSize=9, leading=13, textColor=INK),
    "num": ParagraphStyle("num", fontName="Head", fontSize=15, leading=18, textColor=ACC),
}
story = []
P = lambda t, s="body": story.append(Paragraph(t, ST[s]))
SECTION = [0]


def h1(t, anchor):
    SECTION[0] += 1
    story.append(PageBreak())
    story.append(Paragraph(f'<a name="{anchor}"/>Section {SECTION[0]}', ST["kicker"]))
    story.append(Paragraph(t, ST["h1"]))


def bullets(items):
    for t in items:
        story.append(Paragraph(t, ST["bullet"], bulletText="•"))


def fig(name, caption, width=1.0):
    path = CH / f"{name}.png"
    w, h = Image.open(path).size
    iw = CW * width
    img = RLImage(str(path), width=iw, height=iw * h / w)
    img.hAlign = "LEFT"
    story.append(KeepTogether([img, Paragraph(caption, ST["cap"])]))


def fig_pair(a, b, caption):
    imgs = []
    for n in (a, b):
        w, h = Image.open(CH / f"{n}.png").size
        iw = CW / 2 - 3 * mm
        imgs.append(RLImage(str(CH / f"{n}.png"), width=iw, height=iw * h / w))
    t = Table([imgs], colWidths=[CW / 2, CW / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([t, Paragraph(caption, ST["cap"])]))


def table(head, rows, widths, num_cols=(), font=7.8):
    data = [[Paragraph(h, ST["cellb"]) for h in head]] + \
           [[Paragraph(str(c), ST["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=[CW * w for w in widths], repeatRows=1)
    style = [("LINEBELOW", (0, 0), (-1, 0), .8, INK2), ("LINEBELOW", (0, 1), (-1, -1), .3, RULE),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 4)]
    for c in num_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 8))


def box(text):
    t = Table([[Paragraph(text, ST["box"])]], colWidths=[CW])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.append(KeepTogether([t, Spacer(1, 8)]))


title = lambda s: str(s).title().replace("Fnv", "FNV").replace("Hdds", "HDDS")
f2 = lambda v: f"{v:.2f}"
pct = lambda v, d=0: f"{v:+.{d}f}%"


def sens(e):
    return "highly elastic" if e <= -2 else "elastic" if e <= -1 else "moderate" if e <= -.3 else "inelastic" if e <= 0 else "check"


# ------------------------------------------------------------------ page templates
def cover(c, d):
    c.saveState()
    c.setFillColor(colors.HexColor("#0f3d31"))
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#4fc1a0"))
    c.rect(M, H - 62 * mm, 28 * mm, 1.6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#9fd9c7"))
    c.setFont("Body-Bold", 10)
    c.drawString(M, H - 55 * mm, "FRESMART · ANGOLA · PRICE OPTIMIZATION, PHASE 1")
    c.setFillColor(colors.white)
    c.setFont("Head", 34)
    c.drawString(M, H - 84 * mm, "Price Elasticity &")
    c.drawString(M, H - 98 * mm, "Demand Drivers")
    c.setFont("Head-Reg", 14)
    c.setFillColor(colors.HexColor("#cfe8df"))
    c.drawString(M, H - 112 * mm, "Exploratory analysis and elasticity report")
    c.setFont("Body", 10.5)
    y = H - 140 * mm
    for k, v in [("Period", "January 2023 – September 2026 (45 months)"),
                 ("Scope", "66 locations: 59 stores, 4 HDDS dark stores, HORECA"),
                 ("Articles", "8,385 in scope · 3,716 with an individual elasticity"),
                 ("Sales analysed", "USD 333 million · 46 million daily sales rows"),
                 ("Data", "Azure SQL sales, prices, stock; BNA, INE, IMF, EIA macro series")]:
        c.setFillColor(colors.HexColor("#9fd9c7"))
        c.drawString(M, y, k.upper())
        c.setFillColor(colors.white)
        c.drawString(M + 38 * mm, y, v)
        y -= 7.5 * mm
    c.setFont("Body", 9)
    c.setFillColor(colors.HexColor("#9fd9c7"))
    c.drawString(M, 22 * mm, "Prepared 8 October 2026 · Newaco / Fresmart pricing analytics")
    c.restoreState()


def page(c, d):
    c.saveState()
    c.setFont("Body", 7.5)
    c.setFillColor(MUTED)
    c.drawString(M, 10 * mm, "Fresmart · Price Elasticity & Demand Drivers · Oct 2026")
    c.drawRightString(W - M, 10 * mm, f"{d.page}")
    c.setStrokeColor(RULE)
    c.line(M, 13.5 * mm, W - M, 13.5 * mm)
    c.restoreState()


doc = BaseDocTemplate(str(OUTF), pagesize=A4, leftMargin=M, rightMargin=M, topMargin=16 * mm, bottomMargin=18 * mm,
                      title="Fresmart Price Elasticity & Demand Drivers", author="Newaco pricing analytics",
                      subject="EDA and price elasticity, Jan 2023 - Sep 2026")
frame = Frame(M, 18 * mm, CW, H - 34 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates([PageTemplate("cover", [Frame(0, 0, W, H)], onPage=cover),
                      PageTemplate("body", [frame], onPage=page)])
story += [NextPageTemplate("body"), PageBreak()]

# ------------------------------------------------------------------ contents
P("Contents", "h1")
toc = [("1", "Executive summary"), ("2", "Data, cleaning and method"), ("3", "Sales performance"),
       ("4", "Shopping calendar: seasonality, payday and weekday"), ("5", "Prices, inflation and the exchange rate"),
       ("6", "The macro-economy and demand"), ("7", "Stock and price"), ("8", "Location: price level, mix and sensitivity"),
       ("9", "Price elasticity"), ("10", "What happened when prices changed"), ("11", "Margin and pricing headroom"),
       ("12", "Recommendations, limits and next steps"), ("A", "Appendix: model specifications and glossary")]
table(["", "Section"], [[a, b] for a, b in toc], [.06, .94])

# ------------------------------------------------------------------ 1 executive summary
h1("Executive summary", "s1")
P("This report analyses 45 months of Fresmart sales, prices and stock, linked to Angola's exchange rate, inflation, "
  "oil price and GDP. It answers three questions: how customers respond to price, what else drives demand, and where "
  "pricing can be improved. All prices are adjusted for inflation; elasticities compare each article with its own "
  "category in the same store and week, so inflation, devaluation, new stores and seasonality do not distort them.")
ac = {r["Class"]: r for r in J["art_class"]}
tot_s = sum(r["Sales_KZ"] for r in J["art_class"])
key = [
    ("−1.03", "<b>Chain price elasticity.</b> A 10% price rise relative to the category cuts unit volume by about 10%. "
              "Measured on raw kwanza prices it looks like −0.48: inflation hides half of the true sensitivity."),
    ("−1.30 / −0.85", "<b>Rises hurt more than cuts help.</b> Pricing above an article's usual level loses volume "
                      "faster than pricing below it gains."),
    ("+12% / −9%", "<b>33,154 real price changes confirm it.</b> A 5–10% cut lifted volume a median 12%; a 5–10% rise "
                   "cut it 9% (vs the rest of the category in the same store)."),
    ("−0.1 to −4.9", "<b>Sensitivity varies 40-fold across sub-categories.</b> Water, pasta, juice, carbonated drinks, "
                     "alcohol, oil, milk and chicken are highly elastic; beef, cheese, body care, ice cream and "
                     "detergents barely react."),
    ("+84%", "<b>Prices tracked inflation.</b> The fixed-basket price index rose 84% (Feb 2023–Aug 2026), level "
             "with CPI. Cattle and dry commodities rose about 130%; dry grocery only 16%."),
    ("51%", f"<b>Half of a devaluation reaches shelf prices within six months.</b> Poultry passes on "
            f"{N['pt_fx6']['POULTRY']:.0f}% and dry commodities all of it; beverages, dairy and personal care almost none."),
    ("+2.7% / −1.26", "<b>Province stores charge more and are the most price-sensitive.</b> Their prices sit 1.6–4.3% "
                      "above the chain while their elasticity (−1.26) is the strongest of any store class."),
    ("+30%", "<b>Payday drives the month.</b> Daily sales from the 25th to the 3rd run about 30% above mid-month; "
             "Saturday is 20% above the weekly average; December is 50% above an average month."),
    ("×2", "<b>Cheap prices double stock-out risk.</b> Articles priced 15% or more below their category run out "
           "next month twice as often as those priced 15% above."),
    ("≈21%", "<b>Estimated gross margin is low for how price-insensitive customers are.</b> A 21% margin is optimal "
             "only at an elasticity near −4.8; almost every "
             "sub-category is less price-sensitive than its margin implies, so careful price increases should add "
             "profit. This needs confirming with purchase costs."),
]
rows = [[Paragraph(a, ST["num"]), Paragraph(b, ST["box"])] for a, b in key]
t = Table(rows, colWidths=[34 * mm, CW - 34 * mm])
t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), .3, RULE),
                       ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                       ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
story.append(t)
story.append(Spacer(1, 8))
P("Priority actions", "h2")
bullets([
    "Raise prices in small steps on low-sensitivity sub-categories (beef, cheese, body care, snacks, ice cream, hot "
    "drinks, detergents, fresh produce), starting with the highest-margin articles.",
    "Keep traffic builders (water, juice, carbonated drinks, pasta, oil, milk, eggs, chicken) sharp; use them for "
    "promotions, timed to payday and December.",
    "Review the province price premium: those stores are the most price-sensitive, so the premium is likely costing volume.",
    "Use stock cover in pricing: overstocked slow movers barely respond to price (−0.54), so clear them with targeted "
    "markdowns rather than blanket cuts; avoid deep cuts on fast movers that are already short of stock.",
    "Link repricing to the exchange rate for imported categories (poultry, cattle, dry commodities) with a defined lag.",
])

# ------------------------------------------------------------------ 2 data
h1("Data, cleaning and method", "s2")
P("All sources were extracted from Fresmart's Azure SQL database or official statistics, cleaned, and linked at month × "
  "location × article, then aggregated to weeks for modelling.")
table(["Source", "Coverage", "Role in the analysis"], [
    ["Sales (daily, by store and article)", "Jan 2023 – Sep 2026 · 46.3M rows", "Volume and actual selling price"],
    ["Article master (database)", "25,853 articles · 8,385 in scope", "Category, unit conversion, status"],
    ["Location master + HORECA", "59 stores, 4 HDDS, HRCA, 9 planned", "Zone, class, size, opening date"],
    ["Stock (opening / closing)", "Jun 2024 – Oct 2026, monthly", "Stock cover, stock-outs, cost estimate"],
    ["List-price change log", "2020 – Oct 2026", "Cross-check only (sparse before 2026)"],
    ["Exchange rate (BNA via IMF)", "Jan 2023 – Aug 2026, monthly", "Pass-through, demand driver"],
    ["Consumer prices (INE via IMF)", "Jan 2023 – Aug 2026 (Sep estimated)", "Inflation adjustment"],
    ["Brent crude (EIA via FRED)", "Jan 2023 – Sep 2026", "Cost driver, demand driver"],
    ["GDP growth (INE quarterly)", "Q1 2023 – Q2 2026", "Demand driver"],
], [.32, .33, .35])
P("Article scope", "h2")
P("An article is in scope if it sold in one of the 64 trading locations and is <b>Active</b> in the database article "
  "master, or is <b>Purchase Blocked / blank status</b> but still sold in the last four months (Jun–Sep 2026): "
  "6,380 + 1,669 + 336 = 8,385 articles.")
P("Cleaning", "h2")
bullets([
    "4.8M sales rows for out-of-scope articles dropped; 13k empty rows removed; 9k returns separated.",
    "51k days with a unit price more than 3× or less than ⅓ of that article-store's normal price flagged and excluded "
    "from price calculations.",
    "All quantities converted to each article's base unit using conversions observed in sales (master used as fallback; "
    "108 master conversions corrected).",
    "Negative stock (≈9.5k) set to zero; 73k breaks between closing and next opening stock flagged.",
    "Prices deflated with CPI (Jan 2023 kwanza) and expressed relative to a leave-one-out sub-category price index.",
])
P("Modelling sample", "h2")
table(["Step", "Weekly rows"], [[r["Step"].strip(), f"{r['Rows']:,.1f}" if r["Rows"] % 1 else f"{r['Rows']:,.0f}"]
                                for r in J["sample"]], [.75, .25], num_cols=(1,))
box("<b>Main model.</b> log(weekly units) = β × log(relative price) + a baseline for every article in every store + a "
    "baseline for every week. β is the elasticity. Standard errors are clustered by article. Article-level estimates "
    "use the same design per article and are shrunk towards their sub-category average according to their precision. "
    "See the appendix for all specifications.")

# ------------------------------------------------------------------ 3 sales
h1("Sales performance", "s3")
P("Kwanza sales roughly tripled over the period, but most of that is inflation and new stores. In real terms the "
  "32 stores that traded throughout grew strongly in 2024 and 2025 and slowed sharply in 2026.")
fig("01_sales_index", "Figure 3.1 · Monthly sales indexed to Jan 2023 = 100. Real = deflated by CPI. Like-for-like = "
                      "32 stores trading in every month.")
table(["Like-for-like stores, Jan–Sep", "2024 vs 2023", "2025 vs 2024", "2026 vs 2025"],
      [["Real sales (inflation-adjusted)", "+25.4%", "+19.8%", "+4.0%"],
       ["Volume (kg, indicative)", "+12.0%", "+27.9%", "+9.4%"]], [.4, .2, .2, .2], num_cols=(1, 2, 3))
fig("02_calendar_heat", "Figure 3.2 · Like-for-like real sales by month. December stands out every year; 2026 is "
                        "running only slightly ahead of 2025.")
fig("06_group_year_volume", "Figure 3.3 · Real sales growth by category for like-for-like stores, Jan–Sep of each year.")
gy = N["group_year"]["2026 vs 2025"]
P(f"Growth has rotated across categories. Cattle and poultry led 2024 (+54% and +43%), dry grocery, dairy and personal "
  f"care led 2025, and in 2026 personal care ({gy['Personal Care']:+.0f}%) and dry commodities "
  f"({gy['Dry-Commodity']:+.0f}%) are still growing while poultry ({gy['Poultry']:+.0f}%) has turned negative.")
P("Concentration", "h2")
c = J["conc"]
P(f"Just {c[0]:.0f}% of articles generate half of sales, {c[1]:.0f}% generate 80% and {c[2]:.0f}% generate 90%. "
  "Pricing decisions on a few hundred articles matter far more than the long tail. Stores account for over 98% of "
  "sales; HDDS reached USD 0.9M in 2025 and HORECA USD 0.6M in Jan–Sep 2026.")

# ------------------------------------------------------------------ 4 calendar
h1("Shopping calendar: seasonality, payday and weekday", "s4")
fig_pair("03_seasonality", "04_day_of_month",
         "Figure 4.1 · Left: month of year (like-for-like real sales, average month = 100). Right: day of month "
         "(each day vs its month's daily average); orange = payday window, 25th–3rd.")
P(f"December is 51% above an average month and January–February are the weakest (12–13% below). Within the month, "
  f"the payday window averages {N['payday_days']:.0f} against {N['mid_days']:.0f} in the middle of the month, "
  "a swing of about 30%.")
fig("05_weekday_heat", "Figure 4.2 · Weekday index by category (each week's average day = 100).")
wd = N["weekday"]
P(f"Saturday is the peak day for every category ({wd['Sat']:.0f}), followed by Friday ({wd['Fri']:.0f}); Monday and "
  f"Tuesday are the quietest ({wd['Mon']:.0f}–{wd['Tue']:.0f}). These patterns are fixed effects of the calendar "
  "and should be used for promotion timing; they do not change the price elasticity.")

# ------------------------------------------------------------------ 5 prices
h1("Prices, inflation and the exchange rate", "s5")
P("The kwanza lost about 40% of its value against the dollar in mid-2023. Fresmart's price index jumped with it and "
  "then rose in step with consumer prices. Since early 2025 the exchange rate has been flat and price increases have slowed.")
fig("10_price_vs_cpi_fx", "Figure 5.1 · Fresmart fixed-basket price index (sales-weighted month-on-month change of the "
                          "same article in the same store) vs CPI and the BNA exchange rate. Feb 2023 = 100.")
fig_pair("16_category_inflation", "15_price_change_freq",
         "Figure 5.2 · Left: cumulative price rise by category. Right: share of article-store months by size of "
         "price move (relative to the previous month).")
P("Price increases have become smaller and rarer: in 2023 a third of article-store months saw a rise above 3%; in 2026 "
  "one in six. Stable prices (±3%) rose from 53% to 72% of months.")
fig("11_category_index_multiples", "Figure 5.3 · Category price indices against CPI. Imported proteins and "
                                   "commodities ran well ahead of inflation; dairy, dry grocery and personal care behind it.")
P("Pass-through from the exchange rate and oil", "h2")
fig("12_passthrough_heat", "Figure 5.4 · Cumulative share of a 1% move in the exchange rate (left) or Brent (right) "
                           "that shows up in each category's prices after 0–6 months. Regression of monthly category "
                           "price change on current and lagged driver changes.")
P(f"Across the chain, {N['pt_fx1']['ALL']:.0f}% of a devaluation reaches prices within a month and "
  f"{N['pt_fx6']['ALL']:.0f}% within six months. Poultry ({N['pt_fx6']['POULTRY']:.0f}%), cattle "
  f"({N['pt_fx6']['CATTLE']:.0f}%) and dry commodities (full pass-through) track the dollar closely, consistent with "
  "imported supply. Beverages, dairy, dry grocery and personal care show little or no pass-through: they are priced on "
  "local costs and competition. Oil matters much less: about "
  f"{N['pt_br6']['ALL']:.0f}% of a Brent move shows up after six months, mainly in dry commodities "
  f"({N['pt_br6']['DRY-COMMODITY']:.0f}%). With about 40 monthly observations, individual category estimates are "
  "indicative; the chain totals and the direction by category are reliable.")

# ------------------------------------------------------------------ 6 macro
h1("The macro-economy and demand", "s6")
fig("13_volume_vs_macro", "Figure 6.1 · Like-for-like volume growth (year on year) against each macro factor, monthly.")
mc = N["macro_corr_vol"]
P(f"Volume growth falls when the kwanza depreciates faster (r = {mc['FX_YoY']:+.2f}) and when oil is expensive "
  f"(r = {mc['Brent_USD']:+.2f}). The negative link with GDP growth (r = {mc['GDP_Real_YoY_Pct_Q']:+.2f}) is "
  "counter-intuitive: GDP is driven by oil output, and Fresmart's strongest volume growth came during weak quarters "
  "in 2024–25 as new stores opened and customers traded towards value retail.")
fig("14_macro_corr", "Figure 6.2 · Correlation matrix of like-for-like sales growth and macro factors.", width=.72)
P("Explicit drivers model", "h2")
P("A second model keeps each article-store baseline but replaces the weekly controls with explicit factors.")
lab = {"ln_Price_Real": ("Real price", "+1%"), "ln_FX": ("Kwanza per USD", "+1% (weaker kwanza)"),
       "Inflation_YoY_Pct": ("Inflation", "+1 point"), "ln_Brent": ("Brent oil price", "+1%"),
       "GDP_Real_YoY_Pct_Q": ("Real GDP growth", "+1 point"), "Holidays_In_Week": ("Public holiday in week", "per holiday"),
       "Payday_Week": ("Payday week (25th–3rd)", "vs other weeks"), "Christmas_Season": ("Christmas (8–31 Dec)", "vs early Dec")}
import math
mn = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
rows = []
for r in J["drivers"]:
    term, est, p = r["Term"], r["Estimate"], r["Pr(>|t|)"]
    ev = "strong" if p < .01 else "moderate" if p < .05 else "not significant"
    if "Month_Of_Year" in term:
        k = int(term.split("T.")[1].rstrip("]"))
        rows.append([f"Month: {mn[k - 1]}", "vs January", pct((math.exp(est) - 1) * 100, 1), ev])
    elif term in lab:
        eff = f"{est:+.2f}%" if term in ("ln_Price_Real", "ln_FX", "ln_Brent") else pct((math.exp(est) - 1) * 100, 1)
        rows.append([*lab[term], eff, ev])
table(["Factor", "Change", "Effect on unit volume", "Evidence"], rows, [.36, .24, .22, .18], num_cols=(2,))
P("Price, payday, Christmas and the July–October slowdown are firm results. The macro coefficients are indicative: "
  "they change only monthly and move together over a short window, so the model cannot cleanly separate them.")

# ------------------------------------------------------------------ 7 stock
h1("Stock and price", "s7")
fig("20_cover_vs_price_move", "Figure 7.1 · Next month's relative price move by this month's stock cover "
                              "(row percentages, Jun 2024 onward).", width=.82)
cut, rise = N["cover_cut"], N["cover_rise"]
P(f"Pricing reacts to stock, but weakly. With more than four months of cover, {cut['>4 mo']:.0f}% of articles are cut "
  f"the next month and {rise['>4 mo']:.0f}% raised; with less than a week of cover, {cut['<1 wk']:.0f}% are cut and "
  f"{rise['<1 wk']:.0f}% raised. Deep cuts (>10%) are {N['cover_cut10']['>4 mo']:.1f}% of overstocked months vs "
  f"{N['cover_cut10']['<1 wk']:.1f}% of tight months. Stock levels are not yet a systematic input to pricing.")
fig("21_oos_by_relprice", "Figure 7.2 · Share of article-stores out of stock next month by how the article is priced "
                          "against its category this month.", width=.82)
o = N["oos_rel"]
P(f"Cheap articles run out more often: {o['<0.85']:.2f}% of articles priced 15%+ below their category are out of stock "
  f"the next month vs {o['>1.15']:.2f}% of those 15%+ above. Price cuts must be planned with replenishment, or the "
  "extra demand is lost to empty shelves.")
sp = {(r["Dimension"], r["Value"]): r for r in N["splits"]}
P("Does stock level change the response to price?", "h2")
P(f"Yes, strongly. Articles with 1–2 weeks of cover respond at {sp[('Stock cover', '1-2 weeks')]['Elasticity']:.2f}, "
  f"those with 1–2 months at {sp[('Stock cover', '1-2 months')]['Elasticity']:.2f}, and those with over two months at "
  f"only {sp[('Stock cover', '>2 months')]['Elasticity']:.2f} (Figure 9.3). Slow movers that accumulate stock are "
  "those customers least respond to on price; blanket markdowns on them recover little volume.")

# ------------------------------------------------------------------ 8 location
h1("Location: price level, mix and sensitivity", "s8")
fig("30_store_premium", "Figure 8.1 · Each store's sales-weighted price for the same article and month, % vs the chain "
                        "median. Colour = zone.")
pz = N["premium_by_zone"]
P(f"Prices are almost uniform across Luanda (within ±2%), but every province store charges more: +1.6% to "
  f"+{N['premium_range'][1]:.1f}% (average {pz['PROVINCE']:+.1f}%), presumably reflecting transport costs. "
  f"Price level has no relationship with store productivity (r = {N['corr_premium_sqm']:+.2f}).")
fig("31_premium_vs_productivity", "Figure 8.2 · Left: price premium vs sales per m². Right: store size vs sales.")
fig("32_zone_group_premium", "Figure 8.3 · Price level by zone and category, % vs chain median for the same article and month.")
fig("35_zone_mix", "Figure 8.4 · Category share of sales by zone (top 10 categories).")
P("Price sensitivity by location", "h2")
fig("36_class_zone_elasticity", "Figure 8.5 · Elasticity by store class and zone (95% intervals). Dashed line = −1.")
lo, hi, s_lo, s_hi = N["store_el_range"]
P(f"Province stores (−1.26) and class C stores are the most price-sensitive; class A city stores the least (−0.96). "
  f"Store-level estimates range from {lo:.2f} ({title(s_lo)}) to {hi:.2f} ({title(s_hi)}). The province stores "
  "therefore combine the highest prices with the most price-sensitive customers.")
fig("34_store_elasticity", "Figure 8.6 · Elasticity by store (95% intervals), coloured by class.")
fig("33_zone_group_elasticity", "Figure 8.7 · Elasticity by zone and category. Darker red = more sensitive. Poultry is "
                                "most sensitive in Province, Golf, Sanzala and Zango; fresh produce is the least sensitive everywhere.")

# ------------------------------------------------------------------ 9 elasticity
h1("Price elasticity", "s9")
P("Elasticity is the % change in units sold for a 1% change in price. Below −1, a price cut grows revenue; between −1 "
  "and 0, a price rise grows revenue.")
fig("40_bias_asym", "Figure 9.1 · Chain elasticity by price measure and asymmetry (95% intervals).", width=.82)
P("On raw kwanza prices the elasticity is −0.48, because prices and volumes both rose for unrelated reasons. Removing "
  "inflation gives −1.03, and comparing each article with its category gives the same −1.03, confirming the result. "
  "Price increases above the usual level (−1.30) cost more volume than cuts below it gain (−0.85).")
fig("41_group_elasticity", "Figure 9.2 · Elasticity by main category (95% intervals).", width=.82)
fig("42_splits", "Figure 9.3 · Elasticity by year (with that year's inflation range), stock cover and price tier.")
P(f"Sensitivity has been stable over time ({sp[('Year', '2023')]['Elasticity']:.2f} to "
  f"{sp[('Year', '2025')]['Elasticity']:.2f}) despite inflation peaking at 31% in 2024. Economy-tier articles are more "
  f"sensitive ({sp[('Price tier', 'Economy')]['Elasticity']:.2f}) than premium ones "
  f"({sp[('Price tier', 'Premium')]['Elasticity']:.2f}). Imported ({sp[('Sourcing', 'Import')]['Elasticity']:.2f}) and "
  f"local ({sp[('Sourcing', 'Local')]['Elasticity']:.2f}) articles respond alike.")
P("Sub-categories", "h2")
table(["Category", "Sub-category", "Articles", "Elasticity", "Sensitivity", "Sales (bn Kz)"],
      [[title(r["MainGroup"]), title(r["SubGroup"]), r["Articles"], f2(r["Weighted_Elasticity"]),
        sens(r["Weighted_Elasticity"]), f"{r['Sales_KZ'] / 1e9:.1f}"] for r in J["subgroup"]],
      [.2, .24, .1, .12, .18, .16], num_cols=(2, 3, 5))
P("Article level", "h2")
names = ["highly elastic (< -2)", "elastic (-2 to -1)", "moderate (-1 to -0.3)", "inelastic (-0.3 to 0)", "positive (check)"]
labels = ["Highly elastic (below −2)", "Elastic (−2 to −1)", "Moderate (−1 to −0.3)", "Inelastic (−0.3 to 0)",
          "Positive (treat with caution)"]
w_, h_ = Image.open(CH / "43_article_hist.png").size
img = RLImage(str(CH / "43_article_hist.png"), width=CW * .48, height=CW * .48 * h_ / w_)
ct = Table([[Paragraph(h, ST["cellb"]) for h in ["Class", "Articles", "Sales"]]] +
           [[Paragraph(l, ST["cell"]), Paragraph(f"{ac[n]['Articles']:,}", ST["cell"]),
             Paragraph(f"{ac[n]['Sales_KZ'] / tot_s * 100:.0f}%", ST["cell"])] for n, l in zip(names, labels)],
           colWidths=[CW * .3, CW * .1, CW * .09])
ct.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), .8, INK2), ("LINEBELOW", (0, 1), (-1, -1), .3, RULE),
                        ("ALIGN", (1, 0), (2, -1), "RIGHT")]))
pair = Table([[img, ct]], colWidths=[CW * .5, CW * .5])
pair.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
story.append(KeepTogether([pair, Paragraph("Figure 9.4 · Distribution of 3,716 article elasticities after shrinkage "
                                           "towards the sub-category average, and sales by sensitivity class.", ST["cap"])]))
P("Top 30 articles by sales", "h2")
table(["Article", "Sub-category", "Stores", "Elasticity", "Sensitivity", "Sales (bn Kz)"],
      [[title(r["ArticleName"])[:44], title(r["SubGroup"]), r["Locations"], f2(r["Elasticity"]), sens(r["Elasticity"]),
        f"{r['Sales_KZ'] / 1e9:.2f}"] for r in J["top_articles"]], [.4, .15, .08, .1, .14, .13], num_cols=(2, 3, 5),
      font=7.4)

# ------------------------------------------------------------------ 10 events
h1("What happened when prices changed", "s10")
P("A direct check that does not depend on the model: every clean step in an article's relative price (at least 5%, "
  "stable for four weeks before and after) and the change in its volume relative to the rest of its sub-category in "
  "the same store over the same weeks.")
fig("50_events", "Figure 10.1 · Left: median volume change by direction and size of price change. Right: median volume "
                 "change across all 33,154 events, in 5-point price bands.")
table(["Change", "Size", "Events", "Median price change", "Median volume change", "Implied elasticity"],
      [[r["Direction"], r["Size"], f"{r['Events']:,}", pct(r["Median_Price_Change_pct"], 1),
        pct(r["Median_Volume_Change_pct"], 1), f2(r["Median_Arc_Elasticity"])] for r in J["events"]],
      [.14, .12, .12, .2, .2, .22], num_cols=(2, 3, 4, 5))
fig("51_events_group_heat", "Figure 10.2 · Median volume change after cuts and rises, by category.", width=.6)
P("The short-run responses (−1.2 to −1.7) are a little stronger than the model's long-run −1.03, as expected in the "
  "first weeks after a change: cuts attract stock-up buying, and rises push customers to substitutes immediately. "
  "Fresh produce and bakery hardly react in either direction; beverages, dry commodities, dairy, poultry and pet food "
  "react most.")

# ------------------------------------------------------------------ 11 margin
h1("Margin and pricing headroom", "s11")
fig("44_margin_vs_elasticity", "Figure 11.1 · Estimated gross margin (from stock value, Jun 2024 onward) against "
                               "sub-category elasticity. The orange curve is the margin at which the current price "
                               "would maximise profit (margin = −1/elasticity).")
P("Standard pricing theory says that at the profit-maximising price, gross margin equals −1/elasticity. Every major "
  "sub-category sits below the curve: its margin is lower than its price sensitivity would justify. On these numbers, "
  "careful price increases would raise profit across most of the range, with most headroom in low-sensitivity, "
  "high-volume groups such as beef (vaca), fresh produce, yogurt, frozen and pork. Highly elastic groups (water, pasta, "
  "juice) are closest to the curve and have the least room.")
box("<b>Caution.</b> Margins here are estimated from stock values at cost and cover only Jun 2024 onward. The "
    "elasticities are short-to-medium run and do not include competitor reactions. Before acting, margins should be "
    "confirmed with purchase costs or the COGS in the sales tables, and increases tested on a subset of stores.")

# ------------------------------------------------------------------ 12 recommendations
h1("Recommendations, limits and next steps", "s12")
P("Pricing recommendations", "h2")
bullets([
    "<b>Regular prices:</b> introduce small, frequent increases (3–5%) on low-sensitivity sub-categories and premium-tier "
    "articles; hold or sharpen prices on the traffic builders.",
    "<b>Promotions:</b> concentrate on highly elastic, high-volume articles (water, juice, carbonated drinks, pasta, oil, "
    "milk, eggs, chicken), timed to payday weeks, Saturdays and December, with stock secured in advance.",
    "<b>Markdowns:</b> for overstocked slow movers, a price cut recovers little volume (−0.54); prefer smaller, "
    "targeted markdowns, bundles or transfers between stores.",
    "<b>Inflation and FX repricing:</b> reprice imported categories (poultry, cattle, dry commodities) against the BNA "
    "rate with a 1–3 month lag; reprice local categories against CPI and competition.",
    "<b>Location:</b> test removing part of the province premium on the most sensitive categories (poultry, beverages, "
    "dairy), and use store-class elasticities when setting zone prices.",
])
P("Limits", "h2")
bullets([
    "No purchase-cost data yet; margins are estimates from stock value (Jun 2024 onward).",
    "No promotion calendar: promotional and regular price changes are measured together.",
    "No competitor prices; part of the response reflects competitors' pricing.",
    "Elasticities are each article against its category; switching between substitute articles is not yet modelled.",
    "HORECA has too little history (from Sep 2025) for its own estimate.",
    "477 articles have a positive estimate, mostly noise from small price movements; they are shrunk towards their "
    "category and should not drive decisions alone.",
    "Macro effects are indicative: they vary only monthly over a 45-month window.",
])
P("Next steps", "h2")
bullets([
    "Add purchase costs (or extract COGS for the full history) and confirm margins.",
    "Build the price-optimization engine: recommended price per article and store class within guardrails "
    "(maximum step, price-ending rules, competitor bounds).",
    "Add the promotion calendar to separate promotional lift from regular price response.",
    "Pilot the recommendations in a test-and-control group of stores before chain roll-out.",
])

# ------------------------------------------------------------------ appendix
story.append(PageBreak())
story.append(Paragraph("Appendix", ST["kicker"]))
P("Model specifications and glossary", "h1")
table(["Model", "Specification", "Result"], [
    ["M0", "log units ~ log nominal price | article-store", "−0.48 (biased)"],
    ["M1", "log units ~ log real price | article-store + week", "−1.03"],
    ["M2 (headline)", "log units ~ log relative price | article-store + week", "−1.03"],
    ["M3", "M2 with separate slopes above / below usual price", "−1.30 / −0.85"],
    ["M4", "M2 by category, sub-category, store class, zone, channel, year, stock cover, tier", "Sections 8–9"],
    ["M5", "log units ~ log real price + log FX + inflation + log Brent + GDP + holidays + payday + Christmas + "
           "month | article-store; SE clustered by week", "Section 6"],
    ["Article", "Per article: two-way within (store, week); empirical-Bayes shrinkage to sub-category mean", "3,716 articles"],
    ["Events", "Relative price steps ≥5%, stable ±4 weeks; volume vs sub-category, same store", "33,154 events"],
    ["Pass-through", "Monthly category price change on FX / Brent change, lags 0–6", "Section 5"],
], [.14, .62, .24])
table(["Term", "Meaning"], [
    ["Elasticity", "% change in units sold for a 1% change in price."],
    ["Relative price", "Article's price ÷ the sales-weighted price index of the other articles in its sub-category, "
                       "same store and week."],
    ["Real price", "Price deflated by Angola CPI to January 2023 kwanza."],
    ["Like-for-like", "The 32 stores that traded in every month of the period."],
    ["Stock cover", "Closing stock ÷ average daily sales in the month, in days."],
    ["Pass-through", "Share of a % change in a cost driver that appears in shelf prices."],
    ["Base unit", "Each article's smallest selling unit (piece or kg), used to compare prices across pack sizes."],
], [.2, .8])
P("Files", "h2")
P("Scripts in <font name='Body-Bold'>scripts/</font>: extract_price_stock.py, extract_sales.py, build_article_list.py, "
  "build_macro.py, clean_and_link.py, add_price_indices.py, build_weekly_model_set.py, eda.py, elasticity.py, "
  "deep_analysis.py, report_charts.py, build_pdf_report.py. Results in <font name='Body-Bold'>analysis/</font> "
  "(eda_tables.xlsx, elasticity_results.xlsx, article_elasticity.parquet, price_events.parquet, deep/).")

story = [s for s in story if s is not None]
doc.build(story)
print("written", OUTF)
