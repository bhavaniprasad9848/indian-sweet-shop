"""Batch inventory: FIFO (first-expiring-first-out) deduction, restocking, expiry tracking."""
from datetime import date, timedelta

from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..models import InventoryBatch, Product, StockTransaction


class InsufficientStock(Exception):
    def __init__(self, product_name, requested, available):
        self.product_name, self.requested, self.available = product_name, requested, available
        super().__init__(f"Only {available} of {product_name} available (requested {requested}).")


def _sellable_filter(q):
    return q.filter(InventoryBatch.expiration_date >= date.today(),
                    InventoryBatch.is_written_off.is_(False),
                    InventoryBatch.quantity_available > 0)


def stock_map(product_ids=None):
    """{product_id: sellable_qty} — expired and written-off batches are excluded."""
    q = db.session.query(InventoryBatch.product_id, func.coalesce(func.sum(InventoryBatch.quantity_available), 0))
    q = _sellable_filter(q)
    if product_ids is not None:
        q = q.filter(InventoryBatch.product_id.in_(list(product_ids) or [0]))
    return {pid: int(qty) for pid, qty in q.group_by(InventoryBatch.product_id).all()}


def available_stock(product_id):
    return stock_map([product_id]).get(product_id, 0)


def nearest_expiry_map(product_ids=None):
    q = db.session.query(InventoryBatch.product_id, func.min(InventoryBatch.expiration_date))
    q = _sellable_filter(q)
    if product_ids is not None:
        q = q.filter(InventoryBatch.product_id.in_(list(product_ids) or [0]))
    return dict(q.group_by(InventoryBatch.product_id).all())


def next_batch_number(product):
    prefix = "".join(w[0] for w in product.name.split()[:3]).upper()
    n = InventoryBatch.query.filter_by(product_id=product.id).count() + 1
    candidate = f"{prefix}{product.id:02d}-{date.today():%y%m%d}-{n:02d}"
    while InventoryBatch.query.filter_by(batch_number=candidate).first():
        n += 1
        candidate = f"{prefix}{product.id:02d}-{date.today():%y%m%d}-{n:02d}"
    return candidate


def add_stock(product, quantity, manufacturing_date=None, expiration_date=None, admin_id=None,
              batch_number=None, note=None, commit=True):
    if quantity <= 0:
        raise ValueError("Quantity must be positive.")
    mfg = manufacturing_date or date.today()
    exp = expiration_date or (mfg + timedelta(days=product.shelf_life_days or 3))
    if exp < mfg:
        raise ValueError("Expiration date cannot be before manufacturing date.")
    batch = InventoryBatch(product_id=product.id, batch_number=batch_number or next_batch_number(product),
                           manufacturing_date=mfg, expiration_date=exp,
                           quantity_received=quantity, quantity_available=quantity)
    db.session.add(batch)
    db.session.flush()
    db.session.add(StockTransaction(product_id=product.id, batch_id=batch.id, admin_id=admin_id,
                                    txn_type="stock_in", quantity=quantity,
                                    note=note or f"New batch {batch.batch_number}"))
    if commit:
        db.session.commit()
    return batch


def check_availability(lines):
    """lines: iterable of (product, qty). Raises InsufficientStock on the first shortfall."""
    stocks = stock_map([p.id for p, _ in lines])
    for product, qty in lines:
        if not product.is_active:
            raise InsufficientStock(product.name, qty, 0)
        if stocks.get(product.id, 0) < qty:
            raise InsufficientStock(product.name, qty, stocks.get(product.id, 0))


def deduct_for_order(order):
    """Deduct stock FIFO by expiry across batches. Caller commits. Idempotent per order."""
    if order.stock_deducted:
        return
    for item in order.items:
        needed = item.quantity
        q = InventoryBatch.query.filter_by(product_id=item.product_id)
        q = _sellable_filter(q).order_by(InventoryBatch.expiration_date, InventoryBatch.manufacturing_date,
                                         InventoryBatch.id)
        batches = q.with_for_update().all()
        if sum(b.quantity_available for b in batches) < needed:
            raise InsufficientStock(item.product_name, needed, sum(b.quantity_available for b in batches))
        for b in batches:
            if needed == 0:
                break
            take = min(b.quantity_available, needed)
            b.quantity_available -= take
            b.quantity_sold += take
            needed -= take
            db.session.add(StockTransaction(product_id=item.product_id, batch_id=b.id, order_id=order.id,
                                            txn_type="sale", quantity=-take,
                                            note=f"Order {order.order_number}"))
    order.stock_deducted = True


def restore_for_order(order, note="Order cancelled"):
    """Return deducted units to the exact batches they came from. Caller commits."""
    if not order.stock_deducted:
        return 0
    restored = 0
    sales = StockTransaction.query.filter_by(order_id=order.id, txn_type="sale").all()
    for t in sales:
        qty = -t.quantity
        batch = db.session.get(InventoryBatch, t.batch_id)
        if batch:
            batch.quantity_available += qty
            batch.quantity_sold -= qty
        db.session.add(StockTransaction(product_id=t.product_id, batch_id=t.batch_id, order_id=order.id,
                                        txn_type="cancel_restore", quantity=qty,
                                        note=f"{note} · {order.order_number}"))
        restored += qty
    order.stock_deducted = False
    return restored


def adjust_batch(batch, new_available, admin_id=None, note=None):
    delta = new_available - batch.quantity_available
    if new_available < 0:
        raise ValueError("Quantity cannot be negative.")
    if delta == 0:
        return
    batch.quantity_available = new_available
    db.session.add(StockTransaction(product_id=batch.product_id, batch_id=batch.id, admin_id=admin_id,
                                    txn_type="adjustment", quantity=delta, note=note or "Manual adjustment"))
    db.session.commit()


def write_off_batch(batch, admin_id=None, note="Expired stock written off"):
    if batch.quantity_available:
        db.session.add(StockTransaction(product_id=batch.product_id, batch_id=batch.id, admin_id=admin_id,
                                        txn_type="writeoff", quantity=-batch.quantity_available, note=note))
    batch.quantity_available = 0
    batch.is_written_off = True
    db.session.commit()


# ------------------------------------------------------------------ expiry
def expiry_level(exp_date, today=None):
    """Return (key, label, css colour class) for a date."""
    today = today or date.today()
    days = (exp_date - today).days
    if days < 0:
        return "expired", "Expired", "danger"
    if days == 0:
        return "today", "Expires today", "orange"
    if days <= 3:
        return "3days", f"{days} day{'s' if days > 1 else ''} left", "orange"
    if days <= 7:
        return "7days", f"{days} days left", "warning"
    return "fresh", f"{days} days left", "success"


def expiry_buckets(include_empty=False):
    """Active (not written-off) batches grouped into the five expiry sections."""
    q = InventoryBatch.query.join(Product).filter(InventoryBatch.is_written_off.is_(False))
    if not include_empty:
        q = q.filter(InventoryBatch.quantity_available > 0)
    buckets = {"expired": [], "today": [], "3days": [], "7days": [], "fresh": []}
    for b in q.order_by(InventoryBatch.expiration_date, InventoryBatch.id).all():
        buckets[expiry_level(b.expiration_date)[0]].append(b)
    return buckets


def low_stock_products(threshold=None):
    threshold = threshold if threshold is not None else current_app.config["LOW_STOCK_THRESHOLD"]
    stocks = stock_map()
    prods = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return [(p, stocks.get(p.id, 0)) for p in prods if stocks.get(p.id, 0) <= threshold]
