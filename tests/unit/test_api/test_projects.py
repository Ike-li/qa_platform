from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.engine.redact import redact_url_userinfo


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


def _make_orm_credential(project_id, tenant_id, type_="token"):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    obj.tenant_id = tenant_id
    obj.name = "git-credential"
    obj.type = type_
    return obj


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


_SENSITIVE_SETTINGS_RE = re.compile(
    r"(secret|token|password|passwd|pwd|credential|api[_-]?key|private[_-]?key|auth)",
    re.IGNORECASE,
)


def _expected_project_response(project) -> dict:
    settings = project.settings or {}
    # 对外响应省略 settings 里的敏感键（webhook_secret / token / password 等），
    # 与 api.v1.projects._public 的行为一致。
    settings = {
        key: value
        for key, value in settings.items()
        if not _SENSITIVE_SETTINGS_RE.search(key)
    }
    return {
        "id": str(project.id),
        "tenant_id": str(project.tenant_id),
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "git_url": project.git_url,
        "git_auth_method": project.git_auth_method,
        "credential_id": None if project.credential_id is None else str(project.credential_id),
        "default_branch": project.default_branch,
        "root_path": project.root_path,
        "shallow_clone": project.shallow_clone,
        "default_env_id": None if project.default_env_id is None else str(project.default_env_id),
        "settings": settings,
        "silent_windows": settings.get("silent_windows", []),
        "status": project.status,
        "created_by": str(project.created_by),
        "created_at": _json_datetime(project.created_at),
        "updated_at": _json_datetime(project.updated_at),
    }


def _expected_project_audit_state(project, *, git_url: str | None = None) -> dict:
    state = _expected_project_response(project)
    if git_url is not None:
        state["git_url"] = git_url
    # 审计从原始 settings 出发，而不是响应里已省略敏感键的那份：审计需要保留
    # 「这个键曾经存在」的信号，把它记成 {"redacted": true}，而对外响应是直接
    # 不返回该键。两者的脱敏目标不同，不能共用同一份数据。
    state["settings"] = _expected_project_settings_audit_state(project.settings or {})
    return state


def _expected_project_settings_audit_state(value):
    sensitive_parts = (
        "secret",
        "token",
        "password",
        "passwd",
        "pwd",
        "credential",
        "api_key",
        "api-key",
        "private_key",
        "private-key",
        "auth",
    )
    if isinstance(value, dict):
        return {
            key: {"redacted": True}
            if isinstance(key, str)
            and any(part in key.lower() for part in sensitive_parts)
            else _expected_project_settings_audit_state(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_expected_project_settings_audit_state(item) for item in value]
    if isinstance(value, str):
        return redact_url_userinfo(value)
    return value


_VALID_SILENT_WINDOW = {
    "start_at": "2026-06-01T09:00:00Z",
    "end_at": "2026-06-01T10:00:00Z",
    "reason": "freeze",
}
_TOO_MANY_SILENT_WINDOWS = [_VALID_SILENT_WINDOW] * 21


def _assert_project_not_found_response(resp):
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Project not found",
            "details": [],
        }
    }


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


@pytest.fixture
def mock_project_repo():
    return AsyncMock()


@pytest.fixture
def mock_repos(mock_project_repo):
    repos = MagicMock()
    repos.project = mock_project_repo
    repos.credential = AsyncMock()
    repos.audit = AsyncMock()
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
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    async def _override_session():
        session = AsyncMock()
        session.add = MagicMock()
        yield session

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_db_session] = _override_session
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _assert_422_error_response(openapi: dict, path: str, method: str) -> None:
    assert openapi["paths"][path][method]["responses"]["422"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}


