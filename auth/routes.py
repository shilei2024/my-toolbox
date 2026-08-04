"""Auth routes: register, login, logout."""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models import User
from .forms import LoginForm, RegisterForm

auth_bp = Blueprint("auth", __name__, template_folder="../templates")


def _safe_next_url(value: str | None, external_url: str) -> str | None:
    """Allow relative paths, plus absolute HTTPS URLs on the external tool origin.

    `external_url` comes from AI_IMAGE_EXTERNAL_URL (e.g. the Gallery Web), so
    login/logout initiated from Gallery can return to the original page without
    enabling open redirects to arbitrary hosts.
    """
    if not value:
        return None
    if value.startswith("/") and not value.startswith("//"):
        return value
    external = urlparse(external_url)
    if external.scheme != "https" or not external.hostname:
        return None
    try:
        candidate = urlparse(value)
    except ValueError:
        return None
    if (
        candidate.scheme == "https"
        and candidate.hostname == external.hostname
        and (candidate.port or 443) == (external.port or 443)
    ):
        return value
    return None


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing = db.session.query(User).filter_by(email=email).one_or_none()
        if existing is not None:
            flash("该邮箱已注册，请直接登录。", "warning")
            return redirect(url_for("auth.login"))

        user = User(email=email, is_admin=False, is_active_user=True)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        flash("注册成功，欢迎！", "success")
        next_url = request.args.get("next") or "/"
        return redirect(next_url)

    return render_template("register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = _safe_next_url(request.args.get("next"), current_app.config.get("AI_IMAGE_EXTERNAL_URL", ""))
    if current_user.is_authenticated:
        return redirect(next_url or url_for("home"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.query(User).filter_by(email=email).one_or_none()
        if user is None or not user.check_password(form.password.data):
            flash("邮箱或密码错误。", "danger")
            return render_template("login.html", form=form), 401
        if not user.is_active_user:
            flash("账号已被禁用，请联系管理员。", "danger")
            return render_template("login.html", form=form), 403

        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user, remember=form.remember.data)
        flash(f"欢迎回来，{user.email}", "success")

        return redirect(next_url or "/")

    return render_template("login.html", form=form)


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    next_url = _safe_next_url(request.args.get("next"), current_app.config.get("AI_IMAGE_EXTERNAL_URL", ""))
    logout_user()
    flash("已退出登录。", "info")
    return redirect(next_url or url_for("home"))


@auth_bp.get("/internal/gallery/session")
@auth_bp.get("/auth/internal/gallery/session")
def gallery_session():
    """Return only the identity fields required by the Gallery BFF.

    The Next.js server forwards the existing Flask session cookie and proves
    its own identity with a separate shared secret. Browser-supplied user IDs
    are never trusted.

    `/auth/internal/gallery/session` is kept as a compatibility alias: earlier
    deployment guides used that path, so both must resolve to this endpoint.
    """
    expected = str(current_app.config.get("GALLERY_INTROSPECTION_SECRET", ""))
    supplied = request.headers.get("X-Mavis-Introspection-Secret", "")
    if len(expected.encode("utf-8")) < 32 or not hmac.compare_digest(expected, supplied):
        response = jsonify(error={"code": "not_found", "message": "Not found"})
        response.status_code = 404
        response.headers["Cache-Control"] = "no-store"
        return response

    if not current_user.is_authenticated:
        response = jsonify(role="guest")
    else:
        response = jsonify(
            role="admin" if bool(getattr(current_user, "is_admin", False)) else "user",
            userId=int(current_user.get_id()),
        )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"
    return response
