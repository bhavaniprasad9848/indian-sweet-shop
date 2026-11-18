"""Add or replace a product's photo from the command line. The image is stored in the database.

    python scripts/set_product_image.py --list
    python scripts/set_product_image.py mysore-pak "C:\\Users\\you\\Pictures\\sweet.jpeg"
    python scripts/set_product_image.py mysore-pak --clear      # back to the built-in illustration

Uses DATABASE_URL from .env, so on your PC it updates the live Neon database.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Product  # noqa: E402
from app.services.image_service import store_product_image  # noqa: E402

parser = argparse.ArgumentParser(description="Set a product's photo.")
parser.add_argument("slug", nargs="?", help="product slug, e.g. mysore-pak (see --list)")
parser.add_argument("image", nargs="?", help="path to a PNG, JPG, WEBP or SVG file")
parser.add_argument("--list", action="store_true", help="list products with their slugs and current images")
parser.add_argument("--clear", action="store_true", help="remove the photo and use the default illustration")
args = parser.parse_args()

app = create_app(os.environ.get("FLASK_CONFIG", "development"))
with app.app_context():
    if args.list or not args.slug:
        for p in Product.query.order_by(Product.name).all():
            print(f"{p.slug:<22} {p.name:<22} {p.image or '(default illustration)'}")
        sys.exit(0)

    product = Product.query.filter_by(slug=args.slug).first()
    if not product:
        sys.exit(f"No product with slug '{args.slug}'. Run with --list to see slugs.")

    if args.clear:
        slug_art = f"images/products/{product.slug}.svg"
        art_exists = os.path.exists(os.path.join(app.static_folder, slug_art))
        product.image = slug_art if art_exists else None
        db.session.commit()
        print(f"{product.name}: photo removed, now using {product.image or 'the placeholder'}")
        sys.exit(0)

    if not args.image or not os.path.isfile(args.image):
        sys.exit("Give the path to an image file, e.g. \"C:\\Users\\you\\Pictures\\sweet.jpeg\"")
    with open(args.image, "rb") as fh:
        data = fh.read()
    try:
        ref = store_product_image(product, os.path.basename(args.image), data)
    except ValueError as e:
        sys.exit(f"Not saved: {e}")
    db.session.commit()
    print(f"{product.name}: photo saved in the database as {ref} ({len(data) // 1024} KB)")
    print(f"It will show at /product/{product.slug} once the site is running this version of the code.")
