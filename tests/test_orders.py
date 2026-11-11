import re
from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import (Cancellation, EmailLog, InventoryBatch, Invoice, Order, Payment, Product, Refund,
                        StockTransaction)
from app.services import inventory_service as inv
from conftest import demo_user, last_otp, login_admin, login_customer

ADDRESS = {"email": "priya@example.com", "address_id": "0", "full_name": "Priya Sharma", "phone": "+1 732 555 0101",
           "line1": "48 Oak Tree Rd", "city": "Edison", "state": "NJ", "zip_code": "08820"}


def product(name):
    return Product.query.filter_by(name=name).first()


def add(client, name, qty):
    return client.post("/cart/add", data={"product_id": product(name).id, "quantity": qty},
                       headers={"X-Requested-With": "fetch"})


def place_verified_order(client, items=(("Kaju Katli", 2), ("Gulab Jamun", 1))):
    for name, qty in items:
        assert add(client, name, qty).status_code == 200
    r = client.post("/checkout/", data=ADDRESS)
    assert r.status_code == 302, r.data
    number = re.search(r"/checkout/([^/]+)/verify", r.headers["Location"]).group(1)
    order = Order.query.filter_by(order_number=number).first()
    assert order.status == "pending" and not order.otp_verified
    # paying before OTP is not possible
    assert "/verify" in client.get(f"/checkout/{number}/pay").headers["Location"]
    r = client.post(f"/checkout/{number}/verify", data={"code": last_otp("priya@example.com")})
    assert r.headers["Location"].endswith(f"/checkout/{number}/pay")
    return order


def nonce_for(client, number):
    html = client.get(f"/checkout/{number}/pay").data.decode()
    return re.search(r'name="nonce" value="([^"]+)"', html).group(1)


def pay_card(client, number, card="4242 4242 4242 4242"):
    return client.post(f"/checkout/{number}/pay", data={
        "nonce": nonce_for(client, number), "method": "card", "card_number": card, "card_name": "Priya Sharma",
        "card_expiry": "12/34", "card_cvc": "123"})


# ------------------------------------------------------------------ cart
def test_cart_totals_tax_delivery_and_coupon(client, app):
    login_customer(client)
    add(client, "Samosa", 2)  # 2 × 4.99
    from app.services.cart_service import cart_summary
    s = cart_summary(demo_user())
    assert s["subtotal"] == Decimal("9.98")
    assert s["tax"] == Decimal("0.50")
    assert s["delivery"] == Decimal("4.99")
    assert s["grand_total"] == Decimal("15.47")
    add(client, "Kaju Katli", 4)  # pushes past free-delivery threshold even after discount
    s = cart_summary(demo_user(), "DIWALI10")
    assert s["delivery"] == 0 and s["discount"] == (s["subtotal"] * Decimal("0.10")).quantize(Decimal("0.01"))
    assert s["grand_total"] == s["subtotal"] - s["discount"] + s["tax"]


def test_cannot_add_more_than_stock_or_expired_only_items(client):
    login_customer(client)
    r = add(client, "Veg Puff", 1)  # only an expired batch exists
    assert r.status_code == 400 and b"out of stock" in r.data
    r = add(client, "Kalakand", 500)
    assert r.status_code == 400


