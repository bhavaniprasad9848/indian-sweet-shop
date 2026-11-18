"""Product photos stored in the database (product_images table).

Used by the admin upload form and by scripts/set_product_image.py.
"""
from ..extensions import db
from ..models import ProductImage

IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
               "svg": "image/svg+xml"}
IMAGE_SIGNATURES = {"image/png": (b"\x89PNG",), "image/jpeg": (b"\xff\xd8\xff",), "image/webp": (b"RIFF",)}
MAX_BYTES = 4 * 1024 * 1024


def store_product_image(product, filename, data):
    """Validate an image, save it in product_images, point the product at it, and return the "db:<id>" reference.

    The caller commits.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = IMAGE_TYPES.get(ext)
    if not content_type:
        raise ValueError("Image must be PNG, JPG, WEBP or SVG.")
    if not data:
        raise ValueError("The image file is empty.")
    if len(data) > MAX_BYTES:
        raise ValueError("Image is larger than 4 MB.")
    signatures = IMAGE_SIGNATURES.get(content_type)
    if signatures and not data.startswith(signatures):
        raise ValueError("That file doesn't look like a real image.")
    img = ProductImage(product_id=product.id if product is not None and product.id else None,
                       filename=filename[-255:], content_type=content_type, size_bytes=len(data), data=data)
    db.session.add(img)
    db.session.flush()
    ref = f"db:{img.id}"
    if product is not None:
        product.image = ref
    return ref