@pytest.mark.asyncio
async def test_list_projects(client, mock_project_repo, tenant_id):
    project = _make_orm_project(
        tenant_id=tenant_id,
        created_by=uuid.UUID("20000000-0000-0000-0000-000000000001"),
        created_at=datetime(2026, 5, 31, 19, 20, 21, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 31, 22, 23, 24, tzinfo=timezone.utc),
    )
    mock_project_repo.list_filtered_by_tenant.return_value = ([project], 1)

    resp = await client.get("/api/v1/projects", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "data": [
            {
                "id": str(project.id),
                "tenant_id": str(tenant_id),
                "name": "test-project",
                "slug": "test-project",
                "description": "A test project",
                "git_url": "https://github.com/example/repo.git",
                "git_auth_method": "none",
                "credential_id": None,
                "default_branch": "main",
                "root_path": ".",
                "shallow_clone": True,
                "default_env_id": None,
                "settings": {},
                "silent_windows": [],
                "status": "active",
                "created_by": str(project.created_by),
                "created_at": project.created_at.isoformat().replace("+00:00", "Z"),
                "updated_at": project.updated_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 1,
        "per_page": 20,
        "total": 1,
    }
    mock_project_repo.list_filtered_by_tenant.assert_awaited_once()
    list_kwargs = mock_project_repo.list_filtered_by_tenant.await_args.kwargs
    assert list_kwargs["tenant_id"] == tenant_id
    assert list_kwargs["offset"] == 0
    assert list_kwargs["limit"] == 20
    assert list_kwargs["status"] is None
    assert list_kwargs["query"] is None


@pytest.mark.asyncio
async def test_list_projects_with_search(client, mock_project_repo, tenant_id):
    mock_project_repo.list_filtered_by_tenant.return_value = ([], 0)

    resp = await client.get(
        "/api/v1/projects?q=keyword&page=2&per_page=10",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"data": [], "page": 2, "per_page": 10, "total": 0}
    mock_project_repo.list_filtered_by_tenant.assert_awaited_once()
    list_kwargs = mock_project_repo.list_filtered_by_tenant.await_args.kwargs
    assert list_kwargs["tenant_id"] == tenant_id
    assert list_kwargs["offset"] == 10
    assert list_kwargs["limit"] == 10
    assert list_kwargs["status"] is None
    assert list_kwargs["query"] == "keyword"


@pytest.mark.asyncio
async def test_discover_git_branches(client, app, monkeypatch, mock_repos, mock_user):
    class FakeGitSource:
        def __init__(self, *, allowed_private_hosts):
            assert allowed_private_hosts == ["github.com"]

        async def list_branches(self, git_url):
            assert git_url == "https://github.com/example/repo.git"
            return ["main", "release"], "main"

    app.state.container.settings.git_allowed_private_hosts = ["github.com"]
    monkeypatch.setattr(
        "qaplatform.plugins.builtin.git_source.GitSource",
        FakeGitSource,
    )

    resp = await client.post(
        "/api/v1/projects/branches",
        json={"git_url": "https://github.com/example/repo.git"},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"branches": ["main", "release"], "default_branch": "main"}
    mock_repos.audit.create.assert_awaited_once_with(
        tenant_id=mock_user.tenant_id,
        user_id=mock_user.user_id,
        action="project.branches_discover",
        resource_type="project",
        resource_id=None,
        before_state=None,
        after_state={
            "git_url": "https://github.com/example/repo.git",
            "branch_count": 2,
            "default_branch": "main",
        },
    )


@pytest.mark.asyncio
async def test_discover_git_branches_rejects_private_auth(client):
    resp = await client.post(
        "/api/v1/projects/branches",
        json={
            "git_url": "https://github.com/example/repo.git",
            "git_auth_method": "token",
        },
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Branch discovery currently supports public repositories only",
            "details": [],
        }
    }


@pytest.mark.asyncio
async def test_list_projects_filters_by_status(client, mock_project_repo, tenant_id):
    mock_project_repo.list_filtered_by_tenant.return_value = ([], 0)

    resp = await client.get(
        "/api/v1/projects?status=archived",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    mock_project_repo.list_filtered_by_tenant.assert_awaited_once()
    list_kwargs = mock_project_repo.list_filtered_by_tenant.await_args.kwargs
    assert list_kwargs["tenant_id"] == tenant_id
    assert list_kwargs["status"] == "archived"
    assert list_kwargs["query"] is None


@pytest.mark.asyncio
async def test_list_projects_rejects_unknown_status_without_querying_projects(
    client,
    mock_project_repo,
):
    resp = await client.get(
        "/api/v1/projects?status=deleted",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid project status: deleted",
            "details": [],
        }
    }
    mock_project_repo.list_filtered_by_tenant.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_projects_rejects_empty_status_without_querying_projects(
    client,
    mock_project_repo,
):
    resp = await client.get(
        "/api/v1/projects?status=",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid project status: empty",
            "details": [],
        }
    }
    mock_project_repo.list_filtered_by_tenant.assert_not_awaited()


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("q=", "Invalid project search query: empty"),
        ("q=%20%20%20", "Invalid project search query: empty"),
        (f"q={'x' * 501}", "Invalid project search query: too long"),
    ],
)
@pytest.mark.asyncio
async def test_list_projects_rejects_invalid_search_without_querying_projects(
    client,
    mock_project_repo,
    query,
    message,
):
    resp = await client.get(
        f"/api/v1/projects?{query}",
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
    mock_project_repo.list_filtered_by_tenant.assert_not_awaited()


def test_list_projects_status_filter_422_uses_error_response_schema(app):
    responses = app.openapi()["paths"]["/api/v1/projects"]["get"]["responses"]
    schema = responses["422"]["content"]["application/json"]["schema"]

    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_list_projects_status_filter_is_openapi_enum(app):
    params = app.openapi()["paths"]["/api/v1/projects"]["get"]["parameters"]
    status_schema = next(p["schema"] for p in params if p["name"] == "status")

    assert status_schema["enum"] == ["active", "archived"]


@pytest.mark.asyncio
async def test_create_project(client, mock_project_repo, mock_repos, mock_user, tenant_id):
    git_url = "https://x-access-token:secret-token@github.com/example/repo.git"
    project = _make_orm_project(
        tenant_id=tenant_id,
        git_url=git_url,
        created_by=mock_user.user_id,
        created_at=datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 31, 21, 22, 23, tzinfo=timezone.utc),
    )
    mock_project_repo.get_by_slug.return_value = None
    mock_project_repo.create.return_value = project

    resp = await client.post(
        "/api/v1/projects",
        json={"name": "test-project", "slug": "test-project", "git_url": git_url},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body == _expected_project_response(project)
    assert "secret-token" in body["git_url"]
    mock_project_repo.get_by_slug.assert_awaited_once_with(tenant_id, "test-project")
    assert mock_project_repo.create.await_args.kwargs == {
        "tenant_id": tenant_id,
        "created_by": mock_user.user_id,
        "name": "test-project",
        "slug": "test-project",
        "description": None,
        "git_url": git_url,
        "git_auth_method": "none",
        "credential_id": None,
        "default_branch": "main",
        "root_path": ".",
        "shallow_clone": True,
        "default_env_id": None,
        "settings": {},
    }

    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "project.create",
        "resource_type": "project",
        "resource_id": project.id,
        "before_state": None,
        "after_state": _expected_project_audit_state(
            project,
            git_url="https://***@github.com/example/repo.git",
        ),
    }
    assert "secret-token" not in repr(audit_kwargs)


