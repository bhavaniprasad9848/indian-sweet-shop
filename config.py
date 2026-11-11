"""Application configuration. All secrets come from environment variables (.env)."""
import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _db_url(raw):
    """Accept URLs as cloud providers print them (postgres://, postgresql://) and pick the psycopg driver."""
    if not raw:
        return raw
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    OTP_SECRET = os.environ.get("OTP_SECRET") or SECRET_KEY

    # Database: SQLite by default, MySQL via DATABASE_URL=mysql+pymysql://user:pass@host/db
    SQLALCHEMY_DATABASE_URI = _db_url(os.environ.get("DATABASE_URL")) or (
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "sweetshop.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pre_ping + recycle keep pooled connections healthy when a cloud database drops idle ones
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}

    # Sessions
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSION_HOURS", 8)))
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_TIME_LIMIT = 3600 * 4
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB uploads

    # Store / invoice branding
    STORE_NAME = os.environ.get("STORE_NAME", "Shree Mithai Mahal")
    STORE_TAGLINE = os.environ.get("STORE_TAGLINE", "Pure Ghee Sweets & Savouries since 1987")
    STORE_ADDRESS = os.environ.get("STORE_ADDRESS", "214 Diwali Market Street, Edison, NJ 08820")
    STORE_PHONE = os.environ.get("STORE_PHONE", "+1 (732) 555-0142")
    STORE_EMAIL = os.environ.get("STORE_EMAIL", "orders@shreemithaimahal.example")
    STORE_GSTIN = os.environ.get("STORE_GSTIN", "")  # leave empty to hide
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@shreemithaimahal.example")

    CURRENCY = os.environ.get("CURRENCY", "usd")
    CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "$")
    TAX_RATE = float(os.environ.get("TAX_RATE", "0.05"))  # 5% (GST on sweets)
    TAX_LABEL = os.environ.get("TAX_LABEL", "GST 5%")
    DELIVERY_CHARGE = float(os.environ.get("DELIVERY_CHARGE", "4.99"))
    FREE_DELIVERY_ABOVE = float(os.environ.get("FREE_DELIVERY_ABOVE", "50"))
    STORE_TIMEZONE = os.environ.get("STORE_TIMEZONE", "America/Chicago")
    LOW_STOCK_THRESHOLD = int(os.environ.get("LOW_STOCK_THRESHOLD", "15"))

    # Email over HTTPS via Brevo (works on hosts that block SMTP ports, e.g. Render free tier).
    # Takes priority over SMTP when set. Sender must be verified in Brevo → Senders.
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
    # Email (SMTP). With neither Brevo nor MAIL_SERVER, emails go to instance/outbox/ and EmailLogs.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "Shree Mithai Mahal <orders@shreemithaimahal.example>")

    # OTP policy
    OTP_LENGTH = 6
    OTP_TTL_SECONDS = int(os.environ.get("OTP_TTL_SECONDS", "300"))
    OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
    OTP_RESEND_COOLDOWN = int(os.environ.get("OTP_RESEND_COOLDOWN", "30"))
    OTP_MAX_PER_HOUR = int(os.environ.get("OTP_MAX_PER_HOUR", "6"))
    # Show OTP on screen only in local dev without SMTP. Never enable in production.
    SHOW_DEV_OTP = _bool("SHOW_DEV_OTP", False)

    # Login throttling
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW_SECONDS = 900

    # Payments: "simulated" (no keys needed) or "stripe" (test mode keys)
    PAYMENT_GATEWAY = os.environ.get("PAYMENT_GATEWAY", "simulated")
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    ENABLE_COD = _bool("ENABLE_COD", True)

    CANCELLABLE_STATUSES = ("pending", "confirmed", "preparing")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "images", "products", "uploads")
    OUTBOX_DIR = os.path.join(BASE_DIR, "instance", "outbox")
    INVOICE_DIR = os.path.join(BASE_DIR, "instance", "invoices")


class DevelopmentConfig(Config):
    DEBUG = True
    SHOW_DEV_OTP = _bool("SHOW_DEV_OTP", True)


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"
    # Off unless explicitly enabled (e.g. a demo deployment with no SMTP yet).
    SHOW_DEV_OTP = _bool("SHOW_DEV_OTP", False)


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _db_url(os.environ.get("TEST_DATABASE_URL")) or "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True} if os.environ.get("TEST_DATABASE_URL") else {}
    WTF_CSRF_ENABLED = False
    MAIL_SERVER = ""
    PAYMENT_GATEWAY = "simulated"
    SHOW_DEV_OTP = True
    OTP_RESEND_COOLDOWN = 0
    SECRET_KEY = "test-secret"
    OTP_SECRET = "test-otp-secret"


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
