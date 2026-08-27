"""Shared organization and audit models.

These tables intentionally live outside customer_projects so future business
modules can reuse tenant membership and sanitized audit events.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Organization(db.Model):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class OrganizationMembership(db.Model):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_membership_user"),
        Index("ix_org_membership_active_user", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    roles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    @property
    def roles(self) -> frozenset[str]:
        try:
            value = json.loads(self.roles_json)
        except (TypeError, ValueError):
            return frozenset()
        if not isinstance(value, list):
            return frozenset()
        return frozenset(str(role) for role in value)

    def set_roles(self, roles: list[str] | set[str] | tuple[str, ...]) -> None:
        self.roles_json = json.dumps(sorted(set(roles)), ensure_ascii=False)


class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_object_time", "organization_id", "object_type", "object_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        db.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    safe_diff_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    def set_safe_diff(self, value: dict[str, Any]) -> None:
        self.safe_diff_json = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
