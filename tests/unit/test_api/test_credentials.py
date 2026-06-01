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


def _assert_credential_not_found_response(resp):
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Credential not found",
            "details": [],
        }
    }


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

    container_mock = MagicMock()
    container_mock.crypto_service = mock_crypto
    container_mock.redis_client = None
    app = create_app(container=container_mock)

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


def _expected_credential_response(credential) -> dict:
    return {
        "id": str(credential.id),
        "project_id": str(credential.project_id),
        "name": credential.name,
        "type": credential.type,
        "created_by": str(credential.created_by),
        "created_at": _json_datetime(credential.created_at),
    }


def _assert_503_error_response(openapi: dict, path: str, method: str) -> None:
    assert openapi["paths"][path][method]["responses"]["503"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}


@pytest.mark.asyncio
async def test_list_credentials_returns_response_without_plaintext(
    app, project, tenant_id, mock_repos
):
    c1 = _make_orm_credential(project.id, tenant_id, name="t1", type_="token")
    c2 = _make_orm_credential(project.id, tenant_id, name="t2", type_="ssh_key")
    c1.created_by = uuid.UUID("10000000-0000-0000-0000-000000000001")
    c2.created_by = uuid.UUID("10000000-0000-0000-0000-000000000002")
    c1.created_at = datetime(2026, 5, 31, 10, 11, 12, tzinfo=timezone.utc)
    c2.created_at = datetime(2026, 5, 31, 13, 14, 15, tzinfo=timezone.utc)
    mock_repos.credential.list_by_project_tenant.return_value = ([c1, c2], 2)

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/credentials?page=2&per_page=1",
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "data": [
            {
                "id": str(c1.id),
                "project_id": str(project.id),
                "name": "t1",
                "type": "token",
                "created_by": str(c1.created_by),
                "created_at": c1.created_at.isoformat().replace("+00:00", "Z"),
            },
            {
                "id": str(c2.id),
                "project_id": str(project.id),
                "name": "t2",
                "type": "ssh_key",
                "created_by": str(c2.created_by),
                "created_at": c2.created_at.isoformat().replace("+00:00", "Z"),
            },
        ],
        "page": 2,
        "per_page": 1,
        "total": 2,
    }
    mock_repos.credential.list_by_project_tenant.assert_awaited_once()
    assert mock_repos.credential.list_by_project_tenant.await_args.args == (
        project.id,
        tenant_id,
    )
    assert mock_repos.credential.list_by_project_tenant.await_args.kwargs == {
        "offset": 1,
        "limit": 1,
    }


@pytest.mark.asyncio
async def test_create_credential_encrypts_with_aad(
    app, project, tenant_id, mock_user, mock_crypto, mock_repos
):
    """The router must bind ciphertext to (project_id, name) via AAD so a
    ciphertext from another project/name cannot decrypt here."""
    mock_repos.credential.get_name_exists.return_value = False

    created = _make_orm_credential(project.id, tenant_id, name="db_password", type_="password")
    created.created_by = mock_user.user_id
    created.created_at = datetime(2026, 5, 31, 16, 17, 18, tzinfo=timezone.utc)
    mock_repos.credential.create.return_value = created

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "db_password", "type": "password", "value": "s3cret"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 201, resp.text

    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_name_exists.assert_awaited_once_with(
        project.id,
        "db_password",
    )
    mock_crypto.encrypt.assert_called_once_with(
        "s3cret",
        context_id=f"credential:{project.id}:db_password",
    )
    mock_repos.credential.create.assert_awaited_once_with(
        tenant_id=tenant_id,
        project_id=project.id,
        name="db_password",
        type="password",
        encrypted_value=b"\x00\x01\x02encrypted",
        created_by=mock_user.user_id,
    )

    body = resp.json()
    assert body == _expected_credential_response(created)
    assert "value" not in body
    assert "encrypted_value" not in body


@pytest.mark.asyncio
async def test_create_credential_audit_does_not_leak_plaintext(
    app, project, tenant_id, mock_user, mock_crypto, mock_repos
):
    """The audit trail must not contain the plaintext value or ciphertext."""
    mock_repos.credential.get_name_exists.return_value = False

    created = _make_orm_credential(project.id, tenant_id, name="k", type_="password")
    created.created_by = mock_user.user_id
    created.created_at = datetime(2026, 5, 31, 10, 11, 12, tzinfo=timezone.utc)
    mock_repos.credential.create.return_value = created

    secret_value = "totally-secret-pw-9999"
    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "k", "type": "password", "value": secret_value},
            headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == _expected_credential_response(created)
    assert "value" not in body
    assert "encrypted_value" not in body

    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "credential.create",
        "resource_type": "credential",
        "resource_id": created.id,
        "before_state": None,
        "after_state": {
            "id": str(created.id),
            "project_id": str(project.id),
            "name": "k",
            "type": "password",
            "created_by": str(mock_user.user_id),
            "created_at": "2026-05-31T10:11:12Z",
        },
    }
    serialised = repr(audit_kwargs)
    assert secret_value not in serialised
    assert "encrypted_value" not in serialised
    assert repr(mock_crypto.encrypt.return_value) not in serialised


