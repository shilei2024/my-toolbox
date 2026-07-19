"""Auth routes: register, login, logout."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models import User
from .forms import LoginForm, RegisterForm

auth_bp = Blueprint("auth", __name__, template_folder="../templates")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

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
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

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

        next_url = request.args.get("next")
        # avoid open-redirect: only allow relative paths
        if next_url and not next_url.startswith("/"):
            next_url = None
        return redirect(next_url or "/")

    return render_template("login.html", form=form)


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    flash("已退出登录。", "info")
    return redirect(url_for("main.index"))
