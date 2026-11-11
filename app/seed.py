"""Sample data: categories, 27 products with ingredients, dated inventory batches, demo accounts and
~14 months of realistic order history so the dashboard and reports have something to show.

Run with:  flask --app run.py seed      (or python scripts/init_db.py)
"""
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app

from .extensions import db
from .models import (Address, Admin, Cancellation, Category, InventoryBatch, Invoice, Order, OrderItem,
                     OrderStatusHistory, Payment, Product, ProductIngredient, Refund, StockTransaction, User)
from .services.cart_service import compute_totals
from .utils.helpers import slugify

CATEGORIES = [
    # name, slug, kind, description, sort
    ("Milk Sweets", "milk-sweets", "sweet", "Chhena & khoya classics", 1),
    ("Syrup Sweets", "syrup-sweets", "sweet", "Soaked in cardamom syrup", 2),
    ("Barfi & Katli", "barfi-katli", "sweet", "Cashew, coconut & more", 3),
    ("Laddu & Ghee Sweets", "laddu-ghee", "sweet", "Roasted in desi ghee", 4),
    ("Chaat & Snacks", "snacks", "food", "Crisp, hot & tangy", 5),
    ("South Indian", "south-indian", "food", "Tiffin from the south", 6),
    ("Meals", "meals", "food", "Hearty plates", 7),
]

