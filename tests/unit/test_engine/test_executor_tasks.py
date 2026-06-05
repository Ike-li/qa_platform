from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from qaplatform.engine import executor as executor_module
from qaplatform.engine import executor_tasks as tasks
from qaplatform.engine.docker_backend import ResourceUsageSample


@pytest.mark.asyncio
async def test_drain_log_task_returns_when_task_is_done():
    async def done():
        return "ok"

    log_task = asyncio.create_task(done())
    await log_task

    await tasks.drain_log_task(log_task, timeout=0.01)

    assert log_task.done()


@pytest.mark.asyncio
async def test_drain_log_task_cancels_stuck_task():
    async def stuck():
        await asyncio.sleep(3600)

    log_task = asyncio.create_task(stuck())

    await tasks.drain_log_task(log_task, timeout=0.01)

    assert log_task.cancelled()


@pytest.mark.asyncio
async def test_collect_resource_usage_observes_stream_samples():
    sample = ResourceUsageSample(
        timestamp=datetime.now(timezone.utc),
        memory_usage_bytes=256,
    )
    observed = []

    class Backend:
        async def stream_resource_usage(self, execution_id: str):
            assert execution_id == "container-1"
            yield sample

    class Tracker:
        def observe(self, item):
            observed.append(item)

    await tasks.collect_resource_usage(Backend(), "container-1", Tracker())

    assert observed == [sample]


@pytest.mark.asyncio
async def test_collect_resource_usage_supports_awaitable_stream_factory():
    sample = ResourceUsageSample(
        timestamp=datetime.now(timezone.utc),
        cpu_percent=12.5,
    )
    observed = []

    async def usage_stream():
        yield sample

    class Backend:
        async def stream_resource_usage(self, _execution_id: str):
            return usage_stream()

    class Tracker:
        def observe(self, item):
            observed.append(item)

    await tasks.collect_resource_usage(Backend(), "container-2", Tracker())

    assert observed == [sample]


@pytest.mark.asyncio
async def test_collect_resource_usage_returns_when_backend_has_no_stream():
    class Tracker:
        def observe(self, _item):
            raise AssertionError("should not observe samples")

    await tasks.collect_resource_usage(object(), "container-3", Tracker())


@pytest.mark.asyncio
async def test_drain_resource_usage_task_cancels_pending_task():
    async def stuck():
        await asyncio.sleep(3600)

    usage_task = asyncio.create_task(stuck())

    await tasks.drain_resource_usage_task(usage_task, timeout=0.01)

    assert usage_task.cancelled()


@pytest.mark.asyncio
async def test_drain_resource_usage_task_accepts_none():
    await tasks.drain_resource_usage_task(None)


def test_executor_module_keeps_task_helper_compatibility_exports():
    assert executor_module._drain_log_task is tasks.drain_log_task
    assert executor_module._collect_resource_usage is tasks.collect_resource_usage
    assert (
        executor_module._drain_resource_usage_task
        is tasks.drain_resource_usage_task
    )
