"""Keep a one-way password hash on pending registrations."""
from alembic import op
import sqlalchemy as sa

revision = 'e0f1a2b3c4d5'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('account_registrations', sa.Column('password_hash',sa.String(255),nullable=True))


def downgrade():
    raise RuntimeError('registration_password_requires_forward_fix_preserve_credentials')
