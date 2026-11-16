"""PDF: questions for the business before the all-SKU price plan is finalised (plain language).

Output: output/Business_Questions/Fresmart_Pricing_Questions_for_the_Business.pdf
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "Business_Questions"
LOGO = ROOT / "poultry_ban" / "assets" / "newaco_logo.png"
PURPLE, GOLD, INK, GREY, TINT = (colors.HexColor(x) for x in ["#3B0A45", "#A08700", "#1A1A1A", "#6B6B6B", "#F4F0F5"])

S = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=PURPLE),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=11.5, leading=16, textColor=GREY),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=PURPLE, spaceBefore=4, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=GOLD, spaceBefore=8, spaceAfter=3),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK, alignment=TA_LEFT),
    "q": ParagraphStyle("q", fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK, leftIndent=16, firstLineIndent=-16, spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=GREY),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=12, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white),
}


def box(text):
    t = Table([[Paragraph(text, S["body"])]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("LINEBEFORE", (0, 0), (0, -1), 3, GOLD),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def table(rows, widths):
    data = [[Paragraph(c, S["cellb"]) for c in rows[0]]] + [[Paragraph(c, S["cell"]) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PURPLE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TINT]),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D9D2DB")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def questions(items, start=1):
    return [Paragraph(f"<b>{i}.</b>&nbsp;&nbsp;{q}", S["q"]) for i, q in enumerate(items, start)]


def section(n, title, found, why, qs, need, extra=None, qstart=1):
    out = [Paragraph(f"{n}. {title}", S["h1"]),
           Paragraph("What we found", S["h2"]), box(found)]
    if extra is not None:
        out += [Spacer(1, 6), extra]
    out += [Paragraph("Why it matters", S["h2"]), Paragraph(why, S["body"])]
    out += [Paragraph("Questions for the business", S["h2"])] + questions(qs, qstart)
    out += [Paragraph("What we need back", S["h2"]), Paragraph(need, S["body"]), Spacer(1, 10)]
    return out


def on_page(c, doc):
    c.saveState()
    c.setStrokeColor(GOLD); c.setLineWidth(1)
    c.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    c.setFont("Helvetica", 8); c.setFillColor(GREY)
    c.drawString(20 * mm, 10.5 * mm, "Fresmart price optimisation · questions for the business · November 2026")
    c.drawRightString(190 * mm, 10.5 * mm, f"Page {doc.page}")
    c.restoreState()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT / "Fresmart_Pricing_Questions_for_the_Business.pdf"), pagesize=A4, leftMargin=20 * mm,
                            rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=22 * mm,
                            title="Fresmart pricing: questions for the business", author="Price optimisation team")
    st = []
    if LOGO.exists():
        st += [Image(str(LOGO), width=38 * mm, height=38 * mm * 0.32, hAlign="LEFT", kind="proportional"), Spacer(1, 10)]
    st += [Paragraph("Fresmart price optimisation", S["sub"]),
           Paragraph("Questions for the business before we finalise the new prices", S["title"]), Spacer(1, 8),
           Paragraph("We are building new shelf prices for all 3,812 active Fresmart articles. While checking the data we found a "
                     "few things only the business can confirm or decide. This note explains each one in plain language and lists "
                     "the questions we need answered. The work continues in the meantime; the answers change the final numbers, not "
                     "the method.", S["body"]), Spacer(1, 8),
           table([["#", "Topic", "Who should answer", "Urgency"],
                  ["1", "Sales figures include IVA (sales tax)", "Finance", "High: changes every profit number"],
                  ["2", "Articles with 14% IVA sell below the system price", "Finance + IT", "High: mainly beverages"],
                  ["3", "Everyday price-watched products (KVIs)", "Commercial director + pricing", "High: 26% of sales"],
                  ["4", "Project owner, targets and limits", "Management", "Medium"],
                  ["5", "Stores and articles that changed status", "Operations + category", "Medium"]], [8, 70, 50, 42]),
           Spacer(1, 6), Paragraph("Figures: last 52 weeks to 8 Nov 2026, Fresmart stores and wholesale (HDDS), active articles, US dollars.", S["small"]),
           Spacer(1, 14), box("<b>Next step:</b> please send the answers by e-mail or in a short meeting. We continue the work in parallel and "
                              "update the numbers as soon as the answers arrive."),
           PageBreak()]

    # 1 IVA
    st += section(
        1, "Sales figures include IVA (sales tax)",
        "In the sales data, the <b>sales value already includes IVA</b>, the tax collected for the government. The system also "
        "records the tax amount separately. The profit figure in the data is <b>sales minus cost</b>, so <b>the tax is counted as if it "
        "were Fresmart's profit</b>. When we take the tax out, the real margin is much lower:",
        "Prices are set to earn a margin. If the margin we start from is too high, we would think many articles are healthy when they "
        "are not. After removing IVA, <b>309 articles sell below cost</b> (we thought 194) and <b>536 earn less than 5%</b> (we thought 232). "
        "From now on we calculate profit as <b>sales minus IVA minus cost</b>, unless finance tells us otherwise.",
        ["Does the sales value in the reports (\"Gross sales\" / \"Net sales\") include IVA? Our check says yes. Please confirm.",
         "Is the tax amount in the sales data (\"Tax\") the IVA that Fresmart actually pays to the government?",
         "Are purchase costs (\"COGS\") recorded <b>without</b> IVA (because IVA on purchases is claimed back)?",
         "Which margin does management use today in its reports and targets: with IVA or without IVA?",
         "Do you agree that the price plan should use the margin <b>without IVA</b> (sales minus tax minus cost)?",
         "Are there supplier rebates or bonuses paid outside the invoice? If yes, where are they recorded? They raise the true margin."],
        "A yes / no on questions 1-5 from finance, and the name of the report or table for rebates (question 6).",
        extra=table([["", "Margin as reported (with IVA)", "Real margin (without IVA)"],
                     ["2024", "20.8%", "14.3%"], ["2025", "19.3%", "12.3%"], ["2026 (to Nov)", "20.7%", "13.9%"],
                     ["Last 52 weeks, active articles", "20.3%", "13.4%"]], [60, 55, 55]))

    # 2 14% IVA
    st += [PageBreak()] + section(
        2, "Articles with 14% IVA sell below the system price",
        "For articles with <b>5% IVA</b>, the price customers pay matches the shelf price in the system. For articles with <b>14% IVA</b> "
        "(mostly beverages, but also sausages, charcuterie, personal care and household), customers pay about <b>9% less</b> than the "
        "system shelf price including IVA, every week, in almost every store.",
        "These articles are worth about <b>$30 million</b> a year, led by beverages ($10 million). If the tax or the price in the data is "
        "wrong, their margin is wrong, and so is the price we recommend. For now we use the tax as recorded.",
        ["Which IVA rate applies to beverages and the other 14% articles? Is 14% correct?",
         "Is the shelf price shown in the system for these articles the price <b>with</b> IVA or <b>without</b> IVA?",
         "Is there a reason customers pay about 9% less than the system price (for example a standing discount, a different tax "
         "treatment at the till, or prices loaded differently in the POS)?",
         "Who in IT or finance can check three examples with us: Cuca beer 24x330ml (code 100293), Sanodia chicken sausage 24x340g "
         "(117024) and Chourico Corrente da Nossa Terra 20x140g (113637)?"],
        "An explanation from finance or IT, and the correct IVA rate and shelf price basis for 14% articles.")

    # 3 KVIs
    st += section(
        3, "Everyday price-watched products (KVIs)",
        "<b>112 articles</b> are bought very often and in almost every store, for example soy oil (Boa Vista, Primavera, Sanodia, Fula), "
        "Patriota rice, Soph chicken legs, Cuca beer and chicken sausages. Together they make <b>26% of sales</b>. Customers remember "
        "these prices, so they shape how expensive Fresmart feels. They are also the most price-sensitive and earn only about 9% margin.",
        "In the earlier 40-article test we did not change KVI prices at all. Keeping that rule for all articles means a quarter of "
        "sales is left out of the price plan. We will show both options: KVIs held, and KVIs allowed to move within limits.",
        ["Do you agree with this list of 112 everyday articles? Should any be added or removed?",
         "What should happen to their prices: (a) no change, (b) small moves only (for example at most 3% fewer units sold), "
         "or (c) treat them like every other article?",
         "Should all brands of the same product move together (for example all soy oils), so customers do not just switch brand?",
         "Who approves price changes on these articles?"],
        "A choice of (a), (b) or (c), any changes to the list, and the name of the approver.")

    # 4 charter
    st += [PageBreak()] + section(
        4, "Project owner, targets and limits",
        "To finish the plan we need a few decisions that only management can take. Today's starting point is <b>$104.9 million</b> "
        "sales (without IVA) and <b>$14.1 million</b> gross profit on active articles over the last 52 weeks.",
        "These decide how far prices can move and who signs off. Without them the plan uses the limits of the earlier test.",
        ["Who is the <b>sponsor</b> of the price project (the person who signs the final plan)?",
         "Who is the <b>pricing owner</b> who runs the price changes week to week?",
         "Who in <b>finance</b> confirms the expected and the actual profit gain?",
         "Is there a <b>profit target</b> for the year (for example +X% gross profit)?",
         "What is the most the average customer basket may rise in one step? We suggest stating it in months of inflation "
         "(for example \"no more than 3 months of inflation at once\").",
         "How many shelf labels can a store change in one week? This decides how many waves we need."],
        "Names for 1-3, and numbers (or \"no limit\") for 4-6.")

    # 5 status
    st += section(
        5, "Stores and articles that changed status",
        "The latest data (to 12 Nov 2026) shows changes we cannot explain from the data alone.",
        "We do not want to set prices for a store that is closed, or for articles that are being phased out.",
        ["Wholesale stores <b>HDDS, HDS2 and HDS4</b> have had no sales since October. Are they closed or paused?",
         "Store <b>FE45</b> has no sales in November. Is it closed?",
         "Five articles from the earlier test are no longer active: Fundo cheese slices, Delta Q Qharisma, Nestum Maria (purchase "
         "blocked) and two Friboi beef trays (no status). Are they being discontinued?",
         "Delta Q Qonvictus capsules are being sold at about 45% below their usual price. Is this a planned clearance?"],
        "A short yes / no with the reason for each.")

    doc.build(st, onFirstPage=on_page, onLaterPages=on_page)
    print(OUT / "Fresmart_Pricing_Questions_for_the_Business.pdf")


if __name__ == "__main__":
    main()
