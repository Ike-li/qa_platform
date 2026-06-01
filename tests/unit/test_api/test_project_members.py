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


def _make_orm_member(project_id, user_id, tenant_id, role="developer", created_at=None):
    obj = MagicMock()
    obj.project_id = project_id
    obj.user_id = user_id
    obj.tenant_id = tenant_id
    obj.role = role
    obj.created_at = created_at or datetime.now(timezone.utc)
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

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

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


def _validation_error_projection(errors) -> list[dict]:
    return [
        {
            "type": error["type"],
            "loc": error["loc"],
            "msg": error["msg"],
            "input": error.get("input"),
        }
        for error in errors
    ]


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _expected_member_response(member) -> dict:
    return {
        "project_id": str(member.project_id),
        "user_id": str(member.user_id),
        "username": member.user.username,
        "email": member.user.email,
        "role": member.role,
        "created_at": _json_datetime(member.created_at),
    }


@pytest.mark.asyncio
async def test_list_project_members_returns_rows(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    member1_created_at = datetime(2026, 5, 31, 1, 2, 3, tzinfo=timezone.utc)
    member2_created_at = datetime(2026, 5, 31, 4, 5, 6, tzinfo=timezone.utc)
    member1 = _make_orm_member(
        project_id,
        uuid.uuid4(),
        tenant_id,
        role="admin",
        created_at=member1_created_at,
    )
    member2 = _make_orm_member(
        project_id,
        uuid.uuid4(),
        tenant_id,
        role="viewer",
        created_at=member2_created_at,
    )
    mock_repos.project_member.list_by_project_tenant.return_value = ([member1, member2], 2)

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project_id}/members?page=2&per_page=1",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "data": [
            {
                "project_id": str(project_id),
                "user_id": str(member1.user_id),
                "username": member1.user.username,
                "email": member1.user.email,
                "role": "admin",
                "created_at": member1_created_at.isoformat().replace("+00:00", "Z"),
            },
            {
                "project_id": str(project_id),
                "user_id": str(member2.user_id),
                "username": member2.user.username,
                "email": member2.user.email,
                "role": "viewer",
                "created_at": member2_created_at.isoformat().replace("+00:00", "Z"),
            },
        ],
        "page": 2,
        "per_page": 1,
        "total": 2,
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.project_member.list_by_project_tenant.assert_awaited_once()
    assert mock_repos.project_member.list_by_project_tenant.await_args.args == (
        project_id,
        tenant_id,
    )
    assert mock_repos.project_member.list_by_project_tenant.await_args.kwargs == {
        "offset": 1,
        "limit": 1,
    }
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_member_happy_path(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_user = _make_orm_user(tenant_id)
    created_at = datetime(2026, 5, 31, 7, 8, 9, tzinfo=timezone.utc)

    mock_repos.user.get_by_id.return_value = target_user
    mock_repos.project_member.get_existing.return_value = None

    created_member = _make_orm_member(
        project_id,
        target_user.id,
        tenant_id,
        role="developer",
        created_at=created_at,
    )
    created_member.user = target_user
    mock_repos.project_member.create.return_value = created_member
    expected = _expected_member_response(created_member)

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project_id}/members",
            json={"user_id": str(target_user.id), "role": "developer"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json() == expected
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.user.get_by_id.assert_awaited_once_with(target_user.id)
    mock_repos.project_member.get_existing.assert_awaited_once_with(
        project_id,
        target_user.id,
        tenant_id,
    )
    mock_repos.project_member.create.assert_awaited_once_with(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=target_user.id,
        role="developer",
    )
    mock_repos.audit.create.assert_awaited_once()
    assert mock_repos.audit.create.await_args.kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "project_member.add",
        "resource_type": "project_member",
        "resource_id": project_id,
        "before_state": None,
        "after_state": expected,
    }


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
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "User not in this tenant",
            "details": [],
        }
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.user.get_by_id.assert_awaited_once_with(foreign_user.id)
    mock_repos.project_member.get_existing.assert_not_awaited()
    mock_repos.project_member.create.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


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
    assert resp.json() == {"detail": "User already a project member"}
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.user.get_by_id.assert_awaited_once_with(target_user.id)
    mock_repos.project_member.get_existing.assert_awaited_once_with(
        project_id,
        target_user.id,
        tenant_id,
    )
    mock_repos.project_member.create.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_member_routes_reject_invalid_role_without_side_effects(
    app,
    tenant_id,
    mock_repos,
):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()

    async with await _make_client(app) as ac:
        responses = [
            await ac.post(
                f"/api/v1/projects/{project_id}/members",
                json={"user_id": str(target_uid), "role": "owner"},
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.put(
                f"/api/v1/projects/{project_id}/members/{target_uid}",
                json={"role": "owner"},
                headers={"Authorization": "Bearer fake"},
            ),
        ]

    for resp in responses:
        assert resp.status_code == 422
        assert _validation_error_projection(resp.json()["detail"]) == [
            {
                "type": "literal_error",
                "loc": ["body", "role"],
                "msg": "Input should be 'admin', 'developer' or 'viewer'",
                "input": "owner",
            }
        ]
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.user.get_by_id.assert_not_awaited()
    mock_repos.project_member.get_existing.assert_not_awaited()
    mock_repos.project_member.get_by_project_user.assert_not_awaited()
    mock_repos.project_member.create.assert_not_awaited()
    mock_repos.project_member.update.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_member_role(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()
    created_at = datetime(2026, 5, 31, 8, 9, 10, tzinfo=timezone.utc)
    member = _make_orm_member(
        project_id,
        target_uid,
        tenant_id,
        role="developer",
        created_at=created_at,
    )
    mock_repos.project_member.get_by_project_user.return_value = member

    async def _update(instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    mock_repos.project_member.update.side_effect = _update

    async with await _make_client(app) as ac:
        resp = await ac.put(
            f"/api/v1/projects/{project_id}/members/{target_uid}",
            json={"role": "admin"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text
    expected = _expected_member_response(member)
    assert resp.json() == expected
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.project_member.get_by_project_user.assert_awaited_once_with(
        project_id,
        target_uid,
        tenant_id,
    )
    mock_repos.project_member.update.assert_awaited_once_with(member, role="admin")
    mock_repos.audit.create.assert_awaited_once()
    assert mock_repos.audit.create.await_args.kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "project_member.update",
        "resource_type": "project_member",
        "resource_id": project_id,
        "before_state": {"user_id": str(target_uid), "role": "developer"},
        "after_state": expected,
    }


@pytest.mark.asyncio
async def test_update_nonexistent_member_returns_404_without_side_effects(
    app,
    mock_user,
    tenant_id,
    mock_repos,
):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()
    mock_repos.project_member.get_by_project_user.return_value = None

    async with await _make_client(app) as ac:
        resp = await ac.put(
            f"/api/v1/projects/{project_id}/members/{target_uid}",
            json={"role": "admin"},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Member not found",
            "details": [],
        }
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.project_member.get_by_project_user.assert_awaited_once_with(
        project_id,
        target_uid,
        tenant_id,
    )
    mock_repos.project_member.update.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_member(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()
    member = _make_orm_member(
        project_id,
        target_uid,
        tenant_id,
        created_at=datetime(2026, 5, 31, 9, 10, 11, tzinfo=timezone.utc),
    )
    mock_repos.project_member.get_existing.return_value = member

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project_id}/members/{target_uid}",
            headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 204
    assert resp.content == b""
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.project_member.get_existing.assert_awaited_once_with(
        project_id,
        target_uid,
        tenant_id,
    )
    mock_repos.project_member.delete.assert_awaited_once_with(member)
    mock_repos.audit.create.assert_awaited_once()
    assert mock_repos.audit.create.await_args.kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "project_member.remove",
        "resource_type": "project_member",
        "resource_id": project_id,
        "before_state": {"user_id": str(target_uid), "role": "developer"},
        "after_state": None,
    }


@pytest.mark.asyncio
async def test_remove_nonexistent_member_returns_404(app, mock_user, tenant_id, mock_repos):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()
    mock_repos.project_member.get_existing.return_value = None

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project_id}/members/{target_uid}",
            headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Member not found",
            "details": [],
        }
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.project_member.get_existing.assert_awaited_once_with(
        project_id,
        target_uid,
        tenant_id,
    )
    mock_repos.project_member.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_member_routes_hide_missing_project_without_side_effects(
    app, tenant_id, mock_repos
):
    project_id = uuid.uuid4()
    target_uid = uuid.uuid4()
    mock_repos.project.get_for_tenant.return_value = None

    async with await _make_client(app) as ac:
        responses = [
            await ac.get(
                f"/api/v1/projects/{project_id}/members",
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.post(
                f"/api/v1/projects/{project_id}/members",
                json={"user_id": str(target_uid), "role": "developer"},
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.put(
                f"/api/v1/projects/{project_id}/members/{target_uid}",
                json={"role": "admin"},
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.delete(
                f"/api/v1/projects/{project_id}/members/{target_uid}",
                headers={"Authorization": "Bearer fake"},
            ),
        ]

    assert [resp.status_code for resp in responses] == [404, 404, 404, 404]
    bodies = [resp.json() for resp in responses]
    expected_body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Project not found",
            "details": [],
        }
    }
    assert bodies == [expected_body] * 4
    assert [args.args for args in mock_repos.project.get_for_tenant.await_args_list] == [
        (project_id, tenant_id)
    ] * 4
    mock_repos.user.get_by_id.assert_not_awaited()
    mock_repos.project_member.list_by_project_tenant.assert_not_awaited()
    mock_repos.project_member.get_existing.assert_not_awaited()
    mock_repos.project_member.get_by_project_user.assert_not_awaited()
    mock_repos.project_member.create.assert_not_awaited()
    mock_repos.project_member.update.assert_not_awaited()
    mock_repos.project_member.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
