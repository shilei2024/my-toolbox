"""Website account security and email flows, always Cookie + CSRF."""
import hashlib
import re
import secrets
from flask import Blueprint, current_app, flash, make_response, redirect, render_template, request, session, url_for
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
    # HTTPS CSRF protection requires a same-origin Referer on form POSTs.
    # Cross-origin requests still receive no referrer; tokens use fragments.
    response.headers["Referrer-Policy"] = "same-origin"
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
            elif email:
                from .registration_service import request_registration
                request_registration(email, create=False)
                db.session.commit()
            message = "若该邮箱符合条件，将收到找回或注册验证邮件，请查收并按邮件提示继续。"
    return render_template("account_recover.html", message=message)


@security_bp.route("/account/email/<purpose>", methods=["GET", "POST"])
@limiter.limit("10/minute", methods=["POST"])
def email_action(purpose):
    if purpose not in {"verify", "reset", "register", "register-confirm"}:
        return "页面不存在", 404
    message = ""
    if request.method == "POST":
        password = request.form.get("password")
        if purpose in {"reset", "register"} and password != request.form.get("confirm"):
            message = "两次密码输入不一致，请重新打开邮件链接。"
        elif purpose in {"register", "register-confirm"}:
            from .registration_service import complete
            result = complete(request.form.get("token"), password if purpose == 'register' else None)
            if result:
                from .routes import _safe_next_url
                target = _safe_next_url(result[1], current_app.config.get("AI_IMAGE_EXTERNAL_URL", ""))
                session.pop("registration_email", None)
                session["registration_complete"] = {"next":target}
                return redirect(url_for("account_security.registration_complete"))
            message = ("链接无效、已过期或已使用，请重新申请验证邮件。" if purpose == 'register-confirm'
                else "链接无效或已过期，或密码不符合8–128位且包含字母和数字的要求。请检查密码或重新申请邮件。")
        elif mail.consume(request.form.get("token"), purpose, password):
            if purpose == "reset":
                logout_user()
            flash("邮箱已验证。" if purpose == "verify" else "密码已重置，请重新登录。", "success")
            return redirect(url_for("auth.login"))
        else:
            message = "链接无效或已过期，或密码不符合8–128位要求。请重新申请。"
    nonce = secrets.token_urlsafe(24)
    raw = request.form.get("token", "") if request.method == "POST" else ""
    form_token = raw if re.fullmatch(r"[A-Za-z0-9_-]{43}", raw) else ""
    response = make_response(render_template("account_email_action.html", purpose=purpose, nonce=nonce,
        message=message, form_token=form_token))
    response.headers["Content-Security-Policy"] = f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    return response


@security_bp.get("/account/registration/complete")
def registration_complete():
    result = session.get("registration_complete")
    if not isinstance(result, dict):
        return redirect(url_for("auth.register"))
    return render_template("account_registration_complete.html", next_url=result.get("next"))


@security_bp.route("/account/registration/pending", methods=["GET", "POST"])
@limiter.limit("5/minute", methods=["POST"])
@limiter.limit("5/hour", key_func=email_limit_key, methods=["POST"])
def registration_pending():
    from .forms import RegistrationEmailForm
    from .registration_service import request_registration
    form = RegistrationEmailForm()
    message = ""
    if form.validate_on_submit():
        if mail.ready():
            email = form.email.data.strip().lower()
            request_registration(email, create=False)
            db.session.commit()
            session["registration_email"] = email
            message = "若该邮箱有待完成的注册，将收到验证邮件。请稍后查收，重复申请需间隔一分钟。"
        else:
            message = "注册邮件服务暂不可用，请稍后重试。"
    elif request.method == "GET":
        form.email.data = session.get("registration_email", "")
    return render_template("account_registration_pending.html", form=form, message=message)


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
