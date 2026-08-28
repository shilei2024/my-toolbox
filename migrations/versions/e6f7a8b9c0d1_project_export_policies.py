"""project export policies

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-28 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_export_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("allowed_roles_json", sa.Text(), nullable=False),
        sa.Column("include_prices", sa.Boolean(), nullable=False),
        sa.Column("max_projects", sa.Integer(), nullable=False),
        sa.Column("max_rows", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("max_projects > 0 AND max_projects <= 10000", name="ck_project_export_max_projects"),
        sa.CheckConstraint("max_rows > 0 AND max_rows <= 100000", name="ck_project_export_max_rows"),
        sa.CheckConstraint("version > 0", name="ck_project_export_policy_version_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_project_export_policy_org"),
    )
    op.create_index(
        op.f("ix_project_export_policies_organization_id"),
        "project_export_policies",
        ["organization_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_project_export_policies_organization_id"), table_name="project_export_policies")
    op.drop_table("project_export_policies")
