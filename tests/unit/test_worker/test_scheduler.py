from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.worker.scheduler import (
    PRIORITY_QUEUES,
    FairScheduler,
    Priority,
    enqueue_run,
)


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


def _assert_mark_enqueued(repo, run_id, *, queue_name: str, arq_job_id: str) -> None:
    repo.mark_enqueued.assert_awaited_once()
    mark_args = repo.mark_enqueued.await_args
    enqueued_at = mark_args.kwargs["enqueued_at"]
    assert mark_args.args == (run_id,)
    assert mark_args.kwargs == {
        "queue_name": queue_name,
        "arq_job_id": arq_job_id,
        "enqueued_at": enqueued_at,
    }
    assert enqueued_at.tzinfo is not None


@pytest.mark.asyncio
async def test_enqueue_marks_waiting_when_global_capacity_is_full():
    run = _run()
    repo = _repo(active=2)
    arq = _arq()
    scheduler = FairScheduler(arq, repo, _settings(total=2, per_project=10))

    result = await scheduler.enqueue(run)

    assert result is False
    repo.count_active_or_enqueued.assert_awaited_once_with()
    repo.count_active_or_enqueued_by_project.assert_not_awaited()
    repo.mark_waiting.assert_awaited_once_with(run.id)
    repo.mark_enqueued.assert_not_awaited()
    repo.get_by_arq_job_id.assert_not_awaited()
    arq.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_marks_waiting_when_project_capacity_is_full():
    run = _run()
    repo = _repo(active=0, project_active=1)
    scheduler = FairScheduler(_arq(), repo, _settings(total=10, per_project=1))

    result = await scheduler.enqueue(run)

    assert result is False
    repo.count_active_or_enqueued.assert_awaited_once_with()
    repo.count_active_or_enqueued_by_project.assert_awaited_once_with(run.project_id)
    repo.mark_waiting.assert_awaited_once_with(run.id)
    repo.mark_enqueued.assert_not_awaited()
    repo.get_by_arq_job_id.assert_not_awaited()
    scheduler.arq.enqueue_job.assert_not_awaited()


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
    _assert_mark_enqueued(
        repo,
        run.id,
        queue_name=PRIORITY_QUEUES[Priority.HIGH],
        arq_job_id="job-high",
    )


@pytest.mark.asyncio
async def test_enqueue_falls_back_to_medium_for_invalid_manual_priority():
    run = _run(priority=99)
    repo = _repo()
    arq = _arq()
    scheduler = FairScheduler(arq, repo, _settings())

    assert await scheduler.enqueue(run) is True
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[Priority.MEDIUM],
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    _assert_mark_enqueued(
        repo,
        run.id,
        queue_name=PRIORITY_QUEUES[Priority.MEDIUM],
        arq_job_id="job-1",
    )


@pytest.mark.asyncio
async def test_enqueue_schedule_uses_low_priority_queue():
    run = _run(trigger_type="schedule", priority=0)
    repo = _repo()
    arq = _arq()
    scheduler = FairScheduler(arq, repo, _settings())

    assert await scheduler.enqueue(run) is True
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[Priority.LOW],
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    _assert_mark_enqueued(
        repo,
        run.id,
        queue_name=PRIORITY_QUEUES[Priority.LOW],
        arq_job_id="job-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("priority", "expected"),
    [
        (0, Priority.HIGH),
        (1, Priority.MEDIUM),
        (2, Priority.LOW),
    ],
)
async def test_manual_priority_matrix_targets_all_worker_queues(priority, expected):
    run = _run(trigger_type="manual", priority=priority)
    repo = _repo()
    arq = _arq()
    scheduler = FairScheduler(arq, repo, _settings())

    assert await scheduler.enqueue(run) is True
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[expected],
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    _assert_mark_enqueued(
        repo,
        run.id,
        queue_name=PRIORITY_QUEUES[expected],
        arq_job_id="job-1",
    )


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
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[Priority.MEDIUM],
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    repo.get_by_arq_job_id.assert_awaited_once_with(f"run:{run.id}")
    repo.mark_enqueued.assert_not_awaited()
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
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[Priority.MEDIUM],
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    repo.get_by_arq_job_id.assert_awaited_once_with(f"run:{run.id}")
    repo.mark_enqueued.assert_not_awaited()
    repo.mark_waiting.assert_awaited_once_with(
        run.id,
        reason=f"arq job id conflict: run:{run.id}",
    )


