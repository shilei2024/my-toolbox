"""Unified-admin configuration for customer project organizations and roles."""
from __future__ import annotations

from datetime import date

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select

from auth.decorators import admin_required
from customer_projects.models import ProjectExportPolicy, ProjectReminderPolicy
from customer_projects.services.exports import DEFAULT_EXPORT_ROLES, ensure_default_export_policy
from customer_projects.services.projects import ROLE_CODES, add_audit, bootstrap_organization, seed_default_statuses
from customer_projects.services.reminders import ensure_default_policy
from extensions import db
from models import User
from shared.business_calendar import BusinessCalendarError, upsert_business_day_override
from shared.models import NotificationOutbox, NotificationWorkerHeartbeat, Organization, OrganizationBusinessDayOverride, OrganizationMembership
from shared.notifications import cancel_pending_notifications_for_organization

from . import admin_bp


@admin_bp.get("/customer-projects")
@admin_required
def customer_projects_settings():
    organizations = list(db.session.scalars(select(Organization).order_by(Organization.created_at)))
    org = organizations[0] if organizations else None
    rows = []
    policy = None
    export_policy = None
    notifications = []
    heartbeats = []
    business_days = []
    if org:
        rows = list(
            db.session.execute(
                select(User, OrganizationMembership)
                .outerjoin(
                    OrganizationMembership,
                    (OrganizationMembership.user_id == User.id)
                    & (OrganizationMembership.organization_id == org.id),
                )
                .order_by(User.email)
            )
        )
        policy = db.session.scalar(
            select(ProjectReminderPolicy).where(ProjectReminderPolicy.organization_id == org.id)
        )
        export_policy = db.session.scalar(
            select(ProjectExportPolicy).where(ProjectExportPolicy.organization_id == org.id)
        )
        notifications = list(
            db.session.scalars(
                select(NotificationOutbox)
                .where(NotificationOutbox.organization_id == org.id)
                .order_by(NotificationOutbox.created_at.desc())
                .limit(50)
            )
        )
        heartbeats = list(db.session.scalars(select(NotificationWorkerHeartbeat)))
        business_days = list(
            db.session.scalars(
                select(OrganizationBusinessDayOverride)
                .where(OrganizationBusinessDayOverride.organization_id == org.id)
                .order_by(OrganizationBusinessDayOverride.calendar_date.desc())
                .limit(200)
            )
        )
    return render_template(
        "admin/customer_projects.html",
        organization=org,
        membership_rows=rows,
        role_codes=sorted(ROLE_CODES),
        reminder_policy=policy,
        export_policy=export_policy,
        default_export_roles=DEFAULT_EXPORT_ROLES,
        notification_rows=notifications,
        notification_heartbeats=heartbeats,
        business_days=business_days,
    )


@admin_bp.post("/customer-projects/bootstrap")
@admin_required
def customer_projects_bootstrap():
    org = bootstrap_organization(
        request.form.get("name", "").strip() or "默认业务组织", current_user.id
    )
    flash(f"组织“{org.name}”及默认阶段已准备完成。", "success")
    return redirect(url_for("admin.customer_projects_settings"))


@admin_bp.post("/customer-projects/business-calendar")
@admin_required
def customer_projects_business_calendar_update():
    org = db.session.scalar(select(Organization).order_by(Organization.created_at).limit(1))
    if org is None:
        flash("请先初始化客户项目组织。", "danger")
        return redirect(url_for("admin.customer_projects_settings"))
    try:
        calendar_date = date.fromisoformat(request.form.get("calendar_date", ""))
        day_type = request.form.get("day_type")
        if day_type not in {"working", "holiday"}:
            raise BusinessCalendarError("请选择工作日或休息日。")
        row = upsert_business_day_override(
            org.id, calendar_date, day_type == "working", request.form.get("label", ""), current_user.id
        )
        policy = ensure_default_policy(org.id)
        policy.version += 1
        cancelled = cancel_pending_notifications_for_organization("customer_projects", org.id)
        add_audit(
            org.id,
            "organization_business_day",
            row.id,
            "upserted",
            current_user.id,
            {"calendar_date": row.calendar_date.isoformat(), "is_working_day": row.is_working_day, "calendar_version": row.version, "reminder_policy_version": policy.version, "cancelled_pending": cancelled},
        )
        db.session.commit()
        flash("组织工作日日历已保存，未发送旧提醒已取消。", "success")
    except (ValueError, BusinessCalendarError):
        db.session.rollback()
        flash("日历日期或配置无效，未保存。", "danger")
    return redirect(url_for("admin.customer_projects_settings"))


@admin_bp.post("/customer-projects/business-calendar/<string:override_id>/delete")
@admin_required
def customer_projects_business_calendar_delete(override_id: str):
    org = db.session.scalar(select(Organization).order_by(Organization.created_at).limit(1))
    row = db.session.get(OrganizationBusinessDayOverride, override_id)
    if org is None or row is None or row.organization_id != org.id:
        flash("日历覆盖不存在。", "danger")
        return redirect(url_for("admin.customer_projects_settings"))
    try:
        expected_version = int(request.form.get("version", "0"))
    except ValueError:
        expected_version = 0
    if expected_version != row.version:
        flash("日历覆盖已被其他管理员更新，请刷新后重试。", "warning")
        return redirect(url_for("admin.customer_projects_settings"))
    safe_date = row.calendar_date.isoformat()
    db.session.delete(row)
    policy = ensure_default_policy(org.id)
    policy.version += 1
    cancelled = cancel_pending_notifications_for_organization("customer_projects", org.id)
    add_audit(
        org.id,
        "organization_business_day",
        override_id,
        "deleted",
        current_user.id,
        {"calendar_date": safe_date, "reminder_policy_version": policy.version, "cancelled_pending": cancelled},
    )
    db.session.commit()
    flash("日历覆盖已删除，该日期恢复普通周历规则。", "success")
    return redirect(url_for("admin.customer_projects_settings"))


