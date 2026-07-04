"""Per-user, role-based login.

Accounts live in the `users` table (see app/db.py). On first boot a starter
Administrator account is seeded from the APP_USERNAME / APP_PASSWORD
environment variables (falling back to admin / changeme) so the app is
usable immediately -- the Administrator can then create real accounts
(including "Information Systems Analyst I" and "User" roles) from the
Users page.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import ALLOWED_REGISTRATION_EMAILS, ROLE_ADMIN, ROLE_ISA, ROLE_USER, get_db

PUBLIC_ENDPOINTS = {"login", "register", "static", "logo_file"}


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped


def roles_required(*allowed_roles):
    """Restrict a view to specific roles (Administrators can always access)."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login", next=request.path))
            role = session.get("role")
            if role != ROLE_ADMIN and role not in allowed_roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def current_user_id() -> int | None:
    return session.get("user_id")


def current_role() -> str | None:
    return session.get("role")


def is_isa_or_admin() -> bool:
    return session.get("role") in (ROLE_ADMIN, ROLE_ISA)


def register_auth(app) -> None:
    @app.before_request
    def _require_login():
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            db = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            if user and user["active"] and check_password_hash(user["password_hash"], password):
                session.clear()
                session["logged_in"] = True
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["full_name"] = user["full_name"]
                session["role"] = user["role"]
                session.permanent = True
                next_url = request.args.get("next") or url_for("dashboard")
                return redirect(next_url)
            error = "Invalid username or password."
        return render_template("login.html", error=error)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        error = None
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().lower()
            full_name = (request.form.get("full_name") or "").strip()
            password = request.form.get("password") or ""
            confirm_password = request.form.get("confirm_password") or ""

            if username not in ALLOWED_REGISTRATION_EMAILS:
                error = (
                    "This email is not authorized to self-register. "
                    "Please contact the administrator."
                )
            else:
                db = get_db()
                existing = db.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
                ).fetchone()
                if existing:
                    error = (
                        "An account for this email already exists. "
                        "Please contact the administrator."
                    )
                elif not full_name:
                    error = "Please enter your full name."
                elif len(password) < 8:
                    error = "Password must be at least 8 characters long."
                elif password != confirm_password:
                    error = "Passwords do not match."
                else:
                    db.execute(
                        """
                        INSERT INTO users (username, password_hash, full_name, role, active)
                        VALUES (?, ?, ?, ?, 1)
                        """,
                        (username, generate_password_hash(password), full_name, ROLE_USER),
                    )
                    db.commit()
                    flash("Account created. You can now sign in.", "success")
                    return redirect(url_for("login"))
        return render_template("register.html", error=error, form=request.form)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
