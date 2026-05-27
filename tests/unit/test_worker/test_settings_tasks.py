from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.domain.models.run import RunStatus
from qaplatform.worker.settings import (
    after_job_end,
    cleanup_old_runs,
    dequeue_waiting,
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
        "settings": SimpleNamespace(retention_runs_days=14),
    }
    ctx.update(overrides)
    return ctx, session


@pytest.mark.asyncio
async def test_on_shutdown_closes_container_and_docker_client():
    container = AsyncMock()
    docker_client = AsyncMock()

    await on_shutdown({"container": container, "docker_client": docker_client})

    container.close.assert_awaited_once()
    docker_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_shutdown_closes_docker_even_when_container_close_fails():
    container = AsyncMock()
    container.close.side_effect = RuntimeError("db close failed")
    docker_client = AsyncMock()

    with pytest.raises(RuntimeError):
        await on_shutdown({"container": container, "docker_client": docker_client})

    docker_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_reclaim_resources_exits_without_required_dependencies():
    await reclaim_resources({"db_session_factory": None, "redis": AsyncMock()})
    await reclaim_resources({"db_session_factory": MagicMock(), "redis": None})


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
        patch("qaplatform.api.metrics.runs_in_flight", runs_in_flight),
        patch("qaplatform.api.metrics.run_queue_depth", run_queue_depth),
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
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_dequeue_waiting_exits_without_session_factory():
    await dequeue_waiting({"db_session_factory": None})


@pytest.mark.asyncio
async def test_dequeue_waiting_uses_fair_scheduler_and_commits():
    ctx, session = _ctx_with_session()
    scheduler = AsyncMock()

    with (
        patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=AsyncMock()),
        patch("qaplatform.worker.scheduler.FairScheduler", return_value=scheduler) as scheduler_cls,
    ):
        await dequeue_waiting(ctx)

    scheduler_cls.assert_called_once()
    scheduler.try_dequeue_waiting.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_old_runs_exits_without_session_or_settings():
    await cleanup_old_runs({"db_session_factory": None, "settings": SimpleNamespace()})
    await cleanup_old_runs({"db_session_factory": MagicMock(), "settings": None})


@pytest.mark.asyncio
async def test_cleanup_old_runs_deletes_terminal_runs_and_commits():
    ctx, session = _ctx_with_session()
    run_repo = AsyncMock()
    run_repo.delete_terminal_older_than.return_value = 3

    with (
        patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
        patch("qaplatform.worker.settings.log") as log,
    ):
        await cleanup_old_runs(ctx)

    run_repo.delete_terminal_older_than.assert_awaited_once()
    session.commit.assert_awaited_once()
    log.info.assert_called_once()


@pytest.mark.asyncio
async def test_retry_failed_archives_exits_without_dependencies():
    await retry_failed_archives({"s3_client": AsyncMock(), "s3_bucket": "bucket"})
    await retry_failed_archives({"log_stream": AsyncMock(), "s3_bucket": "bucket"})
    await retry_failed_archives({"log_stream": AsyncMock(), "s3_client": AsyncMock()})


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
    run_repo.fail_if_current.assert_awaited_once()
    assert "user:secret@" not in run_repo.fail_if_current.call_args.kwargs["message"]
    assert "https://***@example.com/repo.git" in run_repo.fail_if_current.call_args.kwargs["message"]
