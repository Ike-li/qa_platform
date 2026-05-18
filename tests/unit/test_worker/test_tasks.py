"""Unit tests for qaplatform.worker.tasks.execute_run.

P0-B: verify the long-lived worker transaction is split — the row lock
acquired by claim_for_worker (UPDATE...RETURNING) must be released
immediately after a successful claim so the cancel API and status reads
on other connections aren't blocked for the duration of the run.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def fake_run():
    run = MagicMock()
    run.id = uuid4()
    run.cancel_requested_at = None
    run.pipeline = MagicMock()
    run.pipeline.stages = []
    run.pipeline.timeout_seconds = 60
    run.pipeline.retry_policy = None
    run.environment = MagicMock()
    run.environment.base_image = "python:3.12-alpine"
    run.environment.env_vars = {}
    run.environment.memory_mb = 512
    run.environment.cpu_cores = 1.0
    run.environment.network_policy = "deny"
    run.environment.setup_script = None
    return run


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    # Default: session.execute returns an active project (for archive check)
    active_project = MagicMock()
    active_project.status = "active"
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = active_project
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    factory = MagicMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = mock_session
    cm.__aexit__.return_value = None
    factory.return_value = cm
    return factory


@pytest.fixture
def ctx(mock_session_factory):
    return {
        "log_stream": AsyncMock(),
        "worker_id": "worker-test",
        "redis": AsyncMock(),
        "db_session_factory": mock_session_factory,
        "docker_backend": MagicMock(),
        "plugin_registry": MagicMock(),
        "s3_client": None,
        "s3_bucket": "qa-platform",
    }


class TestClaimReleasesRowLock:
    """P0-B step 1: claim_for_worker -> session.commit() must run before
    the long execute() phase so PREPARING row lock is released early."""

    @pytest.mark.asyncio
    async def test_commit_called_immediately_after_successful_claim(
        self, ctx, mock_session, fake_run
    ):
        from qaplatform.worker import tasks as worker_tasks

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=fake_run)
        run_repo.release_worker = AsyncMock()
        run_repo.finish_if_current = AsyncMock(return_value=True)
        run_repo.fail_if_current = AsyncMock(return_value=False)

        executor = AsyncMock()
        executor.execute = AsyncMock(side_effect=RuntimeError("stop after claim+commit"))

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ), patch(
            "qaplatform.worker.tasks._attempt_retry", new_callable=AsyncMock
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        # claim_for_worker was awaited
        run_repo.claim_for_worker.assert_awaited_once()
        # commit was called at least once and the FIRST commit happens
        # immediately after the claim, before any execute() work.
        assert mock_session.commit.await_count >= 1

    @pytest.mark.asyncio
    async def test_commit_ordering_claim_then_commit_before_execute(
        self, ctx, mock_session, fake_run
    ):
        """Order: claim_for_worker -> session.commit -> executor.execute."""
        from qaplatform.worker import tasks as worker_tasks

        call_log: list[str] = []

        async def _claim(*args, **kwargs):
            call_log.append("claim")
            return fake_run

        async def _commit():
            call_log.append("commit")

        async def _execute(*args, **kwargs):
            call_log.append("execute")
            from qaplatform.domain.models.run import RunStatus
            return RunStatus.DONE

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(side_effect=_claim)
        run_repo.release_worker = AsyncMock()
        run_repo.finish_if_current = AsyncMock(return_value=True)
        run_repo.fail_if_current = AsyncMock(return_value=False)

        mock_session.commit = AsyncMock(side_effect=_commit)

        executor = AsyncMock()
        executor.execute = AsyncMock(side_effect=_execute)

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        # The first commit MUST come between claim and execute.
        assert call_log[0] == "claim"
        assert call_log[1] == "commit"
        assert "execute" in call_log
        assert call_log.index("commit") < call_log.index("execute")

    @pytest.mark.asyncio
    async def test_no_commit_when_claim_returns_none(
        self, ctx, mock_session, fake_run
    ):
        """If claim_for_worker returns None (already claimed by someone
        else), the function returns early — no commit is required since
        UPDATE matched zero rows and the transaction holds nothing."""
        from qaplatform.worker import tasks as worker_tasks

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=None)

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=AsyncMock(),
        ):
            await worker_tasks.execute_run(ctx, str(uuid4()))

        run_repo.claim_for_worker.assert_awaited_once()
        # No-op fast path: no commits expected.
        assert mock_session.commit.await_count == 0


class TestArchiveBlocking:
    """Worker-side archive check: archived projects cancel queued runs."""

    @pytest.mark.asyncio
    async def test_worker_skips_archived_project(self, ctx, mock_session, fake_run):
        """When project is archived, worker cancels the run without executing."""
        from qaplatform.worker import tasks as worker_tasks

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=fake_run)
        run_repo.cancel_if_current = AsyncMock(return_value=True)
        run_repo.release_worker = AsyncMock()

        # Mock session.execute to return archived project
        archived_project = MagicMock()
        archived_project.status = "archived"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = archived_project
        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = AsyncMock()

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        # Run was cancelled
        run_repo.cancel_if_current.assert_awaited_once_with(fake_run.id)
        # Executor was never called
        executor.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_worker_skips_deleted_project(self, ctx, mock_session, fake_run):
        """When project is soft-deleted (None), worker cancels the run."""
        from qaplatform.worker import tasks as worker_tasks

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=fake_run)
        run_repo.cancel_if_current = AsyncMock(return_value=True)
        run_repo.release_worker = AsyncMock()

        # Mock session.execute to return None (deleted project)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = AsyncMock()

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        run_repo.cancel_if_current.assert_awaited_once_with(fake_run.id)
        executor.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_worker_executes_active_project(self, ctx, mock_session, fake_run):
        """When project is active, worker proceeds with execution."""
        from qaplatform.worker import tasks as worker_tasks
        from qaplatform.domain.models.run import RunStatus

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=fake_run)
        run_repo.release_worker = AsyncMock()
        run_repo.finish_if_current = AsyncMock(return_value=True)
        run_repo.fail_if_current = AsyncMock(return_value=False)

        # Mock session.execute to return active project
        active_project = MagicMock()
        active_project.status = "active"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active_project
        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = AsyncMock()
        executor.execute = AsyncMock(return_value=RunStatus.DONE)

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        # Executor was called (project is active)
        executor.execute.assert_awaited_once()
        # cancel_if_current was NOT called for archive reason
        run_repo.cancel_if_current.assert_not_awaited()


class TestHeartbeatLoop:
    """P1-5: _heartbeat_loop resilience to transient Redis errors."""

    @pytest.mark.asyncio
    async def test_heartbeat_continues_after_redis_error(self):
        """Verify that transient Redis errors don't kill the heartbeat loop.

        Scenario: redis.set() fails on first call, succeeds on second.
        Expected: loop continues, subsequent set() calls are made.
        """
        from qaplatform.worker.tasks import _heartbeat_loop

        worker_id = "test-worker-1"
        redis = AsyncMock()

        # First call raises Exception, second and third succeed
        redis.set = AsyncMock(side_effect=[
            Exception("Redis connection error"),
            None,  # success
            None,  # success
        ])

        # Run heartbeat with very short interval
        task = asyncio.create_task(_heartbeat_loop(worker_id, redis, interval=0.05))

        # Let it run for a bit to trigger multiple iterations
        await asyncio.sleep(0.2)

        # Cancel the task
        task.cancel()
        results = await asyncio.gather(task, return_exceptions=True)

        # Should have CancelledError, not the original Exception
        assert len(results) == 1
        assert isinstance(results[0], asyncio.CancelledError)

        # Verify redis.set was called multiple times (at least 3)
        assert redis.set.await_count >= 3

    @pytest.mark.asyncio
    async def test_heartbeat_propagates_cancelled(self):
        """Verify that CancelledError propagates cleanly from heartbeat loop.

        Scenario: heartbeat is running normally, then cancelled.
        Expected: task exits with CancelledError, not suppressed.
        """
        from qaplatform.worker.tasks import _heartbeat_loop

        worker_id = "test-worker-2"
        redis = AsyncMock()
        redis.set = AsyncMock()

        task = asyncio.create_task(_heartbeat_loop(worker_id, redis, interval=0.1))

        # Let it run for a bit
        await asyncio.sleep(0.05)

        # Cancel it
        task.cancel()
        results = await asyncio.gather(task, return_exceptions=True)

        # Should get CancelledError
        assert len(results) == 1
        assert isinstance(results[0], asyncio.CancelledError)