# slug, category slug, price, unit label, grams, shelf days, veg, featured, description, ingredients (* = allergen)
PRODUCTS = [
    ("Gulab Jamun", "syrup-sweets", "8.99", "Box of 8", 400, 5, True, True,
     "Soft khoya dumplings fried golden in ghee and soaked in rose-cardamom syrup.",
     "Khoya*, Maida*, Ghee*, Sugar, Rose water, Green cardamom, Saffron"),
    ("Rasgulla", "milk-sweets", "7.99", "Tin of 8", 500, 4, True, False,
     "Spongy Bengali chhena balls simmered in light sugar syrup — served chilled.",
     "Cow milk chhena*, Sugar, Semolina*, Rose water"),
    ("Rasmalai", "milk-sweets", "10.99", "Box of 6", 450, 3, True, True,
     "Flattened chhena discs in thickened saffron milk with pistachio and almond slivers.",
     "Cow milk chhena*, Whole milk*, Sugar, Saffron, Pistachio*, Almond*, Green cardamom"),
    ("Kaju Katli", "barfi-katli", "14.99", "250 g box", 250, 21, True, True,
     "Diamond-cut cashew fudge finished with edible silver vark. Our signature Diwali sweet.",
     "Cashew*, Sugar, Ghee*, Edible silver vark"),
    ("Mysore Pak", "laddu-ghee", "9.49", "250 g box", 250, 15, True, False,
     "Melt-in-the-mouth gram-flour fudge cooked with a generous pour of desi ghee.",
     "Besan (gram flour), Ghee*, Sugar"),
    ("Motichoor Laddu", "laddu-ghee", "9.99", "Box of 6", 450, 7, True, True,
     "Tiny boondi pearls bound with saffron syrup, melon seeds and cardamom.",
     "Besan (gram flour), Ghee*, Sugar, Melon seeds, Saffron, Green cardamom"),
    ("Besan Laddu", "laddu-ghee", "8.49", "Box of 6", 420, 14, True, False,
     "Slow-roasted gram flour, ghee and powdered sugar, topped with almond slivers.",
     "Besan (gram flour), Ghee*, Powdered sugar, Almond*, Green cardamom"),
    ("Jalebi", "syrup-sweets", "6.49", "250 g", 250, 2, True, True,
     "Crisp saffron spirals fried to order and dunked in warm sugar syrup.",
     "Maida*, Yogurt*, Sugar, Saffron, Ghee*"),
    ("Peda", "milk-sweets", "8.99", "Box of 10", 300, 7, True, False,
     "Mathura-style khoya peda, slow-cooked until caramel-brown and fragrant with cardamom.",
     "Khoya*, Sugar, Green cardamom, Saffron"),
    ("Soan Papdi", "laddu-ghee", "6.99", "250 g box", 250, 45, True, False,
     "Flaky, cotton-light layers of gram flour and ghee with pistachio crumbs.",
     "Besan (gram flour), Maida*, Ghee*, Sugar, Pistachio*, Green cardamom"),
    ("Milk Cake", "milk-sweets", "11.49", "400 g slab", 400, 10, True, False,
     "Alwar-style granular milk fudge with a caramelised heart.",
     "Whole milk*, Sugar, Ghee*, Lemon juice"),
    ("Badusha", "syrup-sweets", "7.49", "Box of 8", 360, 7, True, False,
     "Flaky, glazed balushahi — crisp outside and tender within.",
     "Maida*, Ghee*, Yogurt*, Sugar, Baking soda"),
    ("Coconut Burfi", "barfi-katli", "7.99", "300 g box", 300, 6, True, False,
     "Fresh grated coconut and milk set in squares with a rose-pink layer.",
     "Fresh coconut, Whole milk*, Sugar, Ghee*, Green cardamom"),
    ("Kalakand", "milk-sweets", "10.49", "300 g box", 300, 4, True, False,
     "Soft, grainy milk cake set with pistachio — made fresh every morning.",
     "Whole milk*, Paneer*, Sugar, Pistachio*, Green cardamom"),
    ("Cham Cham", "milk-sweets", "9.49", "Box of 6", 420, 4, True, False,
     "Oval chhena sweets in rose and kesar, rolled in fresh coconut.",
     "Cow milk chhena*, Sugar, Desiccated coconut, Khoya*, Saffron, Rose water"),
    ("Samosa", "snacks", "4.99", "2 pieces", 240, 1, True, True,
     "Hand-folded pastry stuffed with spiced potato and peas, with mint and tamarind chutneys.",
     "Maida*, Potato, Green peas, Ginger, Green chilli, Garam masala, Mint chutney, Tamarind chutney"),
    ("Kachori", "snacks", "4.49", "2 pieces", 200, 2, True, False,
     "Flaky moong-dal kachori with a warm, peppery filling.",
     "Maida*, Moong dal, Fennel, Asafoetida, Red chilli, Ghee*"),
    ("Veg Puff", "snacks", "3.99", "2 pieces", 180, 2, True, False,
     "Bakery-style puff pastry filled with masala vegetables.",
     "Puff pastry (wheat*, butter*), Potato, Carrot, Peas, Onion, Spices"),
    ("Paneer Tikka", "snacks", "11.99", "8 pieces", 300, 1, True, True,
     "Tandoor-charred paneer, peppers and onion in a smoky yogurt marinade.",
     "Paneer*, Yogurt*, Bell pepper, Onion, Kashmiri chilli, Mustard oil*, Kasuri methi"),
    ("Masala Dosa", "south-indian", "9.99", "1 dosa", 350, 1, True, True,
     "Crisp fermented rice-lentil crepe with potato masala, sambar and two chutneys.",
     "Rice, Urad dal, Potato, Onion, Mustard seeds*, Curry leaves, Coconut chutney, Sambar"),
    ("Idli", "south-indian", "6.99", "4 pieces", 320, 1, True, False,
     "Steamed rice cakes, cloud-soft, with sambar and coconut chutney.",
     "Rice, Urad dal, Salt, Coconut chutney, Sambar"),
    ("Vada", "south-indian", "6.49", "3 pieces", 270, 1, True, False,
     "Crunchy urad dal doughnuts with black pepper and curry leaves.",
     "Urad dal, Black pepper, Curry leaves, Ginger, Green chilli"),
    ("Biryani", "meals", "15.99", "Serves 1–2", 650, 1, False, True,
     "Hyderabadi chicken dum biryani — aged basmati layered with saffron, mint and fried onions.",
     "Basmati rice, Chicken, Yogurt*, Saffron, Mint, Fried onion, Ghee*, Whole spices"),
    ("Pav Bhaji", "meals", "10.99", "Bhaji + 2 pav", 450, 1, True, False,
     "Mumbai street-style buttery vegetable bhaji with toasted pav and onion-lemon.",
     "Potato, Cauliflower, Peas, Tomato, Butter*, Pav bhaji masala, Pav (wheat*)"),
    ("Chole Bhature", "meals", "11.49", "Chole + 2 bhature", 520, 1, True, True,
     "Punjabi chickpea curry with two pillowy fried bhature and pickled onions.",
     "Chickpeas, Onion, Tomato, Chole masala, Maida*, Yogurt*"),
    ("Poori", "meals", "7.99", "4 poori + aloo", 380, 1, True, False,
     "Puffed whole-wheat poori with dry aloo sabzi.",
     "Whole wheat*, Potato, Cumin, Turmeric, Green chilli"),
    ("Parotta", "south-indian", "8.49", "2 parotta + salna", 400, 1, True, False,
     "Flaky Kerala-style layered parotta with vegetable salna.",
     "Maida*, Egg-free dough, Ghee*, Vegetable salna"),
]

