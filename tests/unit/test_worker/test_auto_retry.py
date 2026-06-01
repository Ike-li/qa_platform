"""Tests for automatic retry on infrastructure failures (PRD F-EX-07)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.worker.tasks import _attempt_retry, _should_retry


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

    def test_api_max_attempts_translates_to_retry_count(self):
        policy = {"max_attempts": 2, "retry_on": ["infra"]}
        assert _should_retry(ConnectionError("fail"), policy, 1) is True
        assert _should_retry(ConnectionError("fail"), policy, 2) is False

    def test_retry_on_without_infra_is_not_retryable(self):
        policy = {"max_attempts": 2, "retry_on": ["assertion"]}
        assert _should_retry(ConnectionError("fail"), policy, 1) is False

    def test_one_max_attempt_means_no_retry(self):
        policy = {"max_attempts": 1, "retry_on": ["infra"]}
        assert _should_retry(ConnectionError("fail"), policy, 1) is False


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
        run.git_sha = "abc123"
        run.priority = 1
        run.triggered_by = uuid4()
        run.trigger_type = "manual"
        run.metadata_ = {"git_url": "https://github.com/org/repo.git"}
        run.retry_group_id = run.id
        run.chain_depth = 0
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


def _assert_retry_run_create(run_repo, original):
    expected_metadata = dict(original.metadata_ or {})
    run_repo.create.assert_awaited_once_with(
        tenant_id=original.tenant_id,
        project_id=original.project_id,
        pipeline_id=original.pipeline_id,
        environment_id=original.environment_id,
        git_ref=original.git_ref,
        git_sha=original.git_sha,
        priority=original.priority,
        triggered_by=original.triggered_by,
        trigger_type=original.trigger_type,
        metadata_=expected_metadata,
        retry_group_id=original.retry_group_id or original.id,
        attempt=original.attempt + 1,
        source_run_id=original.id,
        chain_depth=(original.chain_depth or 0) + 1,
    )
    assert run_repo.create.await_args.kwargs["metadata_"] is not original.metadata_


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
        _assert_retry_run_create(run_repo, original)
        scheduler.enqueue.assert_awaited_once_with(retry_run, _defer_by=0)

    @pytest.mark.asyncio
    async def test_returns_false_when_should_retry_false(
        self, mock_run_factory, mock_session_factory
    ):
        original = mock_run_factory(attempt=1, retry_policy=None)
        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=original)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        error = ConnectionError("fail")
        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.scheduler.FairScheduler") as scheduler_cls,
            patch("qaplatform.worker.tasks._should_retry", return_value=False) as should_retry,
        ):
            session = mock_session_factory()
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(original.id), error, ctx, sf)

        assert result is False
        sf.assert_called_once_with()
        run_repo.get_by_id.assert_awaited_once_with(str(original.id))
        session.refresh.assert_awaited_once_with(original, ["pipeline"])
        should_retry.assert_called_once_with(error, original.pipeline.retry_policy, original.attempt)
        run_repo.create.assert_not_awaited()
        scheduler_cls.assert_not_called()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_when_original_not_found(self, mock_session_factory):
        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=None)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        missing_id = uuid4()
        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.scheduler.FairScheduler") as scheduler_cls,
        ):
            session = mock_session_factory()
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(missing_id), ConnectionError("fail"), ctx, sf)

        assert result is False
        sf.assert_called_once_with()
        run_repo.get_by_id.assert_awaited_once_with(str(missing_id))
        session.refresh.assert_not_awaited()
        run_repo.create.assert_not_awaited()
        scheduler_cls.assert_not_called()
        session.commit.assert_not_awaited()

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
        _assert_retry_run_create(run_repo, original)
        scheduler.enqueue.assert_awaited_once_with(retry_run, _defer_by=0)

    @pytest.mark.asyncio
    async def test_non_infra_exception_not_retried(
        self, mock_run_factory, mock_session_factory
    ):
        """RuntimeError is not in _INFRA_EXCEPTIONS — retry should not be scheduled.

        This test exercises the real _should_retry predicate (no mock) to
        verify the FAILED-status path correctly rejects non-infra errors.
        """
        policy = {"enabled": True, "max_retries": 3, "backoff_seconds": 0}
        original = mock_run_factory(attempt=1, retry_policy=policy)

        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=original)

        scheduler = AsyncMock()
        scheduler.enqueue = AsyncMock(return_value=True)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        error = RuntimeError("pipeline execution failed")
        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.scheduler.FairScheduler") as scheduler_cls,
        ):
            scheduler_cls.return_value = scheduler
            session = mock_session_factory()
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(original.id), error, ctx, sf)

        assert result is False
        sf.assert_called_once_with()
        run_repo.get_by_id.assert_awaited_once_with(str(original.id))
        session.refresh.assert_awaited_once_with(original, ["pipeline"])
        run_repo.create.assert_not_awaited()
        scheduler_cls.assert_not_called()
        scheduler.enqueue.assert_not_awaited()
        session.commit.assert_not_awaited()

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
        ):
            session = AsyncMock()
            sf = MagicMock(return_value=session)
            await _attempt_retry(str(original.id), ConnectionError("fail"), ctx, sf)

        # attempt=2: delay = 30 * 2^(2-1) = 60, passed as _defer_by to scheduler
        _assert_retry_run_create(run_repo, original)
        scheduler.enqueue.assert_awaited_once_with(retry_run, _defer_by=60)

    @pytest.mark.asyncio
    async def test_waiting_retry_run_counts_as_scheduled(self, mock_run_factory):
        policy = {"enabled": True, "max_retries": 3, "backoff_seconds": 0}
        original = mock_run_factory(attempt=1, retry_policy=policy)

        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=original)
        retry_run = MagicMock()
        retry_run.id = uuid4()
        retry_run.attempt = 2
        retry_run.project_id = original.project_id
        retry_run.trigger_type = "manual"
        operations = []

        async def create_retry_run(**kwargs):
            operations.append(("create", kwargs["attempt"], kwargs["source_run_id"]))
            return retry_run

        run_repo.create = AsyncMock(side_effect=create_retry_run)

        scheduler = AsyncMock()

        async def enqueue_waiting(run, **kwargs):
            operations.append(("enqueue", run.id, kwargs))
            return False

        scheduler.enqueue = AsyncMock(side_effect=enqueue_waiting)

        ctx = {"arq_pool": MagicMock(), "settings": MagicMock()}

        with (
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.scheduler.FairScheduler", return_value=scheduler),
        ):
            session = AsyncMock()
            session.__aenter__.return_value = session

            async def commit_session():
                operations.append(("commit", None, {}))

            session.commit.side_effect = commit_session
            sf = MagicMock(return_value=session)
            result = await _attempt_retry(str(original.id), ConnectionError("fail"), ctx, sf)

        assert result is True
        sf.assert_called_once_with()
        run_repo.get_by_id.assert_awaited_once_with(str(original.id))
        session.refresh.assert_awaited_once_with(original, ["pipeline"])
        _assert_retry_run_create(run_repo, original)
        scheduler.enqueue.assert_awaited_once_with(retry_run, _defer_by=0)
        session.commit.assert_awaited_once_with()
        assert operations == [
            ("create", 2, original.id),
            ("enqueue", retry_run.id, {"_defer_by": 0}),
            ("commit", None, {}),
        ]
