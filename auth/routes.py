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


@auth_bp.after_app_request
def _no_store_auth_pages(response):
    """Never cache login/register/logout pages (CDN-cached CSRF tokens break forms)."""
    if request.endpoint in {"auth.login", "auth.register", "auth.logout"}:
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Vary"] = "Cookie"
    return response


def _safe_next_url(value: str | None, external_url: str) -> str | None:
    """Allow relative paths, plus absolute HTTPS URLs on the external tool origin.

    `external_url` comes from AI_IMAGE_EXTERNAL_URL (e.g. the Gallery Web), so
    login/logout initiated from Gallery can return to the original page without
    enabling open redirects to arbitrary hosts. Control characters, whitespace
    and backslashes are rejected because they can smuggle header or URL
    variants; absolute URLs carrying userinfo are rejected as well.
    """
    if not value:
        return None
    if any(char.isspace() or char == "\\" for char in value):
        return None
    if value.startswith("/") and not value.startswith("//"):
        return value
    external = urlparse(external_url)
    if not external.hostname or external.scheme not in {"http", "https"}:
        return None
    try:
        candidate = urlparse(value)
    except ValueError:
        return None
    loopback_http = (
        external.scheme == "http"
        and external.hostname in {"127.0.0.1", "localhost", "::1"}
        and candidate.scheme == "http"
    )
    if (
        (candidate.scheme == "https" or loopback_http)
        and candidate.hostname == external.hostname
        and (candidate.port or (443 if candidate.scheme == "https" else 80))
        == (external.port or (443 if external.scheme == "https" else 80))
        and candidate.username is None
        and candidate.password is None
    ):
        return value
    return None


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    next_url = _safe_next_url(request.args.get("next"), current_app.config.get("AI_IMAGE_EXTERNAL_URL", ""))
    if current_user.is_authenticated:
        return redirect(next_url or url_for("home"))

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing = db.session.query(User).filter_by(email=email).one_or_none()
        if existing is not None:
            flash("该邮箱已注册，请直接登录。", "warning")
            return redirect(url_for("auth.login", **({"next": next_url} if next_url else {})))

        user = User(email=email, is_admin=False, is_active_user=True)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        flash("注册成功，欢迎！", "success")
        return redirect(next_url or "/")

    return render_template("register.html", form=form, next_url=next_url)


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
            return render_template("login.html", form=form, next_url=next_url), 401
        if not user.is_active_user:
            flash("账号已被禁用，请联系管理员。", "danger")
            return render_template("login.html", form=form, next_url=next_url), 403

        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user, remember=form.remember.data)
        flash(f"欢迎回来，{user.email}", "success")

        return redirect(next_url or "/")

    return render_template("login.html", form=form, next_url=next_url)


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
        payload = {
            "role": "admin" if bool(getattr(current_user, "is_admin", False)) else "user",
            "userId": int(current_user.get_id()),
        }
        email = str(getattr(current_user, "email", "") or "")
        if email:
            payload["email"] = email
        nickname = str(getattr(current_user, "nickname", "") or "").strip()
        if nickname:
            payload["nickname"] = nickname
        response = jsonify(payload)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"
    return response


@auth_bp.get("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user)


@auth_bp.post("/profile")
@login_required
def profile_update():
    nickname = request.form.get("nickname", "").strip()
    if len(nickname) > 80:
        flash("昵称最多 80 个字符。", "danger")
        return redirect(url_for("auth.profile"))
    current_user.nickname = nickname or None
    db.session.commit()
    _sync_gallery_display_name(current_user.id, current_user.display_name)
    flash("昵称已更新。", "success")
    return redirect(url_for("auth.profile"))


def _sync_gallery_display_name(user_id: int, display_name: str) -> None:
    """Mirror the nickname into ai.user_profiles for artwork attribution."""
    from sqlalchemy import text  # noqa: PLC0415

    try:
        db.session.execute(
            text(
                "INSERT INTO ai.user_profiles (user_id, display_name, created_at, updated_at) "
                "VALUES (:user_id, :display_name, now(), now()) "
                "ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name, updated_at = now()"
            ),
            {"user_id": user_id, "display_name": display_name},
        )
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.warning("ai.user_profiles sync skipped: %s", exc)
