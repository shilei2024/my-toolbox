"""Email actions/jobs and genuine passwordless accounts."""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite" and conn.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("sqlite_parent_rebuild_requires_offline_rehearsal_with_fk_check")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", existing_type=sa.String(255), nullable=True)
        batch.alter_column("password_hash", existing_type=sa.String(255), nullable=True)
    for column in (sa.Column("source_session_hash", sa.String(64)), sa.Column("auth_epoch", sa.Integer()),
                   sa.Column("prepared_subject", sa.String(128)), sa.Column("confirmation_hash", sa.String(64))):
        op.add_column("account_binding_challenges", column)
    op.create_index("uq_binding_confirmation_hash", "account_binding_challenges", ["confirmation_hash"], unique=True)
    op.create_table("account_action_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("target_email", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("auth_epoch", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_account_action_tokens_user_id", "account_action_tokens", ["user_id"])
    op.create_table("account_mail_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("target_email", sa.String(255), nullable=False),
        sa.Column("auth_epoch", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim", sa.String(64), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_account_mail_jobs_user_id", "account_mail_jobs", ["user_id"])
    op.create_index("ix_account_mail_jobs_status", "account_mail_jobs", ["status"])


def downgrade():
    raise RuntimeError("account_security_migration_requires_forward_fix_preserve_credentials")
