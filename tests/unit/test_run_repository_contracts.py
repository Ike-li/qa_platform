from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from qaplatform.infra.database.models import RunStatusEnum
from qaplatform.infra.database.repositories.run_repo import RunRepository


def _postgres_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _bound_param_name(sql: str, expression: str) -> str:
    match = re.search(rf"{re.escape(expression)} %\(([^)]+)\)s", sql)
    assert match is not None, sql
    return match.group(1)


def _postcompile_param_name(sql: str, expression: str) -> str:
    match = re.search(
        rf"{re.escape(expression)} IN \(__\[POSTCOMPILE_([^\]]+)\]\)",
        sql,
    )
    assert match is not None, sql
    return match.group(1)


def _assert_active_status_params(
    *,
    sql: str,
    params: dict,
    expected_extra_params: dict | None = None,
) -> None:
    active_status_param = _postcompile_param_name(sql, "run.status")
    queued_status_param = _bound_param_name(sql, "run.status =")
    expected_extra_params = expected_extra_params or {}

    assert set(params) == {
        active_status_param,
        queued_status_param,
        *expected_extra_params,
    }
    assert set(params[active_status_param]) == {
        RunStatusEnum.PREPARING,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    }
    assert len(params[active_status_param]) == 3
    assert params[queued_status_param] == RunStatusEnum.QUEUED
    for param_name, expected_value in expected_extra_params.items():
        assert params[param_name] == expected_value


def _scalar_result(value: int):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _scalars_result(items: list | None = None):
    result = MagicMock()
    result.scalars.return_value.all.return_value = items or []
    return result


@pytest.mark.asyncio
async def test_find_waiting_uses_skip_locked_row_lock_for_dequeue_races():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalars_result())
    repo = RunRepository(session)

    assert await repo.find_waiting(limit=17) == []

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    assert "FOR UPDATE OF run SKIP LOCKED" in sql
    assert "run.status = " in sql
    assert "run.enqueued_at IS NULL" in sql
    assert "run.deleted_at IS NULL" in sql
    assert "ORDER BY run.priority, run.created_at" in sql

    status_param = _bound_param_name(sql, "run.status =")
    limit_param = _bound_param_name(sql, "LIMIT")
    assert params == {
        status_param: RunStatusEnum.QUEUED,
        limit_param: 17,
    }


@pytest.mark.asyncio
async def test_scheduler_global_capacity_count_includes_active_and_enqueued_runs():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_result(4))
    repo = RunRepository(session)

    assert await repo.count_active_or_enqueued() == 4

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    assert "count(*)" in sql
    assert "run.deleted_at IS NULL" in sql
    assert "run.enqueued_at IS NOT NULL" in sql
    assert "run.status = " in sql
    _assert_active_status_params(sql=sql, params=params)


@pytest.mark.asyncio
async def test_scheduler_project_capacity_count_keeps_project_scope():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_result(2))
    repo = RunRepository(session)
    project_id = uuid4()

    assert await repo.count_active_or_enqueued_by_project(project_id) == 2

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    assert "run.project_id = " in sql
    assert "run.deleted_at IS NULL" in sql
    assert "run.enqueued_at IS NOT NULL" in sql
    project_param = _bound_param_name(sql, "run.project_id =")
    _assert_active_status_params(
        sql=sql,
        params=params,
        expected_extra_params={project_param: project_id},
    )


@pytest.mark.asyncio
async def test_waiting_capacity_count_excludes_already_enqueued_runs():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_result(6))
    repo = RunRepository(session)

    assert await repo.count_queued_waiting() == 6

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    assert "run.deleted_at IS NULL" in sql
    assert "run.enqueued_at IS NULL" in sql
    status_param = _bound_param_name(sql, "run.status =")
    assert params == {status_param: RunStatusEnum.QUEUED}
