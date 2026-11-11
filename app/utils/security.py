"""Role-based access control and simple in-process rate limiting."""
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, flash, redirect, request, url_for
from flask_login import current_user


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.admin_login", next=request.path))
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def customer_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if getattr(current_user, "is_admin", False):
            flash("Admins can't place customer orders. Sign in with a customer account.", "warning")
            return redirect(url_for("admin.dashboard"))
        return view(*args, **kwargs)
    return wrapper


class SlidingWindowLimiter:
    """Thread-safe sliding-window counter keyed by arbitrary strings.

    In-process only; use Redis-backed limiting when running multiple workers.
    """

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key, limit, window):
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)


login_limiter = SlidingWindowLimiter()


def client_ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "") or "").split(",")[0].strip()


def check_login_rate(email):
    cfg = current_app.config
    return login_limiter.hit(f"{client_ip()}|{email}", cfg["LOGIN_MAX_ATTEMPTS"], cfg["LOGIN_WINDOW_SECONDS"])


def is_safe_next(target):
    return bool(target) and target.startswith("/") and not target.startswith("//")
