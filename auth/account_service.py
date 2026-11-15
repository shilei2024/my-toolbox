"""Transaction-scoped account operations. Callers commit the complete action.

Lock order is always User -> Identity -> Session. users.password_hash remains
the transition authority; its canonical identity is mirrored in the same transaction.
"""
import hashlib
import re
import secrets
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from models import User, utcnow
from .account_models import AuthAudit, WebSession
from .mobile_models import BindingChallenge, ExternalIdentity, MobileSession

_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


def normalized_email(value):
    if not isinstance(value, str):
        return None
    try:
        value = value.strip().lower()
        value.encode("utf-8")
    except UnicodeError:
        return None
    if not 1 <= len(value) <= 255 or any(c <= " " or c == "\x7f" for c in value):
        return None
    return value


def audit(user_id, action, channel):
    # No request-derived details: never persist passwords, tokens or identifiers.
    db.session.add(AuthAudit(user_id=user_id, action=action, channel=channel))


def lock_account(user_id):
    return User.query.filter_by(id=user_id).populate_existing().with_for_update().one_or_none()


def identity_for_subject(provider, client_id, subject):
    return ExternalIdentity.query.filter_by(provider=provider, client_id=client_id, subject=subject).first()


def mirror_password(user):
    if not user.email or not user.password_hash:
        return None
    identity = ExternalIdentity.query.filter_by(provider="web_password", user_id=user.id).first()
    if identity is None:
        identity = ExternalIdentity(provider="web_password", client_id="web", user_id=user.id,
                                    identity_type="password")
        db.session.add(identity)
    identity.identifier = user.email.strip().lower()
    identity.subject = hashlib.sha256(identity.identifier.encode()).hexdigest()
    identity.password_hash = user.password_hash
    identity.active = user.is_active_user and user.password_hash != "!"
    identity.verified_at = user.email_verified_at
    identity.updated_at = utcnow()
    return identity


def authenticate_password(email, password, *, channel):
    email = normalized_email(email)
    if email is None or not isinstance(password, str) or not 1 <= len(password) <= 256:
        audit(None, "login.failed", channel)
        return None
    user = User.query.filter_by(email=email).populate_existing().with_for_update().first()
    try:
        password.encode("utf-8")
        valid = check_password_hash(user.password_hash if user and user.password_hash else _DUMMY_HASH, password)
    except (ValueError, UnicodeError):
        valid = False
    if not user or not valid or not user.is_active_user:
        audit(None, "login.failed", channel)
        return None
    identity = mirror_password(user)
    identity.last_login_at = user.last_login_at = utcnow()
    return user


def register_password(email, password):
    email = normalized_email(email)
    if not email or email.count("@") != 1 or not all(email.split("@")):
        raise ValueError("invalid_email")
    if (not isinstance(password, str) or not 8 <= len(password) <= 128
            or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password)):
        raise ValueError("invalid_password")
    password.encode("utf-8")
    user = User(email=email, is_admin=False, is_active_user=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    mirror_password(user)
    audit(user.id, "account.registered", "web")
    return user


def revoke_all(user, *, reason, channel):
    """Caller must hold the account lock; invalidate legacy cookies as well."""
    now = utcnow()
    user.auth_epoch = (user.auth_epoch or 0) + 1
    user.updated_at = now
    for model in (WebSession, MobileSession):
        model.query.filter_by(user_id=user.id, revoked_at=None).update({"revoked_at": now})
    BindingChallenge.query.filter_by(user_id=user.id, consumed_at=None).update({"consumed_at": now})
    audit(user.id, reason, channel)


def change_password(user_id, password, *, expected_hash, channel="web"):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        return False
    try:
        password.encode("utf-8")
    except UnicodeError:
        return False
    user = lock_account(user_id)
    if not user or not user.is_active_user or not secrets.compare_digest(user.password_hash or "", expected_hash or ""):
        return False
    user.set_password(password)
    mirror_password(user)
    revoke_all(user, reason="password.changed", channel=channel)
    return True


def toggle_active(user_id):
    user = lock_account(user_id)
    if user is None:
        return None
    user.is_active_user = not user.is_active_user
    revoke_all(user, reason="account.enabled" if user.is_active_user else "account.disabled", channel="admin")
    mirror_password(user)
    return user


def soft_delete(user_id):
    user = lock_account(user_id)
    if user is None:
        return None
    user.is_active_user = False
    user.email = f"deleted-{user.id}@invalid.local"
    user.nickname = None
    user.password_hash = "!"
    user.email_verified_at = None
    revoke_all(user, reason="account.deleted", channel="admin")
    mirror_password(user)
    return user