# Expiry scenarios relative to today: list of (days_since_mfg, days_to_expiry, qty) per batch
SCENARIOS = {
    "Rasmalai": [(4, -1, 6), (0, 3, 30)],              # one expired batch + fresh
    "Paneer Tikka": [(2, -1, 8), (0, 1, 18)],
    "Samosa": [(1, 0, 22), (0, 1, 40)],                # expiring today
    "Idli": [(1, 0, 14), (0, 1, 30)],
    "Veg Puff": [(3, -1, 10)],                         # only expired stock → sold out
    "Gulab Jamun": [(3, 2, 18), (0, 5, 60)],           # within 3 days
    "Cham Cham": [(2, 2, 12), (0, 4, 30)],
    "Kalakand": [(1, 3, 9)],                           # low stock + 3 days
    "Peda": [(2, 5, 25), (0, 7, 40)],                  # within 7 days
    "Coconut Burfi": [(1, 5, 7)],                      # low stock
    "Badusha": [(1, 6, 30)],
    "Jalebi": [(0, 1, 35)],
}

FIRST = ["Priya", "Arjun", "Ananya", "Rohan", "Kavya", "Vikram", "Meera", "Aditya", "Sneha", "Rahul", "Divya",
         "Karthik", "Pooja", "Siddharth", "Lakshmi", "Nikhil", "Ishita", "Varun", "Neha", "Manoj", "Aisha",
         "Ravi", "Deepa", "Sanjay", "Anjali", "Harish", "Swati", "Imran", "Gurpreet", "Fatima", "Emily",
         "James", "Sophia", "Daniel", "Olivia", "Michael", "Grace", "David", "Hannah", "Ethan"]
LAST = ["Sharma", "Reddy", "Iyer", "Patel", "Nair", "Gupta", "Menon", "Rao", "Singh", "Kapoor", "Desai",
        "Krishnan", "Mehta", "Banerjee", "Pillai", "Khan", "Joshi", "Thomas", "Miller", "Johnson"]
CITIES = [("Edison", "NJ", "08817"), ("Iselin", "NJ", "08830"), ("Jersey City", "NJ", "07306"),
          ("Princeton", "NJ", "08540"), ("New Brunswick", "NJ", "08901"), ("Plainsboro", "NJ", "08536"),
          ("Piscataway", "NJ", "08854"), ("Woodbridge", "NJ", "07095")]
STREETS = ["Oak Tree Rd", "Main St", "Lincoln Hwy", "Grove Ave", "Park Ave", "Maple Dr", "Cedar Ln",
           "Washington Ave", "Elm St", "Route 27"]
REASONS = ["Ordered by mistake", "Delivery time too late", "Want to change items", "Plans changed", None]


def _utc(local_day, hour, minute, tz):
    return (datetime.combine(local_day, time(hour, minute), tz).astimezone(timezone.utc).replace(tzinfo=None))