@pytest.mark.asyncio
async def test_create_credential_duplicate_name_returns_409(
    app,
    project,
    tenant_id,
    mock_crypto,
    mock_repos,
):
    mock_repos.credential.get_name_exists.return_value = True

    async with await _make_client(app) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "db_password", "type": "password", "value": "x"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Credential name already exists"}
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_name_exists.assert_awaited_once_with(
        project.id,
        "db_password",
    )
    mock_crypto.encrypt.assert_not_called()
    mock_repos.credential.create.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_and_rotate_credentials_return_503_when_crypto_unavailable(
    app,
    project,
    tenant_id,
    mock_repos,
):
    app.state.container.crypto_service = None
    mock_repos.credential.get_name_exists.return_value = False
    cred = _make_orm_credential(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.return_value = cred

    async with await _make_client(app) as ac:
        create_resp = await ac.post(
            f"/api/v1/projects/{project.id}/credentials",
            json={"name": "db_password", "type": "password", "value": "s3cret"},
            headers={"Authorization": "Bearer fake"},
        )
        rotate_resp = await ac.put(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            json={"value": "new-secret"},
            headers={"Authorization": "Bearer fake"},
        )

    assert create_resp.status_code == 503
    assert create_resp.json() == {"detail": "Crypto service not initialised"}
    assert rotate_resp.status_code == 503
    assert rotate_resp.json() == {"detail": "Crypto service not initialised"}
    assert [args.args for args in mock_repos.project.get_for_tenant.await_args_list] == [
        (project.id, tenant_id),
        (project.id, tenant_id),
    ]
    mock_repos.credential.get_name_exists.assert_awaited_once_with(
        project.id,
        "db_password",
    )
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        cred.id,
        project.id,
        tenant_id,
    )
    mock_repos.credential.create.assert_not_awaited()
    mock_repos.credential.update.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


def test_credential_crypto_unavailable_responses_are_documented(app):
    openapi = app.openapi()

    _assert_503_error_response(
        openapi,
        "/api/v1/projects/{project_id}/credentials",
        "post",
    )
    _assert_503_error_response(
        openapi,
        "/api/v1/projects/{project_id}/credentials/{credential_id}",
        "put",
    )


@pytest.mark.asyncio
async def test_create_credential_rejects_invalid_body_without_side_effects(
    app,
    project,
    mock_crypto,
    mock_repos,
):
    cases = [
        (
            {"name": "   ", "type": "password", "value": "secret"},
            {
                "type": "value_error",
                "loc": ["body", "name"],
                "msg": "Value error, credential name must not be blank",
                "input": "   ",
            },
        ),
        (
            {"name": "", "type": "password", "value": "secret"},
            {
                "type": "string_too_short",
                "loc": ["body", "name"],
                "msg": "String should have at least 1 character",
                "input": "",
            },
        ),
        (
            {"name": "api", "type": "password", "value": ""},
            {
                "type": "string_too_short",
                "loc": ["body", "value"],
                "msg": "String should have at least 1 character",
                "input": "",
            },
        ),
        (
            {"name": "api", "type": "oauth", "value": "secret"},
            {
                "type": "literal_error",
                "loc": ["body", "type"],
                "msg": "Input should be 'token', 'ssh_key' or 'password'",
                "input": "oauth",
            },
        ),
    ]

    async with await _make_client(app) as ac:
        responses = [
            (
                await ac.post(
                    f"/api/v1/projects/{project.id}/credentials",
                    json=payload,
                    headers={"Authorization": "Bearer fake"},
                ),
                expected_error,
            )
            for payload, expected_error in cases
        ]

    for resp, expected_error in responses:
        assert resp.status_code == 422
        assert _validation_error_projection(resp.json()["detail"]) == [expected_error]
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.credential.get_name_exists.assert_not_awaited()
    mock_repos.credential.create.assert_not_awaited()
    mock_crypto.encrypt.assert_not_called()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_credential_404_when_missing(app, project, tenant_id, mock_repos):
    mock_repos.credential.get_by_project_tenant.return_value = None
    credential_id = uuid.uuid4()

    async with await _make_client(app) as ac:
        resp = await ac.get(
            f"/api/v1/projects/{project.id}/credentials/{credential_id}",
            headers={"Authorization": "Bearer fake"},
        )
    _assert_credential_not_found_response(resp)
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        credential_id,
        project.id,
        tenant_id,
    )
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_rotate_credential_404_when_missing_without_side_effects(
    app,
    project,
    tenant_id,
    mock_crypto,
    mock_repos,
):
    mock_repos.credential.get_by_project_tenant.return_value = None
    credential_id = uuid.uuid4()

    async with await _make_client(app) as ac:
        resp = await ac.put(
            f"/api/v1/projects/{project.id}/credentials/{credential_id}",
            json={"value": "new-secret"},
            headers={"Authorization": "Bearer fake"},
        )

    _assert_credential_not_found_response(resp)
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        credential_id,
        project.id,
        tenant_id,
    )
    mock_crypto.encrypt.assert_not_called()
    mock_repos.credential.update.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_rotate_credential_re_encrypts_with_aad(
    app, project, tenant_id, mock_user, mock_crypto, mock_repos
):
    cred = _make_orm_credential(project.id, tenant_id, name="db_password")
    cred.created_by = mock_user.user_id
    cred.created_at = datetime(2026, 5, 31, 17, 18, 19, tzinfo=timezone.utc)
    mock_repos.credential.get_by_project_tenant.return_value = cred

    async with await _make_client(app) as ac:
        resp = await ac.put(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            json={"value": "new-secret"},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200, resp.text

    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        cred.id,
        project.id,
        tenant_id,
    )
    mock_crypto.encrypt.assert_called_once_with(
        "new-secret",
        context_id=f"credential:{project.id}:db_password",
    )
    mock_repos.credential.update.assert_awaited_once_with(
        cred,
        encrypted_value=b"\x00\x01\x02encrypted",
    )

    body = resp.json()
    assert body == _expected_credential_response(cred)
    assert "value" not in body
    assert "encrypted_value" not in body

    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "credential.rotate",
        "resource_type": "credential",
        "resource_id": cred.id,
        "before_state": None,
        "after_state": _expected_credential_response(cred),
    }
    serialised = repr(audit_kwargs)
    assert "new-secret" not in serialised
    assert "encrypted_value" not in serialised
    assert repr(mock_crypto.encrypt.return_value) not in serialised


