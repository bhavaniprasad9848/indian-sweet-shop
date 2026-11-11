# Shree Mithai Mahal — Indian Sweet Shop Management & Online Ordering

A full-stack Flask application for an Indian sweet shop: a festive storefront where customers browse mithai and snacks, pay online and receive PDF tax invoices by email, plus an admin office for inventory batches, expiry tracking, orders, revenue and reports.

## Features

**Customers**
- Register with email OTP; every sign-in is password + email OTP
- Catalogue of 15 sweets and 12 food items with ingredients (allergens flagged), pack size, live stock, best-before date and veg / non-veg marks
- Search (name, description, ingredient), filter (type, category, price, in-stock, veg) and sort (price, name, availability, freshness)
- Cart with quantity steppers, GST, delivery charge (free above a threshold) and festival coupons (`DIWALI10`, `SWEET5`)
- Checkout with saved addresses, optional separate billing address and delivery instructions
- Order OTP → payment → confirmation. The order stays a *pending draft* until both the OTP and the payment are verified
- Card, UPI and Cash on Delivery through the built-in test gateway, or Stripe Checkout in test mode
- HTML confirmation email styled like a sweet-shop bill, with the PDF invoice attached
- Order tracking timeline, invoice download, and self-service cancellation with automatic refund, stock restoration, credit note PDF and cancellation email

**Admin (separate portal, password + OTP)**
- Dashboard: 9 summary cards, nearest-expiry ribbon, Chart.js daily / weekly / monthly / yearly trends, best-selling sweets and food, category and payment-method split, date-range filter
- Daily revenue: orders, successful payments, collections, taxes, refunds, cancellations, net revenue and COD shown separately — all computed from transactions
- Products: create / edit / deactivate / delete, image upload, ingredients, price, shelf life
- Inventory batches: batch number, manufacturing and expiry dates, received / sold / available, adjustments, write-offs, full stock history
- Expiry tracker: red (expired), orange (today / ≤ 3 days), yellow (≤ 7 days), green (fresh) in five sections. Expired batches can never be sold; sales deduct from the earliest-expiring batch first (FIFO)
- Orders: search and filter, status workflow (Pending → Confirmed → Preparing → Ready for Pickup → Out for Delivery → Delivered, plus Cancelled / Refunded), customer emails on each change; marking a COD order delivered records the cash payment
- Reports with PDF and Excel export: sales (daily / weekly / monthly / yearly), inventory, expiry, best sellers, customers, payments, cancellations & refunds
- Email log with previews of everything sent

## Quick start

Requires Python 3.10+.

```bash
cd indian_sweet_shop
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then set SECRET_KEY and OTP_SECRET
python scripts/init_db.py            # creates tables + sample data (~14 months of orders)
python run.py
```

Open http://127.0.0.1:5000.

| Portal | URL | Login |
|---|---|---|
| Customer | `/login` | `priya@example.com` / `Customer@123` |
| Admin | `/admin/login` | `admin@sweetshop.local` / `Admin@12345` |

Change the admin password before deploying (set `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env` before seeding, or use `flask --app run.py create-admin`).

**OTP codes in development.** Without SMTP settings, every email is saved to `instance/outbox/*.eml` and listed under *Admin → Email log*. With `SHOW_DEV_OTP=true` (the development default) the code is also shown on screen so you can test quickly. Production config forces this off.

Other setup commands:

```bash
python scripts/init_db.py --reset          # wipe and reseed
python scripts/init_db.py --no-history     # catalogue and accounts only
flask --app run.py init-db [--drop]
flask --app run.py seed
flask --app run.py create-admin
python scripts/generate_artwork.py         # regenerate the SVG product illustrations
```

## Configuration

Everything lives in `.env` (see `.env.example`); nothing secret is in the source.

### Email (SMTP)
```
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=you@gmail.com
MAIL_PASSWORD=<16-character app password>
MAIL_DEFAULT_SENDER=Shree Mithai Mahal <you@gmail.com>
SHOW_DEV_OTP=false
```
For Gmail, turn on 2-Step Verification and create an App Password. Any SMTP provider works (SendGrid, Mailgun, SES, Mailtrap for testing). Failed sends are logged with the error and never break checkout.

### Payments
- `PAYMENT_GATEWAY=simulated` (default) — no keys needed. Cards are Luhn-checked and behave like Stripe test cards: `4242 4242 4242 4242` succeeds, `4000 0000 0000 0002` is declined, `4000 0000 0000 9995` has insufficient funds. UPI: `success@upi` approves, `failure@upi` declines. Each response is HMAC-signed and verified server-side before an order is confirmed.
- `PAYMENT_GATEWAY=stripe` with `STRIPE_SECRET_KEY=sk_test_…` — adds a "Pay with Stripe" button using Stripe Checkout. The return URL re-fetches the Checkout Session from Stripe and checks status, amount and order reference. Optionally set `STRIPE_WEBHOOK_SECRET` and point a webhook at `/checkout/webhooks/stripe` (`checkout.session.completed`). Cancellations refund through `stripe.Refund`.
- Only the card brand and last four digits are stored — never the full number or CVC.

### Database
SQLite at `instance/sweetshop.db` by default.

**Cloud Postgres (Supabase, free):**
1. Create a project at https://supabase.com (pick a region near you, save the database password).
2. Click **Connect** → copy the **Session pooler** connection string (works on IPv4 networks).
3. In `.env`, set `DATABASE_URL=` to that string with `[YOUR-PASSWORD]` replaced. URL-encode special characters in the password (`@` → `%40`, `#` → `%23`).
4. Run `python scripts/init_db.py`, then `python run.py`.

Any Postgres URL works the same way (Neon, Render, Railway, Aiven); `postgres://` and `postgresql://` forms are both accepted.

