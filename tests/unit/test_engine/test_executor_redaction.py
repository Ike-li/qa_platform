"""Regression tests for P0-3: executor must redact URL userinfo before
persisting exception messages via run_repo.fail_if_current.

Three test groups:
  1. executor.execute() fail-path redacts git URL tokens
  2. redact_url_userinfo is idempotent
  3. redact_url_userinfo passes through plain text unchanged
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.domain.models.run import Run, RunStatus
from qaplatform.engine.executor import RunExecutor
from qaplatform.engine.redact import redact_url_userinfo
from qaplatform.plugins.registry import PluginRegistry


# --------------------------------------------------------------------------- #
# Shared constants
# --------------------------------------------------------------------------- #

_GIT_URL_WITH_TOKEN = (
    "https://x-access-token:ghp_SECRETTOKEN@github.com/org/repo.git"
)
_GIT_URL_REDACTED = "https://***@github.com/org/repo.git"


def _make_pipeline():
    from qaplatform.engine.executor import PipelineConfig, StageDefinition

    return PipelineConfig(
        image="python:3.12-alpine",
        stages=[StageDefinition(name="pytest", plugin="pytest")],
        timeout_seconds=60,
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_run_repo():
    repo = AsyncMock()
    repo.mark_running.return_value = None
    repo.mark_collecting.return_value = None
    repo.update_execution_id.return_value = None
    repo.update_git_sha.return_value = None
    repo.finish_if_current.return_value = True
    repo.fail_if_current.return_value = True
    repo.commit.return_value = None
    repo.is_cancel_requested.return_value = False
    return repo


@pytest.fixture
def sample_run():
    run = MagicMock(spec=Run)
    run.id = uuid4()
    run.git_ref = "main"
    run.metadata = {"git_url": _GIT_URL_WITH_TOKEN}
    return run


@pytest.fixture
def fail_executor(mock_run_repo):
    """Executor whose source plugin raises a GitCloneError-like exception
    containing a raw URL with userinfo (token) in the message.
    """
    backend = AsyncMock()
    backend.create_execution = AsyncMock(return_value="container-xyz")
    backend.start = AsyncMock()
    backend.cleanup = AsyncMock()

    async def _empty_logs(_id):
        if False:
            yield

    backend.stream_logs = _empty_logs

    plugin_registry = MagicMock(spec=PluginRegistry)
    source = AsyncMock()
    source.clone.side_effect = RuntimeError(
        f"GitCloneError: git exited 128\n"
        f"fatal: repository '{_GIT_URL_WITH_TOKEN}' not found"
    )
    plugin_registry.get_source.return_value = source

    return RunExecutor(
        backend=backend,
        log_stream=AsyncMock(),
        run_repo=mock_run_repo,
        plugin_registry=plugin_registry,
    )


# --------------------------------------------------------------------------- #
# Test 1: executor fail-path redacts URL userinfo
# --------------------------------------------------------------------------- #


class TestExecutorFailRedactsGitUrlUserinfo:
    @pytest.mark.asyncio
    async def test_executor_fail_redacts_git_url_userinfo(
        self, fail_executor, sample_run, mock_run_repo
    ):
        """execute() must call fail_if_current with a message that does NOT
        contain the raw token/password from the git URL, but DOES retain the
        host so the message remains useful for debugging.
        """
        await fail_executor.execute(sample_run, _make_pipeline())

        mock_run_repo.fail_if_current.assert_awaited_once()
        _, kwargs = mock_run_repo.fail_if_current.call_args
        message = kwargs.get("message", "")

        # Token and username must be gone
        assert "ghp_SECRETTOKEN" not in message, (
            f"Token leaked into error_message: {message!r}"
        )
        assert "x-access-token" not in message, (
            f"Username leaked into error_message: {message!r}"
        )
        # Host must survive so the message is still useful
        assert "github.com" in message, (
            f"Host was stripped from error_message: {message!r}"
        )
        # Redaction marker must be present
        assert "***@" in message, (
            f"Redaction marker missing from error_message: {message!r}"
        )


# --------------------------------------------------------------------------- #
# Test 2: redact_url_userinfo is idempotent
# --------------------------------------------------------------------------- #


class TestRedactUrlUserinfoIdempotent:
    def test_redact_url_userinfo_idempotent(self):
        """Calling redact_url_userinfo on an already-redacted string must
        return the same string (idempotent — double application == single).
        """
        once = redact_url_userinfo(_GIT_URL_WITH_TOKEN)
        twice = redact_url_userinfo(once)
        assert once == twice, (
            f"Not idempotent: first={once!r}, second={twice!r}"
        )

    def test_redact_url_userinfo_idempotent_already_redacted(self):
        """A string that is already in redacted form must pass through
        unchanged.
        """
        result = redact_url_userinfo(_GIT_URL_REDACTED)
        assert result == _GIT_URL_REDACTED, (
            f"Expected unchanged, got: {result!r}"
        )


# --------------------------------------------------------------------------- #
# Test 3: redact_url_userinfo handles plain text (no URL)
# --------------------------------------------------------------------------- #


class TestRedactUrlUserinfoHandlesNoUrl:
    def test_redact_url_userinfo_handles_no_url(self):
        """Plain-text exception messages with no URL must be returned
        unchanged.
        """
        plain = "Connection refused: database is down"
        assert redact_url_userinfo(plain) == plain

    def test_redact_url_userinfo_handles_empty_string(self):
        """Empty string must be returned as-is without error."""
        assert redact_url_userinfo("") == ""

    def test_redact_url_userinfo_handles_url_without_userinfo(self):
        """A URL that has no userinfo segment must be returned unchanged."""
        url = "https://github.com/org/repo.git"
        assert redact_url_userinfo(url) == url
