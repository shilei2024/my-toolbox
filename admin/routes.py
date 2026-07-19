"""Admin views: dashboard, users, tools, logs, settings."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from auth.decorators import admin_required
from extensions import db
from models import AnonUsage, Setting, Tool, UsageLog, User, UserUsage
from utils.helpers import utc_today_str

from . import admin_bp


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    today = utc_today_str()
    seven_days_ago = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).strftime("%Y-%m-%d %H:%M:%S")

    total_users = db.session.query(func.count(User.id)).scalar() or 0
    today_active_users = (
        db.session.query(func.count(UserUsage.user_id))
        .filter(UserUsage.day == today)
        .distinct()
        .scalar()
        or 0
    )

    # per-tool totals (last 7 days)
    rows = (
        db.session.query(UsageLog.tool_id, UsageLog.status, func.count(UsageLog.id))
        .filter(UsageLog.ts >= seven_days_ago)
        .group_by(UsageLog.tool_id, UsageLog.status)
        .all()
    )
    tool_stats: dict[str, dict[str, int]] = {}
    for tool_id, status, count in rows:
        tool_stats.setdefault(tool_id, {"success": 0, "failed": 0, "rate_limited": 0})
        tool_stats[tool_id][status] = tool_stats[tool_id].get(status, 0) + count

    # today per tool
    today_rows = (
        db.session.query(UsageLog.tool_id, func.count(UsageLog.id))
        .filter(UsageLog.ts >= today + " 00:00:00")
        .group_by(UsageLog.tool_id)
        .all()
    )
    today_by_tool = {tool_id: count for tool_id, count in today_rows}

    # last 14 days daily volume
    fourteen_days_ago = (
        datetime.now(timezone.utc) - timedelta(days=14)
    ).strftime("%Y-%m-%d %H:%M:%S")
    raw_daily = (
        db.session.query(UsageLog.ts, func.count(UsageLog.id))
        .filter(UsageLog.ts >= fourteen_days_ago)
        .group_by(func.date(UsageLog.ts))
        .all()
    )
    daily_series = sorted(
        (ts.strftime("%Y-%m-%d"), count) for ts, count in raw_daily if ts
    )

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        today_active_users=today_active_users,
        tool_stats=tool_stats,
        today_by_tool=today_by_tool,
        daily_series=daily_series,
    )


# -----------------------------------------------------------------------------
# Users
# -----------------------------------------------------------------------------
@admin_bp.route("/users")
@login_required
@admin_required
def users():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 25
    q = db.session.query(User).order_by(User.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return render_template(
        "admin/users.html",
        users=items,
        page=page,
        per_page=per_page,
        total=total,
    )


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id: int):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("不能禁用自己的账号。", "warning")
        return redirect(url_for("admin.users"))
    user.is_active_user = not user.is_active_user
    db.session.commit()
    flash(
        f"用户 {user.email} 已{'禁用' if not user.is_active_user else '启用'}。",
        "success",
    )
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/limit", methods=["POST"])
@login_required
@admin_required
def set_user_limit(user_id: int):
    user = db.session.get(User, user_id) or abort(404)
    tool_id = request.form.get("tool_id", "").strip()
    raw = request.form.get("limit", "").strip()
    new_map = user.custom_limit_map
    if not tool_id:
        flash("工具 ID 不能为空。", "danger")
    else:
        if raw == "" or raw.lower() in {"default", "null", "none"}:
            new_map.pop(tool_id, None)
            flash(f"已重置 {user.email} 在 {tool_id} 的自定义上限。", "success")
        else:
            try:
                value = int(raw)
                if value < 0 or value > 100000:
                    raise ValueError
                new_map[tool_id] = value
                flash(f"已设置 {user.email} 在 {tool_id} 的每日上限为 {value}。", "success")
            except ValueError:
                flash("上限必须是 0 - 100000 的整数。", "danger")
                return redirect(url_for("admin.users"))
    user.custom_limits = json.dumps(new_map) if new_map else None
    db.session.commit()
    return redirect(url_for("admin.users"))


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------
@admin_bp.route("/tools")
@login_required
@admin_required
def tools():
    items = db.session.query(Tool).order_by(Tool.order.asc()).all()
    return render_template("admin/tools.html", tools=items)


@admin_bp.route("/tools/<string:tool_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_tool(tool_id: str):
    tool = db.session.get(Tool, tool_id) or abort(404)
    tool.enabled = not tool.enabled
    db.session.commit()
    flash(
        f"工具 {tool.name} 已{'禁用' if not tool.enabled else '启用'}。",
        "success",
    )
    return redirect(url_for("admin.tools"))


# -----------------------------------------------------------------------------
# Logs
# -----------------------------------------------------------------------------
@admin_bp.route("/logs")
@login_required
@admin_required
def logs():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 20

    tool_filter = request.args.get("tool", "").strip()
    status_filter = request.args.get("status", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()

    q = db.session.query(UsageLog)
    if tool_filter:
        q = q.filter(UsageLog.tool_id == tool_filter)
    if status_filter:
        q = q.filter(UsageLog.status == status_filter)
    if date_from:
        q = q.filter(UsageLog.ts >= date_from + " 00:00:00")
    if date_to:
        q = q.filter(UsageLog.ts <= date_to + " 23:59:59")

    total = q.count()
    items = q.order_by(UsageLog.ts.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # build tool filter list
    tool_choices = [
        row[0]
        for row in db.session.query(UsageLog.tool_id).distinct().order_by(UsageLog.tool_id).all()
    ]

    return render_template(
        "admin/logs.html",
        logs=items,
        page=page,
        per_page=per_page,
        total=total,
        tool_choices=tool_choices,
        tool_filter=tool_filter,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )


# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------
@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    AI_KEYS = (
        "site_name",
        "site_tagline",
        "daily_free_limit",
        "anon_free_limit",
        "AI_PROVIDER",
        "AI_API_KEY",
        "AI_BASE_URL",
        "AI_MODEL",
    )
    AI_DEFAULTS = {
        "AI_PROVIDER": "pollinations",
        "AI_BASE_URL": "https://image.pollinations.ai",
        "AI_MODEL": "",
        "AI_API_KEY": "",
    }
    if request.method == "POST":
        for key in AI_KEYS:
            value = request.form.get(key, "").strip()
            # For AI keys, empty string means "use env default" → delete the row.
            if key.startswith("AI_") and value == "":
                row = db.session.get(Setting, key)
                if row:
                    db.session.delete(row)
                continue
            row = db.session.get(Setting, key)
            if row is None:
                row = Setting(key=key, value=value)
                db.session.add(row)
            else:
                row.value = value
        db.session.commit()
        flash("设置已保存。", "success")
        return redirect(url_for("admin.settings"))

    stored = {}
    for key in AI_KEYS:
        row = db.session.get(Setting, key)
        if row:
            stored[key] = row.value
        elif key in AI_DEFAULTS:
            stored[key] = AI_DEFAULTS[key]
        else:
            stored[key] = None
    # For display, show the effective value (DB override or env default).
    stored["AI_PROVIDER_EFFECTIVE"] = stored.get("AI_PROVIDER") or current_app.config.get("AI_PROVIDER", "pollinations")
    stored["AI_BASE_URL_EFFECTIVE"] = stored.get("AI_BASE_URL") or current_app.config.get("AI_BASE_URL", "https://image.pollinations.ai")
    stored["AI_MODEL_EFFECTIVE"] = stored.get("AI_MODEL") or current_app.config.get("AI_MODEL", "")
    stored["AI_API_KEY_EFFECTIVE"] = stored.get("AI_API_KEY") or current_app.config.get("AI_API_KEY", "")
    # Don't send the full key to the template; mask it.
    key_eff = stored["AI_API_KEY_EFFECTIVE"]
    stored["AI_API_KEY_MASKED"] = (key_eff[:6] + "…" + key_eff[-4:]) if len(key_eff) > 12 else ("•" * len(key_eff) if key_eff else "")
    return render_template("admin/settings.html", stored=stored)
