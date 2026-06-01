"""Regression tests for P0-1: init_s3 must be wired up by lifespan and
worker on_startup, not left as None — otherwise artifact downloads silently
500 and worker artifact uploads are silently skipped.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_container_mock() -> MagicMock:
    """Return a mock DependencyContainer with all init_* as AsyncMock."""
    container = MagicMock()
    container.init_db = AsyncMock()
    container.init_redis = AsyncMock()
    container.init_arq = AsyncMock()
    container.init_s3 = AsyncMock()
    container.init_crypto = MagicMock()
    container.close = AsyncMock()
    container.plugin_registry = MagicMock()  # skip _ensure_plugin_registry branch
    container.s3_client = object()  # non-None sentinel
    container.settings = MagicMock()
    return container


# ---------------------------------------------------------------------------
# API lifespan smoke tests
# ---------------------------------------------------------------------------

class TestLifespanInitializesS3:
    """P0-1 regression: lifespan must call init_s3.

    The lifespan only runs init_* when container=None (the production path).
    Tests pass container=None and mock init_container to inject a fake container.
    """

    @pytest.mark.asyncio
    async def test_init_s3_called_during_lifespan(self):
        """init_s3 must be awaited inside the FastAPI lifespan startup path."""
        from qaplatform.main import create_app

        container = _make_container_mock()

        with patch("qaplatform.dependencies.init_container", return_value=container), \
             patch("qaplatform.config.Settings"), \
             patch("qaplatform.main.configure_logging"):
            app = create_app(container=None)
            async with app.router.lifespan_context(app):
                assert app.state.container is container
                assert app.state.container.s3_client is container.s3_client

        container.init_s3.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_s3_called_after_init_arq(self):
        """Startup initializers must run in dependency order."""
        from qaplatform.main import create_app

        call_order: list[str] = []

        container = _make_container_mock()
        container.init_db = AsyncMock(side_effect=lambda: call_order.append("init_db"))
        container.init_redis = AsyncMock(side_effect=lambda: call_order.append("init_redis"))
        container.init_arq = AsyncMock(side_effect=lambda: call_order.append("init_arq"))
        container.init_s3 = AsyncMock(side_effect=lambda: call_order.append("init_s3"))
        container.init_crypto = MagicMock(
            side_effect=lambda: call_order.append("init_crypto")
        )

        def _ensure_registry(_container):
            call_order.append("ensure_plugin_registry")

        with patch("qaplatform.dependencies.init_container", return_value=container), \
             patch("qaplatform.config.Settings"), \
             patch("qaplatform.main.configure_logging"), \
             patch("qaplatform.main._ensure_plugin_registry", side_effect=_ensure_registry), \
             patch("qaplatform.main.setup_tracing", return_value=None):
            app = create_app(container=None)
            async with app.router.lifespan_context(app):
                pass

        assert call_order == [
            "init_db",
            "init_redis",
            "init_arq",
            "init_s3",
            "init_crypto",
            "ensure_plugin_registry",
        ]

    @pytest.mark.asyncio
    async def test_init_s3_failure_propagates(self):
        """If init_s3 raises, lifespan must not swallow the error."""
        from qaplatform.main import create_app

        container = _make_container_mock()
        container.init_s3 = AsyncMock(side_effect=RuntimeError("S3 unreachable"))

        with patch("qaplatform.dependencies.init_container", return_value=container), \
             patch("qaplatform.config.Settings"), \
             patch("qaplatform.main.configure_logging"), \
             patch("qaplatform.main._ensure_plugin_registry") as ensure_registry, \
             patch("qaplatform.main.setup_tracing", return_value=None) as setup_tracing, \
             patch("qaplatform.main.instrument_infra") as instrument_infra:
            app = create_app(container=None)
            with pytest.raises(RuntimeError) as exc_info:
                async with app.router.lifespan_context(app):
                    pass  # pragma: no cover

        assert exc_info.value.args == ("S3 unreachable",)
        container.init_db.assert_awaited_once()
        container.init_redis.assert_awaited_once()
        container.init_arq.assert_awaited_once()
        container.init_s3.assert_awaited_once()
        container.init_crypto.assert_not_called()
        ensure_registry.assert_not_called()
        setup_tracing.assert_called_once()
        instrument_infra.assert_not_called()
        assert not hasattr(app.state, "container")


# ---------------------------------------------------------------------------
# Worker on_startup smoke tests
# ---------------------------------------------------------------------------

class TestWorkerStartupInitializesS3:
    """P0-1 regression: worker on_startup must call init_s3.

    DependencyContainer and Settings are imported inside on_startup, so we
    patch them at their source modules (qaplatform.dependencies /
    qaplatform.config) rather than at qaplatform.worker.settings.
    """

    @pytest.mark.asyncio
    async def test_init_s3_called_during_worker_startup(self):
        """on_startup must await init_s3 so ctx['s3_client'] is not None."""
        from qaplatform.worker.settings import on_startup

        container = _make_container_mock()

        with patch("qaplatform.dependencies.DependencyContainer", return_value=container), \
             patch("qaplatform.config.Settings", return_value=MagicMock(
                 redis_url="redis://localhost:6379/0",
                 s3_bucket="qa-platform",
             )), \
             patch("qaplatform.logging.configure_logging"), \
             patch("aiodocker.Docker", return_value=MagicMock()), \
             patch("qaplatform.engine.log_stream.LogStream", return_value=MagicMock()), \
             patch("qaplatform.plugins.registry.PluginRegistry", return_value=MagicMock()), \
             patch("qaplatform.engine.docker_backend.DockerBackend", return_value=MagicMock()), \
             patch("qaplatform.engine.executor.RunExecutor", return_value=MagicMock()):
            ctx: dict = {}
            await on_startup(ctx)

        container.init_s3.assert_awaited_once()
        assert ctx["container"] is container
        assert ctx["s3_client"] is container.s3_client
        assert ctx["s3_bucket"] == "qa-platform"

    @pytest.mark.asyncio
    async def test_worker_startup_init_s3_after_init_arq(self):
        """Worker startup initializers must run in dependency order."""
        from qaplatform.worker.settings import on_startup

        call_order: list[str] = []
        container = _make_container_mock()
        container.init_db = AsyncMock(side_effect=lambda: call_order.append("init_db"))
        container.init_redis = AsyncMock(side_effect=lambda: call_order.append("init_redis"))
        container.init_arq = AsyncMock(side_effect=lambda: call_order.append("init_arq"))
        container.init_s3 = AsyncMock(side_effect=lambda: call_order.append("init_s3"))
        container.init_crypto = MagicMock(
            side_effect=lambda: call_order.append("init_crypto")
        )

        with patch("qaplatform.dependencies.DependencyContainer", return_value=container), \
             patch("qaplatform.config.Settings", return_value=MagicMock(
                 redis_url="redis://localhost:6379/0",
                 s3_bucket="qa-platform",
             )), \
             patch("qaplatform.logging.configure_logging"), \
             patch("qaplatform.worker.settings.setup_tracing", return_value=None), \
             patch("aiodocker.Docker", return_value=MagicMock()), \
             patch("qaplatform.engine.log_stream.LogStream", return_value=MagicMock()), \
             patch("qaplatform.plugins.registry.PluginRegistry", return_value=MagicMock()), \
             patch("qaplatform.engine.docker_backend.DockerBackend", return_value=MagicMock()), \
             patch("qaplatform.engine.executor.RunExecutor", return_value=MagicMock()):
            ctx: dict = {}
            await on_startup(ctx)

        assert call_order == [
            "init_db",
            "init_redis",
            "init_arq",
            "init_s3",
            "init_crypto",
        ]

    @pytest.mark.asyncio
    async def test_worker_startup_configures_logging_before_dependencies(self):
        """Worker startup must configure logging before dependency init work."""
        from qaplatform.worker.settings import on_startup

        call_order: list[str] = []
        settings = MagicMock(
            redis_url="redis://localhost:6379/0",
            s3_bucket="qa-platform",
        )
        container = _make_container_mock()
        container.init_db = AsyncMock(side_effect=lambda: call_order.append("init_db"))

        def _configure_logging(_settings):
            call_order.append("configure_logging")

        with patch("qaplatform.config.Settings", return_value=settings), \
             patch("qaplatform.logging.configure_logging", side_effect=_configure_logging) as configure_logging, \
             patch("qaplatform.dependencies.DependencyContainer", return_value=container) as container_cls, \
             patch("aiodocker.Docker", return_value=MagicMock()), \
             patch("qaplatform.engine.log_stream.LogStream", return_value=MagicMock()), \
             patch("qaplatform.plugins.registry.PluginRegistry", return_value=MagicMock()), \
             patch("qaplatform.engine.docker_backend.DockerBackend", return_value=MagicMock()), \
             patch("qaplatform.engine.executor.RunExecutor", return_value=MagicMock()):
            await on_startup({})

        configure_logging.assert_called_once_with(settings)
        container_cls.assert_called_once_with(settings)
        assert call_order[0] == "configure_logging"
        assert call_order.index("configure_logging") < call_order.index("init_db")


# ---------------------------------------------------------------------------
# P1-6 regression: lifespan shutdown must NOT cancel asyncio.all_tasks()
# ---------------------------------------------------------------------------

class TestLifespanShutdownNoCancelAll:
    """P1-6 regression: lifespan shutdown must not cancel in-flight tasks.

    The cancel-all block was removed because:
    - Every create_task() in this codebase holds an explicit reference and
      cleans up in its own finally block (no orphan tasks).
    - Cancelling all_tasks() races with uvicorn's in-flight request drain,
      SSE long-poll generators, and asyncio.gather() sub-tasks.
    - uvicorn's graceful_timeout (default 30 s) handles the drain;
      container.close() handles connection-pool teardown.

    Coverage limitation: true in-flight SSE / uvicorn signal behaviour
    requires a real uvicorn process and cannot be exercised in unit tests.
    These tests verify the unit-testable invariants only.
    """

    @pytest.mark.asyncio
    async def test_shutdown_does_not_cancel_concurrent_tasks(self):
        """A task running concurrently with lifespan shutdown must not be cancelled."""
        import asyncio
        from qaplatform.main import create_app

        container = _make_container_mock()
        task_was_cancelled = False

        async def long_running():
            nonlocal task_was_cancelled
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                task_was_cancelled = True
                raise

        with patch("qaplatform.dependencies.init_container", return_value=container), \
             patch("qaplatform.config.Settings"), \
             patch("qaplatform.main.configure_logging"):
            app = create_app(container=None)
            async with app.router.lifespan_context(app):
                # Spawn a background task that outlives the lifespan block
                bg = asyncio.create_task(long_running())
                # Give the event loop a tick so the task starts
                await asyncio.sleep(0)

        # Cancel manually so the test loop can clean up — but the lifespan
        # itself must NOT have cancelled it first.
        assert not bg.done()
        assert not task_was_cancelled, (
            "lifespan shutdown cancelled a concurrent task — cancel-all regression"
        )
        container.close.assert_awaited_once_with()
        bg.cancel()
        await asyncio.gather(bg, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_shutdown_calls_container_close(self):
        """container.close() must still be awaited during shutdown."""
        from qaplatform.main import create_app

        container = _make_container_mock()

        with patch("qaplatform.dependencies.init_container", return_value=container), \
             patch("qaplatform.config.Settings"), \
             patch("qaplatform.main.configure_logging"):
            app = create_app(container=None)
            async with app.router.lifespan_context(app):
                pass

        container.close.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_shutdown_does_not_raise_with_no_tasks(self):
        """Lifespan shutdown must complete cleanly when no extra tasks are running."""
        from qaplatform.main import create_app

        container = _make_container_mock()

        with patch("qaplatform.dependencies.init_container", return_value=container), \
             patch("qaplatform.config.Settings"), \
             patch("qaplatform.main.configure_logging"):
            app = create_app(container=None)
            # Must not raise
            async with app.router.lifespan_context(app):
                pass

        container.close.assert_awaited_once_with()
