import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import EmailLog, User  # noqa: E402
from app.seed import seed_all  # noqa: E402
from app.utils.security import login_limiter  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    app = create_app("testing", overrides={
        "OUTBOX_DIR": str(tmp_path / "outbox"), "INVOICE_DIR": str(tmp_path / "invoices"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
    })
    for k in ("OUTBOX_DIR", "INVOICE_DIR", "UPLOAD_FOLDER"):
        os.makedirs(app.config[k], exist_ok=True)
    with app.app_context():
        db.create_all()
        seed_all(history_days=0, echo=lambda *a: None, extra_customers=2)
        login_limiter._hits.clear()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def last_otp(email):
    log = (EmailLog.query.filter_by(recipient=email.lower(), category="otp")
           .order_by(EmailLog.id.desc()).first())
    assert log, f"no OTP email for {email}"
    return re.search(r">(\d{6})<", log.html_body).group(1)


def login_customer(client, email="priya@example.com", password="Customer@123"):
    r = client.post("/login", data={"email": email, "password": password})
    assert r.status_code == 302 and "/verify" in r.headers["Location"]
    r = client.post("/verify", data={"code": last_otp(email)})
    assert r.status_code == 302
    return r


def login_admin(client, email="admin@sweetshop.local", password="Admin@12345"):
    r = client.post("/admin/login", data={"email": email, "password": password})
    assert r.status_code == 302
    r = client.post("/verify", data={"code": last_otp(email)})
    assert r.status_code == 302 and "/admin" in r.headers["Location"]
    return r


def demo_user():
    return User.query.filter_by(email="priya@example.com").first()
