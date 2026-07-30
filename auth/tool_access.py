"""Authorization helpers for tools that require an explicit user grant."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import Flask, abort, jsonify, redirect, request, url_for
from flask_login import current_user

from extensions import db
from models import UserToolGrant


def can_access_private_tool(tool_id: str) -> bool:
    """Admins always pass; other users need a persisted explicit grant."""
    if not current_user.is_authenticated:
        return False
    if getattr(current_user, "is_admin", False):
        return True
    return (
        db.session.get(
            UserToolGrant,
            {"user_id": current_user.id, "tool_id": tool_id},
        )
        is not None
    )


def _denied_response(tool_id: str) -> Any:
    if not current_user.is_authenticated:
        if request.method == "GET" and "/api/" not in request.path:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return jsonify(error="该工具仅对已授权用户开放，请先登录。", tool_id=tool_id), 403

    if request.method != "GET" or "/api/" in request.path or request.is_json:
        return jsonify(error="你的账号尚未获得该专有工具的使用权限。", tool_id=tool_id), 403
    abort(403)


def register_private_tool_guards(
    app: Flask,
    private_routes: Mapping[str, str],
) -> None:
    """Protect every route below each configured private-tool URL prefix."""
    normalized = tuple(
        sorted(
            (
                (tool_id, "/" + prefix.strip("/"))
                for tool_id, prefix in private_routes.items()
            ),
            key=lambda item: len(item[1]),
            reverse=True,
        )
    )
    app.config["PRIVATE_TOOL_ROUTES"] = dict(normalized)

    @app.before_request
    def _guard_private_tools():  # noqa: ANN202
        if app.config.get("TESTING") and not app.config.get(
            "ENFORCE_PRIVATE_TOOL_ACCESS_IN_TESTS",
            False,
        ):
            return None
        for tool_id, prefix in normalized:
            if request.path == prefix or request.path.startswith(prefix + "/"):
                if not can_access_private_tool(tool_id):
                    return _denied_response(tool_id)
                break
        return None
