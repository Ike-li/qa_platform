"""Run execution cleanup helpers for worker tasks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from qaplatform.domain.models.run import RunStatus

log = logging.getLogger(__name__)


async def evaluate_terminal_notifications(
    *,
    run: Any,
    status: RunStatus | None,
    session_factory: Any,
) -> None:
    """Evaluate terminal run notifications without blocking cleanup."""
    try:
        from qaplatform.worker.notifications import evaluate_and_notify

        terminal_status = (
            status
            if status in (RunStatus.DONE, RunStatus.FAILED, RunStatus.TIMEOUT)
            else None
        )
        if terminal_status:
            await evaluate_and_notify(
                run_id=run.id,
                project_id=run.project_id,
                status=terminal_status.value,
                summary=getattr(run, "summary", None),
                session_factory=session_factory,
            )
    except Exception:
        log.warning("notification_evaluation_failed", exc_info=True)


async def archive_run_logs(
    *,
    run_id: str,
    log_stream: Any,
    s3_client: Any,
    s3_bucket: str,
) -> None:
    """Archive run logs when object storage is configured."""
    try:
        if s3_client:
            await log_stream.archive_logs(run_id, s3_client, s3_bucket)
    except Exception:
        log.warning("failed to archive logs for run %s", run_id)


async def release_run_worker(
    *,
    run_repo: Any,
    run_id: str,
    worker_id: str,
) -> None:
    """Release the run's worker association as best effort."""
    try:
        await run_repo.release_worker(run_id, worker_id=worker_id)
    except Exception:
        log.warning("failed to release worker for run %s", run_id)


async def finalize_run_execution(
    *,
    heartbeat_task: asyncio.Task[Any],
    run: Any,
    run_id: str,
    status: RunStatus | None,
    log_stream: Any,
    s3_client: Any,
    s3_bucket: str,
    run_repo: Any,
    worker_id: str,
    session: Any,
    session_factory: Any,
) -> None:
    """Run the worker task cleanup sequence after execution finishes."""
    heartbeat_task.cancel()
    await asyncio.gather(heartbeat_task, return_exceptions=True)

    await evaluate_terminal_notifications(
        run=run,
        status=status,
        session_factory=session_factory,
    )
    await archive_run_logs(
        run_id=run_id,
        log_stream=log_stream,
        s3_client=s3_client,
        s3_bucket=s3_bucket,
    )
    await release_run_worker(
        run_repo=run_repo,
        run_id=run_id,
        worker_id=worker_id,
    )

    await session.commit()
