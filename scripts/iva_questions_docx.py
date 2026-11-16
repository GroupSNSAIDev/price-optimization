"""Word: IVA questions for finance and the business (plain language, with answer boxes).

Output: output/Business_Questions/Fresmart_IVA_Questions_for_Finance.docx
"""
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "Business_Questions"
LOGO = ROOT / "poultry_ban" / "assets" / "newaco_logo.png"
PURPLE, GOLD, GREY, INK = RGBColor(0x3B, 0x0A, 0x45), RGBColor(0xA0, 0x87, 0x00), RGBColor(0x6B, 0x6B, 0x6B), RGBColor(0x1A, 0x1A, 0x1A)
TINT, LINE = "F4F0F5", "D9D2DB"


def shade(cell, hex_fill):
    tc = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hex_fill)
    tc.append(sh)


def borders(table, color=LINE):
    tbl = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:color"), color)
        b.append(e)
    tbl.append(b)


def rule(doc, color="A08700"):
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"), "single"); bot.set(qn("w:sz"), "8"); bot.set(qn("w:color"), color)
    bdr.append(bot); pPr.append(bdr)
    p.paragraph_format.space_after = Pt(6)


def para(doc, text, size=10.5, bold=False, color=INK, after=6, italic=False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.size, r.bold, r.italic = Pt(size), bold, italic
    r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(after)
    return p


def rich(doc, parts, size=10.5, after=6):
    """parts: list of (text, bold)"""
    p = doc.add_paragraph()
    for t, b in parts:
        r = p.add_run(t)
        r.font.size, r.bold = Pt(size), b
        r.font.color.rgb = INK
    p.paragraph_format.space_after = Pt(after)
    return p


def heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for r in h.runs:
        r.font.color.rgb = PURPLE if level == 1 else GOLD
        r.font.name = "Arial"
        r.font.size = Pt(15 if level == 1 else 11.5)
    h.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    h.paragraph_format.space_after = Pt(4)
    h.paragraph_format.keep_with_next = True
    return h


def table(doc, rows, widths_cm, header=True, answer_col=None):
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    borders(t)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = t.cell(i, j)
            c.width = Cm(widths_cm[j])
            c.text = ""
            p = c.paragraphs[0]
            r = p.add_run(str(val))
            r.font.size = Pt(9.5)
            if header and i == 0:
                r.bold = True
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                shade(c, "3B0A45")
            else:
                r.font.color.rgb = INK
                if j == 0:
                    r.bold = True
                if answer_col is not None and j == answer_col:
                    shade(c, "FFFFFF")
                elif i % 2 == 0:
                    shade(c, TINT)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.keep_with_next = i < len(rows) - 1   # keep the table on one page
    for j, w in enumerate(widths_cm):
        for c in t.columns[j].cells:
            c.width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def callout(doc, text):
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.cell(0, 0)
    c.width = Cm(16.5)
    shade(c, TINT)
    tc = c._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single"); left.set(qn("w:sz"), "24"); left.set(qn("w:color"), "A08700")
    b.append(left); tc.append(b)
    c.text = ""
    r = c.paragraphs[0].add_run(text)
    r.font.size = Pt(10)
    r.font.color.rgb = INK
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def questions(doc, qs):
    rows = [["#", "Question", "Your answer"]] + [[str(i), q, ""] for i, q in enumerate(qs, 1)]
    t = table(doc, rows, [0.9, 9.6, 6.0], answer_col=2)
    for i in range(1, len(rows)):
        t.rows[i].height = Cm(1.6)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(1.8)
    st = doc.styles["Normal"]
    st.font.name = "Arial"
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    st.font.size = Pt(10.5)

    # footer
    fp = sec.footer.paragraphs[0]
    fr = fp.add_run("Fresmart price optimisation · IVA questions for finance and the business · November 2026 · Confidential")
    fr.font.size, fr.font.color.rgb = Pt(8), GREY

    # title block
    if LOGO.exists():
        doc.add_picture(str(LOGO), width=Cm(2.6))
    para(doc, "FRESMART PRICE OPTIMISATION", 9, True, GOLD, 2)
    para(doc, "Questions for finance about IVA in our sales data", 20, True, PURPLE, 4)
    para(doc, "Two short topics. Plain language. Please write your answers in the boxes.", 11, False, GREY, 4)
    rule(doc)
    table(doc, [["Prepared for", "Prepared by", "Date", "Please reply by"],
                ["Finance team, Commercial director, IT (topic 2)", "Price optimisation team", "16 November 2026", "____________"]],
          [5.2, 4.2, 3.4, 3.7])

    heading(doc, "Why we are asking")
    para(doc, "We are setting new shelf prices for all active Fresmart articles. To do that, we must know the real profit on each "
              "article. While checking the sales data we found two things about IVA (sales tax) that only finance can confirm. "
              "Your answers change the profit numbers, so we need them before the new prices are approved.")
    table(doc, [["#", "Topic", "Who should answer", "Why it matters"],
                ["1", "Sales figures include IVA", "Finance", "Changes every profit number"],
                ["2", "Articles with 14% IVA sell below the system price", "Finance + IT", "About $30M of sales, mainly beverages"]],
          [0.9, 6.3, 3.5, 5.8])
    callout(doc, "Figures in this note: last 52 weeks to 8 Nov 2026, Fresmart stores and wholesale, active articles, in US dollars.")

    # ---- topic 1
    heading(doc, "Topic 1. Sales figures include IVA")
    heading(doc, "What we found", 2)
    rich(doc, [("The sales value in the data ", False), ("already includes IVA", True),
               (", the tax Fresmart collects for the government. The data also shows the tax amount separately. "
                "The profit figure in the data is simply sales minus cost, so ", False),
               ("the tax is counted as if it were Fresmart's profit.", True)])
    para(doc, "When we take the tax out, the real margin is much lower:")
    table(doc, [["Period", "Margin as reported (with IVA)", "Real margin (without IVA)"],
                ["2024", "20.8%", "14.3%"], ["2025", "19.3%", "12.3%"], ["2026 (to Nov)", "20.7%", "13.9%"],
                ["Last 52 weeks, active articles", "20.3%", "13.4%"]], [6.0, 5.2, 5.3])
    heading(doc, "What it changes", 2)
    table(doc, [["", "With IVA counted as profit", "Without IVA"],
                ["Articles sold below cost", "194", "309"],
                ["Articles earning less than 5%", "232", "536"]], [6.0, 5.2, 5.3])
    para(doc, "Until finance tells us otherwise, we calculate profit as: sales minus IVA minus cost.", 10.5, True)
    heading(doc, "Questions", 2)
    questions(doc, [
        "Does the sales value in our reports (\"Gross sales\" / \"Net sales\") include IVA? Our check says yes. Is that right?",
        "Is the tax amount in the sales data (\"Tax\") the IVA that Fresmart actually pays to the government?",
        "Are purchase costs (\"COGS\") recorded without IVA, because IVA on purchases is claimed back?",
        "Which margin does management use today in reports and targets: with IVA or without IVA?",
        "Do you agree that new prices should be based on the margin without IVA (sales minus IVA minus cost)?",
        "Are there supplier rebates or bonuses paid outside the invoice? If yes, in which report or table are they? They raise "
        "the real margin.",
    ])

    # ---- topic 2
    doc.add_page_break()
    heading(doc, "Topic 2. Articles with 14% IVA sell below the system price")
    heading(doc, "What we found", 2)
    rich(doc, [("For articles with ", False), ("5% IVA", True),
               (", the price customers pay matches the shelf price in the system. For articles with ", False), ("14% IVA", True),
               (" (mostly beverages, but also sausages, charcuterie, personal care and household), customers pay about ", False),
               ("9% less", True), (" than the system shelf price, every week, in almost every store.", False)])
    table(doc, [["", "Value"],
                ["Sales of 14% IVA articles per year", "About $30 million (beverages about $10 million)"],
                ["Beverages: real margin (without IVA)", "5.0%"],
                ["Beverages: share of sales sold below cost", "28.8%"],
                ["Articles flagged in the new price list for this gap", "657 (selling price differs from system price)"]],
          [8.0, 8.5])
    heading(doc, "Why it matters", 2)
    para(doc, "If the tax rate or the price in the data is wrong, the margin of these articles is wrong, and so is the price we "
              "recommend. Beverages look like they lose money on more than a quarter of their sales. That may be true, or it may "
              "be a data problem. For now we use the tax exactly as recorded.")
    heading(doc, "Three examples to check together", 2)
    table(doc, [["Code", "Article"],
                ["100293", "Cuca beer 24 x 330 ml"],
                ["117024", "Sanodia chicken sausage 24 x 340 g"],
                ["113637", "Chourico Corrente da Nossa Terra 20 x 140 g"]], [3.0, 13.5])
    heading(doc, "Questions", 2)
    questions(doc, [
        "Which IVA rate applies to beverages and the other 14% articles? Is 14% correct?",
        "Is the shelf price shown in the system for these articles the price with IVA or without IVA?",
        "Is there a reason customers pay about 9% less than the system price? For example a standing discount, a different tax "
        "at the till, or prices loaded differently in the POS.",
        "Who in IT or finance can check the three examples above with us, and when?",
    ])

    heading(doc, "What happens next")
    for t in ["You send the answers (in this document, by e-mail, or in a 30-minute meeting).",
              "We update all profit numbers and the price list with your answers, and show you what changed.",
              "The new prices go for approval only after these two topics are closed."]:
        p = doc.add_paragraph(style="List Number")
        r = p.add_run(t)
        r.font.size = Pt(10.5)
    para(doc, "Thank you. Contact: price optimisation team.", 10, False, GREY, 0, True)

    path = OUT / "Fresmart_IVA_Questions_for_Finance.docx"
    doc.save(path)
    print(path)


if __name__ == "__main__":
    main()
