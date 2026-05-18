"""make audit_event.tenant_id nullable

Revision ID: 004
Revises: 003
Create Date: 2026-05-18

Background
----------
P1-8 regression: auth failure paths (login_failed, refresh_failed, logout
without a valid access token) cannot resolve a tenant_id and correctly pass
None.  The original NOT NULL constraint caused PG to raise IntegrityError,
which the global 500 handler caught — turning every 401/204 into a 500.

Audit completeness is a product requirement; the fix is to allow NULL
tenant_id so unauthenticated-path events are still recorded.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "event",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        nullable=True,
        schema="audit",
    )


def downgrade() -> None:
    # Cannot safely downgrade if any NULL tenant_id rows exist — doing so would
    # violate the NOT NULL constraint.  Ops must backfill or delete NULL rows
    # before running this downgrade.
    raise NotImplementedError(
        "Cannot downgrade: NULL tenant_id rows in audit.event would violate "
        "the NOT NULL constraint.  Backfill or remove those rows first."
    )
