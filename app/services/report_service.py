"""Tabular admin reports with PDF and Excel export."""
import io
from collections import OrderedDict
from datetime import datetime, timedelta

from flask import current_app
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func

from ..extensions import db
from ..models import (Cancellation, Category, InventoryBatch, Order, OrderItem, Payment, Product, Refund, User, D,
                      PAYMENT_METHOD_LABELS)
from . import inventory_service as inv
from .analytics_service import SOLD_STATUSES, to_local, utc_bounds

REPORTS = OrderedDict([
    ("sales", "Sales report"),
    ("inventory", "Inventory report"),
    ("expiry", "Expiration report"),
    ("best_sellers", "Best-selling products"),
    ("customers", "Customer order report"),
    ("payments", "Payment report"),
    ("cancellations", "Cancellations & refunds"),
])
PERIODS = OrderedDict([("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly"), ("yearly", "Yearly")])
MONEY_COLS = {"Subtotal", "Discount", "Tax", "Delivery", "Gross sales", "Price", "Revenue", "Total spent",
              "Amount", "Original", "Refund", "Avg order"}


def _period_key(d, period):
    if period == "weekly":
        wk = d - timedelta(days=d.weekday())
        return wk, f"Week of {wk:%d %b %Y}"
    if period == "monthly":
        return (d.year, d.month), d.strftime("%B %Y")
    if period == "yearly":
        return d.year, str(d.year)
    return d, d.strftime("%a %d %b %Y")


def build_report(kind, start, end, period="daily"):
    s, e = utc_bounds(start, end)
    title = REPORTS.get(kind, "Report")
    if kind == "sales":
        orders = (Order.query.filter(Order.status.in_(SOLD_STATUSES), Order.confirmed_at >= s,
                                     Order.confirmed_at < e).order_by(Order.confirmed_at).all())
        groups = OrderedDict()
        for o in orders:
            key, label = _period_key(to_local(o.confirmed_at).date(), period)
            g = groups.setdefault(key, {"label": label, "orders": 0, "items": 0, "sub": 0, "disc": 0, "tax": 0,
                                        "del": 0, "gross": 0})
            g["orders"] += 1
            g["items"] += o.item_count
            g["sub"] += float(o.subtotal); g["disc"] += float(o.discount); g["tax"] += float(o.tax_amount)
            g["del"] += float(o.delivery_charge); g["gross"] += float(o.grand_total)
        cols = ["Period", "Orders", "Items", "Subtotal", "Discount", "Tax", "Delivery", "Gross sales", "Avg order"]
        rows = [[g["label"], g["orders"], g["items"], g["sub"], g["disc"], g["tax"], g["del"], g["gross"],
                 g["gross"] / g["orders"] if g["orders"] else 0] for g in groups.values()]
        title = f"{PERIODS.get(period, 'Daily')} {title.lower()}"
    elif kind == "inventory":
        stocks = inv.stock_map()
        sold = dict(db.session.query(InventoryBatch.product_id, func.sum(InventoryBatch.quantity_sold))
                    .group_by(InventoryBatch.product_id).all())
        nearest = inv.nearest_expiry_map()
        cols = ["Product", "Category", "Price", "Available", "Sold (all time)", "Nearest expiry", "Status"]
        rows = []
        for p in Product.query.join(Category).order_by(Category.kind.desc(), Product.name).all():
            qty = stocks.get(p.id, 0)
            status = "Inactive" if not p.is_active else ("Out of stock" if qty == 0 else
                                                          "Low stock" if qty <= current_app.config["LOW_STOCK_THRESHOLD"] else "In stock")
            rows.append([p.name, p.category.name, float(p.price), qty, int(sold.get(p.id) or 0),
                         nearest[p.id].strftime("%d %b %Y") if p.id in nearest else "—", status])
    elif kind == "expiry":
        cols = ["Batch", "Product", "Manufactured", "Expires", "Days left", "Available", "Sold", "Status"]
        rows = []
        for key, batches in inv.expiry_buckets().items():
            for b in batches:
                rows.append([b.batch_number, b.product.name, b.manufacturing_date.strftime("%d %b %Y"),
                             b.expiration_date.strftime("%d %b %Y"), b.days_left, b.quantity_available,
                             b.quantity_sold, inv.expiry_level(b.expiration_date)[1]])
    elif kind == "best_sellers":
        cols = ["Rank", "Product", "Type", "Qty sold", "Orders", "Revenue"]
        q = (db.session.query(OrderItem.product_name, OrderItem.category_kind, func.sum(OrderItem.quantity),
                              func.count(func.distinct(OrderItem.order_id)), func.sum(OrderItem.line_total))
             .join(Order).filter(Order.status.in_(SOLD_STATUSES), Order.confirmed_at >= s, Order.confirmed_at < e)
             .group_by(OrderItem.product_name, OrderItem.category_kind)
             .order_by(func.sum(OrderItem.quantity).desc()).all())
        rows = [[i, n, k.title(), int(qt), int(oc), float(rv)] for i, (n, k, qt, oc, rv) in enumerate(q, 1)]
    elif kind == "customers":
        cols = ["Customer", "Email", "Phone", "Orders", "Total spent", "Avg order", "Last order"]
        q = (db.session.query(User, func.count(Order.id), func.sum(Order.grand_total), func.max(Order.confirmed_at))
             .join(Order, Order.user_id == User.id)
             .filter(Order.status.in_(SOLD_STATUSES), Order.confirmed_at >= s, Order.confirmed_at < e)
             .group_by(User.id).order_by(func.sum(Order.grand_total).desc()).all())
        rows = [[u.name, u.email, u.phone, int(c), float(t), float(t) / c, to_local(last).strftime("%d %b %Y")]
                for u, c, t, last in q]
    elif kind == "payments":
        cols = ["Date", "Order", "Customer", "Method", "Gateway", "Transaction ID", "Amount", "Status"]
        q = (Payment.query.join(Order).filter(Payment.created_at >= s, Payment.created_at < e)
             .order_by(Payment.created_at.desc()).all())
        rows = [[to_local(p.created_at).strftime("%d %b %Y %H:%M"), p.order.order_number, p.order.customer_name,
                 PAYMENT_METHOD_LABELS.get(p.method, p.method), p.gateway, p.transaction_id or "—",
                 float(p.amount), p.status] for p in q]
    elif kind == "cancellations":
        cols = ["Date", "Order", "Customer", "Cancelled by", "Reason", "Original", "Refund", "Refund status"]
        q = (Cancellation.query.join(Order).filter(Cancellation.created_at >= s, Cancellation.created_at < e)
             .order_by(Cancellation.created_at.desc()).all())
        rows = [[to_local(c.created_at).strftime("%d %b %Y %H:%M"), c.order.order_number, c.order.customer_name,
                 c.cancelled_by.title(), c.reason or "—", float(c.original_amount), float(c.refund_amount),
                 (c.refund.status if c.refund else "n/a").title()] for c in q]
    else:
        raise ValueError("Unknown report")

    totals = None
    if rows and kind in ("sales", "best_sellers", "customers", "payments", "cancellations"):
        totals = []
        for i, col in enumerate(cols):
            if col in MONEY_COLS - {"Avg order", "Price"} or col in ("Orders", "Items", "Qty sold"):
                totals.append(sum(r[i] for r in rows if isinstance(r[i], (int, float))))
            else:
                totals.append("")
        totals[0] = "Total"
    return {"kind": kind, "title": title, "columns": cols, "rows": rows, "totals": totals,
            "start": start, "end": end, "period": period, "generated": datetime.now()}


