"""Tests for /projects/{id}/members CRUD: list, add, update, remove.

The router now uses repository methods (repos.project_member, repos.user)
instead of direct session.execute calls. We mock the repository layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_project(tenant_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.tenant_id = tenant_id
    return obj


def _make_orm_user(tenant_id, **overrides):
    obj = MagicMock()
    obj.id = overrides.get("id", uuid.uuid4())
    obj.tenant_id = tenant_id
    obj.username = overrides.get("username", "alice")
    obj.email = overrides.get("email", "alice@x.io")
    return obj


def _make_orm_member(project_id, user_id, tenant_id, role="developer"):
    obj = MagicMock()
    obj.project_id = project_id
    obj.user_id = user_id
    obj.tenant_id = tenant_id
    obj.role = role
    obj.created_at = datetime.now(timezone.utc)
    obj.user = _make_orm_user(tenant_id, id=user_id)
    return obj


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    user.is_platform_admin = False
    return user


@pytest.fixture
def mock_project_repo(tenant_id):
    repo = AsyncMock()
    repo.get_for_tenant.return_value = _make_orm_project(tenant_id)
    return repo


@pytest.fixture
def mock_repos(mock_project_repo):
    repos = MagicMock()
    repos.project = mock_project_repo
    repos.project_member = AsyncMock()
    repos.user = AsyncMock()
    repos.audit = AsyncMock()
    return repos


@pytest.fixture
def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    app = create_app(container=MagicMock())

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    return app


async def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_list_project_members_returns_rows(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    member1 = _make_orm_member(project_id, uuid.uuid4(), tenant_id, role="admin")
    member2 = _make_orm_member(project_id, uuid.uuid4(), tenant_id, role="viewer")
    mock_repos.project_member.list_by_project_tenant.return_value = [member1, member2]

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project_id}/members",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    assert {m["role"] for m in body} == {"admin", "viewer"}


@pytest.mark.asyncio
async def test_add_member_happy_path(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_user = _make_orm_user(tenant_id)

    mock_repos.user.get_by_id.return_value = target_user
    mock_repos.project_member.get_existing.return_value = None

    created_member = _make_orm_member(project_id, target_user.id, tenant_id, role="developer")
    mock_repos.project_member.create.return_value = created_member

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project_id}/members",
            json={"user_id": str(target_user.id), "role": "developer"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "developer"
    mock_repos.project_member.create.assert_called_once()


@pytest.mark.asyncio
async def test_add_member_rejects_cross_tenant_user(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    foreign_user = _make_orm_user(tenant_id=uuid.uuid4())

    mock_repos.user.get_by_id.return_value = foreign_user

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project_id}/members",
            json={"user_id": str(foreign_user.id), "role": "developer"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_add_member_duplicate_returns_409(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_user = _make_orm_user(tenant_id)
    existing = _make_orm_member(project_id, target_user.id, tenant_id)

    mock_repos.user.get_by_id.return_value = target_user
    mock_repos.project_member.get_existing.return_value = existing

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project_id}/members",
            json={"user_id": str(target_user.id), "role": "developer"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_member_role(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()
    member = _make_orm_member(project_id, target_uid, tenant_id, role="developer")
    mock_repos.project_member.get_by_project_user.return_value = member

    async with await _make_client(app) as ac:
        resp = await ac.put(
            f"/api/v1/projects/{project_id}/members/{target_uid}",
            json={"role": "admin"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text
    mock_repos.project_member.update.assert_called_once_with(member, role="admin")


@pytest.mark.asyncio
async def test_remove_member(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()
    member = _make_orm_member(project_id, target_uid, tenant_id)
    mock_repos.project_member.get_existing.return_value = member

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project_id}/members/{target_uid}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 204
    mock_repos.project_member.delete.assert_called_once_with(member)


@pytest.mark.asyncio
async def test_remove_nonexistent_member_returns_404(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    mock_repos.project_member.get_existing.return_value = None

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project_id}/members/{uuid.uuid4()}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 404
