"""Provider-independent account bindings and revocable mobile sessions."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from extensions import db
from models import utcnow


class ExternalIdentity(db.Model):
    __tablename__ = "account_external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "client_id", "subject", name="uq_external_identity_subject"),
        Index("uq_identity_web_identifier", "identifier", unique=True,
              postgresql_where=text("provider = 'web_password'"),
              sqlite_where=text("provider = 'web_password'")),
        Index("uq_identity_web_account", "user_id", unique=True,
              postgresql_where=text("provider = 'web_password'"),
              sqlite_where=text("provider = 'web_password'")),
        CheckConstraint("provider != 'web_password' OR (user_id IS NOT NULL AND identifier IS NOT NULL AND password_hash IS NOT NULL AND client_id = 'web')",
                        name="ck_identity_web_credential"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy", server_default="legacy")
    identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BindingChallenge(db.Model):
    __tablename__ = "account_binding_challenges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prepared_subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)


class MobileSession(db.Model):
    __tablename__ = "account_mobile_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(ForeignKey("account_external_identities.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    auth_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class AuthMigrationRun(db.Model):
    __tablename__ = "auth_migration_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AccountLegacyMapping(db.Model):
    __tablename__ = "account_legacy_mappings"
    __table_args__ = (CheckConstraint("source_user_id = account_id", name="ck_account_mapping_same_id"),)
    source_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    identity_id: Mapped[int | None] = mapped_column(ForeignKey("account_external_identities.id"), nullable=True, unique=True)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("auth_migration_runs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class MobileAccountAudit(db.Model):
    __tablename__ = "account_mobile_audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
