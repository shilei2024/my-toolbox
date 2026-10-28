"""customer project reminder policy and shared notification outbox

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-28 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_reminder_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("due_hour_local", sa.Integer(), nullable=False),
        sa.Column("pre_due_workdays", sa.Integer(), nullable=False),
        sa.Column("overdue_workdays", sa.Integer(), nullable=False),
        sa.Column("stale_manager_after_workdays", sa.Integer(), nullable=False),
        sa.Column("include_pm", sa.Boolean(), nullable=False),
        sa.Column("include_fae", sa.Boolean(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_reminder_policy_version_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_project_reminder_policy_org"),
    )
    op.create_index(op.f("ix_project_reminder_policies_organization_id"), "project_reminder_policies", ["organization_id"])

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("module_code", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("template_code", sa.String(length=64), nullable=False),
        sa.Column("template_data_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_outbox_idempotency"),
    )
    op.create_index(op.f("ix_notification_outbox_organization_id"), "notification_outbox", ["organization_id"])
    op.create_index("ix_notification_outbox_due", "notification_outbox", ["status", "next_attempt_at", "scheduled_for"])
    op.create_index("ix_notification_outbox_object", "notification_outbox", ["module_code", "object_type", "object_id"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("outbox_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("recipient_address", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outbox_id"], ["notification_outbox.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbox_id", "recipient_user_id", name="uq_notification_delivery_recipient"),
    )
    op.create_index(op.f("ix_notification_deliveries_outbox_id"), "notification_deliveries", ["outbox_id"])
    op.create_index("ix_notification_delivery_status", "notification_deliveries", ["status", "updated_at"])

    op.create_table(
        "notification_worker_heartbeats",
        sa.Column("worker_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scanned_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("worker_name"),
    )


def downgrade():
    op.drop_table("notification_worker_heartbeats")
    op.drop_index("ix_notification_delivery_status", table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_outbox_id"), table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_notification_outbox_object", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    op.drop_index(op.f("ix_notification_outbox_organization_id"), table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index(op.f("ix_project_reminder_policies_organization_id"), table_name="project_reminder_policies")
    op.drop_table("project_reminder_policies")
