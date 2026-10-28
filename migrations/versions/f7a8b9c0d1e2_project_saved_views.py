"""project saved filter views

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-28 22:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_saved_views",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("namespace_key", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("normalized_name", sa.String(length=80), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('personal', 'organization')",
            name="ck_project_saved_view_visibility",
        ),
        sa.CheckConstraint("version > 0", name="ck_project_saved_view_version_positive"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "namespace_key", "normalized_name",
            name="uq_project_saved_view_namespace_name",
        ),
    )
    op.create_index(
        op.f("ix_project_saved_views_organization_id"),
        "project_saved_views",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_saved_view_org_namespace",
        "project_saved_views",
        ["organization_id", "namespace_key"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_project_saved_view_org_namespace", table_name="project_saved_views")
    op.drop_index(op.f("ix_project_saved_views_organization_id"), table_name="project_saved_views")
    op.drop_table("project_saved_views")
