"""classify project materials for market scope

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-08-28 23:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


OPPORTUNITY_TYPES = (
    "design_in",
    "matched_opportunity",
    "competitive_opportunity",
)


def upgrade():
    op.add_column(
        "project_materials",
        sa.Column(
            "opportunity_type",
            sa.String(length=32),
            nullable=False,
            server_default="design_in",
        ),
    )
    op.create_check_constraint(
        "ck_material_opportunity_type",
        "project_materials",
        "opportunity_type IN ('design_in', 'matched_opportunity', 'competitive_opportunity')",
    )
    op.create_index(
        "ix_material_project_opportunity",
        "project_materials",
        ["project_id", "opportunity_type"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_material_project_opportunity", table_name="project_materials")
    op.drop_constraint(
        "ck_material_opportunity_type", "project_materials", type_="check"
    )
    op.drop_column("project_materials", "opportunity_type")
