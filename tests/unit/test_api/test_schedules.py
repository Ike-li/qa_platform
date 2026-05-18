"""Tests for /projects/{id}/schedules CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_schedule(project_id, pipeline_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    obj.pipeline_id = pipeline_id
    obj.cron_expr = "0 * * * *"
    obj.timezone = "Asia/Shanghai"
    obj.missed_fire_policy = "skip"
    obj.quiet_windows = []
    obj.enabled = True
    obj.last_run_at = None
    obj.next_run_at = datetime.now(timezone.utc)
    obj.last_error = None
    obj.created_at = datetime.now(timezone.utc)
    return obj


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def project_id():
    return uuid.uuid4()


@pytest.fixture
def pipeline_id():
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
    obj.default_branch = "main"
    return obj


@pytest.fixture
def mock_pipeline(pipeline_id, project_id):
    obj = MagicMock()
    obj.id = pipeline_id
    obj.project_id = project_id
    return obj


@pytest.fixture
def mock_repos(mock_project, mock_pipeline):
    repos = MagicMock()
    repos.project.get_for_tenant = AsyncMock(return_value=mock_project)
    repos.pipeline.get_by_id = AsyncMock(return_value=mock_pipeline)
    repos.schedule = AsyncMock()
    repos.schedule.list_by_project = AsyncMock(return_value=([], 0))
    repos.schedule.get_by_id = AsyncMock(return_value=None)
    repos.schedule.create = AsyncMock()
    repos.schedule.delete = AsyncMock()
    repos.audit = AsyncMock()
    repos.audit.create = AsyncMock()
    return repos


@pytest.fixture
def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    app = create_app(container=MagicMock())
    app.state.container = MagicMock()

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


@pytest.mark.asyncio
async def test_list_schedules_empty(app, mock_repos, project_id):
    mock_repos.schedule.list_by_project = AsyncMock(return_value=([], 0))

    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/schedules")

    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_create_schedule(app, mock_repos, project_id, pipeline_id):
    schedule = _make_orm_schedule(project_id, pipeline_id)
    mock_repos.schedule.create = AsyncMock(return_value=schedule)

    with patch("qaplatform.api.v1.schedules.compute_next_run_at", return_value=datetime.now(timezone.utc)):
        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/projects/{project_id}/schedules",
                json={
                    "pipeline_id": str(pipeline_id),
                    "cron_expr": "0 * * * *",
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["cron_expr"] == "0 * * * *"
    assert data["pipeline_id"] == str(pipeline_id)


@pytest.mark.asyncio
async def test_get_schedule_not_found(app, project_id):
    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/schedules/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_schedule(app, mock_repos, project_id, pipeline_id):
    schedule = _make_orm_schedule(project_id, pipeline_id)
    mock_repos.schedule.get_by_id = AsyncMock(return_value=schedule)
    mock_repos.schedule.delete = AsyncMock()

    async with await _make_client(app) as client:
        resp = await client.delete(f"/api/v1/projects/{project_id}/schedules/{schedule.id}")

    assert resp.status_code == 204
    mock_repos.schedule.delete.assert_awaited_once_with(schedule.id)


@pytest.mark.asyncio
async def test_update_schedule_recomputes_next_run(app, mock_repos, project_id, pipeline_id):
    schedule = _make_orm_schedule(project_id, pipeline_id)
    mock_repos.schedule.get_by_id = AsyncMock(return_value=schedule)

    new_next = datetime.now(timezone.utc)
    with patch("qaplatform.api.v1.schedules.compute_next_run_at", return_value=new_next):
        async with await _make_client(app) as client:
            resp = await client.put(
                f"/api/v1/projects/{project_id}/schedules/{schedule.id}",
                json={"cron_expr": "30 2 * * *"},
            )

    assert resp.status_code == 200
    assert schedule.cron_expr == "30 2 * * *"
