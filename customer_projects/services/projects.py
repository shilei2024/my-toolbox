"""Transactional customer/project operations and business rules."""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from flask import g
from sqlalchemy import func, select, update

from customer_projects.models import (
    Customer,
    CustomerContact,
    CustomerProject,
    MaterialCompetitor,
    ProjectActivity,
    ProjectMaterial,
    ProjectMember,
    ProjectStageEvent,
    ProjectStatusCatalog,
)
from extensions import db
from shared.models import AuditEvent, Organization, OrganizationMembership

ACTIVE_STAGES = (
    "evaluation",
    "initiated",
    "sampling",
    "pilot_batch",
    "trial_production",
    "design_win",
)
TERMINAL_STAGES = frozenset({"mass_production", "lost", "archived"})
ALL_STAGES = frozenset((*ACTIVE_STAGES, "mass_production", "paused", "lost", "archived"))
DEFAULT_STATUSES = (
    ("evaluation", "评估", 10, 14, "active"),
    ("initiated", "立项", 20, 14, "active"),
    ("sampling", "送样/验证", 30, 10, "active"),
    ("pilot_batch", "小批", 40, 14, "active"),
    ("trial_production", "试产", 50, 14, "active"),
    ("design_win", "定点", 60, 30, "active"),
    ("mass_production", "量产", 70, None, "terminal"),
    ("paused", "暂停", 80, None, "auxiliary"),
    ("lost", "失败", 90, None, "terminal"),
    ("archived", "归档", 100, None, "terminal"),
)
ROLE_CODES = frozenset({"organization_admin", "business_manager", "sales", "pm", "fae", "readonly"})


