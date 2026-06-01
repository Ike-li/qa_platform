from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.domain.models.run import RunStatus
from qaplatform.worker.settings import (
    after_job_end,
    cleanup_old_audit_events,
    cleanup_old_runs,
    dequeue_waiting,
    _get_worker_max_jobs,
    on_shutdown,
    reclaim_resources,
    retry_failed_archives,
)


@asynccontextmanager
async def _session_context(session):
    yield session


def _ctx_with_session(**overrides):
    session = AsyncMock()
    factory = MagicMock(return_value=_session_context(session))
    ctx = {
        "db_session_factory": factory,
        "redis": AsyncMock(),
        "docker_backend": MagicMock(),
        "arq_pool": AsyncMock(),
        "settings": SimpleNamespace(retention_runs_days=14, retention_audit_days=365),
    }
    ctx.update(overrides)
    return ctx, session


def test_get_worker_max_jobs_defaults_to_arq_concurrency_default(monkeypatch):
    monkeypatch.delenv("QAP_WORKER_MAX_JOBS", raising=False)

    assert _get_worker_max_jobs() == 10


@pytest.mark.parametrize(
    ("raw_value", "expected_msg"),
    [
        ("0", "QAP_WORKER_MAX_JOBS must be >= 1"),
        ("-1", "QAP_WORKER_MAX_JOBS must be >= 1"),
        ("many", "QAP_WORKER_MAX_JOBS must be an integer"),
    ],
)
def test_get_worker_max_jobs_rejects_invalid_values(
    monkeypatch,
    raw_value,
    expected_msg,
):
    monkeypatch.setenv("QAP_WORKER_MAX_JOBS", raw_value)

    with pytest.raises(ValueError) as exc_info:
        _get_worker_max_jobs()

    assert exc_info.value.args == (expected_msg,)
    assert "QAP_WORKER_MAX_JOBS" in str(exc_info.value)
    assert raw_value not in str(exc_info.value)


@pytest.mark.asyncio
async def test_on_shutdown_closes_container_and_docker_client():
    container = AsyncMock()
    docker_client = AsyncMock()

    await on_shutdown({"container": container, "docker_client": docker_client})

    container.close.assert_awaited_once_with()
    docker_client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_on_shutdown_closes_docker_even_when_container_close_fails():
    container = AsyncMock()
    error = RuntimeError("db close failed")
    container.close.side_effect = error
    docker_client = AsyncMock()

    with pytest.raises(RuntimeError) as exc_info:
        await on_shutdown({"container": container, "docker_client": docker_client})

    assert exc_info.value is error
    container.close.assert_awaited_once_with()
    docker_client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_reclaim_resources_exits_without_required_dependencies():
    session_factory = MagicMock()

    await reclaim_resources({"db_session_factory": None, "redis": AsyncMock()})
    await reclaim_resources({"db_session_factory": session_factory, "redis": None})

    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_reclaim_resources_reclaims_updates_metrics_and_commits():
    ctx, session = _ctx_with_session()
    run_repo = AsyncMock()
    run_repo.count_active_or_enqueued.return_value = 2
    run_repo.count_queued_waiting.return_value = 5
    runs_in_flight = MagicMock()
    run_queue_depth = MagicMock()

    with (
        patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
        patch("qaplatform.engine.reclaim.reclaim_worker_lost", new_callable=AsyncMock) as reclaim,
        patch("qaplatform.observability.metrics.runs_in_flight", runs_in_flight),
        patch("qaplatform.observability.metrics.run_queue_depth", run_queue_depth),
    ):
        await reclaim_resources(ctx)

    reclaim.assert_awaited_once_with(
        run_repo=run_repo,
        redis=ctx["redis"],
        backend=ctx["docker_backend"],
        on_reclaimed=ANY,
    )
    runs_in_flight.set.assert_called_once_with(2)
    run_queue_depth.set.assert_called_once_with(5)
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_reclaim_resources_retry_callback_schedules_reclaimed_run():
    ctx, session = _ctx_with_session()
    run_repo = AsyncMock()
    run_repo.count_active_or_enqueued.return_value = 0
    run_repo.count_queued_waiting.return_value = 0
    reclaimed_run = SimpleNamespace(id=uuid4())
    message = "worker_lost: heartbeat expired for worker-a"

    async def _reclaim_with_callback(*, on_reclaimed, **kwargs):
        await on_reclaimed(reclaimed_run, message)
        return 1

    with (
        patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
        patch("qaplatform.engine.reclaim.reclaim_worker_lost", new=AsyncMock(side_effect=_reclaim_with_callback)),
        patch("qaplatform.worker.tasks._schedule_retry_for_run", new_callable=AsyncMock) as schedule_retry,
        patch("qaplatform.observability.metrics.runs_in_flight", MagicMock()),
        patch("qaplatform.observability.metrics.run_queue_depth", MagicMock()),
    ):
        await reclaim_resources(ctx)

    schedule_retry.assert_awaited_once()
    retry_args = schedule_retry.await_args
    assert retry_args.args[0] is reclaimed_run
    assert isinstance(retry_args.args[1], ConnectionError)
    assert str(retry_args.args[1]) == message
    assert retry_args.kwargs == {
        "run_repo": run_repo,
        "arq": ctx["arq_pool"],
        "settings": ctx["settings"],
    }
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_dequeue_waiting_exits_without_session_factory():
    arq_pool = AsyncMock()

    await dequeue_waiting({"db_session_factory": None, "arq_pool": arq_pool})

    arq_pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_dequeue_waiting_uses_fair_scheduler_and_commits():
    ctx, session = _ctx_with_session()
    run_repo = AsyncMock()
    scheduler = AsyncMock()

    with (
        patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
        patch("qaplatform.worker.scheduler.FairScheduler", return_value=scheduler) as scheduler_cls,
    ):
        await dequeue_waiting(ctx)

    scheduler_cls.assert_called_once_with(
        arq=ctx["arq_pool"],
        run_repo=run_repo,
        settings=ctx["settings"],
    )
    scheduler.try_dequeue_waiting.assert_awaited_once_with()
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cleanup_old_runs_exits_without_session_or_settings():
    session_factory = MagicMock()

    await cleanup_old_runs({"db_session_factory": None, "settings": SimpleNamespace()})
    await cleanup_old_runs({"db_session_factory": session_factory, "settings": None})

    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_old_runs_deletes_terminal_runs_and_commits():
    ctx, session = _ctx_with_session()
    run_repo = AsyncMock()
    run_repo.delete_terminal_older_than.return_value = 3
    before_cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    with (
        patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
        patch("qaplatform.worker.settings.log") as log,
    ):
        await cleanup_old_runs(ctx)

    after_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    run_repo.delete_terminal_older_than.assert_awaited_once_with(cutoff=ANY)
    cutoff = run_repo.delete_terminal_older_than.await_args.kwargs["cutoff"]
    assert before_cutoff <= cutoff <= after_cutoff
    assert cutoff.tzinfo is not None
    session.commit.assert_awaited_once_with()
    log.info.assert_called_once_with(
        "retention_cleanup_done deleted=%s cutoff=%s",
        3,
        cutoff.isoformat(),
    )


