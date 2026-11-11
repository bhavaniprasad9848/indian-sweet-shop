"""Order lifecycle: pending → OTP verified → paid/COD → confirmed → … → delivered | cancelled/refunded."""
from datetime import datetime
from decimal import Decimal

from flask import current_app

from ..extensions import db
from ..models import (Cancellation, Invoice, Order, OrderItem, OrderStatusHistory, Payment, Refund, D,
                      STATUS_LABELS)
from ..utils.helpers import generate_doc_number, generate_order_number, generate_txn_id
from . import inventory_service as inv
from .cart_service import cart_summary, clear_cart
from .payment_service import refund_payment


class OrderError(Exception):
    pass


ADMIN_TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"preparing", "ready_for_pickup", "out_for_delivery", "cancelled"},
    "preparing": {"ready_for_pickup", "out_for_delivery", "cancelled"},
    "ready_for_pickup": {"out_for_delivery", "delivered", "cancelled"},
    "out_for_delivery": {"delivered", "cancelled"},
    "delivered": {"refunded"},
    "cancelled": {"refunded"},
    "refunded": set(),
}


def add_history(order, status, note=None, by=None):
    db.session.add(OrderStatusHistory(order_id=order.id, status=status, note=note, changed_by=by))


# ------------------------------------------------------------------ creation
def create_pending_order(user, contact, address, instructions=None, coupon=None, billing_address=None):
    summary = cart_summary(user, coupon)
    if not summary["rows"]:
        raise OrderError("Your cart is empty.")
    if summary["issues"]:
        raise OrderError(summary["issues"][0])
    try:
        inv.check_availability([(r["product"], r["quantity"]) for r in summary["rows"]])
    except inv.InsufficientStock as e:
        raise OrderError(str(e))

    # A user only ever has one unpaid draft order — older drafts are discarded.
    for old in Order.query.filter_by(user_id=user.id, status="pending", payment_status="unpaid").all():
        if old.payments.count() == 0:
            db.session.delete(old)
    db.session.flush()

    order = Order(order_number=generate_order_number(), user_id=user.id, status="pending",
                  customer_name=contact["full_name"], customer_email=contact["email"].lower(),
                  customer_phone=contact["phone"], ship_line1=address["line1"], ship_line2=address.get("line2"),
                  ship_city=address["city"], ship_state=address["state"], ship_zip=address["zip_code"],
                  delivery_instructions=instructions or None,
                  subtotal=summary["subtotal"], discount=summary["discount"], tax_amount=summary["tax"],
                  delivery_charge=summary["delivery"], grand_total=summary["grand_total"])
    order.billing_address = billing_address or order.shipping_address
    db.session.add(order)
    db.session.flush()
    for r in summary["rows"]:
        p = r["product"]
        db.session.add(OrderItem(order_id=order.id, product_id=p.id, product_name=p.name,
                                 category_kind=p.category.kind, unit_label=p.unit_label,
                                 unit_price=r["unit_price"], quantity=r["quantity"], tax_amount=r["tax"],
                                 line_total=r["line_total"]))
    add_history(order, "pending", "Order placed, awaiting verification", "customer")
    db.session.commit()
    return order


# ------------------------------------------------------------------ confirmation
def _create_invoice(order, amount_paid):
    if order.invoice:
        return order.invoice
    invoice = Invoice(invoice_number=f"TMP-{order.order_number}", order_id=order.id,
                      subtotal=order.subtotal, discount=order.discount, tax_amount=order.tax_amount,
                      delivery_charge=order.delivery_charge, grand_total=order.grand_total,
                      amount_paid=amount_paid)
    db.session.add(invoice)
    db.session.flush()
    invoice.invoice_number = generate_doc_number("INV", invoice.id)
    order.invoice = invoice
    return invoice


def confirm_order(order, payment=None, cod=False):
    """Idempotently confirm a verified order. Returns True if this call confirmed it."""
    if order.status != "pending":
        return False
    if not order.otp_verified:
        raise OrderError("Order must be verified with OTP before confirmation.")
    if not cod and (payment is None or payment.status != "succeeded"):
        raise OrderError("Payment has not been verified.")

    try:
        inv.deduct_for_order(order)
    except inv.InsufficientStock as e:
        db.session.rollback()
        # Stock ran out between checkout and payment: cancel and refund automatically.
        order = db.session.get(Order, order.id)
        if payment is not None:
            payment = db.session.get(Payment, payment.id)
        _system_cancel_out_of_stock(order, payment, str(e))
        raise OrderError(f"{e} Your payment has been refunded in full.")

    now = datetime.utcnow()
    order.status = "confirmed"
    order.confirmed_at = now
    if cod:
        order.payment_method = "cod"
        order.payment_status = "pending"
        db.session.add(Payment(order_id=order.id, gateway="cod", method="cod", amount=order.grand_total,
                               currency=current_app.config["CURRENCY"].upper(), status="initiated",
                               transaction_id=generate_txn_id("cod")))
        amount_paid = Decimal("0")
    else:
        order.payment_method = payment.method
        order.payment_status = "paid"
        amount_paid = D(payment.amount)
    _create_invoice(order, amount_paid)
    add_history(order, "confirmed", "Payment verified" if not cod else "Cash on Delivery order confirmed", "system")
    clear_cart(order.user)
    db.session.commit()

    from .invoice_service import save_invoice_pdf
    from .email_service import send_order_confirmation
    try:
        save_invoice_pdf(order)
        send_order_confirmation(order)
    except Exception:  # invoice/email failure must not undo a paid order
        current_app.logger.exception("Post-confirmation invoice/email failed for %s", order.order_number)
    return True


