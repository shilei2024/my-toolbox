"""Customer project tracking domain models."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from extensions import db
from shared.models import new_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatusCatalog(db.Model):
    __tablename__ = "project_status_catalog"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_project_status_org_code"),
        CheckConstraint("stale_after_days IS NULL OR stale_after_days > 0", name="ck_status_stale_days"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    stale_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_type: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Customer(db.Model):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customer_org_normalized", "organization_id", "normalized_name"),
        CheckConstraint("version > 0", name="ck_customer_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        db.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    primary_owner_user_id: Mapped[int] = mapped_column(
        Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CustomerContact(db.Model):
    __tablename__ = "customer_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(db.ForeignKey("organizations.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CustomerProject(db.Model):
    __tablename__ = "customer_projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "project_code", name="uq_project_org_code"),
        Index("ix_project_org_stage", "organization_id", "stage_code"),
        Index("ix_project_org_sales_followup", "organization_id", "primary_sales_user_id", "next_follow_up_at"),
        Index("ix_project_org_meaningful", "organization_id", "last_meaningful_update_at"),
        Index("ix_project_org_normalized", "organization_id", "customer_id", "normalized_name"),
        CheckConstraint("version > 0", name="ck_project_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(db.ForeignKey("organizations.id"), nullable=False, index=True)
    project_code: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_id: Mapped[str] = mapped_column(db.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    annual_usage: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    stage_code: Mapped[str] = mapped_column(String(32), nullable=False, default="evaluation")
    assessment_grade: Mapped[str | None] = mapped_column(String(4), nullable=True)
    probability_band: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_sales_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    next_action: Mapped[str] = mapped_column(String(500), nullable=False)
    next_follow_up_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_meaningful_update_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expected_design_win_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_mass_production_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_mass_production_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    close_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    derived_from_project_id: Mapped[str | None] = mapped_column(db.ForeignKey("customer_projects.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ProjectMember(db.Model):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", "role_code", name="uq_project_member_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(db.ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(db.ForeignKey("customer_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    role_code: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_preferences_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectMaterial(db.Model):
    __tablename__ = "project_materials"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_material_project_idempotency"),
        Index("ix_material_org_brand_mpn", "organization_id", "promoted_brand", "normalized_mpn"),
        CheckConstraint("version > 0", name="ck_material_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(db.ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(db.ForeignKey("customer_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    promoted_brand: Mapped[str] = mapped_column(String(120), nullable=False)
    promoted_mpn: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_mpn: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mpn_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    customer_part_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    application_position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    machine_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    estimated_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quantity_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    fx_rate_usd_cny: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    unit_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    unit_price_cny_tax_included: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    price_updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    technical_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commercial_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_mass_production_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MaterialCompetitor(db.Model):
    __tablename__ = "material_competitors"
    __table_args__ = (
        UniqueConstraint("project_material_id", "idempotency_key", name="uq_competitor_material_idempotency"),
        Index("ix_competitor_org_brand_mpn", "organization_id", "brand", "normalized_mpn"),
        CheckConstraint("version > 0", name="ck_competitor_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(db.ForeignKey("organizations.id"), nullable=False, index=True)
    project_material_id: Mapped[str] = mapped_column(db.ForeignKey("project_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mpn: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_mpn: Mapped[str | None] = mapped_column(String(160), nullable=True)
    distributor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    incumbent_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quoted_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    strengths: Mapped[str | None] = mapped_column(Text, nullable=True)
    weaknesses: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ProjectActivity(db.Model):
    __tablename__ = "project_activities"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_activity_project_idempotency"),
        Index("ix_activity_project_time", "project_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(db.ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(db.ForeignKey("customer_projects.id", ondelete="CASCADE"), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str] = mapped_column(String(500), nullable=False)
    next_follow_up_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_meaningful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProjectStageEvent(db.Model):
    __tablename__ = "project_stage_events"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_stage_event_project_idempotency"),
        Index("ix_stage_event_project_time", "project_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(db.ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(db.ForeignKey("customer_projects.id", ondelete="CASCADE"), nullable=False)
    from_stage_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_stage_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
