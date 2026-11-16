"""Purpose-bound email credentials. Raw tokens exist only in mail process memory."""
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from flask import current_app
from sqlalchemy import or_, update
from extensions import db
from models import User, utcnow
from shared.mail import send_smtp, valid_address, MailError
from .account_models import ActionToken, AuthMailJob
from .account_service import lock_account, audit, mirror_password, change_password
from .session_service import digest


def smtp_credentials():
    username = current_app.config.get("AUTH_MAIL_SMTP_USERNAME", "")
    password = current_app.config.get("AUTH_MAIL_SMTP_PASSWORD", "")
    # Override as a pair; never combine a dedicated username with the old password.
    return (username, password) if username or password else None


def ready():
    adapter = current_app.config.get("AUTH_MAIL_ADAPTER", "disabled")
    if adapter == "capture":
        return bool(current_app.testing)
    if adapter != "smtp":
        return False
    try:
        base = urlsplit(current_app.config.get("APP_BASE_URL", ""))
        credentials = smtp_credentials()
        username, password = credentials if credentials is not None else (
            current_app.config.get("SMTP_USERNAME"), current_app.config.get("SMTP_PASSWORD"))
        return bool(base.scheme == "https" and base.hostname and not base.username and not base.password
            and not base.query and not base.fragment and base.path in ("", "/")
            and current_app.config.get("SMTP_HOST")
            and valid_address(current_app.config.get("AUTH_MAIL_FROM") or current_app.config.get("SMTP_FROM"))
            and current_app.config.get("SMTP_SECURITY") in {"ssl", "starttls"}
            and bool(username) == bool(password)
            and (credentials is None or bool(current_app.config.get("AUTH_MAIL_FROM")))
            and 1 <= int(current_app.config.get("SMTP_PORT", 0)) <= 65535
            and 1 <= int(current_app.config.get("SMTP_TIMEOUT_SECONDS", 0)) <= 120)
    except (ValueError, TypeError):
        return False


def enqueue(user_id, purpose, email):
    """Caller commits. Account lock serializes duplicate requests and mutations."""
    if purpose not in {"verify", "reset"} or not ready():
        return False
    user = lock_account(user_id)
    if (not user or not user.is_active_user or user.email != email
            or (purpose == "reset" and not user.email_verified_at)):
        return False
    pending = AuthMailJob.query.filter_by(user_id=user.id, purpose=purpose, target_email=email,
        auth_epoch=user.auth_epoch).filter(AuthMailJob.status.in_(["pending", "processing"])).first()
    if pending:
        return True
    db.session.add(AuthMailJob(user_id=user.id, purpose=purpose, target_email=email, auth_epoch=user.auth_epoch))
    audit(user.id, "email.queued", "web")
    return True


def dispatch(limit=20):
    if not ready():
        raise MailError("AUTH_MAIL_NOT_READY")
    now = utcnow()
    AuthMailJob.query.filter(AuthMailJob.status == "processing", AuthMailJob.attempts >= 3,
        AuthMailJob.updated_at < now-timedelta(minutes=5)).update({"status":"failed"})
    db.session.commit()
    ids = db.session.query(AuthMailJob.id, AuthMailJob.user_id).filter(
        AuthMailJob.attempts < 3, AuthMailJob.next_attempt_at <= now,
        or_(AuthMailJob.status == "pending", (AuthMailJob.status == "processing") &
            (AuthMailJob.updated_at < now-timedelta(minutes=5)))).order_by(AuthMailJob.id).limit(limit).all()
    db.session.rollback()
    result = {"sent": 0, "failed": 0, "cancelled": 0}
    for job_id, user_id in ids:
        user = lock_account(user_id)
        job = AuthMailJob.query.filter_by(id=job_id).populate_existing().with_for_update().one()
        now = utcnow()
        if job.status not in {"pending", "processing"} or job.attempts >= 3 or job.next_attempt_at > now:
            db.session.rollback()
            continue
        if job.status == "processing" and job.updated_at >= now-timedelta(minutes=5):
            db.session.rollback()
            continue
        if not user or not user.is_active_user or user.auth_epoch != job.auth_epoch or user.email != job.target_email or (job.purpose == "reset" and not user.email_verified_at):
            job.status = "cancelled"
            db.session.commit()
            result["cancelled"] += 1
            continue
        ActionToken.query.filter_by(user_id=user.id, purpose=job.purpose, consumed_at=None).update({"consumed_at": now})
        token, claim = secrets.token_urlsafe(32), secrets.token_hex(16)
        db.session.add(ActionToken(user_id=user.id, purpose=job.purpose, target_email=job.target_email,
            token_hash=digest(token), auth_epoch=user.auth_epoch, expires_at=now+timedelta(minutes=30)))
        job.status, job.claim, job.updated_at = "processing", claim, now
        job.attempts += 1
        recipient, purpose, attempt = job.target_email, job.purpose, job.attempts
        db.session.commit()
        # Fragment never reaches proxy access logs; landing JS puts it in a POST form.
        link = current_app.config["APP_BASE_URL"].rstrip("/")+"/account/email/"+purpose+"#"+token
        subject = "验证邮箱" if purpose == "verify" else "重置密码"
        body = f"请打开链接{subject}，30分钟内有效：\n{link}\n\n请使用最新邮件中的链接。如非本人操作，请忽略。"
        success = False
        try:
            if current_app.config.get("AUTH_MAIL_ADAPTER") == "capture" and current_app.testing:
                current_app.extensions.setdefault("auth_mail_capture", []).append((recipient, subject, body))
            else:
                send_smtp(recipient, subject, body, sender=current_app.config.get("AUTH_MAIL_FROM") or None,
                    credentials=smtp_credentials())
            success = True
        except MailError:
            pass  # Only aggregate safe delivery state is exposed.
        db.session.execute(update(AuthMailJob).where(AuthMailJob.id == job_id, AuthMailJob.claim == claim).values(
            status="sent" if success else ("failed" if attempt >= 3 else "pending"),
            updated_at=utcnow(), next_attempt_at=utcnow()+timedelta(minutes=attempt*2)))
        db.session.commit()
        result["sent" if success else "failed"] += 1
    return result


def consume(raw, purpose, password=None):
    if purpose not in {"verify", "reset"} or not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw):
        return False
    row = ActionToken.query.filter_by(token_hash=digest(raw), purpose=purpose).first()
    if row is None:
        return False
    user = lock_account(row.user_id)
    row = ActionToken.query.filter_by(id=row.id).populate_existing().one()
    now = utcnow()
    if (not user or not user.is_active_user or row.consumed_at or row.expires_at <= now
            or row.auth_epoch != user.auth_epoch or row.target_email != user.email
            or (purpose == "reset" and not user.email_verified_at)):
        db.session.rollback()
        return False
    consumed = db.session.execute(update(ActionToken).where(ActionToken.id == row.id,
        ActionToken.consumed_at.is_(None), ActionToken.expires_at > now).values(consumed_at=now))
    if consumed.rowcount != 1:
        db.session.rollback()
        return False
    if purpose == "verify":
        user.email_verified_at = now
        mirror_password(user)
        audit(user.id, "email.verified", "web")
    elif not change_password(user.id, password, expected_hash=user.password_hash):
        db.session.rollback()
        return False
    db.session.commit()
    return True