@pytest.mark.asyncio
async def test_enqueue_job_exception_marks_waiting_with_sanitized_reason():
    run = _run()
    repo = _repo()
    arq = _arq()
    arq.enqueue_job = AsyncMock(
        side_effect=RuntimeError("redis://user:queue-secret@localhost/0")
    )
    scheduler = FairScheduler(arq, repo, _settings())

    assert await scheduler.enqueue(run) is False

    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[Priority.MEDIUM],
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    repo.get_by_arq_job_id.assert_not_awaited()
    repo.mark_enqueued.assert_not_awaited()
    repo.mark_waiting.assert_awaited_once_with(
        run.id,
        reason="queue unavailable",
    )
    assert "queue-secret" not in repr(repo.mark_waiting.await_args)


@pytest.mark.asyncio
async def test_try_dequeue_waiting_enqueues_until_capacity_is_full():
    first = _run()
    second = _run()
    repo = _repo()
    repo.find_waiting = AsyncMock(return_value=[first, second])
    repo.count_active_or_enqueued = AsyncMock(side_effect=[0, 2])
    arq = _arq(job_id="job-first")
    scheduler = FairScheduler(arq, repo, _settings(total=2, per_project=10))

    result = await scheduler.try_dequeue_waiting()

    assert result == 1
    repo.find_waiting.assert_awaited_once_with(limit=10)
    assert [call.args for call in repo.count_active_or_enqueued.await_args_list] == [
        (),
        (),
    ]
    assert [
        call.args
        for call in repo.count_active_or_enqueued_by_project.await_args_list
    ] == [
        (first.project_id,),
    ]
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(first.id),
        _queue_name=PRIORITY_QUEUES[Priority.MEDIUM],
        _job_id=f"run:{first.id}",
        _defer_by=0,
    )
    _assert_mark_enqueued(
        repo,
        first.id,
        queue_name=PRIORITY_QUEUES[Priority.MEDIUM],
        arq_job_id="job-first",
    )
    repo.mark_waiting.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_dequeue_waiting_skips_project_at_capacity_and_continues():
    blocked_project = uuid4()
    available_project = uuid4()
    blocked = _run(project_id=blocked_project)
    available = _run(project_id=available_project, trigger_type="schedule", priority=0)
    repo = _repo()
    repo.find_waiting = AsyncMock(return_value=[blocked, available])
    repo.count_active_or_enqueued = AsyncMock(side_effect=[0, 0])
    repo.count_active_or_enqueued_by_project = AsyncMock(side_effect=[1, 0])
    arq = _arq(job_id="job-low")
    scheduler = FairScheduler(arq, repo, _settings(total=3, per_project=1))

    result = await scheduler.try_dequeue_waiting()

    assert result == 1
    repo.find_waiting.assert_awaited_once_with(limit=10)
    project_count_args = repo.count_active_or_enqueued_by_project.await_args_list
    assert [args.args for args in project_count_args] == [
        (blocked_project,),
        (available_project,),
    ]
    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(available.id),
        _queue_name=PRIORITY_QUEUES[Priority.LOW],
        _job_id=f"run:{available.id}",
        _defer_by=0,
    )
    _assert_mark_enqueued(
        repo,
        available.id,
        queue_name=PRIORITY_QUEUES[Priority.LOW],
        arq_job_id="job-low",
    )
    repo.mark_waiting.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_run_convenience_uses_fair_scheduler():
    run = _run()
    repo = _repo()
    arq = _arq()

    assert await enqueue_run(arq, repo, run, "manual", _settings()) is True


@pytest.mark.asyncio
async def test_enqueue_run_convenience_uses_explicit_trigger_type_for_queue():
    run = _run(trigger_type="manual", priority=0)
    repo = _repo()
    arq = _arq()

    assert await enqueue_run(arq, repo, run, "schedule", _settings()) is True

    arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name=PRIORITY_QUEUES[Priority.LOW],
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    _assert_mark_enqueued(
        repo,
        run.id,
        queue_name=PRIORITY_QUEUES[Priority.LOW],
        arq_job_id="job-1",
    )
