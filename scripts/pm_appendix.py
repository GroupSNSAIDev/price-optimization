"""Full-list appendix for the Profit & Margin report, merged after the existing report into a NEW file.

The existing report (output/Profit_Margin_Report/Fresmart_Profit_and_Margin_Report.pdf) is read, never modified.
Output: output/Profit_Margin_Report/Fresmart_Profit_and_Margin_Report_with_Full_Appendix.pdf

  A1 every main group      A2 every sub-group      A3 every loss-making article (L12M)
  A4 every article whose margin fell (L12M vs prior 12M)
"""
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, LongTable, PageBreak, PageTemplate, Paragraph, Spacer,
                                TableStyle)

from rda_analysis import CL, L12, OUT, P12, fin, load_panel

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "output" / "Profit_Margin_Report" / "Fresmart_Profit_and_Margin_Report.pdf"
OUTF = BASE.with_name("Fresmart_Profit_and_Margin_Report_with_Full_Appendix.pdf")

F = "C:/Windows/Fonts/"
for name, file in [("Body", "segoeui.ttf"), ("Body-Bold", "segoeuib.ttf"), ("Head", "georgiab.ttf")]:
    pdfmetrics.registerFont(TTFont(name, F + file))
INK, INK2, MUTED, RULE = (colors.HexColor(c) for c in ("#15201b", "#4d5751", "#7f8781", "#dfe3de"))
ACC, NEGBG = colors.HexColor("#0f6b55"), colors.HexColor("#fbeaea")
W, H = A4
M = 14 * mm
CW = W - 2 * M
ST = {"h1": ParagraphStyle("h1", fontName="Head", fontSize=17, leading=22, textColor=INK, spaceAfter=5),
      "kicker": ParagraphStyle("k", fontName="Body-Bold", fontSize=8, leading=10, textColor=ACC, spaceAfter=2),
      "body": ParagraphStyle("b", fontName="Body", fontSize=8.6, leading=12, textColor=INK, spaceAfter=6),
      "cell": ParagraphStyle("c", fontName="Body", fontSize=6.5, leading=8, textColor=INK),
      "cellb": ParagraphStyle("cb", fontName="Body-Bold", fontSize=6.5, leading=8, textColor=INK2)}
title = lambda s: str(s).title().replace("Fnv", "FNV")
mk = lambda v: "–" if pd.isna(v) else f"{v / 1e6:,.2f}"
pc = lambda v: "–" if pd.isna(v) else f"{v:.1f}%"
pp = lambda v: "–" if pd.isna(v) else f"{v:+.1f}"
code = lambda c: str(c).lstrip("0")


# ------------------------------------------------------------------ data
def build_data():
    p = load_panel()
    s = p[p.Has_Sales]
    names = s.drop_duplicates("ArticleCode").set_index("ArticleCode")[["ArticleName", "MainGroup", "SubGroup"]]

    per = {}
    for k, months in [("L12", L12), ("P12", P12)]:
        x = s[s.Month.isin(months)]
        per[k] = {lvl: fin(x.groupby(keys)[["Net_KZ", "COGS_KZ"]].sum()) for lvl, keys in
                  [("mg", ["MainGroup"]), ("sg", ["MainGroup", "SubGroup"]), ("art", ["ArticleCode"])]}
    l12 = s[s.Month.isin(L12)]
    per["L12"]["art"]["Stores"] = l12.groupby("ArticleCode").Plant.nunique()
    per["L12"]["art"]["Units"] = l12.groupby("ArticleCode").Qty_Base.sum()

    # below-cost losses L12M per article (daily rows where COGS > 1.5x sales)
    parts = []
    for f in sorted((CL / "sales_daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["Month", "ArticleCode", "Sales_KZ", "KZ_COGS", "Below_Cost_50"])
        if d.Month.iloc[0] in L12:
            d = d[d.Below_Cost_50]
            parts.append((d.Sales_KZ - d.KZ_COGS).groupby(d.ArticleCode).sum())
    bc = pd.concat(parts).groupby(level=0).sum().rename("BelowCost_Loss_KZ")

    a = per["L12"]["art"].join(names).join(bc)
    loss = a[a.GP_KZ < 0].sort_values("GP_KZ")

    c = per["L12"]["art"][["Net_KZ", "GP_KZ", "Margin_Pct"]].join(
        per["P12"]["art"][["Net_KZ", "Margin_Pct"]], rsuffix="_P12", how="inner")
    c = c[(c.Net_KZ > 0) & (c.Net_KZ_P12 > 0)]
    c["Change_pp"] = c.Margin_Pct - c.Margin_Pct_P12
    c["GP_Lost_KZ"] = -c.Change_pp / 100 * c.Net_KZ
    fall = c[c.Change_pp < 0].join(names).sort_values("GP_Lost_KZ", ascending=False)

    def level(lvl, keys):
        x = per["L12"][lvl].join(per["P12"][lvl][["Margin_Pct"]], rsuffix="_P12")
        x["Change_pp"] = x.Margin_Pct - x.Margin_Pct_P12
        x["GP_Effect_KZ"] = x.Change_pp / 100 * x.Net_KZ
        x["Loss_Articles"] = loss.groupby(keys).size()
        x["Loss_KZ"] = loss.groupby(keys).GP_KZ.sum()
        x["Falling_Articles"] = fall.groupby(keys).size()
        x["Falling_GP_Lost_KZ"] = fall.groupby(keys).GP_Lost_KZ.sum()
        x["BelowCost_Loss_KZ"] = a.groupby(keys).BelowCost_Loss_KZ.sum()
        x = x[x.Net_KZ > 0].fillna({"Loss_Articles": 0, "Falling_Articles": 0})
        return x.sort_values("GP_KZ", ascending=False).reset_index()

    return level("mg", ["MainGroup"]), level("sg", ["MainGroup", "SubGroup"]), loss.reset_index(), fall.reset_index()


# ------------------------------------------------------------------ pdf
def table(head, rows, widths, num_from, neg_col=None):
    data = [[Paragraph(h, ST["cellb"]) for h in head]] + [[Paragraph(str(v), ST["cell"]) for v in r] for r in rows]
    t = LongTable(data, colWidths=[CW * w for w in widths], repeatRows=1)
    st = [("LINEBELOW", (0, 0), (-1, 0), .8, INK2), ("LINEBELOW", (0, 1), (-1, -1), .25, RULE),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1.3),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 1.3), ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
          ("RIGHTPADDING", (0, 0), (-1, -1), 2.5), ("ALIGN", (num_from, 0), (-1, -1), "RIGHT")]
    if neg_col is not None:
        for i, r in enumerate(rows, start=1):
            if str(r[neg_col]).startswith("-"):
                st.append(("BACKGROUND", (neg_col, i), (neg_col, i), NEGBG))
    t.setStyle(TableStyle(st))
    return t


