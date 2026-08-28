"""Customer-project reminder rules that emit provider-neutral outbox intents."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from customer_projects.models import (
    Customer,
    CustomerProject,
    ProjectMember,
    ProjectReminderOverride,
    ProjectReminderPolicy,
    ProjectStatusCatalog,
)
from extensions import db
from models import User
from shared.models import (
    NotificationDelivery,
    NotificationOutbox,
    NotificationWorkerHeartbeat,
    Organization,
    OrganizationMembership,
)
from shared.business_calendar import add_workdays, load_business_day_overrides

ACTIVE_STAGES = ("evaluation", "initiated", "sampling", "pilot_batch", "trial_production", "design_win")
REMINDER_LABELS = {
    "followup_pre_due": "跟进即将到期",
    "followup_due": "跟进今天到期",
    "followup_overdue": "跟进已逾期",
    "stale_primary": "项目长期未更新",
    "stale_manager": "项目严重停滞升级",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _local_schedule(day: date, hour: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(hour=max(0, min(hour, 23))), tzinfo=tz).astimezone(timezone.utc)


def ensure_default_policy(organization_id: str) -> ProjectReminderPolicy:
    policy = db.session.scalar(
        select(ProjectReminderPolicy).where(ProjectReminderPolicy.organization_id == organization_id)
    )
    if policy is None:
        policy = ProjectReminderPolicy(organization_id=organization_id, is_enabled=False)
        db.session.add(policy)
        db.session.flush()
    return policy


def _member_accepts_email(member: ProjectMember) -> bool:
    try:
        preferences = json.loads(member.notification_preferences_json or "{}")
    except (TypeError, ValueError):
        return True
    return not isinstance(preferences, dict) or preferences.get("email_enabled", True) is not False


def _recipient_users(project: CustomerProject, include_pm: bool, include_fae: bool, event_type: str) -> list[User]:
    user_ids = {project.primary_sales_user_id}
    included_roles = set()
    if include_pm:
        included_roles.add("pm")
    if include_fae:
        included_roles.add("fae")
    if included_roles:
        members = list(
            db.session.scalars(
                select(ProjectMember).where(
                    ProjectMember.organization_id == project.organization_id,
                    ProjectMember.project_id == project.id,
                    ProjectMember.role_code.in_(included_roles),
                    ProjectMember.left_at.is_(None),
                )
            )
        )
        user_ids.update(member.user_id for member in members if _member_accepts_email(member))
    if event_type == "stale_manager":
        manager_memberships = list(
            db.session.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == project.organization_id,
                    OrganizationMembership.status == "active",
                )
            )
        )
        user_ids.update(
            membership.user_id
            for membership in manager_memberships
            if membership.roles.intersection({"organization_admin", "business_manager"})
        )
    active_members = set(
        db.session.scalars(
            select(OrganizationMembership.user_id).where(
                OrganizationMembership.organization_id == project.organization_id,
                OrganizationMembership.status == "active",
                OrganizationMembership.user_id.in_(user_ids),
            )
        )
    )
    return list(
        db.session.scalars(
            select(User).where(
                User.id.in_(active_members),
                User.is_active_user.is_(True),
            ).order_by(User.id)
        )
    ) if active_members else []


def _emit(
    project: CustomerProject,
    policy: ProjectReminderPolicy,
    override_version: int,
    include_pm: bool,
    include_fae: bool,
    event_type: str,
    scheduled_for: datetime,
    cycle_key: str,
    now: datetime,
) -> bool:
    recipients = _recipient_users(project, include_pm, include_fae, event_type)
    if not recipients:
        return False
    raw_key = f"customer-projects:{project.id}:{event_type}:{cycle_key}:v{policy.version}:o{override_version}"
    key = "cp:" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    customer = db.session.get(Customer, project.customer_id)
    base_url = str(current_app.config.get("APP_BASE_URL", "")).rstrip("/")
    outbox = NotificationOutbox(
        organization_id=project.organization_id,
        module_code="customer_projects",
        event_type=event_type,
        object_type="project",
        object_id=project.id,
        idempotency_key=key,
        channel="email",
        template_code="customer_project_reminder_v1",
        scheduled_for=scheduled_for,
        next_attempt_at=now,
    )
    outbox.set_template_data(
        {
            "reminder_label": REMINDER_LABELS[event_type],
            "project_code": project.project_code,
            "project_name": project.name,
            "customer_name": customer.name if customer else "—",
            "stage_code": project.stage_code,
            "next_action": project.next_action,
            "next_follow_up_at": _aware(project.next_follow_up_at).isoformat(),
            "last_meaningful_update_at": _aware(project.last_meaningful_update_at).isoformat(),
            "project_url": f"{base_url}/customer-projects/projects/{project.id}",
        }
    )
    try:
        with db.session.begin_nested():
            db.session.add(outbox)
            db.session.flush()
            for user in recipients:
                db.session.add(
                    NotificationDelivery(
                        outbox_id=outbox.id,
                        recipient_user_id=user.id,
                        recipient_address=user.email,
                    )
                )
            db.session.flush()
    except IntegrityError:
        return False
    return True


def scan_project_reminders(now: datetime | None = None, organization_id: str | None = None) -> dict[str, int]:
    now = _aware(now or datetime.now(timezone.utc))
    heartbeat = db.session.get(NotificationWorkerHeartbeat, "customer-project-reminder-scan")
    if heartbeat is None:
        heartbeat = NotificationWorkerHeartbeat(worker_name="customer-project-reminder-scan")
        db.session.add(heartbeat)
    heartbeat.status = "running"
    heartbeat.last_started_at = now
    db.session.flush()

    org_query = select(Organization).where(Organization.status == "active")
    if organization_id:
        org_query = org_query.where(Organization.id == organization_id)
    organizations = list(db.session.scalars(org_query.order_by(Organization.id)))
    scanned = created = limited = 0
    retention_start = now - timedelta(days=14)
    for organization in organizations:
        policy = ensure_default_policy(organization.id)
        if not policy.is_enabled:
            continue
        tz = ZoneInfo(organization.timezone or "Asia/Shanghai")
        local_now = now.astimezone(tz)
        local_start = datetime.combine(local_now.date(), time.min, tzinfo=tz).astimezone(timezone.utc)
        created_today = db.session.scalar(
            select(func.count()).select_from(NotificationOutbox).where(
                NotificationOutbox.organization_id == organization.id,
                NotificationOutbox.module_code == "customer_projects",
                NotificationOutbox.created_at >= local_start,
            )
        ) or 0
        created_for_org = 0
        statuses = {
            row.code: row.stale_after_days
            for row in db.session.scalars(
                select(ProjectStatusCatalog).where(
                    ProjectStatusCatalog.organization_id == organization.id,
                    ProjectStatusCatalog.is_active.is_(True),
                )
            )
        }
        projects = list(
            db.session.scalars(
                select(CustomerProject).where(
                    CustomerProject.organization_id == organization.id,
                    CustomerProject.deleted_at.is_(None),
                    CustomerProject.stage_code.in_(ACTIVE_STAGES),
                )
            )
        )
        calendar_base_days: list[date] = []
        for project in projects:
            calendar_base_days.append(_aware(project.next_follow_up_at).astimezone(tz).date())
            stale_days = statuses.get(project.stage_code)
            if stale_days:
                calendar_base_days.append(
                    _aware(project.last_meaningful_update_at).astimezone(tz).date()
                    + timedelta(days=stale_days)
                )
        calendar_overrides = (
            load_business_day_overrides(
                organization.id,
                min(calendar_base_days) - timedelta(days=45),
                max(calendar_base_days) + timedelta(days=45),
            )
            if calendar_base_days
            else {}
        )
        for project in projects:
            scanned += 1
            override = db.session.scalar(
                select(ProjectReminderOverride).where(
                    ProjectReminderOverride.organization_id == organization.id,
                    ProjectReminderOverride.project_id == project.id,
                )
            )
            if override is not None and not override.is_enabled:
                continue
            include_pm = policy.include_pm if override is None or override.include_pm is None else override.include_pm
            include_fae = policy.include_fae if override is None or override.include_fae is None else override.include_fae
            followup_local = _aware(project.next_follow_up_at).astimezone(tz)
            due_day = followup_local.date()
            followup_events = (
                ("followup_pre_due", add_workdays(due_day, -policy.pre_due_workdays, calendar_overrides)),
                ("followup_due", due_day),
                ("followup_overdue", add_workdays(due_day, policy.overdue_workdays, calendar_overrides)),
            )
            stale_days = statuses.get(project.stage_code)
            candidates: list[tuple[str, datetime, str]] = []
            for event_type, day in followup_events:
                scheduled = _local_schedule(day, policy.due_hour_local, tz)
                candidates.append((event_type, scheduled, _aware(project.next_follow_up_at).isoformat()))
            if stale_days:
                stale_day = _aware(project.last_meaningful_update_at).astimezone(tz).date() + timedelta(days=stale_days)
                candidates.append(("stale_primary", _local_schedule(stale_day, policy.due_hour_local, tz), _aware(project.last_meaningful_update_at).isoformat()))
                manager_day = add_workdays(
                    stale_day, policy.stale_manager_after_workdays, calendar_overrides
                )
                candidates.append(("stale_manager", _local_schedule(manager_day, policy.due_hour_local, tz), _aware(project.last_meaningful_update_at).isoformat()))
            for event_type, scheduled, cycle_key in candidates:
                if scheduled > now or scheduled < retention_start:
                    continue
                if created_today + created_for_org >= policy.daily_limit:
                    limited += 1
                    continue
                if _emit(project, policy, override.version if override else 0, include_pm, include_fae, event_type, scheduled, cycle_key, now):
                    created += 1
                    created_for_org += 1
    heartbeat.status = "ok"
    heartbeat.last_completed_at = datetime.now(timezone.utc)
    heartbeat.scanned_count = scanned
    heartbeat.processed_count = created
    heartbeat.failed_count = limited
    heartbeat.last_error_code = "DAILY_LIMIT_REACHED" if limited else None
    db.session.commit()
    return {"scanned": scanned, "created": created, "limited": limited}
