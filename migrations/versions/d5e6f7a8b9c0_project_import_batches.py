"""project import batches and rows

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-28 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("mapping_json", sa.Text(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("error_rows", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_import_batches_organization_id"), "project_import_batches", ["organization_id"])
    op.create_index("ix_project_import_org_created", "project_import_batches", ["organization_id", "created_at"])
    op.create_table(
        "project_import_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("customer_was_created", sa.Boolean(), nullable=False),
        sa.Column("project_version_at_create", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["project_import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["customer_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_project_import_batch_row"),
    )
    op.create_index(op.f("ix_project_import_rows_batch_id"), "project_import_rows", ["batch_id"])
    op.create_index(op.f("ix_project_import_rows_organization_id"), "project_import_rows", ["organization_id"])
    op.create_index("ix_project_import_row_batch_status", "project_import_rows", ["batch_id", "status"])


def downgrade():
    op.drop_index("ix_project_import_row_batch_status", table_name="project_import_rows")
    op.drop_index(op.f("ix_project_import_rows_organization_id"), table_name="project_import_rows")
    op.drop_index(op.f("ix_project_import_rows_batch_id"), table_name="project_import_rows")
    op.drop_table("project_import_rows")
    op.drop_index("ix_project_import_org_created", table_name="project_import_batches")
    op.drop_index(op.f("ix_project_import_batches_organization_id"), table_name="project_import_batches")
    op.drop_table("project_import_batches")
