"""Unit tests for qaplatform.engine.reclaim.reclaim_worker_lost.

P1 fix: scheduler periodic task must mark non-terminal runs as failed when
their worker's heartbeat key has expired in Redis (TTL 90s, refreshed every
30s). The mark_worker_lost UPDATE is conditional, so a run that just got
re-claimed or already finished is left untouched.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.engine.reclaim import HEARTBEAT_KEY, reclaim_worker_lost
from qaplatform.infra.database.models import RunStatusEnum


def _fake_run(*, worker_id: str | None = "worker-a", execution_id: str | None = "ctr-1",
              status: RunStatusEnum = RunStatusEnum.RUNNING):
    run = MagicMock()
    run.id = uuid4()
    run.worker_id = worker_id
    run.execution_id = execution_id
    run.status = status
    return run


@pytest.fixture
def run_repo():
    repo = MagicMock()
    repo.find_active_with_worker = AsyncMock(return_value=[])
    repo.mark_worker_lost = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def backend():
    bk = MagicMock()
    bk.cleanup = AsyncMock()
    return bk


@pytest.mark.asyncio
async def test_no_active_runs_is_noop(run_repo, backend):
    redis = AsyncMock()
    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)
    assert n == 0
    run_repo.mark_worker_lost.assert_not_awaited()
    backend.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_alive_heartbeat_skips_run(run_repo, backend):
    run = _fake_run()
    run_repo.find_active_with_worker.return_value = [run]
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=1)

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)

    assert n == 0
    redis.exists.assert_awaited_once_with(HEARTBEAT_KEY.format(worker_id="worker-a"))
    run_repo.mark_worker_lost.assert_not_awaited()
    backend.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_heartbeat_marks_failed_and_cleans_container(run_repo, backend):
    run = _fake_run()
    run_repo.find_active_with_worker.return_value = [run]
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)

    assert n == 1
    run_repo.mark_worker_lost.assert_awaited_once()
    kwargs = run_repo.mark_worker_lost.call_args.kwargs
    assert kwargs["worker_id"] == "worker-a"
    assert "worker_lost" in kwargs["message"]
    # status_change event published with previous=running
    redis.xadd.assert_awaited()
    # Orphan container forced removed
    backend.cleanup.assert_awaited_once_with("ctr-1")


@pytest.mark.asyncio
async def test_expired_without_execution_id_skips_cleanup(run_repo, backend):
    run = _fake_run(execution_id=None)
    run_repo.find_active_with_worker.return_value = [run]
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)

    assert n == 1
    run_repo.mark_worker_lost.assert_awaited_once()
    backend.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_worker_lost_returns_false_skips_event_and_cleanup(run_repo, backend):
    """Run was re-claimed / completed between scan and update — leave it alone."""
    run = _fake_run()
    run_repo.find_active_with_worker.return_value = [run]
    run_repo.mark_worker_lost = AsyncMock(return_value=False)
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)

    assert n == 0
    redis.xadd.assert_not_awaited()
    backend.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_probe_failure_is_fail_open(run_repo, backend):
    """Transient Redis error during heartbeat probe must not kill healthy runs."""
    run = _fake_run()
    run_repo.find_active_with_worker.return_value = [run]
    redis = AsyncMock()
    redis.exists = AsyncMock(side_effect=RuntimeError("redis down"))

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)

    assert n == 0
    run_repo.mark_worker_lost.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_block_status_transition(run_repo, backend):
    run = _fake_run()
    run_repo.find_active_with_worker.return_value = [run]
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)
    backend.cleanup = AsyncMock(side_effect=RuntimeError("docker socket dead"))

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)

    assert n == 1
    run_repo.mark_worker_lost.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_with_null_worker_id_is_skipped(run_repo, backend):
    run = _fake_run(worker_id=None)
    run_repo.find_active_with_worker.return_value = [run]
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=backend)

    assert n == 0
    redis.exists.assert_not_awaited()
    run_repo.mark_worker_lost.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_backend_skips_cleanup_but_still_marks_failed(run_repo):
    run = _fake_run()
    run_repo.find_active_with_worker.return_value = [run]
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)

    n = await reclaim_worker_lost(run_repo=run_repo, redis=redis, backend=None)

    assert n == 1
    run_repo.mark_worker_lost.assert_awaited_once()
