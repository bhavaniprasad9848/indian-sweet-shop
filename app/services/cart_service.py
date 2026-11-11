"""Cart persistence and price calculation (single source of truth for totals)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from ..extensions import db
from ..models import Cart, CartItem, Product, D
from .inventory_service import stock_map

# Festival coupon codes: code -> (kind, value, minimum subtotal, description)
COUPONS = {
    "DIWALI10": ("percent", Decimal("10"), Decimal("30"), "10% off orders above $30"),
    "SWEET5": ("flat", Decimal("5"), Decimal("40"), "$5 off orders above $40"),
}

MAX_QTY_PER_ITEM = 50


def q2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_cart(user, create=True):
    cart = Cart.query.filter_by(user_id=user.id).first()
    if not cart and create:
        cart = Cart(user_id=user.id)
        db.session.add(cart)
        db.session.flush()
    return cart


def cart_count(user):
    cart = Cart.query.filter_by(user_id=user.id).first()
    return sum(i.quantity for i in cart.items) if cart else 0


def add_item(user, product, qty=1):
    if not product.is_active:
        raise ValueError("This product is no longer available.")
    cart = get_cart(user)
    item = CartItem.query.filter_by(cart_id=cart.id, product_id=product.id).first()
    new_qty = (item.quantity if item else 0) + qty
    available = stock_map([product.id]).get(product.id, 0)
    if available <= 0:
        raise ValueError(f"{product.name} is out of stock.")
    if new_qty > min(available, MAX_QTY_PER_ITEM):
        raise ValueError(f"Only {min(available, MAX_QTY_PER_ITEM)} of {product.name} can be added.")
    if item:
        item.quantity = new_qty
    else:
        db.session.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=qty))
    db.session.commit()


def set_quantity(user, product_id, qty):
    cart = get_cart(user)
    item = CartItem.query.filter_by(cart_id=cart.id, product_id=product_id).first_or_404()
    if qty <= 0:
        db.session.delete(item)
    else:
        available = stock_map([product_id]).get(product_id, 0)
        item.quantity = min(qty, available, MAX_QTY_PER_ITEM) or 1
    db.session.commit()


def remove_item(user, product_id):
    set_quantity(user, product_id, 0)


def clear_cart(user):
    cart = get_cart(user, create=False)
    if cart:
        CartItem.query.filter_by(cart_id=cart.id).delete()


def compute_totals(lines, coupon_code=None):
    """lines: list of (product_or_price_holder, qty). Returns dict of Decimal values and per-line rows."""
    cfg = current_app.config
    rate = Decimal(str(cfg["TAX_RATE"]))
    rows, subtotal, tax_total = [], Decimal("0"), Decimal("0")
    for product, qty in lines:
        unit = D(product.price)
        base = q2(unit * qty)
        tax = q2(base * rate)
        rows.append({"product": product, "quantity": qty, "unit_price": unit, "base": base,
                     "tax": tax, "line_total": base + tax})
        subtotal += base
        tax_total += tax

    discount, coupon_note, applied = Decimal("0"), None, None
    if coupon_code:
        c = COUPONS.get(coupon_code.upper())
        if not c:
            coupon_note = "Invalid coupon code."
        elif subtotal < c[2]:
            coupon_note = f"{coupon_code.upper()} needs a subtotal of {cfg['CURRENCY_SYMBOL']}{c[2]}."
        else:
            discount = q2(subtotal * c[1] / 100) if c[0] == "percent" else min(c[1], subtotal)
            applied = coupon_code.upper()
            coupon_note = c[3]

    delivery = Decimal("0")
    if rows and (subtotal - discount) < Decimal(str(cfg["FREE_DELIVERY_ABOVE"])):
        delivery = D(cfg["DELIVERY_CHARGE"])
    grand = q2(subtotal - discount + tax_total + delivery)
    return {"rows": rows, "subtotal": q2(subtotal), "discount": q2(discount), "tax": q2(tax_total),
            "delivery": delivery, "grand_total": grand, "coupon": applied, "coupon_note": coupon_note,
            "tax_rate": rate, "free_delivery_above": Decimal(str(cfg["FREE_DELIVERY_ABOVE"]))}


def cart_summary(user, coupon_code=None):
    cart = get_cart(user, create=False)
    items = list(cart.items) if cart else []
    stocks = stock_map([i.product_id for i in items])
    lines, issues = [], []
    for i in items:
        stock = stocks.get(i.product_id, 0)
        if not i.product.is_active or stock == 0:
            issues.append(f"{i.product.name} is currently unavailable — remove it to continue.")
        elif i.quantity > stock:
            issues.append(f"Only {stock} of {i.product.name} left — please reduce the quantity.")
        lines.append((i.product, i.quantity))
    totals = compute_totals(lines, coupon_code)
    for row in totals["rows"]:
        row["stock"] = stocks.get(row["product"].id, 0)
    totals["issues"] = issues
    totals["item_count"] = sum(q for _, q in lines)
    return totals