def fmt_cell(col, v):
    if col in MONEY_COLS and isinstance(v, (int, float)):
        return f"{current_app.config['CURRENCY_SYMBOL']}{v:,.2f}"
    return "" if v is None else str(v)


# ------------------------------------------------------------------ exporters
def export_excel(report):
    wb = Workbook()
    ws = wb.active
    ws.title = report["kind"][:30]
    maroon, saffron = "7B1E2B", "F28C28"
    ws.append([current_app.config["STORE_NAME"]])
    ws["A1"].font = Font(bold=True, size=15, color=maroon)
    ws.append([f"{report['title']} · {report['start']:%d %b %Y} – {report['end']:%d %b %Y}"])
    ws["A2"].font = Font(italic=True, color="8A6E5A")
    ws.append([])
    ws.append(report["columns"])
    thin = Side(style="thin", color="EAD8B8")
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=saffron)
        c.alignment = Alignment(horizontal="center")
    money_fmt = f'"{current_app.config["CURRENCY_SYMBOL"]}"#,##0.00'
    for row in report["rows"] + ([report["totals"]] if report["totals"] else []):
        ws.append(row)
        for i, c in enumerate(ws[ws.max_row]):
            c.border = Border(bottom=thin)
            if report["columns"][i] in MONEY_COLS and isinstance(c.value, (int, float)):
                c.number_format = money_fmt
    if report["totals"]:
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color=maroon)
            c.fill = PatternFill("solid", fgColor="FFF3DF")
    for i, col in enumerate(report["columns"], 1):
        width = max([len(str(col))] + [len(fmt_cell(col, r[i - 1])) for r in report["rows"][:500]]) + 3
        ws.column_dimensions[get_column_letter(i)].width = min(max(width, 10), 48)
    ws.freeze_panes = "A5"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_pdf(report):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title=report["title"])
    maroon, saffron, cream = colors.HexColor("#7B1E2B"), colors.HexColor("#F28C28"), colors.HexColor("#FFF8EC")
    h = ParagraphStyle("h", fontName="Times-Bold", fontSize=18, textColor=maroon, leading=22)
    sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#8A6E5A"))
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=8, leading=10)
    story = [Paragraph(f"{current_app.config['STORE_NAME']} — {report['title']}", h),
             Paragraph(f"{report['start']:%d %b %Y} – {report['end']:%d %b %Y} · generated "
                       f"{report['generated']:%d %b %Y %H:%M} · {len(report['rows'])} rows", sub),
             Spacer(1, 5 * mm)]
    data = [report["columns"]]
    for r in report["rows"]:
        data.append([Paragraph(fmt_cell(c, v), cell) for c, v in zip(report["columns"], r)])
    if report["totals"]:
        data.append([fmt_cell(c, v) for c, v in zip(report["columns"], report["totals"])])
    if len(data) == 1:
        data.append(["No data for this period"] + [""] * (len(report["columns"]) - 1))
    t = Table(data, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), saffron), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
             ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#EAD8B8")),
             ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D4A017")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), cream))
    if report["totals"]:
        style += [("BACKGROUND", (0, -1), (-1, -1), maroon), ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
                  ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    story.append(t)
    doc.build(story)
    return buf.getvalue()
