"""Unit tests for test quarantine endpoints (T17)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.main import create_app


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id, mock_user_id):
    user = MagicMock()
    user.user_id = mock_user_id
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    user.is_platform_admin = True
    return user


@pytest.fixture
def mock_repos():
    repos = MagicMock()
    repos.project = AsyncMock()
    repos.quarantine = AsyncMock()
    repos.audit = AsyncMock()
    return repos


@pytest.fixture
async def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    async def _override_session():
        yield MagicMock()

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_db_session] = _override_session
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


_AUTH = {"Authorization": "Bearer fake"}


@pytest.mark.asyncio
async def test_list_quarantine_success(client, mock_repos, tenant_id):
    project_id = uuid4()
    project = SimpleNamespace(id=project_id, tenant_id=tenant_id, status="active")
    mock_repos.project.get_for_tenant.return_value = project

    now = datetime.now(timezone.utc)
    mock_rows = [
        SimpleNamespace(
            id=uuid4(),
            project_id=project_id,
            suite="tests.suite_a",
            name="test_1",
            reason="Flaky in staging",
            created_by=uuid4(),
            created_at=now,
            expires_at=None,
        )
    ]
    mock_repos.quarantine.list_by_project.return_value = (mock_rows, 1)

    resp = await client.get(f"/api/v1/projects/{project_id}/quarantine", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["data"]) == 1
    assert body["data"][0]["suite"] == "tests.suite_a"
    assert body["data"][0]["name"] == "test_1"
    assert body["data"][0]["reason"] == "Flaky in staging"
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.quarantine.list_by_project.assert_awaited_once_with(
        project_id, offset=0, limit=20
    )


@pytest.mark.asyncio
async def test_list_quarantine_project_not_found(client, mock_repos):
    project_id = uuid4()
    mock_repos.project.get_for_tenant.return_value = None

    resp = await client.get(f"/api/v1/projects/{project_id}/quarantine", headers=_AUTH)

    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "Project not found"


@pytest.mark.asyncio
async def test_add_to_quarantine_success(client, mock_repos, tenant_id, mock_user_id):
    project_id = uuid4()
    project = SimpleNamespace(id=project_id, tenant_id=tenant_id, status="active")
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.quarantine.get_quarantine.return_value = None

    now = datetime.now(timezone.utc)
    record_id = uuid4()
    mock_record = SimpleNamespace(
        id=record_id,
        project_id=project_id,
        suite="tests.suite_a",
        name="test_1",
        reason="Flaky in staging",
        created_by=mock_user_id,
        created_at=now,
        expires_at=None,
    )
    mock_repos.quarantine.add_to_quarantine.return_value = mock_record

    payload = {
        "suite": "tests.suite_a",
        "name": "test_1",
        "reason": "Flaky in staging",
    }
    resp = await client.post(
        f"/api/v1/projects/{project_id}/quarantine", json=payload, headers=_AUTH
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(record_id)
    assert body["suite"] == "tests.suite_a"
    assert body["name"] == "test_1"
    assert body["reason"] == "Flaky in staging"

    mock_repos.quarantine.add_to_quarantine.assert_awaited_once_with(
        project_id=project_id,
        suite="tests.suite_a",
        name="test_1",
        reason="Flaky in staging",
        created_by=mock_user_id,
        expires_at=None,
    )
    mock_repos.audit.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_to_quarantine_archived_project(client, mock_repos, tenant_id):
    project_id = uuid4()
    project = SimpleNamespace(id=project_id, tenant_id=tenant_id, status="archived")
    mock_repos.project.get_for_tenant.return_value = project

    payload = {
        "suite": "tests.suite_a",
        "name": "test_1",
        "reason": "Flaky in staging",
    }
    resp = await client.post(
        f"/api/v1/projects/{project_id}/quarantine", json=payload, headers=_AUTH
    )

    assert resp.status_code == 409
    assert "archived" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_to_quarantine_validation_error(client, mock_repos, tenant_id):
    project_id = uuid4()
    payload = {
        "suite": "",
        "name": "test_1",
        "reason": "x" * 1001,  # Too long
    }
    resp = await client.post(
        f"/api/v1/projects/{project_id}/quarantine", json=payload, headers=_AUTH
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_remove_from_quarantine_success(client, mock_repos, tenant_id):
    project_id = uuid4()
    project = SimpleNamespace(id=project_id, tenant_id=tenant_id, status="active")
    mock_repos.project.get_for_tenant.return_value = project

    now = datetime.now(timezone.utc)
    record_id = uuid4()
    mock_record = SimpleNamespace(
        id=record_id,
        project_id=project_id,
        suite="tests.suite_a",
        name="test_1",
        reason="Flaky",
        created_by=uuid4(),
        created_at=now,
        expires_at=None,
    )
    mock_repos.quarantine.get_quarantine.return_value = mock_record

    resp = await client.delete(
        f"/api/v1/projects/{project_id}/quarantine",
        params={"suite": "tests.suite_a", "name": "test_1"},
        headers=_AUTH,
    )

    assert resp.status_code == 204
    mock_repos.quarantine.remove_from_quarantine.assert_awaited_once_with(
        project_id, "tests.suite_a", "test_1"
    )
    mock_repos.audit.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_from_quarantine_not_found(client, mock_repos, tenant_id):
    project_id = uuid4()
    project = SimpleNamespace(id=project_id, tenant_id=tenant_id, status="active")
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.quarantine.get_quarantine.return_value = None

    resp = await client.delete(
        f"/api/v1/projects/{project_id}/quarantine",
        params={"suite": "tests.suite_a", "name": "test_1"},
        headers=_AUTH,
    )

    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]["message"].lower()
