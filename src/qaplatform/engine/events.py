"""Run lifecycle event publisher.

Writes status_change events to Redis Stream `run:{id}:events` and updates
the current status in hash `run:{id}:status`. The SSE endpoint
(`/runs/{id}/events`) consumes both: the stream for delivery and the hash
for terminal-state detection.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)

EVENT_STREAM_KEY = "run:{run_id}:events"
STATUS_HASH_KEY = "run:{run_id}:status"


async def publish_status_event(
    redis: Any,
    run_id: UUID | str,
    status: str,
    *,
    previous: str | None = None,
) -> None:
    """Publish a run status_change event to Redis (best-effort).

    Never raises: a failed publish must not break run execution.
    """
    if redis is None:
        return
    run_id_str = str(run_id)
    ts = datetime.now(timezone.utc).isoformat()
    event: dict[str, str] = {
        "run_id": run_id_str,
        "status": status,
        "timestamp": ts,
    }
    if previous is not None:
        event["previous"] = previous

    try:
        await redis.xadd(EVENT_STREAM_KEY.format(run_id=run_id_str), event)
        await redis.hset(
            STATUS_HASH_KEY.format(run_id=run_id_str),
            mapping={"status": status, "timestamp": ts},
        )
    except Exception:
        log.warning(
            "failed to publish status event for run %s (status=%s)",
            run_id_str,
            status,
            exc_info=True,
        )
