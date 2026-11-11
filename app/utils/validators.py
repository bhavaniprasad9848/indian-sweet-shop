"""Server-side input validation helpers. Every form is validated here before touching the DB."""
import re

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{7,20}$")
ZIP_RE = re.compile(r"^[A-Za-z0-9 \-]{3,10}$")
NAME_RE = re.compile(r"^[A-Za-zÀ-ɏ .'\-]{2,120}$")


def clean(value, max_len=255):
    return (value or "").strip()[:max_len]


def validate_email(email):
    if not email or not EMAIL_RE.match(email) or len(email) > 255:
        return "Enter a valid email address."
    return None


def validate_phone(phone):
    if not phone or not PHONE_RE.match(phone) or sum(c.isdigit() for c in phone) < 7:
        return "Enter a valid phone number."
    return None


def validate_name(name):
    if not name or not NAME_RE.match(name):
        return "Enter a valid name (letters, spaces, . ' - only)."
    return None


def validate_zip(z):
    if not z or not ZIP_RE.match(z):
        return "Enter a valid ZIP / PIN code."
    return None


def validate_password(pw):
    if not pw or len(pw) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Password must include at least one letter and one number."
    if len(pw) > 128:
        return "Password is too long."
    return None


def validate_address(form):
    """Return (data, errors) for an address-shaped form."""
    data = {
        "full_name": clean(form.get("full_name"), 120),
        "phone": clean(form.get("phone"), 20),
        "line1": clean(form.get("line1"), 200),
        "line2": clean(form.get("line2"), 200),
        "city": clean(form.get("city"), 80),
        "state": clean(form.get("state"), 80),
        "zip_code": clean(form.get("zip_code"), 12),
        "label": clean(form.get("label"), 40) or "Home",
    }
    errors = []
    for check in (validate_name(data["full_name"]), validate_phone(data["phone"]), validate_zip(data["zip_code"])):
        if check:
            errors.append(check)
    if len(data["line1"]) < 4:
        errors.append("Enter the street address.")
    if len(data["city"]) < 2:
        errors.append("Enter the city.")
    if len(data["state"]) < 2:
        errors.append("Enter the state.")
    return data, errors


def to_int(value, default=None, lo=None, hi=None):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None and v < lo:
        return default
    if hi is not None and v > hi:
        return default
    return v
