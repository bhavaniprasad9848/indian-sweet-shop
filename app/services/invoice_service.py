"""PDF tax invoices and credit notes (ReportLab), styled like a traditional sweet-shop bill."""
import io
import math
import os

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

from ..extensions import db
from ..models import D
from .analytics_service import to_local

MAROON = colors.HexColor("#7B1E2B")
SAFFRON = colors.HexColor("#F28C28")
GOLD = colors.HexColor("#D4A017")
CREAM = colors.HexColor("#FFF8EC")
IVORY = colors.HexColor("#FFFDF7")
INK = colors.HexColor("#3A2418")
MUTED = colors.HexColor("#8A6E5A")

S = {
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=7.5, textColor=MAROON, leading=10,
                            spaceAfter=2),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=8.8, textColor=INK, leading=12),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.6, textColor=MUTED, leading=10),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.8, textColor=INK, leading=11),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.8, textColor=INK, leading=11),
    "thanks": ParagraphStyle("thanks", fontName="Times-BoldItalic", fontSize=13, textColor=MAROON,
                             alignment=TA_CENTER, leading=16),
    "center": ParagraphStyle("center", fontName="Helvetica", fontSize=8, textColor=MUTED, alignment=TA_CENTER,
                             leading=11),
    "right": ParagraphStyle("right", fontName="Helvetica", fontSize=8.8, textColor=INK, alignment=TA_RIGHT),
}

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
        "sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _words(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + _words(n % 100) if n % 100 else "")
    for div, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= div:
            return _words(n // div) + f" {name}" + (" " + _words(n % div) if n % div else "")
    return str(n)


def amount_in_words(amount):
    amount = D(amount)
    whole, cents = int(amount), int((amount - int(amount)) * 100)
    unit = "dollars" if current_app.config["CURRENCY"].lower() == "usd" else current_app.config["CURRENCY"].upper()
    text = f"{_words(whole).capitalize()} {unit}"
    if cents:
        text += f" and {_words(cents)} cents"
    return text + " only"


def money(v):
    return f"{current_app.config['CURRENCY_SYMBOL']}{float(v or 0):,.2f}"


# ------------------------------------------------------------------ page decoration
def _draw_logo(c, cx, cy, r):
    c.saveState()
    c.setFillColor(GOLD)
    c.circle(cx, cy, r, stroke=0, fill=1)
    c.setFillColor(MAROON)
    c.circle(cx, cy, r * 0.86, stroke=0, fill=1)
    # petal ring
    c.setFillColor(GOLD)
    for i in range(12):
        a = i * math.pi / 6
        c.circle(cx + math.cos(a) * r * 0.72, cy + math.sin(a) * r * 0.72, r * 0.07, stroke=0, fill=1)
    # diya bowl
    c.setFillColor(SAFFRON)
    p = c.beginPath()
    p.moveTo(cx - r * 0.42, cy - r * 0.08)
    p.curveTo(cx - r * 0.3, cy - r * 0.42, cx + r * 0.3, cy - r * 0.42, cx + r * 0.42, cy - r * 0.08)
    p.close()
    c.drawPath(p, stroke=0, fill=1)
    # flame
    c.setFillColor(colors.HexColor("#FFD36B"))
    p = c.beginPath()
    p.moveTo(cx, cy + r * 0.45)
    p.curveTo(cx + r * 0.18, cy + r * 0.18, cx + r * 0.12, cy - r * 0.02, cx, cy - r * 0.04)
    p.curveTo(cx - r * 0.12, cy - r * 0.02, cx - r * 0.18, cy + r * 0.18, cx, cy + r * 0.45)
    c.drawPath(p, stroke=0, fill=1)
    c.restoreState()


def _border_motif(c, y, width, x0):
    """A row of small diamonds and dots — a simple rangoli border."""
    c.saveState()
    c.setFillColor(GOLD)
    step = 9
    x = x0
    i = 0
    while x < x0 + width:
        if i % 2 == 0:
            p = c.beginPath()
            p.moveTo(x, y + 2.2); p.lineTo(x + 2.2, y); p.lineTo(x, y - 2.2); p.lineTo(x - 2.2, y); p.close()
            c.drawPath(p, stroke=0, fill=1)
        else:
            c.circle(x, y, 0.9, stroke=0, fill=1)
        x += step / 2
        i += 1
    c.restoreState()


def _make_page_painter(title, subtitle):
    cfg = current_app.config

    def paint(c, doc):
        w, h = A4
        c.saveState()
        c.setFillColor(IVORY)
        c.rect(0, 0, w, h, stroke=0, fill=1)
        # outer double border
        c.setStrokeColor(GOLD); c.setLineWidth(1.4)
        c.rect(10 * mm, 10 * mm, w - 20 * mm, h - 20 * mm, stroke=1, fill=0)
        c.setStrokeColor(MAROON); c.setLineWidth(0.5)
        c.rect(11.5 * mm, 11.5 * mm, w - 23 * mm, h - 23 * mm, stroke=1, fill=0)
        # header band
        band_h = 34 * mm
        top = h - 11.5 * mm
        c.setFillColor(MAROON)
        c.rect(11.5 * mm, top - band_h, w - 23 * mm, band_h, stroke=0, fill=1)
        c.setFillColor(SAFFRON)
        c.rect(11.5 * mm, top - band_h - 1.6 * mm, w - 23 * mm, 1.6 * mm, stroke=0, fill=1)
        _draw_logo(c, 28 * mm, top - band_h / 2, 11 * mm)
        c.setFillColor(CREAM)
        c.setFont("Times-Bold", 21)
        c.drawString(43 * mm, top - 14 * mm, cfg["STORE_NAME"])
        c.setFont("Times-Italic", 9.5)
        c.setFillColor(colors.HexColor("#F7D58B"))
        c.drawString(43 * mm, top - 19.5 * mm, cfg["STORE_TAGLINE"])
        c.setFont("Helvetica", 7.8)
        c.setFillColor(CREAM)
        c.drawString(43 * mm, top - 25 * mm, cfg["STORE_ADDRESS"])
        line = f"Tel {cfg['STORE_PHONE']}   ·   {cfg['STORE_EMAIL']}"
        if cfg["STORE_GSTIN"]:
            line += f"   ·   GSTIN {cfg['STORE_GSTIN']}"
        c.drawString(43 * mm, top - 29.5 * mm, line)
        c.setFont("Helvetica-Bold", 13)
        c.setFillColor(colors.HexColor("#F7D58B"))
        c.drawRightString(w - 17 * mm, top - 14 * mm, title)
        c.setFont("Helvetica", 8)
        c.setFillColor(CREAM)
        c.drawRightString(w - 17 * mm, top - 19.5 * mm, subtitle)
        _border_motif(c, top - band_h - 4.4 * mm, w - 34 * mm, 17 * mm)
        # footer
        _border_motif(c, 19 * mm, w - 34 * mm, 17 * mm)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawCentredString(w / 2, 14.5 * mm,
                            f"This is a computer-generated document and does not require a signature.  ·  Page {doc.page}")
        c.restoreState()

    return paint


# ------------------------------------------------------------------ content blocks
def _party_block(order, meta_rows):
    bill = Paragraph(f"<b>{order.customer_name}</b><br/>{order.customer_email}<br/>{order.customer_phone}<br/>"
                     f"{order.billing_address or order.shipping_address}", S["body"])
    ship = Paragraph(f"<b>{order.customer_name}</b><br/>{order.shipping_address}"
                     + (f"<br/><font color='#8A6E5A'>Note: {order.delivery_instructions}</font>"
                        if order.delivery_instructions else ""), S["body"])
    meta = Table([[Paragraph(k, S["label"]), Paragraph(v, S["cellb"] if i == 0 else S["cell"])]
                  for i, (k, v) in enumerate(meta_rows)], colWidths=[27 * mm, 38 * mm])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                              ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    t = Table([[Paragraph("BILLED TO", S["label"]), Paragraph("DELIVER TO", S["label"]), meta],
               [bill, ship, ""]], colWidths=[55 * mm, 55 * mm, 66 * mm])
    t.setStyle(TableStyle([
        ("SPAN", (2, 0), (2, 1)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), CREAM), ("BOX", (0, 0), (-1, -1), 0.6, GOLD),
        ("LINEBEFORE", (2, 0), (2, 1), 0.6, GOLD), ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    return t


def _items_table(order, sign=1):
    rate_pct = f"{current_app.config['TAX_RATE'] * 100:g}%"
    data = [["#", "Item", "Qty", "Unit Price", f"Tax ({rate_pct})", "Total"]]
    for n, i in enumerate(order.items, 1):
        label = f"<b>{i.product_name}</b>" + (f"<br/><font size=7 color='#8A6E5A'>{i.unit_label}</font>" if i.unit_label else "")
        data.append([str(n), Paragraph(label, S["cell"]), str(i.quantity), money(i.unit_price),
                     money(D(i.tax_amount) * sign), money(D(i.line_total) * sign)])
    t = Table(data, colWidths=[9 * mm, 71 * mm, 14 * mm, 26 * mm, 26 * mm, 30 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), SAFFRON), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.8),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#EAD8B8")),
        ("BOX", (0, 0), (-1, -1), 0.6, GOLD),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for r in range(1, len(data)):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), CREAM))
    t.setStyle(TableStyle(style))
    return t


