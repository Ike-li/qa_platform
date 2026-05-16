from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from qaplatform.engine.events import (
    EVENT_STREAM_KEY,
    STATUS_HASH_KEY,
    publish_status_event,
)


@pytest.mark.asyncio
async def test_publish_status_event_writes_stream_and_hash():
    redis = AsyncMock()
    run_id = "11111111-1111-1111-1111-111111111111"

    await publish_status_event(redis, run_id, "running", previous="preparing")

    redis.xadd.assert_awaited_once()
    args, _ = redis.xadd.call_args
    assert args[0] == EVENT_STREAM_KEY.format(run_id=run_id)
    event = args[1]
    assert event["run_id"] == run_id
    assert event["status"] == "running"
    assert event["previous"] == "preparing"
    assert "timestamp" in event

    redis.hset.assert_awaited_once()
    hset_kwargs = redis.hset.call_args.kwargs
    assert redis.hset.call_args.args[0] == STATUS_HASH_KEY.format(run_id=run_id)
    assert hset_kwargs["mapping"]["status"] == "running"


@pytest.mark.asyncio
async def test_publish_status_event_omits_previous_when_none():
    redis = AsyncMock()
    await publish_status_event(redis, "rid", "queued")
    event = redis.xadd.call_args.args[1]
    assert "previous" not in event


@pytest.mark.asyncio
async def test_publish_status_event_silent_when_redis_none():
    # Should not raise, no-op
    await publish_status_event(None, "rid", "running")


@pytest.mark.asyncio
async def test_publish_status_event_swallows_redis_errors():
    redis = AsyncMock()
    redis.xadd.side_effect = RuntimeError("redis down")

    # Must not raise even when redis is broken
    await publish_status_event(redis, "rid", "running")
