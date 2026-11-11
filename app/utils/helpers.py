import re
import secrets
from datetime import datetime


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def generate_order_number():
    return f"SMM-{datetime.utcnow():%y%m%d}-{secrets.token_hex(3).upper()}"


def generate_doc_number(prefix, seq_id):
    return f"{prefix}-{datetime.utcnow():%Y}-{seq_id:06d}"


def generate_txn_id(prefix="SIM"):
    return f"{prefix}_{secrets.token_hex(10)}"


def mask_email(email):
    name, _, domain = (email or "").partition("@")
    if not domain:
        return email
    return f"{name[:2]}{'•' * max(1, len(name) - 2)}@{domain}"