**MySQL:**
```sql
CREATE DATABASE sweetshop CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'sweetshop'@'localhost' IDENTIFIED BY 'strong-password';
GRANT ALL ON sweetshop.* TO 'sweetshop'@'localhost';
```
```
DATABASE_URL=mysql+pymysql://sweetshop:strong-password@localhost:3306/sweetshop?charset=utf8mb4
```
then run `python scripts/init_db.py`. FIFO stock deduction uses `SELECT … FOR UPDATE` on MySQL.

Schema migrations (Flask-Migrate / Alembic) are in `migrations/` with an initial revision. `init_db.py` creates tables directly; if you prefer Alembic, run `flask --app run.py db upgrade` on an empty database instead, then `flask --app run.py seed`. After changing models:
```bash
flask --app run.py db migrate -m "describe change"
flask --app run.py db upgrade
```

### Store details
`STORE_NAME`, address, phone, emails, `STORE_GSTIN` (shown on invoices when set), `STORE_TIMEZONE` (day boundaries for revenue reports), `CURRENCY_SYMBOL`, `TAX_RATE`, `TAX_LABEL`, `DELIVERY_CHARGE`, `FREE_DELIVERY_ABOVE`.

## How the order flow works

1. **Checkout** validates the cart against sellable stock and creates a `pending` order with price snapshots. Older unpaid drafts for the same customer are discarded.
2. **OTP** — a 6-digit code (HMAC-SHA256 hashed with a per-code salt, 5-minute expiry, 5 attempts, 30-second resend cooldown, 6 per hour) is emailed. Payment pages refuse unverified orders.
3. **Payment** — the gateway response is verified server-side. Each payment form carries a one-time nonce and the order is confirmed idempotently, so a double-click or refresh can't charge twice.
4. **Confirmation** — stock is deducted FIFO by expiry across batches (each movement logged per batch), the invoice is numbered and stored, a PDF is generated and emailed. If stock ran out in the meantime, the order is cancelled and the payment refunded automatically.
5. **Cancellation** (Pending / Confirmed / Preparing) — units go back to the exact batches they came from, online payments are refunded through the original gateway, a credit note is issued and emailed.

## Security

- Passwords hashed with Werkzeug (scrypt); OTPs stored only as salted HMACs
- Role separation: customers and admins are separate tables and login portals; `@admin_required` on every admin route; customers can only load their own orders and documents (others return 404)
- CSRF protection on every form and AJAX call (Flask-WTF); the Stripe webhook is verified by signature instead
- SQLAlchemy ORM with bound parameters throughout; server-side validation of all input
- Session cookies HttpOnly + SameSite=Lax (Secure in production), session regenerated on login, POST-only logout, 8-hour lifetime
- Login throttling (5 attempts / 15 minutes per IP + email) and OTP send limits
- Upload whitelist (png / jpg / webp / svg, 4 MB); secrets only from environment; production refuses to start with the default `SECRET_KEY`

The login limiter is in-process; behind several workers, swap it for Redis-backed limiting.

## Tests

```bash
pytest
```
25 tests cover registration and two-step login, OTP hashing / expiry / attempt and send limits, role access, cart maths and coupons, the full card / UPI / COD checkout, declined cards, double-submit protection, FIFO deduction across batches, expired-stock exclusion, invoice and email contents, cancellation with stock restore / refund / credit note, admin status transitions, charts JSON vs. DB totals, and PDF / Excel exports for every report.

## Project layout

```
indian_sweet_shop/
├── app/
│   ├── __init__.py          app factory, filters, CLI commands
│   ├── extensions.py        db, login manager, CSRF, migrate
│   ├── models.py            18 tables + order status history
│   ├── seed.py              sample catalogue, batches, customers, order history
│   ├── routes/              main · auth · cart · checkout · account · admin
│   ├── services/            otp · email · inventory · cart · payment · order · invoice · analytics · report
│   ├── templates/           storefront, account, admin, email and error templates
│   ├── static/css|js|images
│   └── utils/               validators, security (RBAC, rate limit), helpers
├── migrations/              Alembic environment + initial revision
├── scripts/                 init_db.py, generate_artwork.py
├── tests/
├── config.py · run.py · requirements.txt · .env.example
```

## Deploying to Render (free)

1. Push the project to GitHub.
2. At https://render.com sign in with GitHub → **New → Blueprint** → choose the repo. Render reads `render.yaml`.
3. When asked, paste your Neon/Postgres connection string into `DATABASE_URL` (leave the mail fields blank for now).
4. Click **Apply**. After the build (~3 minutes) the app is live at `https://shree-mithai-mahal.onrender.com` (or similar).

If the database is empty, run `python scripts/init_db.py` once from your PC with the same `DATABASE_URL`.
The blueprint starts with `SHOW_DEV_OTP=true` so the demo works without email; add Gmail SMTP settings in
Render → Environment and set `SHOW_DEV_OTP=false` before real customers use it. Free instances sleep after
15 idle minutes, and uploaded product images are lost on redeploy (use the bundled artwork or external hosting).

### Other hosts

```bash
FLASK_CONFIG=production gunicorn -w 3 -b 0.0.0.0:8000 "run:app"
```
Serve over HTTPS (secure cookies are on in production), use MySQL, configure SMTP, and set `SHOW_DEV_OTP=false`. The front end loads Bootstrap 5, Bootstrap Icons, Chart.js and Google Fonts from CDNs.

## Notes

- Product images are SVG illustrations generated by `scripts/generate_artwork.py`; upload photos from *Admin → Products → Edit* to replace them.
- Sample order history is generated directly into the order, payment, invoice and refund tables so the charts and reports have data; it doesn't draw down today's batches.
- Prices are in USD with a 5% GST-style tax by default; switch currency and tax in `.env`.
