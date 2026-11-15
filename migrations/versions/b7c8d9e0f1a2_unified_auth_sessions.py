"""Shared revocable web sessions and authentication audit."""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("account_web_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("auth_epoch", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_account_web_sessions_user_id", "account_web_sessions", ["user_id"])
    op.create_table("account_auth_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_account_auth_audits_user_id", "account_auth_audits", ["user_id"])


def downgrade():
    conn = op.get_bind()
    for table in ("account_web_sessions", "account_auth_audits"):
        if conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("auth_sessions_in_use_keep_compatible_code_and_schema")
    op.drop_table("account_auth_audits")
    op.drop_table("account_web_sessions")
