"""Admin dashboard: analytics, products, inventory & expiry, orders, revenue, reports, email log."""
import io
import os
import uuid
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file,
                   url_for)
from flask_login import current_user
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (Category, EmailLog, InventoryBatch, Order, OrderItem, Product, ProductIngredient,
                      StockTransaction, User, ORDER_STATUSES)
from ..services import analytics_service as an
from ..services import inventory_service as inv
from ..services import report_service as rs
from ..services.email_service import provider_label
from ..services.invoice_service import build_credit_note_pdf, build_invoice_pdf
from ..services.order_service import ADMIN_TRANSITIONS, OrderError, update_status
from ..utils.helpers import slugify
from ..utils.security import admin_required
from ..utils.validators import clean, to_int

bp = Blueprint("admin", __name__)
ALLOWED_IMAGES = {"png", "jpg", "jpeg", "webp", "svg"}


def _date_arg(name, default):
    try:
        return datetime.strptime(request.args.get(name, ""), "%Y-%m-%d").date()
    except ValueError:
        return default


def _range(default_days=30):
    end = _date_arg("end", an.local_today())
    start = _date_arg("start", end - timedelta(days=default_days - 1))
    if start > end:
        start, end = end, start
    if (end - start).days > 731:
        start = end - timedelta(days=731)
    return start, end


# ------------------------------------------------------------------ dashboard
@bp.route("/")
@admin_required
def dashboard():
    start, end = _range(30)
    buckets = inv.expiry_buckets()
    nearest = (buckets["expired"] + buckets["today"] + buckets["3days"] + buckets["7days"] + buckets["fresh"])[:8]
    recent = Order.query.filter(Order.status != "pending").order_by(Order.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html", cards=an.dashboard_summary(), today=an.daily_revenue(),
                           nearest=nearest, expiry_level=inv.expiry_level, recent=recent, start=start, end=end,
                           low_stock=inv.low_stock_products()[:6])


@bp.route("/api/charts")
@admin_required
def api_charts():
    start, end = _range(30)
    return jsonify(an.chart_data(start, end))


@bp.route("/revenue")
@admin_required
def revenue():
    day = _date_arg("day", an.local_today())
    data = an.daily_revenue(day)
    s, e = an.utc_bounds(day, day)
    orders = (Order.query.filter(Order.confirmed_at >= s, Order.confirmed_at < e)
              .order_by(Order.confirmed_at.desc()).all())
    return render_template("admin/revenue.html", r=data, orders=orders, day=day,
                           prev=day - timedelta(days=1), next=day + timedelta(days=1))


# ------------------------------------------------------------------ products
@bp.route("/products")
@admin_required
def products():
    q = clean(request.args.get("q"), 80)
    query = Product.query.join(Category)
    if q:
        query = query.filter(or_(Product.name.ilike(f"%{q}%"), Category.name.ilike(f"%{q}%")))
    if request.args.get("show") == "inactive":
        query = query.filter(Product.is_active.is_(False))
    items = query.order_by(Category.kind.desc(), Category.sort_order, Product.name).all()
    stocks, nearest = inv.stock_map(), inv.nearest_expiry_map()
    return render_template("admin/products.html", products=items, stocks=stocks, nearest=nearest, q=q,
                           expiry_level=inv.expiry_level, low=current_app.config["LOW_STOCK_THRESHOLD"])


def _save_image(file):
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGES:
        raise ValueError("Image must be PNG, JPG, WEBP or SVG.")
    name = f"{uuid.uuid4().hex[:12]}_{secure_filename(file.filename)}"
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    return f"images/products/uploads/{name}"