@pytest.mark.asyncio
async def test_cleanup_old_audit_events_exits_without_session_or_settings():
    session_factory = MagicMock()

    await cleanup_old_audit_events({"db_session_factory": None, "settings": SimpleNamespace()})
    await cleanup_old_audit_events({"db_session_factory": session_factory, "settings": None})

    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_old_audit_events_deletes_expired_events_and_commits():
    ctx, session = _ctx_with_session()
    audit_repo = AsyncMock()
    audit_repo.delete_older_than.return_value = 2
    before_cutoff = datetime.now(timezone.utc) - timedelta(days=365)

    with (
        patch(
            "qaplatform.infra.database.repositories.audit_repo.AuditEventRepository",
            return_value=audit_repo,
        ),
        patch("qaplatform.worker.settings.log") as log,
    ):
        await cleanup_old_audit_events(ctx)

    after_cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    audit_repo.delete_older_than.assert_awaited_once_with(cutoff=ANY)
    cutoff = audit_repo.delete_older_than.await_args.kwargs["cutoff"]
    assert before_cutoff <= cutoff <= after_cutoff
    assert cutoff.tzinfo is not None
    session.commit.assert_awaited_once_with()
    log.info.assert_called_once_with(
        "audit_retention_cleanup_done deleted=%s cutoff=%s",
        2,
        cutoff.isoformat(),
    )


@pytest.mark.asyncio
async def test_retry_failed_archives_exits_without_dependencies():
    log_stream_without_bucket = AsyncMock()
    log_stream_without_s3 = AsyncMock()

    await retry_failed_archives({"s3_client": AsyncMock(), "s3_bucket": "bucket"})
    await retry_failed_archives(
        {"log_stream": log_stream_without_s3, "s3_bucket": "bucket"}
    )
    await retry_failed_archives(
        {"log_stream": log_stream_without_bucket, "s3_client": AsyncMock()}
    )

    log_stream_without_s3.retry_failed_archives.assert_not_awaited()
    log_stream_without_bucket.retry_failed_archives.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_failed_archives_retries_and_logs_success():
    log_stream = AsyncMock()
    s3_client = AsyncMock()
    log_stream.retry_failed_archives.return_value = 2

    with patch("qaplatform.worker.settings.log") as log:
        await retry_failed_archives(
            {
                "log_stream": log_stream,
                "s3_client": s3_client,
                "s3_bucket": "qa-platform",
            }
        )

    log_stream.retry_failed_archives.assert_awaited_once_with(s3_client, "qa-platform")
    log.info.assert_called_once_with("log_archive_retry_done retried=%s", 2)


@pytest.mark.asyncio
async def test_after_job_end_ignores_successful_and_non_run_jobs():
    run_repo = AsyncMock()

    await after_job_end({"success": True, "job_id": "run:1", "run_repo": run_repo})
    await after_job_end({"success": False, "job_id": "maintenance:1", "run_repo": run_repo})

    run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_after_job_end_marks_active_run_failed_with_redacted_error():
    run_id = uuid4()
    run = SimpleNamespace(id=run_id, status=RunStatus.RUNNING)
    run_repo = AsyncMock()
    run_repo.get.return_value = run

    await after_job_end(
        {
            "success": False,
            "job_id": f"run:{run_id}",
            "result": "git clone https://user:secret@example.com/repo.git failed",
            "run_repo": run_repo,
        }
    )

    run_repo.get.assert_awaited_once_with(str(run_id))
    run_repo.fail_if_current.assert_awaited_once_with(run_id, message=ANY)
    message = run_repo.fail_if_current.await_args.kwargs["message"]
    assert "user:secret@" not in message
    assert "https://***@example.com/repo.git" in message