@admin_bp.post("/customer-projects/members/<int:user_id>")
@admin_required
def customer_projects_member_update(user_id: int):
    org = db.session.scalar(select(Organization).order_by(Organization.created_at).limit(1))
    user = db.session.get(User, user_id)
    if org is None or user is None:
        flash("组织或用户不存在。", "danger")
        return redirect(url_for("admin.customer_projects_settings"))
    requested = set(request.form.getlist("roles"))
    invalid = requested - ROLE_CODES
    if invalid:
        flash("包含无效角色，未保存。", "danger")
        return redirect(url_for("admin.customer_projects_settings"))
    membership = db.session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        membership = OrganizationMembership(organization_id=org.id, user_id=user.id)
        db.session.add(membership)
    membership.set_roles(requested)
    membership.status = "active" if request.form.get("status") == "active" else "inactive"
    seed_default_statuses(org.id)
    add_audit(
        org.id,
        "organization_membership",
        membership.id,
        "roles_updated",
        current_user.id,
        {"user_id": user.id, "roles": sorted(requested), "status": membership.status},
    )
    db.session.commit()
    flash(f"{user.display_name} 的客户项目权限已更新。", "success")
    return redirect(url_for("admin.customer_projects_settings"))


@admin_bp.post("/customer-projects/export-policy")
@admin_required
def customer_projects_export_policy_update():
    org = db.session.scalar(select(Organization).order_by(Organization.created_at).limit(1))
    if org is None:
        flash("请先初始化客户项目组织。", "danger")
        return redirect(url_for("admin.customer_projects_settings"))
    requested_roles = set(request.form.getlist("allowed_roles"))
    if requested_roles - ROLE_CODES:
        flash("导出策略包含无效角色，未保存。", "danger")
        return redirect(url_for("admin.customer_projects_settings"))
    try:
        max_projects = int(request.form.get("max_projects", "2000"))
        max_rows = int(request.form.get("max_rows", "20000"))
        if not 1 <= max_projects <= 10000 or not 1 <= max_rows <= 100000:
            raise ValueError
        if max_rows < max_projects:
            raise ValueError
        policy = ensure_default_export_policy(org.id)
        policy.set_allowed_roles(requested_roles)
        policy.include_prices = request.form.get("include_prices") == "on"
        policy.max_projects = max_projects
        policy.max_rows = max_rows
        policy.version += 1
        add_audit(
            org.id,
            "project_export_policy",
            policy.id,
            "updated",
            current_user.id,
            {
                "allowed_roles": sorted(requested_roles),
                "include_prices": policy.include_prices,
                "max_projects": max_projects,
                "max_rows": max_rows,
                "version": policy.version,
            },
        )
        db.session.commit()
        flash("受控导出策略已保存。", "success")
    except ValueError:
        db.session.rollback()
        flash("导出上限无效：项目数 1-10000，行数 1-100000，且行数不得小于项目数。", "danger")
    return redirect(url_for("admin.customer_projects_settings"))


@admin_bp.post("/customer-projects/reminder-policy")
@admin_required
def customer_projects_reminder_policy_update():
    org = db.session.scalar(select(Organization).order_by(Organization.created_at).limit(1))
    if org is None:
        flash("请先初始化客户项目组织。", "danger")
        return redirect(url_for("admin.customer_projects_settings"))
    try:
        policy = ensure_default_policy(org.id)
        policy.is_enabled = request.form.get("is_enabled") == "on"
        policy.due_hour_local = max(0, min(int(request.form.get("due_hour_local", "9")), 23))
        policy.pre_due_workdays = max(0, min(int(request.form.get("pre_due_workdays", "1")), 10))
        policy.overdue_workdays = max(0, min(int(request.form.get("overdue_workdays", "1")), 10))
        policy.stale_manager_after_workdays = max(1, min(int(request.form.get("stale_manager_after_workdays", "3")), 30))
        policy.daily_limit = max(1, min(int(request.form.get("daily_limit", "500")), 5000))
        policy.include_pm = request.form.get("include_pm") == "on"
        policy.include_fae = request.form.get("include_fae") == "on"
        policy.version += 1
        cancelled = cancel_pending_notifications_for_organization(
            "customer_projects", org.id
        )
        add_audit(
            org.id,
            "project_reminder_policy",
            policy.id,
            "updated",
            current_user.id,
            {"enabled": policy.is_enabled, "version": policy.version, "daily_limit": policy.daily_limit, "cancelled_pending": cancelled},
        )
        db.session.commit()
        flash("提醒策略已保存。启用真实邮件仍需环境开关和 SMTP 配置。", "success")
    except ValueError:
        db.session.rollback()
        flash("提醒策略包含无效数字。", "danger")
    return redirect(url_for("admin.customer_projects_settings"))