def _summary_table(rows, highlight_index):
    data = []
    for i, (k, v) in enumerate(rows):
        hl = i == highlight_index
        lstyle = ParagraphStyle(f"sl{i}", parent=S["cellb"] if hl else S["cell"],
                                textColor=colors.white if hl else INK)
        rstyle = ParagraphStyle(f"sr{i}", parent=S["right"], fontName="Helvetica-Bold" if hl else "Helvetica",
                                textColor=colors.white if hl else INK)
        data.append([Paragraph(k, lstyle), Paragraph(v, rstyle)])
    t = Table(data, colWidths=[42 * mm, 34 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, GOLD), ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#EAD8B8")),
        ("BACKGROUND", (0, highlight_index), (-1, highlight_index), MAROON),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))
    return t


def _render(story, title, subtitle):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=54 * mm, bottomMargin=26 * mm,
                            title=title, author=current_app.config["STORE_NAME"])
    painter = _make_page_painter(title, subtitle)
    doc.build(story, onFirstPage=painter, onLaterPages=painter)
    return buf.getvalue()


# ------------------------------------------------------------------ public API
def build_invoice_pdf(order):
    inv = order.invoice
    if inv is None:
        raise ValueError("Order has no invoice yet.")
    pay = order.successful_payment or order.payments.first()
    txn = pay.transaction_id if pay else "—"
    pay_desc = order.payment_method_label
    if pay and pay.card_last4:
        pay_desc += f" ({pay.card_brand or 'Card'} •••• {pay.card_last4})"
    elif pay and pay.upi_handle_masked:
        pay_desc += f" ({pay.upi_handle_masked})"
    meta = [("INVOICE NO.", inv.invoice_number), ("ORDER ID", order.order_number),
            ("INVOICE DATE", to_local(inv.invoice_date).strftime("%d %b %Y, %I:%M %p")),
            ("PAYMENT", pay_desc), ("TRANSACTION ID", txn), ("ORDER STATUS", order.status_label)]
    paid_label = {"paid": "PAID", "pending": "DUE ON DELIVERY", "refunded": "REFUNDED"}.get(order.payment_status,
                                                                                          order.payment_status.upper())
    rows = [("Subtotal", money(inv.subtotal)), ("Discount", f"− {money(inv.discount)}"),
            (current_app.config["TAX_LABEL"], money(inv.tax_amount)),
            ("Delivery charges", money(inv.delivery_charge) if D(inv.delivery_charge) else "FREE"),
            ("Grand Total", money(inv.grand_total)), ("Amount Paid", money(inv.amount_paid)),
            ("Payment Status", paid_label)]
    words = Paragraph(f"<font color='#7B1E2B'><b>Amount in words:</b></font> {amount_in_words(inv.grand_total)}",
                      S["body"])
    bottom = Table([[words, _summary_table(rows, 4)]], colWidths=[100 * mm, 76 * mm])
    bottom.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [
        _party_block(order, meta), Spacer(1, 6 * mm), _items_table(order), Spacer(1, 5 * mm), bottom,
        Spacer(1, 9 * mm),
        KeepTogether([
            Paragraph("Dhanyavaad! Thank you for choosing us.", S["thanks"]), Spacer(1, 2 * mm),
            Paragraph("Every sweet is handcrafted fresh in small batches. Please refrigerate milk-based sweets and "
                      "consume within the shelf life printed on the box.", S["center"]),
            Paragraph(f"Questions about your order? Write to {current_app.config['SUPPORT_EMAIL']} or call "
                      f"{current_app.config['STORE_PHONE']}.", S["center"]),
        ]),
    ]
    return _render(story, "TAX INVOICE", f"{inv.invoice_number}  ·  Original for recipient")


