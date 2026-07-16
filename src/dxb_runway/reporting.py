from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .domain import gbp_equivalent, to_aed


def create_financial_pdf(destination: Path, *, month: str, summary: Mapping[str, Any], rows: Iterable[Mapping[str, Any]],
                         gbp_aed_rate: str | float = "4.928313") -> Path:
    doc = SimpleDocTemplate(str(destination), pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
                            topMargin=18 * mm, bottomMargin=16 * mm, title=f"DXB RUNWAY — {month}")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("DXBTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22,
                           leading=26, textColor=colors.HexColor("#11151d"), spaceAfter=3 * mm)
    label = ParagraphStyle("DXBLabel", parent=styles["Normal"], fontSize=8, leading=10,
                           textColor=colors.HexColor("#697386"), uppercase=True)
    value = ParagraphStyle("DXBValue", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=13,
                           leading=16, textColor=colors.HexColor("#0f1723"))
    story = [Paragraph("DXB RUNWAY", title), Paragraph(f"PRIVATE FINANCIAL REPORT · {month}", label), Spacer(1, 7 * mm)]
    cards = []
    for key in ("Income", "Expenditure", "Net cash flow", "Commission pending"):
        cards.append([Paragraph(key.upper(), label), Paragraph(str(summary.get(key, "AED 0")), value)])
    overview = Table([cards[:2], cards[2:]], colWidths=[88 * mm, 88 * mm], rowHeights=[20 * mm, 20 * mm])
    overview.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f7fa")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8dee8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8dee8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
    ]))
    story += [overview, Spacer(1, 8 * mm), Paragraph("TRANSACTION LEDGER", label), Spacer(1, 2 * mm)]
    data = [["Date", "Type", "Category", "Merchant", "Amount"]]
    for row in rows:
        amount_aed = to_aed(row.get("amount", 0), str(row.get("currency", "AED")), gbp_aed_rate)
        data.append([str(row.get("occurred_at", ""))[:10], str(row.get("kind", "")).title(),
                     str(row.get("category", "—")), str(row.get("merchant", "")),
                     f"AED {amount_aed:,.2f}\nGBP {gbp_equivalent(amount_aed, gbp_aed_rate):,.2f}"])
    if len(data) == 1:
        data.append(["—", "—", "No transactions", "", ""])
    table = Table(data, repeatRows=1, colWidths=[25 * mm, 22 * mm, 38 * mm, 58 * mm, 33 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#11151d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d8dee8")), ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.3 * mm),
    ]))
    story += [table, Spacer(1, 6 * mm), Paragraph(
        f"Generated locally on {datetime.now():%d %B %Y at %H:%M}. No data was transmitted.", label)]
    doc.build(story)
    return destination
