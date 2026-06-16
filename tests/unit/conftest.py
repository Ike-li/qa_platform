"""Shared pytest fixtures for unit tests.

Prefer these over ad-hoc MagicMock construction — they provide sensible
defaults and keep test bodies focused on the behaviour under test.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_repos():
    """Return a MagicMock repos bag with ``artifact`` pre-wired as AsyncMock.

    Individual tests override ``mock_repos.artifact.get_with_run`` or add
    other repo attributes (``run``, ``environment``, etc.) as needed.
    """
    repos = MagicMock()
    repos.artifact = AsyncMock()
    repos.quarantine = AsyncMock()
    repos.quarantine.list_keys = AsyncMock(return_value=set())
    return repos


@pytest.fixture
def mock_request():
    """Return a MagicMock request with minimal container + settings state.

    * ``s3_client`` — AsyncMock (set to ``None`` in tests that expect 503).
    * ``settings.s3_bucket`` — ``"qa-platform"``
    * ``settings.s3_presigned_url_ttl`` — ``3600``
    * ``settings.jwt_secret`` — ``"test-secret-with-at-least-32-bytes"``
    """
    request = MagicMock()
    request.app.state.container.s3_client = AsyncMock()
    request.app.state.container.settings.s3_bucket = "qa-platform"
    request.app.state.container.settings.s3_presigned_url_ttl = 3600
    request.app.state.container.settings.jwt_secret = (
        "test-secret-with-at-least-32-bytes"
    )
    return request
