from __future__ import annotations

from uuid import UUID

CANCEL_CHANNEL_PREFIX = "run:cancel:"


async def publish_cancel(redis, run_id: UUID | str) -> None:
    """Publish a cancel signal for a run via Redis pub/sub."""
    channel = f"{CANCEL_CHANNEL_PREFIX}{run_id}"
    await redis.publish(channel, "cancel")