def _apply_product_form(p, form, files):
    errors = []
    p.name = clean(form.get("name"), 120)
    p.description = clean(form.get("description"), 2000)
    p.unit_label = clean(form.get("unit_label"), 60) or "1 box"
    p.weight_grams = to_int(form.get("weight_grams"), None, lo=1, hi=100000)
    p.shelf_life_days = to_int(form.get("shelf_life_days"), 3, lo=1, hi=365)
    p.is_veg = form.get("is_veg") == "1"
    p.is_featured = bool(form.get("is_featured"))
    p.is_active = bool(form.get("is_active"))
    cat = db.session.get(Category, to_int(form.get("category_id"), 0) or 0)
    try:
        price = round(float(form.get("price", "")), 2)
        if price <= 0 or price > 10000:
            raise ValueError
        p.price = price
    except ValueError:
        errors.append("Enter a valid price.")
    if len(p.name or "") < 2:
        errors.append("Enter a product name.")
    if not cat:
        errors.append("Choose a category.")
    else:
        p.category_id = cat.id
    try:
        img = _save_image(files.get("image"))
        if img:
            p.image = img
    except ValueError as e:
        errors.append(str(e))
    if not errors:
        base = slugify(p.name)
        slug, n = base, 2
        while Product.query.filter(Product.slug == slug, Product.id != (p.id or 0)).first():
            slug, n = f"{base}-{n}", n + 1
        p.slug = slug
        p.ingredients.clear()
        for raw in (form.get("ingredients") or "").split(","):
            raw = raw.strip()
            if raw:
                p.ingredients.append(ProductIngredient(name=raw.rstrip("*").strip()[:80], is_allergen=raw.endswith("*")))
    return errors


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    p = Product(is_active=True, is_veg=True, shelf_life_days=5)
    if request.method == "POST":
        errors = _apply_product_form(p, request.form, request.files)
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, "danger")
        else:
            db.session.add(p)
            db.session.flush()
            qty = to_int(request.form.get("initial_stock"), 0, lo=0, hi=100000)
            if qty:
                inv.add_stock(p, qty, admin_id=current_user.id, commit=False)
            db.session.commit()
            flash(f"{p.name} created.", "success")
            return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", p=p, categories=Category.query.order_by(Category.kind.desc(),
                           Category.sort_order).all(), is_new=True)


@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(pid):
    p = db.session.get(Product, pid) or abort(404)
    if request.method == "POST":
        errors = _apply_product_form(p, request.form, request.files)
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, "danger")
        else:
            db.session.commit()
            flash(f"{p.name} updated.", "success")
            return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", p=p, categories=Category.query.order_by(Category.kind.desc(),
                           Category.sort_order).all(), is_new=False)


@bp.route("/products/<int:pid>/toggle", methods=["POST"])
@admin_required
def product_toggle(pid):
    p = db.session.get(Product, pid) or abort(404)
    p.is_active = not p.is_active
    db.session.commit()
    flash(f"{p.name} {'activated' if p.is_active else 'deactivated'}.", "info")
    return redirect(request.referrer or url_for("admin.products"))


@bp.route("/products/<int:pid>/delete", methods=["POST"])
@admin_required
def product_delete(pid):
    p = db.session.get(Product, pid) or abort(404)
    if OrderItem.query.filter_by(product_id=p.id).first():
        p.is_active = False
        db.session.commit()
        flash(f"{p.name} has order history, so it was deactivated instead of deleted.", "warning")
    else:
        StockTransaction.query.filter_by(product_id=p.id).delete()
        db.session.delete(p)
        db.session.commit()
        flash(f"{p.name} deleted.", "info")
    return redirect(url_for("admin.products"))


# ------------------------------------------------------------------ inventory
@bp.route("/inventory")
@admin_required
def inventory():
    prods = Product.query.join(Category).order_by(Category.kind.desc(), Product.name).all()
    stocks, nearest = inv.stock_map(), inv.nearest_expiry_map()
    sold = dict(db.session.query(InventoryBatch.product_id, db.func.sum(InventoryBatch.quantity_sold))
                .group_by(InventoryBatch.product_id).all())
    return render_template("admin/inventory.html", products=prods, stocks=stocks, nearest=nearest, sold=sold,
                           expiry_level=inv.expiry_level, low=current_app.config["LOW_STOCK_THRESHOLD"],
                           today=date.today())