def build_credit_note_pdf(order):
    canc = order.cancellation
    if not canc or not canc.credit_note_number:
        raise ValueError("No credit note for this order.")
    refund = canc.refund
    meta = [("CREDIT NOTE NO.", canc.credit_note_number), ("ORDER ID", order.order_number),
            ("AGAINST INVOICE", order.invoice.invoice_number if order.invoice else "—"),
            ("ORDER DATE", to_local(order.created_at).strftime("%d %b %Y")),
            ("CANCELLED ON", to_local(canc.created_at).strftime("%d %b %Y, %I:%M %p")),
            ("REFUND REF.", (refund.gateway_refund_id if refund else None) or "—")]
    rows = [("Original order amount", money(canc.original_amount)), ("Refund amount", money(canc.refund_amount)),
            ("Refund status", (refund.status if refund else "not applicable").title()),
            ("Refund method", order.payment_method_label)]
    reason = Paragraph(f"<font color='#7B1E2B'><b>Reason:</b></font> {canc.reason or 'Not provided'}<br/>"
                       f"<font color='#7B1E2B'><b>Cancelled by:</b></font> {canc.cancelled_by.title()}", S["body"])
    bottom = Table([[reason, _summary_table(rows, 1)]], colWidths=[100 * mm, 76 * mm])
    bottom.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [_party_block(order, meta), Spacer(1, 6 * mm),
             Paragraph("CANCELLED ITEMS", S["label"]), _items_table(order), Spacer(1, 5 * mm), bottom,
             Spacer(1, 9 * mm),
             Paragraph("We're sorry to see this order go.", S["thanks"]),
             Paragraph("Refunds to cards and UPI usually reach your account within 5–7 business days.", S["center"])]
    return _render(story, "CREDIT NOTE", canc.credit_note_number)


def _save(data, filename):
    path = os.path.join(current_app.config["INVOICE_DIR"], filename)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def save_invoice_pdf(order):
    path = _save(build_invoice_pdf(order), f"Invoice-{order.invoice.invoice_number}.pdf")
    order.invoice.pdf_path = path
    db.session.commit()
    return path


def save_credit_note_pdf(order):
    path = _save(build_credit_note_pdf(order), f"CreditNote-{order.cancellation.credit_note_number}.pdf")
    order.cancellation.credit_note_path = path
    return path
