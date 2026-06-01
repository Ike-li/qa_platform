from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch
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

        redis.publish.assert_awaited_once_with(
            f"{CANCEL_CHANNEL_PREFIX}{run_id}",
            "cancel",
        )

    @pytest.mark.asyncio
    async def test_publish_cancel_with_string_id(self):
        redis = AsyncMock()
        run_id = uuid4()

        await publish_cancel(redis, str(run_id))

        redis.publish.assert_awaited_once_with(
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
        self.closed_with: str | None = None

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def close(self) -> None:
        self.closed = True
        self.closed_with = "close"

    async def aclose(self) -> None:
        self.closed = True
        self.closed_with = "aclose"

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
        # P1-D: watcher now keeps listening after each delivery (so a
        # cancel arriving during a stage transition still has a
        # consumer). Close the stream to make the task exit.
        await asyncio.sleep(0)
        pubsub.feed(None)
        await asyncio.wait_for(task, timeout=1.0)

        on_cancel.assert_awaited_once_with()
        assert pubsub.unsubscribed == [f"{CANCEL_CHANNEL_PREFIX}{run_id}"]
        assert pubsub.closed_with == "aclose"

    @pytest.mark.asyncio
    async def test_callback_invoked_for_each_message(self):
        """P1-D regression: a second cancel signal — e.g. a redelivery
        during a stage boundary, or the user clicking cancel twice — must
        still reach the handler. The pre-fix watcher returned after the
        first message and silently dropped subsequent ones."""
        pubsub = _FakePubSub()
        redis = _FakeRedis(pubsub)
        deliveries: list[int] = []
        first_seen = asyncio.Event()
        second_seen = asyncio.Event()

        async def _record_cancel():
            deliveries.append(len(deliveries) + 1)
            if len(deliveries) == 1:
                first_seen.set()
            elif len(deliveries) == 2:
                second_seen.set()

        on_cancel = AsyncMock(side_effect=_record_cancel)
        stop = asyncio.Event()

        task = asyncio.create_task(watch_for_cancel(redis, "r", on_cancel, stop))
        await asyncio.sleep(0)

        pubsub.feed({"type": "message", "data": b"cancel"})
        await asyncio.wait_for(first_seen.wait(), timeout=1.0)
        assert deliveries == [1]
        assert not task.done()
        assert pubsub.unsubscribed == []
        assert pubsub.closed_with is None

        pubsub.feed({"type": "message", "data": b"cancel"})
        await asyncio.wait_for(second_seen.wait(), timeout=1.0)
        assert deliveries == [1, 2]
        assert not task.done()

        pubsub.feed(None)
        await asyncio.wait_for(task, timeout=1.0)

        assert on_cancel.await_args_list == [call(), call()]
        assert pubsub.unsubscribed == [f"{CANCEL_CHANNEL_PREFIX}r"]
        assert pubsub.closed_with == "aclose"

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
        pubsub.feed(None)

        await asyncio.wait_for(task, timeout=1.0)
        on_cancel.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_returns_silently_when_redis_is_none(self):
        """Dev/test paths without redis must not crash the executor."""
        on_cancel = AsyncMock()
        await watch_for_cancel(None, "r1", on_cancel, asyncio.Event())
        on_cancel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_swallows_handler_exceptions(self, caplog):
        """A buggy on_cancel must not propagate and abort the executor's
        finally block."""
        pubsub = _FakePubSub()
        redis = _FakeRedis(pubsub)
        on_cancel = AsyncMock(side_effect=[RuntimeError("boom"), None])
        stop = asyncio.Event()
        task = asyncio.create_task(watch_for_cancel(redis, "r", on_cancel, stop))
        await asyncio.sleep(0)

        with caplog.at_level(logging.ERROR, logger="qaplatform.engine.cancel"):
            pubsub.feed({"type": "message", "data": b"cancel"})
            await asyncio.sleep(0)
            assert not task.done()
            pubsub.feed({"type": "message", "data": b"cancel"})
            pubsub.feed(None)
            await asyncio.wait_for(task, timeout=1.0)

        assert on_cancel.await_args_list == [call(), call()]
        error_records = [
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
            if record.name == "qaplatform.engine.cancel"
            and record.levelno == logging.ERROR
        ]
        assert error_records == [
            {
                "levelno": logging.ERROR,
                "message": "cancel handler raised for run r",
                "exc_type": "RuntimeError",
                "exc_message": "boom",
            }
        ]
        assert pubsub.unsubscribed == [f"{CANCEL_CHANNEL_PREFIX}r"]
        assert pubsub.closed_with == "aclose"


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
        executor.backend.cancel.assert_not_awaited()
        executor.backend.force_kill.assert_not_awaited()

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
        executor.backend.force_kill.assert_not_awaited()
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
        from qaplatform.engine.executor import GRACE_PERIOD_SECONDS

        call_log: list[object] = []
        executor._active_execution_id = "container-xyz"

        async def _cancel(execution_id):
            call_log.append(("cancel", execution_id))

        async def _wait(execution_id, timeout):
            call_log.append(("wait", execution_id, timeout))
            raise asyncio.TimeoutError

        async def _force_kill(execution_id):
            call_log.append(("force_kill", execution_id))

        executor.backend.cancel = AsyncMock(side_effect=_cancel)
        # backend.wait blocks past the grace window — container ignored SIGTERM.
        executor.backend.wait = AsyncMock(side_effect=_wait)
        executor.backend.force_kill = AsyncMock(side_effect=_force_kill)

        await executor._handle_cancel_signal("run-id")

        executor.backend.cancel.assert_awaited_once_with("container-xyz")
        executor.backend.force_kill.assert_awaited_once_with("container-xyz")
        assert call_log == [
            ("cancel", "container-xyz"),
            ("wait", "container-xyz", GRACE_PERIOD_SECONDS),
            ("force_kill", "container-xyz"),
        ]

    @pytest.mark.asyncio
    async def test_sigterm_failure_still_force_kills(self, executor):
        """If SIGTERM fails (e.g. container already gone) we still want to
        attempt force_kill — otherwise an aiodocker hiccup mid-cancel
        would leave the run in a half-cancelled state."""
        call_log: list[object] = []
        executor._active_execution_id = "c"

        async def _cancel(execution_id):
            call_log.append(("cancel", execution_id))
            raise RuntimeError("boom")

        async def _wait(execution_id, timeout):
            call_log.append(("wait", execution_id, timeout))
            raise asyncio.TimeoutError

        async def _force_kill(execution_id):
            call_log.append(("force_kill", execution_id))

        executor.backend.cancel = AsyncMock(side_effect=_cancel)
        # wait raises -> falls through to force_kill path
        executor.backend.wait = AsyncMock(side_effect=_wait)
        executor.backend.force_kill = AsyncMock(side_effect=_force_kill)

        await executor._handle_cancel_signal("r")

        executor.backend.force_kill.assert_awaited_once_with("c")
        assert [entry[0] for entry in call_log] == ["cancel", "wait", "force_kill"]


# --------------------------------------------------------------------------- #
# P1-D — stage-boundary cancel guards
# --------------------------------------------------------------------------- #


class TestStageBoundaryCancelGuard:
    """The watcher's callback only kills the active container if one is
    running when the message arrives. Two separate failure modes need a
    boundary check on top of that:

      - cancel published *before* the worker's pubsub.subscribe completed
        → message is gone (redis pub/sub does not buffer).
      - cancel arrived *between* stages, when ``_active_execution_id`` is
        None → previous behaviour was to silently drop the second / late
        signal because the watcher returned after the first delivery.

    ``_check_cancel_boundary`` covers both: the in-process Event is set
    by every callback invocation, and a fresh DB SELECT recovers the
    pub/sub-dropped case.
    """

    @pytest.fixture
    def executor(self):
        from qaplatform.engine.executor import RunExecutor

        backend = AsyncMock()
        run_repo = AsyncMock()
        run_repo.is_cancel_requested = AsyncMock(return_value=False)
        return RunExecutor(
            backend=backend,
            log_stream=AsyncMock(),
            run_repo=run_repo,
            plugin_registry=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_event_short_circuits_without_db_lookup(self, executor):
        """If the watcher already set ``_cancel_requested`` we don't need
        the DB probe — and we shouldn't pay for it on every stage."""
        executor._cancel_requested.set()

        assert await executor._check_cancel_boundary("run-id") is True
        executor.run_repo.is_cancel_requested.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_db_recovers_dropped_pubsub_signal(self, executor):
        """No callback fired (pubsub raced the subscribe) but the row has
        ``cancel_requested_at`` set — we must still stop at the boundary
        and latch the in-process flag for subsequent stages."""
        executor.run_repo.is_cancel_requested.return_value = True

        assert await executor._check_cancel_boundary("run-id") is True
        assert executor._cancel_requested.is_set()

    @pytest.mark.asyncio
    async def test_no_cancel_lets_pipeline_continue(self, executor):
        """Happy path: neither in-memory nor DB flag set → boundary
        returns False so the next stage starts normally."""
        assert await executor._check_cancel_boundary("run-id") is False

    @pytest.mark.asyncio
    async def test_db_probe_failure_falls_through(self, executor):
        """A transient DB error in is_cancel_requested must not abort
        the pipeline — we degrade to the watcher-only signal path."""
        executor.run_repo.is_cancel_requested.side_effect = RuntimeError("db down")

        assert await executor._check_cancel_boundary("run-id") is False

    @pytest.mark.asyncio
    async def test_handle_cancel_signal_sets_event_even_without_container(
        self, executor
    ):
        """When the cancel arrives between stages (no active container)
        the handler must still latch ``_cancel_requested`` so the next
        stage boundary stops the run instead of starting another stage.
        """
        executor._active_execution_id = None

        await executor._handle_cancel_signal("run-id")

        assert executor._cancel_requested.is_set()
