from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.engine.cancel import (
    CANCEL_CHANNEL_PREFIX,
    publish_cancel,
    watch_for_cancel,
)


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


# --------------------------------------------------------------------------- #
# watch_for_cancel
# --------------------------------------------------------------------------- #


class _FakePubSub:
    """Minimal redis pubsub stand-in.

    listen() yields whatever messages are pushed via ``feed`` and then
    suspends so the watcher can be cancelled cleanly.
    """

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def close(self) -> None:
        self.closed = True

    async def listen(self):
        while True:
            msg = await self._queue.get()
            if msg is None:
                return
            yield msg

    def feed(self, msg: dict) -> None:
        self._queue.put_nowait(msg)


class _FakeRedis:
    def __init__(self, pubsub: _FakePubSub):
        self._pubsub = pubsub

    def pubsub(self):
        return self._pubsub


class TestWatchForCancel:
    """Tests for the executor-side cancel subscriber."""

    @pytest.mark.asyncio
    async def test_invokes_callback_on_cancel_message(self):
        pubsub = _FakePubSub()
        redis = _FakeRedis(pubsub)
        on_cancel = AsyncMock()
        stop = asyncio.Event()
        run_id = "11111111-1111-1111-1111-111111111111"

        task = asyncio.create_task(
            watch_for_cancel(redis, run_id, on_cancel, stop)
        )
        await asyncio.sleep(0)  # let subscribe run

        assert pubsub.subscribed == [f"{CANCEL_CHANNEL_PREFIX}{run_id}"]

        pubsub.feed({"type": "message", "data": b"cancel"})
        await asyncio.wait_for(task, timeout=1.0)

        on_cancel.assert_awaited_once()
        assert pubsub.unsubscribed == [f"{CANCEL_CHANNEL_PREFIX}{run_id}"]

    @pytest.mark.asyncio
    async def test_ignores_non_message_envelopes(self):
        """Redis 'subscribe' confirmation envelopes must not fire the
        callback — otherwise every run would self-cancel on start."""
        pubsub = _FakePubSub()
        redis = _FakeRedis(pubsub)
        on_cancel = AsyncMock()
        stop = asyncio.Event()

        task = asyncio.create_task(watch_for_cancel(redis, "r1", on_cancel, stop))
        await asyncio.sleep(0)

        pubsub.feed({"type": "subscribe", "data": 1})
        pubsub.feed({"type": "message", "data": b"cancel"})

        await asyncio.wait_for(task, timeout=1.0)
        on_cancel.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_silently_when_redis_is_none(self):
        """Dev/test paths without redis must not crash the executor."""
        on_cancel = AsyncMock()
        await watch_for_cancel(None, "r1", on_cancel, asyncio.Event())
        on_cancel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_swallows_handler_exceptions(self):
        """A buggy on_cancel must not propagate and abort the executor's
        finally block."""
        pubsub = _FakePubSub()
        redis = _FakeRedis(pubsub)

        async def bad_handler():
            raise RuntimeError("boom")

        stop = asyncio.Event()
        task = asyncio.create_task(watch_for_cancel(redis, "r", bad_handler, stop))
        await asyncio.sleep(0)
        pubsub.feed({"type": "message", "data": b"cancel"})
        await asyncio.wait_for(task, timeout=1.0)


# --------------------------------------------------------------------------- #
# RunExecutor._handle_cancel_signal — F-EX-06 / F-PL-03 grace-period contract
# --------------------------------------------------------------------------- #


class TestExecutorCancelHandler:
    @pytest.fixture
    def executor(self):
        from qaplatform.engine.executor import RunExecutor

        backend = AsyncMock()
        backend.cancel = AsyncMock()
        backend.force_kill = AsyncMock()

        ex = RunExecutor(
            backend=backend,
            log_stream=AsyncMock(),
            run_repo=AsyncMock(),
            plugin_registry=MagicMock(),
        )
        return ex

    @pytest.mark.asyncio
    async def test_no_active_container_is_a_noop(self, executor):
        executor._active_execution_id = None
        await executor._handle_cancel_signal("r")
        executor.backend.cancel.assert_not_called()
        executor.backend.force_kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_sigterm_then_sigkill_after_30s(self, executor):
        """F-EX-06 + F-PL-03: SIGTERM first, 30s grace, then SIGKILL.
        We patch ``asyncio.sleep`` so the test runs in milliseconds while
        still asserting the 30s value."""
        executor._active_execution_id = "container-xyz"

        sleep_calls: list[float] = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("qaplatform.engine.executor.asyncio.sleep", fake_sleep):
            await executor._handle_cancel_signal("run-id")

        executor.backend.cancel.assert_awaited_once_with("container-xyz")
        executor.backend.force_kill.assert_awaited_once_with("container-xyz")
        # Order matters: sleep must be between cancel and force_kill, and
        # the wait must be exactly 30 seconds (the F-PL-03 grace window).
        assert sleep_calls == [30]

    @pytest.mark.asyncio
    async def test_sigterm_failure_still_force_kills(self, executor):
        """If SIGTERM fails (e.g. container already gone) we still want to
        attempt force_kill — otherwise an aiodocker hiccup mid-cancel
        would leave the run in a half-cancelled state."""
        executor._active_execution_id = "c"
        executor.backend.cancel.side_effect = RuntimeError("boom")

        with patch("qaplatform.engine.executor.asyncio.sleep", AsyncMock()):
            await executor._handle_cancel_signal("r")

        executor.backend.force_kill.assert_awaited_once_with("c")
