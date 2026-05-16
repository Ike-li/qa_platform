"""Add environment resource fields

Revision ID: 002
Revises: 001
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "environment",
        sa.Column("memory_mb", sa.Integer(), nullable=False, server_default=sa.text("512")),
    )
    op.add_column(
        "environment",
        sa.Column("cpu_cores", sa.Float(), nullable=False, server_default=sa.text("1.0")),
    )
    op.execute(
        """
        UPDATE environment
        SET
            memory_mb = COALESCE((resource_limits ->> 'memory_mb')::integer, memory_mb),
            cpu_cores = COALESCE((resource_limits ->> 'cpu_cores')::double precision, cpu_cores)
        WHERE resource_limits ? 'memory_mb'
           OR resource_limits ? 'cpu_cores'
        """
    )


def downgrade() -> None:
    op.drop_column("environment", "cpu_cores")
    op.drop_column("environment", "memory_mb")
