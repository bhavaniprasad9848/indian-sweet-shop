"""Business analytics computed from real order/payment/refund rows.

Timestamps are stored in UTC; day/week/month boundaries use STORE_TIMEZONE.
"""
from collections import OrderedDict, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..models import (Cancellation, Category, Order, OrderItem, Payment, Product, Refund, User, D,
                      PAYMENT_METHOD_LABELS)
from . import inventory_service as inv

SOLD_STATUSES = ("confirmed", "preparing", "ready_for_pickup", "out_for_delivery", "delivered")


def tz():
    return ZoneInfo(current_app.config.get("STORE_TIMEZONE", "America/Chicago"))


def local_today():
    return datetime.now(tz()).date()


def to_local(dt_utc):
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(tz())


def utc_bounds(start_day, end_day):
    """Inclusive local dates → [start, end) naive-UTC datetimes for DB filtering."""
    z = tz()
    s = datetime.combine(start_day, time.min, z).astimezone(timezone.utc).replace(tzinfo=None)
    e = datetime.combine(end_day + timedelta(days=1), time.min, z).astimezone(timezone.utc).replace(tzinfo=None)
    return s, e


def f(x):
    return float(D(x))


# ------------------------------------------------------------------ dashboard cards
def dashboard_summary():
    today = local_today()
    ts, te = utc_bounds(today, today)
    ms, me = utc_bounds(today.replace(day=1), today)
    stocks = inv.stock_map()
    buckets = inv.expiry_buckets()
    sold = Order.query.filter(Order.status.in_(SOLD_STATUSES))
    return {
        "total_products": Product.query.filter_by(is_active=True).count(),
        "total_stock": sum(stocks.values()),
        "total_orders": Order.query.filter(Order.status != "pending").count(),
        "today_orders": Order.query.filter(Order.status != "pending", Order.confirmed_at >= ts,
                                           Order.confirmed_at < te).count(),
        "today_revenue": f(sold.filter(Order.confirmed_at >= ts, Order.confirmed_at < te)
                           .with_entities(func.coalesce(func.sum(Order.grand_total), 0)).scalar()),
        "month_revenue": f(sold.filter(Order.confirmed_at >= ms, Order.confirmed_at < me)
                           .with_entities(func.coalesce(func.sum(Order.grand_total), 0)).scalar()),
        "total_customers": User.query.filter_by(is_verified=True).count(),
        "low_stock": len(inv.low_stock_products()),
        "expiring": len(buckets["today"]) + len(buckets["3days"]) + len(buckets["7days"]),
        "expired": len(buckets["expired"]),
    }


def daily_revenue(day=None):
    day = day or local_today()
    s, e = utc_bounds(day, day)
    orders = Order.query.filter(Order.confirmed_at >= s, Order.confirmed_at < e).all()
    payments = Payment.query.filter(Payment.verified_at >= s, Payment.verified_at < e,
                                    Payment.status.in_(("succeeded", "refunded", "partially_refunded"))).all()
    refunds = Refund.query.filter(Refund.processed_at >= s, Refund.processed_at < e,
                                  Refund.status == "processed").all()
    cancels = Cancellation.query.filter(Cancellation.created_at >= s, Cancellation.created_at < e).count()
    live = [o for o in orders if o.status in SOLD_STATUSES]
    cod = [o for o in orders if o.payment_method == "cod"]
    collected = sum((D(p.amount) for p in payments), Decimal("0"))
    refunded = sum((D(r.amount) for r in refunds), Decimal("0"))
    return {
        "day": day,
        "orders_received": len(orders),
        "successful_payments": len(payments),
        "collected": f(collected),
        "online_collected": f(sum((D(p.amount) for p in payments if p.gateway != "cod"), Decimal("0"))),
        "cod_collected": f(sum((D(p.amount) for p in payments if p.gateway == "cod"), Decimal("0"))),
        "gross_sales": f(sum((D(o.grand_total) for o in live), Decimal("0"))),
        "taxes": f(sum((D(o.tax_amount) for o in live), Decimal("0"))),
        "refunds": f(refunded),
        "refund_count": len(refunds),
        "cancellations": cancels,
        "net_revenue": f(collected - refunded),
        "cod_orders": len(cod),
        "cod_value": f(sum((D(o.grand_total) for o in cod if o.status in SOLD_STATUSES), Decimal("0"))),
        "cod_pending": f(sum((D(o.grand_total) for o in cod if o.payment_status == "pending"), Decimal("0"))),
    }


