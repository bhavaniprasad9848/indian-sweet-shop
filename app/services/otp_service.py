"""One-time passwords: generation, hashed storage, expiry, attempt limits and send-rate limits."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from flask import current_app

from ..extensions import db
from ..models import OTPVerification


class OTPError(Exception):
    pass


PURPOSE_TEXT = {
    "register": "verify your new account",
    "login": "sign in to your account",
    "admin_login": "sign in to the admin dashboard",
    "order": "confirm your order",
}


def _hash(code, salt):
    key = current_app.config["OTP_SECRET"].encode()
    return hmac.new(key, f"{salt}:{code}".encode(), hashlib.sha256).hexdigest()


def _latest(email, purpose, reference_id):
    return (OTPVerification.query
            .filter_by(email=email, purpose=purpose, reference_id=reference_id, is_used=False)
            .order_by(OTPVerification.id.desc()).first())


def issue_otp(email, purpose, reference_id=None, ip=None, context=None):
    """Create and email a fresh OTP. Returns the plain code (for dev display/tests only)."""
    cfg = current_app.config
    now = datetime.utcnow()
    email = email.lower()

    last = (OTPVerification.query.filter_by(email=email, purpose=purpose, reference_id=reference_id)
            .order_by(OTPVerification.id.desc()).first())
    if last and cfg["OTP_RESEND_COOLDOWN"] and (now - last.created_at).total_seconds() < cfg["OTP_RESEND_COOLDOWN"]:
        wait = int(cfg["OTP_RESEND_COOLDOWN"] - (now - last.created_at).total_seconds()) + 1
        raise OTPError(f"Please wait {wait} seconds before requesting another code.")

    sent_last_hour = OTPVerification.query.filter(
        OTPVerification.email == email, OTPVerification.purpose == purpose,
        OTPVerification.created_at >= now - timedelta(hours=1)).count()
    if sent_last_hour >= cfg["OTP_MAX_PER_HOUR"]:
        raise OTPError("Too many codes requested. Please try again in an hour.")

    # Invalidate earlier unused codes for the same flow
    OTPVerification.query.filter_by(email=email, purpose=purpose, reference_id=reference_id,
                                    is_used=False).update({"is_used": True})

    code = "".join(secrets.choice("0123456789") for _ in range(cfg["OTP_LENGTH"]))
    salt = secrets.token_hex(16)
    rec = OTPVerification(email=email, purpose=purpose, reference_id=reference_id, salt=salt,
                          otp_hash=_hash(code, salt), expires_at=now + timedelta(seconds=cfg["OTP_TTL_SECONDS"]),
                          max_attempts=cfg["OTP_MAX_ATTEMPTS"], ip_address=ip)
    db.session.add(rec)
    db.session.commit()

    from .email_service import send_otp_email
    send_otp_email(email, code, PURPOSE_TEXT.get(purpose, "continue"),
                   cfg["OTP_TTL_SECONDS"] // 60, context=context)
    return code


def verify_otp(email, purpose, code, reference_id=None):
    """Return (ok, message)."""
    rec = _latest(email.lower(), purpose, reference_id)
    if not rec:
        return False, "No active code found. Please request a new one."
    if rec.expires_at < datetime.utcnow():
        rec.is_used = True
        db.session.commit()
        return False, "This code has expired. Please request a new one."
    if rec.attempts >= rec.max_attempts:
        rec.is_used = True
        db.session.commit()
        return False, "Too many incorrect attempts. Please request a new code."

    code = (code or "").strip()
    if not code.isdigit() or not hmac.compare_digest(rec.otp_hash, _hash(code, rec.salt)):
        rec.attempts += 1
        remaining = rec.max_attempts - rec.attempts
        if remaining <= 0:
            rec.is_used = True
        db.session.commit()
        return False, (f"Incorrect code. {remaining} attempt(s) left." if remaining > 0
                       else "Too many incorrect attempts. Please request a new code.")

    rec.is_used = True
    rec.verified_at = datetime.utcnow()
    db.session.commit()
    return True, "Verified."


def seconds_until_resend(email, purpose, reference_id=None):
    last = (OTPVerification.query.filter_by(email=email.lower(), purpose=purpose, reference_id=reference_id)
            .order_by(OTPVerification.id.desc()).first())
    if not last:
        return 0
    left = current_app.config["OTP_RESEND_COOLDOWN"] - (datetime.utcnow() - last.created_at).total_seconds()
    return max(0, int(left))
