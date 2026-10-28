"""add design_win material opportunity type

Revision ID: c2d3e4f5a6b7
Revises: b9c0d1e2f3a4
Create Date: 2026-08-28 23:55:00
"""
from alembic import op


revision = "c2d3e4f5a6b7"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


NEW_CONSTRAINT = (
    "opportunity_type IN ('design_in', 'design_win', "
    "'matched_opportunity', 'competitive_opportunity')"
)
OLD_CONSTRAINT = (
    "opportunity_type IN ('design_in', 'matched_opportunity', 'competitive_opportunity')"
)


def upgrade():
    # 放宽机会类型约束以纳入 design_win（定点物料）
    op.drop_constraint("ck_material_opportunity_type", "project_materials", type_="check")
    op.create_check_constraint(
        "ck_material_opportunity_type", "project_materials", NEW_CONSTRAINT
    )


def downgrade():
    # 回滚前将 design_win 物料归入 design_in，避免违反旧约束
    op.execute(
        "UPDATE project_materials SET opportunity_type = 'design_in' "
        "WHERE opportunity_type = 'design_win'"
    )
    op.drop_constraint("ck_material_opportunity_type", "project_materials", type_="check")
    op.create_check_constraint(
        "ck_material_opportunity_type", "project_materials", OLD_CONSTRAINT
    )
