"""Signed admin client from the Flask main site to the Generation Service.

The unified admin console lives on the main site. It calls the Generation
Service admin endpoints with the same internal viewer-context contract the
Next.js BFF uses: a short-lived HMAC-signed payload carried in
``X-Mavis-User-Context`` / ``X-Mavis-User-Signature`` headers.

Secrets are never logged or included in user-facing messages.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import requests
from flask import current_app


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
CONTEXT_LIFETIME_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 8


class GalleryAdminError(Exception):
    """Safe, user-facing error raised by the Gallery admin client."""

    def __init__(self, code: str, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def sign_admin_context(user_id: int, secret: str, now: int | None = None) -> tuple[str, str]:
    """Build the signed viewer-context headers exactly like the Next.js BFF."""
    timestamp = int(time.time()) if now is None else now
    payload = {
        "v": 1,
        "role": "admin",
        "userId": int(user_id),
        "requestId": str(uuid.uuid4()),
        "issuedAt": timestamp,
        "expiresAt": timestamp + CONTEXT_LIFETIME_SECONDS,
    }
    context = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64url(
        hmac.new(secret.encode("utf-8"), context.encode("utf-8"), hashlib.sha256).digest()
    )
    return context, signature


def gallery_admin_dashboard(user_id: int) -> dict[str, Any]:
    return _request("GET", "/v1/admin/dashboard", user_id)


def gallery_moderate_image(
    user_id: int,
    image_id: str,
    decision: str,
    expected_updated_at: str,
) -> dict[str, Any]:
    reason = "manual_approved" if decision == "approved" else "manual_rejected"
    return _request(
        "PATCH",
        f"/v1/admin/images/{quote(image_id, safe='')}/moderation",
        user_id,
        payload={
            "decision": decision,
            "reasonCodes": [reason],
            "expectedUpdatedAt": expected_updated_at,
        },
    )


def gallery_delete_image(user_id: int, image_id: str) -> None:
    _request("DELETE", f"/v1/images/{quote(image_id, safe='')}", user_id)


def gallery_update_provider(
    user_id: int,
    provider_id: str,
    status: str,
    priority: int,
    expected_updated_at: str,
) -> dict[str, Any]:
    return _request(
        "PATCH",
        f"/v1/admin/providers/{quote(provider_id, safe='')}",
        user_id,
        payload={
            "status": status,
            "priority": int(priority),
            "expectedUpdatedAt": expected_updated_at,
        },
    )


def gallery_update_workflow(
    user_id: int,
    workflow_id: str,
    is_enabled: bool,
    sort_order: int,
    expected_updated_at: str,
) -> dict[str, Any]:
    return _request(
        "PATCH",
        f"/v1/admin/workflows/{quote(workflow_id, safe='')}",
        user_id,
        payload={
            "isEnabled": bool(is_enabled),
            "sortOrder": int(sort_order),
            "expectedUpdatedAt": expected_updated_at,
        },
    )


def localize_iso(value: str | None) -> str:
    """Render an ISO-8601 timestamp in Asia/Shanghai for admin templates."""
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(value)
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def _request(method: str, path: str, user_id: int, payload: dict[str, Any] | None = None) -> Any:
    base_url, secret = _endpoint_config()
    context, signature = sign_admin_context(user_id, secret)
    headers = {
        "Accept": "application/json",
        "X-Mavis-User-Context": context,
        "X-Mavis-User-Signature": signature,
    }
    url = f"{base_url}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=payload if payload is not None else None,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        raise GalleryAdminError(
            "service_unavailable",
            "Gallery 管理服务暂时不可用，请稍后重试。",
            503,
        )
    if response.status_code >= 400:
        code, message = _safe_error(response)
        raise GalleryAdminError(code, message, response.status_code)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError:
        raise GalleryAdminError(
            "invalid_response",
            "Gallery 管理服务返回了无法解析的数据。",
            502,
        )


def _endpoint_config() -> tuple[str, str]:
    base_url = str(current_app.config.get("GALLERY_SERVICE_BASE_URL", "") or "").strip()
    secret = str(current_app.config.get("GALLERY_INTERNAL_HMAC_SECRET", "") or "")
    if len(secret.encode("utf-8")) < 32:
        raise GalleryAdminError(
            "unconfigured",
            "Gallery 管理后台未配置：缺少有效的 GALLERY_INTERNAL_HMAC_SECRET。",
            503,
        )
    parsed = urlparse(base_url)
    if not (parsed.scheme and parsed.hostname) or (
        parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS
    ):
        raise GalleryAdminError(
            "unconfigured",
            "Gallery 管理后台未配置：GALLERY_SERVICE_BASE_URL 必须是 HTTPS 地址。",
            503,
        )
    return base_url.rstrip("/"), secret


def _safe_error(response: requests.Response) -> tuple[str, str]:
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code", "service_error"))
            message = str(error.get("message", "Gallery 管理操作未完成。"))
            return code, message
    except ValueError:
        pass
    if response.status_code == 409:
        return "conflict", "数据已被其他管理员修改，请刷新后重试。"
    return "service_error", "Gallery 管理操作未完成，请稍后重试。"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
