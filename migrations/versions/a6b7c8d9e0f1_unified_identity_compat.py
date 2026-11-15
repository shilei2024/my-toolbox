"""Add account identity compatibility metadata, without changing legacy ownership."""
from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade():
    # Do not relax email/password constraints until every reader supports them.
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("auth_epoch", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(), nullable=True))
    for column in (
        sa.Column("identity_type", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("identifier", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    ):
        op.add_column("account_external_identities", column)
    # Existing provider subjects (including password-session fingerprints) are immutable.
    op.create_index("uq_identity_web_identifier", "account_external_identities", ["identifier"], unique=True,
                    postgresql_where=sa.text("provider = 'web_password'"), sqlite_where=sa.text("provider = 'web_password'"))
    op.create_index("uq_identity_web_account", "account_external_identities", ["user_id"], unique=True,
                    postgresql_where=sa.text("provider = 'web_password'"), sqlite_where=sa.text("provider = 'web_password'"))
    # SQLite ADD CONSTRAINT requires a parent-table rebuild. Keep its equivalent
    # checks in preflight; PostgreSQL can enforce the constraint without a rebuild.
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint("ck_identity_web_credential", "account_external_identities",
            "provider != 'web_password' OR (user_id IS NOT NULL AND identifier IS NOT NULL AND password_hash IS NOT NULL AND client_id = 'web')")
    op.add_column("account_mobile_sessions", sa.Column("auth_epoch", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("auth_migration_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("account_legacy_mappings",
        sa.Column("source_user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("account_external_identities.id"), nullable=True, unique=True),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("auth_migration_runs.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("source_user_id = account_id", name="ck_account_mapping_same_id"))


def downgrade():
    conn = op.get_bind()
    # Never silently destroy copied credentials, mappings, verification or revocations.
    guards = (
        "SELECT count(*) FROM account_legacy_mappings",
        "SELECT count(*) FROM auth_migration_runs",
        "SELECT count(*) FROM users WHERE auth_epoch != 0 OR email_verified_at IS NOT NULL OR updated_at IS NOT NULL",
        "SELECT count(*) FROM account_mobile_sessions WHERE auth_epoch != 0",
        "SELECT count(*) FROM account_external_identities WHERE identity_type != 'legacy' OR identifier IS NOT NULL OR password_hash IS NOT NULL OR verified_at IS NOT NULL OR updated_at IS NOT NULL OR last_login_at IS NOT NULL OR provider = 'web_password'",
    )
    if any(conn.execute(sa.text(query)).scalar_one() for query in guards):
        raise RuntimeError("auth_downgrade_has_data_use_compatible_code_rollback")
    op.drop_table("account_legacy_mappings")
    op.drop_table("auth_migration_runs")
    op.drop_column("account_mobile_sessions", "auth_epoch")
    if conn.dialect.name == "postgresql":
        op.drop_constraint("ck_identity_web_credential", "account_external_identities", type_="check")
    op.drop_index("uq_identity_web_account", table_name="account_external_identities")
    op.drop_index("uq_identity_web_identifier", table_name="account_external_identities")
    for name in ("last_login_at", "updated_at", "verified_at", "password_hash", "identifier", "identity_type"):
        op.drop_column("account_external_identities", name)
    for name in ("updated_at", "auth_epoch", "email_verified_at"):
        op.drop_column("users", name)