@pytest.mark.asyncio
async def test_create_project_duplicate_slug(client, mock_project_repo, mock_repos, tenant_id):
    mock_project_repo.get_by_slug.return_value = _make_orm_project(
        tenant_id=tenant_id,
        slug="dup-slug",
    )

    resp = await client.post(
        "/api/v1/projects",
        json={"name": "dup", "slug": "dup-slug", "git_url": "https://github.com/example/repo.git"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Slug already exists"}
    mock_project_repo.get_by_slug.assert_awaited_once_with(tenant_id, "dup-slug")
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_project_repo.create.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_project_rejects_credential_before_project_exists(
    client,
    mock_project_repo,
    mock_repos,
):
    mock_project_repo.get_by_slug.return_value = None

    resp = await client.post(
        "/api/v1/projects",
        json={
            "name": "private",
            "slug": "private",
            "git_url": "https://github.com/example/repo.git",
            "git_auth_method": "token",
            "credential_id": str(uuid.uuid4()),
        },
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Create the project before binding a project credential",
            "details": [],
        }
    }
    mock_project_repo.create.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


def test_project_git_binding_business_validation_responses_are_documented(app):
    openapi = app.openapi()

    _assert_422_error_response(openapi, "/api/v1/projects", "post")
    _assert_422_error_response(openapi, "/api/v1/projects/{project_id}", "put")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "bad_value", "expected_type", "expected_msg"),
    [
        ("name", "", "string_too_short", "String should have at least 1 character"),
        ("slug", "", "string_too_short", "String should have at least 1 character"),
        (
            "slug",
            "Bad Slug",
            "string_pattern_mismatch",
            "String should match pattern '^[a-z0-9-]+$'",
        ),
        ("git_url", "", "string_too_short", "String should have at least 1 character"),
        (
            "default_branch",
            "",
            "string_too_short",
            "String should have at least 1 character",
        ),
        (
            "root_path",
            "",
            "string_too_short",
            "String should have at least 1 character",
        ),
        ("name", "   ", "value_error", "Value error, project name must not be blank"),
        (
            "git_url",
            "   ",
            "value_error",
            "Value error, project git_url must not be blank",
        ),
        (
            "default_branch",
            "   ",
            "value_error",
            "Value error, project default_branch must not be blank",
        ),
        (
            "root_path",
            "   ",
            "value_error",
            "Value error, project root_path must not be blank",
        ),
    ],
)
async def test_create_project_rejects_invalid_core_fields_without_side_effects(
    client,
    mock_project_repo,
    mock_repos,
    field,
    bad_value,
    expected_type,
    expected_msg,
):
    body = {
        "name": "test-project",
        "slug": "test-project",
        "git_url": "https://github.com/example/repo.git",
        field: bad_value,
    }

    resp = await client.post(
        "/api/v1/projects",
        json=body,
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": expected_type,
            "loc": ["body", field],
            "msg": expected_msg,
            "input": bad_value,
        }
    ]
    mock_project_repo.get_by_slug.assert_not_awaited()
    mock_project_repo.create.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "expected_type", "expected_msg"),
    [
        ("name", "", "string_too_short", "String should have at least 1 character"),
        ("git_url", "", "string_too_short", "String should have at least 1 character"),
        (
            "default_branch",
            "",
            "string_too_short",
            "String should have at least 1 character",
        ),
        (
            "root_path",
            "",
            "string_too_short",
            "String should have at least 1 character",
        ),
        ("name", "   ", "value_error", "Value error, project name must not be blank"),
        (
            "git_url",
            "   ",
            "value_error",
            "Value error, project git_url must not be blank",
        ),
        (
            "default_branch",
            "   ",
            "value_error",
            "Value error, project default_branch must not be blank",
        ),
        (
            "root_path",
            "   ",
            "value_error",
            "Value error, project root_path must not be blank",
        ),
    ],
)
async def test_update_project_rejects_empty_core_fields_without_side_effects(
    client,
    mock_project_repo,
    mock_repos,
    field,
    value,
    expected_type,
    expected_msg,
):
    resp = await client.put(
        f"/api/v1/projects/{uuid.uuid4()}",
        json={field: value},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": expected_type,
            "loc": ["body", field],
            "msg": expected_msg,
            "input": value,
        }
    ]
    mock_project_repo.get_for_tenant.assert_not_awaited()
    mock_project_repo.update.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings", "expected_error"),
    [
        (
            {"allowed_branches": "main"},
            "settings.allowed_branches must be a list of strings",
        ),
        ({"allowed_branches": [""]}, "settings.allowed_branches entries must be non-empty"),
        ({"allowed_branches": [123]}, "settings.allowed_branches entries must be strings"),
        (
            {"allowed_branches": ["main"] * 51},
            "settings.allowed_branches must contain at most 50 entries",
        ),
        (
            {"allowed_branches": ["x" * 201]},
            "settings.allowed_branches entries must be at most 200 characters",
        ),
    ],
)
async def test_create_project_rejects_invalid_allowed_branches(
    client,
    mock_project_repo,
    mock_repos,
    settings,
    expected_error,
):
    resp = await client.post(
        "/api/v1/projects",
        json={
            "name": "test-project",
            "slug": "test-project",
            "git_url": "https://github.com/example/repo.git",
            "settings": settings,
        },
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": "value_error",
            "loc": ["body", "settings"],
            "msg": f"Value error, {expected_error}",
            "input": settings,
        }
    ]
    mock_project_repo.create.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


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
    operations = []

    class _RecordingSession:
        def add(self, instance):
            captured_added.append(instance)
            operations.append(("add", instance))

        async def flush(self):
            operations.append(("flush", None))

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
        assert resp.json() == _expected_project_response(project)

        member = captured_added[0]
        assert captured_added == [member]
        assert isinstance(member, ProjectMemberORM)
        assert operations == [("add", member), ("flush", None)]
        assert member.role == "admin"
        assert member.user_id == mock_user.user_id
        assert member.project_id == project.id
        assert member.tenant_id == tenant_id
        assert member.deleted_at is None
    finally:
        app.dependency_overrides.pop(_get_db_session, None)


