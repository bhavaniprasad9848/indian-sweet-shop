"""Storefront: home page, catalog with search/filter/sort, product detail."""
from flask import Blueprint, abort, render_template, request
from sqlalchemy import or_

from ..models import Category, Product, ProductIngredient
from ..services import inventory_service as inv
from ..utils.validators import clean

bp = Blueprint("main", __name__)

SORTS = {
    "featured": "Featured",
    "name": "Name (A–Z)",
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
    "availability": "Most available",
    "expiry": "Freshest first",
}


def _decorate(products):
    ids = [p.id for p in products]
    stocks, expiry = inv.stock_map(ids), inv.nearest_expiry_map(ids)
    return [{"p": p, "stock": stocks.get(p.id, 0), "expiry": expiry.get(p.id)} for p in products]


@bp.route("/")
def home():
    base = Product.query.filter_by(is_active=True).join(Category)
    featured = base.filter(Product.is_featured.is_(True)).order_by(Product.name).limit(8).all()
    sweets = base.filter(Category.kind == "sweet").order_by(Product.is_featured.desc(), Product.name).limit(8).all()
    food = base.filter(Category.kind == "food").order_by(Product.is_featured.desc(), Product.name).limit(8).all()
    categories = Category.query.order_by(Category.kind.desc(), Category.sort_order).all()
    return render_template("main/home.html", featured=_decorate(featured), sweets=_decorate(sweets),
                           food=_decorate(food), categories=categories)


@bp.route("/shop")
def shop():
    q = clean(request.args.get("q"), 80)
    cat = clean(request.args.get("category"), 80)
    kind = request.args.get("kind") if request.args.get("kind") in ("sweet", "food") else ""
    sort = request.args.get("sort") if request.args.get("sort") in SORTS else "featured"
    in_stock = request.args.get("in_stock") == "1"
    veg = request.args.get("veg") == "1"
    max_price = request.args.get("max_price", type=float)

    query = Product.query.filter_by(is_active=True).join(Category)
    if q:
        like = f"%{q}%"
        query = query.outerjoin(ProductIngredient).filter(
            or_(Product.name.ilike(like), Product.description.ilike(like), Category.name.ilike(like),
                ProductIngredient.name.ilike(like))).distinct()
    if cat:
        query = query.filter(Category.slug == cat)
    if kind:
        query = query.filter(Category.kind == kind)
    if veg:
        query = query.filter(Product.is_veg.is_(True))
    if max_price:
        query = query.filter(Product.price <= max_price)
    if sort == "name":
        query = query.order_by(Product.name)
    elif sort == "price_asc":
        query = query.order_by(Product.price, Product.name)
    elif sort == "price_desc":
        query = query.order_by(Product.price.desc(), Product.name)
    else:
        query = query.order_by(Product.is_featured.desc(), Category.sort_order, Product.name)

    items = _decorate(query.all())
    if in_stock:
        items = [i for i in items if i["stock"] > 0]
    if sort == "availability":
        items.sort(key=lambda i: -i["stock"])
    elif sort == "expiry":
        items.sort(key=lambda i: (i["expiry"] is None, -(i["expiry"].toordinal() if i["expiry"] else 0)))

    categories = Category.query.order_by(Category.kind.desc(), Category.sort_order).all()
    return render_template("main/shop.html", items=items, categories=categories, sorts=SORTS,
                           f={"q": q, "category": cat, "kind": kind, "sort": sort, "in_stock": in_stock,
                              "veg": veg, "max_price": max_price or ""})


@bp.route("/product/<slug>")
def product(slug):
    p = Product.query.filter_by(slug=slug).first()
    if not p or not p.is_active:
        abort(404)
    info = _decorate([p])[0]
    related = (Product.query.filter(Product.category_id == p.category_id, Product.id != p.id,
                                    Product.is_active.is_(True)).limit(4).all())
    if len(related) < 4:
        related += (Product.query.join(Category).filter(Category.kind == p.category.kind, Product.id != p.id,
                                                        Product.is_active.is_(True),
                                                        ~Product.id.in_([r.id for r in related] or [0]))
                    .limit(4 - len(related)).all())
    level = inv.expiry_level(info["expiry"]) if info["expiry"] else None
    return render_template("main/product.html", item=info, related=_decorate(related), level=level)


@bp.route("/about")
def about():
    return render_template("main/about.html")