# ------------------------------------------------------------------ checkout + payment
def test_full_card_checkout_confirms_deducts_fifo_and_emails_invoice(client, app):
    login_customer(client)
    gj = product("Gulab Jamun")
    batches = (InventoryBatch.query.filter_by(product_id=gj.id).order_by(InventoryBatch.expiration_date).all())
    oldest_before = batches[0].quantity_available
    newest_before = batches[1].quantity_available

    order = place_verified_order(client, (("Kaju Katli", 2), ("Gulab Jamun", oldest_before + 2)))
    r = pay_card(client, order.order_number)
    assert r.headers["Location"].endswith(f"/checkout/{order.order_number}/success")

    order = db.session.get(Order, order.id)
    assert order.status == "confirmed" and order.payment_status == "paid" and order.stock_deducted
    pay = order.successful_payment
    assert pay.card_last4 == "4242" and pay.card_brand == "Visa"
    assert not Payment.query.filter(Payment.transaction_id.contains("4242424242")).first()

    # FIFO: earliest-expiring batch emptied first, remainder from the next
    db.session.refresh(batches[0]); db.session.refresh(batches[1])
    assert batches[0].quantity_available == 0
    assert batches[1].quantity_available == newest_before - 2

    # invoice matches the order exactly
    inv_row = order.invoice
    assert inv_row and inv_row.grand_total == order.grand_total and inv_row.amount_paid == order.grand_total
    assert sum(i.line_total for i in order.items) == order.subtotal + order.tax_amount

    mail = EmailLog.query.filter_by(order_id=order.id, category="order_confirmation").first()
    assert mail and mail.attachment_name.endswith(".pdf") and inv_row.invoice_number in mail.subject
    assert order.order_number in mail.html_body and f"{float(order.grand_total):,.2f}" in mail.html_body

    pdf = client.get(f"/account/orders/{order.order_number}/invoice.pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert client.get("/cart/").status_code == 200 and b"empty" in client.get("/cart/").data


def test_declined_card_does_not_confirm(client):
    login_customer(client)
    order = place_verified_order(client)
    r = pay_card(client, order.order_number, "4000 0000 0000 0002")
    assert r.status_code == 200 and b"declined" in r.data
    order = db.session.get(Order, order.id)
    assert order.status == "pending" and not order.stock_deducted
    assert Payment.query.filter_by(order_id=order.id, status="failed").count() == 1


def test_replayed_payment_is_not_charged_twice(client):
    login_customer(client)
    order = place_verified_order(client)
    nonce = nonce_for(client, order.order_number)
    form = {"nonce": nonce, "method": "card", "card_number": "4242424242424242", "card_name": "P S",
            "card_expiry": "12/34", "card_cvc": "123"}
    client.post(f"/checkout/{order.order_number}/pay", data=form)
    client.post(f"/checkout/{order.order_number}/pay", data=form)  # double submit
    assert Payment.query.filter_by(order_id=order.id, status="succeeded").count() == 1
    assert Invoice.query.filter_by(order_id=order.id).count() == 1


def test_upi_and_cod_paths(client):
    login_customer(client)
    order = place_verified_order(client)
    client.post(f"/checkout/{order.order_number}/pay",
                data={"nonce": nonce_for(client, order.order_number), "method": "upi", "upi_id": "success@upi"})
    assert db.session.get(Order, order.id).payment_method == "upi"

    order2 = place_verified_order(client, (("Peda", 1),))
    client.post(f"/checkout/{order2.order_number}/pay",
                data={"nonce": nonce_for(client, order2.order_number), "method": "cod"})
    o2 = db.session.get(Order, order2.id)
    assert o2.status == "confirmed" and o2.payment_status == "pending" and o2.invoice.amount_paid == 0


def test_customers_cannot_see_each_others_orders(client, app):
    login_customer(client)
    order = place_verified_order(client)
    pay_card(client, order.order_number)
    client.post("/logout")
    client.post("/register", data={"name": "Other User", "email": "other@example.com", "phone": "+1 908 555 0000",
                                   "password": "Other1234", "confirm_password": "Other1234"})
    client.post("/verify", data={"code": last_otp("other@example.com")})
    assert client.get(f"/account/orders/{order.order_number}").status_code == 404
    assert client.get(f"/account/orders/{order.order_number}/invoice.pdf").status_code == 404


# ------------------------------------------------------------------ cancellation
def test_cancel_restores_stock_refunds_and_emails(client):
    login_customer(client)
    kk = product("Kaju Katli")
    before = inv.available_stock(kk.id)
    order = place_verified_order(client, (("Kaju Katli", 3),))
    pay_card(client, order.order_number)
    assert inv.available_stock(kk.id) == before - 3

    r = client.post(f"/account/orders/{order.order_number}/cancel", data={"reason": "Plans changed"})
    assert r.status_code == 302
    order = db.session.get(Order, order.id)
    assert order.status == "refunded" and order.payment_status == "refunded"
    assert inv.available_stock(kk.id) == before
    assert StockTransaction.query.filter_by(order_id=order.id, txn_type="cancel_restore").count() >= 1

    canc = Cancellation.query.filter_by(order_id=order.id).first()
    refund = Refund.query.filter_by(order_id=order.id).first()
    assert canc.refund_amount == order.grand_total and canc.credit_note_number and canc.reason == "Plans changed"
    assert refund.status == "processed" and refund.amount == order.grand_total
    mail = EmailLog.query.filter_by(order_id=order.id, category="cancellation").first()
    assert mail and "CreditNote" in mail.attachment_name and "Plans changed" in mail.html_body
    assert client.get(f"/account/orders/{order.order_number}/credit-note.pdf").data[:4] == b"%PDF"
    # cannot cancel twice
    client.post(f"/account/orders/{order.order_number}/cancel")
    assert Cancellation.query.filter_by(order_id=order.id).count() == 1


def test_delivered_orders_cannot_be_cancelled_by_customer(client):
    login_customer(client)
    order = place_verified_order(client)
    pay_card(client, order.order_number)
    o = db.session.get(Order, order.id)
    o.status = "delivered"
    db.session.commit()
    r = client.post(f"/account/orders/{order.order_number}/cancel", follow_redirects=True)
    assert b"can no longer be cancelled" in r.data
    assert db.session.get(Order, order.id).status == "delivered"


# ------------------------------------------------------------------ inventory
def test_expired_batches_never_sold_and_writeoff(app):
    p = product("Rasmalai")
    expired = InventoryBatch.query.filter(InventoryBatch.product_id == p.id,
                                          InventoryBatch.expiration_date < date.today()).first()
    assert expired and expired.quantity_available > 0
    sellable = inv.available_stock(p.id)
    assert sellable == sum(b.quantity_available for b in p.batches if b.expiration_date >= date.today())
    buckets = inv.expiry_buckets()
    assert expired in buckets["expired"]
    inv.write_off_batch(expired)
    assert expired.quantity_available == 0 and expired.is_written_off
    assert expired not in inv.expiry_buckets()["expired"]


def test_add_stock_and_expiry_levels(app):
    p = product("Samosa")
    before = inv.available_stock(p.id)
    b = inv.add_stock(p, 25, date.today(), date.today() + timedelta(days=2))
    assert inv.available_stock(p.id) == before + 25
    assert StockTransaction.query.filter_by(batch_id=b.id, txn_type="stock_in").first().quantity == 25
    assert inv.expiry_level(date.today() - timedelta(days=1))[2] == "danger"
    assert inv.expiry_level(date.today() + timedelta(days=2))[2] == "orange"
    assert inv.expiry_level(date.today() + timedelta(days=6))[2] == "warning"
    assert inv.expiry_level(date.today() + timedelta(days=20))[2] == "success"


# ------------------------------------------------------------------ admin
def test_admin_status_flow_cod_delivery_marks_paid(client):
    login_customer(client)
    order = place_verified_order(client, (("Peda", 2),))
    client.post(f"/checkout/{order.order_number}/pay",
                data={"nonce": nonce_for(client, order.order_number), "method": "cod"})
    client.post("/logout")
    login_admin(client)
    for status in ("preparing", "out_for_delivery", "delivered"):
        r = client.post(f"/admin/orders/{order.order_number}", data={"status": status, "notify": "1"})
        assert r.status_code == 302
    o = db.session.get(Order, order.id)
    assert o.status == "delivered" and o.payment_status == "paid" and o.invoice.amount_paid == o.grand_total
    assert EmailLog.query.filter_by(order_id=o.id, category="status").count() == 3
    # illegal transition rejected
    client.post(f"/admin/orders/{order.order_number}", data={"status": "preparing"})
    assert db.session.get(Order, order.id).status == "delivered"


def test_admin_cancel_restores_stock(client):
    login_customer(client)
    p = product("Motichoor Laddu")
    before = inv.available_stock(p.id)
    order = place_verified_order(client, (("Motichoor Laddu", 4),))
    pay_card(client, order.order_number)
    client.post("/logout")
    login_admin(client)
    client.post(f"/admin/orders/{order.order_number}", data={"status": "cancelled", "note": "Out of saffron"})
    assert inv.available_stock(p.id) == before
    assert db.session.get(Order, order.id).cancellation.cancelled_by == "admin"


def test_dashboard_charts_and_reports(client):
    login_customer(client)
    order = place_verified_order(client)
    pay_card(client, order.order_number)
    client.post("/logout")
    login_admin(client)
    assert client.get("/admin/").status_code == 200
    data = client.get("/admin/api/charts").get_json()
    assert data["range"]["orders"] == 1
    assert abs(data["range"]["revenue"] - float(db.session.get(Order, order.id).grand_total)) < 0.01
    assert data["best_sweets"] and data["payment_methods"]["labels"] == ["Card"]
    rev = client.get("/admin/revenue")
    assert rev.status_code == 200
    for page in ("/admin/products", "/admin/inventory", "/admin/expiry", "/admin/orders", "/admin/customers",
                 "/admin/emails", "/admin/stock-history", f"/admin/orders/{order.order_number}"):
        assert client.get(page).status_code == 200, page
    for kind in ("sales", "inventory", "expiry", "best_sellers", "customers", "payments", "cancellations"):
        assert client.get(f"/admin/reports?kind={kind}").status_code == 200
        assert client.get(f"/admin/reports?kind={kind}&export=pdf").data[:4] == b"%PDF"
        assert client.get(f"/admin/reports?kind={kind}&export=xlsx").data[:2] == b"PK"


def test_admin_creates_product_with_stock(client):
    login_admin(client)
    from app.models import Category
    cat = Category.query.filter_by(slug="milk-sweets").first()
    r = client.post("/admin/products/new", data={
        "name": "Kesar Rabri", "category_id": cat.id, "description": "Thickened saffron milk", "price": "6.50",
        "unit_label": "Cup", "shelf_life_days": "2", "is_veg": "1", "is_active": "1",
        "ingredients": "Whole milk*, Sugar, Saffron", "initial_stock": "12"})
    assert r.status_code == 302
    p = Product.query.filter_by(name="Kesar Rabri").first()
    assert p and inv.available_stock(p.id) == 12 and [i.is_allergen for i in p.ingredients] == [True, False, False]
    assert client.get("/shop?q=rabri").data.count(b"Kesar Rabri") >= 1


def test_storefront_pages(client):
    assert client.get("/").status_code == 200
    r = client.get("/shop?kind=sweet&sort=price_asc")
    assert r.status_code == 200 and b"Kaju Katli" in r.data and b"Samosa" not in r.data
    assert b"Gulab Jamun" in client.get("/shop?q=cardamom").data  # ingredient search
    assert client.get("/product/kaju-katli").status_code == 200
    assert client.get("/product/nope").status_code == 404
