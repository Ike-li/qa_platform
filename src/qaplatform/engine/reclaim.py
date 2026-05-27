"""Worker-lost reclaimer.

Periodic task that turns runs whose worker heartbeat has expired (Redis key
`worker:{worker_id}:heartbeat`, TTL 90s) into terminal `failed` runs and
forces removal of any orphan container labelled with the run id, so the
freed slot can be reused by the fair scheduler.

Lives in the engine layer because it composes infra (Redis, run_repo) with
the Docker backend; the worker `cron_job` only handles wiring and session
lifecycle.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from qaplatform.engine.events import publish_status_event
from qaplatform.worker._redact import redact_url_userinfo

log = logging.getLogger(__name__)

HEARTBEAT_KEY = "worker:{worker_id}:heartbeat"


class _BackendCleanup(Protocol):
    async def cleanup(self, execution_id: str) -> None: ...


async def _is_heartbeat_alive(redis: Any, worker_id: str) -> bool:
    if redis is None or not worker_id:
        return False
    try:
        return bool(await redis.exists(HEARTBEAT_KEY.format(worker_id=worker_id)))
    except Exception:
        log.warning("heartbeat lookup failed for worker %s", worker_id, exc_info=True)
        # Fail-open: treat probe failure as "alive" to avoid wrongly killing
        # a healthy run during a transient Redis blip.
        return True


async def reclaim_worker_lost(
    *,
    run_repo: Any,
    redis: Any,
    backend: _BackendCleanup | None = None,
    on_reclaimed: Callable[[Any, str], Awaitable[None]] | None = None,
) -> int:
    """Mark every non-terminal run whose worker heartbeat has expired as failed.

    Returns the number of runs reclaimed. Best-effort container cleanup; cleanup
    failures don't block the status transition.
    """
    runs = await run_repo.find_active_with_worker()
    reclaimed = 0
    for run in runs:
        worker_id = run.worker_id
        if not worker_id:
            continue
        if await _is_heartbeat_alive(redis, worker_id):
            continue

        message = redact_url_userinfo(
            f"worker_lost: heartbeat expired for {worker_id}"
        )
        updated = await run_repo.mark_worker_lost(
            run.id, worker_id=worker_id, message=message
        )
        if not updated:
            continue

        reclaimed += 1
        previous = run.status.value if hasattr(run.status, "value") else str(run.status)
        log.warning(
            "reclaimed run %s (worker_lost, was %s, worker=%s)",
            run.id,
            previous,
            worker_id,
        )
        await publish_status_event(redis, run.id, "failed", previous=previous)

        if on_reclaimed is not None:
            try:
                await on_reclaimed(run, message)
            except Exception:
                log.warning(
                    "worker_lost_retry_callback_failed",
                    extra={"run_id": str(run.id)},
                    exc_info=True,
                )

        execution_id = run.execution_id
        if backend is not None and execution_id:
            try:
                await backend.cleanup(execution_id)
            except Exception:
                log.warning(
                    "failed to cleanup orphan container %s for run %s",
                    execution_id,
                    run.id,
                    exc_info=True,
                )

    return reclaimed
