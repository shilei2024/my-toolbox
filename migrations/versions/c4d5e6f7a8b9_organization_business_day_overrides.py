"""organization business day overrides

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-28 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_business_day_overrides",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("is_working_day", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_org_business_day_version_positive"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "calendar_date", name="uq_org_business_day_date"),
    )
    op.create_index(
        op.f("ix_organization_business_day_overrides_organization_id"),
        "organization_business_day_overrides",
        ["organization_id"],
    )
    op.create_index(
        "ix_org_business_day_range",
        "organization_business_day_overrides",
        ["organization_id", "calendar_date"],
    )


def downgrade():
    op.drop_index("ix_org_business_day_range", table_name="organization_business_day_overrides")
    op.drop_index(
        op.f("ix_organization_business_day_overrides_organization_id"),
        table_name="organization_business_day_overrides",
    )
    op.drop_table("organization_business_day_overrides")
