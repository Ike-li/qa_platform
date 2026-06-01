from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock

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

    started_at = datetime.now(timezone.utc)
    await publish_status_event(redis, run_id, "running", previous="preparing")
    finished_at = datetime.now(timezone.utc)

    redis.xadd.assert_awaited_once_with(
        EVENT_STREAM_KEY.format(run_id=run_id),
        {
            "run_id": run_id,
            "status": "running",
            "timestamp": ANY,
            "previous": "preparing",
        },
    )
    event = redis.xadd.await_args.args[1]
    event_timestamp = datetime.fromisoformat(event["timestamp"])
    assert event == {
        "run_id": run_id,
        "status": "running",
        "timestamp": event["timestamp"],
        "previous": "preparing",
    }
    assert started_at <= event_timestamp <= finished_at
    assert event_timestamp.tzinfo is timezone.utc

    redis.hset.assert_awaited_once_with(
        STATUS_HASH_KEY.format(run_id=run_id),
        mapping={
            "status": "running",
            "timestamp": event["timestamp"],
        },
    )


@pytest.mark.asyncio
async def test_publish_status_event_omits_previous_when_none():
    redis = AsyncMock()
    run_id = "rid"

    await publish_status_event(redis, run_id, "queued")

    redis.xadd.assert_awaited_once_with(
        EVENT_STREAM_KEY.format(run_id=run_id),
        {
            "run_id": run_id,
            "status": "queued",
            "timestamp": ANY,
        },
    )
    event = redis.xadd.await_args.args[1]
    assert event == {
        "run_id": run_id,
        "status": "queued",
        "timestamp": event["timestamp"],
    }
    assert datetime.fromisoformat(event["timestamp"]).tzinfo is not None

    redis.hset.assert_awaited_once_with(
        STATUS_HASH_KEY.format(run_id=run_id),
        mapping={
            "status": "queued",
            "timestamp": event["timestamp"],
        },
    )


@pytest.mark.asyncio
async def test_publish_status_event_silent_when_redis_none(caplog):
    # Should not raise and should not emit Redis outage noise for the explicit no-op path.
    with caplog.at_level(logging.WARNING, logger="qaplatform.engine.events"):
        await publish_status_event(None, "rid", "running")

    assert not [
        record for record in caplog.records
        if record.name == "qaplatform.engine.events"
    ]


@pytest.mark.asyncio
async def test_publish_status_event_swallows_redis_errors(caplog):
    redis = AsyncMock()
    redis.xadd.side_effect = RuntimeError("redis down")

    # Must not raise even when redis is broken
    with caplog.at_level(logging.WARNING, logger="qaplatform.engine.events"):
        started_at = datetime.now(timezone.utc)
        await publish_status_event(redis, "rid", "running")
        finished_at = datetime.now(timezone.utc)

    redis.xadd.assert_awaited_once_with(
        EVENT_STREAM_KEY.format(run_id="rid"),
        {
            "run_id": "rid",
            "status": "running",
            "timestamp": ANY,
        },
    )
    event = redis.xadd.await_args.args[1]
    event_timestamp = datetime.fromisoformat(event["timestamp"])
    assert event == {
        "run_id": "rid",
        "status": "running",
        "timestamp": event["timestamp"],
    }
    assert started_at <= event_timestamp <= finished_at
    assert event_timestamp.tzinfo is timezone.utc
    redis.hset.assert_not_awaited()
    warning_records = [
        {
            "levelno": record.levelno,
            "message": record.getMessage(),
            "exc_type": (
                type(record.exc_info[1]).__name__
                if record.exc_info is not None
                else None
            ),
            "exc_message": (
                str(record.exc_info[1]) if record.exc_info is not None else None
            ),
        }
        for record in caplog.records
        if record.name == "qaplatform.engine.events"
    ]
    assert warning_records == [
        {
            "levelno": logging.WARNING,
            "message": "failed to publish status event for run rid (status=running)",
            "exc_type": "RuntimeError",
            "exc_message": "redis down",
        }
    ]
