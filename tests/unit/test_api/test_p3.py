"""Tests for P3 endpoints: webhooks, analytics, batch operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from types import SimpleNamespace


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def project_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.tenant_id = tenant_id
    user.role = "owner"
    user.is_platform_admin = False
    return user


def _make_run(
    *,
    tenant_id,
    project_id,
    status,
    user_id=None,
    run_id=None,
    attempt=1,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=run_id or uuid.uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        pipeline_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        status=status,
        trigger_type="manual",
        priority=1,
        triggered_by=user_id,
        git_ref="main",
        git_sha="abc123",
        attempt=attempt,
        started_at=None,
        finished_at=None,
        duration_ms=None,
        summary=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        metadata_={},
        chain_depth=0,
        pipeline=SimpleNamespace(name="smoke"),
        environment=SimpleNamespace(name="default"),
    )


@pytest.fixture
def mock_project(project_id, tenant_id):
    obj = MagicMock()
    obj.id = project_id
    obj.tenant_id = tenant_id
    obj.status = "active"
    obj.git_url = "https://github.com/org/repo.git"
    obj.git_auth_method = "none"
    obj.credential_id = None
    obj.shallow_clone = False
    obj.default_branch = "main"
    obj.default_env_id = uuid.uuid4()
    obj.settings = {}
    return obj


@pytest.fixture
def mock_pipeline(project_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    return obj


@pytest.fixture
def mock_repos(mock_project, mock_pipeline):
    repos = MagicMock()
    repos.project.get_for_tenant = AsyncMock(return_value=mock_project)
    repos.pipeline.list_by_project = AsyncMock(return_value=([mock_pipeline], 1))
    repos.environment.list_by_project = AsyncMock(return_value=([MagicMock(id=uuid.uuid4())], 1))
    repos.run = AsyncMock()
    repos.run.create = AsyncMock()
    repos.run.get_for_tenant = AsyncMock()
    repos.run.get_active_by_dedup = AsyncMock(return_value=None)
    repos.run.cancel_if_current = AsyncMock(return_value=True)
    repos.audit = AsyncMock()
    repos.audit.create = AsyncMock()
    return repos


@pytest.fixture
def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    container_mock = MagicMock()
    container_mock.redis_client = None
    app = create_app(container=container_mock)
    app.state.container = container_mock

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    async def _override_session():
        yield AsyncMock()

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_db_session] = _override_session
    return app


async def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# --------------------------------------------------------------------------- #
# Webhook trigger
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("settings", "git_ref", "expected"),
    [
        ({}, "refs/heads/feature/foo", True),
        ({"allowed_branches": "main"}, "main", True),
        ({"allowed_branches": ["main"]}, "refs/heads/main", True),
        ({"allowed_branches": ["release/*"]}, "refs/heads/release/2026.05", True),
        ({"allowed_branches": ["main"]}, "refs/heads/feature/foo", False),
    ],
)
def test_webhook_allowed_branches(settings, git_ref, expected):
    from qaplatform.api.v1.webhooks import (
        _allowed_branch_patterns,
        _branch_allowed,
        _branch_name_from_ref,
    )

    branch_name = _branch_name_from_ref(git_ref)

    assert _branch_allowed(branch_name, _allowed_branch_patterns(settings)) is expected


def test_webhook_dedup_key_and_audit_state_defaults():
    from qaplatform.api.schemas import WebhookTriggerRequest
    from qaplatform.api.v1.webhooks import _dedup_key, _webhook_decision_audit_state

    project_id = uuid.uuid4()
    body = WebhookTriggerRequest(
        git_ref="main",
        git_sha="abc123",
        metadata={"delivery_id": "delivery-123"},
    )

    assert _dedup_key({}, "https://github.com/acme/widget.git", None, "main") is None
    assert (
        _dedup_key({}, "https://github.com/acme/widget.git", "abc123", "main")
        == "webhook:https://github.com/acme/widget.git:abc123:main"
    )
    assert _webhook_decision_audit_state(
        body,
        project_id=project_id,
        branch_name="main",
        status="duplicate",
        reason="dedup_key_conflict",
    ) == {
        "project_id": str(project_id),
        "status": "duplicate",
        "reason": "dedup_key_conflict",
        "git_ref": "main",
        "git_sha": "abc123",
        "branch_name": "main",
        "provider": "webhook",
        "delivery_id": "delivery-123",
    }


def test_signature_header_prefers_platform_header_then_github_alias():
    from qaplatform.api.v1.webhooks import _signature_header

    assert _signature_header(SimpleNamespace(headers={})) == ""
    assert _signature_header(
        SimpleNamespace(headers={"X-Hub-Signature-256": "sha256=github"})
    ) == "sha256=github"
    assert _signature_header(
        SimpleNamespace(
            headers={
                "X-Webhook-Signature": "sha256=platform",
                "X-Hub-Signature-256": "sha256=github",
            }
        )
    ) == "sha256=platform"


def test_github_repo_url_candidates_expand_common_clone_forms():
    from qaplatform.api.v1.webhooks import _github_repo_url_candidates

    candidates = _github_repo_url_candidates(
        {
            "clone_url": "https://github.com/acme/widget.git",
            "ssh_url": "git@github.com:acme/widget.git",
            "git_url": "git://github.com/acme/widget.git",
            "html_url": "https://github.com/acme/widget",
            "full_name": "acme/widget",
        }
    )

    assert {
        "https://github.com/acme/widget",
        "https://github.com/acme/widget.git",
        "git@github.com:acme/widget.git",
        "git://github.com/acme/widget.git",
    }.issubset(candidates)


def test_github_push_payload_maps_to_webhook_trigger_request():
    from qaplatform.api.v1.webhooks import _github_payload_to_trigger_request

    body, repo_urls = _github_payload_to_trigger_request(
        {
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {
                "full_name": "acme/widget",
                "html_url": "https://github.com/acme/widget",
            },
        },
        event="push",
        delivery_id="delivery-123",
    )

    assert body.git_ref == "refs/heads/main"
    assert body.git_sha == "a" * 40
    assert body.metadata == {
        "provider": "github",
        "event": "push",
        "delivery_id": "delivery-123",
        "repository": "acme/widget",
    }
    assert "https://github.com/acme/widget.git" in repo_urls


def test_github_pull_request_payload_uses_head_sha_and_base_repo_urls():
    from qaplatform.api.v1.webhooks import _github_payload_to_trigger_request

    body, repo_urls = _github_payload_to_trigger_request(
        {
            "pull_request": {
                "number": 42,
                "base": {
                    "repo": {
                        "full_name": "acme/widget",
                        "html_url": "https://github.com/acme/widget",
                    }
                },
                "head": {
                    "sha": "b" * 40,
                    "repo": {"full_name": "acme/widget"},
                },
            }
        },
        event="pull_request",
        delivery_id=None,
    )

    assert body.git_ref == "refs/pull/42/head"
    assert body.git_sha == "b" * 40
    assert body.metadata == {
        "provider": "github",
        "event": "pull_request",
        "repository": "acme/widget",
    }
    assert "https://github.com/acme/widget" in repo_urls


@pytest.mark.parametrize(
    ("payload", "event", "status_code", "detail"),
    [
        ({}, "push", 400, "Missing GitHub repository payload"),
        ({"repository": {}, "after": "a" * 40}, "push", 400, "Missing GitHub ref"),
        ({"repository": {}, "ref": "refs/heads/main"}, "push", 400, "Missing GitHub commit SHA"),
        ({}, "pull_request", 400, "Missing GitHub pull_request payload"),
        (
            {"pull_request": {"base": {}, "head": None}},
            "pull_request",
            400,
            "Missing GitHub pull_request refs",
        ),
        (
            {"pull_request": {"base": {"repo": {}}, "head": {"repo": None}}},
            "pull_request",
            400,
            "Missing GitHub pull_request repo",
        ),
        (
            {
                "pull_request": {
                    "number": "42",
                    "base": {"repo": {"full_name": "acme/widget"}},
                    "head": {"repo": {"full_name": "acme/widget"}, "sha": ""},
                }
            },
            "pull_request",
            400,
            "Missing GitHub pull_request number or SHA",
        ),
        (
            {
                "pull_request": {
                    "number": 1,
                    "base": {"repo": {"full_name": "acme/widget"}},
                    "head": {"repo": {"full_name": "fork/widget"}, "sha": "b" * 40},
                }
            },
            "pull_request",
            202,
            "Fork pull requests are ignored",
        ),
        ({}, "issues", 202, "Unsupported GitHub event: issues"),
    ],
)
def test_github_payload_validation_errors_are_explicit(payload, event, status_code, detail):
    from qaplatform.api.v1.webhooks import _github_payload_to_trigger_request

    with pytest.raises(HTTPException) as excinfo:
        _github_payload_to_trigger_request(payload, event=event, delivery_id=None)

    assert excinfo.value.status_code == status_code
    assert excinfo.value.detail == detail


def test_integrity_error_detection_follows_wrapped_driver_exceptions():
    from qaplatform.api.v1.webhooks import _is_integrity_error

    class UniqueViolationError(Exception):
        pass

    wrapped = RuntimeError("repository failed")
    wrapped.__cause__ = UniqueViolationError("duplicate key value violates unique constraint")

    assert _is_integrity_error(wrapped) is True
    assert _is_integrity_error(RuntimeError("connection reset")) is False


class TestWebhookTrigger:
    @pytest.mark.asyncio
    async def test_webhook_trigger_missing_project_returns_404(self, app, mock_repos, project_id):
        mock_repos.project.get_for_tenant = AsyncMock(return_value=None)

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_webhook_trigger_signed_project_requires_signature(
        self,
        app,
        mock_project,
        mock_repos,
        project_id,
    ):
        mock_project.settings = {"webhook_secret": "signed-webhook-secret"}

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing X-Webhook-Signature header"
        mock_repos.run.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_webhook_trigger_creates_run(self, app, mock_repos, project_id, mock_pipeline):
        run = MagicMock()
        run.id = uuid.uuid4()
        run.project_id = project_id
        run.pipeline_id = mock_pipeline.id
        run.pipeline = MagicMock()
        run.pipeline.name = "test-pipeline"
        run.status = "queued"
        run.trigger_type = "webhook"
        run.triggered_by = uuid.uuid4()
        run.git_ref = "main"
        run.git_sha = "abc123"
        run.attempt = 1
        run.started_at = None
        run.finished_at = None
        run.duration_ms = None
        run.summary = None
        run.error_message = None
        run.created_at = datetime.now(timezone.utc)
        run.updated_at = datetime.now(timezone.utc)
        run.tenant_id = uuid.uuid4()
        run.environment_id = uuid.uuid4()
        run.priority = 1
        mock_repos.run.create = AsyncMock(return_value=run)

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock):
            async with await _make_client(app) as client:
                resp = await client.post(
                    f"/api/v1/webhooks/{project_id}/trigger",
                    json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
                )

        assert resp.status_code == 201
        mock_repos.run.create.assert_awaited_once()
        call_kwargs = mock_repos.run.create.call_args.kwargs
        assert call_kwargs["trigger_type"] == "webhook"
        assert call_kwargs["dedup_key"] == (
            "webhook:https://github.com/org/repo.git:abc123:main"
        )

    @pytest.mark.asyncio
    async def test_webhook_trigger_preserves_project_git_auth_metadata(
        self, app, mock_repos, project_id, mock_project, mock_pipeline
    ):
        credential_id = uuid.uuid4()
        mock_project.git_auth_method = "token"
        mock_project.credential_id = credential_id
        run = _make_run(
            tenant_id=mock_project.tenant_id,
            project_id=project_id,
            status="queued",
        )
        run.pipeline_id = mock_pipeline.id
        run.trigger_type = "webhook"
        mock_repos.run.create = AsyncMock(return_value=run)

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock):
            async with await _make_client(app) as client:
                resp = await client.post(
                    f"/api/v1/webhooks/{project_id}/trigger",
                    json={
                        "git_ref": "refs/heads/main",
                        "git_sha": "abc123",
                        "metadata": {
                            "git_auth_method": "ssh_key",
                            "credential_id": str(uuid.uuid4()),
                            "delivery_id": "delivery-1",
                        },
                    },
                )

        assert resp.status_code == 201, resp.text
        metadata = mock_repos.run.create.call_args.kwargs["metadata_"]
        assert metadata["git_auth_method"] == "token"
        assert metadata["credential_id"] == str(credential_id)
        assert metadata["delivery_id"] == "delivery-1"

    @pytest.mark.asyncio
    async def test_webhook_trigger_archived_project_409(self, app, mock_repos, project_id):
        mock_repos.project.get_for_tenant = AsyncMock(
            return_value=SimpleNamespace(status="archived", id=project_id, settings={})
        )

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "main"},
            )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_webhook_trigger_filtered_branch_returns_200_without_run(
        self,
        app,
        mock_project,
        mock_repos,
        project_id,
    ):
        mock_project.settings = {"allowed_branches": ["main"]}

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/feature/foo", "git_sha": "abc123"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "filtered"
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "webhook.filtered"
        assert audit_kwargs["resource_type"] == "project"
        assert audit_kwargs["resource_id"] == mock_project.id
        assert audit_kwargs["after_state"]["status"] == "filtered"
        assert audit_kwargs["after_state"]["reason"] == "branch_not_allowed"
        assert audit_kwargs["after_state"]["branch_name"] == "feature/foo"

    @pytest.mark.asyncio
    async def test_webhook_trigger_dedup_integrity_error_returns_duplicate(
        self,
        app,
        mock_repos,
        project_id,
    ):
        mock_repos.run.create = AsyncMock(
            side_effect=IntegrityError("insert run", {}, Exception("duplicate"))
        )

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "duplicate"}
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "webhook.duplicate"
        assert audit_kwargs["resource_type"] == "project"
        assert audit_kwargs["resource_id"] == project_id
        assert audit_kwargs["after_state"]["status"] == "duplicate"
        assert audit_kwargs["after_state"]["reason"] == "dedup_key_conflict"
        assert audit_kwargs["after_state"]["branch_name"] == "main"


# --------------------------------------------------------------------------- #
# Batch operations
# --------------------------------------------------------------------------- #


class TestBatchCancel:
    @pytest.mark.asyncio
    async def test_batch_cancel_success(self, app, mock_repos, tenant_id):
        from qaplatform.infra.database.models import RunStatusEnum

        run = _make_run(
            tenant_id=tenant_id,
            project_id=uuid.uuid4(),
            status=RunStatusEnum.RUNNING,
        )
        run_after = _make_run(
            tenant_id=tenant_id,
            project_id=run.project_id,
            status=RunStatusEnum.CANCELLED,
            run_id=run.id,
        )
        mock_repos.run.get_for_tenant = AsyncMock(side_effect=[run, run_after])
        mock_repos.run.cancel_if_current = AsyncMock(return_value=True)

        with patch("qaplatform.engine.cancel.publish_cancel", new_callable=AsyncMock), \
             patch("qaplatform.engine.events.publish_status_event", new_callable=AsyncMock):
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/cancel",
                    json={"run_ids": [str(run.id)]},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 1
        assert data["failed"] == 0
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "run.batch_cancel"
        assert audit_kwargs["resource_id"] == run.id
        assert audit_kwargs["before_state"]["status"] == "running"
        assert audit_kwargs["after_state"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_batch_cancel_not_found(self, app, mock_repos):
        mock_repos.run.get_for_tenant = AsyncMock(return_value=None)

        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/runs/batch/cancel",
                json={"run_ids": [str(uuid.uuid4())]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 0
        assert data["failed"] == 1
        assert len(data["errors"]) == 1


class TestBatchRetry:
    @pytest.mark.asyncio
    async def test_batch_retry_success(self, app, mock_repos, project_id, tenant_id):
        from qaplatform.infra.database.models import RunStatusEnum

        original = _make_run(
            tenant_id=tenant_id,
            project_id=project_id,
            status=RunStatusEnum.FAILED,
        )

        new_run = MagicMock()
        new_run.id = uuid.uuid4()
        new_run.retry_group_id = None
        new_run.attempt = 2

        mock_repos.run.get_for_tenant = AsyncMock(return_value=original)
        mock_repos.run.create = AsyncMock(return_value=new_run)

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock):
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/retry",
                    json={"run_ids": [str(original.id)]},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 1
        assert data["failed"] == 0
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "run.batch_retry"
        assert audit_kwargs["resource_id"] == original.id
        assert audit_kwargs["before_state"]["status"] == "failed"
        assert audit_kwargs["after_state"]["retry_run_id"] == str(new_run.id)

    @pytest.mark.asyncio
    async def test_batch_retry_not_terminal(self, app, mock_repos, tenant_id):
        from qaplatform.infra.database.models import RunStatusEnum

        run = MagicMock()
        run.id = uuid.uuid4()
        run.tenant_id = tenant_id
        run.status = RunStatusEnum.RUNNING
        mock_repos.run.get_for_tenant = AsyncMock(return_value=run)

        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/runs/batch/retry",
                json={"run_ids": [str(run.id)]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 0
        assert data["failed"] == 1


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


class TestAnalytics:
    """Tests for analytics endpoints with pagination support."""

    def _setup_session(self, app, mock_repos, mock_session):
        """Common session override setup for analytics tests."""
        from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user

        app.dependency_overrides = {}

        async def _override_repos():
            return mock_repos

        async def _override_user():
            return MagicMock(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner", is_platform_admin=False)

        app.dependency_overrides[_get_repos] = _override_repos
        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[_get_db_session] = lambda: mock_session

    @pytest.mark.asyncio
    async def test_trends_returns_paginated_response(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        # First call = count, second call = data
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.all.return_value = [
            SimpleNamespace(date="2026-05-19", total_runs=10, passed_runs=8, failed_runs=2),
        ]
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            resp = await client.get(f"/api/v1/projects/{project_id}/analytics/trends")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "pagination" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["date"] == "2026-05-19"
        assert body["data"][0]["total_runs"] == 10
        assert body["pagination"]["total"] == 1
        assert body["pagination"]["offset"] == 0
        assert body["pagination"]["limit"] == 365

    @pytest.mark.asyncio
    async def test_trends_with_custom_pagination(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 10
        data_result = MagicMock()
        data_result.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/trends?offset=5&limit=3",
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["pagination"]["offset"] == 5
        assert body["pagination"]["limit"] == 3
        assert body["pagination"]["total"] == 10

    @pytest.mark.asyncio
    async def test_trends_rejects_invalid_pagination(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            # offset < 0
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/trends?offset=-1",
            )
            assert resp.status_code == 422

            # limit > 365
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/trends?limit=366",
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_flaky_returns_paginated_response(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.all.return_value = [
            SimpleNamespace(suite="test_auth", name="test_login", total_runs=10, passed_count=7, failed_count=3),
        ]
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            resp = await client.get(f"/api/v1/projects/{project_id}/analytics/flaky")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "pagination" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["suite"] == "test_auth"
        assert body["data"][0]["flaky_rate"] == 0.3
        assert body["pagination"]["total"] == 1
        assert body["pagination"]["offset"] == 0
        assert body["pagination"]["limit"] == 50

    @pytest.mark.asyncio
    async def test_flaky_with_offset(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 100
        data_result = MagicMock()
        data_result.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/flaky?offset=10&limit=20",
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["pagination"]["offset"] == 10
        assert body["pagination"]["limit"] == 20
        assert body["pagination"]["total"] == 100

    @pytest.mark.asyncio
    async def test_flaky_rejects_invalid_pagination(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            # offset < 0
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/flaky?offset=-1",
            )
            assert resp.status_code == 422

            # limit > 200
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/flaky?limit=201",
            )
            assert resp.status_code == 422
