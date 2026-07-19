"""
Auth decorators.

The key one is `require_usage` — every tool view should be wrapped with it so
the free-tier / anonymous counter is enforced uniformly.
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from flask import abort, current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user

from extensions import db
from models import AnonUsage, UsageLog, UserUsage, new_anon_id
from utils.helpers import get_client_ip, utc_today_str

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# ensure_anon_id: stored in session so we count anonymous users across pages
# -----------------------------------------------------------------------------
def ensure_anon_id() -> str:
    from flask import session

    aid = session.get("anon_id")
    if not aid:
        aid = new_anon_id()
        session["anon_id"] = aid
        session.permanent = True
    return aid


# -----------------------------------------------------------------------------
# Admin guard
# -----------------------------------------------------------------------------
def admin_required(view_func: Callable) -> Callable:
    @wraps(view_func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapper


# -----------------------------------------------------------------------------
# Usage counter helpers
# -----------------------------------------------------------------------------
def _anon_count(anon_id: str, tool_id: str, day: str) -> int:
    row = (
        db.session.query(AnonUsage)
        .filter_by(anon_id=anon_id, tool_id=tool_id, day=day)
        .one_or_none()
    )
    return row.count if row else 0


def _user_count(user_id: int, tool_id: str, day: str) -> int:
    row = (
        db.session.query(UserUsage)
        .filter_by(user_id=user_id, tool_id=tool_id, day=day)
        .one_or_none()
    )
    return row.count if row else 0


def _bump_anon(anon_id: str, tool_id: str, day: str, ip: str) -> None:
    row = (
        db.session.query(AnonUsage)
        .filter_by(anon_id=anon_id, tool_id=tool_id, day=day)
        .one_or_none()
    )
    if row is None:
        row = AnonUsage(anon_id=anon_id, tool_id=tool_id, day=day, count=1, last_ip=ip)
        db.session.add(row)
    else:
        row.count += 1
        row.last_ip = ip


def _bump_user(user_id: int, tool_id: str, day: str) -> None:
    row = (
        db.session.query(UserUsage)
        .filter_by(user_id=user_id, tool_id=tool_id, day=day)
        .one_or_none()
    )
    if row is None:
        row = UserUsage(user_id=user_id, tool_id=tool_id, day=day, count=1)
        db.session.add(row)
    else:
        row.count += 1


def _log(
    tool_id: str,
    status: str,
    message: str | None = None,
    user_id: int | None = None,
    anon_id: str | None = None,
    email: str | None = None,
    ip: str | None = None,
) -> None:
    db.session.add(
        UsageLog(
            tool_id=tool_id,
            status=status,
            message=message,
            user_id=user_id,
            anon_id=anon_id,
            email=email,
            ip=ip,
        )
    )


# -----------------------------------------------------------------------------
# Public helpers — used by tool views / templates
# -----------------------------------------------------------------------------
def remaining_for(tool_id: str) -> int:
    """Return the number of free uses remaining *right now* (∞ for admins)."""
    if current_user.is_authenticated:
        if getattr(current_user, "is_admin", False):
            return 10**9
        limit = current_user.limit_for(tool_id, current_app.config["DAILY_FREE_LIMIT"])
        used = _user_count(current_user.id, tool_id, utc_today_str())
        return max(0, limit - used)

    aid = ensure_anon_id()
    used = _anon_count(aid, tool_id, utc_today_str())
    return max(0, current_app.config["ANON_FREE_LIMIT"] - used)


def has_quota(tool_id: str) -> bool:
    return remaining_for(tool_id) > 0


# -----------------------------------------------------------------------------
# The decorator
# -----------------------------------------------------------------------------
def require_usage(tool_id: str) -> Callable:
    """
    Gate a view: anonymous users must have a free trial slot, logged-in users
    must have daily quota. On success, the counter is *not* bumped yet — call
    `commit_usage()` after the tool actually finishes work.
    """

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # admins bypass everything
            if current_user.is_authenticated and getattr(current_user, "is_admin", False):
                return view_func(*args, **kwargs)

            ip = get_client_ip()

            if current_user.is_authenticated:
                limit = current_user.limit_for(
                    tool_id, current_app.config["DAILY_FREE_LIMIT"]
                )
                used = _user_count(current_user.id, tool_id, utc_today_str())
                if used >= limit:
                    return _quota_exceeded(
                        "今日免费次数已用完，请明天再试或升级会员。",
                        tool_id=tool_id,
                        user_id=current_user.id,
                        email=current_user.email,
                        ip=ip,
                    )
            else:
                aid = ensure_anon_id()
                used = _anon_count(aid, tool_id, utc_today_str())
                if used >= current_app.config["ANON_FREE_LIMIT"]:
                    return _quota_exceeded(
                        "试用次数已用完，请注册或登录后继续使用。",
                        tool_id=tool_id,
                        anon_id=aid,
                        ip=ip,
                    )

            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def commit_usage(tool_id: str, *, success: bool = True, message: str | None = None) -> None:
    """Atomically bump the counter and write an audit log entry."""
    ip = get_client_ip()
    day = utc_today_str()

    if current_user.is_authenticated:
        user_id = current_user.id
        email = current_user.email
        anon_id = None
        if success:
            _bump_user(user_id, tool_id, day)
    else:
        user_id = None
        email = None
        anon_id = ensure_anon_id()
        if success:
            _bump_anon(anon_id, tool_id, day, ip)

    _log(
        tool_id=tool_id,
        status="success" if success else "failed",
        message=message,
        user_id=user_id,
        anon_id=anon_id,
        email=email,
        ip=ip,
    )
    db.session.commit()


def _quota_exceeded(message: str, **log_kwargs: Any):
    # API-style tools (XHR) return JSON; HTML tools get a flash + redirect.
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(error=message), 429

    _log(tool_id=log_kwargs.pop("tool_id"), status="rate_limited", message=message, **log_kwargs)
    db.session.commit()
    flash(message, "warning")
    # Anonymous -> bounce to login; logged-in -> back to tool page
    if current_user.is_authenticated:
        return redirect(request.referrer or url_for("main.index"))
    return redirect(url_for("auth.login", next=request.path))
