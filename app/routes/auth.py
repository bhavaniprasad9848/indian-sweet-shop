"""Two login portals (customer + admin), registration, and OTP second step."""
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from ..extensions import db
from ..models import Admin, User
from ..services.otp_service import OTPError, issue_otp, seconds_until_resend, verify_otp
from ..utils.helpers import mask_email
from ..utils.security import check_login_rate, client_ip, is_safe_next, login_limiter
from ..utils.validators import clean, validate_email, validate_name, validate_password, validate_phone

bp = Blueprint("auth", __name__)

PENDING_KEY = "pending_auth"


def _dev_otp(code):
    if current_app.config["SHOW_DEV_OTP"] and not current_app.config["MAIL_SERVER"]:
        flash(f"Dev mode (SMTP not configured): your code is {code}", "dev")


def _start_otp(purpose, email, ref_id, next_url=None):
    try:
        code = issue_otp(email, purpose, ref_id, ip=client_ip())
    except OTPError as e:
        flash(str(e), "danger")
        return False
    session[PENDING_KEY] = {"purpose": purpose, "email": email, "ref": ref_id, "next": next_url,
                            "started": datetime.utcnow().isoformat()}
    _dev_otp(code)
    return True


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    form = {}
    if request.method == "POST":
        form = {k: clean(request.form.get(k), 255) for k in ("name", "email", "phone")}
        form["email"] = form["email"].lower()
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm_password", "")
        errors = [e for e in (validate_name(form["name"]), validate_email(form["email"]),
                              validate_phone(form["phone"]), validate_password(pw)) if e]
        if pw != pw2:
            errors.append("Passwords don't match.")
        existing = User.query.filter_by(email=form["email"]).first()
        if existing and existing.is_verified:
            errors.append("An account with this email already exists. Please sign in.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            user = existing or User(email=form["email"])
            user.name, user.phone, user.is_verified = form["name"], form["phone"], False
            user.set_password(pw)
            db.session.add(user)
            db.session.commit()
            if _start_otp("register", user.email, user.id):
                flash(f"We sent a 6-digit code to {mask_email(user.email)}.", "info")
                return redirect(url_for("auth.verify"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated and not current_user.is_admin:
        return redirect(url_for("main.home"))
    email = ""
    if request.method == "POST":
        email = clean(request.form.get("email"), 255).lower()
        pw = request.form.get("password", "")
        next_url = request.args.get("next") or request.form.get("next")
        if not check_login_rate(email):
            flash("Too many sign-in attempts. Please wait 15 minutes and try again.", "danger")
            return render_template("auth/login.html", email=email), 429
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(pw) or not user.is_active_account:
            flash("Incorrect email or password.", "danger")
        else:
            purpose = "login" if user.is_verified else "register"
            if _start_otp(purpose, user.email, user.id, next_url if is_safe_next(next_url) else None):
                flash(f"Enter the code we sent to {mask_email(user.email)} to finish signing in.", "info")
                return redirect(url_for("auth.verify"))
    return render_template("auth/login.html", email=email)


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for("admin.dashboard"))
    email = ""
    if request.method == "POST":
        email = clean(request.form.get("email"), 255).lower()
        pw = request.form.get("password", "")
        if not check_login_rate("admin|" + email):
            flash("Too many sign-in attempts. Please wait 15 minutes and try again.", "danger")
            return render_template("auth/admin_login.html", email=email), 429
        admin = Admin.query.filter_by(email=email).first()
        if not admin or not admin.check_password(pw) or not admin.is_active_account:
            flash("Incorrect email or password.", "danger")
        else:
            nxt = request.args.get("next")
            if _start_otp("admin_login", admin.email, admin.id, nxt if is_safe_next(nxt) else None):
                flash(f"Enter the admin code sent to {mask_email(admin.email)}.", "info")
                return redirect(url_for("auth.verify"))
    return render_template("auth/admin_login.html", email=email)


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    pending = session.get(PENDING_KEY)
    if not pending:
        flash("Please sign in first.", "warning")
        return redirect(url_for("auth.login"))
    is_admin = pending["purpose"] == "admin_login"
    if request.method == "POST":
        code = "".join(request.form.getlist("otp")) or request.form.get("code", "")
        ok, msg = verify_otp(pending["email"], pending["purpose"], code, pending["ref"])
        if not ok:
            flash(msg, "danger")
        else:
            model = Admin if is_admin else User
            account = db.session.get(model, pending["ref"])
            if account is None:
                return redirect(url_for("auth.login"))
            if pending["purpose"] == "register":
                account.is_verified = True
            account.last_login_at = datetime.utcnow()
            db.session.commit()
            next_url = pending.get("next")
            session.clear()  # new session on privilege change (prevents fixation)
            session.permanent = True
            login_user(account, remember=False)
            login_limiter.reset(f"{client_ip()}|{('admin|' if is_admin else '') + account.email}")
            flash(f"Welcome{' back' if pending['purpose'] != 'register' else ''}, {account.name.split()[0]}!", "success")
            if is_admin:
                return redirect(next_url or url_for("admin.dashboard"))
            return redirect(next_url or url_for("main.home"))
    return render_template("auth/verify.html", email=mask_email(pending["email"]), purpose=pending["purpose"],
                           wait=seconds_until_resend(pending["email"], pending["purpose"], pending["ref"]),
                           resend_url=url_for("auth.resend"), is_admin=is_admin)


@bp.route("/verify/resend", methods=["POST"])
def resend():
    pending = session.get(PENDING_KEY)
    if not pending:
        return redirect(url_for("auth.login"))
    try:
        code = issue_otp(pending["email"], pending["purpose"], pending["ref"], ip=client_ip())
        _dev_otp(code)
        flash("A new code is on its way.", "info")
    except OTPError as e:
        flash(str(e), "warning")
    return redirect(url_for("auth.verify"))


@bp.route("/logout", methods=["POST"])
def logout():
    was_admin = current_user.is_authenticated and current_user.is_admin
    logout_user()
    session.clear()
    flash("You've been signed out.", "info")
    return redirect(url_for("auth.admin_login" if was_admin else "main.home"))
