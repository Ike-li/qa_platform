"""Tests for P3 endpoints: webhooks, analytics, batch operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
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


@pytest.fixture
def mock_project(project_id, tenant_id):
    obj = MagicMock()
    obj.id = project_id
    obj.tenant_id = tenant_id
    obj.status = "active"
    obj.git_url = "https://github.com/org/repo.git"
    obj.git_auth_method = "none"
    obj.credential_id = None
    obj.default_branch = "main"
    obj.default_env_id = uuid.uuid4()
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


class TestWebhookTrigger:
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
                    json={"git_ref": "main"},
                )

        assert resp.status_code == 201
        mock_repos.run.create.assert_awaited_once()
        call_kwargs = mock_repos.run.create.call_args.kwargs
        assert call_kwargs["trigger_type"] == "webhook"

    @pytest.mark.asyncio
    async def test_webhook_trigger_archived_project_409(self, app, mock_repos, project_id):
        mock_repos.project.get_for_tenant = AsyncMock(
            return_value=MagicMock(status="archived", id=project_id)
        )

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "main"},
            )

        assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# Batch operations
# --------------------------------------------------------------------------- #


class TestBatchCancel:
    @pytest.mark.asyncio
    async def test_batch_cancel_success(self, app, mock_repos, tenant_id):
        from qaplatform.infra.database.models import RunStatusEnum

        run = MagicMock()
        run.id = uuid.uuid4()
        run.tenant_id = tenant_id
        run.status = RunStatusEnum.RUNNING
        mock_repos.run.get_for_tenant = AsyncMock(return_value=run)
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

        original = MagicMock()
        original.id = uuid.uuid4()
        original.tenant_id = tenant_id
        original.project_id = project_id
        original.pipeline_id = uuid.uuid4()
        original.environment_id = uuid.uuid4()
        original.git_ref = "main"
        original.git_sha = "abc123"
        original.metadata_ = {}
        original.status = RunStatusEnum.FAILED
        original.pipeline = MagicMock()
        original.environment = MagicMock()

        new_run = MagicMock()
        new_run.id = uuid.uuid4()
        new_run.retry_group_id = None

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
    @pytest.mark.asyncio
    async def test_trends_returns_data(self, app, mock_repos, project_id):
        mock_result = MagicMock()
        mock_result.all.return_value = [
            SimpleNamespace(date="2026-05-19", total_runs=10, passed_runs=8, failed_runs=2),
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        app.dependency_overrides = {}
        from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user

        async def _override_repos():
            return mock_repos

        async def _override_user():
            return MagicMock(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner", is_platform_admin=False)

        app.dependency_overrides[_get_repos] = _override_repos
        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[_get_db_session] = lambda: mock_session

        async with await _make_client(app) as client:
            resp = await client.get(f"/api/v1/projects/{project_id}/analytics/trends")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_flaky_returns_data(self, app, mock_repos, project_id):
        mock_result = MagicMock()
        mock_result.all.return_value = [
            SimpleNamespace(suite="test_auth", name="test_login", total_runs=10, passed_count=7, failed_count=3),
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        app.dependency_overrides = {}
        from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user

        async def _override_repos():
            return mock_repos

        async def _override_user():
            return MagicMock(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner", is_platform_admin=False)

        app.dependency_overrides[_get_repos] = _override_repos
        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[_get_db_session] = lambda: mock_session

        async with await _make_client(app) as client:
            resp = await client.get(f"/api/v1/projects/{project_id}/analytics/flaky")

        assert resp.status_code == 200
