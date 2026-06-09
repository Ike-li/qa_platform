"""add report share tokens

Revision ID: 009
Revises: 008
Create Date: 2026-06-09 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create report_share_tokens table for temporary report sharing."""
    op.create_table(
        'report_share_token',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token', sa.String(255), nullable=False, unique=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('access_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_access_count', sa.Integer, nullable=True),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['run.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], ondelete='CASCADE'),
    )

    # Indexes for performance
    op.create_index('idx_report_share_token_token', 'report_share_token', ['token'])
    op.create_index('idx_report_share_token_run_id', 'report_share_token', ['run_id'])
    op.create_index('idx_report_share_token_expires_at', 'report_share_token', ['expires_at'])


def downgrade() -> None:
    """Drop report_share_tokens table."""
    op.drop_index('idx_report_share_token_expires_at', table_name='report_share_token')
    op.drop_index('idx_report_share_token_run_id', table_name='report_share_token')
    op.drop_index('idx_report_share_token_token', table_name='report_share_token')
    op.drop_table('report_share_token')
