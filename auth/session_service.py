"""Database-backed website sessions, including signed remember cookies."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from flask import current_app, session
from flask_login import login_user
from extensions import db
from models import User, utcnow
from .account_models import WebSession
from .account_service import audit, lock_account, revoke_all
from .mobile_models import MobileSession


def issue_mobile_session(user, identity, *, channel, lifetime):
    """Account and identity have already been validated under the account lock."""
    token = secrets.token_urlsafe(32)
    expires = utcnow() + lifetime
    db.session.add(MobileSession(user_id=user.id, identity_id=identity.id,
        token_hash=digest(token), auth_epoch=user.auth_epoch, expires_at=expires))
    audit(user.id, "session.created", channel)
    return token, expires


def end_mobile_session(user_id, session_id):
    lock_account(user_id)
    MobileSession.query.filter_by(id=session_id, user_id=user_id, revoked_at=None).update({"revoked_at": utcnow()})
    audit(user_id, "session.revoked", "mobile")


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def start_web_session(user, *, remember):
    """Caller holds the account lock (or created it) and commits before response."""
    token = secrets.token_urlsafe(32)
    row = WebSession(user_id=user.id, token_hash=digest(token), auth_epoch=user.auth_epoch or 0,
                     expires_at=utcnow() + timedelta(days=14 if remember else 1))
    db.session.add(row)
    audit(user.id, "session.created", "web")
    db.session.commit()
    # Flask-Login remember cookies use session['_user_id']; User.id remains numeric.
    login_user(user, remember=remember)
    if not remember:
        session["_remember"] = "clear"
    session["_user_id"] = "v2:" + token


def legacy_cookie_allowed():
    cutoff = current_app.config.get("AUTH_LEGACY_COOKIE_UNTIL", "")
    try:
        end = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        return end.tzinfo is not None and datetime.now(timezone.utc) < end
    except (ValueError, TypeError, AttributeError):
        return False


def load_web_user(identifier):
    if not isinstance(identifier, str):
        return None
    if re.fullmatch(r"v2:[A-Za-z0-9_-]{43}", identifier):
        row = WebSession.query.filter_by(token_hash=digest(identifier[3:])).populate_existing().first()
        if not row or row.revoked_at or row.expires_at <= utcnow():
            return None
        user = db.session.get(User, row.user_id, populate_existing=True)
        return user if user and user.is_active_user and user.auth_epoch == row.auth_epoch else None
    if re.fullmatch(r"[1-9][0-9]{0,9}", identifier) and int(identifier) <= 2147483647 and legacy_cookie_allowed():
        user = db.session.get(User, int(identifier), populate_existing=True)
        return user if user and user.is_active_user and user.auth_epoch == 0 else None
    return None


def end_web_session(user_id):
    user = lock_account(user_id)
    if user is None:
        return
    identifier = session.get("_user_id", "")
    if isinstance(identifier, str) and re.fullmatch(r"v2:[A-Za-z0-9_-]{43}", identifier):
        WebSession.query.filter_by(user_id=user_id, token_hash=digest(identifier[3:]), revoked_at=None).update({"revoked_at": utcnow()})
        audit(user_id, "session.revoked", "web")
    else:
        revoke_all(user, reason="legacy_session.revoked", channel="web")
    db.session.commit()
