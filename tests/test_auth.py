from datetime import datetime, timedelta

from app.extensions import db
from app.models import OTPVerification, User
from conftest import last_otp, login_admin, login_customer


def test_register_requires_email_otp(client):
    r = client.post("/register", data={"name": "Asha Rao", "email": "asha@example.com", "phone": "+1 908 555 1212",
                                       "password": "Sweets123", "confirm_password": "Sweets123"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/verify")
    user = User.query.filter_by(email="asha@example.com").first()
    assert user and not user.is_verified
    assert user.password_hash != "Sweets123"  # hashed

    r = client.post("/verify", data={"code": "000000"})
    assert b"Incorrect code" in r.data
    r = client.post("/verify", data={"code": last_otp("asha@example.com")})
    assert r.status_code == 302
    assert db.session.get(User, user.id).is_verified
    assert client.get("/account/").status_code == 200


def test_register_validation(client):
    r = client.post("/register", data={"name": "A", "email": "bad", "phone": "x", "password": "short",
                                       "confirm_password": "nope"}, follow_redirects=True)
    assert b"valid email" in r.data and b"at least 8 characters" in r.data
    assert User.query.filter_by(email="bad").first() is None


def test_customer_login_two_step(client):
    r = client.post("/login", data={"email": "priya@example.com", "password": "wrong"})
    assert b"Incorrect email or password" in r.data
    login_customer(client)
    assert client.get("/account/orders").status_code == 200


def test_login_rate_limited(client):
    for _ in range(5):
        client.post("/login", data={"email": "priya@example.com", "password": "nope"})
    r = client.post("/login", data={"email": "priya@example.com", "password": "Customer@123"})
    assert r.status_code == 429


def test_otp_stored_hashed_with_attempt_limit(client, app):
    client.post("/login", data={"email": "priya@example.com", "password": "Customer@123"})
    code = last_otp("priya@example.com")
    rec = OTPVerification.query.order_by(OTPVerification.id.desc()).first()
    assert code not in rec.otp_hash and len(rec.otp_hash) == 64
    for _ in range(app.config["OTP_MAX_ATTEMPTS"]):
        client.post("/verify", data={"code": "999999" if code != "999999" else "111111"})
    r = client.post("/verify", data={"code": code})  # correct code after lockout is refused
    assert b"request a new" in r.data
    assert client.get("/account/").status_code == 302


def test_otp_expires(client):
    client.post("/login", data={"email": "priya@example.com", "password": "Customer@123"})
    code = last_otp("priya@example.com")
    rec = OTPVerification.query.order_by(OTPVerification.id.desc()).first()
    rec.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    r = client.post("/verify", data={"code": code})
    assert b"expired" in r.data


def test_otp_send_rate_limit(client, app):
    client.post("/login", data={"email": "priya@example.com", "password": "Customer@123"})
    for _ in range(app.config["OTP_MAX_PER_HOUR"]):
        client.post("/verify/resend")
    r = client.post("/verify/resend", follow_redirects=True)
    assert b"Too many codes" in r.data


def test_admin_portal_requires_otp_and_role(client):
    assert client.get("/admin/").status_code == 302  # anonymous → admin login
    login_customer(client)
    assert client.get("/admin/").status_code == 403  # customers forbidden
    client.post("/logout")
    login_admin(client)
    assert client.get("/admin/").status_code == 200


def test_customer_password_does_not_open_admin_portal(client):
    r = client.post("/admin/login", data={"email": "priya@example.com", "password": "Customer@123"})
    assert b"Incorrect email or password" in r.data
