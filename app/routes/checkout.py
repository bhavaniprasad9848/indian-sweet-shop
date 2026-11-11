"""Checkout → OTP verification → payment → confirmation.

The order stays ``pending`` (a temporary draft) until both the OTP and the payment are verified.
Payment pages refuse to charge an order that already has a succeeded payment, and each payment
form carries a one-time nonce so a double-submit or browser retry cannot charge twice.
"""
import secrets

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user

from ..extensions import csrf, db
from ..models import Address, Order
from ..services import cart_service, payment_service as ps
from ..services.order_service import OrderError, confirm_order, create_pending_order
from ..services.otp_service import OTPError, issue_otp, seconds_until_resend, verify_otp
from ..utils.helpers import mask_email
from ..utils.security import client_ip, customer_required
from ..utils.validators import clean, to_int, validate_address, validate_email

bp = Blueprint("checkout", __name__)


def _own_order(number):
    order = Order.query.filter_by(order_number=number).first()
    if not order or order.user_id != current_user.id:
        abort(404)
    return order


def _send_order_otp(order):
    code = issue_otp(order.customer_email, "order", order.id, ip=client_ip(),
                     context={"order_number": order.order_number, "total": order.grand_total})
    if current_app.config["SHOW_DEV_OTP"] and not current_app.config["MAIL_SERVER"]:
        flash(f"Dev mode (SMTP not configured): your order code is {code}", "dev")


@bp.route("/", methods=["GET", "POST"])
@customer_required
def checkout():
    coupon = session.get("coupon")
    summary = cart_service.cart_summary(current_user, coupon)
    if not summary["rows"]:
        flash("Your cart is empty.", "info")
        return redirect(url_for("main.shop"))
    addresses = current_user.addresses.order_by(Address.is_default.desc(), Address.id).all()
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        contact_email = clean(form.get("email"), 255).lower()
        addr_id = to_int(form.get("address_id"), 0)
        errors = []
        if addr_id:
            a = Address.query.filter_by(id=addr_id, user_id=current_user.id).first()
            if not a:
                abort(400)
            addr = {k: getattr(a, k) for k in ("full_name", "phone", "line1", "line2", "city", "state", "zip_code")}
        else:
            addr, errors = validate_address(form)
        if validate_email(contact_email):
            errors.append(validate_email(contact_email))
        if summary["issues"]:
            errors.extend(summary["issues"])
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            if not addr_id and form.get("save_address"):
                db.session.add(Address(user_id=current_user.id, is_default=not addresses, **addr))
                db.session.commit()
            billing = None
            if form.get("billing_different"):
                billing = clean(form.get("billing_address"), 400) or None
            try:
                order = create_pending_order(
                    current_user, {"full_name": addr["full_name"], "email": contact_email, "phone": addr["phone"]},
                    addr, clean(form.get("instructions"), 300), coupon, billing)
                _send_order_otp(order)
                flash(f"We've sent a confirmation code to {mask_email(order.customer_email)}.", "info")
                return redirect(url_for("checkout.verify", number=order.order_number))
            except (OrderError, OTPError) as e:
                flash(str(e), "danger")
    return render_template("checkout/checkout.html", s=summary, addresses=addresses, form=form)


@bp.route("/<number>/verify", methods=["GET", "POST"])
@customer_required
def verify(number):
    order = _own_order(number)
    if order.status != "pending":
        return redirect(url_for("checkout.success", number=number))
    if order.otp_verified:
        return redirect(url_for("checkout.pay", number=number))
    if request.method == "POST":
        code = "".join(request.form.getlist("otp")) or request.form.get("code", "")
        ok, msg = verify_otp(order.customer_email, "order", code, order.id)
        if ok:
            order.otp_verified = True
            db.session.commit()
            flash("Order verified. Choose how you'd like to pay.", "success")
            return redirect(url_for("checkout.pay", number=number))
        flash(msg, "danger")
    return render_template("checkout/verify.html", order=order, email=mask_email(order.customer_email),
                           wait=seconds_until_resend(order.customer_email, "order", order.id))


@bp.route("/<number>/verify/resend", methods=["POST"])
@customer_required
def resend(number):
    order = _own_order(number)
    if order.status == "pending" and not order.otp_verified:
        try:
            _send_order_otp(order)
            flash("A new code has been sent.", "info")
        except OTPError as e:
            flash(str(e), "warning")
    return redirect(url_for("checkout.verify", number=number))


def _new_nonce(order):
    nonce = secrets.token_urlsafe(16)
    session[f"paynonce:{order.order_number}"] = nonce
    return nonce