class DomainError(ValueError):
    def __init__(self, code: str, message: str, *, field_errors: dict[str, str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_errors = field_errors or {}


class VersionConflict(DomainError):
    def __init__(self, current_version: int):
        super().__init__("PROJECT_VERSION_CONFLICT", "项目已被其他成员更新，请刷新后重试。")
        self.current_version = current_version


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    return re.sub(r"\s+", "", normalized)


def normalize_mpn(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return re.sub(r"[\s_-]+", "", unicodedata.normalize("NFKC", value).upper())


def parse_datetime(value: str | datetime, timezone_name: str = "Asia/Shanghai") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise DomainError("INVALID_DATETIME", "日期时间格式不正确。") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def parse_date(value: str | date | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DomainError("INVALID_DATE", "日期格式不正确。") from exc


def seed_default_statuses(organization_id: str) -> None:
    existing = set(
        db.session.scalars(
            select(ProjectStatusCatalog.code).where(
                ProjectStatusCatalog.organization_id == organization_id
            )
        )
    )
    for code, label, order, stale_days, status_type in DEFAULT_STATUSES:
        if code not in existing:
            db.session.add(
                ProjectStatusCatalog(
                    organization_id=organization_id,
                    code=code,
                    display_name=label,
                    sort_order=order,
                    stale_after_days=stale_days,
                    status_type=status_type,
                )
            )


def bootstrap_organization(name: str, admin_user_id: int) -> Organization:
    org = db.session.scalar(select(Organization).order_by(Organization.created_at.asc()).limit(1))
    if org is None:
        org = Organization(name=name or "默认业务组织")
        db.session.add(org)
        db.session.flush()
    membership = db.session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == admin_user_id,
        )
    )
    if membership is None:
        membership = OrganizationMembership(organization_id=org.id, user_id=admin_user_id)
        membership.set_roles(["organization_admin"])
        db.session.add(membership)
    else:
        membership.status = "active"
        membership.set_roles(set(membership.roles) | {"organization_admin"})
    seed_default_statuses(org.id)
    db.session.commit()
    return org


def add_audit(
    organization_id: str,
    object_type: str,
    object_id: str,
    action: str,
    actor_user_id: int,
    safe_diff: dict[str, Any],
) -> None:
    event = AuditEvent(
        organization_id=organization_id,
        object_type=object_type,
        object_id=object_id,
        action=action,
        actor_user_id=actor_user_id,
        request_id=getattr(g, "request_id", None),
    )
    event.set_safe_diff(safe_diff)
    db.session.add(event)


def create_customer(data: dict[str, Any], membership: OrganizationMembership) -> Customer:
    name = str(data.get("name", "")).strip()
    if not name:
        raise DomainError("VALIDATION_ERROR", "请填写客户名称。", field_errors={"name": "必填"})
    customer = Customer(
        organization_id=membership.organization_id,
        name=name[:255],
        normalized_name=normalize_name(name)[:255],
        short_name=str(data.get("short_name") or "").strip()[:120] or None,
        industry=str(data.get("industry") or "").strip()[:120] or None,
        region=str(data.get("region") or "").strip()[:120] or None,
        primary_owner_user_id=int(data.get("primary_owner_user_id") or membership.user_id),
        notes=str(data.get("notes") or "").strip()[:4000] or None,
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    db.session.add(customer)
    db.session.flush()
    add_audit(customer.organization_id, "customer", customer.id, "created", membership.user_id, {"name": customer.name})
    return customer


def add_contact(customer: Customer, data: dict[str, Any], membership: OrganizationMembership) -> CustomerContact:
    name = str(data.get("name") or "").strip()
    if not name:
        raise DomainError("VALIDATION_ERROR", "联系人姓名必填。", field_errors={"name": "必填"})
    contact = CustomerContact(
        organization_id=membership.organization_id,
        customer_id=customer.id,
        name=name[:120],
        department=str(data.get("department") or "").strip()[:120] or None,
        title=str(data.get("title") or "").strip()[:120] or None,
        email=str(data.get("email") or "").strip()[:255] or None,
        phone=str(data.get("phone") or "").strip()[:64] or None,
        is_primary=bool(data.get("is_primary")),
        notes=str(data.get("notes") or "").strip()[:4000] or None,
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    db.session.add(contact)
    db.session.flush()
    add_audit(customer.organization_id, "customer_contact", contact.id, "created", membership.user_id, {"name": contact.name, "contact_fields": "已保存并脱敏审计"})
    return contact


def _project_id_for_key(organization_id: str, idempotency_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"customer-project:{organization_id}:{idempotency_key}"))


def create_project(data: dict[str, Any], membership: OrganizationMembership, idempotency_key: str) -> CustomerProject:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    project_id = _project_id_for_key(membership.organization_id, idempotency_key)
    existing = db.session.get(CustomerProject, project_id)
    if existing is not None:
        if (
            existing.name != str(data.get("name", "")).strip()
            or existing.customer_id != str(data.get("customer_id", "")).strip()
        ):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的项目请求。")
        return existing

    fields: dict[str, str] = {}
    name = str(data.get("name", "")).strip()
    customer_id = str(data.get("customer_id", "")).strip()
    stage = str(data.get("stage_code") or "evaluation")
    next_action = str(data.get("next_action", "")).strip()
    if not name:
        fields["name"] = "必填"
    if not customer_id:
        fields["customer_id"] = "必填"
    if stage not in ACTIVE_STAGES:
        fields["stage_code"] = "无效阶段"
    if not next_action:
        fields["next_action"] = "必填"
    if not data.get("next_follow_up_at"):
        fields["next_follow_up_at"] = "必填"
    if fields:
        raise DomainError("VALIDATION_ERROR", "请检查必填字段。", field_errors=fields)
    customer = db.session.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == membership.organization_id,
            Customer.deleted_at.is_(None),
        )
    )
    if customer is None:
        raise DomainError("CUSTOMER_NOT_FOUND", "客户不存在或不可访问。")
    owner_id = int(data.get("primary_sales_user_id") or membership.user_id)
    owner_membership = db.session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == membership.organization_id,
            OrganizationMembership.user_id == owner_id,
            OrganizationMembership.status == "active",
        )
    )
    if owner_membership is None or not owner_membership.roles.intersection(
        {"organization_admin", "business_manager", "sales"}
    ):
        raise DomainError("INVALID_OWNER", "主业务不是当前组织的有效成员。")
    org = db.session.get(Organization, membership.organization_id)
    follow_up = parse_datetime(str(data["next_follow_up_at"]), org.timezone if org else "Asia/Shanghai")
    now = datetime.now(timezone.utc)
    code = f"CP-{now.year}-{project_id.replace('-', '')[:8].upper()}"
    grade = str(data.get("assessment_grade") or "").upper()[:1]
    if grade and grade not in {"A", "B", "C", "D"}:
        raise DomainError("VALIDATION_ERROR", "评估等级无效。", field_errors={"assessment_grade": "仅支持 A/B/C/D"})
    probability = int(data["probability_band"]) if data.get("probability_band") else None
    if probability is not None and probability not in {10, 30, 50, 70, 90}:
        raise DomainError("VALIDATION_ERROR", "成功概率区间无效。")
    project = CustomerProject(
        id=project_id,
        organization_id=membership.organization_id,
        project_code=code,
        customer_id=customer.id,
        name=name[:255],
        normalized_name=normalize_name(name)[:255],
        stage_code=stage,
        assessment_grade=grade or None,
        probability_band=probability,
        primary_sales_user_id=owner_id,
        next_action=next_action[:500],
        next_follow_up_at=follow_up,
        last_meaningful_update_at=now,
        expected_design_win_at=parse_date(data.get("expected_design_win_at")),
        expected_mass_production_at=parse_date(data.get("expected_mass_production_at")),
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    db.session.add(project)
    db.session.flush()
    db.session.add(
        ProjectMember(
            organization_id=membership.organization_id,
            project_id=project.id,
            user_id=owner_id,
            role_code="sales",
            is_primary=True,
        )
    )
    db.session.add(
        ProjectStageEvent(
            organization_id=membership.organization_id,
            project_id=project.id,
            from_stage_code=None,
            to_stage_code=stage,
            reason="创建项目",
            idempotency_key=f"create:{idempotency_key}",
            actor_user_id=membership.user_id,
        )
    )
    add_audit(project.organization_id, "project", project.id, "created", membership.user_id, {"project_code": code, "stage_code": stage})
    return project


def update_project(project: CustomerProject, data: dict[str, Any], membership: OrganizationMembership, expected_version: int) -> CustomerProject:
    values: dict[str, Any] = {"updated_by_user_id": membership.user_id, "version": expected_version + 1, "updated_at": datetime.now(timezone.utc)}
    safe_diff: dict[str, Any] = {}
    for field, limit in (("name", 255), ("next_action", 500)):
        if field in data:
            value = str(data[field]).strip()
            if not value:
                raise DomainError("VALIDATION_ERROR", f"{field} 不能为空。", field_errors={field: "必填"})
            values[field] = value[:limit]
            safe_diff[field] = "已变更"
            if field == "name":
                values["normalized_name"] = normalize_name(value)[:255]
    if "assessment_grade" in data:
        grade = str(data.get("assessment_grade") or "").upper()
        if grade and grade not in {"A", "B", "C", "D"}:
            raise DomainError("VALIDATION_ERROR", "评估等级无效。", field_errors={"assessment_grade": "仅支持 A/B/C/D"})
        values["assessment_grade"] = grade or None
        safe_diff["assessment_grade"] = grade or None
    if "next_follow_up_at" in data:
        org = db.session.get(Organization, membership.organization_id)
        values["next_follow_up_at"] = parse_datetime(data["next_follow_up_at"], org.timezone if org else "Asia/Shanghai")
        safe_diff["next_follow_up_at"] = str(values["next_follow_up_at"])
    result = db.session.execute(
        update(CustomerProject)
        .where(
            CustomerProject.id == project.id,
            CustomerProject.organization_id == membership.organization_id,
            CustomerProject.version == expected_version,
            CustomerProject.deleted_at.is_(None),
        )
        .values(**values)
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(CustomerProject, project.id)
        raise VersionConflict(current.version if current else expected_version)
    add_audit(project.organization_id, "project", project.id, "updated", membership.user_id, safe_diff)
    db.session.flush()
    return db.session.get(CustomerProject, project.id)


def add_activity(project: CustomerProject, data: dict[str, Any], membership: OrganizationMembership, idempotency_key: str) -> ProjectActivity:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    existing = db.session.scalar(
        select(ProjectActivity).where(
            ProjectActivity.project_id == project.id,
            ProjectActivity.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if (
            existing.summary != str(data.get("summary", "")).strip()
            or existing.next_action != str(data.get("next_action", "")).strip()
        ):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的跟进请求。")
        return existing
    expected_version = int(data.get("project_version") or 0)
    if expected_version != project.version:
        raise VersionConflict(project.version)
    summary = str(data.get("summary", "")).strip()
    next_action = str(data.get("next_action", "")).strip()
    if not summary or not next_action or not data.get("next_follow_up_at"):
        raise DomainError("VALIDATION_ERROR", "摘要、下一步和跟进时间均为必填。")
    org = db.session.get(Organization, membership.organization_id)
    tz_name = org.timezone if org else "Asia/Shanghai"
    occurred_at = parse_datetime(data.get("occurred_at") or datetime.now(timezone.utc), tz_name)
    next_follow_up = parse_datetime(data["next_follow_up_at"], tz_name)
    meaningful = bool(data.get("is_meaningful", True))
    activity = ProjectActivity(
        organization_id=membership.organization_id,
        project_id=project.id,
        activity_type=str(data.get("activity_type") or "other")[:32],
        occurred_at=occurred_at,
        summary=summary[:500],
        details=str(data.get("details") or "").strip()[:8000] or None,
        customer_feedback=str(data.get("customer_feedback") or "").strip()[:4000] or None,
        risk=str(data.get("risk") or "").strip()[:4000] or None,
        decision=str(data.get("decision") or "").strip()[:4000] or None,
        next_action=next_action[:500],
        next_follow_up_at=next_follow_up,
        is_meaningful=meaningful,
        idempotency_key=idempotency_key,
        created_by_user_id=membership.user_id,
    )
    result = db.session.execute(
        update(CustomerProject)
        .where(CustomerProject.id == project.id, CustomerProject.version == expected_version)
        .values(
            next_action=next_action[:500],
            next_follow_up_at=next_follow_up,
            last_meaningful_update_at=occurred_at if meaningful else project.last_meaningful_update_at,
            version=expected_version + 1,
            updated_by_user_id=membership.user_id,
            updated_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(CustomerProject, project.id)
        raise VersionConflict(current.version if current else expected_version)
    db.session.add(activity)
    add_audit(project.organization_id, "project", project.id, "activity_added", membership.user_id, {"activity_type": activity.activity_type, "is_meaningful": meaningful})
    return activity


def transition_stage(project: CustomerProject, data: dict[str, Any], membership: OrganizationMembership, idempotency_key: str) -> ProjectStageEvent:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    existing = db.session.scalar(
        select(ProjectStageEvent).where(
            ProjectStageEvent.project_id == project.id,
            ProjectStageEvent.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.to_stage_code != str(data.get("to_stage_code") or ""):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的阶段请求。")
        return existing
    expected_version = int(data.get("project_version") or 0)
    if expected_version != project.version:
        raise VersionConflict(project.version)
    target = str(data.get("to_stage_code") or "")
    reason = str(data.get("reason") or "").strip()
    if target not in ALL_STAGES or target == project.stage_code:
        raise DomainError("INVALID_STAGE_TRANSITION", "目标阶段无效或与当前阶段相同。")
    if project.stage_code in TERMINAL_STAGES | {"paused"} and target in ACTIVE_STAGES:
        raise DomainError("REACTIVATION_REQUIRED", "终态或暂停项目必须使用重新激活流程。")
    if target in {"mass_production", "lost"} and not membership.roles.intersection(
        {"organization_admin", "business_manager"}
    ):
        raise DomainError("APPROVAL_REQUIRED", "量产或失败需要业务经理或组织管理员确认。")
    if not reason:
        raise DomainError("VALIDATION_ERROR", "阶段变更原因必填。", field_errors={"reason": "必填"})
    values: dict[str, Any] = {"stage_code": target, "version": expected_version + 1, "updated_by_user_id": membership.user_id, "updated_at": datetime.now(timezone.utc)}
    if target == "mass_production":
        material_count = db.session.scalar(select(func.count()).select_from(ProjectMaterial).where(ProjectMaterial.project_id == project.id, ProjectMaterial.deleted_at.is_(None))) or 0
        production_date = parse_date(data.get("actual_mass_production_at") or data.get("expected_mass_production_at"))
        if material_count < 1 or production_date is None or not str(data.get("close_notes") or "").strip():
            raise DomainError("MASS_PRODUCTION_REQUIREMENTS", "量产需要至少一条物料、量产日期和结果说明。")
        values["actual_mass_production_at"] = production_date
        values["close_notes"] = str(data["close_notes"]).strip()[:8000]
    elif target == "lost":
        code = str(data.get("close_reason_code") or "").strip()
        notes = str(data.get("close_notes") or "").strip()
        if not code or not notes:
            raise DomainError("LOST_REQUIREMENTS", "失败原因和复盘说明必填。")
        values["close_reason_code"] = code[:64]
        values["close_notes"] = notes[:8000]
    elif target == "paused":
        pause_reason = str(data.get("pause_reason") or "").strip()
        if not pause_reason:
            raise DomainError("PAUSE_REQUIREMENTS", "暂停原因必填。")
        values["pause_reason"] = pause_reason[:8000]
        values["paused_until"] = parse_date(data.get("paused_until"))
    from_stage = project.stage_code
    result = db.session.execute(
        update(CustomerProject)
        .where(CustomerProject.id == project.id, CustomerProject.version == expected_version)
        .values(**values)
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(CustomerProject, project.id)
        raise VersionConflict(current.version if current else expected_version)
    event = ProjectStageEvent(
        organization_id=membership.organization_id,
        project_id=project.id,
        from_stage_code=from_stage,
        to_stage_code=target,
        reason=reason[:8000],
        idempotency_key=idempotency_key,
        actor_user_id=membership.user_id,
        approved_by_user_id=membership.user_id if membership.roles.intersection({"organization_admin", "business_manager"}) else None,
    )
    db.session.add(event)
    add_audit(project.organization_id, "project", project.id, "stage_changed", membership.user_id, {"from": from_stage, "to": target})
    return event


def add_material(
    project: CustomerProject,
    data: dict[str, Any],
    membership: OrganizationMembership,
    idempotency_key: str,
) -> ProjectMaterial:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    existing = db.session.scalar(
        select(ProjectMaterial).where(
            ProjectMaterial.project_id == project.id,
            ProjectMaterial.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if (
            existing.promoted_brand != str(data.get("promoted_brand") or "").strip()
            or (existing.promoted_mpn or "") != str(data.get("promoted_mpn") or "").strip()
        ):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的物料请求。")
        return existing
    brand = str(data.get("promoted_brand") or "").strip()
    mpn = str(data.get("promoted_mpn") or "").strip()
    pending = bool(data.get("mpn_pending"))
    if not brand or (not mpn and not pending):
        raise DomainError("VALIDATION_ERROR", "推广品牌必填；推广型号或“型号待确认”至少填写一项。")
    material = ProjectMaterial(
        organization_id=membership.organization_id,
        project_id=project.id,
        category_code=str(data.get("category_code") or "").strip()[:64] or None,
        promoted_brand=brand[:120],
        promoted_mpn=mpn[:160] or None,
        normalized_mpn=normalize_mpn(mpn),
        mpn_pending=pending,
        application_position=str(data.get("application_position") or "").strip()[:255] or None,
        technical_status=str(data.get("technical_status") or "").strip()[:64] or None,
        commercial_status=str(data.get("commercial_status") or "").strip()[:64] or None,
        is_primary=bool(data.get("is_primary")),
        idempotency_key=idempotency_key,
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    db.session.add(material)
    db.session.flush()
    add_audit(project.organization_id, "material", material.id, "created", membership.user_id, {"brand": brand, "mpn": mpn or "待确认"})
    return material


def add_competitor(
    material: ProjectMaterial,
    data: dict[str, Any],
    membership: OrganizationMembership,
    idempotency_key: str,
) -> MaterialCompetitor:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    existing = db.session.scalar(
        select(MaterialCompetitor).where(
            MaterialCompetitor.project_material_id == material.id,
            MaterialCompetitor.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if (
            (existing.brand or "") != str(data.get("brand") or "").strip()
            or (existing.mpn or "") != str(data.get("mpn") or "").strip()
        ):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的竞争方案请求。")
        return existing
    brand = str(data.get("brand") or "").strip()
    mpn = str(data.get("mpn") or "").strip()
    distributor = str(data.get("distributor") or "").strip()
    pending = bool(data.get("model_pending"))
    if not any((brand, mpn, distributor, pending)):
        raise DomainError("VALIDATION_ERROR", "品牌、型号、代理商至少填写一项，或标记型号待确认。")
    competitor = MaterialCompetitor(
        organization_id=membership.organization_id,
        project_material_id=material.id,
        brand=brand[:120] or None,
        mpn=mpn[:160] or None,
        normalized_mpn=normalize_mpn(mpn),
        distributor=distributor[:160] or None,
        model_pending=pending,
        incumbent_status=str(data.get("incumbent_status") or "").strip()[:64] or None,
        strengths=str(data.get("strengths") or "").strip()[:4000] or None,
        weaknesses=str(data.get("weaknesses") or "").strip()[:4000] or None,
        confidence_level=str(data.get("confidence_level") or "").strip()[:32] or None,
        observed_at=parse_date(data.get("observed_at")),
        idempotency_key=idempotency_key,
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    db.session.add(competitor)
    db.session.flush()
    add_audit(membership.organization_id, "competitor", competitor.id, "created", membership.user_id, {"brand": brand or "待确认", "mpn": mpn or "待确认"})
    return competitor


def add_project_member(project: CustomerProject, user_id: int, role_code: str, membership: OrganizationMembership) -> ProjectMember:
    if role_code not in {"sales", "pm", "fae", "observer"}:
        raise DomainError("VALIDATION_ERROR", "项目职责无效。")
    active_member = db.session.scalar(
        select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == membership.organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == "active",
        )
    )
    if active_member is None:
        raise DomainError("INVALID_MEMBER", "该用户不是当前组织的有效成员。")
    existing = db.session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
            ProjectMember.role_code == role_code,
        )
    )
    if existing:
        existing.left_at = None
        return existing
    project_member = ProjectMember(
        organization_id=membership.organization_id,
        project_id=project.id,
        user_id=user_id,
        role_code=role_code,
        is_primary=False,
    )
    db.session.add(project_member)
    db.session.flush()
    add_audit(project.organization_id, "project", project.id, "member_added", membership.user_id, {"user_id": user_id, "role_code": role_code})
    return project_member


def soft_delete_project(project: CustomerProject, reason: str, membership: OrganizationMembership, expected_version: int) -> None:
    reason = reason.strip()
    if not reason:
        raise DomainError("VALIDATION_ERROR", "删除原因必填。", field_errors={"delete_reason": "必填"})
    result = db.session.execute(
        update(CustomerProject)
        .where(
            CustomerProject.id == project.id,
            CustomerProject.organization_id == membership.organization_id,
            CustomerProject.version == expected_version,
            CustomerProject.deleted_at.is_(None),
        )
        .values(
            deleted_at=datetime.now(timezone.utc),
            deleted_by_user_id=membership.user_id,
            delete_reason=reason[:500],
            version=expected_version + 1,
            updated_by_user_id=membership.user_id,
            updated_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(CustomerProject, project.id)
        raise VersionConflict(current.version if current else expected_version)
    add_audit(project.organization_id, "project", project.id, "soft_deleted", membership.user_id, {"reason": reason[:500]})


def restore_project(project: CustomerProject, membership: OrganizationMembership) -> None:
    if project.organization_id != membership.organization_id or project.deleted_at is None:
        raise DomainError("NOT_FOUND", "回收站项目不存在。")
    project.deleted_at = None
    project.deleted_by_user_id = None
    project.delete_reason = None
    project.version += 1
    project.updated_by_user_id = membership.user_id
    add_audit(project.organization_id, "project", project.id, "restored", membership.user_id, {})
