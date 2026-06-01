from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from qaplatform.infra.database.repositories.project_repo import ScheduleRepository


def _postgres_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _bound_param_name(sql: str, expression: str) -> str:
    match = re.search(rf"{re.escape(expression)} %\(([^)]+)\)s", sql)
    assert match is not None, sql
    return match.group(1)


def _scalars_result(items: list | None = None):
    result = MagicMock()
    result.scalars.return_value.all.return_value = items or []
    return result


@pytest.mark.asyncio
async def test_find_due_schedules_uses_skip_locked_schedule_row_lock():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalars_result())
    repo = ScheduleRepository(session)
    now = datetime(2026, 5, 30, 8, 0, tzinfo=timezone.utc)

    assert await repo.find_due_schedules(now, limit=23) == []

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    assert "FOR UPDATE OF schedule SKIP LOCKED" in sql
    assert "schedule.enabled IS true" in sql
    assert "schedule.deleted_at IS NULL" in sql
    assert "schedule.next_run_at <= " in sql
    assert "ORDER BY schedule.next_run_at" in sql

    due_at_param = _bound_param_name(sql, "schedule.next_run_at <=")
    limit_param = _bound_param_name(sql, "LIMIT")
    assert params == {
        due_at_param: now,
        limit_param: 23,
    }
