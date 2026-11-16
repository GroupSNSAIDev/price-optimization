"""Word: one file with every open question for the business and finance teams (questions only, numbered, answer boxes).

Output: output/Business_Questions/Fresmart_Questions_for_Business_and_Finance.docx
"""
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from iva_questions_docx import GREY, INK, LOGO, OUT, PURPLE, TINT, borders, para, shade

Q = [
    ("Does the sales value in our sales data (\"Gross sales\" / \"Net sales\") include IVA?", "Finance"),
    ("Is the \"Tax\" amount in the sales data the IVA that Fresmart pays to the government?", "Finance"),
    ("Are purchase costs (\"COGS\") recorded without IVA, because IVA on purchases is claimed back?", "Finance"),
    ("Which margin does management use today in reports and targets: with IVA or without IVA?", "Finance"),
    ("Do you agree that new prices should be based on the margin without IVA (sales minus IVA minus cost)?", "Finance"),
    ("Are there supplier rebates or bonuses paid outside the invoice? If yes, in which report or table are they recorded?", "Finance"),
    ("Which IVA rate applies to beverages and the other articles we see at 14%? Is 14% correct?", "Finance"),
    ("For articles with 14% IVA, is the shelf price in the system the price with IVA or without IVA?", "Finance + IT"),
    ("For articles with 14% IVA, customers pay about 9% less than the system shelf price, in almost every store. What is the "
     "reason (for example a standing discount, a different tax at the till, or prices loaded differently in the POS)?", "Finance + IT"),
    ("Who can check three examples with us, and when: Cuca beer 24 x 330 ml (100293), Sanodia chicken sausage 24 x 340 g "
     "(117024) and Chourico Corrente da Nossa Terra 20 x 140 g (113637)?", "Finance + IT"),
    ("We see 112 everyday articles that customers buy very often (for example soy oil, Patriota rice, Soph chicken legs, Cuca "
     "beer), 26% of sales. Do you agree with this list? Should any be added or removed?", "Business"),
    ("What should happen to the prices of these everyday articles: (a) no change, (b) small moves only, or (c) treat them like "
     "every other article?", "Business"),
    ("Should all brands of the same product move together (for example all soy oils), so customers do not just switch brand?", "Business"),
    ("Who approves price changes on these everyday articles?", "Business"),
    ("Who is the sponsor of the price project (the person who signs the final price plan)?", "Business"),
    ("Who is the pricing owner who runs the price changes week to week?", "Business"),
    ("Who in finance confirms the expected and the actual profit gain?", "Finance"),
    ("Is there a profit target for the year (for example +X% gross profit)?", "Business + Finance"),
    ("What is the most the average customer basket may rise in one step (for example no more than 3 months of inflation at once)?", "Business"),
    ("How many shelf labels can one store change in one week?", "Business"),
    ("Do you agree that some stores keep today's prices for 4 to 8 weeks, so we can measure the real profit gain against them?", "Business"),
    ("Wholesale stores HDDS, HDS2 and HDS4 have had no sales since October. Are they closed or paused?", "Business"),
    ("Store FE45 has no sales in November. Is it closed?", "Business"),
    ("Five articles are no longer active: Fundo cheese slices, Delta Q Qharisma, Nestum Maria and two Friboi beef trays. "
     "Are they being discontinued?", "Business"),
    ("Delta Q Qonvictus capsules are selling at about 45% below their usual price. Is this a planned clearance?", "Business"),
    ("Can we get supplier invoice prices (purchase price per unit, by date) for the last 2 years?", "Finance"),
    ("Is there a promotion calendar (which articles, which dates, what discount)? Can we get it?", "Business"),
    ("Do you collect competitor prices for everyday articles? If yes, can we get them?", "Business"),
    ("Are any articles under government price control or a regulated basic basket? If yes, which ones and with what limits?",
     "Business + Finance"),
]


def main():
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(1.8)
    st = doc.styles["Normal"]
    st.font.name = "Arial"
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    st.font.size = Pt(10.5)
    fr = sec.footer.paragraphs[0].add_run("Fresmart price optimisation · questions for business and finance · November 2026 · Confidential")
    fr.font.size, fr.font.color.rgb = Pt(8), GREY

    if LOGO.exists():
        doc.add_picture(str(LOGO), width=Cm(2.4))
    para(doc, "Fresmart price optimisation: questions for business and finance", 17, True, PURPLE, 10)

    widths = [1.0, 9.4, 2.6, 4.0]
    t = doc.add_table(rows=len(Q) + 1, cols=4)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    borders(t)
    for j, h in enumerate(["#", "Question", "For", "Answer"]):
        c = t.cell(0, j)
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size, r.font.color.rgb = True, Pt(10), RGBColor(0xFF, 0xFF, 0xFF)
        shade(c, "3B0A45")
    t.rows[0].repeat_header = True
    tr = t.rows[0]._tr.get_or_add_trPr()
    from docx.oxml import OxmlElement
    hdr = OxmlElement("w:tblHeader"); hdr.set(qn("w:val"), "true"); tr.append(hdr)
    for i, (q, who) in enumerate(Q, 1):
        row = t.rows[i]
        row.height = Cm(1.5)
        cant = OxmlElement("w:cantSplit"); cant.set(qn("w:val"), "true"); row._tr.get_or_add_trPr().append(cant)
        for j, val in enumerate([str(i), q, who, ""]):
            c = t.cell(i, j)
            c.text = ""
            r = c.paragraphs[0].add_run(val)
            r.font.size = Pt(10)
            r.font.color.rgb = PURPLE if j == 0 else INK
            r.bold = j == 0
            if j < 3 and i % 2 == 0:
                shade(c, TINT)
    for j, w in enumerate(widths):
        for c in t.columns[j].cells:
            c.width = Cm(w)

    path = OUT / "Fresmart_Questions_for_Business_and_Finance.docx"
    doc.save(path)
    print(path, len(Q), "questions")


if __name__ == "__main__":
    main()
