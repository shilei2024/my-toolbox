"""Admin-issued, single-use password reset codes; no mail backend required."""
from __future__ import annotations

import hashlib
import hmac

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import db
from models import User

SALT = "password-reset-v1"
# Anything the admin should know but the public form must not disclose.
GENERIC_ERROR = "重置码无效、已过期或账号不匹配"


def mode() -> str:
    return str(current_app.config.get("PASSWORD_RESET_MODE", "admin")).strip().lower()


def ttl_minutes() -> int:
    try:
        return max(1, min(int(current_app.config.get("PASSWORD_RESET_TTL_MINUTES", 60)), 1440))
    except (TypeError, ValueError):
        return 60


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def _fingerprint(user: User) -> str:
    return hashlib.sha256((user.password_hash or "").encode()).hexdigest()[:16]


def issue(user: User) -> str:
    """Sign a code bound to the account's current password hash.

    A successful reset changes that hash, so every earlier code for the account
    dies by itself: no extra table, cleanup job or migration is required.
    """
    if mode() == "disabled":
        raise ValueError("password-reset-disabled")
    return _serializer().dumps({"uid": user.id, "ph": _fingerprint(user)})


def verify(code: str, *, max_age: int | None = None) -> tuple[User | None, str | None]:
    if not isinstance(code, str) or not 1 <= len(code) <= 512:
        return None, "invalid"
    try:
        payload = _serializer().loads(
            code.strip(), max_age=max_age if max_age is not None else ttl_minutes() * 60
        )
    except SignatureExpired:
        return None, "expired"
    except (BadSignature, TypeError, ValueError):
        return None, "invalid"
    if not isinstance(payload, dict):
        return None, "invalid"
    user = db.session.get(User, payload.get("uid") or 0)
    if user is None or not user.is_active_user:
        return None, "invalid"
    if not hmac.compare_digest(str(payload.get("ph", "")), _fingerprint(user)):
        return None, "invalid"
    return user, None


def reset(user: User, new_password: str) -> None:
    from .account_service import change_password
    expected = user.password_hash
    if not change_password(user.id, new_password, expected_hash=expected):
        raise ValueError("password_reset_state_changed")
    db.session.commit()


def redeem(code: str, email: str, new_password: str) -> bool:
    """Recheck the signed credential under the account lock before changing it."""
    from .account_service import lock_account, change_password
    user, _ = verify(code)
    if user is None:
        return False
    user = lock_account(user.id)
    user, _ = verify(code)
    if user is None or (user.email or "").strip().lower() != email:
        db.session.rollback()
        return False
    if not change_password(user.id, new_password, expected_hash=user.password_hash):
        db.session.rollback()
        return False
    db.session.commit()
    return True