@pytest.mark.asyncio
async def test_delete_credential_404_when_missing(app, project, tenant_id, mock_repos):
    mock_repos.credential.get_by_project_tenant.return_value = None
    credential_id = uuid.uuid4()

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/credentials/{credential_id}",
            headers={"Authorization": "Bearer fake"},
        )
    _assert_credential_not_found_response(resp)
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        credential_id,
        project.id,
        tenant_id,
    )
    mock_repos.credential.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


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
    assert resp.json() == {
        "detail": "Credential is in use by this project (project.credential_id)"
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        cred.id,
        project.id,
        tenant_id,
    )
    mock_repos.credential.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_credential_happy_path(
    app, project, tenant_id, mock_user, mock_repos
):
    cred = _make_orm_credential(project.id, tenant_id)
    cred.created_by = mock_user.user_id
    cred.created_at = datetime(2026, 5, 31, 18, 19, 20, tzinfo=timezone.utc)
    mock_repos.credential.get_by_project_tenant.return_value = cred

    async with await _make_client(app) as ac:
        resp = await ac.delete(
            f"/api/v1/projects/{project.id}/credentials/{cred.id}",
            headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 204
    assert resp.content == b""
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)
    mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(
        cred.id,
        project.id,
        tenant_id,
    )
    mock_repos.credential.delete.assert_awaited_once_with(cred)
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": tenant_id,
        "user_id": mock_user.user_id,
        "action": "credential.delete",
        "resource_type": "credential",
        "resource_id": cred.id,
        "before_state": _expected_credential_response(cred),
        "after_state": None,
    }
    serialised = repr(audit_kwargs)
    assert "value" not in serialised
    assert "encrypted_value" not in serialised
    assert repr(cred.encrypted_value) not in serialised


@pytest.mark.asyncio
async def test_credential_routes_hide_missing_project_without_side_effects(
    app, project, tenant_id, mock_crypto, mock_repos
):
    mock_repos.project.get_for_tenant.return_value = None
    credential_id = uuid.uuid4()

    async with await _make_client(app) as ac:
        responses = [
            await ac.get(
                f"/api/v1/projects/{project.id}/credentials",
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.post(
                f"/api/v1/projects/{project.id}/credentials",
                json={"name": "db_password", "type": "password", "value": "secret"},
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.get(
                f"/api/v1/projects/{project.id}/credentials/{credential_id}",
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.put(
                f"/api/v1/projects/{project.id}/credentials/{credential_id}",
                json={"value": "new-secret"},
                headers={"Authorization": "Bearer fake"},
            ),
            await ac.delete(
                f"/api/v1/projects/{project.id}/credentials/{credential_id}",
                headers={"Authorization": "Bearer fake"},
            ),
        ]

    assert [resp.status_code for resp in responses] == [404, 404, 404, 404, 404]
    bodies = [resp.json() for resp in responses]
    expected_body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Project not found",
            "details": [],
        }
    }
    assert bodies == [expected_body] * 5
    assert [args.args for args in mock_repos.project.get_for_tenant.await_args_list] == [
        (project.id, tenant_id)
    ] * 5

    mock_repos.credential.list_by_project_tenant.assert_not_awaited()
    mock_repos.credential.get_name_exists.assert_not_awaited()
    mock_repos.credential.create.assert_not_awaited()
    mock_repos.credential.get_by_project_tenant.assert_not_awaited()
    mock_repos.credential.update.assert_not_awaited()
    mock_repos.credential.delete.assert_not_awaited()
    mock_crypto.encrypt.assert_not_called()
    mock_repos.audit.create.assert_not_awaited()