@pytest.mark.asyncio
async def test_get_project(client, mock_project_repo, tenant_id):
    project = _make_orm_project(
        tenant_id=tenant_id,
        created_at=datetime(2026, 5, 31, 22, 23, 24, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 31, 23, 24, 25, tzinfo=timezone.utc),
    )
    mock_project_repo.get_for_tenant.return_value = project

    resp = await client.get(f"/api/v1/projects/{project.id}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    assert resp.json() == _expected_project_response(project)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)


@pytest.mark.asyncio
async def test_get_project_not_found(client, mock_project_repo, tenant_id):
    mock_project_repo.get_for_tenant.return_value = None
    project_id = uuid.uuid4()

    resp = await client.get(
        f"/api/v1/projects/{project_id}",
        headers={"Authorization": "Bearer fake"},
    )
    _assert_project_not_found_response(resp)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)


@pytest.mark.asyncio
async def test_update_project(client, mock_project_repo, mock_repos, mock_user, tenant_id):
    project = _make_orm_project(
        tenant_id=tenant_id,
        created_by=mock_user.user_id,
        created_at=datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 31, 21, 22, 23, tzinfo=timezone.utc),
    )
    updated = _make_orm_project(
        id=project.id,
        tenant_id=tenant_id,
        name="updated-name",
        slug=project.slug,
        description=project.description,
        git_url=project.git_url,
        git_auth_method=project.git_auth_method,
        credential_id=project.credential_id,
        default_branch=project.default_branch,
        root_path=project.root_path,
        shallow_clone=project.shallow_clone,
        default_env_id=project.default_env_id,
        settings=project.settings,
        status=project.status,
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=datetime(2026, 5, 31, 23, 24, 25, tzinfo=timezone.utc),
    )
    mock_project_repo.get_for_tenant.return_value = project
    mock_project_repo.update.return_value = updated

    resp = await client.put(
        f"/api/v1/projects/{project.id}",
        json={"name": "updated-name"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json() == _expected_project_response(updated)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_project_repo.update.assert_awaited_once_with(project, name="updated-name")
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "project.update",
        "resource_type": "project",
        "resource_id": project.id,
        "before_state": _expected_project_audit_state(project),
        "after_state": _expected_project_audit_state(updated),
    }


@pytest.mark.asyncio
async def test_update_project_validates_git_credential_binding(
    client,
    mock_repos,
    mock_project_repo,
    mock_user,
    tenant_id,
):
    project = _make_orm_project(tenant_id=tenant_id)
    credential = _make_orm_credential(project.id, tenant_id, type_="token")
    updated = _make_orm_project(
        id=project.id,
        tenant_id=tenant_id,
        git_auth_method="token",
        credential_id=credential.id,
    )
    mock_project_repo.get_for_tenant.return_value = project
    mock_repos.credential.get_by_project_tenant.return_value = credential
    mock_project_repo.update.return_value = updated

    resp = await client.put(
        f"/api/v1/projects/{project.id}",
        json={"git_auth_method": "token", "credential_id": str(credential.id)},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == _expected_project_response(updated)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        credential.id,
        project.id,
        tenant_id,
    )
    mock_project_repo.update.assert_awaited_once_with(
        project,
        git_auth_method="token",
        credential_id=credential.id,
    )
    mock_repos.audit.create.assert_awaited_once()
    assert mock_repos.audit.create.await_args.kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "project.update",
        "resource_type": "project",
        "resource_id": project.id,
        "before_state": _expected_project_audit_state(project),
        "after_state": _expected_project_audit_state(updated),
    }


