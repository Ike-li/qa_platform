"""add pipeline collectors

Revision ID: 008
Revises: 007
Create Date: 2026-05-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_COLLECTORS = (
    "jsonb_build_array("
    "jsonb_build_object('plugin', 'junit', 'config', '{}'::jsonb, 'enabled', true)"
    ")"
)


def upgrade() -> None:
    op.add_column(
        "pipeline",
        sa.Column(
            "collectors",
            JSONB,
            nullable=False,
            server_default=sa.text(_DEFAULT_COLLECTORS),
        ),
    )


def downgrade() -> None:
    op.drop_column("pipeline", "collectors")
