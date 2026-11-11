"""SQLAlchemy models — 18 core tables plus order status history."""
from datetime import datetime, date
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db

Money = db.Numeric(12, 2)


def utcnow():
    return datetime.utcnow()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


# ---------------------------------------------------------------- people
class PasswordMixin:
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return bool(self.password_hash) and check_password_hash(self.password_hash, raw)


class User(UserMixin, PasswordMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_active_account = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)

    addresses = db.relationship("Address", backref="user", cascade="all, delete-orphan", lazy="dynamic")
    orders = db.relationship("Order", backref="user", lazy="dynamic")
    cart = db.relationship("Cart", backref="user", uselist=False, cascade="all, delete-orphan")

    role = "customer"

    def get_id(self):
        return f"c:{self.id}"

    @property
    def is_active(self):
        return self.is_active_account

    @property
    def is_admin(self):
        return False


class Admin(UserMixin, PasswordMixin, TimestampMixin, db.Model):
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active_account = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)

    role = "admin"

    def get_id(self):
        return f"a:{self.id}"

    @property
    def is_active(self):
        return self.is_active_account

    @property
    def is_admin(self):
        return True


# ---------------------------------------------------------------- catalog
class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    kind = db.Column(db.String(10), nullable=False, default="sweet")  # sweet | food
    description = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0)
    products = db.relationship("Product", backref="category", lazy="dynamic")


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(Money, nullable=False)
    unit_label = db.Column(db.String(60), nullable=False, default="1 box")
    weight_grams = db.Column(db.Integer)
    shelf_life_days = db.Column(db.Integer, default=3)
    is_veg = db.Column(db.Boolean, default=True, nullable=False)
    image = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    ingredients = db.relationship("ProductIngredient", backref="product", cascade="all, delete-orphan",
                                  order_by="ProductIngredient.id")
    batches = db.relationship("InventoryBatch", backref="product", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def image_url(self):
        return self.image or "images/products/placeholder.svg"


class ProductIngredient(db.Model):
    __tablename__ = "product_ingredients"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    is_allergen = db.Column(db.Boolean, default=False)


# ---------------------------------------------------------------- inventory
class InventoryBatch(TimestampMixin, db.Model):
    __tablename__ = "inventory_batches"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    batch_number = db.Column(db.String(40), unique=True, nullable=False)
    manufacturing_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=False, index=True)
    quantity_received = db.Column(db.Integer, nullable=False)
    quantity_available = db.Column(db.Integer, nullable=False)
    quantity_sold = db.Column(db.Integer, nullable=False, default=0)
    is_written_off = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def days_left(self):
        return (self.expiration_date - date.today()).days

    @property
    def is_expired(self):
        return self.expiration_date < date.today()


class StockTransaction(TimestampMixin, db.Model):
    __tablename__ = "stock_transactions"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("inventory_batches.id"), index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"))
    # stock_in | sale | cancel_restore | adjustment | writeoff
    txn_type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)  # signed
    note = db.Column(db.String(255))

    product = db.relationship("Product")
    batch = db.relationship("InventoryBatch")
    order = db.relationship("Order")


# ---------------------------------------------------------------- customer data
class Address(TimestampMixin, db.Model):
    __tablename__ = "addresses"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    label = db.Column(db.String(40), default="Home")
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    line1 = db.Column(db.String(200), nullable=False)
    line2 = db.Column(db.String(200))
    city = db.Column(db.String(80), nullable=False)
    state = db.Column(db.String(80), nullable=False)
    zip_code = db.Column(db.String(12), nullable=False)
    is_default = db.Column(db.Boolean, default=False)

    def one_line(self):
        parts = [self.line1, self.line2, self.city, f"{self.state} {self.zip_code}"]
        return ", ".join(p for p in parts if p)


class Cart(db.Model):
    __tablename__ = "carts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    items = db.relationship("CartItem", backref="cart", cascade="all, delete-orphan", order_by="CartItem.id")


