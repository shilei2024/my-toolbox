"""Database-backed settings that take effect without restarting the app."""
from __future__ import annotations

from typing import Any

from flask import Flask

from extensions import db
from models import Setting


RUNTIME_SETTING_KEYS = {
    "site_name": "SITE_NAME",
    "site_tagline": "SITE_TAGLINE",
    "daily_free_limit": "DAILY_FREE_LIMIT",
    "anon_free_limit": "ANON_FREE_LIMIT",
}


def validate_site_settings(values: dict[str, str]) -> dict[str, Any]:
    """Validate and coerce settings submitted by the admin form."""
    site_name = values.get("site_name", "").strip()
    site_tagline = values.get("site_tagline", "").strip()
    if not site_name:
        raise ValueError("网站名称不能为空。")
    if len(site_name) > 100:
        raise ValueError("网站名称不能超过 100 个字符。")
    if len(site_tagline) > 300:
        raise ValueError("首页标语不能超过 300 个字符。")

    try:
        daily_limit = int(values.get("daily_free_limit", ""))
        anon_limit = int(values.get("anon_free_limit", ""))
    except ValueError as exc:
        raise ValueError("免费次数必须是整数。") from exc
    if not 0 <= daily_limit <= 1000:
        raise ValueError("注册用户每日免费次数必须在 0–1000 之间。")
    if not 0 <= anon_limit <= 100:
        raise ValueError("匿名用户免费次数必须在 0–100 之间。")

    return {
        "site_name": site_name,
        "site_tagline": site_tagline,
        "daily_free_limit": daily_limit,
        "anon_free_limit": anon_limit,
    }


def apply_runtime_settings(app: Flask) -> None:
    """Refresh effective site settings from the DB for this worker."""
    rows = (
        db.session.query(Setting)
        .filter(Setting.key.in_(tuple(RUNTIME_SETTING_KEYS)))
        .all()
    )
    raw = {row.key: row.value or "" for row in rows}
    if not raw:
        return

    # A legacy or manually edited invalid row must not break every request.
    combined = {
        "site_name": raw.get("site_name", str(app.config["SITE_NAME"])),
        "site_tagline": raw.get("site_tagline", str(app.config["SITE_TAGLINE"])),
        "daily_free_limit": raw.get(
            "daily_free_limit", str(app.config["DAILY_FREE_LIMIT"])
        ),
        "anon_free_limit": raw.get(
            "anon_free_limit", str(app.config["ANON_FREE_LIMIT"])
        ),
    }
    try:
        effective = validate_site_settings(combined)
    except ValueError as exc:
        app.logger.warning("Ignoring invalid database-backed site settings: %s", exc)
        return

    for db_key, config_key in RUNTIME_SETTING_KEYS.items():
        app.config[config_key] = effective[db_key]
