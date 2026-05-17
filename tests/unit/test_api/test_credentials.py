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


def _result(scalar=None, scalars_all=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=scalar)
    if scalars_all is not None:
        sp = MagicMock()
        sp.all = MagicMock(return_value=scalars_all)
        r.scalars = MagicMock(return_value=sp)
    return r


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
    repos.project.get_by_id.return_value = project
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
    # The routes read crypto from request.app.state.container.crypto_service
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


def _override_session(app, mock_session):
    from qaplatform.api.deps import _get_db_session

    async def _gen():
        yield mock_session

    app.dependency_overrides[_get_db_session] = _gen


async def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_list_credentials_returns_response_without_plaintext(
    app, project, tenant_id
):
    c1 = _make_orm_credential(project.id, tenant_id, name="t1", type_="token")
    c2 = _make_orm_credential(project.id, tenant_id, name="t2", type_="ssh_key")

    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalars_all=[c1, c2]))
    _override_session(app, session)

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/credentials",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    # Schema does not include plaintext or encrypted_value, even by accident.
    for entry in body:
        assert "value" not in entry
        assert "encrypted_value" not in entry


@pytest.mark.asyncio
async def test_create_credential_encrypts_with_aad(
    app, project, tenant_id, mock_crypto
):
    """The router must bind ciphertext to (project_id, name) via AAD so a
    ciphertext from another project/name cannot decrypt here."""
    session = MagicMock()
    # 1) duplicate-name check returns None, 2) flush, 3) refresh sets created_at
    session.execute = AsyncMock(return_value=_result(scalar=None))

    def _add(instance):
        # ORM auto-generates id/created_by/created_at on flush in real life;
        # simulate enough of that here so the response model can serialize.
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    _override_session(app, session)

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "db_password", "type": "password", "value": "s3cret"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 201, resp.text

    # crypto.encrypt must be called once with the AAD context_id.
    mock_crypto.encrypt.assert_called_once()
    call = mock_crypto.encrypt.call_args
    assert call.args[0] == "s3cret"
    assert call.kwargs["context_id"] == f"credential:{project.id}:db_password"

    # Plaintext must not surface in the response.
    body = resp.json()
    assert "value" not in body


@pytest.mark.asyncio
async def test_create_credential_audit_does_not_leak_plaintext(
    app, project, tenant_id, mock_crypto, mock_repos
):
    """The audit trail must not contain the plaintext value or ciphertext —
    only metadata (id/name/type). Otherwise an audit reader becomes a
    secondary credential-disclosure surface."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=None))

    def _add(instance):
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    _override_session(app, session)

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
    # And positively assert the metadata fields we DO want.
    assert after_state.get("name") == "k"
    assert after_state.get("type") == "password"


@pytest.mark.asyncio
async def test_create_credential_duplicate_name_returns_409(app, project):
    existing_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=existing_id))
    _override_session(app, session)

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "db_password", "type": "password", "value": "x"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_credential_404_when_missing(app, project):
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=None))
    _override_session(app, session)

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/credentials/{uuid.uuid4()}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rotate_credential_re_encrypts_with_aad(
    app, project, tenant_id, mock_crypto
):
    cred = _make_orm_credential(project.id, tenant_id, name="db_password")

    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=cred))
    session.flush = AsyncMock()
    _override_session(app, session)

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
    # AAD must rebind to the credential's *current* name, preventing cross-name reuse.
    assert call.kwargs["context_id"] == f"credential:{project.id}:db_password"
    # The ORM mutation used the freshly produced ciphertext.
    assert cred.encrypted_value == b"\x00\x01\x02encrypted"


@pytest.mark.asyncio
async def test_delete_credential_404_when_missing(app, project):
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=None))
    _override_session(app, session)

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
    project.credential_id = cred.id  # mark it as in use
    mock_repos.project.get_by_id.return_value = project

    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=cred))
    session.delete = AsyncMock(side_effect=AssertionError("delete should not happen"))
    _override_session(app, session)

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 409
    session.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_credential_happy_path(app, project, tenant_id):
    cred = _make_orm_credential(project.id, tenant_id)
    # Not in use: project.credential_id is None.

    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=cred))
    session.delete = AsyncMock()
    _override_session(app, session)

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 204
    session.delete.assert_called_once_with(cred)
