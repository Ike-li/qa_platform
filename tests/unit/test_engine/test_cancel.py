from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.engine.cancel import publish_cancel, CANCEL_CHANNEL_PREFIX


class TestPublishCancel:
    """Test cancel signal publishing via Redis."""

    @pytest.mark.asyncio
    async def test_publish_cancel_sends_redis_message(self):
        redis = AsyncMock()
        run_id = uuid4()

        await publish_cancel(redis, run_id)

        redis.publish.assert_called_once_with(
            f"{CANCEL_CHANNEL_PREFIX}{run_id}",
            "cancel",
        )

    @pytest.mark.asyncio
    async def test_publish_cancel_with_string_id(self):
        redis = AsyncMock()
        run_id = uuid4()

        await publish_cancel(redis, str(run_id))

        redis.publish.assert_called_once_with(
            f"{CANCEL_CHANNEL_PREFIX}{run_id}",
            "cancel",
        )
