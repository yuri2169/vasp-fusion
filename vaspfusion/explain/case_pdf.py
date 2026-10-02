"""The case file as an A4 PDF (reportlab: pure Python, no system libraries).

`case_file.py` decides what the file says; this module only draws its blocks. The
same case always gives the same bytes (`invariant`, and no clock: the date printed
is the case's own), so the PDF an officer exports today is the one a reviewer gets
tomorrow. Pages are left uncompressed, as for the request letter: the text can be
checked by searching the file.

Every page's footer carries the findings fingerprint, so a loose page can be tied
back to its receipt.
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from ..desk.pdf import BODY, BOLD, CELL, DRAFT, HEAD, INK, MONO, RULE, SMALL, SOFT, _t, _unescaped
from . import fmt
from .case_file import bar_check_for, case_file, reference

WIDTH = A4[0] - 36 * mm
OK = colors.HexColor("#2E7D5B")
TITLE = ParagraphStyle("title", parent=BODY, fontName="Helvetica-Bold", fontSize=20, leading=24,
                       spaceAfter=0)
SUB = ParagraphStyle("sub", parent=BODY, fontSize=9.5, textColor=SOFT, spaceAfter=8)
H1 = ParagraphStyle("h1", parent=HEAD, fontSize=9, leading=11.5, spaceBefore=12, spaceAfter=5,
                    textColor=INK, keepWithNext=1)
H2 = ParagraphStyle("h2", parent=BOLD, fontSize=9.5, leading=12, spaceBefore=8, spaceAfter=3,
                    keepWithNext=1)
PARA = ParagraphStyle("para", parent=BODY, fontSize=9.5, leading=13, spaceAfter=5)
ITEM = ParagraphStyle("item", parent=PARA, leftIndent=10, bulletIndent=0, spaceAfter=3)
EVID = ParagraphStyle("evid", parent=PARA, fontSize=8.8, leading=12, leftIndent=8, spaceAfter=1)
HASH = ParagraphStyle("hash", parent=MONO, fontSize=7, leading=9, leftIndent=16, textColor=SOFT)
PAGE = ParagraphStyle("page", parent=MONO, fontSize=6, leading=7.6, textColor=SOFT,
                      spaceAfter=2.5)
KEY = ParagraphStyle("key", parent=CELL, textColor=SOFT, fontSize=8)
VAL = ParagraphStyle("val", parent=CELL, fontSize=8.8, leading=11.5)
OUTCOME = ParagraphStyle("outcome", parent=BOLD, fontSize=12, leading=15, spaceAfter=4)
NOTICE = ParagraphStyle("notice", parent=PARA, fontSize=8.5, leading=11.5, textColor=DRAFT)

# box fill, border, text
ROLE_STYLE = {
    "suspect": ("#0E1C27", "#0E1C27", "#FFFFFF"),
    "exchange": ("#E3F1EA", "#2E7D5B", "#0E1C27"),
    "exchange_hot": ("#E3F1EA", "#2E7D5B", "#0E1C27"),
    "exchange_deposit": ("#E3F1EA", "#2E7D5B", "#0E1C27"),
    "custodial_wallet": ("#E3F1EA", "#2E7D5B", "#0E1C27"),
    "swap_service": ("#FBF1DC", "#B8791C", "#0E1C27"),
    "bridge": ("#ECE4F1", "#7B4B94", "#0E1C27"),
    "mixer": ("#F6E3E0", "#A2453B", "#0E1C27"),
    "sanctioned": ("#F6E3E0", "#A2453B", "#0E1C27"),
    "hub": ("#EEF1F3", "#4A5B69", "#0E1C27"),
    "unknown": ("#EEF1F3", "#4A5B69", "#0E1C27"),
    "intermediary": ("#FFFFFF", "#4A5B69", "#0E1C27"),
}
DASHED = ("hub", "unknown")           # wallets the trace did not go through


def _fit(text: str, font: str, size: float, width: float) -> str:
    """The text, cut to the width with no ellipsis character (a cut name ends in '.')."""
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + ".", font, size) > width:
        text = text[:-1]
    return text + "."


class FlowDiagram(Flowable):
    """Wallets as numbered boxes in hop columns, transfers as arrows (explain/flow.py)."""

    BOX_H, ROW_GAP, HEAD_H = 12 * mm, 4 * mm, 6 * mm

    def __init__(self, layout: dict, width: float = WIDTH):
        super().__init__()
        self.layout, self.width = layout, width
        n = max(1, len(layout["columns"]))
        self.col_gap = 9 * mm
        # half a gap is kept free on the right: a same-column arrow runs through it
        self.box_w = min(46 * mm, (width - self.col_gap * (n - 0.5)) / n)
        self.height = self.HEAD_H + layout["rows"] * (self.BOX_H + self.ROW_GAP)

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def _xy(self, box: dict) -> tuple[float, float]:
        x = box["col"] * (self.box_w + self.col_gap)
        y = self.height - self.HEAD_H - (box["row"] + 1) * (self.BOX_H + self.ROW_GAP) + self.ROW_GAP
        return x, y

    def _arrow(self, c, a: dict, at: dict, most: float) -> None:
        s, t = at[a["source"]], at[a["target"]]
        (sx, sy), (tx, ty) = self._xy(s), self._xy(t)
        mid = self.BOX_H / 2
        if t["col"] > s["col"]:
            x1, y1, x2, y2 = sx + self.box_w, sy + mid, tx, ty + mid
        elif t["col"] < s["col"]:
            x1, y1, x2, y2 = sx, sy + mid - 2, tx + self.box_w, ty + mid - 2
        else:                    # same column: out into the gap, along it, and back in
            x1 = x2 = sx + self.box_w
            y1, y2 = sy + mid + 2, ty + mid + 2
        c.setStrokeColor(SOFT)
        c.setFillColor(SOFT)
        c.setLineWidth(0.4 + 1.8 * (a["amount"] / most if most else 0))
        if t["col"] == s["col"]:
            out = x1 + self.col_gap * 0.45
            c.line(x1, y1, out, y1)
            c.line(out, y1, out, y2)
            x1 = out                              # the head is drawn on the last leg
        c.line(x1, y1, x2, y2)
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 or 1.0
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        bx, by = x2 - ux * 4.5, y2 - uy * 4.5
        head = c.beginPath()
        head.moveTo(x2, y2)
        head.lineTo(bx - uy * 2, by + ux * 2)
        head.lineTo(bx + uy * 2, by - ux * 2)
        head.close()
        c.drawPath(head, stroke=0, fill=1)

    def draw(self):
        c, lay = self.canv, self.layout
        c.saveState()
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(SOFT)
        for i, title in enumerate(lay["columns"]):
            c.drawString(i * (self.box_w + self.col_gap), self.height - 7, title.upper())
        at = {b["address"]: b for b in lay["boxes"]}
        most = max((a["amount"] for a in lay["arrows"]), default=0.0)
        for a in lay["arrows"]:
            self._arrow(c, a, at, most)
        for b in lay["boxes"]:
            x, y = self._xy(b)
            fill, edge, ink = ROLE_STYLE[b["role"]]
            c.setFillColor(colors.HexColor(fill))
            c.setStrokeColor(colors.HexColor(edge))
            c.setLineWidth(0.9)
            c.setDash(2, 2) if b["role"] in DASHED else c.setDash()
            c.roundRect(x, y, self.box_w, self.BOX_H, 2, stroke=1, fill=1)
            c.setDash()
            c.setFillColor(colors.HexColor(ink))
            inner = self.box_w - 8
            number = f"W{b['n']}"
            used = stringWidth(number, "Helvetica-Bold", 8) + 4
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x + 4, y + self.BOX_H - 10, number)
            c.setFont("Helvetica", 7)
            c.drawString(x + 4 + used, y + self.BOX_H - 10,
                         _fit(_unescaped(_t(b["title"])), "Helvetica", 7, inner - used))
            amount = fmt.amount(str(round(b["amount"], 6)), lay["asset"])
            c.drawString(x + 4, y + 6, _fit(amount, "Helvetica", 7, inner))
        c.restoreState()


def _cells(row, style_for) -> list:
    return [Paragraph(_t(v), style_for(i)) for i, v in enumerate(row)]


def _table(block: dict) -> Table:
    mono = set(block.get("mono", ()))
    total = sum(block["widths"])
    rows = [[Paragraph(_t(h).upper(), HEAD) for h in block["head"]]]
    rows += [_cells(r, lambda i: MONO if i in mono else CELL) for r in block["rows"]]
    table = Table(rows, repeatRows=1, colWidths=[WIDTH * w / total for w in block["widths"]])
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
             ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
             ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if block.get("total"):
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, INK))
    table.setStyle(TableStyle(style))
    return table


def _kv(block: dict) -> Table:
    rows = [[Paragraph(_t(k), KEY), Paragraph(_t(v), VAL)] for k, v in block["rows"]]
    table = Table(rows, colWidths=[38 * mm, WIDTH - 38 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 2),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE)]))
    return table


def _boxed(flowables: list, edge, fill) -> Table:
    table = Table([[flowables]], colWidths=[WIDTH])
    table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.9, edge),
                               ("BACKGROUND", (0, 0), (-1, -1), fill),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return table


def _story(blocks: list[dict]) -> list:
    story: list = []
    for b in blocks:
        t = b["t"]
        if t == "title":
            story += [Paragraph(_t(b["text"]).upper(), TITLE), Paragraph(_t(b["sub"]), SUB)]
        elif t == "h":
            story.append(Paragraph(_t(b["text"]).upper(), H1))
        elif t == "h2":
            story.append(Paragraph(_t(b["text"]), H2))
        elif t == "p":
            story.append(Paragraph(_t(b["text"]), PARA))
        elif t == "small":
            story.append(Paragraph(_t(b["text"]), SMALL))
        elif t == "note":
            story += [_boxed([Paragraph(_t(b["text"]), NOTICE)], DRAFT, colors.white),
                      Spacer(1, 6)]
        elif t == "result":
            story.append(_boxed([Paragraph(_t(b["outcome"]), OUTCOME)]
                                + [Paragraph(_t(line), PARA) for line in b["lines"]],
                                INK, colors.HexColor("#F3F5F7")))
        elif t == "kv":
            story.append(_kv(b))
        elif t == "table":
            story.append(_table(b))
        elif t == "list":
            story += [Paragraph(_t(item), ITEM, bulletText="-") for item in b["items"]]
        elif t == "evidence":
            lines = [Paragraph(f"<b>{_t(b['kind'])}.</b> {_t(b['text'])}", EVID)]
            lines += [Paragraph(_t(h), HASH) for h in b["hashes"]]
            story += [KeepTogether(lines[:3]), *lines[3:], Spacer(1, 3)]
        elif t == "flow":
            # the heading goes into the same block, or it is left behind on the page before
            heading = [story.pop()] if story and getattr(story[-1], "style", None) is H1 else []
            story += [KeepTogether(heading + [FlowDiagram(b["layout"]), Spacer(1, 2),
                                              Paragraph(_t(b["caption"]), SMALL)]),
                      Spacer(1, 4)]
        elif t == "pages":
            story += [Paragraph(f"{_t(sha)}<br/>{_t(query)}", PAGE) for sha, query in b["rows"]]
        else:
            raise ValueError(f"unknown block {t}")
    return story


def case_pdf(case: dict, *, watermark: str | None = None, bar_check: dict | None = None,
             blocks: list[dict] | None = None) -> bytes:
    """The case file of a finished case. `watermark` marks a file that is not evidence
    (a mock demo fixture). Raises `case_file.NotReady` for a case with no result."""
    if blocks is None:
        blocks = case_file(case, bar_check=bar_check if bar_check is not None
                           else bar_check_for(case["chain"]))
    ref = reference(case)
    fingerprint = (case.get("provenance") or {}).get("findings_sha256")
    footer = f"Case file {ref}  |  VASP-FUSION {case['provenance']['code_version']}" + \
             (f"  |  fingerprint {fingerprint}" if fingerprint else "")

    def page(canvas, doc):
        canvas.saveState()
        if watermark:
            canvas.setFont("Helvetica-Bold", 38)
            canvas.setFillColor(colors.Color(0.64, 0.27, 0.23, alpha=0.13))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(52)
            canvas.drawCentredString(0, 0, watermark.upper())
            canvas.rotate(-52)
            canvas.translate(-A4[0] / 2, -A4[1] / 2)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(DRAFT)
            canvas.drawString(18 * mm, A4[1] - 11 * mm, watermark.upper() + ".")
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(SOFT)
        canvas.drawString(18 * mm, 10 * mm, _unescaped(_t(footer)))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, invariant=1,
                            pageCompression=0, title=f"Case file {_unescaped(_t(ref))}",
                            author="VASP-FUSION",
                            subject=f"{case['chain']} {case['address']}")
    doc.build(_story(blocks), onFirstPage=page, onLaterPages=page)
    return out.getvalue()
