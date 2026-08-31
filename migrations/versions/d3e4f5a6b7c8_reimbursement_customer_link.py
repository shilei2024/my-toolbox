"""link reimbursements to shared customers and normalize customer grades

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-31 02:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reimbursement_invoices") as batch_op:
        batch_op.add_column(sa.Column("customer_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_reimbursement_invoice_customer",
            "customers",
            ["customer_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_rb_invoice_customer",
        "reimbursement_invoices",
        ["customer_id"],
        unique=False,
    )

    # Old customer grades used A as the highest tier. Preserve that ordering in
    # the new 0-1/A/AA/AAA vocabulary.
    op.execute(
        sa.text(
            """
            UPDATE customers
            SET grade = CASE grade
                WHEN 'A' THEN 'AAA'
                WHEN 'B' THEN 'AA'
                WHEN 'C' THEN 'A'
                WHEN 'D' THEN '0-1'
                ELSE grade
            END
            WHERE grade IN ('A', 'B', 'C', 'D')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE reimbursement_invoices
            SET customer_level = CASE customer_level
                WHEN 'level 1' THEN 'A'
                WHEN 'level 2' THEN 'AA'
                WHEN 'level 3' THEN 'AAA'
                ELSE customer_level
            END
            WHERE customer_level IN ('level 1', 'level 2', 'level 3')
            """
        )
    )


def downgrade():
    op.execute(
        sa.text(
            """
            UPDATE reimbursement_invoices
            SET customer_level = CASE customer_level
                WHEN 'A' THEN 'level 1'
                WHEN 'AA' THEN 'level 2'
                WHEN 'AAA' THEN 'level 3'
                ELSE customer_level
            END
            WHERE customer_level IN ('A', 'AA', 'AAA')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE customers
            SET grade = CASE grade
                WHEN 'AAA' THEN 'A'
                WHEN 'AA' THEN 'B'
                WHEN 'A' THEN 'C'
                WHEN '0-1' THEN 'D'
                ELSE grade
            END
            WHERE grade IN ('0-1', 'A', 'AA', 'AAA')
            """
        )
    )
    op.drop_index("ix_rb_invoice_customer", table_name="reimbursement_invoices")
    with op.batch_alter_table("reimbursement_invoices") as batch_op:
        batch_op.drop_constraint(
            "fk_reimbursement_invoice_customer", type_="foreignkey"
        )
        batch_op.drop_column("customer_id")
