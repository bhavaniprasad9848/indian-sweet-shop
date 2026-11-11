def register_blueprints(app):
    from .main import bp as main_bp
    from .auth import bp as auth_bp
    from .cart import bp as cart_bp
    from .checkout import bp as checkout_bp
    from .account import bp as account_bp
    from .admin import bp as admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(cart_bp, url_prefix="/cart")
    app.register_blueprint(checkout_bp, url_prefix="/checkout")
    app.register_blueprint(account_bp, url_prefix="/account")
    app.register_blueprint(admin_bp, url_prefix="/admin")