def seed_all(history_days=420, echo=print, rng_seed=7, extra_customers=44):
    rng = random.Random(rng_seed)
    if Product.query.first():
        echo("Database already has products — skipping seed. Use `flask init-db --drop` to reset first.")
        return
    today = date.today()

    # categories & products
    cats = {}
    for name, slug, kind, desc, order in CATEGORIES:
        c = Category(name=name, slug=slug, kind=kind, description=desc, sort_order=order)
        db.session.add(c)
        cats[slug] = c
    db.session.flush()
    products = []
    for (name, cslug, price, unit, grams, shelf, veg, feat, desc, ings) in PRODUCTS:
        slug = slugify(name)
        p = Product(name=name, slug=slug, category_id=cats[cslug].id, price=Decimal(price), unit_label=unit,
                    weight_grams=grams, shelf_life_days=shelf, is_veg=veg, is_featured=feat, description=desc,
                    image=f"images/products/{slug}.svg")
        for raw in ings.split(", "):
            p.ingredients.append(ProductIngredient(name=raw.rstrip("*"), is_allergen=raw.endswith("*")))
        db.session.add(p)
        products.append(p)
    db.session.flush()

    # inventory batches
    n = 0
    for p in products:
        plan = SCENARIOS.get(p.name)
        if not plan:
            age = rng.randint(0, max(0, min(p.shelf_life_days - 1, 6)))
            plan = [(age + 2, p.shelf_life_days - age - 2, rng.randint(15, 30)), (0, p.shelf_life_days, rng.randint(35, 80))] \
                if p.shelf_life_days > 4 else [(0, p.shelf_life_days, rng.randint(25, 50))]
        for mfg_ago, exp_in, qty in plan:
            n += 1
            mfg = today - timedelta(days=mfg_ago)
            exp = today + timedelta(days=exp_in)
            sold = rng.randint(2, 20) if mfg_ago > 0 else rng.randint(0, 6)
            b = InventoryBatch(product_id=p.id, manufacturing_date=mfg, expiration_date=max(exp, mfg),
                               batch_number=f"{''.join(w[0] for w in p.name.split()).upper()}{p.id:02d}-{mfg:%y%m%d}-{n:03d}",
                               quantity_received=qty + sold, quantity_available=qty, quantity_sold=sold)
            db.session.add(b)
            db.session.flush()
            db.session.add(StockTransaction(product_id=p.id, batch_id=b.id, txn_type="stock_in",
                                            quantity=qty + sold, note=f"Batch {b.batch_number} (seed)",
                                            created_at=datetime.combine(mfg, time(6, 30))))
            if sold:
                db.session.add(StockTransaction(product_id=p.id, batch_id=b.id, txn_type="sale", quantity=-sold,
                                                note="Counter sales (seed)", created_at=datetime.combine(mfg, time(12))))
    db.session.commit()
    echo(f"Created {len(cats)} categories, {len(products)} products, {n} inventory batches.")

    # accounts
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@sweetshop.local").lower()
    admin_pw = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
    admin = Admin(email=admin_email, name=os.environ.get("ADMIN_NAME", "Shop Admin"))
    admin.set_password(admin_pw)
    db.session.add(admin)

    demo = User(name="Priya Sharma", email="priya@example.com", phone="+1 732 555 0101", is_verified=True,
                created_at=datetime.utcnow() - timedelta(days=history_days))
    demo.set_password("Customer@123")
    db.session.add(demo)
    db.session.flush()
    db.session.add(Address(user_id=demo.id, label="Home", full_name="Priya Sharma", phone="+1 732 555 0101",
                           line1="48 Oak Tree Rd", line2="Apt 3B", city="Edison", state="NJ", zip_code="08820",
                           is_default=True))
    db.session.add(Address(user_id=demo.id, label="Office", full_name="Priya Sharma", phone="+1 732 555 0101",
                           line1="101 Wood Ave S", city="Iselin", state="NJ", zip_code="08830"))

    customers = [demo]
    used = {demo.email}
    for i in range(extra_customers):
        fn, ln = rng.choice(FIRST), rng.choice(LAST)
        email = f"{fn.lower()}.{ln.lower()}{rng.randint(1, 99)}@example.com"
        if email in used:
            continue
        used.add(email)
        u = User(name=f"{fn} {ln}", email=email, phone=f"+1 {rng.choice(['732', '908', '201', '609'])} 555 {rng.randint(1000, 9999)}",
                 is_verified=True, created_at=datetime.utcnow() - timedelta(days=rng.randint(10, max(history_days, 30))))
        u.set_password(f"Demo-{rng.randint(100000, 999999)}x")
        db.session.add(u)
        db.session.flush()
        city, st, z = rng.choice(CITIES)
        db.session.add(Address(user_id=u.id, label="Home", full_name=u.name, phone=u.phone,
                               line1=f"{rng.randint(10, 999)} {rng.choice(STREETS)}", city=city, state=st,
                               zip_code=z, is_default=True))
        customers.append(u)
    db.session.commit()
    echo(f"Created admin {admin_email} and {len(customers)} customers (demo login priya@example.com).")

    if history_days > 0:
        count = _seed_history(history_days, customers, products, rng, echo)
        echo(f"Generated {count} historical orders.")