# ------------------------------------------------------------------ charts
def _sold_orders(start_utc=None, end_utc=None):
    q = Order.query.filter(Order.status.in_(SOLD_STATUSES), Order.confirmed_at.isnot(None))
    if start_utc:
        q = q.filter(Order.confirmed_at >= start_utc)
    if end_utc:
        q = q.filter(Order.confirmed_at < end_utc)
    return q.with_entities(Order.id, Order.confirmed_at, Order.grand_total, Order.payment_method).all()


def chart_data(start_day, end_day):
    s, e = utc_bounds(start_day, end_day)
    in_range = _sold_orders(s, e)

    # daily
    daily = OrderedDict()
    d = start_day
    while d <= end_day:
        daily[d] = [0.0, 0]
        d += timedelta(days=1)
    for _, at, total, _ in in_range:
        ld = to_local(at).date()
        if ld in daily:
            daily[ld][0] += f(total)
            daily[ld][1] += 1

    # weekly (ISO week starting Monday)
    weekly = OrderedDict()
    for day, (rev, cnt) in daily.items():
        wk = day - timedelta(days=day.weekday())
        w = weekly.setdefault(wk, [0.0, 0])
        w[0] += rev
        w[1] += cnt

    # monthly: 12 months ending at end_day
    m_start = (end_day.replace(day=1) - timedelta(days=330)).replace(day=1)
    ms, _ = utc_bounds(m_start, m_start)
    monthly = OrderedDict()
    cur = m_start
    while cur <= end_day:
        monthly[(cur.year, cur.month)] = 0.0
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    yearly = defaultdict(float)
    for _, at, total, _ in _sold_orders(None, e):
        ld = to_local(at).date()
        yearly[ld.year] += f(total)
        if (ld.year, ld.month) in monthly and at >= ms:
            monthly[(ld.year, ld.month)] += f(total)

    ids = [r[0] for r in in_range]
    best = {"sweet": [], "food": []}
    cat_rev = []
    if ids:
        rows = (db.session.query(OrderItem.product_name, OrderItem.category_kind,
                                 func.sum(OrderItem.quantity), func.sum(OrderItem.line_total))
                .filter(OrderItem.order_id.in_(ids))
                .group_by(OrderItem.product_name, OrderItem.category_kind)
                .order_by(func.sum(OrderItem.quantity).desc()).all())
        for name, kind, qty, rev in rows:
            if len(best.get(kind, [])) < 8:
                best.setdefault(kind, []).append({"name": name, "qty": int(qty), "revenue": f(rev)})
        cat_rev = (db.session.query(Category.name, func.sum(OrderItem.line_total))
                   .join(Product, Product.category_id == Category.id)
                   .join(OrderItem, OrderItem.product_id == Product.id)
                   .filter(OrderItem.order_id.in_(ids)).group_by(Category.name)
                   .order_by(func.sum(OrderItem.line_total).desc()).all())

    pm = defaultdict(lambda: [0, 0.0])
    for _, _, total, method in in_range:
        pm[method or "unknown"][0] += 1
        pm[method or "unknown"][1] += f(total)

    return {
        "range": {"start": start_day.isoformat(), "end": end_day.isoformat(),
                  "orders": len(in_range), "revenue": round(sum(f(r[2]) for r in in_range), 2)},
        "daily": {"labels": [k.strftime("%d %b") for k in daily], "revenue": [round(v[0], 2) for v in daily.values()],
                  "orders": [v[1] for v in daily.values()]},
        "weekly": {"labels": [f"Wk of {k:%d %b}" for k in weekly], "revenue": [round(v[0], 2) for v in weekly.values()],
                   "orders": [v[1] for v in weekly.values()]},
        "monthly": {"labels": [date(y, m, 1).strftime("%b %Y") for y, m in monthly],
                    "revenue": [round(v, 2) for v in monthly.values()]},
        "yearly": {"labels": [str(y) for y in sorted(yearly)], "revenue": [round(yearly[y], 2) for y in sorted(yearly)]},
        "best_sweets": best.get("sweet", []),
        "best_food": best.get("food", []),
        "categories": {"labels": [c for c, _ in cat_rev], "revenue": [f(v) for _, v in cat_rev]},
        "payment_methods": {"labels": [PAYMENT_METHOD_LABELS.get(k, k.title()) for k in pm],
                            "orders": [v[0] for v in pm.values()], "revenue": [round(v[1], 2) for v in pm.values()]},
    }