@bp.route("/inventory/<int:pid>", methods=["GET", "POST"])
@admin_required
def product_stock(pid):
    p = db.session.get(Product, pid) or abort(404)
    if request.method == "POST":
        qty = to_int(request.form.get("quantity"), 0, lo=1, hi=100000)
        try:
            mfg = datetime.strptime(request.form.get("manufacturing_date"), "%Y-%m-%d").date()
            exp = datetime.strptime(request.form.get("expiration_date"), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            mfg = exp = None
        if not qty or not mfg or not exp:
            flash("Enter quantity, manufacturing date and expiration date.", "danger")
        else:
            try:
                b = inv.add_stock(p, qty, mfg, exp, admin_id=current_user.id,
                                  batch_number=clean(request.form.get("batch_number"), 40) or None,
                                  note=clean(request.form.get("note"), 200) or None)
                flash(f"Added {qty} units as batch {b.batch_number}.", "success")
            except ValueError as e:
                flash(str(e), "danger")
            except Exception:
                db.session.rollback()
                flash("That batch number already exists.", "danger")
        return redirect(url_for("admin.product_stock", pid=pid))
    batches = p.batches.order_by(InventoryBatch.expiration_date.desc()).all()
    history = (StockTransaction.query.filter_by(product_id=pid).order_by(StockTransaction.created_at.desc())
               .limit(100).all())
    return render_template("admin/product_stock.html", p=p, batches=batches, history=history,
                           stock=inv.available_stock(pid), expiry_level=inv.expiry_level, today=date.today(),
                           default_exp=date.today() + timedelta(days=p.shelf_life_days or 3))


@bp.route("/batches/<int:bid>/adjust", methods=["POST"])
@admin_required
def batch_adjust(bid):
    b = db.session.get(InventoryBatch, bid) or abort(404)
    qty = to_int(request.form.get("quantity_available"), None, lo=0, hi=100000)
    if qty is None:
        flash("Enter a valid quantity.", "danger")
    else:
        inv.adjust_batch(b, qty, admin_id=current_user.id, note=clean(request.form.get("note"), 200) or None)
        flash(f"Batch {b.batch_number} set to {qty} units.", "success")
    return redirect(request.referrer or url_for("admin.product_stock", pid=b.product_id))


@bp.route("/batches/<int:bid>/writeoff", methods=["POST"])
@admin_required
def batch_writeoff(bid):
    b = db.session.get(InventoryBatch, bid) or abort(404)
    inv.write_off_batch(b, admin_id=current_user.id)
    flash(f"Batch {b.batch_number} written off.", "info")
    return redirect(request.referrer or url_for("admin.expiry"))


@bp.route("/expiry")
@admin_required
def expiry():
    return render_template("admin/expiry.html", buckets=inv.expiry_buckets(), expiry_level=inv.expiry_level)


@bp.route("/stock-history")
@admin_required
def stock_history():
    t = request.args.get("type", "")
    q = StockTransaction.query
    if t:
        q = q.filter_by(txn_type=t)
    page = to_int(request.args.get("page"), 1, lo=1)
    pag = q.order_by(StockTransaction.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    return render_template("admin/stock_history.html", pag=pag, t=t)


# ------------------------------------------------------------------ orders
@bp.route("/orders")
@admin_required
def orders():
    status = request.args.get("status", "")
    q_text = clean(request.args.get("q"), 80)
    query = Order.query
    if status == "pending":
        query = query.filter(Order.status == "pending")
    elif status in dict(ORDER_STATUSES):
        query = query.filter(Order.status == status)
    else:
        query = query.filter(Order.status != "pending")
    if q_text:
        like = f"%{q_text}%"
        query = query.filter(or_(Order.order_number.ilike(like), Order.customer_name.ilike(like),
                                 Order.customer_email.ilike(like), Order.customer_phone.ilike(like)))
    if request.args.get("start") or request.args.get("end"):
        start, end = _range(30)
        s, e = an.utc_bounds(start, end)
        query = query.filter(Order.created_at >= s, Order.created_at < e)
    page = to_int(request.args.get("page"), 1, lo=1)
    pag = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    counts = dict(db.session.query(Order.status, db.func.count(Order.id)).group_by(Order.status).all())
    return render_template("admin/orders.html", pag=pag, status=status, q=q_text, counts=counts,
                           statuses=ORDER_STATUSES)


@bp.route("/orders/<number>", methods=["GET", "POST"])
@admin_required
def order_detail(number):
    order = Order.query.filter_by(order_number=number).first_or_404()
    if request.method == "POST":
        try:
            update_status(order, request.form.get("status"), admin_name=current_user.name,
                          note=clean(request.form.get("note"), 250) or None,
                          notify=bool(request.form.get("notify")))
            flash(f"Order moved to {order.status_label}.", "success")
        except OrderError as e:
            flash(str(e), "danger")
        return redirect(url_for("admin.order_detail", number=number))
    allowed = [(s, l) for s, l in ORDER_STATUSES if s in ADMIN_TRANSITIONS.get(order.status, set())]
    emails = EmailLog.query.filter_by(order_id=order.id).order_by(EmailLog.created_at.desc()).all()
    return render_template("admin/order_detail.html", order=order, allowed=allowed, emails=emails,
                           payments=order.payments.all(), refunds=order.refunds.all())


@bp.route("/orders/<number>/invoice.pdf")
@admin_required
def order_invoice(number):
    order = Order.query.filter_by(order_number=number).first_or_404()
    if not order.invoice:
        abort(404)
    return send_file(io.BytesIO(build_invoice_pdf(order)), mimetype="application/pdf",
                     download_name=f"Invoice-{order.invoice.invoice_number}.pdf")


@bp.route("/orders/<number>/credit-note.pdf")
@admin_required
def order_credit_note(number):
    order = Order.query.filter_by(order_number=number).first_or_404()
    if not order.cancellation or not order.cancellation.credit_note_number:
        abort(404)
    return send_file(io.BytesIO(build_credit_note_pdf(order)), mimetype="application/pdf",
                     download_name=f"CreditNote-{order.cancellation.credit_note_number}.pdf")


# ------------------------------------------------------------------ customers / emails
@bp.route("/customers")
@admin_required
def customers():
    q = clean(request.args.get("q"), 80)
    query = User.query
    if q:
        query = query.filter(or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"), User.phone.ilike(f"%{q}%")))
    stats = dict((uid, (c, t)) for uid, c, t in db.session.query(
        Order.user_id, db.func.count(Order.id), db.func.sum(Order.grand_total))
        .filter(Order.status.in_(an.SOLD_STATUSES)).group_by(Order.user_id).all())
    page = to_int(request.args.get("page"), 1, lo=1)
    pag = query.order_by(User.created_at.desc()).paginate(page=page, per_page=30, error_out=False)
    return render_template("admin/customers.html", pag=pag, stats=stats, q=q)


@bp.route("/emails")
@admin_required
def emails():
    page = to_int(request.args.get("page"), 1, lo=1)
    cat = request.args.get("category", "")
    q = EmailLog.query
    if cat:
        q = q.filter_by(category=cat)
    pag = q.order_by(EmailLog.created_at.desc()).paginate(page=page, per_page=30, error_out=False)
    return render_template("admin/emails.html", pag=pag, cat=cat, provider=provider_label())


@bp.route("/emails/<int:eid>")
@admin_required
def email_view(eid):
    e = db.session.get(EmailLog, eid) or abort(404)
    if e.category == "otp" and request.args.get("raw") != "1":
        return render_template("admin/email_view.html", e=e, masked=True)
    return render_template("admin/email_view.html", e=e, masked=False)


# ------------------------------------------------------------------ reports
@bp.route("/reports")
@admin_required
def reports():
    kind = request.args.get("kind", "sales")
    if kind not in rs.REPORTS:
        kind = "sales"
    period = request.args.get("period", "daily")
    if period not in rs.PERIODS:
        period = "daily"
    start, end = _range(30)
    report = rs.build_report(kind, start, end, period)
    fmt = request.args.get("export")
    stem = f"{kind}_{start:%Y%m%d}_{end:%Y%m%d}"
    if fmt == "xlsx":
        return send_file(io.BytesIO(rs.export_excel(report)), as_attachment=True, download_name=f"{stem}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt == "pdf":
        return send_file(io.BytesIO(rs.export_pdf(report)), as_attachment=True, download_name=f"{stem}.pdf",
                         mimetype="application/pdf")
    return render_template("admin/reports.html", report=report, reports=rs.REPORTS, periods=rs.PERIODS,
                           fmt_cell=rs.fmt_cell)
