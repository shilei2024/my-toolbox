"""add project timeline comments and mentions

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-28 22:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["customer_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_project_comment_idempotency"),
    )
    op.create_index("ix_project_comments_organization_id", "project_comments", ["organization_id"], unique=False)
    op.create_index("ix_project_comment_project_time", "project_comments", ["project_id", "created_at"], unique=False)
    op.create_table(
        "project_comment_mentions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("comment_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["project_comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comment_id", "user_id", name="uq_project_comment_mention_user"),
    )
    op.create_index("ix_project_comment_mentions_comment_id", "project_comment_mentions", ["comment_id"], unique=False)
    op.create_index("ix_project_comment_mentions_organization_id", "project_comment_mentions", ["organization_id"], unique=False)
    op.create_index("ix_project_comment_mention_user", "project_comment_mentions", ["organization_id", "user_id", "created_at"], unique=False)


def downgrade():
    op.drop_index("ix_project_comment_mention_user", table_name="project_comment_mentions")
    op.drop_index("ix_project_comment_mentions_organization_id", table_name="project_comment_mentions")
    op.drop_index("ix_project_comment_mentions_comment_id", table_name="project_comment_mentions")
    op.drop_table("project_comment_mentions")
    op.drop_index("ix_project_comment_project_time", table_name="project_comments")
    op.drop_index("ix_project_comments_organization_id", table_name="project_comments")
    op.drop_table("project_comments")
