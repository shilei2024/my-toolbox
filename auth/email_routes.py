"""Website account security and email flows, always Cookie + CSRF."""
import hashlib
import secrets
from flask import Blueprint, current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from extensions import db, limiter
from models import User
from . import account_service as accounts, email_service as mail

security_bp = Blueprint("account_security", __name__)


def email_limit_key():
    value = accounts.normalized_email(request.form.get("email")) or "invalid"
    return "auth-email:"+hashlib.sha256(value.encode()).hexdigest()


@security_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@security_bp.route("/account/recover", methods=["GET", "POST"])
@limiter.limit("5/minute", methods=["POST"])
@limiter.limit("5/hour", key_func=email_limit_key, methods=["POST"])
def recover():
    message = ""
    if request.method == "POST":
        if not mail.ready():
            message = "邮件找回暂不可用，请联系管理员。"
        else:
            email = accounts.normalized_email(request.form.get("email"))
            user = User.query.filter_by(email=email).first() if email else None
            if user:
                mail.enqueue(user.id, "reset", email)
                db.session.commit()
            message = "若该邮箱已验证且符合找回条件，将收到重置邮件。"
    return render_template("account_recover.html", message=message)


@security_bp.route("/account/email/<purpose>", methods=["GET", "POST"])
@limiter.limit("10/minute", methods=["POST"])
def email_action(purpose):
    if purpose not in {"verify", "reset"}:
        return "页面不存在", 404
    message = ""
    if request.method == "POST":
        password = request.form.get("password")
        if purpose == "reset" and password != request.form.get("confirm"):
            message = "两次密码输入不一致，请重新打开邮件链接。"
        elif mail.consume(request.form.get("token"), purpose, password):
            if purpose == "reset":
                logout_user()
            flash("邮箱已验证。" if purpose == "verify" else "密码已重置，请重新登录。", "success")
            return redirect(url_for("auth.login"))
        else:
            message = "链接无效或已过期，或密码不符合8–128位要求。请重新申请。"
    nonce = secrets.token_urlsafe(24)
    response = make_response(render_template("account_email_action.html", purpose=purpose, nonce=nonce, message=message))
    response.headers["Content-Security-Policy"] = f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    return response


@security_bp.route("/account/security", methods=["GET", "POST"])
@login_required
@limiter.limit("5/minute", methods=["POST"])
def security():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "verify":
            if not mail.ready():
                flash("邮件服务暂不可用，请联系管理员。", "warning")
            else:
                mail.enqueue(current_user.id, "verify", current_user.email)
                db.session.commit()
                flash("验证邮件已加入发送队列，请稍后查收。", "info")
        elif action in {"password", "logout_all"}:
            user = accounts.authenticate_password(current_user.email, request.form.get("current_password"), channel="web_reauth")
            if not user or user.id != current_user.id:
                db.session.commit()
                flash("当前密码不正确或账号不可用。", "warning")
            elif action == "password":
                password = request.form.get("password")
                if password != request.form.get("confirm") or not accounts.change_password(user.id, password, expected_hash=user.password_hash):
                    db.session.rollback()
                    flash("新密码需8–128位且两次输入相同。", "warning")
                else:
                    db.session.commit()
                    logout_user()
                    return redirect(url_for("auth.login"))
            else:
                accounts.revoke_all(user, reason="sessions.revoked_all", channel="web")
                db.session.commit()
                logout_user()
                return redirect(url_for("auth.login"))
        return redirect(url_for("account_security.security"))
    return render_template("account_security.html", user=current_user)