def _system_cancel_out_of_stock(order, payment, reason):
    refund_amt = D(payment.amount) if payment is not None and payment.status == "succeeded" else Decimal("0")
    canc = Cancellation(order_id=order.id, cancelled_by="system", reason=reason,
                        original_amount=order.grand_total, refund_amount=refund_amt)
    db.session.add(canc)
    db.session.flush()
    if refund_amt:
        _issue_refund(order, payment, canc, refund_amt)
    order.status = "refunded" if refund_amt else "cancelled"
    order.cancelled_at = datetime.utcnow()
    add_history(order, order.status, reason, "system")
    db.session.commit()


# ------------------------------------------------------------------ cancellation
def can_cancel(order):
    return order.status in current_app.config["CANCELLABLE_STATUSES"]


def _issue_refund(order, payment, canc, amount):
    status, ref_id, note = ("processed", None, None)
    if payment is not None:
        status, ref_id, note = refund_payment(payment, amount)
    refund = Refund(order_id=order.id, payment_id=payment.id if payment else None, cancellation_id=canc.id,
                    amount=amount, status=status, gateway_refund_id=ref_id, note=note,
                    processed_at=datetime.utcnow() if status == "processed" else None)
    db.session.add(refund)
    if payment is not None and status == "processed":
        payment.status = "refunded" if D(amount) >= D(payment.amount) else "partially_refunded"
        order.payment_status = "refunded"
    canc.credit_note_number = generate_doc_number("CN", canc.id)
    return refund


def cancel_order(order, by="customer", reason=None, force=False):
    if order.cancellation or order.status in ("cancelled", "refunded"):
        raise OrderError("This order has already been cancelled.")
    if not force and not can_cancel(order):
        raise OrderError(f"Orders that are '{order.status_label}' can no longer be cancelled.")

    was_pending = order.status == "pending"
    inv.restore_for_order(order)
    payment = order.successful_payment
    refund_amt = D(payment.amount) if payment and order.payment_status == "paid" else Decimal("0")

    canc = Cancellation(order_id=order.id, cancelled_by=by, reason=(reason or "")[:300] or None,
                        original_amount=order.grand_total, refund_amount=refund_amt)
    db.session.add(canc)
    db.session.flush()
    if refund_amt > 0:
        refund = _issue_refund(order, payment, canc, refund_amt)
        order.status = "refunded" if refund.status == "processed" else "cancelled"
    else:
        order.status = "cancelled"
        if order.payment_status == "pending":  # COD never collected
            order.payment_status = "cancelled"
            cod = order.payments.filter_by(gateway="cod").first()
            if cod:
                cod.status = "failed"
                cod.failure_reason = "Order cancelled before delivery"
    order.cancelled_at = datetime.utcnow()
    add_history(order, order.status, reason or f"Cancelled by {by}", by)
    db.session.commit()

    if order.invoice and canc.credit_note_number:
        from .invoice_service import save_credit_note_pdf
        try:
            save_credit_note_pdf(order)
            db.session.commit()
        except Exception:
            current_app.logger.exception("Credit note generation failed")
    if not was_pending:
        from .email_service import send_cancellation_email
        try:
            send_cancellation_email(order)
        except Exception:
            current_app.logger.exception("Cancellation email failed")
    return canc


# ------------------------------------------------------------------ admin status updates
def update_status(order, new_status, admin_name="admin", note=None, notify=True):
    if new_status not in STATUS_LABELS:
        raise OrderError("Unknown status.")
    if new_status == order.status:
        return
    if new_status not in ADMIN_TRANSITIONS.get(order.status, set()):
        raise OrderError(f"Can't move an order from {order.status_label} to {STATUS_LABELS[new_status]}.")
    if new_status == "cancelled":
        cancel_order(order, by="admin", reason=note or "Cancelled by store", force=True)
        return
    if new_status == "refunded":
        _refund_after_delivery(order, admin_name, note)
        return

    order.status = new_status
    if new_status == "delivered":
        order.delivered_at = datetime.utcnow()
        if order.payment_method == "cod" and order.payment_status == "pending":
            cod = order.payments.filter_by(gateway="cod").first()
            if cod:
                cod.status = "succeeded"
                cod.verified_at = datetime.utcnow()
            order.payment_status = "paid"
            if order.invoice:
                order.invoice.amount_paid = order.grand_total
    add_history(order, new_status, note, admin_name)
    db.session.commit()
    if notify:
        from .email_service import send_status_update
        try:
            send_status_update(order)
        except Exception:
            current_app.logger.exception("Status email failed")


def _refund_after_delivery(order, admin_name, note):
    payment = order.successful_payment
    if order.status == "cancelled" and order.cancellation and not order.cancellation.refund_amount and not payment:
        order.status = "refunded"
        add_history(order, "refunded", note, admin_name)
        db.session.commit()
        return
    if not payment:
        raise OrderError("There is no collected payment to refund.")
    canc = order.cancellation
    if not canc:
        canc = Cancellation(order_id=order.id, cancelled_by="admin", reason=note or "Refund after delivery",
                            original_amount=order.grand_total, refund_amount=D(payment.amount))
        db.session.add(canc)
        db.session.flush()
    else:
        canc.refund_amount = D(payment.amount)
    _issue_refund(order, payment, canc, D(payment.amount))
    order.status = "refunded"
    add_history(order, "refunded", note or "Refund issued", admin_name)
    db.session.commit()
    if order.invoice:
        from .invoice_service import save_credit_note_pdf
        save_credit_note_pdf(order)
        db.session.commit()
    from .email_service import send_cancellation_email
    try:
        send_cancellation_email(order)
    except Exception:
        current_app.logger.exception("Refund email failed")

