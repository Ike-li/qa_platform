"""add soft delete deleted_at to all business tables

Revision ID: 005
Revises: 004
Create Date: 2026-05-18

Background
----------
Architecture docs require soft-delete support (deleted_at column) on all
business tables.  This enables recoverable deletes and audit-friendly
data lifecycle management.

Tables affected: 15 Base-inheriting tables.
Tables excluded: audit.event (AuditBase, separate DeclarativeBase).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "tenant",
    "app_user",
    "api_token",
    "project",
    "environment",
    "pipeline",
    "credential",
    "run",
    "test_result",
    "artifact",
    "run_event",
    "schedule",
    "notification_rule",
    "notification_log",
    "project_member",
]

# High-volume tables that benefit from partial indexes
INDEXED_TABLES = ["run", "test_result", "run_event"]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    for table in INDEXED_TABLES:
        op.execute(
            f"CREATE INDEX ix_{table}_active ON {table} (id) WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    for table in INDEXED_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_active")

    for table in TABLES:
        op.drop_column(table, "deleted_at")
