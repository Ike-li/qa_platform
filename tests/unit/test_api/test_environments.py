from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from qaplatform.api.schemas import EnvironmentCreate, EnvironmentUpdate
from qaplatform.dependencies import CryptoService
from qaplatform.domain.services.env_vars_crypto import decrypt_env_vars, encrypt_env_vars


def _make_orm_project(tenant_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.tenant_id = tenant_id
    return obj


def _make_orm_environment(project_id, *, env_id=None, env_vars=None):
    obj = MagicMock()
    obj.id = env_id or uuid.uuid4()
    obj.project_id = project_id
    obj.name = "default"
    obj.base_image = "python:3.12.1"
    obj.setup_script = None
    obj.memory_mb = 512
    obj.cpu_cores = 1.0
    obj.resource_limits = {
        "disk_mb": 1024,
        "max_artifact_size_mb": 100,
        "max_artifacts_count": 50,
    }
    obj.network_policy = "deny"
    obj.env_vars = env_vars or {}
    obj.cache_key = None
    obj.created_at = datetime.now(timezone.utc)
    return obj


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def crypto():
    return CryptoService({0: b"\x00" * 32})


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    user.is_platform_admin = False
    return user


@pytest.fixture
def project(tenant_id):
    return _make_orm_project(tenant_id)


@pytest.fixture
def mock_repos(project):
    repos = MagicMock()
    repos.project = AsyncMock()
    repos.project.get_for_tenant.return_value = project
    repos.environment = AsyncMock()
    repos.audit = AsyncMock()
    return repos


@pytest.fixture
def app(mock_repos, mock_user, crypto):
    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    app = create_app(container=MagicMock())
    container_mock = MagicMock()
    container_mock.crypto_service = crypto
    app.state.container = container_mock

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


def _assert_503_error_response(openapi: dict, path: str, method: str) -> None:
    assert openapi["paths"][path][method]["responses"]["503"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}


def _assert_not_found_response(body: dict, message: str) -> None:
    assert body == {
        "error": {
            "code": "NOT_FOUND",
            "message": message,
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


@pytest.mark.parametrize(
    ("base_image", "expected_msg"),
    [
        ("python", "Image must use format 'registry/name:tag'"),
        ("python:latest", "Tag ':latest' is not allowed; pin a specific version"),
        ("python:stable", "Tag ':stable' is not allowed; pin a specific version"),
        ("python:edge", "Tag ':edge' is not allowed; pin a specific version"),
    ],
)
def test_environment_schema_rejects_unpinned_or_moving_base_images(
    base_image,
    expected_msg,
):
    with pytest.raises(ValidationError) as create_exc:
        EnvironmentCreate(name="default", base_image=base_image)

    expected_error = {
        "type": "value_error",
        "loc": ("base_image",),
        "msg": f"Value error, {expected_msg}",
        "input": base_image,
    }
    assert _validation_error_projection(create_exc.value.errors()) == [expected_error]

    with pytest.raises(ValidationError) as update_exc:
        EnvironmentUpdate(base_image=base_image)

    assert _validation_error_projection(update_exc.value.errors()) == [expected_error]


def test_environment_schema_accepts_pinned_base_image():
    created = EnvironmentCreate(name="default", base_image="python:3.12.1")
    updated = EnvironmentUpdate(base_image="python:3.12-alpine")

    assert created.base_image == "python:3.12.1"
    assert updated.base_image == "python:3.12-alpine"


@pytest.mark.parametrize(
    ("field_name", "payload"),
    [
        ("name", {"name": ""}),
        ("cache_key", {"cache_key": ""}),
    ],
)
def test_environment_schema_rejects_empty_name_or_cache_key(field_name, payload):
    create_payload = {
        "name": "default",
        "base_image": "python:3.12.1",
        **payload,
    }
    with pytest.raises(ValidationError) as create_exc:
        EnvironmentCreate(**create_payload)

    expected_error = {
        "type": "string_too_short",
        "loc": (field_name,),
        "msg": "String should have at least 1 character",
        "input": payload[field_name],
    }
    assert _validation_error_projection(create_exc.value.errors()) == [expected_error]

    with pytest.raises(ValidationError) as update_exc:
        EnvironmentUpdate(**payload)

    assert _validation_error_projection(update_exc.value.errors()) == [expected_error]


@pytest.mark.parametrize(
    ("field_name", "payload", "expected_msg"),
    [
        ("name", {"name": "   "}, "environment name must not be blank"),
        ("cache_key", {"cache_key": "   "}, "environment cache_key must not be blank"),
    ],
)
def test_environment_schema_rejects_blank_name_or_cache_key(
    field_name,
    payload,
    expected_msg,
):
    create_payload = {
        "name": "default",
        "base_image": "python:3.12.1",
        **payload,
    }
    with pytest.raises(ValidationError) as create_exc:
        EnvironmentCreate(**create_payload)

    expected_error = {
        "type": "value_error",
        "loc": (field_name,),
        "msg": f"Value error, {expected_msg}",
        "input": payload[field_name],
    }
    assert _validation_error_projection(create_exc.value.errors()) == [expected_error]

    with pytest.raises(ValidationError) as update_exc:
        EnvironmentUpdate(**payload)

    assert _validation_error_projection(update_exc.value.errors()) == [expected_error]


@pytest.mark.parametrize(
    ("field_name", "bad_value", "expected_type", "expected_msg"),
    [
        ("memory_mb", 0, "greater_than_equal", "Input should be greater than or equal to 1"),
        ("cpu_cores", 0, "greater_than", "Input should be greater than 0"),
        (
            "max_artifact_size_mb",
            0,
            "greater_than_equal",
            "Input should be greater than or equal to 1",
        ),
        (
            "max_artifacts_count",
            0,
            "greater_than_equal",
            "Input should be greater than or equal to 1",
        ),
    ],
)
def test_environment_schema_rejects_non_positive_resource_limits(
    field_name,
    bad_value,
    expected_type,
    expected_msg,
):
    with pytest.raises(ValidationError) as create_exc:
        EnvironmentCreate(
            name="default",
            base_image="python:3.12.1",
            **{field_name: bad_value},
        )

    expected_error = {
        "type": expected_type,
        "loc": (field_name,),
        "msg": expected_msg,
        "input": bad_value,
    }
    assert _validation_error_projection(create_exc.value.errors()) == [expected_error]

    with pytest.raises(ValidationError) as update_exc:
        EnvironmentUpdate(**{field_name: bad_value})

    assert _validation_error_projection(update_exc.value.errors()) == [expected_error]


@pytest.mark.asyncio
async def test_list_environments_uses_pagination_and_decrypts_items(
    app,
    project,
    crypto,
    mock_repos,
):
    env = _make_orm_environment(project.id)
    env.name = "ci"
    env.base_image = "python:3.12.1"
    env.memory_mb = 2048
    env.cpu_cores = 2.5
    env.resource_limits = {
        "disk_mb": 4096,
        "max_artifact_size_mb": 512,
        "max_artifacts_count": 20,
    }
    env.network_policy = "restricted"
    env.env_vars = encrypt_env_vars(
        {"API_TOKEN": "list-secret"},
        environment_id=env.id,
        crypto=crypto,
    )
    env.cache_key = "ci-py312"
    env.created_at = datetime(2026, 5, 31, 16, 17, 18, tzinfo=timezone.utc)
    mock_repos.environment.list_by_project.return_value = ([env], 11)

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/environments?page=3&per_page=5",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "data": [
            {
                "id": str(env.id),
                "project_id": str(project.id),
                "name": "ci",
                "base_image": "python:3.12.1",
                "setup_script": None,
                "memory_mb": 2048,
                "cpu_cores": 2.5,
                "disk_mb": 4096,
                "max_artifact_size_mb": 512,
                "max_artifacts_count": 20,
                "network_policy": "restricted",
                "env_vars": {"API_TOKEN": "list-secret"},
                "cache_key": "ci-py312",
                "created_at": env.created_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 3,
        "per_page": 5,
        "total": 11,
    }
    mock_repos.environment.list_by_project.assert_awaited_once_with(
        project.id,
        offset=10,
        limit=5,
    )
    mock_repos.audit.create.assert_not_awaited()
    mock_repos.audit.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_environment_routes_reject_empty_name_or_cache_key_without_side_effects(
    app,
    project,
    mock_repos,
):
    env_id = uuid.uuid4()
    cases = [
        (
            "post",
            f"/api/v1/projects/{project.id}/environments",
            {"name": "", "base_image": "python:3.12.1"},
            "name",
            "string_too_short",
            "String should have at least 1 character",
        ),
        (
            "post",
            f"/api/v1/projects/{project.id}/environments",
            {"name": "   ", "base_image": "python:3.12.1"},
            "name",
            "value_error",
            "Value error, environment name must not be blank",
        ),
        (
            "post",
            f"/api/v1/projects/{project.id}/environments",
            {
                "name": "default",
                "base_image": "python:3.12.1",
                "cache_key": "",
            },
            "cache_key",
            "string_too_short",
            "String should have at least 1 character",
        ),
        (
            "post",
            f"/api/v1/projects/{project.id}/environments",
            {
                "name": "default",
                "base_image": "python:3.12.1",
                "cache_key": "   ",
            },
            "cache_key",
            "value_error",
            "Value error, environment cache_key must not be blank",
        ),
        (
            "put",
            f"/api/v1/projects/{project.id}/environments/{env_id}",
            {"name": ""},
            "name",
            "string_too_short",
            "String should have at least 1 character",
        ),
        (
            "put",
            f"/api/v1/projects/{project.id}/environments/{env_id}",
            {"name": "   "},
            "name",
            "value_error",
            "Value error, environment name must not be blank",
        ),
        (
            "put",
            f"/api/v1/projects/{project.id}/environments/{env_id}",
            {"cache_key": ""},
            "cache_key",
            "string_too_short",
            "String should have at least 1 character",
        ),
        (
            "put",
            f"/api/v1/projects/{project.id}/environments/{env_id}",
            {"cache_key": "   "},
            "cache_key",
            "value_error",
            "Value error, environment cache_key must not be blank",
        ),
    ]

    async with await _make_client(app) as ac:
        responses = [
            (
                await ac.request(
                    method,
                    url,
                    json=payload,
                    headers={"Authorization": "Bearer fake"},
                ),
                field,
                expected_type,
                expected_msg,
                payload[field],
            )
            for method, url, payload, field, expected_type, expected_msg in cases
        ]

    for resp, field, expected_type, expected_msg, bad_value in responses:
        assert resp.status_code == 422
        assert _validation_error_projection(resp.json()["detail"]) == [
            {
                "type": expected_type,
                "loc": ["body", field],
                "msg": expected_msg,
                "input": bad_value,
            }
        ]
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.environment.list_by_project.assert_not_awaited()
    mock_repos.environment.get_for_project.assert_not_awaited()
    mock_repos.environment.create.assert_not_awaited()
    mock_repos.environment.update.assert_not_awaited()
    mock_repos.environment.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
    mock_repos.audit.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_environment_encrypts_env_vars_and_redacts_audit(
    app, project, crypto, mock_repos, mock_user
):
    secret_env = {"API_TOKEN": "secret-value"}

    async def _create(**kwargs):
        env = _make_orm_environment(
            kwargs["project_id"],
            env_id=kwargs["id"],
            env_vars=kwargs["env_vars"],
        )
        env.name = kwargs["name"]
        env.base_image = kwargs["base_image"]
        env.setup_script = kwargs["setup_script"]
        env.memory_mb = kwargs["memory_mb"]
        env.cpu_cores = kwargs["cpu_cores"]
        env.resource_limits = kwargs["resource_limits"]
        env.network_policy = kwargs["network_policy"]
        env.cache_key = kwargs["cache_key"]
        return env

    mock_repos.environment.create.side_effect = _create

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/environments",
            json={
                "name": "default",
                "base_image": "python:3.12.1",
                "setup_script": "pip install -r requirements.txt",
                "memory_mb": 1024,
                "cpu_cores": 2.0,
                "disk_mb": 2048,
                "max_artifact_size_mb": 256,
                "max_artifacts_count": 12,
                "network_policy": "restricted",
                "env_vars": secret_env,
                "cache_key": "py312",
            },
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["env_vars"] == secret_env
    assert body["memory_mb"] == 1024
    assert body["cpu_cores"] == 2.0
    assert body["disk_mb"] == 2048
    assert body["max_artifact_size_mb"] == 256
    assert body["max_artifacts_count"] == 12
    assert body["network_policy"] == "restricted"
    assert body["cache_key"] == "py312"

    create_kwargs = mock_repos.environment.create.await_args.kwargs
    assert create_kwargs["id"] == uuid.UUID(body["id"])
    assert create_kwargs["project_id"] == project.id
    assert create_kwargs["name"] == "default"
    assert create_kwargs["base_image"] == "python:3.12.1"
    assert create_kwargs["setup_script"] == "pip install -r requirements.txt"
    assert create_kwargs["memory_mb"] == 1024
    assert create_kwargs["cpu_cores"] == 2.0
    assert create_kwargs["resource_limits"] == {
        "max_artifact_size_mb": 256,
        "max_artifacts_count": 12,
        "disk_mb": 2048,
    }
    assert create_kwargs["network_policy"] == "restricted"
    assert create_kwargs["cache_key"] == "py312"
    stored_env_vars = create_kwargs["env_vars"]
    assert "API_TOKEN" not in repr(stored_env_vars)
    assert "secret-value" not in repr(stored_env_vars)
    assert decrypt_env_vars(
        stored_env_vars,
        environment_id=create_kwargs["id"],
        crypto=crypto,
    ) == secret_env

    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["tenant_id"] == mock_user.tenant_id
    assert audit_kwargs["user_id"] == mock_user.user_id
    assert audit_kwargs["action"] == "environment.create"
    assert audit_kwargs["resource_type"] == "environment"
    assert audit_kwargs["resource_id"] == uuid.UUID(body["id"])
    assert audit_kwargs["before_state"] is None
    assert audit_kwargs["after_state"]["id"] == body["id"]
    assert audit_kwargs["after_state"]["project_id"] == str(project.id)
    assert audit_kwargs["after_state"]["name"] == "default"
    assert audit_kwargs["after_state"]["base_image"] == "python:3.12.1"
    assert audit_kwargs["after_state"]["setup_script"] == "pip install -r requirements.txt"
    assert audit_kwargs["after_state"]["memory_mb"] == 1024
    assert audit_kwargs["after_state"]["cpu_cores"] == 2.0
    assert audit_kwargs["after_state"]["disk_mb"] == 2048
    assert audit_kwargs["after_state"]["max_artifact_size_mb"] == 256
    assert audit_kwargs["after_state"]["max_artifacts_count"] == 12
    assert audit_kwargs["after_state"]["network_policy"] == "restricted"
    assert audit_kwargs["after_state"]["cache_key"] == "py312"
    serialized_audit = repr(audit_kwargs["after_state"])
    assert "API_TOKEN" not in serialized_audit
    assert "secret-value" not in serialized_audit
    assert audit_kwargs["after_state"]["env_vars"] == {"redacted": True, "count": 1}


@pytest.mark.asyncio
async def test_create_environment_stores_disk_limit(
    app,
    project,
    crypto,
    mock_repos,
    mock_user,
):
    async def _create(**kwargs):
        env = _make_orm_environment(kwargs["project_id"], env_id=kwargs["id"])
        env.name = kwargs["name"]
        env.base_image = kwargs["base_image"]
        env.setup_script = kwargs["setup_script"]
        env.memory_mb = kwargs["memory_mb"]
        env.cpu_cores = kwargs["cpu_cores"]
        env.resource_limits = kwargs["resource_limits"]
        env.network_policy = kwargs["network_policy"]
        env.env_vars = kwargs["env_vars"]
        env.cache_key = kwargs["cache_key"]
        env.created_at = datetime(2026, 5, 31, 19, 20, 21, tzinfo=timezone.utc)
        return env

    mock_repos.environment.create.side_effect = _create

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/environments",
            json={
                "name": "default",
                "base_image": "python:3.12.1",
                "disk_mb": 2048,
            },
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    env_id = uuid.UUID(body["id"])
    assert body == {
        "id": str(env_id),
        "project_id": str(project.id),
        "name": "default",
        "base_image": "python:3.12.1",
        "setup_script": None,
        "memory_mb": 512,
        "cpu_cores": 1.0,
        "disk_mb": 2048,
        "max_artifact_size_mb": 100,
        "max_artifacts_count": 50,
        "network_policy": "deny",
        "env_vars": {},
        "cache_key": None,
        "created_at": "2026-05-31T19:20:21Z",
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project.id,
        mock_user.tenant_id,
    )
    mock_repos.environment.create.assert_awaited_once()
    create_kwargs = mock_repos.environment.create.await_args.kwargs
    stored_env_vars = create_kwargs["env_vars"]
    assert decrypt_env_vars(stored_env_vars, environment_id=env_id, crypto=crypto) == {}
    assert create_kwargs == {
        "id": env_id,
        "project_id": project.id,
        "name": "default",
        "base_image": "python:3.12.1",
        "setup_script": None,
        "memory_mb": 512,
        "cpu_cores": 1.0,
        "resource_limits": {
            "max_artifact_size_mb": 100,
            "max_artifacts_count": 50,
            "disk_mb": 2048,
        },
        "network_policy": "deny",
        "env_vars": stored_env_vars,
        "cache_key": None,
    }
    mock_repos.audit.create.assert_awaited_once()
    assert mock_repos.audit.create.await_args.kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "environment.create",
        "resource_type": "environment",
        "resource_id": env_id,
        "before_state": None,
        "after_state": {
            "id": str(env_id),
            "project_id": str(project.id),
            "name": "default",
            "base_image": "python:3.12.1",
            "setup_script": None,
            "memory_mb": 512,
            "cpu_cores": 1.0,
            "disk_mb": 2048,
            "max_artifact_size_mb": 100,
            "max_artifacts_count": 50,
            "network_policy": "deny",
            "env_vars": {"redacted": True, "count": 0},
            "cache_key": None,
            "created_at": "2026-05-31T19:20:21Z",
        },
    }


@pytest.mark.asyncio
async def test_update_environment_updates_and_clears_disk_limit(
    app,
    project,
    mock_repos,
    mock_user,
):
    env = _make_orm_environment(project.id)
    env.created_at = datetime(2026, 5, 31, 21, 22, 23, tzinfo=timezone.utc)
    mock_repos.environment.get_for_project.return_value = env

    async def _update(instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    mock_repos.environment.update.side_effect = _update

    async with await _make_client(app) as ac:
        update_resp = await ac.put(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            json={"disk_mb": 2048},
            headers={"Authorization": "Bearer fake"},
        )
        clear_resp = await ac.put(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            json={"disk_mb": None},
            headers={"Authorization": "Bearer fake"},
        )

    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json() == {
        "id": str(env.id),
        "project_id": str(project.id),
        "name": "default",
        "base_image": "python:3.12.1",
        "setup_script": None,
        "memory_mb": 512,
        "cpu_cores": 1.0,
        "disk_mb": 2048,
        "max_artifact_size_mb": 100,
        "max_artifacts_count": 50,
        "network_policy": "deny",
        "env_vars": {},
        "cache_key": None,
        "created_at": "2026-05-31T21:22:23Z",
    }
    assert clear_resp.status_code == 200, clear_resp.text
    assert clear_resp.json() == {
        "id": str(env.id),
        "project_id": str(project.id),
        "name": "default",
        "base_image": "python:3.12.1",
        "setup_script": None,
        "memory_mb": 512,
        "cpu_cores": 1.0,
        "disk_mb": None,
        "max_artifact_size_mb": 100,
        "max_artifacts_count": 50,
        "network_policy": "deny",
        "env_vars": {},
        "cache_key": None,
        "created_at": "2026-05-31T21:22:23Z",
    }
    assert [call.args for call in mock_repos.project.get_for_tenant.await_args_list] == [
        (project.id, mock_user.tenant_id),
        (project.id, mock_user.tenant_id),
    ]
    assert [
        call.args for call in mock_repos.environment.get_for_project.await_args_list
    ] == [
        (env.id, project.id),
        (env.id, project.id),
    ]
    assert [call.args for call in mock_repos.environment.update.await_args_list] == [
        (env,),
        (env,),
    ]
    assert [call.kwargs for call in mock_repos.environment.update.await_args_list] == [
        {
            "resource_limits": {
                "disk_mb": 2048,
                "max_artifact_size_mb": 100,
                "max_artifacts_count": 50,
            },
        },
        {
            "resource_limits": {
                "max_artifact_size_mb": 100,
                "max_artifacts_count": 50,
            },
        },
    ]
    audit_calls = [
        call.kwargs for call in mock_repos.audit.create.await_args_list
    ]
    assert [
        (
            call["tenant_id"],
            call["user_id"],
            call["action"],
            call["resource_type"],
            call["resource_id"],
            call["before_state"]["disk_mb"],
            call["after_state"]["disk_mb"],
            call["after_state"]["max_artifact_size_mb"],
            call["after_state"]["max_artifacts_count"],
            call["after_state"]["env_vars"],
        )
        for call in audit_calls
    ] == [
        (
            mock_user.tenant_id,
            mock_user.user_id,
            "environment.update",
            "environment",
            env.id,
            1024,
            2048,
            100,
            50,
            {"redacted": True, "count": 0},
        ),
        (
            mock_user.tenant_id,
            mock_user.user_id,
            "environment.update",
            "environment",
            env.id,
            2048,
            None,
            100,
            50,
            {"redacted": True, "count": 0},
        ),
    ]


@pytest.mark.asyncio
async def test_update_environment_reencrypts_env_vars_and_redacts_audit(
    app, project, crypto, mock_repos, mock_user
):
    env = _make_orm_environment(project.id)
    env.created_at = datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc)
    env.env_vars = encrypt_env_vars(
        {"OLD_TOKEN": "old-secret"},
        environment_id=env.id,
        crypto=crypto,
    )
    mock_repos.environment.get_for_project.return_value = env

    async def _update(instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    mock_repos.environment.update.side_effect = _update

    async with await _make_client(app) as ac:
        resp = await ac.put(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            json={"env_vars": {"NEW_TOKEN": "new-secret"}},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_body = {
        "id": str(env.id),
        "project_id": str(project.id),
        "name": "default",
        "base_image": "python:3.12.1",
        "setup_script": None,
        "memory_mb": 512,
        "cpu_cores": 1.0,
        "disk_mb": 1024,
        "max_artifact_size_mb": 100,
        "max_artifacts_count": 50,
        "network_policy": "deny",
        "env_vars": {"NEW_TOKEN": "new-secret"},
        "cache_key": None,
        "created_at": "2026-05-31T20:21:22Z",
    }
    assert body == expected_body

    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project.id,
        mock_user.tenant_id,
    )
    mock_repos.environment.get_for_project.assert_awaited_once_with(env.id, project.id)
    mock_repos.environment.update.assert_awaited_once()
    assert mock_repos.environment.update.await_args.args == (env,)
    update_kwargs = mock_repos.environment.update.await_args.kwargs
    stored_env_vars = update_kwargs["env_vars"]
    assert update_kwargs == {"env_vars": stored_env_vars}
    assert "OLD_TOKEN" not in repr(stored_env_vars)
    assert "old-secret" not in repr(stored_env_vars)
    assert "NEW_TOKEN" not in repr(stored_env_vars)
    assert "new-secret" not in repr(stored_env_vars)
    assert decrypt_env_vars(stored_env_vars, environment_id=env.id, crypto=crypto) == {
        "NEW_TOKEN": "new-secret",
    }
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    expected_before = {
        **expected_body,
        "env_vars": {"redacted": True, "count": 1},
    }
    expected_after = {
        **expected_body,
        "env_vars": {"redacted": True, "count": 1},
    }
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "environment.update",
        "resource_type": "environment",
        "resource_id": env.id,
        "before_state": expected_before,
        "after_state": expected_after,
    }
    serialized_audit = repr(audit_kwargs)
    assert "OLD_TOKEN" not in serialized_audit
    assert "old-secret" not in serialized_audit
    assert "NEW_TOKEN" not in serialized_audit
    assert "new-secret" not in serialized_audit


@pytest.mark.asyncio
async def test_delete_environment_removes_existing_environment_and_audits(
    app,
    project,
    crypto,
    mock_repos,
):
    env = _make_orm_environment(project.id)
    env.env_vars = encrypt_env_vars(
        {"API_TOKEN": "delete-secret"},
        environment_id=env.id,
        crypto=crypto,
    )
    mock_repos.environment.get_for_project.return_value = env

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 204, resp.text
    assert resp.content == b""
    mock_repos.environment.get_for_project.assert_awaited_once_with(env.id, project.id)
    mock_repos.environment.delete.assert_awaited_once_with(env)
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["action"] == "environment.delete"
    assert audit_kwargs["resource_type"] == "environment"
    assert audit_kwargs["resource_id"] == env.id
    assert audit_kwargs["before_state"]["id"] == str(env.id)
    assert audit_kwargs["before_state"]["project_id"] == str(project.id)
    assert audit_kwargs["before_state"]["name"] == "default"
    assert audit_kwargs["before_state"]["base_image"] == "python:3.12.1"
    assert audit_kwargs["before_state"]["disk_mb"] == 1024
    assert audit_kwargs["before_state"]["env_vars"] == {"redacted": True, "count": 1}
    assert audit_kwargs["after_state"] is None
    serialized_audit = repr(audit_kwargs)
    assert "delete-secret" not in serialized_audit
    assert "API_TOKEN" not in serialized_audit


@pytest.mark.asyncio
async def test_get_environment_returns_same_404_for_missing_or_other_project(
    app,
    project,
    mock_repos,
):
    missing_id = uuid.uuid4()
    mock_repos.environment.get_for_project.return_value = None

    async with await _make_client(app) as ac:
        missing = await ac.get(
            f"/api/v1/projects/{project.id}/environments/{missing_id}",
            headers={"Authorization": "Bearer fake"},
        )

    assert missing.status_code == 404, missing.text
    mock_repos.environment.get_for_project.assert_awaited_once_with(
        missing_id, project.id
    )

    # An environment owned by another project is invisible to the scoped query,
    # so get_for_project returns None exactly as for a missing id.
    other_project_env_id = uuid.uuid4()
    mock_repos.environment.get_for_project = AsyncMock(return_value=None)

    async with await _make_client(app) as ac:
        wrong_project = await ac.get(
            f"/api/v1/projects/{project.id}/environments/{other_project_env_id}",
            headers={"Authorization": "Bearer fake"},
        )

    assert wrong_project.status_code == 404, wrong_project.text
    mock_repos.environment.get_for_project.assert_awaited_once_with(
        other_project_env_id, project.id
    )
    missing_body = missing.json()
    wrong_project_body = wrong_project.json()
    assert wrong_project_body == missing_body
    _assert_not_found_response(wrong_project_body, "Environment not found")
    mock_repos.environment.create.assert_not_awaited()
    mock_repos.environment.update.assert_not_awaited()
    mock_repos.environment.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
    mock_repos.audit.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_delete_environment_return_same_404_without_side_effects(
    app,
    project,
    mock_repos,
):
    missing_id = uuid.uuid4()
    # Both a missing id and an environment owned by another project resolve to
    # None through the project-scoped query, so all four lookups return None.
    other_project_env_id = uuid.uuid4()
    mock_repos.environment.get_for_project.side_effect = [
        None,
        None,
        None,
        None,
    ]

    async with await _make_client(app) as ac:
        responses = [
            await ac.put(
                f"/api/v1/projects/{project.id}/environments/{missing_id}",
                json={"env_vars": {"NEW_TOKEN": "should-not-encrypt"}},
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.delete(
                f"/api/v1/projects/{project.id}/environments/{missing_id}",
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.put(
                f"/api/v1/projects/{project.id}/environments/{other_project_env_id}",
                json={"env_vars": {"NEW_TOKEN": "should-not-encrypt"}},
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.delete(
                f"/api/v1/projects/{project.id}/environments/{other_project_env_id}",
                headers={"Authorization": "Bearer fake"},
            ),
        ]

    bodies = [resp.json() for resp in responses]
    assert [resp.status_code for resp in responses] == [404, 404, 404, 404]
    expected_body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Environment not found",
            "details": [],
        }
    }
    assert bodies == [expected_body] * 4
    assert [
        args.args for args in mock_repos.environment.get_for_project.await_args_list
    ] == [
        (missing_id, project.id),
        (missing_id, project.id),
        (other_project_env_id, project.id),
        (other_project_env_id, project.id),
    ]
    mock_repos.environment.create.assert_not_awaited()
    mock_repos.environment.update.assert_not_awaited()
    mock_repos.environment.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
    mock_repos.audit.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_environment_routes_hide_missing_project_without_side_effects(
    app,
    project,
    mock_user,
    mock_repos,
):
    class _FailIfCryptoUsed:
        def encrypt(self, *args, **kwargs):
            raise AssertionError("crypto should not be used for hidden projects")

        def decrypt(self, *args, **kwargs):
            raise AssertionError("crypto should not be used for hidden projects")

    app.state.container.crypto_service = _FailIfCryptoUsed()
    mock_repos.project.get_for_tenant.return_value = None
    env_id = uuid.uuid4()
    create_payload = {
        "name": "hidden",
        "base_image": "python:3.12.1",
        "env_vars": {"API_TOKEN": "should-not-encrypt"},
    }

    async with await _make_client(app) as ac:
        responses = [
            await ac.get(f"/api/v1/projects/{project.id}/environments"),
            await ac.post(
                f"/api/v1/projects/{project.id}/environments",
                json=create_payload,
            ),
            await ac.get(f"/api/v1/projects/{project.id}/environments/{env_id}"),
            await ac.put(
                f"/api/v1/projects/{project.id}/environments/{env_id}",
                json={"env_vars": {"NEW_TOKEN": "should-not-encrypt"}},
            ),
            await ac.delete(f"/api/v1/projects/{project.id}/environments/{env_id}"),
        ]

    bodies = [resp.json() for resp in responses]
    assert [resp.status_code for resp in responses] == [404, 404, 404, 404, 404]
    expected_body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Project not found",
            "details": [],
        }
    }
    assert bodies == [expected_body] * 5
    assert [args.args for args in mock_repos.project.get_for_tenant.await_args_list] == [
        (project.id, mock_user.tenant_id),
        (project.id, mock_user.tenant_id),
        (project.id, mock_user.tenant_id),
        (project.id, mock_user.tenant_id),
        (project.id, mock_user.tenant_id),
    ]
    mock_repos.environment.list_by_project.assert_not_awaited()
    mock_repos.environment.get_for_project.assert_not_awaited()
    mock_repos.environment.create.assert_not_awaited()
    mock_repos.environment.update.assert_not_awaited()
    mock_repos.environment.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
    mock_repos.audit.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_environment_routes_return_503_when_crypto_unavailable(
    app,
    project,
    mock_repos,
):
    app.state.container.crypto_service = None
    env = _make_orm_environment(project.id)
    mock_repos.environment.get_for_project.return_value = env

    async with await _make_client(app) as ac:
        list_resp = await ac.get(
            f"/api/v1/projects/{project.id}/environments",
            headers={"Authorization": "Bearer fake"},
        )
        create_resp = await ac.post(
            f"/api/v1/projects/{project.id}/environments",
            json={"name": "default", "base_image": "python:3.12.1"},
            headers={"Authorization": "Bearer fake"},
        )
        get_resp = await ac.get(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            headers={"Authorization": "Bearer fake"},
        )
        update_resp = await ac.put(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            json={"env_vars": {"API_TOKEN": "new-secret"}},
            headers={"Authorization": "Bearer fake"},
        )
        delete_resp = await ac.delete(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            headers={"Authorization": "Bearer fake"},
        )

    responses = [list_resp, create_resp, get_resp, update_resp, delete_resp]
    assert [resp.status_code for resp in responses] == [503, 503, 503, 503, 503]
    assert [resp.json() for resp in responses] == [
        {"detail": "Crypto service not initialised"}
    ] * 5
    mock_repos.environment.list_by_project.assert_not_awaited()
    assert [
        args.args for args in mock_repos.environment.get_for_project.await_args_list
    ] == [
        (env.id, project.id),
        (env.id, project.id),
        (env.id, project.id),
    ]
    mock_repos.environment.create.assert_not_awaited()
    mock_repos.environment.update.assert_not_awaited()
    mock_repos.environment.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
    mock_repos.audit.commit.assert_not_awaited()


def test_environment_crypto_unavailable_responses_are_documented(app):
    openapi = app.openapi()

    for method in ("get", "post"):
        _assert_503_error_response(
            openapi,
            "/api/v1/projects/{project_id}/environments",
            method,
        )
    for method in ("get", "put", "delete"):
        _assert_503_error_response(
            openapi,
            "/api/v1/projects/{project_id}/environments/{env_id}",
            method,
        )


@pytest.mark.asyncio
async def test_get_environment_decrypt_failure_returns_500_and_writes_audit(
    app, project, crypto, mock_repos
):
    env = _make_orm_environment(
        project.id,
        env_vars=encrypt_env_vars(
            {"API_TOKEN": "secret-value"},
            environment_id=uuid.uuid4(),
            crypto=crypto,
        ),
    )
    mock_repos.environment.get_for_project.return_value = env

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 500, resp.text
    assert resp.json() == {"detail": "Environment env vars decrypt failed"}
    assert "secret-value" not in resp.text
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["action"] == "environment.env_vars_decrypt_failed"
    assert audit_kwargs["resource_id"] == env.id
    assert "secret-value" not in repr(audit_kwargs)
    mock_repos.audit.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_environment_encrypt_failure_returns_500_and_writes_audit(
    app, project, mock_repos
):
    class _FailingCrypto:
        def encrypt(self, *args, **kwargs):
            raise RuntimeError("crypto unavailable: secret-value")

    app.state.container.crypto_service = _FailingCrypto()

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/environments",
            json={
                "name": "default",
                "base_image": "python:3.12.1",
                "env_vars": {"API_TOKEN": "secret-value"},
            },
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 500, resp.text
    assert resp.json() == {"detail": "Environment env vars encrypt failed"}
    assert "secret-value" not in resp.text
    mock_repos.environment.create.assert_not_awaited()
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["action"] == "environment.env_vars_encrypt_failed"
    assert audit_kwargs["resource_id"] is not None
    assert "secret-value" not in repr(audit_kwargs)
    mock_repos.audit.commit.assert_awaited_once()
