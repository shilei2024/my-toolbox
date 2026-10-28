"""Separate invoice accounting from retention and printing."""
from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reimbursement_invoices") as batch:
        for name, length, default in (("inclusion_policy", 16, "expense"), ("document_kind", 16, "invoice"), ("occurrence_month", 7, ""), ("settlement_month", 7, "")):
            batch.add_column(sa.Column(name, sa.String(length), nullable=False, server_default=default))
        for name in ("print_selected", "amount_confirmed"):
            batch.add_column(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("reimbursement_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_type", sa.String(8), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_reimbursement_audits_period_id", "reimbursement_audits", ["period_id"])


def downgrade():
    # Only in a disposable verification DB. Production must retain policy data.
    op.drop_index("ix_reimbursement_audits_period_id", "reimbursement_audits")
    op.drop_table("reimbursement_audits")
    with op.batch_alter_table("reimbursement_invoices") as batch:
        for name in ("amount_confirmed", "print_selected", "settlement_month", "occurrence_month", "document_kind", "inclusion_policy"):
            batch.drop_column(name)
