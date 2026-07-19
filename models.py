"""
SQLAlchemy ORM models.

We use SQLite locally but keep code ORM-only so a future swap to PostgreSQL is
just a `DATABASE_URL` change. The schema is created on first run via
`db.create_all()` inside the app factory — no Alembic needed at this scale.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from flask_login import UserMixin
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# User
# -----------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active_user: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    # custom_limits: {tool_id: int_limit, ...}; null means use global default
    custom_limits: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # ---- helpers ----
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def custom_limit_map(self) -> dict[str, int]:
        if not self.custom_limits:
            return {}
        try:
            return {str(k): int(v) for k, v in json.loads(self.custom_limits).items()}
        except (ValueError, TypeError):
            return {}

    def limit_for(self, tool_id: str, default: int) -> int:
        return self.custom_limit_map.get(tool_id, default)

    # Flask-Login glue
    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.is_active_user

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"


# -----------------------------------------------------------------------------
# Tool registry
# -----------------------------------------------------------------------------
class Tool(db.Model):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    icon: Mapped[str] = mapped_column(String(64), default="bi-tools", nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#0d6efd", nullable=False)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    blueprint_module: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    required_plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    # category: 分组键，首页按它分块。未指定时归到 "其他工具"。
    category: Mapped[str] = mapped_column(String(32), default="other", nullable=False, index=True)
    order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "route": self.route,
            "enabled": self.enabled,
            "required_plan": self.required_plan,
            "category": self.category,
            "order": self.order,
        }


# -----------------------------------------------------------------------------
# Usage tracking
# -----------------------------------------------------------------------------
class AnonUsage(db.Model):
    """Aggregated daily anonymous usage: (anon_id, tool_id, day) -> count."""
    __tablename__ = "anon_usage"
    __table_args__ = (
        UniqueConstraint("anon_id", "tool_id", "day", name="uq_anon_usage"),
        Index("ix_anon_usage_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anon_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD UTC
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class UserUsage(db.Model):
    """Aggregated daily user usage: (user_id, tool_id, day) -> count."""
    __tablename__ = "user_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "tool_id", "day", name="uq_user_usage"),
        Index("ix_user_usage_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# -----------------------------------------------------------------------------
# Audit log
# -----------------------------------------------------------------------------
class UsageLog(db.Model):
    __tablename__ = "usage_logs"
    __table_args__ = (
        Index("ix_usage_logs_ts", "ts"),
        Index("ix_usage_logs_tool", "tool_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    anon_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)  # success|failed
    message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


# -----------------------------------------------------------------------------
# Settings (k/v)
# -----------------------------------------------------------------------------
class Setting(db.Model):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


# -----------------------------------------------------------------------------
# Anonymous identity (persistent in DB so we can purge / re-issue)
# -----------------------------------------------------------------------------
def new_anon_id() -> str:
    return secrets.token_urlsafe(24)


# -----------------------------------------------------------------------------
# Part-number mapping (for the FCST merge tool)
# -----------------------------------------------------------------------------
class PnMapping(db.Model):
    """品号 → 原厂料号 / 品牌 映射表。

    存在数据库里方便增删改查；FCST 处理时按品号查这张表补全原厂料号和品牌。

    Owner 隔离：
    - 登录用户 (owner_type='user') 的料号永久保存。
    - 匿名用户 (owner_type='anon') 的料号是临时的，绑定到 session 里的 anon_id，
      超过 24h 未活动会被清理 job 删除。
    """
    __tablename__ = "pn_mappings"
    __table_args__ = (
        Index("ix_pn_part_number", "part_number"),
        Index("ix_pn_owner", "owner_type", "owner_id"),
        UniqueConstraint("owner_type", "owner_id", "part_number", name="uq_pn_owner_pn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mfr_part: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    brand: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 'user' → owner_id = str(user.id); 'anon' → owner_id = anon_id (session)
    owner_type: Mapped[str] = mapped_column(String(8), default="anon", nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "part_number": self.part_number,
            "mfr_part": self.mfr_part,
            "brand": self.brand,
        }
