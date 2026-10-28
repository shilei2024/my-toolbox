"""customer project commercial fields

Revision ID: f1a2b3c4d5e6
Revises: 8904db6a3fa5
Create Date: 2026-08-27 23:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "8904db6a3fa5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("customer_projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("product_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("annual_usage", sa.Numeric(precision=18, scale=4), nullable=True))

    with op.batch_alter_table("project_materials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("machine_quantity", sa.Numeric(precision=18, scale=4), nullable=True))
        batch_op.add_column(sa.Column("fx_rate_usd_cny", sa.Numeric(precision=18, scale=6), nullable=True))
        batch_op.add_column(sa.Column("unit_price_usd", sa.Numeric(precision=18, scale=6), nullable=True))
        batch_op.add_column(
            sa.Column("unit_price_cny_tax_included", sa.Numeric(precision=18, scale=6), nullable=True)
        )
        batch_op.add_column(sa.Column("price_updated_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_project_materials_price_updated_by_user_id_users",
            "users",
            ["price_updated_by_user_id"],
            ["id"],
        )
        batch_op.add_column(sa.Column("price_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("project_materials", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_project_materials_price_updated_by_user_id_users", type_="foreignkey"
        )
        batch_op.drop_column("price_updated_at")
        batch_op.drop_column("price_updated_by_user_id")
        batch_op.drop_column("unit_price_cny_tax_included")
        batch_op.drop_column("unit_price_usd")
        batch_op.drop_column("fx_rate_usd_cny")
        batch_op.drop_column("machine_quantity")

    with op.batch_alter_table("customer_projects", schema=None) as batch_op:
        batch_op.drop_column("annual_usage")
        batch_op.drop_column("product_name")
