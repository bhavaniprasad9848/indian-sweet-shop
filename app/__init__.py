"""Application factory."""
import os
from datetime import datetime

import click
from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError

from config import config_by_name
from .extensions import db, login_manager, csrf, migrate


def create_app(config_name=None, overrides=None):
    config_name = config_name or os.environ.get("FLASK_CONFIG", "development")
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_by_name[config_name])
    if overrides:
        app.config.update(overrides)

    for folder in (app.config["OUTBOX_DIR"], app.config["INVOICE_DIR"], app.config["UPLOAD_FOLDER"]):
        os.makedirs(folder, exist_ok=True)
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"):
        os.makedirs(os.path.dirname(app.config["SQLALCHEMY_DATABASE_URI"][10:]), exist_ok=True)

    if config_name == "production" and app.config["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError("Set SECRET_KEY in the environment before running in production.")

    if config_name == "production":
        # Behind Render/Heroku-style proxies: trust X-Forwarded-* so HTTPS URLs and client IPs are correct
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "warning"
    login_manager.session_protection = "strong"

    from .models import User, Admin

    @login_manager.user_loader
    def load_user(user_id):
        try:
            kind, raw_id = user_id.split(":", 1)
            model = Admin if kind == "a" else User
            return db.session.get(model, int(raw_id))
        except (ValueError, TypeError):
            return None

    from .routes import register_blueprints
    register_blueprints(app)

    _register_template_helpers(app)
    _register_error_handlers(app)
    _register_cli(app)
    return app


def _register_template_helpers(app):
    from .models import STATUS_LABELS
    from .services.cart_service import cart_count

    @app.template_filter("money")
    def money_filter(value):
        try:
            return f"{app.config['CURRENCY_SYMBOL']}{float(value or 0):,.2f}"
        except (TypeError, ValueError):
            return value

    from datetime import date as _date, timezone as _tz
    from zoneinfo import ZoneInfo

    def _local(value):
        # DB timestamps are naive UTC; show them in the store's time zone
        if isinstance(value, datetime):
            return value.replace(tzinfo=_tz.utc).astimezone(ZoneInfo(app.config["STORE_TIMEZONE"]))
        return value

    @app.template_filter("dt")
    def dt_filter(value, fmt="%d %b %Y, %I:%M %p"):
        return _local(value).strftime(fmt) if value else "—"

    @app.template_filter("d")
    def d_filter(value, fmt="%d %b %Y"):
        return _local(value).strftime(fmt) if value else "—"

    @app.context_processor
    def inject_globals():
        count = 0
        if current_user and current_user.is_authenticated and not getattr(current_user, "is_admin", False):
            count = cart_count(current_user)
        return {
            "store": {
                "name": app.config["STORE_NAME"], "tagline": app.config["STORE_TAGLINE"],
                "address": app.config["STORE_ADDRESS"], "phone": app.config["STORE_PHONE"],
                "email": app.config["STORE_EMAIL"], "support": app.config["SUPPORT_EMAIL"],
                "gstin": app.config["STORE_GSTIN"],
            },
            "cart_count": count,
            "status_labels": STATUS_LABELS,
            "now": datetime.utcnow(),
            "currency_symbol": app.config["CURRENCY_SYMBOL"],
        }


def _register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/error.html", code=403, title="Access denied",
                               message="You don't have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/error.html", code=404, title="Page not found",
                               message="This sweet seems to have been eaten already."), 404

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        # A duplicate submit right after signing in carries the pre-login token; the user is already in.
        if current_user and current_user.is_authenticated and request.endpoint in ("auth.verify", "auth.login", "auth.admin_login"):
            return redirect(url_for("admin.dashboard" if current_user.is_admin else "main.home"))
        return render_template("errors/error.html", code=400, title="Session expired",
                               message="Your form session expired. Please go back and try again."), 400

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/error.html", code=500, title="Something went wrong",
                               message="Our kitchen hit a snag. Please try again in a moment."), 500


def _register_cli(app):
    @app.cli.command("init-db")
    @click.option("--drop", is_flag=True, help="Drop all tables first.")
    def init_db(drop):
        """Create all database tables."""
        if drop:
            db.drop_all()
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("seed")
    @click.option("--history-days", default=420, help="Days of historical orders to generate.")
    def seed(history_days):
        """Load sample categories, products, batches, users and order history."""
        from .seed import seed_all
        seed_all(history_days=history_days, echo=click.echo)

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.password_option()
    def create_admin(email, name, password):
        """Create an admin account."""
        from .models import Admin
        from .utils.validators import validate_password
        err = validate_password(password)
        if err:
            raise click.ClickException(err)
        if Admin.query.filter_by(email=email.lower()).first():
            raise click.ClickException("Admin already exists.")
        a = Admin(email=email.lower(), name=name)
        a.set_password(password)
        db.session.add(a)
        db.session.commit()
        click.echo(f"Admin {email} created.")
