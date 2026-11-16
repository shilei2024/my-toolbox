"""Email ownership before account creation; compatible existing mail jobs."""
from alembic import op
import sqlalchemy as sa

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("account_registrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("return_to", sa.String(1024)),
        sa.Column("token_hash", sa.String(64), unique=True),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("last_requested_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    with op.batch_alter_table("account_mail_jobs") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("registration_id", sa.Integer(),
            sa.ForeignKey("account_registrations.id", name="fk_auth_mail_registration")))
        batch.create_index("ix_account_mail_jobs_registration_id", ["registration_id"])
        batch.create_check_constraint("ck_auth_mail_recipient_owner",
            "(purpose = 'register' AND user_id IS NULL AND registration_id IS NOT NULL) OR "
            "(purpose != 'register' AND user_id IS NOT NULL AND registration_id IS NULL)")


def downgrade():
    raise RuntimeError("verified_registration_requires_forward_fix_preserve_accounts")
