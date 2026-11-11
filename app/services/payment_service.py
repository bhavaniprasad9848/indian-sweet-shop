"""Payment gateways.

* ``simulated`` — an offline test gateway (no keys). It validates cards/UPI the way a gateway would,
  signs its response with HMAC, and the server verifies that signature before accepting payment.
* ``stripe`` — Stripe Checkout in test mode. Payment is confirmed by retrieving the Checkout Session
  server-side and checking status, amount and order reference (plus an optional webhook).

Card data posted to the simulated gateway is used only to compute brand/last4 and is never stored.
"""
import hashlib
import hmac
import re
from datetime import date, datetime
from decimal import Decimal

from flask import current_app

from ..extensions import db
from ..models import Payment, D
from ..utils.helpers import generate_txn_id


class PaymentError(Exception):
    pass


# Stripe-style test numbers so the simulated gateway behaves like real test mode
DECLINE_CARDS = {
    "4000000000000002": "Your card was declined.",
    "4000000000009995": "Your card has insufficient funds.",
    "4000000000000069": "Your card has expired.",
}
UPI_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,64}@[A-Za-z]{2,32}$")


def gateway_name():
    return current_app.config["PAYMENT_GATEWAY"]


def stripe_enabled():
    return gateway_name() == "stripe" and bool(current_app.config["STRIPE_SECRET_KEY"])


def to_cents(amount):
    return int((D(amount) * 100).to_integral_value())


def luhn_ok(number):
    digits = [int(c) for c in number][::-1]
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(digits))
    return total % 10 == 0


def card_brand(number):
    if number.startswith("4"):
        return "Visa"
    if re.match(r"^(5[1-5]|2[2-7])", number):
        return "Mastercard"
    if re.match(r"^3[47]", number):
        return "Amex"
    if re.match(r"^(6011|65|64[4-9])", number):
        return "Discover"
    if re.match(r"^(60|65|81|82|508)", number):
        return "RuPay"
    return "Card"


def _sign(order_number, txn_id, amount_cents):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{order_number}|{txn_id}|{amount_cents}".encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ simulated gateway
def simulated_charge(order, method, form):
    """Run a test charge. Returns a gateway response dict (never contains the PAN)."""
    amount_cents = to_cents(order.grand_total)
    if method == "card":
        number = re.sub(r"\D", "", form.get("card_number", ""))
        exp = (form.get("card_expiry") or "").strip()
        cvc = (form.get("card_cvc") or "").strip()
        name = (form.get("card_name") or "").strip()
        if not (12 <= len(number) <= 19) or not luhn_ok(number):
            raise PaymentError("That card number isn't valid.")
        m = re.match(r"^(\d{2})\s*/\s*(\d{2}|\d{4})$", exp)
        if not m:
            raise PaymentError("Enter the expiry as MM/YY.")
        month, year = int(m.group(1)), int(m.group(2))
        year = year + 2000 if year < 100 else year
        if not 1 <= month <= 12 or (year, month) < (date.today().year, date.today().month):
            raise PaymentError("Your card has expired.")
        if not re.match(r"^\d{3,4}$", cvc):
            raise PaymentError("Enter a valid CVC.")
        if len(name) < 2:
            raise PaymentError("Enter the name on the card.")
        last4, brand = number[-4:], card_brand(number)
        decline = DECLINE_CARDS.get(number)
        del number, cvc  # explicitly drop sensitive values
        txn = generate_txn_id("pay_sim")
        resp = {"status": "failed" if decline else "succeeded", "transaction_id": txn, "method": "card",
                "card_brand": brand, "card_last4": last4, "failure_reason": decline,
                "amount_cents": amount_cents}
    elif method == "upi":
        vpa = (form.get("upi_id") or "").strip().lower()
        if not UPI_RE.match(vpa):
            raise PaymentError("Enter a valid UPI ID, e.g. name@okbank.")
        failed = vpa.startswith("failure@")
        handle, _, bank = vpa.partition("@")
        txn = generate_txn_id("upi_sim")
        resp = {"status": "failed" if failed else "succeeded", "transaction_id": txn, "method": "upi",
                "upi_masked": f"{handle[:2]}***@{bank}", "failure_reason": "UPI request was declined." if failed else None,
                "amount_cents": amount_cents}
    else:
        raise PaymentError("Unsupported payment method.")
    resp["signature"] = _sign(order.order_number, resp["transaction_id"], amount_cents)
    return resp


