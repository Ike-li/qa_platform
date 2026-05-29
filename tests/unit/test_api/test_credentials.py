"""Tests for /projects/{id}/credentials CRUD: list, create, get, rotate, delete.

Verifies:
- AES envelope: encrypt() is invoked with the (project_id, name) AAD context
- delete-in-use: 409 when project.credential_id references the credential
- happy paths for list/create/get/rotate

Plaintext is never returned in CredentialResponse — schema enforces that
(no ``value`` field), so the route can't accidentally leak it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_project(tenant_id, credential_id=None):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.tenant_id = tenant_id
    obj.credential_id = credential_id
    return obj


def _make_orm_credential(project_id, tenant_id, name="db_password", type_="password"):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.tenant_id = tenant_id
    obj.project_id = project_id
    obj.name = name
    obj.type = type_
    obj.encrypted_value = b"old-cipher"
    obj.created_by = uuid.uuid4()
    obj.created_at = datetime.now(timezone.utc)
    return obj


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.role = "platform_admin"  # bypasses project RBAC layer
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
    repos.credential = AsyncMock()
    repos.audit = AsyncMock()
    return repos


@pytest.fixture
def mock_crypto():
    crypto = MagicMock()
    crypto.encrypt = MagicMock(return_value=b"\x00\x01\x02encrypted")
    return crypto


@pytest.fixture
def app(mock_repos, mock_user, mock_crypto):
    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    app = create_app(container=MagicMock())
    container_mock = MagicMock()
    container_mock.crypto_service = mock_crypto
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


@pytest.mark.asyncio
async def test_list_credentials_returns_response_without_plaintext(
    app, project, tenant_id, mock_repos
):
    c1 = _make_orm_credential(project.id, tenant_id, name="t1", type_="token")
    c2 = _make_orm_credential(project.id, tenant_id, name="t2", type_="ssh_key")
    mock_repos.credential.list_by_project_tenant.return_value = ([c1, c2], 2)

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/credentials?page=2&per_page=1",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == 2
    assert body["per_page"] == 1
    assert body["total"] == 2
    assert len(body["data"]) == 2
    for entry in body["data"]:
        assert "value" not in entry
        assert "encrypted_value" not in entry
    mock_repos.credential.list_by_project_tenant.assert_awaited_once()
    assert mock_repos.credential.list_by_project_tenant.await_args.kwargs == {
        "offset": 1,
        "limit": 1,
    }


@pytest.mark.asyncio
async def test_create_credential_encrypts_with_aad(
    app, project, tenant_id, mock_crypto, mock_repos
):
    """The router must bind ciphertext to (project_id, name) via AAD so a
    ciphertext from another project/name cannot decrypt here."""
    mock_repos.credential.get_name_exists.return_value = False

    created = _make_orm_credential(project.id, tenant_id, name="db_password", type_="password")
    mock_repos.credential.create.return_value = created

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "db_password", "type": "password", "value": "s3cret"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 201, resp.text

    mock_crypto.encrypt.assert_called_once()
    call = mock_crypto.encrypt.call_args
    assert call.args[0] == "s3cret"
    assert call.kwargs["context_id"] == f"credential:{project.id}:db_password"

    body = resp.json()
    assert "value" not in body


@pytest.mark.asyncio
async def test_create_credential_audit_does_not_leak_plaintext(
    app, project, tenant_id, mock_crypto, mock_repos
):
    """The audit trail must not contain the plaintext value or ciphertext."""
    mock_repos.credential.get_name_exists.return_value = False

    created = _make_orm_credential(project.id, tenant_id, name="k", type_="password")
    mock_repos.credential.create.return_value = created

    secret_value = "totally-secret-pw-9999"
    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "k", "type": "password", "value": secret_value},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 201, resp.text

    mock_repos.audit.create.assert_called_once()
    audit_kwargs = mock_repos.audit.create.call_args.kwargs
    after_state = audit_kwargs.get("after_state") or {}
    serialised = repr(after_state) + repr(audit_kwargs.get("before_state"))
    assert secret_value not in serialised
    assert "encrypted_value" not in serialised
    assert after_state.get("name") == "k"
    assert after_state.get("type") == "password"


@pytest.mark.asyncio
async def test_create_credential_duplicate_name_returns_409(app, project, mock_repos):
    mock_repos.credential.get_name_exists.return_value = True

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "db_password", "type": "password", "value": "x"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_credential_404_when_missing(app, project, mock_repos):
    mock_repos.credential.get_by_project_tenant.return_value = None

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/credentials/{uuid.uuid4()}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rotate_credential_re_encrypts_with_aad(
    app, project, tenant_id, mock_crypto, mock_repos
):
    cred = _make_orm_credential(project.id, tenant_id, name="db_password")
    mock_repos.credential.get_by_project_tenant.return_value = cred

    async with await _make_client(app) as ac:
        resp = await ac.put(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            json={"value": "new-secret"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text

    mock_crypto.encrypt.assert_called_once()
    call = mock_crypto.encrypt.call_args
    assert call.args[0] == "new-secret"
    assert call.kwargs["context_id"] == f"credential:{project.id}:db_password"
    mock_repos.credential.update.assert_called_once_with(cred, encrypted_value=b"\x00\x01\x02encrypted")


@pytest.mark.asyncio
async def test_delete_credential_404_when_missing(app, project, mock_repos):
    mock_repos.credential.get_by_project_tenant.return_value = None

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/credentials/{uuid.uuid4()}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_credential_in_use_returns_409(
    app, project, tenant_id, mock_repos
):
    """If the credential is referenced by project.credential_id, deleting it
    must fail with 409 to avoid orphaning git auth on the project."""
    cred = _make_orm_credential(project.id, tenant_id)
    project.credential_id = cred.id
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.credential.get_by_project_tenant.return_value = cred

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 409
    mock_repos.credential.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_credential_happy_path(app, project, tenant_id, mock_repos):
    cred = _make_orm_credential(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.return_value = cred

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 204
    mock_repos.credential.delete.assert_called_once_with(cred)
