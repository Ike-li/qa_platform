"""Tests for automatic retry on infrastructure failures (PRD F-EX-07)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.worker.tasks import _should_retry, _attempt_retry


# --------------------------------------------------------------------------- #
# _should_retry unit tests
# --------------------------------------------------------------------------- #


class TestShouldRetry:
    """Unit tests for the retry predicate."""

    def test_infrastructure_connection_error_is_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        assert _should_retry(ConnectionError("docker daemon unreachable"), policy, 1) is True

    def test_infrastructure_timeout_error_is_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        assert _should_retry(TimeoutError("container wait timed out"), policy, 1) is True

    def test_infrastructure_os_error_is_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        assert _should_retry(OSError("no space left on device"), policy, 1) is True

    def test_runtime_error_not_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        assert _should_retry(RuntimeError("setup script failed"), policy, 1) is False

    def test_value_error_not_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        assert _should_retry(ValueError("bad config"), policy, 1) is False

    def test_generic_exception_not_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        assert _should_retry(Exception("something"), policy, 1) is False

    def test_no_policy_not_retryable(self):
        assert _should_retry(ConnectionError("fail"), None, 1) is False

    def test_disabled_policy_not_retryable(self):
        policy = {"enabled": False, "max_retries": 3}
        assert _should_retry(ConnectionError("fail"), policy, 1) is False

    def test_zero_max_retries_not_retryable(self):
        policy = {"enabled": True, "max_retries": 0}
        assert _should_retry(ConnectionError("fail"), policy, 1) is False

    def test_negative_max_retries_not_retryable(self):
        policy = {"enabled": True, "max_retries": -1}
        assert _should_retry(ConnectionError("fail"), policy, 1) is False

    def test_exhausted_retries_not_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        # attempt=4 means 3 retries already done (original=1, retries=2,3,4)
        assert _should_retry(ConnectionError("fail"), policy, 4) is False

    def test_last_retry_is_retryable(self):
        policy = {"enabled": True, "max_retries": 3}
        # attempt=3: can still retry (original=1, retry1=2, retry2=3)
        assert _should_retry(ConnectionError("fail"), policy, 3) is True

    def test_first_attempt_is_retryable(self):
        policy = {"enabled": True, "max_retries": 2}
        assert _should_retry(ConnectionError("fail"), policy, 1) is True

    def test_defaults_enabled_true(self):
        policy = {"max_retries": 1}
        assert _should_retry(ConnectionError("fail"), policy, 1) is True


# --------------------------------------------------------------------------- #
# _attempt_retry integration tests
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_run_factory():
    """Create a mock run with pipeline that has retry_policy."""

    def _make(attempt: int = 1, retry_policy=None, run_id=None):
        pipeline = MagicMock()
        pipeline.retry_policy = retry_policy

        run = MagicMock()
        run.id = run_id or uuid4()
        run.attempt = attempt
        run.tenant_id = uuid4()
        run.project_id = uuid4()
        run.pipeline_id = uuid4()
        run.environment_id = uuid4()
        run.git_ref = "main"
        run.triggered_by = uuid4()
        run.trigger_type = "manual"
        run.metadata_ = {"git_url": "https://github.com/org/repo.git"}
        run.retry_group_id = run.id
        run.pipeline = pipeline
        return run

    return _make


@pytest.fixture
def mock_session_factory():
    """Session factory that yields a mock session."""

    def _factory():
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        return session

    return _factory


class TestAttemptRetry:
    """Integration tests for _attempt_retry."""

    @pytest.mark.asyncio
    async def test_creates_retry_run_with_incremented_attempt(
        self, mock_run_factory, mock_session_factory
    ):
        policy = {"enabled": True, "max_retries": 3, "backoff_seconds": 0}
        original = mock_run_factory(attempt=1, retry_policy=policy)

        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=original)
        retry_run = MagicMock()
        retry_run.id = uuid4()
        retry_run.attempt = 2
        retry_run.project_id = original.project_id
        retry_run.trigger_type = "manual"
        run_repo.create = AsyncMock(return_value=retry_run)

        scheduler = AsyncMock()
        scheduler.enqueue = AsyncMock(return_value=True)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.scheduler.FairScheduler", return_value=scheduler),
            patch("qaplatform.worker.tasks._should_retry", return_value=True),
        ):
            session = AsyncMock()
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(original.id), ConnectionError("fail"), ctx, sf)

        assert result is True
        run_repo.create.assert_awaited_once()
        create_kwargs = run_repo.create.call_args.kwargs
        assert create_kwargs["attempt"] == 2
        assert create_kwargs["retry_group_id"] == original.retry_group_id
        assert create_kwargs["source_run_id"] == original.id

    @pytest.mark.asyncio
    async def test_returns_false_when_should_retry_false(
        self, mock_run_factory, mock_session_factory
    ):
        original = mock_run_factory(attempt=1, retry_policy=None)
        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=original)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.tasks._should_retry", return_value=False),
        ):
            session = AsyncMock()
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(original.id), ConnectionError("fail"), ctx, sf)

        assert result is False
        run_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_when_original_not_found(self, mock_session_factory):
        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=None)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        with patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo):
            session = AsyncMock()
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(uuid4()), ConnectionError("fail"), ctx, sf)

        assert result is False

    @pytest.mark.asyncio
    async def test_skips_sleep_when_backoff_zero(
        self, mock_run_factory
    ):
        policy = {"enabled": True, "max_retries": 3, "backoff_seconds": 0}
        original = mock_run_factory(attempt=1, retry_policy=policy)

        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=original)
        retry_run = MagicMock()
        retry_run.id = uuid4()
        retry_run.attempt = 2
        retry_run.project_id = original.project_id
        retry_run.trigger_type = "manual"
        run_repo.create = AsyncMock(return_value=retry_run)

        scheduler = AsyncMock()
        scheduler.enqueue = AsyncMock(return_value=True)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.scheduler.FairScheduler", return_value=scheduler),
            patch("qaplatform.worker.tasks._should_retry", return_value=True),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            session = AsyncMock()
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(original.id), ConnectionError("fail"), ctx, sf)

        # delay=0 → sleep is skipped entirely
        mock_sleep.assert_not_awaited()
        assert result is True
        scheduler.enqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enqueues_with_exponential_backoff(self, mock_run_factory):
        policy = {"enabled": True, "max_retries": 3, "backoff_seconds": 30}
        original = mock_run_factory(attempt=2, retry_policy=policy)

        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=original)
        retry_run = MagicMock()
        retry_run.id = uuid4()
        retry_run.attempt = 3
        retry_run.project_id = original.project_id
        retry_run.trigger_type = "manual"
        run_repo.create = AsyncMock(return_value=retry_run)

        scheduler = AsyncMock()
        scheduler.enqueue = AsyncMock(return_value=True)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.scheduler.FairScheduler", return_value=scheduler),
            patch("qaplatform.worker.tasks._should_retry", return_value=True),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            session = AsyncMock()
            sf = MagicMock(return_value=session)
            await _attempt_retry(str(original.id), ConnectionError("fail"), ctx, sf)

        # attempt=2: delay = 30 * 2^(2-1) = 60
        mock_sleep.assert_awaited_once_with(60)
