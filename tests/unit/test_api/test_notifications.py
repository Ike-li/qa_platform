"""Tests for /projects/{id}/notification-rules CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_rule(project_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    obj.name = "Test Rule"
    obj.enabled = True
    obj.conditions = [{"field": "status", "operator": "eq", "value": "failed"}]
    obj.channels = [{"type": "webhook", "config": {"url": "https://example.com"}}]
    obj.template = None
    obj.created_at = datetime.now(timezone.utc)
    return obj


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
    return obj


@pytest.fixture
def mock_repos(mock_project):
    repos = MagicMock()
    repos.project.get_for_tenant = AsyncMock(return_value=mock_project)
    repos.notification_rule = AsyncMock()
    repos.notification_rule.list_by_project = AsyncMock(return_value=([], 0))
    repos.notification_rule.get_by_id = AsyncMock(return_value=None)
    repos.notification_rule.create = AsyncMock()
    repos.notification_rule.delete = AsyncMock()
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
async def test_list_rules_empty(app, project_id):
    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/notification-rules")

    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_create_rule(app, mock_repos, project_id):
    rule = _make_orm_rule(project_id)
    mock_repos.notification_rule.create = AsyncMock(return_value=rule)

    async with await _make_client(app) as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "Test Rule",
                "channels": [{"type": "webhook", "config": {}}],
            },
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Rule"


@pytest.mark.asyncio
async def test_get_rule_not_found(app, project_id):
    async with await _make_client(app) as client:
        resp = await client.get(
            f"/api/v1/projects/{project_id}/notification-rules/{uuid.uuid4()}"
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_rule(app, mock_repos, project_id):
    rule = _make_orm_rule(project_id)
    mock_repos.notification_rule.get_by_id = AsyncMock(return_value=rule)
    mock_repos.notification_rule.delete = AsyncMock()

    async with await _make_client(app) as client:
        resp = await client.delete(
            f"/api/v1/projects/{project_id}/notification-rules/{rule.id}"
        )

    assert resp.status_code == 204
    mock_repos.notification_rule.delete.assert_awaited_once_with(rule)


@pytest.mark.asyncio
async def test_update_rule(app, mock_repos, project_id):
    rule = _make_orm_rule(project_id)
    mock_repos.notification_rule.get_by_id = AsyncMock(return_value=rule)

    async with await _make_client(app) as client:
        resp = await client.put(
            f"/api/v1/projects/{project_id}/notification-rules/{rule.id}",
            json={"name": "Updated Rule"},
        )

    assert resp.status_code == 200
    assert rule.name == "Updated Rule"
