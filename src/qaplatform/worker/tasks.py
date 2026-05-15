from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from qaplatform.domain.models.run import RunStatus, TERMINAL_STATUSES

log = logging.getLogger(__name__)


async def _heartbeat_loop(worker_id: str, redis: Any, interval: int = 30) -> None:
    """Background task: refresh worker heartbeat key every interval seconds."""
    try:
        while True:
            now = datetime.now(timezone.utc).isoformat()
            await redis.set(f"worker:{worker_id}:heartbeat", now, ex=90)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


async def execute_run(ctx: dict, run_id: str) -> None:
    """arq task entry point: execute a QA pipeline run.

    Flow:
    1. claim_for_worker (queued -> preparing)
    2. executor.execute()
    3. On exception: fail_if_current
    4. Finally: archive logs, release worker
    """
    run_repo = ctx["run_repo"]
    executor = ctx["executor"]
    log_stream = ctx["log_stream"]
    worker_id = ctx["worker_id"]
    redis = ctx["redis"]

    # 1. Claim the run
    run = await run_repo.claim_for_worker(run_id, worker_id=worker_id)
    if not run:
        log.warning("could not claim run %s (not in queued state or not found)", run_id)
        return

    # Check if cancellation was requested before we started
    if run.cancel_requested_at:
        if await run_repo.cancel_if_current(run.id):
            log.info("run %s cancelled before execution started", run_id)
        return

    # Start heartbeat
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(worker_id, redis)
    )

    try:
        # 2. Execute the pipeline
        status = await executor.execute(run, run.pipeline)

        # 3. Write terminal state (conditional update)
        updated = await run_repo.finish_if_current(
            run.id,
            status=status,
        )
        if updated:
            log.info("run %s completed with status: %s", run_id, status.value)

    except Exception as exc:
        log.exception("execute_run failed for run %s", run_id)
        updated = await run_repo.fail_if_current(
            run.id,
            message=str(exc),
        )
        if updated:
            log.info("run %s marked as failed: %s", run_id, exc)
        # Do NOT re-raise: arq job is considered complete to avoid built-in retry.
        # Platform-level retry creates a new Run attempt via domain service.

    finally:
        # Cancel heartbeat
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)

        # Best-effort log archival
        try:
            if ctx.get("s3_client"):
                await log_stream.archive_logs(
                    run_id, ctx["s3_client"], ctx.get("s3_bucket", "qa-platform")
                )
        except Exception:
            log.warning("failed to archive logs for run %s", run_id)

        # Release worker association
        try:
            await run_repo.release_worker(run_id, worker_id=worker_id)
        except Exception:
            log.warning("failed to release worker for run %s", run_id)