def _seed_history(days, customers, products, rng, echo):
    tz = ZoneInfo(current_app.config["STORE_TIMEZONE"])
    today = datetime.now(tz).date()
    sweets = [p for p in products if p.category.kind == "sweet"]
    food = [p for p in products if p.category.kind == "food"]
    weights_sweet = [3 if p.is_featured else 1 for p in sweets]
    weights_food = [3 if p.is_featured else 1 for p in food]
    count = 0
    seq = 0
    inv_seq = 0
    for d_ago in range(days, -1, -1):
        day = today - timedelta(days=d_ago)
        base = 4 + (3 if day.weekday() >= 5 else 0)
        # festival spikes: late Oct–mid Nov (Diwali), Aug (Rakhi), Mar (Holi)
        if (day.month == 10 and day.day >= 20) or (day.month == 11 and day.day <= 15):
            base += 7
        elif day.month in (8, 3):
            base += 2
        base = int(base * (0.85 + 0.25 * ((days - d_ago) / max(days, 1))))  # gentle growth
        n_orders = max(1, base + rng.randint(-2, 3))
        if d_ago == 0:
            now_local = datetime.now(tz)
            n_orders = max(2, min(n_orders, max(2, now_local.hour - 7)))
        for _ in range(n_orders):
            seq += 1
            user = rng.choice(customers)
            addr = user.addresses.filter_by(is_default=True).first() or user.addresses.first()
            picks = {}
            for _ in range(rng.choice([1, 1, 2, 2, 3, 4])):
                pool, w = (sweets, weights_sweet) if rng.random() < .62 else (food, weights_food)
                p = rng.choices(pool, w)[0]
                picks[p] = picks.get(p, 0) + rng.choice([1, 1, 1, 2, 2, 3])
            coupon = "DIWALI10" if (day.month in (10, 11) and rng.random() < .3) else None
            t = compute_totals(list(picks.items()), coupon)
            hour = rng.choice([9, 10, 11, 12, 13, 15, 16, 17, 18, 18, 19, 19, 20, 21])
            if d_ago == 0:
                hour = min(hour, max(8, datetime.now(tz).hour - 1))
            created = _utc(day, hour, rng.randint(0, 59), tz)
            method = rng.choices(["card", "upi", "cod"], [55, 22, 23])[0]

            if d_ago > 3:
                status = rng.choices(["delivered", "cancelled", "refunded"], [93, 4, 3])[0]
            elif d_ago >= 1:
                status = rng.choices(["delivered", "out_for_delivery", "cancelled"], [80, 15, 5])[0]
            else:
                status = rng.choice(["confirmed", "confirmed", "preparing", "ready_for_pickup", "out_for_delivery", "delivered"])

            o = Order(order_number=f"SMM-{day:%y%m%d}-{seq:05X}", user_id=user.id, status=status,
                      customer_name=user.name, customer_email=user.email, customer_phone=user.phone,
                      ship_line1=addr.line1, ship_line2=addr.line2, ship_city=addr.city, ship_state=addr.state,
                      ship_zip=addr.zip_code, billing_address=addr.one_line(), subtotal=t["subtotal"],
                      discount=t["discount"], tax_amount=t["tax"], delivery_charge=t["delivery"],
                      grand_total=t["grand_total"], payment_method=method, otp_verified=True, stock_deducted=False,
                      created_at=created, confirmed_at=created + timedelta(minutes=2), updated_at=created)
            db.session.add(o)
            db.session.flush()
            for r in t["rows"]:
                p = r["product"]
                db.session.add(OrderItem(order_id=o.id, product_id=p.id, product_name=p.name,
                                         category_kind=p.category.kind, unit_label=p.unit_label,
                                         unit_price=r["unit_price"], quantity=r["quantity"], tax_amount=r["tax"],
                                         line_total=r["line_total"]))
            db.session.add(OrderStatusHistory(order_id=o.id, status="pending", note="Order placed", changed_by="customer", created_at=created))
            db.session.add(OrderStatusHistory(order_id=o.id, status="confirmed", note="Payment verified", changed_by="system", created_at=o.confirmed_at))

            paid_online = method != "cod"
            pay = Payment(order_id=o.id, gateway="cod" if method == "cod" else "simulated", method=method,
                          transaction_id=f"{'cod' if method == 'cod' else 'pay_sim'}_{seq:08x}{rng.randint(0, 0xffff):04x}",
                          amount=o.grand_total, currency=current_app.config["CURRENCY"].upper(), created_at=o.confirmed_at,
                          card_brand=rng.choice(["Visa", "Mastercard", "Amex"]) if method == "card" else None,
                          card_last4=rng.choice(["4242", "4444", "0005", "1881"]) if method == "card" else None,
                          upi_handle_masked=f"{user.name[:2].lower()}***@okbank" if method == "upi" else None)
            amount_paid = Decimal("0")
            if paid_online:
                pay.status, pay.verified_at = "succeeded", o.confirmed_at
                o.payment_status, amount_paid = "paid", o.grand_total
            elif status == "delivered":
                delivered = o.confirmed_at + timedelta(hours=rng.randint(1, 4))
                pay.status, pay.verified_at = "succeeded", delivered
                o.payment_status, amount_paid = "paid", o.grand_total
            else:
                pay.status = "initiated"
                o.payment_status = "pending"
            db.session.add(pay)
            db.session.flush()

            inv_seq += 1
            db.session.add(Invoice(invoice_number=f"INV-{day:%Y}-H{inv_seq:06d}", order_id=o.id,
                                   invoice_date=o.confirmed_at, subtotal=o.subtotal, discount=o.discount,
                                   tax_amount=o.tax_amount, delivery_charge=o.delivery_charge,
                                   grand_total=o.grand_total, amount_paid=amount_paid, created_at=o.confirmed_at))

            if status == "delivered":
                o.delivered_at = o.confirmed_at + timedelta(hours=rng.randint(1, 4))
                for s, h in (("preparing", .3), ("out_for_delivery", .8)):
                    db.session.add(OrderStatusHistory(order_id=o.id, status=s, changed_by="Shop Admin",
                                                      created_at=o.confirmed_at + timedelta(hours=h)))
                db.session.add(OrderStatusHistory(order_id=o.id, status="delivered", changed_by="Shop Admin", created_at=o.delivered_at))
            elif status in ("cancelled", "refunded"):
                when = o.confirmed_at + timedelta(minutes=rng.randint(10, 90))
                refund_amt = o.grand_total if o.payment_status == "paid" else Decimal("0")
                c = Cancellation(order_id=o.id, cancelled_by=rng.choice(["customer", "customer", "admin"]),
                                 reason=rng.choice(REASONS), original_amount=o.grand_total, refund_amount=refund_amt,
                                 created_at=when)
                db.session.add(c)
                db.session.flush()
                if refund_amt:
                    c.credit_note_number = f"CN-{day:%Y}-H{c.id:06d}"
                    db.session.add(Refund(order_id=o.id, payment_id=pay.id, cancellation_id=c.id, amount=refund_amt,
                                          status="processed", gateway_refund_id=f"rf_sim_{seq:08x}",
                                          note="Refunded to original payment method", processed_at=when, created_at=when))
                    pay.status = "refunded"
                    o.payment_status = "refunded"
                    o.status = "refunded"
                else:
                    o.status = "cancelled"
                    o.payment_status = "cancelled"
                    pay.status = "failed"
                o.cancelled_at = when
                db.session.add(OrderStatusHistory(order_id=o.id, status=o.status, note=c.reason, changed_by=c.cancelled_by, created_at=when))
            elif status != "confirmed":
                db.session.add(OrderStatusHistory(order_id=o.id, status=status, changed_by="Shop Admin",
                                                  created_at=o.confirmed_at + timedelta(minutes=40)))
            count += 1
        if d_ago % 30 == 0:
            db.session.commit()
    db.session.commit()
    return count
