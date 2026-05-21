"""remove deleted_at from non-soft-deletable tables

Revision ID: 006
Revises: 005
Create Date: 2026-05-22

§5.2: Migration 005 added deleted_at to ALL business tables, but
TestResult, RunEvent, and NotificationLog have __soft_deletable__ = False
(physical deletes). The deleted_at column and partial indexes on these
tables are semantically wrong and waste storage.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["test_result", "run_event", "notification_log"]

PARTIAL_INDEXES = ["test_result", "run_event"]


def upgrade() -> None:
    for table in PARTIAL_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_active")

    for table in TABLES:
        op.drop_column(table, "deleted_at")


def downgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    for table in PARTIAL_INDEXES:
        cols = "(run_id)" if table != "notification_log" else "(id)"
        op.execute(
            f"CREATE INDEX ix_{table}_active ON {table} {cols} WHERE deleted_at IS NULL"
        )