@pytest.mark.asyncio
async def test_update_project_rejects_git_credential_type_mismatch(
    client, mock_repos, mock_project_repo, tenant_id
):
    project = _make_orm_project(tenant_id=tenant_id)
    credential = _make_orm_credential(project.id, tenant_id, type_="ssh_key")
    mock_project_repo.get_for_tenant.return_value = project
    mock_repos.credential.get_by_project_tenant.return_value = credential

    resp = await client.put(
        f"/api/v1/projects/{project.id}",
        json={"git_auth_method": "token", "credential_id": str(credential.id)},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Credential type must be token for git_auth_method=token",
            "details": [],
        }
    }
    mock_project_repo.update.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_project_rejects_token_auth_for_ssh_url(client, mock_project_repo, tenant_id):
    project = _make_orm_project(
        tenant_id=tenant_id,
        git_url="git@github.com:example/repo.git",
    )
    mock_project_repo.get_for_tenant.return_value = project

    resp = await client.put(
        f"/api/v1/projects/{project.id}",
        json={"git_auth_method": "token"},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Token Git credentials require an https:// git_url",
            "details": [],
        }
    }
    mock_project_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_project_not_found(
    client, mock_project_repo, mock_repos, tenant_id
):
    mock_project_repo.get_for_tenant.return_value = None
    project_id = uuid.uuid4()

    resp = await client.put(
        f"/api/v1/projects/{project_id}",
        json={"name": "x"},
        headers={"Authorization": "Bearer fake"},
    )
    _assert_project_not_found_response(resp)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_project_repo.update.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings", "expected_error"),
    [
        (
            {"allowed_branches": "main"},
            "settings.allowed_branches must be a list of strings",
        ),
        ({"allowed_branches": [""]}, "settings.allowed_branches entries must be non-empty"),
        ({"allowed_branches": [123]}, "settings.allowed_branches entries must be strings"),
        (
            {"allowed_branches": ["main"] * 51},
            "settings.allowed_branches must contain at most 50 entries",
        ),
        (
            {"allowed_branches": ["x" * 201]},
            "settings.allowed_branches entries must be at most 200 characters",
        ),
    ],
)
async def test_update_project_rejects_invalid_allowed_branches(
    client,
    mock_project_repo,
    mock_repos,
    settings,
    expected_error,
):
    resp = await client.put(
        f"/api/v1/projects/{uuid.uuid4()}",
        json={"settings": settings},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": "value_error",
            "loc": ["body", "settings"],
            "msg": f"Value error, {expected_error}",
            "input": settings,
        }
    ]
    mock_project_repo.get_for_tenant.assert_not_awaited()
    mock_project_repo.update.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        (
            {
                "silent_windows": [
                    {
                        "start_at": "2026-06-01T09:00:00",
                        "end_at": "2026-06-01T10:00:00Z",
                        "reason": "freeze",
                    }
                ],
            },
            {
                "type": "value_error",
                "loc": ["body", "silent_windows", 0, "start_at"],
                "msg": "Value error, datetime must be timezone-aware",
                "input": "2026-06-01T09:00:00",
            },
        ),
        (
            {
                "silent_windows": [
                    {
                        "start_at": "2026-06-01T10:00:00Z",
                        "end_at": "2026-06-01T09:00:00Z",
                        "reason": "freeze",
                    }
                ],
            },
            {
                "type": "value_error",
                "loc": ["body", "silent_windows", 0],
                "msg": "Value error, end_at must be greater than start_at",
                "input": {
                    "start_at": "2026-06-01T10:00:00Z",
                    "end_at": "2026-06-01T09:00:00Z",
                    "reason": "freeze",
                },
            },
        ),
        (
            {"silent_windows": _TOO_MANY_SILENT_WINDOWS},
            {
                "type": "too_long",
                "loc": ["body", "silent_windows"],
                "msg": "List should have at most 20 items after validation, not 21",
                "input": _TOO_MANY_SILENT_WINDOWS,
            },
        ),
        (
            {"settings": {"silent_windows": "nope"}},
            {
                "type": "value_error",
                "loc": ["body", "settings"],
                "msg": "Value error, settings.silent_windows must be a list",
                "input": {"silent_windows": "nope"},
            },
        ),
        (
            {
                "settings": {
                    "silent_windows": [
                        {
                            "start_at": "2026-06-01T09:00:00",
                            "end_at": "2026-06-01T10:00:00Z",
                            "reason": "freeze",
                        }
                    ]
                }
            },
            {
                "type": "value_error",
                "loc": ["body", "settings", "start_at"],
                "msg": "Value error, datetime must be timezone-aware",
                "input": "2026-06-01T09:00:00",
            },
        ),
    ],
)
async def test_update_project_rejects_invalid_silent_windows(
    client,
    mock_project_repo,
    mock_repos,
    payload,
    expected_error,
):
    resp = await client.put(
        f"/api/v1/projects/{uuid.uuid4()}",
        json=payload,
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [expected_error]
    mock_project_repo.get_for_tenant.assert_not_awaited()
    mock_project_repo.update.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_project_serializes_silent_windows_into_settings(
    client,
    mock_project_repo,
    mock_repos,
    mock_user,
    tenant_id,
):
    created_at = datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc)
    updated_at = datetime(2026, 5, 31, 21, 22, 23, tzinfo=timezone.utc)
    project = _make_orm_project(
        tenant_id=tenant_id,
        settings={
            "allowed_branches": ["main"],
            "webhook_secret": "project-webhook-secret",
        },
        created_at=created_at,
        updated_at=updated_at,
    )
    before_state = _expected_project_audit_state(project)
    mock_project_repo.get_for_tenant.return_value = project

    async def _update(instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        instance.updated_at = datetime(2026, 5, 31, 22, 23, 24, tzinfo=timezone.utc)
        return instance

    mock_project_repo.update.side_effect = _update
    expected_silent_windows = [
        {
            "start_at": "2026-06-01T09:00:00+08:00",
            "end_at": "2026-06-01T10:00:00+08:00",
            "reason": "Release freeze",
        }
    ]
    expected_settings = {
        "allowed_branches": ["main"],
        "webhook_secret": "project-webhook-secret",
        "silent_windows": expected_silent_windows,
    }

    resp = await client.put(
        f"/api/v1/projects/{project.id}",
        json={"silent_windows": expected_silent_windows},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    assert resp.json() == _expected_project_response(project)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_project_repo.update.assert_awaited_once_with(
        project,
        settings=expected_settings,
    )
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "project.update",
        "resource_type": "project",
        "resource_id": project.id,
        "before_state": before_state,
        "after_state": _expected_project_audit_state(project),
    }
    assert audit_kwargs["before_state"]["settings"]["webhook_secret"] == {
        "redacted": True
    }
    assert audit_kwargs["after_state"]["settings"]["webhook_secret"] == {
        "redacted": True
    }
    assert "project-webhook-secret" not in repr(
        [audit_kwargs["before_state"], audit_kwargs["after_state"]]
    )


@pytest.mark.asyncio
async def test_delete_project(client, mock_project_repo, mock_repos, mock_user, tenant_id):
    project = _make_orm_project(
        tenant_id=tenant_id,
        created_by=mock_user.user_id,
        created_at=datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 31, 21, 22, 23, tzinfo=timezone.utc),
    )
    mock_project_repo.get_for_tenant.return_value = project

    resp = await client.delete(f"/api/v1/projects/{project.id}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 204
    assert resp.content == b""
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_project_repo.delete.assert_awaited_once_with(project)
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "project.delete",
        "resource_type": "project",
        "resource_id": project.id,
        "before_state": _expected_project_audit_state(project),
        "after_state": None,
    }


@pytest.mark.asyncio
async def test_delete_project_not_found(
    client, mock_project_repo, mock_repos, tenant_id
):
    mock_project_repo.get_for_tenant.return_value = None
    project_id = uuid.uuid4()

    resp = await client.delete(
        f"/api/v1/projects/{project_id}",
        headers={"Authorization": "Bearer fake"},
    )
    _assert_project_not_found_response(resp)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_project_repo.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unauthenticated(app, mock_project_repo):
    from qaplatform.api.deps import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/projects")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Missing Authorization header"}
    mock_project_repo.list_filtered_by_tenant.assert_not_awaited()
