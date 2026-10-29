"""Revocable mobile identities and atomic invoice upload receipts."""
from alembic import op
import sqlalchemy as sa

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("account_external_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "client_id", "subject", name="uq_external_identity_subject"))
    op.create_index("ix_account_external_identities_user_id", "account_external_identities", ["user_id"])
    op.create_table("account_binding_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_account_binding_challenges_user_id", "account_binding_challenges", ["user_id"])
    op.create_table("account_mobile_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("account_external_identities.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_account_mobile_sessions_identity_id", "account_mobile_sessions", ["identity_id"])
    op.create_table("account_mobile_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_account_mobile_audits_user_id", "account_mobile_audits", ["user_id"])
    op.create_table("reimbursement_upload_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("reimbursement_invoices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_rb_upload_receipt_key"))
    with op.batch_alter_table("reimbursement_attachments") as batch:
        batch.add_column(sa.Column("content_sha256", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_rb_attachment_content", ["owner_type", "owner_id", "content_sha256"])


def downgrade():
    op.drop_table("reimbursement_upload_receipts")
    for table in ("account_mobile_sessions", "account_binding_challenges", "account_mobile_audits", "account_external_identities"):
        op.drop_table(table)
    with op.batch_alter_table("reimbursement_attachments") as batch:
        batch.drop_constraint("uq_rb_attachment_content", type_="unique")
        batch.drop_column("content_sha256")
