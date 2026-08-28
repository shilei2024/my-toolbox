"""Lifecycle reporting built from the PostgreSQL business records."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone
from typing import Any, Mapping

from sqlalchemy import exists, select

from extensions import db
from shared.models import Organization, OrganizationMembership

from customer_projects.models import Customer, CustomerProject, MaterialCompetitor, ProjectMaterial
from customer_projects.permissions import apply_project_scope
from customer_projects.services.projects import DomainError


REPORT_STAGES = ("mass_production", "lost", "archived")


def _parse_date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DomainError(
            "VALIDATION_ERROR", "报表日期格式无效。", field_errors={field: "请使用 YYYY-MM-DD"}
        ) from exc


def build_lifecycle_report(
    membership: OrganizationMembership, filters: Mapping[str, Any]
) -> dict[str, Any]:
    """Return scoped lifecycle snapshots with explicit reporting semantics."""
    date_from = _parse_date(filters.get("date_from"), "date_from")
    date_to = _parse_date(filters.get("date_to"), "date_to")
    if date_from and date_to and date_from > date_to:
        raise DomainError(
            "VALIDATION_ERROR", "开始日期不能晚于结束日期。", field_errors={"date_from": "日期范围无效"}
        )
    stmt = apply_project_scope(
        select(CustomerProject).where(
            CustomerProject.organization_id == membership.organization_id,
            CustomerProject.deleted_at.is_(None),
            CustomerProject.stage_code.in_(REPORT_STAGES),
        ),
        membership,
    )
    customer_id = str(filters.get("customer_id") or "").strip()
    owner_id = str(filters.get("owner_user_id") or "").strip()
    stage = str(filters.get("stage") or "").strip()
    material_brand = str(filters.get("material_brand") or "").strip()
    category = str(filters.get("category") or "").strip()
    competitor_brand = str(filters.get("competitor_brand") or "").strip()
    distributor = str(filters.get("distributor") or "").strip()
    year_value = str(filters.get("year") or "").strip()
    month_value = str(filters.get("month") or "").strip()
    if customer_id:
        stmt = stmt.where(CustomerProject.customer_id == customer_id)
    if owner_id:
        try:
            stmt = stmt.where(CustomerProject.primary_sales_user_id == int(owner_id))
        except ValueError as exc:
            raise DomainError(
                "VALIDATION_ERROR", "负责人筛选无效。", field_errors={"owner_user_id": "必须是数字"}
            ) from exc
    if stage:
        if stage not in REPORT_STAGES:
            raise DomainError(
                "VALIDATION_ERROR", "生命周期状态筛选无效。", field_errors={"stage": "不支持该状态"}
            )
        stmt = stmt.where(CustomerProject.stage_code == stage)
    if material_brand:
        stmt = stmt.where(
            exists().where(
                ProjectMaterial.project_id == CustomerProject.id,
                ProjectMaterial.deleted_at.is_(None),
                ProjectMaterial.promoted_brand.ilike(f"%{material_brand}%"),
            )
        )
    if category:
        stmt = stmt.where(
            exists().where(
                ProjectMaterial.project_id == CustomerProject.id,
                ProjectMaterial.deleted_at.is_(None),
                ProjectMaterial.category_code == category,
            )
        )
    if competitor_brand or distributor:
        competitor_filter = exists().where(
            ProjectMaterial.project_id == CustomerProject.id,
            ProjectMaterial.deleted_at.is_(None),
            MaterialCompetitor.project_material_id == ProjectMaterial.id,
            MaterialCompetitor.deleted_at.is_(None),
        )
        if competitor_brand:
            competitor_filter = competitor_filter.where(
                MaterialCompetitor.brand.ilike(f"%{competitor_brand}%")
            )
        if distributor:
            competitor_filter = competitor_filter.where(
                MaterialCompetitor.distributor.ilike(f"%{distributor}%")
            )
        stmt = stmt.where(competitor_filter)
    if year_value or month_value:
        try:
            report_year = int(year_value or datetime.now(timezone.utc).year)
            report_month = int(month_value) if month_value else None
            if report_year < 2000 or report_year > 2100 or (
                report_month is not None and report_month not in range(1, 13)
            ):
                raise ValueError
        except ValueError as exc:
            raise DomainError(
                "VALIDATION_ERROR",
                "报表年份或月份无效。",
                field_errors={"year": "2000–2100", "month": "1–12"},
            ) from exc
        period_start = datetime(report_year, report_month or 1, 1, tzinfo=timezone.utc)
        if report_month == 12:
            period_end = datetime(report_year + 1, 1, 1, tzinfo=timezone.utc)
        elif report_month:
            period_end = datetime(report_year, report_month + 1, 1, tzinfo=timezone.utc)
        else:
            period_end = datetime(report_year + 1, 1, 1, tzinfo=timezone.utc)
        stmt = stmt.where(
            CustomerProject.updated_at >= period_start,
            CustomerProject.updated_at < period_end,
        )
    if date_from:
        stmt = stmt.where(
            CustomerProject.updated_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to:
        stmt = stmt.where(
            CustomerProject.updated_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        )
    projects = list(db.session.scalars(stmt.order_by(CustomerProject.updated_at.desc())))

    customer_ids = {project.customer_id for project in projects}
    customers = {
        customer.id: customer.name
        for customer in db.session.scalars(select(Customer).where(Customer.id.in_(customer_ids)))
    } if customer_ids else {}
    lost_ids = {project.id for project in projects if project.stage_code == "lost"}
    competitor_brands: Counter[str] = Counter()
    competitor_distributors: Counter[str] = Counter()
    if lost_ids:
        competitors = db.session.scalars(
            select(MaterialCompetitor)
            .join(ProjectMaterial, ProjectMaterial.id == MaterialCompetitor.project_material_id)
            .where(
                ProjectMaterial.project_id.in_(lost_ids),
                ProjectMaterial.deleted_at.is_(None),
                MaterialCompetitor.deleted_at.is_(None),
            )
        )
        for competitor in competitors:
            competitor_brands[competitor.brand or "未记录"] += 1
            competitor_distributors[competitor.distributor or "未记录"] += 1

    stage_counts = Counter(project.stage_code for project in projects)
    lost_reasons = Counter(
        project.close_reason_code or "未分类" for project in projects if project.stage_code == "lost"
    )
    production_customers = Counter(
        customers.get(project.customer_id, "未知客户")
        for project in projects
        if project.stage_code == "mass_production"
    )
    production_products = Counter(
        project.product_name or "未记录"
        for project in projects
        if project.stage_code == "mass_production"
    )
    normalized_filters = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "customer_id": customer_id or None,
        "owner_user_id": owner_id or None,
        "stage": stage or None,
        "material_brand": material_brand or None,
        "category": category or None,
        "competitor_brand": competitor_brand or None,
        "distributor": distributor or None,
        "year": year_value or None,
        "month": month_value or None,
    }
    organization = db.session.get(Organization, membership.organization_id)
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc),
            "data_fresh_through": max((p.updated_at for p in projects), default=None),
            "timezone": organization.timezone if organization else "Asia/Shanghai",
            "scope": "organization" if membership.roles.intersection({"organization_admin", "business_manager"}) else "authorized_projects",
            "filters": normalized_filters,
            "definition": "按项目当前生命周期状态统计；日期筛选使用项目 updated_at（UTC），结果不是阶段转化率。",
        },
        "summary": {
            "total": len(projects),
            "by_stage": dict(stage_counts),
            "lost_by_reason": dict(lost_reasons),
            "lost_by_competitor_brand": dict(competitor_brands),
            "lost_by_distributor": dict(competitor_distributors),
            "mass_production_by_customer": dict(production_customers),
            "mass_production_by_product": dict(production_products),
        },
        "projects": [
            {
                "id": project.id,
                "project_code": project.project_code,
                "name": project.name,
                "customer_name": customers.get(project.customer_id, "未知客户"),
                "product_name": project.product_name,
                "stage_code": project.stage_code,
                "close_reason_code": project.close_reason_code,
                "primary_sales_user_id": project.primary_sales_user_id,
                "actual_mass_production_at": project.actual_mass_production_at,
                "updated_at": project.updated_at,
            }
            for project in projects
        ],
    }
