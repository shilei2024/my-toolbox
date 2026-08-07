"""Admin views: dashboard, users, tools, logs, settings."""
from __future__ import annotations

import json
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, text

from auth.decorators import admin_required
from extensions import db
from models import (
    AnonUsage,
    Setting,
    Tool,
    UsageLog,
    User,
    UserToolGrant,
    UserUsage,
)
from utils.helpers import (
    china_day_utc_bounds,
    china_now,
    china_today_str,
    to_china_time,
)
from utils.settings import apply_runtime_settings, validate_site_settings

from . import admin_bp


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    today = china_today_str()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    seven_days_ago = now_utc - timedelta(days=7)
    today_start_utc, tomorrow_start_utc = china_day_utc_bounds(today)

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
        .filter(
            UsageLog.ts >= today_start_utc,
            UsageLog.ts < tomorrow_start_utc,
        )
        .group_by(UsageLog.tool_id)
        .all()
    )
    today_by_tool = {tool_id: count for tool_id, count in today_rows}

    # last 14 days daily volume
    first_day = china_now().date() - timedelta(days=13)
    first_day_utc, _ = china_day_utc_bounds(first_day)
    raw_timestamps = (
        db.session.query(UsageLog.ts)
        .filter(
            UsageLog.ts >= first_day_utc,
            UsageLog.ts < tomorrow_start_utc,
        )
        .all()
    )
    counts = Counter(
        local.strftime("%Y-%m-%d")
        for (ts,) in raw_timestamps
        if (local := to_china_time(ts)) is not None
    )
    daily_series = [
        (
            (first_day + timedelta(days=offset)).isoformat(),
            counts[(first_day + timedelta(days=offset)).isoformat()],
        )
        for offset in range(14)
    ]

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
    private_tools = (
        db.session.query(Tool)
        .filter(Tool.required_plan == "private")
        .order_by(Tool.order.asc(), Tool.name.asc())
        .all()
    )
    user_ids = [user.id for user in items]
    credits: dict[int, float] = {}
    if user_ids:
        try:
            rows = db.session.execute(
                text("SELECT user_id, available_amount FROM ai.credit_accounts WHERE user_id IN :ids"),
                {"ids": tuple(user_ids)},
            ).all()
            credits = {int(row[0]): float(row[1]) for row in rows}
        except Exception:  # noqa: BLE001
            credits = {}
    private_tool_ids = [tool.id for tool in private_tools]
    grants = set()
    if user_ids and private_tool_ids:
        grants = {
            (grant.user_id, grant.tool_id)
            for grant in db.session.query(UserToolGrant)
            .filter(
                UserToolGrant.user_id.in_(user_ids),
                UserToolGrant.tool_id.in_(private_tool_ids),
            )
            .all()
        }
    return render_template(
        "admin/users.html",
        users=items,
        private_tools=private_tools,
        tool_grants=grants,
        credits=credits,
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


@admin_bp.route("/users/<int:user_id>/nickname", methods=["POST"])
@login_required
@admin_required
def set_user_nickname(user_id: int):
    user = db.session.get(User, user_id) or abort(404)
    nickname = request.form.get("nickname", "").strip()
    if len(nickname) > 80:
        flash("昵称最多 80 个字符。", "danger")
        return redirect(url_for("admin.users"))
    user.nickname = nickname or None
    db.session.commit()
    from auth.routes import _sync_gallery_display_name  # noqa: PLC0415

    _sync_gallery_display_name(user.id, user.display_name)
    flash(f"用户 {user.email} 的昵称已更新。", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/credits", methods=["POST"])
@login_required
@admin_required
def set_user_credits(user_id: int):
    from datetime import datetime, timezone  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    user = db.session.get(User, user_id) or abort(404)
    raw = request.form.get("delta", "").strip()
    account = request.form.get("account", "free").strip().lower()
    if account not in {"free", "member"}:
        flash("账本类型必须是 free / member。", "danger")
        return redirect(url_for("admin.users"))
    try:
        delta = round(float(raw), 4)
        if not (-1000000000 <= delta <= 1000000000):
            raise ValueError
    except ValueError:
        flash("积分调整必须是 -1000000000 ~ 1000000000 的数字。", "danger")
        return redirect(url_for("admin.users"))
    if delta == 0:
        flash("调整值为 0，未做任何修改。", "warning")
        return redirect(url_for("admin.users"))

    idempotency = f"admin-credit:{user.id}:{datetime.now(timezone.utc).isoformat()}"
    table = "ai.member_credit_accounts" if account == "member" else "ai.credit_accounts"
    account_type = "member" if account == "member" else "free"
    try:
        with db.engine.begin() as conn:
            current = conn.execute(
                text(f"SELECT available_amount FROM {table} WHERE user_id = :uid FOR UPDATE"),
                {"uid": user.id},
            ).scalar() or 0
            new_available = round(float(current) + delta, 4)
            if new_available < 0:
                flash("调整后积分不能为负数（当前可用积分不足）。", "danger")
                return redirect(url_for("admin.users"))
            conn.execute(
                text(
                    f"INSERT INTO {table} (user_id, available_amount, reserved_amount, lifetime_granted, lifetime_spent, version, created_at, updated_at) "
                    "VALUES (:uid, :delta, 0, GREATEST(:delta, 0), 0, 0, now(), now()) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    f"available_amount = {table}.available_amount + :delta, "
                    f"lifetime_granted = {table}.lifetime_granted + GREATEST(:delta, 0), "
                    f"version = {table}.version + 1, updated_at = now()"
                ),
                {"uid": user.id, "delta": delta},
            )
            conn.execute(
                text(
                    "INSERT INTO ai.credit_ledger_entries (user_id, account_type, entry_type, delta_available, delta_reserved, available_after, reserved_after, source_type, source_ref, idempotency_key, metadata) "
                    "VALUES (:uid, :account_type, 'admin_adjustment', :delta, 0, :after, 0, 'admin', :ref, :idem, jsonb_build_object('operator_user_id', :op))"
                ),
                {"uid": user.id, "account_type": account_type, "delta": delta, "after": new_available, "ref": f"user:{user.id}", "idem": idempotency, "op": current_user.id},
            )
            db.session.rollback()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        flash("积分调整失败，请确认 ai 数据库表已迁移（0005）。", "danger")
        return redirect(url_for("admin.users"))
    flash(f"用户 {user.email} 积分调整 {delta:+,}，当前可用 {new_available:,.4f}。", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id: int):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("不能删除自己的账号。", "warning")
        return redirect(url_for("admin.users"))
    if user.is_admin:
        flash("不能删除管理员账号。", "warning")
        return redirect(url_for("admin.users"))
    # Soft delete: disable login and anonymize the account while preserving
    # audit history, usage logs and generated artwork attribution.
    user.is_active_user = False
    user.email = f"deleted-{user.id}@invalid.local"
    user.nickname = None
    user.password_hash = "!"
    db.session.commit()
    flash(f"用户 #{user.id} 已删除（停用并匿名化，历史记录保留）。", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/plan", methods=["POST"])
@login_required
@admin_required
def set_user_plan(user_id: int):
    user = db.session.get(User, user_id) or abort(404)
    plan = request.form.get("plan", "free").strip().lower()
    if plan not in {"free", "member", "pro", "vip"}:
        flash("会员等级必须是 free / member / pro / vip。", "danger")
        return redirect(url_for("admin.users"))
    user.plan = plan
    db.session.commit()
    flash(f"用户 {user.email} 的会员等级已设为 {plan}。", "success")
    return redirect(url_for("admin.users"))


# -----------------------------------------------------------------------------
# Redemption codes (Phase 3: China-friendly credit top-up)
# -----------------------------------------------------------------------------
@admin_bp.route("/redemption")
@login_required
@admin_required
def redemption():
    codes: list[dict] = []
    total = 0
    try:
        rows = db.session.execute(
            text("SELECT code, amount, status, created_at, redeemed_at, redeemed_by FROM ai.redemption_codes ORDER BY created_at DESC LIMIT 200")
        ).all()
        codes = [
            {
                "code": row[0],
                "amount": float(row[1]),
                "status": row[2],
                "created_at": row[3],
                "redeemed_at": row[4],
                "redeemed_by": row[5],
            }
            for row in rows
        ]
        total = db.session.execute(text("SELECT count(*) FROM ai.redemption_codes")).scalar() or 0
    except Exception:  # noqa: BLE001
        pass
    return render_template("admin/redemption.html", codes=codes, total=total, generated=[])


@admin_bp.route("/redemption/generate", methods=["POST"])
@login_required
@admin_required
def redemption_generate():
    try:
        amount = round(float(request.form.get("amount", "")), 4)
        count = int(request.form.get("count", ""))
    except ValueError:
        flash("金额/数量格式不正确。", "danger")
        return redirect(url_for("admin.redemption"))
    if not (0 < amount <= 1000000) or not (1 <= count <= 200):
        flash("金额需在 0–1000000 之间，数量需在 1–200 之间。", "danger")
        return redirect(url_for("admin.redemption"))
    generated: list[str] = []
    try:
        with db.engine.begin() as conn:
            for _ in range(count):
                code = "MP-" + "-".join(secrets.token_hex(2).upper() for _ in range(3))
                conn.execute(
                    text("INSERT INTO ai.redemption_codes (code, amount, created_by) VALUES (:code, :amount, :by)"),
                    {"code": code, "amount": amount, "by": current_user.id},
                )
                generated.append(code)
    except Exception:  # noqa: BLE001
        flash("生成失败，请确认 ai.redemption_codes 表已迁移（0010）。", "danger")
        return redirect(url_for("admin.redemption"))
    flash(f"已生成 {len(generated)} 个兑换码，每个 {amount:g} 会员积分。", "success")
    return render_template("admin/redemption.html", codes=[], total=0, generated=generated)


@admin_bp.route(
    "/users/<int:user_id>/tools/<string:tool_id>/toggle-access",
    methods=["POST"],
)
@login_required
@admin_required
def toggle_user_tool_access(user_id: int, tool_id: str):
    user = db.session.get(User, user_id) or abort(404)
    tool = db.session.get(Tool, tool_id) or abort(404)
    if tool.required_plan != "private":
        flash("该工具不是专有工具，不能设置用户级授权。", "danger")
        return redirect(url_for("admin.users"))
    if user.is_admin:
        flash("管理员自动拥有全部专有工具权限，无需单独授权。", "info")
        return redirect(url_for("admin.users"))

    key = {"user_id": user.id, "tool_id": tool.id}
    grant = db.session.get(UserToolGrant, key)
    if grant is None:
        db.session.add(
            UserToolGrant(
                user_id=user.id,
                tool_id=tool.id,
                granted_by_id=current_user.id,
            )
        )
        message = f"已向 {user.email} 开放“{tool.name}”。"
    else:
        db.session.delete(grant)
        message = f"已取消 {user.email} 的“{tool.name}”权限。"
    db.session.commit()
    flash(message, "success")
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
        try:
            start_utc, _ = china_day_utc_bounds(date_from)
            q = q.filter(UsageLog.ts >= start_utc)
        except ValueError:
            date_from = ""
    if date_to:
        try:
            _, end_utc = china_day_utc_bounds(date_to)
            q = q.filter(UsageLog.ts < end_utc)
        except ValueError:
            date_to = ""

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
    SETTING_KEYS = (
        "site_name",
        "site_tagline",
        "daily_free_limit",
        "anon_free_limit",
        "signup_credit_grant",
    )
    if request.method == "POST":
        submitted = {
            key: request.form.get(key, "").strip()
            for key in SETTING_KEYS
        }
        try:
            site_settings = validate_site_settings(submitted)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin.settings"))

        for key in SETTING_KEYS:
            value = str(site_settings[key]) if key in site_settings else submitted[key]
            row = db.session.get(Setting, key)
            if row is None:
                row = Setting(key=key, value=value)
                db.session.add(row)
            else:
                row.value = value
        db.session.commit()
        apply_runtime_settings(current_app, force=True)
        flash("设置已保存。", "success")
        return redirect(url_for("admin.settings"))

    stored = {}
    for key in SETTING_KEYS:
        row = db.session.get(Setting, key)
        if row:
            stored[key] = row.value
        else:
            stored[key] = None
    return render_template("admin/settings.html", stored=stored)
