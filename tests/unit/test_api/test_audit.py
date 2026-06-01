"""Tests for the audit helper and integration with API write endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from qaplatform.api.audit import write_audit


class _UserIdentity(MagicMock):
    pass


def _user():
    u = MagicMock()
    u.tenant_id = uuid4()
    u.user_id = uuid4()
    return u


def _repos_with_audit():
    repos = MagicMock()
    repos.audit = AsyncMock()
    return repos


def _container_without_redis():
    container = MagicMock()
    container.redis_client = None
    return container


def _audit_route_user(*, tenant_id):
    user = MagicMock()
    user.user_id = uuid4()
    user.role = "owner"
    user.tenant_id = tenant_id
    user.is_platform_admin = False
    user.scopes = None
    return user


def _audit_event_orm(*, tenant_id, user_id, resource_id, created_at):
    event = MagicMock()
    event.id = uuid4()
    event.tenant_id = tenant_id
    event.user_id = user_id
    event.action = "project.create"
    event.resource_type = "project"
    event.resource_id = resource_id
    event.before_state = None
    event.after_state = {"name": "demo", "api_token": "redacted"}
    event.ip_address = "127.0.0.1"
    event.user_agent = "pytest"
    event.created_at = created_at
    return event


class _ResponseModel(BaseModel):
    name: str
    value: int


@pytest.mark.asyncio
async def test_write_audit_passes_through_to_repo():
    repos = _repos_with_audit()
    user = _user()
    resource_id = uuid4()

    await write_audit(
        repos, user,
        action="project.create",
        resource_type="project",
        resource_id=resource_id,
        after=_ResponseModel(name="x", value=42),
    )

    repos.audit.create.assert_awaited_once()
    assert repos.audit.create.await_args.kwargs == {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "action": "project.create",
        "resource_type": "project",
        "resource_id": resource_id,
        "before_state": None,
        "after_state": {"name": "x", "value": 42},
    }


@pytest.mark.asyncio
async def test_write_audit_serializes_pydantic_before_and_after():
    repos = _repos_with_audit()
    user = _user()
    resource_id = uuid4()
    before = _ResponseModel(name="old", value=1)
    after = _ResponseModel(name="new", value=2)

    await write_audit(
        repos, user,
        action="project.update",
        resource_type="project",
        resource_id=resource_id,
        before=before,
        after=after,
    )

    repos.audit.create.assert_awaited_once()
    assert repos.audit.create.await_args.kwargs == {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "action": "project.update",
        "resource_type": "project",
        "resource_id": resource_id,
        "before_state": {"name": "old", "value": 1},
        "after_state": {"name": "new", "value": 2},
    }


@pytest.mark.asyncio
async def test_write_audit_swallows_repo_errors(caplog):
    repos = MagicMock()
    repos.audit = AsyncMock()
    repos.audit.create.side_effect = RuntimeError("audit table is down")
    user = _user()
    resource_id = uuid4()

    # Must not raise — audit is best-effort, never blocks the main path.
    with caplog.at_level(logging.WARNING, logger="qaplatform.api.audit"):
        await write_audit(
            repos,
            user,
            action="anything",
            resource_type="x",
            resource_id=resource_id,
        )

    repos.audit.create.assert_awaited_once()
    assert repos.audit.create.await_args.kwargs == {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "action": "anything",
        "resource_type": "x",
        "resource_id": resource_id,
        "before_state": None,
        "after_state": None,
    }
    warning_records = [
        {
            "levelno": record.levelno,
            "message": record.getMessage(),
            "exc_type": (
                type(record.exc_info[1]).__name__
                if record.exc_info is not None
                else None
            ),
            "exc_message": (
                str(record.exc_info[1]) if record.exc_info is not None else None
            ),
        }
        for record in caplog.records
        if record.name == "qaplatform.api.audit" and record.levelno == logging.WARNING
    ]
    assert warning_records == [
        {
            "levelno": logging.WARNING,
            "message": (
                f"audit write failed (action=anything resource=x id={resource_id})"
            ),
            "exc_type": "RuntimeError",
            "exc_message": "audit table is down",
        }
    ]


@pytest.mark.asyncio
async def test_write_audit_handles_dict_states():
    repos = _repos_with_audit()
    user = _user()
    resource_id = uuid4()

    await write_audit(
        repos, user,
        action="env.update",
        resource_type="environment",
        resource_id=resource_id,
        before={"a": 1},
        after={"a": 2},
    )

    repos.audit.create.assert_awaited_once()
    assert repos.audit.create.await_args.kwargs == {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "action": "env.update",
        "resource_type": "environment",
        "resource_id": resource_id,
        "before_state": {"a": 1},
        "after_state": {"a": 2},
    }


# --- End-to-end route wiring verification ---


@pytest.mark.asyncio
async def test_project_create_route_invokes_audit():
    """Smoke test: POST /projects must call write_audit on success."""
    import uuid
    from datetime import datetime, timezone
    from unittest.mock import patch
    from httpx import ASGITransport, AsyncClient

    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    tenant = uuid.uuid4()
    project_orm = MagicMock()
    project_orm.id = uuid.uuid4()
    project_orm.tenant_id = tenant
    project_orm.name = "demo"
    project_orm.slug = "demo"
    project_orm.description = None
    project_orm.git_url = "https://example.com/repo.git"
    project_orm.git_auth_method = "none"
    project_orm.credential_id = None
    project_orm.default_branch = "main"
    project_orm.root_path = "."
    project_orm.shallow_clone = True
    project_orm.default_env_id = None
    project_orm.settings = {}
    project_orm.status = "active"
    project_orm.created_by = uuid.uuid4()
    project_orm.created_at = datetime.now(timezone.utc)
    project_orm.updated_at = datetime.now(timezone.utc)

    project_repo = AsyncMock()
    project_repo.get_by_slug.return_value = None
    project_repo.create.return_value = project_orm

    repos = MagicMock()
    repos.project = project_repo
    repos.audit = AsyncMock()

    user = MagicMock()
    user.user_id = str(uuid.uuid4())
    user.role = "platform_admin"
    user.tenant_id = tenant

    app = create_app(container=_container_without_redis())
    app.dependency_overrides[_get_repos] = lambda: repos
    app.dependency_overrides[get_current_user] = lambda: user

    async def _override_session():
        session = AsyncMock()
        session.add = MagicMock()
        yield session

    app.dependency_overrides[_get_db_session] = _override_session

    audit_recorder = AsyncMock()
    with patch("qaplatform.api.v1.projects.write_audit", audit_recorder):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/projects",
                json={
                    "name": "demo",
                    "slug": "demo",
                    "git_url": "https://example.com/repo.git",
                },
                headers={"Authorization": "Bearer fake"},
            )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    audit_recorder.assert_awaited_once()
    assert audit_recorder.await_args.args == (repos, user)
    kwargs = audit_recorder.await_args.kwargs
    assert kwargs == {
        "action": "project.create",
        "resource_type": "project",
        "resource_id": project_orm.id,
        "after": body,
    }


@pytest.mark.asyncio
async def test_audit_events_list_applies_filters_pagination_and_self_audits_summary():
    from httpx import ASGITransport, AsyncClient

    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    tenant_id = uuid4()
    actor_id = uuid4()
    resource_id = uuid4()
    start_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    end_at = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    event = _audit_event_orm(
        tenant_id=tenant_id,
        user_id=actor_id,
        resource_id=resource_id,
        created_at=end_at,
    )

    repos = MagicMock()
    repos.audit = MagicMock()
    repos.audit.list = AsyncMock(return_value=([event], 7))
    repos.audit.has_cross_tenant_match = AsyncMock(return_value=False)
    repos.audit.create = AsyncMock()
    user = _audit_route_user(tenant_id=tenant_id)

    app = create_app(container=_container_without_redis())
    app.dependency_overrides[_get_repos] = lambda: repos
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/audit-events",
            params={
                "actor_id": str(actor_id),
                "action": "project.create",
                "resource_type": "project",
                "resource_id": str(resource_id),
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "page": "3",
                "per_page": "2",
            },
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "data": [
            {
                "id": str(event.id),
                "tenant_id": str(tenant_id),
                "user_id": str(actor_id),
                "action": "project.create",
                "resource_type": "project",
                "resource_id": str(resource_id),
                "before_state": None,
                "after_state": event.after_state,
                "ip_address": "127.0.0.1",
                "user_agent": "pytest",
                "created_at": end_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 3,
        "per_page": 2,
        "total": 7,
    }

    repos.audit.list.assert_awaited_once_with(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="project.create",
        resource_type="project",
        resource_id=resource_id,
        start_at=start_at,
        end_at=end_at,
        offset=4,
        limit=2,
    )
    repos.audit.has_cross_tenant_match.assert_not_awaited()

    repos.audit.create.assert_awaited_once()
    audit_kwargs = repos.audit.create.await_args.kwargs
    assert audit_kwargs["tenant_id"] == tenant_id
    assert audit_kwargs["user_id"] == user.user_id
    assert audit_kwargs["action"] == "audit_events.list"
    assert audit_kwargs["resource_type"] == "audit_event"
    assert audit_kwargs["resource_id"] is None
    assert audit_kwargs["before_state"] is None

    after_state = audit_kwargs["after_state"]
    assert after_state["actor_id"] == str(actor_id)
    assert after_state["action"] == "project.create"
    assert after_state["resource_type"] == "project"
    assert after_state["resource_id"] == str(resource_id)
    assert after_state["page"] == 3
    assert after_state["per_page"] == 2
    assert after_state["total"] == 7
    assert "data" not in after_state
    assert "api_token" not in str(after_state)


@pytest.mark.asyncio
async def test_audit_events_list_masks_cross_tenant_matches_without_self_audit():
    from httpx import ASGITransport, AsyncClient

    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    tenant_id = uuid4()
    resource_id = uuid4()
    repos = MagicMock()
    repos.audit = MagicMock()
    repos.audit.list = AsyncMock(return_value=([], 0))
    repos.audit.has_cross_tenant_match = AsyncMock(return_value=True)
    repos.audit.create = AsyncMock()
    user = _audit_route_user(tenant_id=tenant_id)

    app = create_app(container=_container_without_redis())
    app.dependency_overrides[_get_repos] = lambda: repos
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/audit-events",
            params={
                "resource_type": "project",
                "resource_id": str(resource_id),
            },
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 404, resp.text
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Audit event not found",
            "details": [],
        }
    }
    repos.audit.list.assert_awaited_once_with(
        tenant_id=tenant_id,
        actor_id=None,
        action=None,
        resource_type="project",
        resource_id=resource_id,
        start_at=None,
        end_at=None,
        offset=0,
        limit=20,
    )
    repos.audit.has_cross_tenant_match.assert_awaited_once_with(
        tenant_id=tenant_id,
        actor_id=None,
        resource_type="project",
        resource_id=resource_id,
    )
    repos.audit.create.assert_not_awaited()


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"action": ""}, "Invalid audit action: empty"),
        ({"action": "x" * 201}, "Invalid audit action: too long"),
        ({"resource_type": ""}, "Invalid audit resource_type: empty"),
        ({"resource_type": "x" * 201}, "Invalid audit resource_type: too long"),
    ],
)
@pytest.mark.asyncio
async def test_audit_events_rejects_invalid_text_filters_without_repo_lookup(
    params,
    message,
):
    from httpx import ASGITransport, AsyncClient

    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    tenant_id = uuid4()
    repos = MagicMock()
    repos.audit = MagicMock()
    repos.audit.list = AsyncMock()
    repos.audit.has_cross_tenant_match = AsyncMock()
    repos.audit.create = AsyncMock()
    user = _audit_route_user(tenant_id=tenant_id)

    app = create_app(container=_container_without_redis())
    app.dependency_overrides[_get_repos] = lambda: repos
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/audit-events",
            params=params,
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": message,
            "details": [],
        }
    }
    repos.audit.list.assert_not_awaited()
    repos.audit.has_cross_tenant_match.assert_not_awaited()
    repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_events_rejects_reversed_time_range_without_repo_lookup():
    from httpx import ASGITransport, AsyncClient

    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    tenant_id = uuid4()
    repos = MagicMock()
    repos.audit = MagicMock()
    repos.audit.list = AsyncMock()
    repos.audit.has_cross_tenant_match = AsyncMock()
    repos.audit.create = AsyncMock()
    user = _audit_route_user(tenant_id=tenant_id)
    start_at = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    end_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    app = create_app(container=_container_without_redis())
    app.dependency_overrides[_get_repos] = lambda: repos
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/audit-events",
            params={
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
            },
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid audit time range: start_at must be before end_at",
            "details": [],
        }
    }
    repos.audit.list.assert_not_awaited()
    repos.audit.has_cross_tenant_match.assert_not_awaited()
    repos.audit.create.assert_not_awaited()


def test_audit_events_list_422_uses_error_response_schema():
    from qaplatform.main import create_app

    app = create_app(container=_container_without_redis())
    schema = app.openapi()["paths"]["/api/v1/audit-events"]["get"]["responses"][
        "422"
    ]["content"]["application/json"]["schema"]

    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
