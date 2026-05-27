from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.worker.scheduler import FairScheduler, PRIORITY_QUEUES, Priority, enqueue_run


@asynccontextmanager
async def _lock():
    yield


def _run(**overrides):
    defaults = {
        "id": uuid4(),
        "project_id": uuid4(),
        "trigger_type": "manual",
        "priority": 1,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _settings(total=2, per_project=1):
    return SimpleNamespace(
        max_concurrent_runs=total,
        max_concurrent_per_project=per_project,
    )


def _repo(*, active=0, project_active=0):
    repo = MagicMock()
    repo.scheduler_lock = MagicMock(side_effect=lambda: _lock())
    repo.count_active_or_enqueued = AsyncMock(return_value=active)
    repo.count_active_or_enqueued_by_project = AsyncMock(return_value=project_active)
    repo.mark_waiting = AsyncMock()
    repo.mark_enqueued = AsyncMock()
    repo.get_by_arq_job_id = AsyncMock(return_value=None)
    repo.find_waiting = AsyncMock(return_value=[])
    return repo


def _arq(job_id="job-1"):
    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id=job_id))
    return arq


@pytest.mark.asyncio
async def test_enqueue_marks_waiting_when_global_capacity_is_full():
    run = _run()
    repo = _repo(active=2)
    scheduler = FairScheduler(_arq(), repo, _settings(total=2, per_project=10))

    result = await scheduler.enqueue(run)

    assert result is False
    repo.mark_waiting.assert_awaited_once_with(run.id)


@pytest.mark.asyncio
async def test_enqueue_marks_waiting_when_project_capacity_is_full():
    run = _run()
    repo = _repo(active=0, project_active=1)
    scheduler = FairScheduler(_arq(), repo, _settings(total=10, per_project=1))

    result = await scheduler.enqueue(run)

    assert result is False
    repo.mark_waiting.assert_awaited_once_with(run.id)


@pytest.mark.asyncio
async def test_enqueue_uses_manual_priority_queue_and_records_metadata():
    run = _run(priority=0)
    repo = _repo()
    arq = _arq(job_id="job-high")
    scheduler = FairScheduler(arq, repo, _settings())

    result = await scheduler.enqueue(run, _defer_by=3)

    assert result is True
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[Priority.HIGH],
        _job_id=f"run:{run.id}",
        _defer_by=3,
    )
    repo.mark_enqueued.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_falls_back_to_medium_for_invalid_manual_priority():
    run = _run(priority=99)
    arq = _arq()
    scheduler = FairScheduler(arq, _repo(), _settings())

    assert await scheduler.enqueue(run) is True
    assert arq.enqueue_job.call_args.kwargs["_queue_name"] == PRIORITY_QUEUES[Priority.MEDIUM]


@pytest.mark.asyncio
async def test_enqueue_schedule_uses_low_priority_queue():
    run = _run(trigger_type="schedule", priority=0)
    arq = _arq()
    scheduler = FairScheduler(arq, _repo(), _settings())

    assert await scheduler.enqueue(run) is True
    assert arq.enqueue_job.call_args.kwargs["_queue_name"] == PRIORITY_QUEUES[Priority.LOW]


@pytest.mark.asyncio
async def test_enqueue_job_conflict_is_idempotent_for_same_enqueued_run():
    run = _run()
    repo = _repo()
    repo.get_by_arq_job_id = AsyncMock(
        return_value=SimpleNamespace(id=run.id, enqueued_at=object())
    )
    arq = _arq()
    arq.enqueue_job = AsyncMock(return_value=None)
    scheduler = FairScheduler(arq, repo, _settings())

    assert await scheduler.enqueue(run) is True
    repo.mark_waiting.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_job_conflict_marks_waiting_for_different_run():
    run = _run()
    repo = _repo()
    repo.get_by_arq_job_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    arq = _arq()
    arq.enqueue_job = AsyncMock(return_value=None)
    scheduler = FairScheduler(arq, repo, _settings())

    assert await scheduler.enqueue(run) is False
    repo.mark_waiting.assert_awaited_once()
    assert "arq job id conflict" in repo.mark_waiting.call_args.kwargs["reason"]


@pytest.mark.asyncio
async def test_try_dequeue_waiting_enqueues_until_capacity_is_full():
    first = _run()
    second = _run()
    repo = _repo()
    repo.find_waiting = AsyncMock(return_value=[first, second])
    repo.count_active_or_enqueued = AsyncMock(side_effect=[0, 2])
    scheduler = FairScheduler(_arq(), repo, _settings(total=2, per_project=10))

    result = await scheduler.try_dequeue_waiting()

    assert result == 1
    assert repo.mark_enqueued.await_count == 1


@pytest.mark.asyncio
async def test_enqueue_run_convenience_uses_fair_scheduler():
    run = _run()
    repo = _repo()
    arq = _arq()

    assert await enqueue_run(arq, repo, run, "manual", _settings()) is True
