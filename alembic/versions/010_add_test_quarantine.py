"""add test quarantine

Revision ID: 010
Revises: 009
Create Date: 2026-06-16 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create test_quarantine table."""
    op.create_table(
        'test_quarantine',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('suite', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('project_id', 'suite', 'name', name='uq_test_quarantine_project_suite_name')
    )

    # Indexes for performance
    op.create_index('idx_test_quarantine_project', 'test_quarantine', ['project_id'])


def downgrade() -> None:
    """Drop test_quarantine table."""
    op.drop_index('idx_test_quarantine_project', table_name='test_quarantine')
    op.drop_table('test_quarantine')
