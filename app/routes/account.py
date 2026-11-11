"""Customer account: profile, saved addresses, order history, tracking, cancellation, documents."""
import io

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Address, Order, ORDER_STATUSES
from ..services.invoice_service import build_credit_note_pdf, build_invoice_pdf
from ..services.order_service import OrderError, can_cancel, cancel_order
from ..utils.security import customer_required
from ..utils.validators import clean, validate_address, validate_name, validate_password, validate_phone

bp = Blueprint("account", __name__)

TRACK_STEPS = ["confirmed", "preparing", "ready_for_pickup", "out_for_delivery", "delivered"]


def _own(number):
    order = Order.query.filter_by(order_number=number).first()
    if not order or order.user_id != current_user.id:
        abort(404)  # customers can only ever see their own orders
    return order


@bp.route("/", methods=["GET", "POST"])
@customer_required
def profile():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name, phone = clean(request.form.get("name"), 120), clean(request.form.get("phone"), 20)
            err = validate_name(name) or validate_phone(phone)
            if err:
                flash(err, "danger")
            else:
                current_user.name, current_user.phone = name, phone
                db.session.commit()
                flash("Profile updated.", "success")
        elif action == "password":
            cur, new, conf = (request.form.get(k, "") for k in ("current", "new", "confirm"))
            if not current_user.check_password(cur):
                flash("Your current password is incorrect.", "danger")
            elif new != conf:
                flash("New passwords don't match.", "danger")
            elif validate_password(new):
                flash(validate_password(new), "danger")
            else:
                current_user.set_password(new)
                db.session.commit()
                flash("Password changed.", "success")
        return redirect(url_for("account.profile"))
    recent = current_user.orders.filter(Order.status != "pending").order_by(Order.created_at.desc()).limit(3).all()
    stats = {"orders": current_user.orders.filter(Order.status != "pending").count(),
             "addresses": current_user.addresses.count()}
    return render_template("account/profile.html", recent=recent, stats=stats)


@bp.route("/addresses", methods=["GET", "POST"])
@customer_required
def addresses():
    if request.method == "POST":
        data, errors = validate_address(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            addr_id = request.form.get("address_id", type=int)
            if addr_id:
                a = Address.query.filter_by(id=addr_id, user_id=current_user.id).first_or_404()
                for k, v in data.items():
                    setattr(a, k, v)
            else:
                a = Address(user_id=current_user.id, **data)
                db.session.add(a)
            if request.form.get("is_default") or current_user.addresses.count() == 0:
                current_user.addresses.update({"is_default": False})
                a.is_default = True
            db.session.commit()
            flash("Address saved.", "success")
        return redirect(url_for("account.addresses"))
    items = current_user.addresses.order_by(Address.is_default.desc(), Address.id).all()
    return render_template("account/addresses.html", addresses=items)


@bp.route("/addresses/<int:addr_id>/delete", methods=["POST"])
@customer_required
def delete_address(addr_id):
    a = Address.query.filter_by(id=addr_id, user_id=current_user.id).first_or_404()
    db.session.delete(a)
    db.session.commit()
    flash("Address removed.", "info")
    return redirect(url_for("account.addresses"))


@bp.route("/addresses/<int:addr_id>/default", methods=["POST"])
@customer_required
def default_address(addr_id):
    a = Address.query.filter_by(id=addr_id, user_id=current_user.id).first_or_404()
    current_user.addresses.update({"is_default": False})
    a.is_default = True
    db.session.commit()
    return redirect(url_for("account.addresses"))


@bp.route("/orders")
@customer_required
def orders():
    status = request.args.get("status", "")
    q = current_user.orders.filter(Order.status != "pending")
    if status in dict(ORDER_STATUSES):
        q = q.filter(Order.status == status)
    drafts = current_user.orders.filter(Order.status == "pending").order_by(Order.created_at.desc()).all()
    return render_template("account/orders.html", orders=q.order_by(Order.created_at.desc()).all(),
                           drafts=drafts, status=status)


@bp.route("/orders/<number>")
@customer_required
def order_detail(number):
    order = _own(number)
    reached = {h.status: h.created_at for h in order.history}
    return render_template("account/order_detail.html", order=order, steps=TRACK_STEPS, reached=reached,
                           cancellable=can_cancel(order) and order.status != "pending")


@bp.route("/orders/<number>/cancel", methods=["POST"])
@customer_required
def cancel(number):
    order = _own(number)
    try:
        canc = cancel_order(order, by="customer", reason=clean(request.form.get("reason"), 300))
        if canc.refund_amount:
            flash(f"Order cancelled. A refund of {current_app.config['CURRENCY_SYMBOL']}{canc.refund_amount:.2f} has been issued to your original "
                  "payment method.", "success")
        else:
            flash("Order cancelled. A confirmation email is on its way.", "success")
    except OrderError as e:
        flash(str(e), "danger")
    return redirect(url_for("account.order_detail", number=number))


@bp.route("/orders/<number>/invoice.pdf")
@customer_required
def invoice_pdf(number):
    order = _own(number)
    if not order.invoice:
        abort(404)
    return send_file(io.BytesIO(build_invoice_pdf(order)), mimetype="application/pdf",
                     download_name=f"Invoice-{order.invoice.invoice_number}.pdf",
                     as_attachment=request.args.get("download") == "1")


@bp.route("/orders/<number>/credit-note.pdf")
@customer_required
def credit_note_pdf(number):
    order = _own(number)
    if not order.cancellation or not order.cancellation.credit_note_number:
        abort(404)
    return send_file(io.BytesIO(build_credit_note_pdf(order)), mimetype="application/pdf",
                     download_name=f"CreditNote-{order.cancellation.credit_note_number}.pdf")
