from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable
from uuid import UUID

CANCEL_CHANNEL_PREFIX = "run:cancel:"

log = logging.getLogger(__name__)


async def publish_cancel(redis, run_id: UUID | str) -> None:
    """Publish a cancel signal for a run via Redis pub/sub."""
    channel = f"{CANCEL_CHANNEL_PREFIX}{run_id}"
    await redis.publish(channel, "cancel")


async def watch_for_cancel(
    redis,
    run_id: UUID | str,
    on_cancel: Callable[[], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    """Subscribe to the cancel channel for ``run_id`` and invoke
    ``on_cancel`` for *every* message until ``stop_event`` is set.

    The watcher is intended to run as a background task for the lifetime
    of an executing run. ``stop_event`` lets the executor signal that the
    run has reached a terminal state and the watcher should exit.

    P1-D: previously the watcher returned after the first cancel message,
    so a cancel that arrived during a stage transition (when
    ``_active_execution_id is None``) silently dropped — the next signal
    after the new container started had no consumer. We now keep
    listening until ``stop_event`` fires, so each redelivered cancel
    re-runs ``on_cancel`` and the executor's idempotent
    ``_handle_cancel_signal`` can target whichever container is currently
    active.

    The function never raises; subscribe-side failures degrade to a
    warning log, since the worst case is missing one cancel signal which
    F-EX-06 already concedes ("< 10s") rather than guaranteeing.
    """
    if redis is None:
        return

    channel = f"{CANCEL_CHANNEL_PREFIX}{run_id}"
    pubsub = None
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if stop_event.is_set():
                return
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            try:
                await on_cancel()
            except Exception:
                log.exception("cancel handler raised for run %s", run_id)
            # Keep listening — do NOT return — so a follow-up cancel
            # arriving during a stage boundary still reaches a consumer.
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("cancel watcher failed for run %s", run_id, exc_info=True)
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(channel)
                close = getattr(pubsub, "aclose", None)
                if close is None:
                    close = pubsub.close
                await close()
            except Exception:
                pass
