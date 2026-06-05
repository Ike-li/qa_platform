from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from qaplatform.domain.models.run import RunStatus
from qaplatform.infra.database.models import RunStatusEnum
from qaplatform.infra.database.repositories.run_repo import RunRepository
from qaplatform.infra.database.repositories.run_status_helpers import (
    coerce_run_status_enum,
    run_status_enums,
)


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


def _rowcount_result(value: int):
    result = MagicMock()
    result.rowcount = value
    return result


def _scalars_result(items: list | None = None):
    result = MagicMock()
    result.scalars.return_value.all.return_value = items or []
    return result


def _rows_result(items: list | None = None):
    result = MagicMock()
    result.all.return_value = items or []
    return result


def _one_result(item):
    result = MagicMock()
    result.one.return_value = item
    return result


def test_run_status_helpers_accept_domain_infra_and_string_statuses():
    assert coerce_run_status_enum(RunStatus.RUNNING) == RunStatusEnum.RUNNING
    assert coerce_run_status_enum(RunStatusEnum.COLLECTING) == RunStatusEnum.COLLECTING
    assert coerce_run_status_enum("failed") == RunStatusEnum.FAILED
    assert run_status_enums(
        [RunStatus.PREPARING, RunStatusEnum.RUNNING, "collecting"]
    ) == {
        RunStatusEnum.PREPARING,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    }


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


@pytest.mark.asyncio
async def test_reclaimer_active_worker_scan_uses_in_flight_statuses():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalars_result())
    repo = RunRepository(session)

    assert await repo.find_active_with_worker() == []

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    status_param = _postcompile_param_name(sql, "run.status")
    assert set(params[status_param]) == {
        RunStatusEnum.PREPARING,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    }
    assert RunStatusEnum.QUEUED not in params[status_param]
    assert "run.worker_id IS NOT NULL" in sql
    assert "run.deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_reclaimer_pipeline_deadline_uses_pipeline_timeout_floor_and_buffer():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalars_result())
    repo = RunRepository(session)

    assert await repo.find_past_pipeline_deadline(
        [RunStatus.RUNNING, "collecting"],
        buffer_seconds=42,
    ) == []

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    status_param = _postcompile_param_name(sql, "run.status")
    assert set(params[status_param]) == {
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    }
    assert params["buffer_seconds"] == 42
    assert "JOIN pipeline ON pipeline.id = run.pipeline_id" in sql
    assert "GREATEST(pipeline.timeout_seconds, 1800)" in sql
    assert "run.deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_maintenance_counts_coerce_domain_infra_and_string_statuses():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_result(9))
    repo = RunRepository(session)

    assert await repo.count_by_statuses(
        [RunStatus.QUEUED, RunStatusEnum.RUNNING, "collecting"]
    ) == 9

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    status_param = _postcompile_param_name(sql, "run.status")
    assert set(params[status_param]) == {
        RunStatusEnum.QUEUED,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    }
    assert "count(*)" in sql
    assert "run.deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_maintenance_delete_terminal_older_than_only_targets_terminal_runs():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_rowcount_result(3))
    repo = RunRepository(session)
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)

    assert await repo.delete_terminal_older_than(cutoff=cutoff) == 3

    statement = session.execute.await_args.args[0]
    sql = _postgres_sql(statement)
    params = statement.compile(dialect=postgresql.dialect()).params

    status_param = _postcompile_param_name(sql, "run.status")
    cutoff_param = _bound_param_name(sql, "run.finished_at <")
    assert set(params[status_param]) == {
        RunStatusEnum.DONE,
        RunStatusEnum.FAILED,
        RunStatusEnum.CANCELLED,
        RunStatusEnum.TIMEOUT,
    }
    assert params[cutoff_param] == cutoff
    assert "run.finished_at < " in sql
    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_list_trend_points_adds_git_ref_filter_when_requested():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(0), _rows_result()])
    repo = RunRepository(session)
    project_id = uuid4()
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)

    rows, total = await repo.list_trend_points(
        project_id=project_id,
        cutoff=cutoff,
        offset=0,
        limit=30,
        git_ref="release/2026.06",
    )

    assert rows == []
    assert total == 0
    assert session.execute.await_count == 2
    for call in session.execute.await_args_list:
        statement = call.args[0]
        sql = _postgres_sql(statement)
        params = statement.compile(dialect=postgresql.dialect()).params
        git_ref_param = _bound_param_name(sql, "run.git_ref =")
        assert params[git_ref_param] == "release/2026.06"
        assert "run.project_id = " in sql
        assert "run.created_at >= " in sql
        assert "run.deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_release_summary_calculates_flaky_adjusted_and_test_deltas():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _one_result(
                SimpleNamespace(total_runs=4, passed_runs=3, failed_runs=1),
            ),
            _rows_result([
                SimpleNamespace(
                    suite="checkout",
                    name="test_new_failure",
                    total_count=2,
                    passed_count=0,
                    failed_count=2,
                ),
                SimpleNamespace(
                    suite="checkout",
                    name="test_flaky_known",
                    total_count=2,
                    passed_count=1,
                    failed_count=1,
                ),
                SimpleNamespace(
                    suite="checkout",
                    name="test_stable_pass",
                    total_count=2,
                    passed_count=2,
                    failed_count=0,
                ),
            ]),
            _rows_result([
                SimpleNamespace(
                    suite="checkout",
                    name="test_recovered",
                    total_count=1,
                    passed_count=0,
                    failed_count=1,
                ),
                SimpleNamespace(
                    suite="checkout",
                    name="test_flaky_known",
                    total_count=1,
                    passed_count=0,
                    failed_count=1,
                ),
            ]),
        ]
    )
    repo = RunRepository(session)

    summary = await repo.get_release_summary(
        project_id=uuid4(),
        cutoff=datetime(2026, 6, 1, tzinfo=timezone.utc),
        git_ref="release/2026.06",
        baseline_git_ref="main",
    )

    assert summary == {
        "git_ref": "release/2026.06",
        "baseline_git_ref": "main",
        "total_runs": 4,
        "passed_runs": 3,
        "failed_runs": 1,
        "raw_pass_rate": 0.75,
        "flaky_adjusted_pass_rate": 0.5,
        "new_failing_tests": [
            {
                "suite": "checkout",
                "name": "test_new_failure",
                "failed_count": 2,
            }
        ],
        "recovered_tests": [
            {
                "suite": "checkout",
                "name": "test_recovered",
                "failed_count": 1,
            }
        ],
    }
