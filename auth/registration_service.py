"""Pending email requests own no account or session until atomic completion."""
from datetime import timedelta
import re
import secrets
from flask import current_app
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import User, utcnow
from .account_models import AccountRegistration, AuthMailJob
from . import account_service
from .session_service import digest


def request_registration(email, return_to=None, *, create=True):
    """Uniform public response; lock Registration -> MailJob. Caller commits."""
    from .email_service import ready
    email = account_service.normalized_email(email)
    if email is None:
        return False
    if not isinstance(return_to, str) or len(return_to) > 1024:
        return_to = None
    if not ready() or User.query.filter_by(email=email).first():
        return False
    row = AccountRegistration.query.filter_by(email=email).populate_existing().with_for_update().first()
    now = utcnow()
    if row is None and create:
        try:
            with db.session.begin_nested():
                row = AccountRegistration(email=email, return_to=return_to, last_requested_at=now)
                db.session.add(row)
                db.session.flush()
        except IntegrityError:
            row = AccountRegistration.query.filter_by(email=email).populate_existing().with_for_update().one()
    elif row is not None and row.last_requested_at > now-timedelta(minutes=1):
        return False
    if row is None or row.completed_at:
        return False
    pending = AuthMailJob.query.filter_by(registration_id=row.id, purpose="register").filter(
        AuthMailJob.status.in_(["pending", "processing"])).first()
    if pending:
        return False
    row.last_requested_at = now
    # Preserve the first validated return URL; a resend cannot redirect someone.
    db.session.add(AuthMailJob(registration_id=row.id, purpose="register", target_email=email, auth_epoch=0))
    return True


def prepare_delivery(job_id, registration_id):
    """Return a payload after committing the claim; no network under the lock."""
    row = AccountRegistration.query.filter_by(id=registration_id).populate_existing().with_for_update().one()
    job = AuthMailJob.query.filter_by(id=job_id).populate_existing().with_for_update().one()
    now = utcnow()
    if (job.status not in {"pending", "processing"} or job.attempts >= 3 or job.next_attempt_at > now
            or (job.status == "processing" and job.updated_at >= now-timedelta(minutes=5))):
        db.session.rollback()
        return None
    if row.completed_at or row.email != job.target_email or User.query.filter_by(email=row.email).first():
        job.status = "cancelled"
        db.session.commit()
        return "cancelled"
    token = secrets.token_urlsafe(32)
    row.token_hash, row.expires_at = digest(token), now+timedelta(minutes=30)
    job.status, job.claim, job.updated_at = "processing", secrets.token_hex(16), now
    job.attempts += 1
    link = current_app.config["APP_BASE_URL"].rstrip("/")+"/account/email/register#"+token
    payload = (job.id, row.email, "验证邮箱，完成注册",
        f"请打开链接验证邮箱并设置登录密码，30分钟内有效：\n{link}\n\n完成后才能使用账号。请使用最新邮件中的链接。如非本人操作，请忽略。",
        job.claim, job.attempts)
    db.session.commit()
    return payload


def complete(token, password):
    """Ownership proof + fresh owner-selected password -> User + welcome job."""
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    row = AccountRegistration.query.filter_by(token_hash=digest(token)).populate_existing().with_for_update().first()
    now = utcnow()
    if not row or row.completed_at or not row.expires_at or row.expires_at <= now:
        db.session.rollback()
        return None
    if User.query.filter_by(email=row.email).first():
        db.session.rollback()
        return None  # Never merge or replace credentials of an existing account.
    try:
        user = account_service.register_password(row.email, password)
        user.email_verified_at = now
        account_service.mirror_password(user)
        row.completed_at, row.user_id = now, user.id
        AuthMailJob.query.filter_by(registration_id=row.id).filter(
            AuthMailJob.status.in_(["pending", "processing"])).update({"status":"cancelled"})
        # Registration success does not depend on SMTP being available right now.
        db.session.add(AuthMailJob(user_id=user.id, purpose="welcome", target_email=user.email, auth_epoch=user.auth_epoch))
        account_service.audit(user.id, "registration.verified", "web")
        result = (user.id, row.return_to)
        db.session.commit()
        return result
    except (ValueError, UnicodeError, IntegrityError):
        db.session.rollback()
        return None
