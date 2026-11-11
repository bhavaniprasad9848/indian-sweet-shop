from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Product
from ..services import cart_service
from ..utils.security import customer_required
from ..utils.validators import clean, to_int

bp = Blueprint("cart", __name__)


def _wants_json():
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


@bp.route("/")
@customer_required
def view():
    summary = cart_service.cart_summary(current_user, session.get("coupon"))
    if session.get("coupon") and not summary["coupon"]:
        flash(summary["coupon_note"], "warning")
        session.pop("coupon", None)
    return render_template("cart/cart.html", s=summary, coupons=cart_service.COUPONS)


@bp.route("/add", methods=["POST"])
def add():
    if not current_user.is_authenticated or current_user.is_admin:
        if _wants_json():
            return jsonify(ok=False, login=url_for("auth.login", next=request.referrer and url_for("main.shop"))), 401
        flash("Please sign in to add sweets to your cart.", "warning")
        return redirect(url_for("auth.login", next=url_for("main.shop")))
    pid = to_int(request.form.get("product_id"), lo=1)
    qty = to_int(request.form.get("quantity"), 1, lo=1, hi=10000)
    product = db.session.get(Product, pid) if pid else None
    if not product:
        return (jsonify(ok=False, error="Product not found."), 404) if _wants_json() else redirect(url_for("main.shop"))
    try:
        cart_service.add_item(current_user, product, qty)
        msg, ok = f"{product.name} added to your cart.", True
    except ValueError as e:
        msg, ok = str(e), False
    if _wants_json():
        return jsonify(ok=ok, message=msg, count=cart_service.cart_count(current_user)), (200 if ok else 400)
    flash(msg, "success" if ok else "warning")
    return redirect(request.referrer or url_for("cart.view"))


@bp.route("/update", methods=["POST"])
@customer_required
def update():
    pid = to_int(request.form.get("product_id"), lo=1)
    qty = to_int(request.form.get("quantity"), 0, lo=0, hi=cart_service.MAX_QTY_PER_ITEM)
    if pid:
        cart_service.set_quantity(current_user, pid, qty)
    if _wants_json():
        s = cart_service.cart_summary(current_user, session.get("coupon"))
        return jsonify(ok=True, count=s["item_count"])
    return redirect(url_for("cart.view"))


@bp.route("/remove", methods=["POST"])
@customer_required
def remove():
    pid = to_int(request.form.get("product_id"), lo=1)
    if pid:
        cart_service.remove_item(current_user, pid)
        flash("Item removed from your cart.", "info")
    return redirect(url_for("cart.view"))


@bp.route("/coupon", methods=["POST"])
@customer_required
def coupon():
    if request.form.get("action") == "remove":
        session.pop("coupon", None)
        flash("Coupon removed.", "info")
        return redirect(request.referrer or url_for("cart.view"))
    code = clean(request.form.get("code"), 20).upper()
    s = cart_service.cart_summary(current_user, code)
    if s["coupon"]:
        session["coupon"] = code
        flash(f"Coupon {code} applied — {s['coupon_note']}.", "success")
    else:
        flash(s["coupon_note"] or "Invalid coupon.", "warning")
    return redirect(request.referrer or url_for("cart.view"))