def _consume_nonce(order, value):
    key = f"paynonce:{order.order_number}"
    expected = session.pop(key, None)
    return bool(expected) and secrets.compare_digest(expected, value or "")


@bp.route("/<number>/pay", methods=["GET", "POST"])
@customer_required
def pay(number):
    order = _own_order(number)
    if order.status != "pending" or order.successful_payment:
        return redirect(url_for("checkout.success", number=number))
    if not order.otp_verified:
        return redirect(url_for("checkout.verify", number=number))

    if request.method == "POST":
        if not _consume_nonce(order, request.form.get("nonce")):
            flash("This payment was already submitted. Please check your orders before trying again.", "warning")
            return redirect(url_for("checkout.pay", number=number))
        method = request.form.get("method")
        try:
            if method == "cod":
                if not current_app.config["ENABLE_COD"]:
                    abort(400)
                confirm_order(order, cod=True)
                session.pop("coupon", None)
                return redirect(url_for("checkout.success", number=number))
            resp = ps.simulated_charge(order, method, request.form)
            if not ps.verify_simulated_response(order, resp):
                raise ps.PaymentError("Payment signature verification failed.")
            payment = ps.record_payment(order, resp, "simulated")
            db.session.commit()
            if payment.status != "succeeded":
                flash(f"Payment failed: {payment.failure_reason} No money was taken.", "danger")
            else:
                confirm_order(order, payment)
                session.pop("coupon", None)
                return redirect(url_for("checkout.success", number=number))
        except ps.PaymentError as e:
            flash(str(e), "danger")
        except OrderError as e:
            flash(str(e), "danger")
            return redirect(url_for("account.order_detail", number=number))
    return render_template("checkout/pay.html", order=order, nonce=_new_nonce(order),
                           stripe=ps.stripe_enabled(), cod=current_app.config["ENABLE_COD"])


@bp.route("/<number>/stripe", methods=["POST"])
@customer_required
def stripe_start(number):
    order = _own_order(number)
    if order.status != "pending" or not order.otp_verified or not ps.stripe_enabled():
        return redirect(url_for("checkout.pay", number=number))
    try:
        url = ps.create_stripe_session(order, url_for("checkout.stripe_return", number=number, _external=True),
                                       url_for("checkout.pay", number=number, _external=True))
    except Exception as e:  # noqa: BLE001 - surface any Stripe error to the user
        current_app.logger.exception("Stripe session failed")
        flash(f"Couldn't start Stripe checkout: {e}", "danger")
        return redirect(url_for("checkout.pay", number=number))
    return redirect(url, code=303)


@bp.route("/<number>/stripe/return")
@customer_required
def stripe_return(number):
    order = _own_order(number)
    if order.status != "pending":
        return redirect(url_for("checkout.success", number=number))
    try:
        resp = ps.verify_stripe_session(order, request.args.get("session_id", ""))
        payment = ps.record_payment(order, resp, "stripe")
        db.session.commit()
        confirm_order(order, payment)
        session.pop("coupon", None)
        return redirect(url_for("checkout.success", number=number))
    except (ps.PaymentError, OrderError) as e:
        flash(str(e), "danger")
    except Exception:
        current_app.logger.exception("Stripe verification failed")
        flash("We couldn't verify the payment with Stripe yet. If you were charged, it will confirm shortly.", "warning")
    return redirect(url_for("checkout.pay", number=number))


@bp.route("/webhooks/stripe", methods=["POST"])
@csrf.exempt
def stripe_webhook():
    secret = current_app.config["STRIPE_WEBHOOK_SECRET"]
    if not secret:
        abort(404)
    import stripe
    try:
        event = stripe.Webhook.construct_event(request.data, request.headers.get("Stripe-Signature", ""), secret)
    except Exception:
        abort(400)
    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        order = Order.query.filter_by(order_number=obj.get("client_reference_id")).first()
        if order and order.status == "pending" and order.otp_verified:
            try:
                resp = ps.verify_stripe_session(order, obj["id"])
                payment = ps.record_payment(order, resp, "stripe")
                db.session.commit()
                confirm_order(order, payment)
            except Exception:
                current_app.logger.exception("Webhook confirmation failed")
    return jsonify(received=True)


@bp.route("/<number>/success")
@customer_required
def success(number):
    order = _own_order(number)
    if order.status == "pending":
        return redirect(url_for("checkout.pay", number=number))
    return render_template("checkout/success.html", order=order, payment=order.successful_payment)