def main():
    mg, sg, loss, fall = build_data()
    first_page = len(PdfReader(BASE).pages) + 1
    story = []

    def section(kicker, head, text):
        story.extend([PageBreak(), Paragraph(kicker, ST["kicker"]), Paragraph(head, ST["h1"]), Paragraph(text, ST["body"])])

    story += [Paragraph("Appendix", ST["kicker"]), Paragraph("Full profit, loss and margin lists", ST["h1"]),
              Paragraph(
                  "This appendix lists every main group, every sub-group, every loss-making article and every article whose "
                  "margin fell, so nothing is limited to a top-N view. All figures use actual COGS (with the cost-posting "
                  "corrections described in Section 2). <b>L12M</b> = Oct 2025 – Sep 2026; <b>prior 12M</b> = Oct 2024 – "
                  "Sep 2025. Money in <b>million Kz</b>. Margin change in percentage points (pp). Negative values in the "
                  "highlighted column are shaded.", ST["body"]),
              Paragraph(
                  f"<b>Contents.</b> A1 Main groups ({len(mg)}) · A2 Sub-groups ({len(sg)}) · A3 Loss-making articles "
                  f"({len(loss)}, total gross loss {loss.GP_KZ.sum() / 1e6:,.0f}m Kz) · A4 Articles with falling margin "
                  f"({len(fall):,}, gross profit lost {fall.GP_Lost_KZ.sum() / 1e6:,.0f}m Kz).", ST["body"]),
              Paragraph(
                  "<b>How to read the columns.</b> <i>GP effect of margin change</i> = L12M net sales × change in margin, "
                  "i.e. profit gained or lost because the margin moved. <i>Loss-making articles / loss</i> = articles in "
                  "the group with negative L12M gross profit and their combined loss. <i>Falling-margin articles / GP "
                  "lost</i> = articles sold in both periods whose margin fell, and the profit that fall cost. "
                  "<i>Below-cost loss</i> = loss on days where an article sold for less than two-thirds of its cost. "
                  "Groups overlap with each other's figures, so the columns should not be added across.", ST["body"])]

    head = ["Main group", "Net sales", "Gross profit", "Margin", "Prior 12M", "Change pp", "GP effect of change",
            "Loss-making art.", "Loss of loss-makers", "Falling-margin art.", "GP lost (falling)", "Below-cost loss"]
    rows = [[title(r.MainGroup), mk(r.Net_KZ), mk(r.GP_KZ), pc(r.Margin_Pct), pc(r.Margin_Pct_P12), pp(r.Change_pp),
             mk(r.GP_Effect_KZ), f"{r.Loss_Articles:.0f}", mk(r.Loss_KZ), f"{r.Falling_Articles:.0f}",
             mk(r.Falling_GP_Lost_KZ), mk(r.BelowCost_Loss_KZ)] for r in mg.itertuples()]
    story += [Spacer(1, 4), Paragraph("A1 · Every main group, L12M", ST["kicker"]),
              table(head, rows, [.14, .08, .08, .065, .065, .065, .085, .07, .085, .07, .085, .085], 1, neg_col=5)]

    section("Appendix A2", "Every sub-group", "All sub-groups with sales in the last 12 months, ranked by gross profit. "
            "Same columns as A1.")
    head = ["Sub-group", "Main group"] + head[1:]
    rows = [[title(r.SubGroup), title(r.MainGroup), mk(r.Net_KZ), mk(r.GP_KZ), pc(r.Margin_Pct), pc(r.Margin_Pct_P12),
             pp(r.Change_pp), mk(r.GP_Effect_KZ), f"{r.Loss_Articles:.0f}", mk(r.Loss_KZ), f"{r.Falling_Articles:.0f}",
             mk(r.Falling_GP_Lost_KZ), mk(r.BelowCost_Loss_KZ)] for r in sg.itertuples()]
    story.append(table(head, rows, [.11, .1, .07, .07, .06, .06, .06, .08, .065, .08, .065, .08, .07], 2, neg_col=6))

    section("Appendix A3", f"All {len(loss)} loss-making articles (L12M)",
            f"Every article with negative gross profit over the last 12 months, largest loss first. Together they lost "
            f"{loss.GP_KZ.sum() / 1e6:,.1f}m Kz. Where COGS is far above sales, check both the selling price and the cost "
            f"or unit-of-measure posting before acting.")
    head = ["#", "Code", "Article", "Sub-group", "Main group", "Stores", "Net sales", "COGS", "Gross profit", "Margin",
            "Below-cost loss"]
    rows = [[i, code(r.ArticleCode), title(r.ArticleName)[:44], title(r.SubGroup)[:16], title(r.MainGroup)[:14],
             f"{r.Stores:.0f}", mk(r.Net_KZ), mk(r.COGS_KZ), mk(r.GP_KZ), pc(r.Margin_Pct), mk(r.BelowCost_Loss_KZ)]
            for i, r in enumerate(loss.itertuples(), start=1)]
    story.append(table(head, rows, [.04, .06, .27, .1, .1, .05, .075, .075, .08, .065, .085], 5, neg_col=8))

    section("Appendix A4", f"All {len(fall):,} articles whose margin fell (L12M vs prior 12M)",
            f"Every article sold in both periods whose gross margin was lower in the last 12 months, ranked by the gross "
            f"profit the fall cost (L12M net sales × margin change). In total {fall.GP_Lost_KZ.sum() / 1e6:,.0f}m Kz; "
            f"the chain margin still rose because other articles gained more. Small articles can move by several points "
            f"from a single cost or price change, so focus on the top of the list.")
    head = ["#", "Code", "Article", "Sub-group", "Main group", "Net sales L12M", "Margin prior 12M", "Margin L12M",
            "Change pp", "GP lost"]
    rows = [[i, code(r.ArticleCode), title(r.ArticleName)[:46], title(r.SubGroup)[:16], title(r.MainGroup)[:14],
             mk(r.Net_KZ), pc(r.Margin_Pct_P12), pc(r.Margin_Pct), pp(r.Change_pp), mk(r.GP_Lost_KZ)]
            for i, r in enumerate(fall.itertuples(), start=1)]
    story.append(table(head, rows, [.045, .06, .29, .11, .1, .085, .08, .075, .07, .085], 5, neg_col=8))

    def page(c, d):
        c.saveState()
        c.setFont("Body", 7.4)
        c.setFillColor(MUTED)
        c.drawString(M, 10 * mm, "Fresmart · Profit & Margin Analysis Report · Appendix · Oct 2026")
        c.drawRightString(W - M, 10 * mm, f"{d.page + first_page - 1}")
        c.setStrokeColor(RULE)
        c.line(M, 13.5 * mm, W - M, 13.5 * mm)
        c.restoreState()

    buf = BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=14 * mm, bottomMargin=17 * mm)
    doc.addPageTemplates([PageTemplate("p", [Frame(M, 17 * mm, CW, H - 31 * mm, id="f", leftPadding=0,
                                                   rightPadding=0, topPadding=0, bottomPadding=0)], onPage=page)])
    doc.build(story)

    w = PdfWriter()
    for src in (PdfReader(BASE), PdfReader(BytesIO(buf.getvalue()))):
        for pg in src.pages:
            w.add_page(pg)
    w.add_metadata({"/Title": "Fresmart Profit & Margin Analysis Report (with full appendix)",
                    "/Author": "Newaco pricing analytics"})
    with open(OUTF, "wb") as fh:
        w.write(fh)
    print(OUTF, len(w.pages), "pages;", len(mg), len(sg), len(loss), len(fall))
    with pd.ExcelWriter(OUTF.with_suffix(".xlsx")) as xw:   # same lists, for filtering
        for name, d in [("A1 Main groups", mg), ("A2 Sub-groups", sg), ("A3 Loss-making articles", loss),
                        ("A4 Falling-margin articles", fall)]:
            d.to_excel(xw, sheet_name=name, index=False)


if __name__ == "__main__":
    main()