def verify_simulated_response(order, resp):
    expected = _sign(order.order_number, resp["transaction_id"], to_cents(order.grand_total))
    return hmac.compare_digest(expected, resp.get("signature", "")) and resp["amount_cents"] == to_cents(order.grand_total)


# ------------------------------------------------------------------ stripe
def _stripe():
    import stripe
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe


def create_stripe_session(order, success_url, cancel_url):
    stripe = _stripe()
    cur = current_app.config["CURRENCY"].lower()
    line_items = [{
        "price_data": {"currency": cur, "unit_amount": to_cents(order.grand_total),
                       "product_data": {"name": f"{current_app.config['STORE_NAME']} order {order.order_number}",
                                        "description": ", ".join(f"{i.product_name} × {i.quantity}" for i in order.items)[:500]}},
        "quantity": 1,
    }]
    session = stripe.checkout.Session.create(
        mode="payment", line_items=line_items, customer_email=order.customer_email,
        client_reference_id=order.order_number, metadata={"order_number": order.order_number},
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}", cancel_url=cancel_url,
        idempotency_key=f"checkout-{order.order_number}-{to_cents(order.grand_total)}",
    )
    pay = Payment.query.filter_by(order_id=order.id, gateway_reference=session.id).first()
    if not pay:
        db.session.add(Payment(order_id=order.id, gateway="stripe", method="stripe", amount=order.grand_total,
                               currency=cur.upper(), status="initiated", gateway_reference=session.id))
        db.session.commit()
    return session.url


def verify_stripe_session(order, session_id):
    """Retrieve the session from Stripe and return a gateway response dict if it is genuinely paid."""
    stripe = _stripe()
    s = stripe.checkout.Session.retrieve(session_id, expand=["payment_intent.latest_charge"])
    if s.client_reference_id != order.order_number:
        raise PaymentError("Payment does not belong to this order.")
    if s.payment_status != "paid":
        raise PaymentError("Payment has not completed.")
    if s.amount_total != to_cents(order.grand_total):
        raise PaymentError("Paid amount does not match the order total.")
    pi = s.payment_intent
    brand = last4 = None
    try:
        card = pi.latest_charge.payment_method_details.card
        brand, last4 = card.brand.title(), card.last4
    except AttributeError:
        pass
    return {"status": "succeeded", "transaction_id": pi.id, "method": "stripe", "card_brand": brand,
            "card_last4": last4, "gateway_reference": s.id}


# ------------------------------------------------------------------ recording
def record_payment(order, resp, gateway):
    """Persist a gateway response idempotently and return the Payment row."""
    existing = Payment.query.filter_by(transaction_id=resp["transaction_id"]).first()
    if existing:
        return existing
    pay = None
    if resp.get("gateway_reference"):
        pay = Payment.query.filter_by(order_id=order.id, gateway_reference=resp["gateway_reference"]).first()
    if not pay:
        pay = Payment(order_id=order.id, gateway=gateway, amount=order.grand_total,
                      currency=current_app.config["CURRENCY"].upper())
        db.session.add(pay)
    pay.method = resp["method"]
    pay.transaction_id = resp["transaction_id"]
    pay.status = resp["status"]
    pay.card_brand = resp.get("card_brand")
    pay.card_last4 = resp.get("card_last4")
    pay.upi_handle_masked = resp.get("upi_masked")
    pay.failure_reason = resp.get("failure_reason")
    if resp["status"] == "succeeded":
        pay.verified_at = datetime.utcnow()
    db.session.flush()
    return pay


def refund_payment(payment, amount):
    """Issue a refund through the original gateway. Returns (status, gateway_refund_id, note)."""
    if payment.gateway == "stripe":
        try:
            stripe = _stripe()
            r = stripe.Refund.create(payment_intent=payment.transaction_id, amount=to_cents(amount),
                                     idempotency_key=f"refund-{payment.transaction_id}-{to_cents(amount)}")
            return ("processed" if r.status in ("succeeded", "pending") else "failed"), r.id, f"Stripe: {r.status}"
        except Exception as exc:
            current_app.logger.exception("Stripe refund failed")
            return "failed", None, str(exc)[:250]
    if payment.gateway == "simulated":
        return "processed", generate_txn_id("rf_sim"), "Refunded to original payment method"
    if payment.gateway == "cod":
        return "processed", generate_txn_id("rf_cash"), "Cash refund recorded"
    return "failed", None, "Unknown gateway"
