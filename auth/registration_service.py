"""Pending email requests own no account or session until atomic completion."""
from datetime import timedelta
import re
import secrets
from flask import current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from extensions import db
from models import User, utcnow
from .account_models import AccountRegistration, AuthMailJob
from . import account_service
from .session_service import digest


def request_registration(email, return_to=None, *, create=True, password=None):
    """Uniform public response; lock Registration -> MailJob. Caller commits."""
    from .email_service import ready
    email = account_service.normalized_email(email)
    if email is None:
        return False
    if not isinstance(return_to, str) or len(return_to) > 1024:
        return_to = None
    if not ready() or User.query.filter_by(email=email).first():
        return False
    if create:
        if (not isinstance(password,str) or not 8 <= len(password) <= 128
                or not re.search(r'[A-Za-z]',password) or not re.search(r'\d',password)):
            return False
        try:
            password.encode('utf-8')
        except UnicodeError:
            return False
    row = AccountRegistration.query.filter_by(email=email).populate_existing().with_for_update().first()
    now = utcnow()
    created = False
    if row is None and create:
        try:
            with db.session.begin_nested():
                row = AccountRegistration(email=email, return_to=return_to, last_requested_at=now)
                db.session.add(row)
                db.session.flush()
                created = True
        except IntegrityError:
            row = AccountRegistration.query.filter_by(email=email).populate_existing().with_for_update().one()
    if row is not None and not created and row.last_requested_at > now-timedelta(minutes=1):
        return False
    if row is None or row.completed_at:
        return False
    if create:
        # Old emailed links cannot activate a later replacement password.
        # Plain resends preserve the previously submitted password hash.
        row.password_hash = generate_password_hash(password)
        row.token_hash, row.expires_at = None, None
        AuthMailJob.query.filter_by(registration_id=row.id).filter(
            AuthMailJob.status.in_(['pending','processing'])).update({'status':'cancelled'})
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
    purpose = 'register-confirm' if row.password_hash else 'register'
    link = current_app.config["APP_BASE_URL"].rstrip("/")+"/account/email/"+purpose+'#'+token
    instruction = '确认邮箱并完成注册' if row.password_hash else '验证邮箱并设置登录密码'
    payload = (job.id, row.email, "验证邮箱，完成注册",
        f"请打开链接{instruction}，30分钟内有效：\n{link}\n\n本邮件对应你提交的注册申请。请使用最新邮件中的链接。如非本人注册，请忽略，不要确认。",
        job.claim, job.attempts)
    db.session.commit()
    return payload


def complete(token, password=None):
    """Confirm the stored password; only legacy requests set it on activation."""
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
        if row.password_hash:
            user = User(email=row.email,password_hash=row.password_hash,is_admin=False,is_active_user=True)
            db.session.add(user)
            db.session.flush()
            account_service.audit(user.id,'account.registered','web')
        else:
            user = account_service.register_password(row.email, password)
        user.email_verified_at = now
        account_service.mirror_password(user)
        row.completed_at, row.user_id = now, user.id
        row.password_hash = None  # The formal account now owns the credential.
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
