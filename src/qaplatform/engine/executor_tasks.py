"""Async task helpers for run execution."""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import suppress
from typing import Any

log = logging.getLogger(__name__)


async def drain_log_task(log_task: asyncio.Task, *, timeout: float) -> None:
    if log_task.done():
        try:
            log_task.result()
        except Exception:
            pass
        return
    try:
        await asyncio.wait_for(asyncio.shield(log_task), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("log task did not drain within %ss; cancelling", timeout)
        log_task.cancel()
        await asyncio.gather(log_task, return_exceptions=True)
    except Exception:
        log.warning("log task raised during drain", exc_info=True)


async def collect_resource_usage(
    backend: Any,
    execution_id: str,
    tracker: Any,
) -> None:
    stream_usage = getattr(backend, "stream_resource_usage", None)
    if stream_usage is None:
        return
    try:
        usage_stream = stream_usage(execution_id)
        if inspect.isawaitable(usage_stream):
            usage_stream = await usage_stream
        if usage_stream is None:
            return
        async for sample in usage_stream:
            tracker.observe(sample)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.debug("resource usage streaming ended for container %s", execution_id)


async def drain_resource_usage_task(
    usage_task: asyncio.Task | None,
    *,
    timeout: float = 1,
) -> None:
    if usage_task is None:
        return
    if usage_task.done():
        with suppress(Exception):
            usage_task.result()
        return
    usage_task.cancel()
    try:
        await asyncio.wait_for(usage_task, timeout=timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception:
        log.debug("resource usage task raised during drain", exc_info=True)
