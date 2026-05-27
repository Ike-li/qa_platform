"""Tests for the audit helper and integration with API write endpoints."""
from __future__ import annotations

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
    kwargs = repos.audit.create.call_args.kwargs
    assert kwargs["tenant_id"] == user.tenant_id
    assert kwargs["user_id"] == user.user_id
    assert kwargs["action"] == "project.create"
    assert kwargs["resource_type"] == "project"
    assert kwargs["resource_id"] == resource_id
    assert kwargs["before_state"] is None
    assert kwargs["after_state"] == {"name": "x", "value": 42}


@pytest.mark.asyncio
async def test_write_audit_serializes_pydantic_before_and_after():
    repos = _repos_with_audit()
    user = _user()
    before = _ResponseModel(name="old", value=1)
    after = _ResponseModel(name="new", value=2)

    await write_audit(
        repos, user,
        action="project.update",
        resource_type="project",
        resource_id=uuid4(),
        before=before,
        after=after,
    )

    kwargs = repos.audit.create.call_args.kwargs
    assert kwargs["before_state"] == {"name": "old", "value": 1}
    assert kwargs["after_state"] == {"name": "new", "value": 2}


@pytest.mark.asyncio
async def test_write_audit_swallows_repo_errors():
    repos = MagicMock()
    repos.audit = AsyncMock()
    repos.audit.create.side_effect = RuntimeError("audit table is down")

    # Must not raise — audit is best-effort, never blocks the main path.
    await write_audit(
        repos, _user(),
        action="anything",
        resource_type="x",
        resource_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_write_audit_handles_dict_states():
    repos = _repos_with_audit()
    user = _user()

    await write_audit(
        repos, user,
        action="env.update",
        resource_type="environment",
        resource_id=uuid4(),
        before={"a": 1},
        after={"a": 2},
    )

    kwargs = repos.audit.create.call_args.kwargs
    assert kwargs["before_state"] == {"a": 1}
    assert kwargs["after_state"] == {"a": 2}


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

    app = create_app(container=MagicMock())
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
    audit_recorder.assert_awaited_once()
    kwargs = audit_recorder.call_args.kwargs
    assert kwargs["action"] == "project.create"
    assert kwargs["resource_type"] == "project"
    assert kwargs["resource_id"] == project_orm.id
    assert kwargs["after"] is not None
