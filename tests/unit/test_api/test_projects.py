from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_project(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="test-project",
        slug="test-project",
        description="A test project",
        git_url="https://github.com/example/repo.git",
        git_auth_method="none",
        credential_id=None,
        default_branch="main",
        root_path=".",
        shallow_clone=True,
        default_env_id=None,
        settings={},
        status="active",
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest.fixture
def mock_project_repo():
    return AsyncMock()


@pytest.fixture
def mock_repos(mock_project_repo):
    repos = MagicMock()
    repos.project = mock_project_repo
    return repos


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = str(uuid.uuid4())
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    return user


@pytest.fixture
async def app(mock_repos, mock_user):
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


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_projects(client, mock_project_repo, tenant_id):
    project = _make_orm_project(tenant_id=tenant_id)
    mock_project_repo.list.return_value = ([project], 1)

    resp = await client.get("/api/v1/projects", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["slug"] == "test-project"


@pytest.mark.asyncio
async def test_list_projects_with_search(client, mock_project_repo):
    mock_project_repo.list.return_value = ([], 0)

    resp = await client.get(
        "/api/v1/projects?q=keyword&page=2&per_page=10",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    mock_project_repo.list.assert_called_once()


@pytest.mark.asyncio
async def test_create_project(client, mock_project_repo, tenant_id):
    project = _make_orm_project(tenant_id=tenant_id)
    mock_project_repo.get_by_slug.return_value = None
    mock_project_repo.create.return_value = project

    resp = await client.post(
        "/api/v1/projects",
        json={"name": "test-project", "slug": "test-project", "git_url": "https://github.com/example/repo.git"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "test-project"


@pytest.mark.asyncio
async def test_create_project_duplicate_slug(client, mock_project_repo):
    mock_project_repo.get_by_slug.return_value = _make_orm_project()

    resp = await client.post(
        "/api/v1/projects",
        json={"name": "dup", "slug": "dup-slug", "git_url": "https://github.com/example/repo.git"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_project_adds_creator_as_project_admin(
    app, mock_project_repo, tenant_id, mock_user
):
    """Regression test for P0-2: a tenant Member who creates a project must
    be auto-added as ProjectMember(role=admin); otherwise they 403 on every
    subsequent project-scoped action.
    """
    from qaplatform.api.deps import _get_db_session
    from qaplatform.infra.database.models import ProjectMember as ProjectMemberORM

    project = _make_orm_project(tenant_id=tenant_id)
    mock_project_repo.get_by_slug.return_value = None
    mock_project_repo.create.return_value = project

    captured_added = []

    class _RecordingSession:
        def add(self, instance):
            captured_added.append(instance)

        async def flush(self):
            pass

    async def _override_session():
        yield _RecordingSession()

    app.dependency_overrides[_get_db_session] = _override_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/projects",
                json={"name": "p", "slug": "p", "git_url": "https://example.com/x.git"},
                headers={"Authorization": "Bearer fake"},
            )
        assert resp.status_code == 201

        members = [x for x in captured_added if isinstance(x, ProjectMemberORM)]
        assert len(members) == 1, f"expected exactly one ProjectMember added, got: {captured_added}"
        m = members[0]
        assert str(m.role) == "admin"
        assert m.user_id == mock_user.user_id
        assert m.project_id == project.id
        assert m.tenant_id == tenant_id
    finally:
        app.dependency_overrides.pop(_get_db_session, None)


@pytest.mark.asyncio
async def test_get_project(client, mock_project_repo, tenant_id):
    project = _make_orm_project(tenant_id=tenant_id)
    mock_project_repo.get_by_id.return_value = project

    resp = await client.get(f"/api/v1/projects/{project.id}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(project.id)


@pytest.mark.asyncio
async def test_get_project_not_found(client, mock_project_repo):
    mock_project_repo.get_by_id.return_value = None

    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_project(client, mock_project_repo, tenant_id):
    project = _make_orm_project(tenant_id=tenant_id)
    updated = _make_orm_project(name="updated-name", tenant_id=tenant_id)
    mock_project_repo.get_by_id.return_value = project
    mock_project_repo.update.return_value = updated

    resp = await client.put(
        f"/api/v1/projects/{project.id}",
        json={"name": "updated-name"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated-name"


@pytest.mark.asyncio
async def test_update_project_not_found(client, mock_project_repo):
    mock_project_repo.get_by_id.return_value = None

    resp = await client.put(
        f"/api/v1/projects/{uuid.uuid4()}",
        json={"name": "x"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_project(client, mock_project_repo, tenant_id):
    project = _make_orm_project(tenant_id=tenant_id)
    mock_project_repo.get_by_id.return_value = project

    resp = await client.delete(f"/api/v1/projects/{project.id}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_project_not_found(client, mock_project_repo):
    mock_project_repo.get_by_id.return_value = None

    resp = await client.delete(f"/api/v1/projects/{uuid.uuid4()}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated(app):
    from qaplatform.api.deps import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/projects")
    assert resp.status_code == 401
