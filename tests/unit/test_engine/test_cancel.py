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
        backend.wait = AsyncMock()

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
    async def test_graceful_stop_returns_early_when_container_exits_on_sigterm(
        self, executor
    ):
        """F-EX-06: a container that responds to SIGTERM must NOT incur the
        full 30 s grace wait. We model the common case (container exits
        immediately) and assert that force_kill is *not* called and that
        the legacy unconditional ``asyncio.sleep(30)`` is gone."""
        executor._active_execution_id = "container-xyz"
        # backend.wait returns immediately — container honoured SIGTERM.
        executor.backend.wait = AsyncMock(return_value=None)

        sleep_mock = AsyncMock()
        with patch("qaplatform.engine.executor.asyncio.sleep", sleep_mock):
            await executor._handle_cancel_signal("run-id")

        executor.backend.cancel.assert_awaited_once_with("container-xyz")
        executor.backend.force_kill.assert_not_called()
        # The old implementation slept 30 s unconditionally; the new one
        # must not call asyncio.sleep at all on the happy path.
        sleep_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_graceful_stop_force_kills_when_container_ignores_sigterm(
        self, executor
    ):
        """F-PL-03: the 30 s grace window is the upper bound. If the
        container ignores SIGTERM for the full window we must escalate
        to SIGKILL."""
        executor._active_execution_id = "container-xyz"
        # backend.wait blocks past the grace window — container ignored SIGTERM.
        executor.backend.wait = AsyncMock(side_effect=asyncio.TimeoutError())

        await executor._handle_cancel_signal("run-id")

        executor.backend.cancel.assert_awaited_once_with("container-xyz")
        executor.backend.force_kill.assert_awaited_once_with("container-xyz")
        # cancel must precede force_kill — the order is part of the contract.
        cancel_call = executor.backend.cancel.await_args_list[0]
        force_call = executor.backend.force_kill.await_args_list[0]
        assert cancel_call is not None and force_call is not None

    @pytest.mark.asyncio
    async def test_sigterm_failure_still_force_kills(self, executor):
        """If SIGTERM fails (e.g. container already gone) we still want to
        attempt force_kill — otherwise an aiodocker hiccup mid-cancel
        would leave the run in a half-cancelled state."""
        executor._active_execution_id = "c"
        executor.backend.cancel.side_effect = RuntimeError("boom")
        # wait raises -> falls through to force_kill path
        executor.backend.wait = AsyncMock(side_effect=asyncio.TimeoutError())

        await executor._handle_cancel_signal("r")

        executor.backend.force_kill.assert_awaited_once_with("c")
