"""Unified-admin configuration for customer project organizations and roles."""
from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select

from auth.decorators import admin_required
from customer_projects.models import ProjectReminderPolicy
from customer_projects.services.projects import ROLE_CODES, add_audit, bootstrap_organization, seed_default_statuses
from customer_projects.services.reminders import ensure_default_policy
from extensions import db
from models import User
from shared.models import NotificationOutbox, NotificationWorkerHeartbeat, Organization, OrganizationMembership
from shared.notifications import cancel_pending_notifications_for_organization

from . import admin_bp


@admin_bp.get("/customer-projects")
@admin_required
def customer_projects_settings():
    organizations = list(db.session.scalars(select(Organization).order_by(Organization.created_at)))
    org = organizations[0] if organizations else None
    rows = []
    policy = None
    notifications = []
    heartbeats = []
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
        notifications = list(
            db.session.scalars(
                select(NotificationOutbox)
                .where(NotificationOutbox.organization_id == org.id)
                .order_by(NotificationOutbox.created_at.desc())
                .limit(50)
            )
        )
        heartbeats = list(db.session.scalars(select(NotificationWorkerHeartbeat)))
    return render_template(
        "admin/customer_projects.html",
        organization=org,
        membership_rows=rows,
        role_codes=sorted(ROLE_CODES),
        reminder_policy=policy,
        notification_rows=notifications,
        notification_heartbeats=heartbeats,
    )


@admin_bp.post("/customer-projects/bootstrap")
@admin_required
def customer_projects_bootstrap():
    org = bootstrap_organization(
        request.form.get("name", "").strip() or "默认业务组织", current_user.id
    )
    flash(f"组织“{org.name}”及默认阶段已准备完成。", "success")
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