class CartItem(db.Model):
    __tablename__ = "cart_items"
    __table_args__ = (db.UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),)
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("carts.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    product = db.relationship("Product")


# ---------------------------------------------------------------- orders
ORDER_STATUSES = [
    ("pending", "Pending"),
    ("confirmed", "Confirmed"),
    ("preparing", "Preparing"),
    ("ready_for_pickup", "Ready for Pickup"),
    ("out_for_delivery", "Out for Delivery"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
    ("refunded", "Refunded"),
]
STATUS_LABELS = dict(ORDER_STATUSES)
PAYMENT_METHOD_LABELS = {"card": "Card", "upi": "UPI", "cod": "Cash on Delivery",
                         "stripe": "Stripe (Card)", "wallet": "Wallet"}


class Order(TimestampMixin, db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)

    customer_name = db.Column(db.String(120), nullable=False)
    customer_email = db.Column(db.String(255), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    ship_line1 = db.Column(db.String(200), nullable=False)
    ship_line2 = db.Column(db.String(200))
    ship_city = db.Column(db.String(80), nullable=False)
    ship_state = db.Column(db.String(80), nullable=False)
    ship_zip = db.Column(db.String(12), nullable=False)
    billing_address = db.Column(db.String(400))
    delivery_instructions = db.Column(db.String(300))

    subtotal = db.Column(Money, nullable=False, default=0)
    discount = db.Column(Money, nullable=False, default=0)
    tax_amount = db.Column(Money, nullable=False, default=0)
    delivery_charge = db.Column(Money, nullable=False, default=0)
    grand_total = db.Column(Money, nullable=False, default=0)

    payment_method = db.Column(db.String(20))
    payment_status = db.Column(db.String(20), nullable=False, default="unpaid", index=True)
    otp_verified = db.Column(db.Boolean, default=False, nullable=False)
    stock_deducted = db.Column(db.Boolean, default=False, nullable=False)

    confirmed_at = db.Column(db.DateTime, index=True)
    delivered_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan", order_by="OrderItem.id")
    payments = db.relationship("Payment", backref="order", lazy="dynamic", order_by="Payment.id")
    invoice = db.relationship("Invoice", backref="order", uselist=False)
    cancellation = db.relationship("Cancellation", backref="order", uselist=False)
    refunds = db.relationship("Refund", backref="order", lazy="dynamic")
    history = db.relationship("OrderStatusHistory", backref="order", order_by="OrderStatusHistory.id",
                              cascade="all, delete-orphan")

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status.title())

    @property
    def payment_method_label(self):
        return PAYMENT_METHOD_LABELS.get(self.payment_method or "", (self.payment_method or "—").title())

    @property
    def shipping_address(self):
        parts = [self.ship_line1, self.ship_line2, self.ship_city, f"{self.ship_state} {self.ship_zip}"]
        return ", ".join(p for p in parts if p)

    @property
    def successful_payment(self):
        return self.payments.filter_by(status="succeeded").order_by(Payment.id.desc()).first()

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items)


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    product_name = db.Column(db.String(120), nullable=False)
    category_kind = db.Column(db.String(10), nullable=False, default="sweet")
    unit_label = db.Column(db.String(60))
    unit_price = db.Column(Money, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    tax_amount = db.Column(Money, nullable=False, default=0)
    line_total = db.Column(Money, nullable=False)  # (unit_price * qty) + tax
    product = db.relationship("Product")


class OrderStatusHistory(TimestampMixin, db.Model):
    __tablename__ = "order_status_history"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(255))
    changed_by = db.Column(db.String(60))


class Payment(TimestampMixin, db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    gateway = db.Column(db.String(20), nullable=False)  # simulated | stripe | cod
    method = db.Column(db.String(20), nullable=False)  # card | upi | cod | stripe
    transaction_id = db.Column(db.String(80), unique=True)
    gateway_reference = db.Column(db.String(255), index=True)  # e.g. Stripe checkout session id
    amount = db.Column(Money, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    # initiated | succeeded | failed | refunded | partially_refunded
    status = db.Column(db.String(20), nullable=False, default="initiated", index=True)
    # Only non-sensitive descriptors are stored — never PAN or CVV.
    card_brand = db.Column(db.String(20))
    card_last4 = db.Column(db.String(4))
    upi_handle_masked = db.Column(db.String(60))
    failure_reason = db.Column(db.String(255))
    verified_at = db.Column(db.DateTime)


class OTPVerification(TimestampMixin, db.Model):
    __tablename__ = "otp_verifications"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    purpose = db.Column(db.String(20), nullable=False, index=True)  # register|login|admin_login|order
    reference_id = db.Column(db.Integer)  # user/admin/order id
    otp_hash = db.Column(db.String(128), nullable=False)
    salt = db.Column(db.String(32), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=5, nullable=False)
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    verified_at = db.Column(db.DateTime)
    ip_address = db.Column(db.String(64))


class Invoice(TimestampMixin, db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(30), unique=True, nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), unique=True, nullable=False)
    invoice_date = db.Column(db.DateTime, default=utcnow, nullable=False)
    subtotal = db.Column(Money, nullable=False)
    discount = db.Column(Money, nullable=False, default=0)
    tax_amount = db.Column(Money, nullable=False)
    delivery_charge = db.Column(Money, nullable=False)
    grand_total = db.Column(Money, nullable=False)
    amount_paid = db.Column(Money, nullable=False, default=0)
    pdf_path = db.Column(db.String(255))


class Cancellation(TimestampMixin, db.Model):
    __tablename__ = "cancellations"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), unique=True, nullable=False)
    cancelled_by = db.Column(db.String(20), nullable=False)  # customer | admin | system
    reason = db.Column(db.String(300))
    original_amount = db.Column(Money, nullable=False)
    refund_amount = db.Column(Money, nullable=False, default=0)
    credit_note_number = db.Column(db.String(30), unique=True)
    credit_note_path = db.Column(db.String(255))
    refund = db.relationship("Refund", backref="cancellation", uselist=False)


class Refund(TimestampMixin, db.Model):
    __tablename__ = "refunds"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"))
    cancellation_id = db.Column(db.Integer, db.ForeignKey("cancellations.id"))
    amount = db.Column(Money, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending|processed|failed
    gateway_refund_id = db.Column(db.String(80))
    note = db.Column(db.String(255))
    processed_at = db.Column(db.DateTime, index=True)
    payment = db.relationship("Payment")


class EmailLog(TimestampMixin, db.Model):
    __tablename__ = "email_logs"
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(255), nullable=False, index=True)
    subject = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # otp|order_confirmation|cancellation|status
    status = db.Column(db.String(20), nullable=False)  # sent | outbox | failed
    error = db.Column(db.String(500))
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    html_body = db.Column(db.Text)
    attachment_name = db.Column(db.String(120))
    outbox_path = db.Column(db.String(255))


def D(value) -> Decimal:
    """Coerce numbers to 2dp Decimal for money maths."""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))
