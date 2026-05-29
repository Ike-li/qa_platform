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


@pytest.mark.parametrize("base_image", ["python", "python:latest", "python:stable", "python:edge"])
def test_environment_schema_rejects_unpinned_or_moving_base_images(base_image):
    with pytest.raises(ValidationError):
        EnvironmentCreate(name="default", base_image=base_image)

    with pytest.raises(ValidationError):
        EnvironmentUpdate(base_image=base_image)


def test_environment_schema_accepts_pinned_base_image():
    created = EnvironmentCreate(name="default", base_image="python:3.12.1")
    updated = EnvironmentUpdate(base_image="python:3.12-alpine")

    assert created.base_image == "python:3.12.1"
    assert updated.base_image == "python:3.12-alpine"


@pytest.mark.asyncio
async def test_create_environment_encrypts_env_vars_and_redacts_audit(
    app, project, crypto, mock_repos
):
    secret_env = {"API_TOKEN": "secret-value"}

    async def _create(**kwargs):
        return _make_orm_environment(
            kwargs["project_id"],
            env_id=kwargs["id"],
            env_vars=kwargs["env_vars"],
        )

    mock_repos.environment.create.side_effect = _create

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/environments",
            json={
                "name": "default",
                "base_image": "python:3.12.1",
                "env_vars": secret_env,
            },
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["env_vars"] == secret_env

    create_kwargs = mock_repos.environment.create.call_args.kwargs
    stored_env_vars = create_kwargs["env_vars"]
    assert "API_TOKEN" not in repr(stored_env_vars)
    assert "secret-value" not in repr(stored_env_vars)
    assert decrypt_env_vars(
        stored_env_vars,
        environment_id=create_kwargs["id"],
        crypto=crypto,
    ) == secret_env

    audit_kwargs = mock_repos.audit.create.call_args.kwargs
    serialized_audit = repr(audit_kwargs["after_state"])
    assert "secret-value" not in serialized_audit
    assert audit_kwargs["after_state"]["env_vars"] == {"redacted": True, "count": 1}


@pytest.mark.asyncio
async def test_create_environment_stores_disk_limit(app, project, mock_repos):
    async def _create(**kwargs):
        env = _make_orm_environment(kwargs["project_id"], env_id=kwargs["id"])
        env.resource_limits = kwargs["resource_limits"]
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
    assert resp.json()["disk_mb"] == 2048
    assert mock_repos.environment.create.call_args.kwargs["resource_limits"] == {
        "max_artifact_size_mb": 100,
        "max_artifacts_count": 50,
        "disk_mb": 2048,
    }


@pytest.mark.asyncio
async def test_update_environment_updates_and_clears_disk_limit(app, project, mock_repos):
    env = _make_orm_environment(project.id)
    mock_repos.environment.get_by_id.return_value = env

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
    assert update_resp.json()["disk_mb"] == 2048
    assert clear_resp.status_code == 200, clear_resp.text
    assert clear_resp.json()["disk_mb"] is None
    first_update = mock_repos.environment.update.call_args_list[0].kwargs
    second_update = mock_repos.environment.update.call_args_list[1].kwargs
    assert first_update["resource_limits"]["disk_mb"] == 2048
    assert "disk_mb" not in second_update["resource_limits"]


@pytest.mark.asyncio
async def test_update_environment_reencrypts_env_vars_and_redacts_audit(
    app, project, crypto, mock_repos
):
    env = _make_orm_environment(project.id)
    env.env_vars = encrypt_env_vars(
        {"OLD_TOKEN": "old-secret"},
        environment_id=env.id,
        crypto=crypto,
    )
    mock_repos.environment.get_by_id.return_value = env

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
    assert resp.json()["env_vars"] == {"NEW_TOKEN": "new-secret"}

    stored_env_vars = mock_repos.environment.update.call_args.kwargs["env_vars"]
    assert decrypt_env_vars(stored_env_vars, environment_id=env.id, crypto=crypto) == {
        "NEW_TOKEN": "new-secret",
    }
    serialized_audit = repr(mock_repos.audit.create.call_args.kwargs)
    assert "old-secret" not in serialized_audit
    assert "new-secret" not in serialized_audit


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
    mock_repos.environment.get_by_id.return_value = env

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/environments/{env.id}",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 500, resp.text
    audit_kwargs = mock_repos.audit.create.call_args.kwargs
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
            raise RuntimeError("crypto unavailable")

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
    mock_repos.environment.create.assert_not_called()
    audit_kwargs = mock_repos.audit.create.call_args.kwargs
    assert audit_kwargs["action"] == "environment.env_vars_encrypt_failed"
    assert audit_kwargs["resource_id"] is not None
    assert "secret-value" not in repr(audit_kwargs)
    mock_repos.audit.commit.assert_awaited_once()
