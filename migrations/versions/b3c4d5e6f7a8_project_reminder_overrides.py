"""project reminder overrides

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-28 13:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_reminder_overrides",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("include_pm", sa.Boolean(), nullable=True),
        sa.Column("include_fae", sa.Boolean(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_reminder_override_version_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["customer_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_reminder_override_project"),
    )
    op.create_index(op.f("ix_project_reminder_overrides_organization_id"), "project_reminder_overrides", ["organization_id"])


def downgrade():
    op.drop_index(op.f("ix_project_reminder_overrides_organization_id"), table_name="project_reminder_overrides")
    op.drop_table("project_reminder_overrides")
