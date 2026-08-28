"""Transactional customer/project operations and business rules."""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app, g
from sqlalchemy import func, select, update

from customer_projects.models import (
    Customer,
    CustomerContact,
    CustomerProject,
    MaterialCompetitor,
    ProjectActivity,
    ProjectComment,
    ProjectCommentMention,
    ProjectMaterial,
    ProjectMember,
    ProjectStageEvent,
    ProjectStatusCatalog,
)
from extensions import db
from shared.exchange_rates import ExchangeRateError, get_exchange_rate
from shared.models import AuditEvent, Organization, OrganizationMembership
from shared.notifications import cancel_pending_notifications

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
MATERIAL_OPPORTUNITY_TYPES = {
    "design_in": "Design In",
    "design_win": "Design Win",
    "matched_opportunity": "Evaluation",
    "competitive_opportunity": "Lost",
}
# Lost 机会仅记录竞品信息，不要求推广品牌/型号
LOST_OPPORTUNITY = "competitive_opportunity"


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


class ObjectVersionConflict(DomainError):
    def __init__(self, code: str, message: str, current_version: int):
        super().__init__(code, message)
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


def parse_nonnegative_decimal(value: Any, field: str, label: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(
            "VALIDATION_ERROR", f"{label}格式不正确。", field_errors={field: "请输入有效数字"}
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise DomainError(
            "VALIDATION_ERROR", f"{label}不能为负数。", field_errors={field: "不能为负数"}
        )
    return parsed


def parse_nonnegative_integer(value: Any, field: str, label: str) -> Decimal | None:
    parsed = parse_nonnegative_decimal(value, field, label)
    if parsed is None:
        return None
    if parsed != parsed.to_integral_value():
        raise DomainError(
            "VALIDATION_ERROR",
            f"{label}必须是整数。",
            field_errors={field: "请输入整数"},
        )
    return parsed.to_integral_value()


def parse_price(value: Any, field: str, label: str) -> Decimal | None:
    parsed = parse_nonnegative_decimal(value, field, label)
    if parsed is None:
        return None
    normalized = parsed.normalize() if parsed else Decimal("0")
    decimal_places = max(0, -normalized.as_tuple().exponent)
    if decimal_places > 5:
        raise DomainError(
            "VALIDATION_ERROR",
            f"{label}最多保留 5 位小数。",
            field_errors={field: "最多输入 5 位小数"},
        )
    return parsed.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def decimal_display(value: Decimal | None, max_places: int | None = None) -> str | None:
    if value is None:
        return None
    displayed = value
    if max_places is not None:
        displayed = displayed.quantize(
            Decimal(1).scaleb(-max_places), rounding=ROUND_HALF_UP
        )
    return format(displayed, "f").rstrip("0").rstrip(".") or "0"


def parse_positive_integer(value: Any, field: str, label: str) -> Decimal | None:
    parsed = parse_nonnegative_decimal(value, field, label)
    if parsed is None:
        return None
    if parsed <= 0 or parsed != parsed.to_integral_value():
        raise DomainError(
            "VALIDATION_ERROR",
            f"{label}必须是大于 0 的整数。",
            field_errors={field: "请输入大于 0 的整数"},
        )
    return parsed.to_integral_value()


def parse_opportunity_type(value: Any) -> str:
    opportunity_type = str(value or "design_in").strip()
    if opportunity_type not in MATERIAL_OPPORTUNITY_TYPES:
        raise DomainError(
            "VALIDATION_ERROR",
            "物料机会分类无效。",
            field_errors={"opportunity_type": "请选择有效分类"},
        )
    return opportunity_type


def material_annual_value_usd(
    annual_usage: Decimal | None,
    machine_quantity: Decimal | None,
    unit_price_usd: Decimal | None,
) -> Decimal | None:
    if annual_usage is None or machine_quantity is None or unit_price_usd is None:
        return None
    return (annual_usage * machine_quantity * unit_price_usd).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def competitor_reference_price(competitors: list[MaterialCompetitor]) -> Decimal | None:
    """取 Lost 物料下有效竞品的最高报价，作为市场容量估算单价。"""
    prices = [
        competitor.quoted_price
        for competitor in competitors
        if competitor.quoted_price is not None
    ]
    return max(prices) if prices else None


def build_market_scope(
    project: CustomerProject,
    materials: list[ProjectMaterial],
    competitors_by_material: dict[str, list[MaterialCompetitor]] | None = None,
) -> dict[str, Any]:
    """Build a non-overlapping TAM/SAM/SOM funnel from material opportunity classes.

    TAM = 四类机会合计（Lost 按竞品最高报价估算）；SAM = Design In + Design Win + Evaluation；
    SOM = Design In + Design Win。
    """
    competitors_by_material = competitors_by_material or {}
    category_totals = {key: Decimal("0.00") for key in MATERIAL_OPPORTUNITY_TYPES}
    material_values: dict[str, Decimal | None] = {}
    incomplete_material_ids: list[str] = []
    for material in materials:
        if material.opportunity_type == LOST_OPPORTUNITY:
            # Lost 物料没有推广单价，TAM 采用竞品最高报价
            value = material_annual_value_usd(
                project.annual_usage,
                material.machine_quantity,
                competitor_reference_price(competitors_by_material.get(material.id, [])),
            )
        else:
            value = material_annual_value_usd(
                project.annual_usage, material.machine_quantity, material.unit_price_usd
            )
        material_values[material.id] = value
        if value is None:
            incomplete_material_ids.append(material.id)
            continue
        category_totals[material.opportunity_type] += value
    design_in = category_totals["design_in"]
    design_win = category_totals["design_win"]
    matched = category_totals["matched_opportunity"]
    lost = category_totals["competitive_opportunity"]
    return {
        "tam_usd": design_in + design_win + matched + lost,
        "sam_usd": design_in + design_win + matched,
        "som_usd": design_in + design_win,
        "category_totals": category_totals,
        "material_values": material_values,
        "incomplete_material_ids": incomplete_material_ids,
    }


def parse_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def local_day_bounds(now: datetime, timezone_name: str) -> tuple[datetime, datetime]:
    """Return the current organization's local-day bounds as UTC datetimes."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        local_now = now.astimezone(ZoneInfo(timezone_name))
    except (KeyError, ValueError) as exc:
        raise DomainError("INVALID_TIMEZONE", "组织时区配置无效。") from exc
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc), (local_start + timedelta(days=1)).astimezone(
        timezone.utc
    )


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
    try:
        owner_id = int(data.get("primary_owner_user_id") or membership.user_id)
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_OWNER", "客户负责人无效。") from exc
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
        raise DomainError("INVALID_OWNER", "客户负责人不是当前组织的有效业务成员。")
    grade = str(data.get("grade") or "").upper().strip()
    if grade and grade not in {"A", "B", "C", "D"}:
        raise DomainError(
            "VALIDATION_ERROR", "客户评级无效。", field_errors={"grade": "仅支持 A/B/C/D"}
        )
    customer = Customer(
        organization_id=membership.organization_id,
        name=name[:255],
        normalized_name=normalize_name(name)[:255],
        short_name=str(data.get("short_name") or "").strip()[:120] or None,
        industry=str(data.get("industry") or "").strip()[:120] or None,
        region=str(data.get("region") or "").strip()[:120] or None,
        grade=grade or None,
        primary_owner_user_id=owner_id,
        notes=str(data.get("notes") or "").strip()[:4000] or None,
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    db.session.add(customer)
    db.session.flush()
    add_audit(customer.organization_id, "customer", customer.id, "created", membership.user_id, {"name": customer.name})
    return customer


def update_customer_grade(
    customer: Customer, grade_value: Any, membership: OrganizationMembership
) -> Customer:
    if customer.organization_id != membership.organization_id or customer.deleted_at is not None:
        raise DomainError("CUSTOMER_NOT_FOUND", "客户不存在或不可访问。")
    grade = str(grade_value or "").upper().strip()
    if grade and grade not in {"A", "B", "C", "D"}:
        raise DomainError(
            "VALIDATION_ERROR", "客户评级无效。", field_errors={"grade": "仅支持 A/B/C/D"}
        )
    customer.grade = grade or None
    customer.version += 1
    customer.updated_by_user_id = membership.user_id
    customer.updated_at = datetime.now(timezone.utc)
    add_audit(
        customer.organization_id,
        "customer",
        customer.id,
        "grade_updated",
        membership.user_id,
        {"grade": grade or None},
    )
    return customer


def add_contact(customer: Customer, data: dict[str, Any], membership: OrganizationMembership) -> CustomerContact:
    if customer.organization_id != membership.organization_id or customer.deleted_at is not None:
        raise DomainError("CUSTOMER_NOT_FOUND", "客户不存在或不可访问。")
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
            or (existing.product_name or "") != str(data.get("product_name", "")).strip()
            or existing.annual_usage
            != parse_positive_integer(data.get("annual_usage"), "annual_usage", "项目年用量")
            or existing.customer_id != str(data.get("customer_id", "")).strip()
        ):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的项目请求。")
        return existing

    fields: dict[str, str] = {}
    name = str(data.get("name", "")).strip()
    product_name = str(data.get("product_name", "")).strip()
    annual_usage = parse_positive_integer(data.get("annual_usage"), "annual_usage", "项目年用量")
    customer_id = str(data.get("customer_id", "")).strip()
    stage = str(data.get("stage_code") or "evaluation")
    next_action = str(data.get("next_action", "")).strip()
    if not name:
        fields["name"] = "必填"
    if not product_name:
        fields["product_name"] = "必填"
    if annual_usage in (None, Decimal("0")):
        fields["annual_usage"] = "必须大于 0"
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
    try:
        owner_id = int(data.get("primary_sales_user_id") or membership.user_id)
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_OWNER", "主业务无效。") from exc
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
        product_name=product_name[:255],
        annual_usage=annual_usage,
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
    for field, limit in (("name", 255), ("product_name", 255), ("next_action", 500)):
        if field in data:
            value = str(data[field]).strip()
            if not value:
                raise DomainError("VALIDATION_ERROR", f"{field} 不能为空。", field_errors={field: "必填"})
            values[field] = value[:limit]
            safe_diff[field] = "已变更"
            if field == "name":
                values["normalized_name"] = normalize_name(value)[:255]
    if "annual_usage" in data:
        annual_usage = parse_positive_integer(data.get("annual_usage"), "annual_usage", "项目年用量")
        if annual_usage in (None, Decimal("0")):
            raise DomainError(
                "VALIDATION_ERROR", "项目年用量必须大于 0。", field_errors={"annual_usage": "必须大于 0"}
            )
        values["annual_usage"] = annual_usage
        safe_diff["annual_usage"] = str(annual_usage)
    if "assessment_grade" in data:
        grade = str(data.get("assessment_grade") or "").upper()
        if grade and grade not in {"A", "B", "C", "D"}:
            raise DomainError("VALIDATION_ERROR", "评估等级无效。", field_errors={"assessment_grade": "仅支持 A/B/C/D"})
        values["assessment_grade"] = grade or None
        safe_diff["assessment_grade"] = grade or None
    if "probability_band" in data:
        raw_probability = data.get("probability_band")
        try:
            probability = int(raw_probability) if raw_probability not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise DomainError(
                "VALIDATION_ERROR",
                "成功概率区间无效。",
                field_errors={"probability_band": "仅支持 10/30/50/70/90"},
            ) from exc
        if probability is not None and probability not in {10, 30, 50, 70, 90}:
            raise DomainError(
                "VALIDATION_ERROR",
                "成功概率区间无效。",
                field_errors={"probability_band": "仅支持 10/30/50/70/90"},
            )
        values["probability_band"] = probability
        safe_diff["probability_band"] = probability
    if "next_follow_up_at" in data:
        org = db.session.get(Organization, membership.organization_id)
        values["next_follow_up_at"] = parse_datetime(data["next_follow_up_at"], org.timezone if org else "Asia/Shanghai")
        safe_diff["next_follow_up_at"] = str(values["next_follow_up_at"])
    for field in ("expected_design_win_at", "expected_mass_production_at"):
        if field in data:
            values[field] = parse_date(data.get(field))
            safe_diff[field] = str(values[field]) if values[field] else None
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
    if "next_follow_up_at" in data:
        cancel_pending_notifications("customer_projects", "project", project.id)
    add_audit(project.organization_id, "project", project.id, "updated", membership.user_id, safe_diff)
    db.session.flush()
    return db.session.get(CustomerProject, project.id)


def add_activity(project: CustomerProject, data: dict[str, Any], membership: OrganizationMembership, idempotency_key: str) -> ProjectActivity:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    existing = db.session.scalar(
        select(ProjectActivity).where(
            ProjectActivity.organization_id == membership.organization_id,
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
        .where(
            CustomerProject.id == project.id,
            CustomerProject.organization_id == membership.organization_id,
            CustomerProject.version == expected_version,
            CustomerProject.deleted_at.is_(None),
        )
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
    cancel_pending_notifications("customer_projects", "project", project.id)
    db.session.add(activity)
    add_audit(project.organization_id, "project", project.id, "activity_added", membership.user_id, {"activity_type": activity.activity_type, "is_meaningful": meaningful})
    return activity


def add_comment(
    project: CustomerProject,
    data: dict[str, Any],
    membership: OrganizationMembership,
    idempotency_key: str,
) -> ProjectComment:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    body = str(data.get("body") or "").strip()
    if not body:
        raise DomainError(
            "VALIDATION_ERROR", "留言内容必填。", field_errors={"body": "请输入留言内容"}
        )
    if len(body) > 4000:
        raise DomainError(
            "VALIDATION_ERROR", "留言不能超过 4000 个字符。", field_errors={"body": "最多 4000 个字符"}
        )
    raw_mentions = data.get("mention_user_ids") or []
    if isinstance(raw_mentions, (str, int)):
        raw_mentions = [raw_mentions]
    try:
        mention_ids = {int(value) for value in raw_mentions if str(value).strip()}
    except (TypeError, ValueError) as exc:
        raise DomainError(
            "VALIDATION_ERROR", "@成员格式不正确。", field_errors={"mention_user_ids": "请选择有效成员"}
        ) from exc
    mention_ids.discard(membership.user_id)
    if len(mention_ids) > 10:
        raise DomainError(
            "VALIDATION_ERROR", "每条留言最多 @ 10 人。", field_errors={"mention_user_ids": "最多选择 10 人"}
        )
    if mention_ids:
        valid_ids = set(
            db.session.scalars(
                select(OrganizationMembership.user_id).where(
                    OrganizationMembership.organization_id == membership.organization_id,
                    OrganizationMembership.status == "active",
                    OrganizationMembership.user_id.in_(mention_ids),
                )
            )
        )
        if valid_ids != mention_ids:
            raise DomainError(
                "VALIDATION_ERROR",
                "只能 @ 当前组织的有效成员。",
                field_errors={"mention_user_ids": "包含无效成员"},
            )
    existing = db.session.scalar(
        select(ProjectComment).where(
            ProjectComment.organization_id == membership.organization_id,
            ProjectComment.project_id == project.id,
            ProjectComment.idempotency_key == idempotency_key,
        )
    )
    if existing:
        existing_mentions = set(
            db.session.scalars(
                select(ProjectCommentMention.user_id).where(
                    ProjectCommentMention.comment_id == existing.id
                )
            )
        )
        if existing.body != body or existing_mentions != mention_ids:
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的留言请求。")
        return existing
    comment = ProjectComment(
        organization_id=membership.organization_id,
        project_id=project.id,
        body=body,
        idempotency_key=idempotency_key,
        created_by_user_id=membership.user_id,
    )
    db.session.add(comment)
    db.session.flush()
    db.session.add_all(
        ProjectCommentMention(
            organization_id=membership.organization_id,
            comment_id=comment.id,
            user_id=user_id,
        )
        for user_id in sorted(mention_ids)
    )
    add_audit(
        project.organization_id,
        "project",
        project.id,
        "comment_added",
        membership.user_id,
        {"comment_id": comment.id, "mention_count": len(mention_ids), "body_length": len(body)},
    )
    return comment


def transition_stage(project: CustomerProject, data: dict[str, Any], membership: OrganizationMembership, idempotency_key: str) -> ProjectStageEvent:
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    existing = db.session.scalar(
        select(ProjectStageEvent).where(
            ProjectStageEvent.organization_id == membership.organization_id,
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
    if target in TERMINAL_STAGES | {"paused"}:
        cancel_pending_notifications("customer_projects", "project", project.id)
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


def reactivate_project(
    project: CustomerProject,
    data: dict[str, Any],
    membership: OrganizationMembership,
    idempotency_key: str,
) -> ProjectStageEvent:
    """Reopen a paused/terminal project without erasing its prior lifecycle."""
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    if not membership.roles.intersection({"organization_admin", "business_manager"}):
        raise DomainError("MANAGER_REQUIRED", "重新激活项目需要业务经理或组织管理员权限。")
    existing = db.session.scalar(
        select(ProjectStageEvent).where(
            ProjectStageEvent.organization_id == membership.organization_id,
            ProjectStageEvent.project_id == project.id,
            ProjectStageEvent.idempotency_key == idempotency_key,
        )
    )
    target = str(data.get("to_stage_code") or "evaluation").strip()
    if existing is not None:
        if existing.to_stage_code != target:
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于不同的重新激活请求。")
        return existing
    if project.organization_id != membership.organization_id or project.deleted_at is not None:
        raise DomainError("PROJECT_NOT_FOUND", "项目不存在或不可访问。")
    if project.stage_code not in TERMINAL_STAGES | {"paused"}:
        raise DomainError("REACTIVATION_NOT_ALLOWED", "只有暂停或终态项目可以重新激活。")
    if target not in ACTIVE_STAGES:
        raise DomainError("INVALID_STAGE_TRANSITION", "重新激活的目标必须是进行中阶段。")
    reason = str(data.get("reason") or "").strip()
    next_action = str(data.get("next_action") or "").strip()
    if not reason or not next_action or not data.get("next_follow_up_at"):
        raise DomainError(
            "VALIDATION_ERROR",
            "重新激活原因、下一步和下次跟进时间必填。",
            field_errors={
                key: "必填"
                for key, value in {
                    "reason": reason,
                    "next_action": next_action,
                    "next_follow_up_at": data.get("next_follow_up_at"),
                }.items()
                if not value
            },
        )
    try:
        expected_version = int(data.get("project_version") or 0)
        owner_id = int(data.get("primary_sales_user_id") or project.primary_sales_user_id)
    except (TypeError, ValueError) as exc:
        raise DomainError("VALIDATION_ERROR", "项目版本或负责人无效。") from exc
    if expected_version != project.version:
        raise VersionConflict(project.version)
    owner = db.session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == membership.organization_id,
            OrganizationMembership.user_id == owner_id,
            OrganizationMembership.status == "active",
        )
    )
    if owner is None or not owner.roles.intersection(
        {"organization_admin", "business_manager", "sales"}
    ):
        raise DomainError("INVALID_OWNER", "主业务不是当前组织的有效成员。")
    organization = db.session.get(Organization, membership.organization_id)
    follow_up = parse_datetime(
        data["next_follow_up_at"], organization.timezone if organization else "Asia/Shanghai"
    )
    now = datetime.now(timezone.utc)
    from_stage = project.stage_code
    result = db.session.execute(
        update(CustomerProject)
        .where(
            CustomerProject.id == project.id,
            CustomerProject.organization_id == membership.organization_id,
            CustomerProject.version == expected_version,
            CustomerProject.deleted_at.is_(None),
        )
        .values(
            stage_code=target,
            primary_sales_user_id=owner_id,
            next_action=next_action[:500],
            next_follow_up_at=follow_up,
            last_meaningful_update_at=now,
            version=expected_version + 1,
            updated_by_user_id=membership.user_id,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(CustomerProject, project.id)
        raise VersionConflict(current.version if current else expected_version)
    db.session.execute(
        update(ProjectMember)
        .where(
            ProjectMember.project_id == project.id,
            ProjectMember.role_code == "sales",
            ProjectMember.left_at.is_(None),
        )
        .values(is_primary=False)
    )
    primary_member = db.session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == owner_id,
            ProjectMember.role_code == "sales",
            ProjectMember.left_at.is_(None),
        )
    )
    if primary_member is None:
        db.session.add(
            ProjectMember(
                organization_id=membership.organization_id,
                project_id=project.id,
                user_id=owner_id,
                role_code="sales",
                is_primary=True,
            )
        )
    else:
        primary_member.is_primary = True
    cancel_pending_notifications("customer_projects", "project", project.id)
    event = ProjectStageEvent(
        organization_id=membership.organization_id,
        project_id=project.id,
        from_stage_code=from_stage,
        to_stage_code=target,
        reason=reason[:8000],
        idempotency_key=idempotency_key,
        actor_user_id=membership.user_id,
        approved_by_user_id=membership.user_id,
    )
    db.session.add(event)
    add_audit(
        project.organization_id,
        "project",
        project.id,
        "reactivated",
        membership.user_id,
        {"from": from_stage, "to": target, "primary_sales_user_id": owner_id},
    )
    return event


def derive_project(
    source: CustomerProject,
    data: dict[str, Any],
    membership: OrganizationMembership,
    idempotency_key: str,
) -> CustomerProject:
    """Create a new lifecycle from a project while keeping histories isolated."""
    if not idempotency_key or len(idempotency_key) > 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "缺少有效的幂等键。")
    if source.organization_id != membership.organization_id or source.deleted_at is not None:
        raise DomainError("PROJECT_NOT_FOUND", "来源项目不存在或不可访问。")
    project_id = _project_id_for_key(membership.organization_id, idempotency_key)
    existing = db.session.get(CustomerProject, project_id)
    if existing is not None:
        if existing.derived_from_project_id != source.id:
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "相同幂等键已用于其他项目请求。")
        return existing

    payload = dict(data)
    payload.setdefault("customer_id", source.customer_id)
    payload.setdefault("product_name", source.product_name or source.name)
    payload.setdefault("annual_usage", source.annual_usage)
    payload.setdefault("assessment_grade", source.assessment_grade)
    payload.setdefault("probability_band", source.probability_band)
    payload.setdefault("primary_sales_user_id", source.primary_sales_user_id)
    derived = create_project(payload, membership, idempotency_key)
    derived.derived_from_project_id = source.id

    if bool(data.get("copy_members")):
        members = db.session.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == source.id,
                ProjectMember.left_at.is_(None),
            )
        )
        existing_roles = {(derived.primary_sales_user_id, "sales")}
        for member in members:
            key = (member.user_id, member.role_code)
            if key in existing_roles:
                continue
            db.session.add(
                ProjectMember(
                    organization_id=membership.organization_id,
                    project_id=derived.id,
                    user_id=member.user_id,
                    role_code=member.role_code,
                    is_primary=False,
                    notification_preferences_json=member.notification_preferences_json,
                )
            )
            existing_roles.add(key)

    material_map: dict[str, ProjectMaterial] = {}
    if bool(data.get("copy_materials")):
        materials = list(
            db.session.scalars(
                select(ProjectMaterial).where(
                    ProjectMaterial.project_id == source.id,
                    ProjectMaterial.deleted_at.is_(None),
                )
            )
        )
        for material in materials:
            clone = ProjectMaterial(
                organization_id=membership.organization_id,
                project_id=derived.id,
                opportunity_type=material.opportunity_type,
                category_code=material.category_code,
                promoted_brand=material.promoted_brand,
                promoted_mpn=material.promoted_mpn,
                normalized_mpn=material.normalized_mpn,
                mpn_pending=material.mpn_pending,
                customer_part_number=material.customer_part_number,
                application_position=material.application_position,
                machine_quantity=material.machine_quantity,
                estimated_quantity=material.estimated_quantity,
                quantity_period=material.quantity_period,
                unit_code=material.unit_code,
                target_price=material.target_price,
                currency=material.currency,
                fx_rate_usd_cny=material.fx_rate_usd_cny,
                unit_price_usd=material.unit_price_usd,
                unit_price_cny_tax_included=material.unit_price_cny_tax_included,
                price_updated_by_user_id=membership.user_id if material.target_price is not None else None,
                price_updated_at=datetime.now(timezone.utc) if material.target_price is not None else None,
                technical_status=material.technical_status,
                commercial_status=material.commercial_status,
                expected_mass_production_at=material.expected_mass_production_at,
                is_primary=material.is_primary,
                notes=material.notes,
                idempotency_key=f"derive:{material.id}"[:128],
                created_by_user_id=membership.user_id,
                updated_by_user_id=membership.user_id,
            )
            db.session.add(clone)
            db.session.flush()
            material_map[material.id] = clone

    if material_map and bool(data.get("copy_competitors")):
        competitors = db.session.scalars(
            select(MaterialCompetitor).where(
                MaterialCompetitor.project_material_id.in_(material_map),
                MaterialCompetitor.deleted_at.is_(None),
            )
        )
        for competitor in competitors:
            db.session.add(
                MaterialCompetitor(
                    organization_id=membership.organization_id,
                    project_material_id=material_map[competitor.project_material_id].id,
                    brand=competitor.brand,
                    mpn=competitor.mpn,
                    normalized_mpn=competitor.normalized_mpn,
                    distributor=competitor.distributor,
                    model_pending=competitor.model_pending,
                    incumbent_status=competitor.incumbent_status,
                    quoted_price=competitor.quoted_price,
                    strengths=competitor.strengths,
                    weaknesses=competitor.weaknesses,
                    confidence_level=competitor.confidence_level,
                    observed_at=competitor.observed_at,
                    notes=competitor.notes,
                    idempotency_key=f"derive:{competitor.id}"[:128],
                    created_by_user_id=membership.user_id,
                    updated_by_user_id=membership.user_id,
                )
            )
    add_audit(
        membership.organization_id,
        "project",
        derived.id,
        "derived",
        membership.user_id,
        {
            "source_project_id": source.id,
            "copied_members": bool(data.get("copy_members")),
            "copied_materials": bool(data.get("copy_materials")),
            "copied_competitors": bool(data.get("copy_competitors")),
        },
    )
    return derived


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
            ProjectMaterial.organization_id == membership.organization_id,
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
    opportunity_type = parse_opportunity_type(data.get("opportunity_type"))
    brand = str(data.get("promoted_brand") or "").strip()
    mpn = str(data.get("promoted_mpn") or "").strip()
    pending = bool(data.get("mpn_pending"))
    if opportunity_type != LOST_OPPORTUNITY and (
        not brand or (not mpn and not pending)
    ):
        raise DomainError("VALIDATION_ERROR", "推广品牌必填；推广型号或“型号待确认”至少填写一项。")
    machine_quantity = parse_nonnegative_integer(
        data.get("machine_quantity"), "machine_quantity", "单机数量"
    )
    material = ProjectMaterial(
        organization_id=membership.organization_id,
        project_id=project.id,
        opportunity_type=parse_opportunity_type(data.get("opportunity_type")),
        category_code=str(data.get("category_code") or "").strip()[:64] or None,
        promoted_brand=brand[:120],
        promoted_mpn=mpn[:160] or None,
        normalized_mpn=normalize_mpn(mpn),
        mpn_pending=pending,
        application_position=str(data.get("application_position") or "").strip()[:255] or None,
        machine_quantity=machine_quantity,
        technical_status=str(data.get("technical_status") or "").strip()[:64] or None,
        commercial_status=str(data.get("commercial_status") or "").strip()[:64] or None,
        is_primary=bool(data.get("is_primary")),
        idempotency_key=idempotency_key,
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    if data.get("unit_price") not in (None, ""):
        apply_material_price(material, data, membership)
    db.session.add(material)
    db.session.flush()
    add_audit(project.organization_id, "material", material.id, "created", membership.user_id, {"brand": brand, "mpn": mpn or "待确认"})
    return material


def apply_material_price(
    material: ProjectMaterial, data: dict[str, Any], membership: OrganizationMembership
) -> None:
    allowed_roles = {"organization_admin", "business_manager", "sales", "pm"}
    if not membership.roles.intersection(allowed_roles):
        raise DomainError("PRICE_EDIT_FORBIDDEN", "只有业务和 PM 可以编辑单价。")
    amount = parse_price(data.get("unit_price"), "unit_price", "单价")
    if amount in (None, Decimal("0")):
        raise DomainError(
            "VALIDATION_ERROR", "单价必须大于 0。", field_errors={"unit_price": "必须大于 0"}
        )
    currency = str(data.get("currency") or "").upper().strip()
    if currency not in {"USD", "CNY"}:
        raise DomainError(
            "VALIDATION_ERROR", "单价币别仅支持 USD 或 CNY。", field_errors={"currency": "请选择币别"}
        )
    try:
        fx_rate = Decimal(
            str(get_exchange_rate(current_app._get_current_object(), "USD", "CNY")["rate"])
        )
    except ExchangeRateError as exc:
        raise DomainError("EXCHANGE_RATE_UNAVAILABLE", "汇率暂不可用，单价未保存，请稍后重试。") from exc
    tax_multiplier = Decimal("1.13")
    precision = Decimal("0.00001")
    if currency == "USD":
        usd_price = amount
        cny_tax_price = amount * fx_rate * tax_multiplier
    else:
        cny_tax_price = amount
        usd_price = amount / tax_multiplier / fx_rate
    material.target_price = amount.quantize(precision, rounding=ROUND_HALF_UP)
    material.currency = currency
    material.fx_rate_usd_cny = fx_rate.quantize(precision, rounding=ROUND_HALF_UP)
    material.unit_price_usd = usd_price.quantize(precision, rounding=ROUND_HALF_UP)
    material.unit_price_cny_tax_included = cny_tax_price.quantize(
        precision, rounding=ROUND_HALF_UP
    )
    material.price_updated_by_user_id = membership.user_id
    material.price_updated_at = datetime.now(timezone.utc)


def update_material_commercial(
    material: ProjectMaterial,
    data: dict[str, Any],
    membership: OrganizationMembership,
    expected_version: int,
) -> ProjectMaterial:
    if material.organization_id != membership.organization_id or material.deleted_at is not None:
        raise DomainError("MATERIAL_NOT_FOUND", "推广物料不存在或不可访问。")
    values: dict[str, Any] = {
        "updated_by_user_id": membership.user_id,
        "updated_at": datetime.now(timezone.utc),
        "version": expected_version + 1,
    }
    safe_diff: dict[str, Any] = {}
    supported_fields = {
        "category_code",
        "opportunity_type",
        "promoted_brand",
        "promoted_mpn",
        "mpn_pending",
        "customer_part_number",
        "application_position",
        "machine_quantity",
        "technical_status",
        "commercial_status",
        "expected_mass_production_at",
        "is_primary",
        "notes",
    }
    has_price = data.get("unit_price") not in (None, "")
    if not supported_fields.intersection(data) and not has_price:
        raise DomainError("VALIDATION_ERROR", "请至少更新一项物料信息。")

    brand = str(data.get("promoted_brand", material.promoted_brand) or "").strip()
    mpn = str(data.get("promoted_mpn", material.promoted_mpn) or "").strip()
    pending = (
        parse_boolean(data.get("mpn_pending"))
        if "mpn_pending" in data
        else material.mpn_pending
    )
    target_type = (
        parse_opportunity_type(data.get("opportunity_type"))
        if "opportunity_type" in data
        else material.opportunity_type
    )
    # Older records created before the MPN/pending invariant may legitimately
    # have neither value.  Allow those records to be edited and normalize them
    # to the explicit "model pending" state; newly-cleared MPNs still require
    # the user to check the pending box.
    if target_type == LOST_OPPORTUNITY:
        # Lost 仅记录竞品信息，推广品牌/型号可不填
        pass
    elif material.opportunity_type == LOST_OPPORTUNITY:
        # Lost 转为其他三类时，必须补充推广物料信息
        if not brand or (not mpn and not pending):
            raise DomainError(
                "VALIDATION_ERROR",
                "Lost 转为其他机会类型时，必须补充推广品牌与型号（或勾选“型号待确认”）。",
                field_errors={
                    "promoted_brand": "请补充推广品牌",
                    "promoted_mpn": "请补充推广型号或勾选型号待确认",
                },
            )
    elif not brand or (not mpn and not pending):
        if (
            not brand
            or material.promoted_mpn is not None
            or material.mpn_pending
        ):
            raise DomainError(
                "VALIDATION_ERROR",
                "推广品牌必填；推广型号或“型号待确认”至少填写一项。",
            )
        pending = True
    if "promoted_brand" in data:
        values["promoted_brand"] = brand[:120]
        safe_diff["promoted_brand"] = "已变更"
    if "opportunity_type" in data:
        values["opportunity_type"] = parse_opportunity_type(data.get("opportunity_type"))
        safe_diff["opportunity_type"] = values["opportunity_type"]
    if "promoted_mpn" in data:
        values["promoted_mpn"] = mpn[:160] or None
        values["normalized_mpn"] = normalize_mpn(mpn)
        safe_diff["promoted_mpn"] = "已变更"
    if "mpn_pending" in data:
        values["mpn_pending"] = pending
        safe_diff["mpn_pending"] = pending
    for field, limit in (
        ("category_code", 64),
        ("customer_part_number", 160),
        ("application_position", 255),
        ("technical_status", 64),
        ("commercial_status", 64),
        ("notes", 8000),
    ):
        if field in data:
            values[field] = str(data.get(field) or "").strip()[:limit] or None
            safe_diff[field] = "已变更"
    if "is_primary" in data:
        values["is_primary"] = parse_boolean(data.get("is_primary"))
        safe_diff["is_primary"] = values["is_primary"]
    if "expected_mass_production_at" in data:
        values["expected_mass_production_at"] = parse_date(
            data.get("expected_mass_production_at")
        )
        safe_diff["expected_mass_production_at"] = str(
            values["expected_mass_production_at"] or ""
        )
    if "machine_quantity" in data:
        values["machine_quantity"] = parse_nonnegative_integer(
            data.get("machine_quantity"), "machine_quantity", "单机数量"
        )
        safe_diff["machine_quantity"] = str(values["machine_quantity"] or "")
    if has_price:
        apply_material_price(material, data, membership)
        for field in (
            "target_price",
            "currency",
            "fx_rate_usd_cny",
            "unit_price_usd",
            "unit_price_cny_tax_included",
            "price_updated_by_user_id",
            "price_updated_at",
        ):
            values[field] = getattr(material, field)
        safe_diff.update(
            {
                "currency": material.currency,
                "fx_rate_usd_cny": str(material.fx_rate_usd_cny),
                "price": "已更新",
            }
        )
    result = db.session.execute(
        update(ProjectMaterial)
        .where(
            ProjectMaterial.id == material.id,
            ProjectMaterial.organization_id == membership.organization_id,
            ProjectMaterial.version == expected_version,
            ProjectMaterial.deleted_at.is_(None),
        )
        .values(**values)
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(ProjectMaterial, material.id)
        raise ObjectVersionConflict(
            "MATERIAL_VERSION_CONFLICT",
            "物料已被其他成员更新，请刷新后重试。",
            current.version if current else expected_version,
        )
    add_audit(
        material.organization_id,
        "material",
        material.id,
        "updated",
        membership.user_id,
        safe_diff,
    )
    db.session.flush()
    return db.session.get(ProjectMaterial, material.id)


def soft_delete_material(
    material: ProjectMaterial,
    reason: str,
    membership: OrganizationMembership,
    expected_version: int,
) -> None:
    reason = reason.strip()
    if not reason:
        raise DomainError(
            "VALIDATION_ERROR", "删除原因必填。", field_errors={"reason": "必填"}
        )
    result = db.session.execute(
        update(ProjectMaterial)
        .where(
            ProjectMaterial.id == material.id,
            ProjectMaterial.organization_id == membership.organization_id,
            ProjectMaterial.version == expected_version,
            ProjectMaterial.deleted_at.is_(None),
        )
        .values(
            deleted_at=datetime.now(timezone.utc),
            deleted_by_user_id=membership.user_id,
            delete_reason=reason[:500],
            updated_by_user_id=membership.user_id,
            updated_at=datetime.now(timezone.utc),
            version=expected_version + 1,
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(ProjectMaterial, material.id)
        raise ObjectVersionConflict(
            "MATERIAL_VERSION_CONFLICT",
            "物料已被其他成员更新，请刷新后重试。",
            current.version if current else expected_version,
        )
    add_audit(
        material.organization_id,
        "material",
        material.id,
        "deleted",
        membership.user_id,
        {"reason": reason[:500]},
    )


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
            MaterialCompetitor.organization_id == membership.organization_id,
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
        quoted_price=(
            parse_price(data.get("quoted_price"), "quoted_price", "竞品报价")
            if data.get("quoted_price") not in (None, "")
            else None
        ),
        idempotency_key=idempotency_key,
        created_by_user_id=membership.user_id,
        updated_by_user_id=membership.user_id,
    )
    db.session.add(competitor)
    db.session.flush()
    add_audit(membership.organization_id, "competitor", competitor.id, "created", membership.user_id, {"brand": brand or "待确认", "mpn": mpn or "待确认"})
    return competitor


def update_competitor(
    competitor: MaterialCompetitor,
    data: dict[str, Any],
    membership: OrganizationMembership,
    expected_version: int,
) -> MaterialCompetitor:
    if competitor.organization_id != membership.organization_id or competitor.deleted_at is not None:
        raise DomainError("COMPETITOR_NOT_FOUND", "竞争方案不存在或不可访问。")
    supported_fields = {
        "brand",
        "mpn",
        "distributor",
        "model_pending",
        "incumbent_status",
        "quoted_price",
        "strengths",
        "weaknesses",
        "confidence_level",
        "observed_at",
        "notes",
    }
    if not supported_fields.intersection(data):
        raise DomainError("VALIDATION_ERROR", "请至少更新一项竞争方案信息。")
    brand = str(data.get("brand", competitor.brand) or "").strip()
    mpn = str(data.get("mpn", competitor.mpn) or "").strip()
    distributor = str(data.get("distributor", competitor.distributor) or "").strip()
    pending = (
        parse_boolean(data.get("model_pending"))
        if "model_pending" in data
        else competitor.model_pending
    )
    if not any((brand, mpn, distributor, pending)):
        raise DomainError("VALIDATION_ERROR", "品牌、型号、代理商至少填写一项，或标记型号待确认。")
    values: dict[str, Any] = {
        "updated_by_user_id": membership.user_id,
        "updated_at": datetime.now(timezone.utc),
        "version": expected_version + 1,
    }
    safe_diff: dict[str, Any] = {}
    for field, value, limit in (
        ("brand", brand, 120),
        ("mpn", mpn, 160),
        ("distributor", distributor, 160),
    ):
        if field in data:
            values[field] = value[:limit] or None
            safe_diff[field] = "已变更"
    if "mpn" in data:
        values["normalized_mpn"] = normalize_mpn(mpn)
    if "model_pending" in data:
        values["model_pending"] = pending
        safe_diff["model_pending"] = pending
    for field, limit in (
        ("incumbent_status", 64),
        ("strengths", 4000),
        ("weaknesses", 4000),
        ("confidence_level", 32),
        ("notes", 8000),
    ):
        if field in data:
            values[field] = str(data.get(field) or "").strip()[:limit] or None
            safe_diff[field] = "已变更"
    if "quoted_price" in data:
        values["quoted_price"] = parse_price(
            data.get("quoted_price"), "quoted_price", "竞品报价"
        )
        safe_diff["quoted_price"] = str(values["quoted_price"] or "")
    if "observed_at" in data:
        values["observed_at"] = parse_date(data.get("observed_at"))
        safe_diff["observed_at"] = str(values["observed_at"] or "")
    result = db.session.execute(
        update(MaterialCompetitor)
        .where(
            MaterialCompetitor.id == competitor.id,
            MaterialCompetitor.organization_id == membership.organization_id,
            MaterialCompetitor.version == expected_version,
            MaterialCompetitor.deleted_at.is_(None),
        )
        .values(**values)
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(MaterialCompetitor, competitor.id)
        raise ObjectVersionConflict(
            "COMPETITOR_VERSION_CONFLICT",
            "竞争方案已被其他成员更新，请刷新后重试。",
            current.version if current else expected_version,
        )
    add_audit(
        competitor.organization_id,
        "competitor",
        competitor.id,
        "updated",
        membership.user_id,
        safe_diff,
    )
    db.session.flush()
    return db.session.get(MaterialCompetitor, competitor.id)


def soft_delete_competitor(
    competitor: MaterialCompetitor,
    reason: str,
    membership: OrganizationMembership,
    expected_version: int,
) -> None:
    reason = reason.strip()
    if not reason:
        raise DomainError(
            "VALIDATION_ERROR", "删除原因必填。", field_errors={"reason": "必填"}
        )
    result = db.session.execute(
        update(MaterialCompetitor)
        .where(
            MaterialCompetitor.id == competitor.id,
            MaterialCompetitor.organization_id == membership.organization_id,
            MaterialCompetitor.version == expected_version,
            MaterialCompetitor.deleted_at.is_(None),
        )
        .values(
            deleted_at=datetime.now(timezone.utc),
            deleted_by_user_id=membership.user_id,
            delete_reason=reason[:500],
            updated_by_user_id=membership.user_id,
            updated_at=datetime.now(timezone.utc),
            version=expected_version + 1,
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(MaterialCompetitor, competitor.id)
        raise ObjectVersionConflict(
            "COMPETITOR_VERSION_CONFLICT",
            "竞争方案已被其他成员更新，请刷新后重试。",
            current.version if current else expected_version,
        )
    add_audit(
        competitor.organization_id,
        "competitor",
        competitor.id,
        "deleted",
        membership.user_id,
        {"reason": reason[:500]},
    )


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
            ProjectMember.organization_id == membership.organization_id,
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
    cancel_pending_notifications("customer_projects", "project", project.id)
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
