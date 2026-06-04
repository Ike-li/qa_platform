from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from qaplatform.api import deps as auth_deps
from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.middleware import CurrentUser, get_current_user
from qaplatform.api.v1.auth import _refresh_cookie_secure, _resolve_tenant_id, router


# --- Helpers ---


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


def _settings(jwt_secret="test-secret-key-for-jwt-32bytes!!"):
    s = MagicMock()
    s.jwt_secret = jwt_secret
    s.jwt_access_token_ttl = 1800
    s.jwt_refresh_token_ttl = 604800
    return s


def _session_mock():
    """Create a mock session and its async context manager factory."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def _factory():
        yield session

    return session, _factory()


def _make_orm_user(**overrides):
    user = MagicMock()
    user.id = overrides.get("id", uuid4())
    user.tenant_id = overrides.get("tenant_id", uuid4())
    user.username = overrides.get("username", "alice")
    user.email = overrides.get("email", "alice@example.com")
    user.password_hash = overrides.get("password_hash", "")
    user.role = overrides.get("role", "developer")
    user.is_active = overrides.get("is_active", True)
    user.is_platform_admin = overrides.get("is_platform_admin", False)
    user.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    return user


def _make_orm_token(**overrides):
    token = MagicMock()
    token.id = overrides.get("id", uuid4())
    token.user_id = overrides.get("user_id", uuid4())
    token.token_id = overrides.get("token_id", "tok123")
    token.name = overrides.get("name", "ci")
    token.secret_hash = overrides.get("secret_hash", "$argon2hash")
    token.scopes = overrides.get("scopes", ["*"])
    token.expires_at = overrides.get(
        "expires_at", datetime.now(timezone.utc) + timedelta(days=90)
    )
    token.is_revoked = overrides.get("is_revoked", False)
    token.last_used_at = overrides.get("last_used_at", None)
    token.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    user = MagicMock()
    user.role = overrides.get("user_role", "developer")
    user.tenant_id = overrides.get("user_tenant_id", uuid4())
    token.user = user
    return token


def _make_session_factory(session_cm):
    """Return a mock async_sessionmaker that returns session_cm when called."""
    return MagicMock(return_value=session_cm)


def _request_for_url(url: str):
    scheme, rest = url.split("://", 1)
    host = rest.split("/", 1)[0]
    return SimpleNamespace(url=SimpleNamespace(scheme=scheme, hostname=host))


def _multi_session_factory():
    """Return a factory callable that yields a fresh AsyncMock session each call."""

    def _make_fresh_session():
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.flush = AsyncMock()

        @asynccontextmanager
        async def _cm():
            yield session

        return _cm()

    return MagicMock(side_effect=lambda: _make_fresh_session())


def test_refresh_cookie_secure_defaults_to_secure():
    assert _refresh_cookie_secure(_request_for_url("http://test")) is True
    assert _refresh_cookie_secure(_request_for_url("https://127.0.0.1")) is True


def test_refresh_cookie_secure_allows_local_development_http():
    settings = SimpleNamespace(debug=True, environment="development")

    assert (
        _refresh_cookie_secure(_request_for_url("http://127.0.0.1"), settings) is False
    )
    assert (
        _refresh_cookie_secure(_request_for_url("http://localhost"), settings) is False
    )


def test_refresh_cookie_secure_can_be_configured_explicitly():
    assert (
        _refresh_cookie_secure(
            _request_for_url("http://127.0.0.1"),
            SimpleNamespace(
                refresh_cookie_secure=True, debug=True, environment="development"
            ),
        )
        is True
    )
    assert (
        _refresh_cookie_secure(
            _request_for_url("https://qa.example"),
            SimpleNamespace(refresh_cookie_secure=False),
        )
        is False
    )


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(router, prefix="/api/v1")
    return a


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _post_with_refresh_cookie(
    client: AsyncClient,
    path: str,
    refresh_token: str,
    **kwargs,
):
    client.cookies.set("refresh_token", refresh_token)
    return await client.post(path, **kwargs)


def _refresh_set_cookie(response) -> str:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith("refresh_token="):
            return header
    raise AssertionError("refresh_token Set-Cookie header missing")


def _assert_refresh_cookie_security(response, *, max_age: int = 604800) -> None:
    cookie = _refresh_set_cookie(response).lower()
    assert f"max-age={max_age}" in cookie
    assert "path=/api/v1/auth" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie


def _assert_refresh_cookie_cleared(response) -> None:
    cookie = _refresh_set_cookie(response).lower()
    assert "max-age=0" in cookie
    assert "path=/api/v1/auth" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie


def _assert_no_login_tokens(response) -> None:
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "refresh_token" not in response.cookies
    refresh_cookie_headers = [
        header
        for header in response.headers.get_list("set-cookie")
        if header.lower().startswith("refresh_token=")
    ]
    assert refresh_cookie_headers == []


def _assert_access_token_claims(
    jwt_svc: JWTService,
    token: str,
    *,
    user_id,
    tenant_id,
    role: str,
    is_platform_admin: bool = False,
) -> None:
    payload = jwt_svc.decode_token(token)
    assert {
        "sub": payload["sub"],
        "role": payload["role"],
        "tenant_id": payload["tenant_id"],
        "is_platform_admin": payload["is_platform_admin"],
        "type": payload["type"],
    } == {
        "sub": str(user_id),
        "role": role,
        "tenant_id": str(tenant_id),
        "is_platform_admin": is_platform_admin,
        "type": "access",
    }
    assert isinstance(payload["jti"], str)
    assert payload["jti"]
    assert payload["exp"] > payload["iat"]


def _assert_refresh_cookie_claims(
    response,
    jwt_svc: JWTService,
    *,
    user_id,
) -> None:
    payload = jwt_svc.decode_token(response.cookies["refresh_token"])
    assert {"sub": payload["sub"], "type": payload["type"]} == {
        "sub": str(user_id),
        "type": "refresh",
    }
    assert isinstance(payload["jti"], str)
    assert payload["jti"]
    assert payload["exp"] > payload["iat"]


def _assert_login_failed_audit(
    audit_repo,
    *,
    reason: str,
    username: str,
    tenant_id: UUID | None,
    user_id: UUID | None,
    user_agent: str,
) -> None:
    audit_repo.create.assert_awaited_once()
    call_kwargs = audit_repo.create.await_args.kwargs
    assert call_kwargs == {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "action": "auth.login_failed",
        "resource_type": "auth",
        "resource_id": None,
        "after_state": {"reason": reason, "username": username},
        "ip_address": "127.0.0.1",
        "user_agent": user_agent,
    }


def _setup_overrides(
    app: FastAPI, *, session_factory=None, jwt_svc=None, settings=None
):
    """Install dependency overrides on the app for auth deps."""
    if session_factory is not None:
        app.dependency_overrides[auth_deps.get_session_factory] = lambda: (
            session_factory
        )
    if jwt_svc is not None:
        app.dependency_overrides[auth_deps.get_jwt_service] = lambda: jwt_svc
    if settings is not None:
        app.dependency_overrides[auth_deps.get_settings] = lambda: settings


# --- Tenant resolution tests ---


class TestResolveTenant:
    @pytest.mark.asyncio
    async def test_returns_explicit_tenant_without_database_lookup(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=AssertionError("explicit tenant must not query database")
        )
        tenant_id = uuid4()

        result = await _resolve_tenant_id(session, tenant_id)

        assert result == tenant_id
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_tenant_repository_for_single_tenant_fallback(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=AssertionError("tenant fallback must use TenantRepository")
        )
        tenant_id = uuid4()
        tenant_repo = AsyncMock()
        tenant_repo.get_first.return_value = SimpleNamespace(id=tenant_id)

        with patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo):
            result = await _resolve_tenant_id(session, None)

        assert result == tenant_id
        tenant_repo.get_first.assert_awaited_once_with()
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_missing_single_tenant_fallback(self):
        session = AsyncMock()
        tenant_repo = AsyncMock()
        tenant_repo.get_first.return_value = None

        with patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_tenant_id(session, None)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "No tenant configured"
        tenant_repo.get_first.assert_awaited_once_with()


# --- Login tests ---


class TestLogin:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("payload", "expected_error"),
        [
            (
                {"username": "", "password": "correct-password"},
                {
                    "type": "string_too_short",
                    "loc": ["body", "username"],
                    "msg": "String should have at least 3 characters",
                    "input": "",
                },
            ),
            (
                {"username": "   ", "password": "correct-password"},
                {
                    "type": "string_pattern_mismatch",
                    "loc": ["body", "username"],
                    "msg": "String should match pattern '^[a-zA-Z0-9_]+$'",
                    "input": "   ",
                },
            ),
            (
                {"username": "x" * 33, "password": "correct-password"},
                {
                    "type": "string_too_long",
                    "loc": ["body", "username"],
                    "msg": "String should have at most 32 characters",
                    "input": "x" * 33,
                },
            ),
            (
                {"username": "alice", "password": ""},
                {
                    "type": "string_too_short",
                    "loc": ["body", "password"],
                    "msg": "String should have at least 1 character",
                    "input": "",
                },
            ),
            (
                {"username": "alice", "password": "   "},
                {
                    "type": "value_error",
                    "loc": ["body", "password"],
                    "msg": "Value error, login password must not be blank",
                    "input": "   ",
                },
            ),
            (
                {"username": "alice", "password": "x" * 129},
                {
                    "type": "string_too_long",
                    "loc": ["body", "password"],
                    "msg": "String should have at most 128 characters",
                    "input": "x" * 129,
                },
            ),
        ],
    )
    async def test_login_rejects_invalid_body_without_side_effects(
        self,
        app: FastAPI,
        client: AsyncClient,
        payload,
        expected_error,
    ):
        settings = _settings()
        jwt_svc = JWTService(settings)
        session_factory = MagicMock(
            side_effect=AssertionError("invalid login body must not open DB sessions")
        )
        user_repo_cls = MagicMock()
        audit_repo_cls = MagicMock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", user_repo_cls),
            patch("qaplatform.api.v1.auth.AuditEventRepository", audit_repo_cls),
            patch(
                "qaplatform.api.v1.auth._resolve_tenant_id",
                new_callable=AsyncMock,
            ) as mock_resolve,
        ):
            _setup_overrides(
                app,
                session_factory=session_factory,
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post("/api/v1/auth/login", json=payload)

        assert resp.status_code == 422
        assert _validation_error_projection(resp.json()["detail"]) == [expected_error]
        _assert_no_login_tokens(resp)
        session_factory.assert_not_called()
        user_repo_cls.assert_not_called()
        audit_repo_cls.assert_not_called()
        mock_resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_login_success(self, app: FastAPI, client: AsyncClient):
        from argon2 import PasswordHasher

        settings = _settings()
        jwt_svc = JWTService(settings)
        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("correct-password"))
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user
        user_repo.update_last_login = AsyncMock()

        session, session_cm = _session_mock()
        tenant_id = uuid4()
        before_login = datetime.now(timezone.utc)

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock
            ) as mock_resolve,
        ):
            mock_resolve.return_value = tenant_id
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "correct-password"},
            )
        after_login = datetime.now(timezone.utc)

        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "access_token": data["access_token"],
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "username": "alice",
                "email": "alice@example.com",
                "role": "developer",
                "tenant_id": str(user.tenant_id),
            },
        }
        assert "refresh_token" not in data
        assert "refresh_token" in resp.cookies
        _assert_refresh_cookie_security(resp, max_age=settings.jwt_refresh_token_ttl)
        _assert_access_token_claims(
            jwt_svc,
            data["access_token"],
            user_id=user.id,
            role="developer",
            tenant_id=user.tenant_id,
            is_platform_admin=False,
        )
        _assert_refresh_cookie_claims(resp, jwt_svc, user_id=user.id)
        mock_resolve.assert_awaited_once_with(session, None)
        user_repo.get_by_username.assert_awaited_once_with(tenant_id, "alice")
        user_repo.update_last_login.assert_awaited_once()
        last_login_args = user_repo.update_last_login.await_args.args
        assert last_login_args[0] is user
        assert before_login <= last_login_args[1] <= after_login
        assert last_login_args[1].tzinfo is timezone.utc
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, app: FastAPI, client: AsyncClient):
        from argon2 import PasswordHasher

        settings = _settings()
        jwt_svc = JWTService(settings)
        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("correct-password"))
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user
        user_repo.update_last_login = AsyncMock()
        audit_repo = _make_audit_repo_mock()
        tenant_id = uuid4()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock
            ) as mock_resolve,
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            mock_resolve.return_value = tenant_id
            _setup_overrides(
                app,
                session_factory=_multi_session_factory(),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/login",
                headers={"user-agent": "login-wrong-password-audit-test"},
                json={"username": "alice", "password": "wrong"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid credentials"}
        _assert_no_login_tokens(resp)
        mock_resolve.assert_awaited_once()
        assert mock_resolve.await_args.args[1] is None
        user_repo.get_by_username.assert_awaited_once_with(tenant_id, "alice")
        user_repo.update_last_login.assert_not_awaited()
        _assert_login_failed_audit(
            audit_repo,
            reason="invalid_credentials",
            username="alice",
            tenant_id=user.tenant_id,
            user_id=user.id,
            user_agent="login-wrong-password-audit-test",
        )

    @pytest.mark.asyncio
    async def test_login_user_not_found(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = None
        user_repo.update_last_login = AsyncMock()
        audit_repo = _make_audit_repo_mock()
        tenant_id = uuid4()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock
            ) as mock_resolve,
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            mock_resolve.return_value = tenant_id
            _setup_overrides(
                app,
                session_factory=_multi_session_factory(),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/login",
                headers={"user-agent": "login-user-not-found-audit-test"},
                json={"username": "nobody", "password": "x"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid credentials"}
        _assert_no_login_tokens(resp)
        mock_resolve.assert_awaited_once()
        assert mock_resolve.await_args.args[1] is None
        user_repo.get_by_username.assert_awaited_once_with(tenant_id, "nobody")
        user_repo.update_last_login.assert_not_awaited()
        _assert_login_failed_audit(
            audit_repo,
            reason="invalid_credentials",
            username="nobody",
            tenant_id=None,
            user_id=None,
            user_agent="login-user-not-found-audit-test",
        )

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, app: FastAPI, client: AsyncClient):
        from argon2 import PasswordHasher

        settings = _settings()
        jwt_svc = JWTService(settings)
        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("pw"), is_active=False)
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user
        user_repo.update_last_login = AsyncMock()
        audit_repo = _make_audit_repo_mock()
        tenant_id = uuid4()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock
            ) as mock_resolve,
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            mock_resolve.return_value = tenant_id
            _setup_overrides(
                app,
                session_factory=_multi_session_factory(),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/login",
                headers={"user-agent": "login-inactive-user-audit-test"},
                json={"username": "alice", "password": "pw"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Account is deactivated"}
        _assert_no_login_tokens(resp)
        mock_resolve.assert_awaited_once()
        assert mock_resolve.await_args.args[1] is None
        user_repo.get_by_username.assert_awaited_once_with(tenant_id, "alice")
        user_repo.update_last_login.assert_not_awaited()
        _assert_login_failed_audit(
            audit_repo,
            reason="account_deactivated",
            username="alice",
            tenant_id=user.tenant_id,
            user_id=user.id,
            user_agent="login-inactive-user-audit-test",
        )


# --- Register tests ---


def _register_session_mock():
    """Session mock for register that fails on route-level SQL."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(
        side_effect=AssertionError("register must use repositories")
    )

    @asynccontextmanager
    async def factory():
        yield session

    return session, factory()


def _register_repository_mocks(existing_tenant=None):
    tenant_repo = AsyncMock()
    tenant_repo.get_by_name.return_value = existing_tenant

    async def _create_tenant(**kwargs):
        return SimpleNamespace(id=uuid4(), **kwargs)

    tenant_repo.create.side_effect = _create_tenant

    user_repo = AsyncMock()

    async def _create_user(**kwargs):
        return SimpleNamespace(id=uuid4(), is_platform_admin=False, **kwargs)

    user_repo.create.side_effect = _create_user
    return tenant_repo, user_repo


def _assert_register_validation_short_circuited(
    response,
    *,
    expected_error: dict,
    session_factory,
    session,
    tenant_repo,
    user_repo,
    audit_repo,
) -> None:
    assert response.status_code == 422
    assert _validation_error_projection(response.json()["detail"]) == [expected_error]
    session_factory.assert_not_called()
    tenant_repo.get_by_name.assert_not_awaited()
    tenant_repo.create.assert_not_awaited()
    user_repo.create.assert_not_awaited()
    audit_repo.create.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        session, session_cm = _register_session_mock()
        tenant_repo, user_repo = _register_repository_mocks()

        with (
            patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "alice",
                    "email": "alice@example.com",
                    "password": "secure-password-1",
                },
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert UUID(data["user"]["id"])
        assert data == {
            "access_token": data["access_token"],
            "token_type": "bearer",
            "user": {
                "id": data["user"]["id"],
                "username": "alice",
                "email": "alice@example.com",
                "role": "owner",
                "tenant_id": str(user_repo.create.await_args.kwargs["tenant_id"]),
            },
        }
        assert "refresh_token" not in data
        assert "refresh_token" in resp.cookies
        _assert_refresh_cookie_security(resp, max_age=settings.jwt_refresh_token_ttl)
        _assert_access_token_claims(
            jwt_svc,
            data["access_token"],
            user_id=data["user"]["id"],
            role="owner",
            tenant_id=data["user"]["tenant_id"],
            is_platform_admin=False,
        )
        _assert_refresh_cookie_claims(resp, jwt_svc, user_id=data["user"]["id"])
        tenant_repo.get_by_name.assert_awaited_once_with("alice")
        tenant_repo.create.assert_awaited_once_with(name="alice")
        user_repo.create.assert_awaited_once()
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_register_username_conflict(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        existing = MagicMock()
        existing.name = "alice"
        session, session_cm = _register_session_mock()
        session_factory = _make_session_factory(session_cm)
        tenant_repo, user_repo = _register_repository_mocks(existing_tenant=existing)

        with (
            patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo),
            patch(
                "qaplatform.api.v1.auth.UserRepository", return_value=user_repo
            ) as user_repo_cls,
            patch("qaplatform.api.v1.auth.AuditEventRepository") as audit_repo_cls,
        ):
            _setup_overrides(
                app,
                session_factory=session_factory,
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "alice",
                    "email": "alice@example.com",
                    "password": "secure-password-1",
                },
            )

        assert resp.status_code == 409
        assert resp.json() == {"detail": "Username already taken"}
        _assert_no_login_tokens(resp)
        session_factory.assert_called_once_with()
        tenant_repo.get_by_name.assert_awaited_once_with("alice")
        tenant_repo.create.assert_not_awaited()
        user_repo_cls.assert_not_called()
        user_repo.create.assert_not_awaited()
        audit_repo_cls.assert_not_called()
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("username", "expected_error"),
        [
            (
                "ab",
                {
                    "type": "string_too_short",
                    "loc": ["body", "username"],
                    "msg": "String should have at least 3 characters",
                    "input": "ab",
                },
            ),
            (
                "x" * 33,
                {
                    "type": "string_too_long",
                    "loc": ["body", "username"],
                    "msg": "String should have at most 32 characters",
                    "input": "x" * 33,
                },
            ),
            (
                "has space",
                {
                    "type": "string_pattern_mismatch",
                    "loc": ["body", "username"],
                    "msg": "String should match pattern '^[a-zA-Z0-9_]+$'",
                    "input": "has space",
                },
            ),
            (
                "with-dash",
                {
                    "type": "string_pattern_mismatch",
                    "loc": ["body", "username"],
                    "msg": "String should match pattern '^[a-zA-Z0-9_]+$'",
                    "input": "with-dash",
                },
            ),
            (
                "umlautü",
                {
                    "type": "string_pattern_mismatch",
                    "loc": ["body", "username"],
                    "msg": "String should match pattern '^[a-zA-Z0-9_]+$'",
                    "input": "umlautü",
                },
            ),
        ],
    )
    async def test_register_rejects_invalid_username(
        self,
        app: FastAPI,
        client: AsyncClient,
        username,
        expected_error,
    ):
        settings = _settings()
        session, session_cm = _register_session_mock()
        session_factory = _make_session_factory(session_cm)
        tenant_repo, user_repo = _register_repository_mocks()
        audit_repo = _make_audit_repo_mock()

        with (
            patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                app,
                session_factory=session_factory,
                jwt_svc=JWTService(settings),
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": username,
                    "email": "alice@example.com",
                    "password": "secure-password-1",
                },
            )

        _assert_register_validation_short_circuited(
            resp,
            expected_error=expected_error,
            session_factory=session_factory,
            session=session,
            tenant_repo=tenant_repo,
            user_repo=user_repo,
            audit_repo=audit_repo,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("password", "expected_error"),
        [
            (
                "short",
                {
                    "type": "string_too_short",
                    "loc": ["body", "password"],
                    "msg": "String should have at least 8 characters",
                    "input": "short",
                },
            ),
            (
                "        ",
                {
                    "type": "value_error",
                    "loc": ["body", "password"],
                    "msg": "Value error, register password must not be blank",
                    "input": "        ",
                },
            ),
            (
                "x" * 129,
                {
                    "type": "string_too_long",
                    "loc": ["body", "password"],
                    "msg": "String should have at most 128 characters",
                    "input": "x" * 129,
                },
            ),
        ],
    )
    async def test_register_rejects_invalid_password(
        self,
        app: FastAPI,
        client: AsyncClient,
        password,
        expected_error,
    ):
        settings = _settings()
        session, session_cm = _register_session_mock()
        session_factory = _make_session_factory(session_cm)
        tenant_repo, user_repo = _register_repository_mocks()
        audit_repo = _make_audit_repo_mock()

        with (
            patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                app,
                session_factory=session_factory,
                jwt_svc=JWTService(settings),
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "alice",
                    "email": "alice@example.com",
                    "password": password,
                },
            )

        _assert_register_validation_short_circuited(
            resp,
            expected_error=expected_error,
            session_factory=session_factory,
            session=session,
            tenant_repo=tenant_repo,
            user_repo=user_repo,
            audit_repo=audit_repo,
        )

    @pytest.mark.asyncio
    async def test_register_rejects_bad_email(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        session, session_cm = _register_session_mock()
        session_factory = _make_session_factory(session_cm)
        tenant_repo, user_repo = _register_repository_mocks()
        audit_repo = _make_audit_repo_mock()

        with (
            patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                app,
                session_factory=session_factory,
                jwt_svc=JWTService(settings),
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "alice",
                    "email": "not-an-email",
                    "password": "secure-password-1",
                },
            )

        _assert_register_validation_short_circuited(
            resp,
            expected_error={
                "type": "value_error",
                "loc": ["body", "email"],
                "msg": "value is not a valid email address: An email address must have an @-sign.",
                "input": "not-an-email",
            },
            session_factory=session_factory,
            session=session,
            tenant_repo=tenant_repo,
            user_repo=user_repo,
            audit_repo=audit_repo,
        )


# --- Refresh tests ---


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        user_id = uuid4()
        refresh_token = jwt_svc.create_refresh_token(str(user_id))

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user

        session, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                refresh_token,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "access_token": data["access_token"],
            "token_type": "bearer",
        }
        assert "refresh_token" not in data
        assert "refresh_token" in resp.cookies
        _assert_refresh_cookie_security(resp, max_age=settings.jwt_refresh_token_ttl)
        _assert_access_token_claims(
            jwt_svc,
            data["access_token"],
            user_id=user.id,
            role="developer",
            tenant_id=user.tenant_id,
            is_platform_admin=False,
        )
        _assert_refresh_cookie_claims(resp, jwt_svc, user_id=user.id)
        user_repo.get_by_id.assert_awaited_once_with(user_id)

    @pytest.mark.asyncio
    async def test_refresh_missing_cookie(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        session, session_cm = _session_mock()
        session_factory = _make_session_factory(session_cm)
        _setup_overrides(
            app, session_factory=session_factory, jwt_svc=jwt_svc, settings=settings
        )
        resp = await client.post("/api/v1/auth/refresh")

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Missing refresh token"}
        assert "refresh_token" not in resp.cookies
        refresh_cookie_headers = [
            header
            for header in resp.headers.get_list("set-cookie")
            if header.lower().startswith("refresh_token=")
        ]
        assert refresh_cookie_headers == []
        session_factory.assert_not_called()
        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_rejected(
        self, app: FastAPI, client: AsyncClient
    ):
        settings = _settings()
        jwt_svc = JWTService(settings)
        access_token = jwt_svc.create_access_token("user-1", "viewer", "t1")
        session, session_cm = _session_mock()
        audit_repo = _make_audit_repo_mock()

        with patch(
            "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                access_token,
                headers={"user-agent": "refresh-access-token-audit-test"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid token type"}
        _assert_refresh_cookie_cleared(resp)
        _assert_refresh_failed_audit(
            audit_repo,
            reason="invalid_token_type",
            user_agent="refresh-access-token-audit-test",
            forbidden_values=[access_token],
        )
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refresh_expired_token(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        settings.jwt_refresh_token_ttl = 0
        jwt_svc = JWTService(settings)
        import time

        session, session_cm = _session_mock()
        audit_repo = _make_audit_repo_mock()

        refresh_token = jwt_svc.create_refresh_token("user-1")
        time.sleep(0.01)

        with patch(
            "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                refresh_token,
                headers={"user-agent": "refresh-expired-audit-test"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid refresh token"}
        _assert_refresh_cookie_cleared(resp)
        _assert_refresh_failed_audit(
            audit_repo,
            reason="invalid_refresh_token",
            user_agent="refresh-expired-audit-test",
            forbidden_values=[refresh_token],
        )
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refresh_missing_user_clears_cookie_without_revoking_token(
        self,
        app: FastAPI,
        client: AsyncClient,
    ):
        import jwt as _jwt

        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_id = uuid4()
        refresh_token = jwt_svc.create_refresh_token(str(user_id))
        refresh_jti = _jwt.decode(
            refresh_token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )["jti"]
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = None
        session, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                refresh_token,
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "User not found or deactivated"}
        _assert_refresh_cookie_cleared(resp)
        user_repo.get_by_id.assert_awaited_once_with(user_id)
        assert f"jwt:revoked:{refresh_jti}" not in store
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()


# --- Token CRUD tests ---


@pytest.fixture
def authenticated_app(app: FastAPI):
    fake_user = CurrentUser(
        user_id="a0000000-0000-0000-0000-000000000001",
        role="developer",
        tenant_id="b0000000-0000-0000-0000-000000000001",
    )
    app.dependency_overrides[get_current_user] = lambda: fake_user
    return app


@pytest.fixture
async def auth_client(authenticated_app):
    transport = ASGITransport(app=authenticated_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestTokenRoutes:
    @pytest.mark.asyncio
    async def test_create_token(
        self, authenticated_app: FastAPI, auth_client: AsyncClient
    ):
        token_id = "c" * 32
        token_secret = "d" * 64
        full_token = f"qap_{token_id}_{token_secret}"
        created_at = datetime(2026, 5, 31, 7, 8, 9, tzinfo=timezone.utc)
        fake_record = _make_orm_token(
            token_id=token_id,
            name="ci",
            scopes=["runs:read"],
            created_at=created_at,
        )
        api_token_repo = AsyncMock()

        async def _create_token_record(**kwargs):
            fake_record.expires_at = kwargs["expires_at"]
            return fake_record

        api_token_repo.create.side_effect = _create_token_record
        audit_repo = _make_audit_repo_mock()

        session, session_cm = _session_mock()

        with (
            patch(
                "qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo
            ),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
            patch(
                "qaplatform.api.v1.auth.TokenService.generate_token",
                return_value=(token_id, full_token),
            ),
            patch(
                "qaplatform.api.v1.auth.TokenService.hash_token",
                return_value="hashed-secret",
            ) as hash_token,
        ):
            _setup_overrides(
                authenticated_app, session_factory=_make_session_factory(session_cm)
            )
            resp = await auth_client.post(
                "/api/v1/auth/tokens",
                headers={"user-agent": "api-token-create-audit-test"},
                json={"name": "ci", "scopes": ["runs:read"], "expires_days": 30},
            )

        assert resp.status_code == 201
        data = resp.json()
        hash_token.assert_called_once_with(token_secret)
        create_kwargs = api_token_repo.create.await_args.kwargs
        assert data == {
            "token_id": token_id,
            "token": full_token,
            "name": "ci",
            "scopes": ["runs:read"],
            "expires_at": create_kwargs["expires_at"]
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            ),
            "created_at": "2026-05-31T07:08:09Z",
        }
        assert "secret_hash" not in resp.text
        assert "hashed-secret" not in resp.text
        assert create_kwargs["user_id"] == UUID("a0000000-0000-0000-0000-000000000001")
        assert create_kwargs["name"] == "ci"
        assert create_kwargs["token_id"] == token_id
        assert create_kwargs["secret_hash"] == "hashed-secret"
        assert create_kwargs["scopes"] == ["runs:read"]
        assert (
            timedelta(days=29, hours=23)
            < create_kwargs["expires_at"] - datetime.now(timezone.utc)
            <= timedelta(days=30)
        )
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.await_args.kwargs
        assert audit_kwargs == {
            "tenant_id": UUID("b0000000-0000-0000-0000-000000000001"),
            "user_id": UUID("a0000000-0000-0000-0000-000000000001"),
            "action": "auth.api_token_create",
            "resource_type": "auth",
            "resource_id": fake_record.id,
            "after_state": {"name": "ci", "scopes": ["runs:read"]},
            "ip_address": "127.0.0.1",
            "user_agent": "api-token-create-audit-test",
        }
        assert token_secret not in str(audit_kwargs)
        assert full_token not in str(audit_kwargs)
        assert "hashed-secret" not in str(audit_kwargs)
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("payload", "expected_error"),
        [
            (
                {"name": "", "scopes": ["runs:read"], "expires_days": 30},
                {
                    "type": "string_too_short",
                    "loc": ["body", "name"],
                    "msg": "String should have at least 1 character",
                    "input": "",
                },
            ),
            (
                {"name": "   ", "scopes": ["runs:read"], "expires_days": 30},
                {
                    "type": "value_error",
                    "loc": ["body", "name"],
                    "msg": "Value error, api token name must not be blank",
                    "input": "   ",
                },
            ),
            (
                {"name": "x" * 101, "scopes": ["runs:read"], "expires_days": 30},
                {
                    "type": "string_too_long",
                    "loc": ["body", "name"],
                    "msg": "String should have at most 100 characters",
                    "input": "x" * 101,
                },
            ),
            (
                {"name": "ci", "scopes": [""], "expires_days": 30},
                {
                    "type": "string_too_short",
                    "loc": ["body", "scopes", 0],
                    "msg": "String should have at least 1 character",
                    "input": "",
                },
            ),
            (
                {"name": "ci", "scopes": ["   "], "expires_days": 30},
                {
                    "type": "value_error",
                    "loc": ["body", "scopes", 0],
                    "msg": "Value error, api token scope must not be blank",
                    "input": "   ",
                },
            ),
            (
                {"name": "ci", "scopes": ["x" * 101], "expires_days": 30},
                {
                    "type": "string_too_long",
                    "loc": ["body", "scopes", 0],
                    "msg": "String should have at most 100 characters",
                    "input": "x" * 101,
                },
            ),
        ],
    )
    async def test_create_token_rejects_invalid_body_without_side_effects(
        self,
        authenticated_app: FastAPI,
        auth_client: AsyncClient,
        payload,
        expected_error,
    ):
        api_token_repo_cls = MagicMock()
        audit_repo_cls = MagicMock()
        session, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.ApiTokenRepository", api_token_repo_cls),
            patch("qaplatform.api.v1.auth.AuditEventRepository", audit_repo_cls),
            patch(
                "qaplatform.api.v1.auth.TokenService.generate_token"
            ) as generate_token,
            patch("qaplatform.api.v1.auth.TokenService.hash_token") as hash_token,
        ):
            _setup_overrides(
                authenticated_app,
                session_factory=_make_session_factory(session_cm),
            )
            resp = await auth_client.post("/api/v1/auth/tokens", json=payload)

        assert resp.status_code == 422
        assert _validation_error_projection(resp.json()["detail"]) == [expected_error]
        api_token_repo_cls.assert_not_called()
        audit_repo_cls.assert_not_called()
        generate_token.assert_not_called()
        hash_token.assert_not_called()
        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "path", "json_body"),
        [
            ("post", "/api/v1/auth/tokens", {"name": "ci"}),
            ("get", "/api/v1/auth/tokens", None),
            ("delete", "/api/v1/auth/tokens/tok123", None),
        ],
    )
    async def test_token_routes_require_authentication(
        self,
        app: FastAPI,
        client: AsyncClient,
        method: str,
        path: str,
        json_body: dict | None,
    ):
        session_factory = MagicMock(
            side_effect=AssertionError(
                "unauthenticated token routes must not open DB sessions"
            )
        )
        app.dependency_overrides[auth_deps.get_session_factory] = session_factory
        request = getattr(client, method)
        kwargs = {"json": json_body} if json_body is not None else {}

        resp = await request(path, **kwargs)

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Missing Authorization header"}
        session_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_token(
        self, authenticated_app: FastAPI, auth_client: AsyncClient
    ):
        fake_token = _make_orm_token(
            token_id="tok123",
            user_id=UUID("a0000000-0000-0000-0000-000000000001"),
        )
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = fake_token
        api_token_repo.revoke = AsyncMock()
        audit_repo = _make_audit_repo_mock()

        session, session_cm = _session_mock()

        with (
            patch(
                "qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo
            ),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                authenticated_app, session_factory=_make_session_factory(session_cm)
            )
            resp = await auth_client.delete(
                "/api/v1/auth/tokens/tok123",
                headers={"user-agent": "api-token-revoke-audit-test"},
            )

        assert resp.status_code == 204
        assert resp.content == b""
        api_token_repo.get_by_token_id.assert_awaited_once_with("tok123")
        api_token_repo.revoke.assert_awaited_once_with(fake_token)
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.await_args.kwargs
        assert audit_kwargs == {
            "tenant_id": UUID("b0000000-0000-0000-0000-000000000001"),
            "user_id": UUID("a0000000-0000-0000-0000-000000000001"),
            "action": "auth.api_token_revoke",
            "resource_type": "auth",
            "resource_id": fake_token.id,
            "before_state": {"name": fake_token.name},
            "ip_address": "127.0.0.1",
            "user_agent": "api-token-revoke-audit-test",
        }
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(
        self, authenticated_app: FastAPI, auth_client: AsyncClient
    ):
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = None
        api_token_repo.revoke = AsyncMock()
        audit_repo = _make_audit_repo_mock()

        session, session_cm = _session_mock()

        with (
            patch(
                "qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo
            ),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                authenticated_app, session_factory=_make_session_factory(session_cm)
            )
            resp = await auth_client.delete("/api/v1/auth/tokens/nonexistent")

        assert resp.status_code == 404
        assert resp.json() == {"detail": "Token not found"}
        api_token_repo.get_by_token_id.assert_awaited_once_with("nonexistent")
        api_token_repo.revoke.assert_not_awaited()
        audit_repo.create.assert_not_awaited()
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_revoke_token_hides_other_users_token_without_side_effects(
        self,
        authenticated_app: FastAPI,
        auth_client: AsyncClient,
    ):
        other_user_token = _make_orm_token(
            token_id="tok-other-user",
            user_id=UUID("c0000000-0000-0000-0000-000000000001"),
            name="other-user-token",
        )
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = other_user_token
        api_token_repo.revoke = AsyncMock()
        audit_repo = _make_audit_repo_mock()
        session, session_cm = _session_mock()

        with (
            patch(
                "qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo
            ),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                authenticated_app,
                session_factory=_make_session_factory(session_cm),
            )
            resp = await auth_client.delete("/api/v1/auth/tokens/tok-other-user")

        assert resp.status_code == 404
        assert resp.json() == {"detail": "Token not found"}
        api_token_repo.get_by_token_id.assert_awaited_once_with("tok-other-user")
        api_token_repo.revoke.assert_not_awaited()
        audit_repo.create.assert_not_awaited()
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_tokens(
        self, authenticated_app: FastAPI, auth_client: AsyncClient
    ):
        expires_at = datetime(2026, 5, 31, 1, 2, 3, tzinfo=timezone.utc)
        last_used_at = datetime(2026, 5, 31, 4, 5, 6, tzinfo=timezone.utc)
        created_at = datetime(2026, 5, 31, 7, 8, 9, tzinfo=timezone.utc)
        fake_token = _make_orm_token(
            token_id="tok1",
            name="ci",
            scopes=["run.read", "audit.read"],
            expires_at=expires_at,
            last_used_at=last_used_at,
            is_revoked=True,
            created_at=created_at,
        )
        api_token_repo = AsyncMock()
        api_token_repo.list_by_user.return_value = ([fake_token], 1)

        _, session_cm = _session_mock()

        with patch(
            "qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo
        ):
            _setup_overrides(
                authenticated_app, session_factory=_make_session_factory(session_cm)
            )
            resp = await auth_client.get("/api/v1/auth/tokens?page=2&per_page=1")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "data": [
                {
                    "token_id": "tok1",
                    "name": "ci",
                    "scopes": ["run.read", "audit.read"],
                    "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
                    "last_used_at": last_used_at.isoformat().replace("+00:00", "Z"),
                    "is_revoked": True,
                    "created_at": created_at.isoformat().replace("+00:00", "Z"),
                }
            ],
            "page": 2,
            "per_page": 1,
            "total": 1,
        }
        api_token_repo.list_by_user.assert_awaited_once_with(
            UUID("a0000000-0000-0000-0000-000000000001"),
            offset=1,
            limit=1,
        )


# --- JWT Blacklist / Logout tests ---


def _make_redis_mock(revoked_jtis: set[str] | None = None):
    """Return an AsyncMock redis that tracks revoked jtis in memory."""
    store: dict[str, str] = {}
    if revoked_jtis:
        for jti in revoked_jtis:
            store[f"jwt:revoked:{jti}"] = "1"

    redis = AsyncMock()

    async def _set(key, value, ex=None):
        store[key] = value

    async def _exists(key):
        return 1 if key in store else 0

    redis.set = AsyncMock(side_effect=_set)
    redis.exists = AsyncMock(side_effect=_exists)
    return redis, store


class TestRefreshRevokesOldToken:
    @pytest.mark.asyncio
    async def test_refresh_revokes_old_refresh_token(
        self, app: FastAPI, client: AsyncClient
    ):
        """After refresh, the old refresh token jti must be in the blacklist."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_id = uuid4()
        old_refresh_token = jwt_svc.create_refresh_token(str(user_id))

        import jwt as _jwt

        old_payload = _jwt.decode(
            old_refresh_token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        old_jti = old_payload["jti"]

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user
        audit_repo = _make_audit_repo_mock()

        session, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                old_refresh_token,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "access_token": body["access_token"],
            "token_type": "bearer",
        }
        assert "refresh_token" not in body
        assert resp.cookies["refresh_token"] != old_refresh_token
        _assert_refresh_cookie_security(resp, max_age=settings.jwt_refresh_token_ttl)
        _assert_access_token_claims(
            jwt_svc,
            body["access_token"],
            user_id=user.id,
            role="developer",
            tenant_id=user.tenant_id,
            is_platform_admin=False,
        )
        _assert_refresh_cookie_claims(resp, jwt_svc, user_id=user.id)
        new_refresh_payload = jwt_svc.decode_token(resp.cookies["refresh_token"])
        new_jti = new_refresh_payload["jti"]
        assert new_jti != old_jti
        user_repo.get_by_id.assert_awaited_once_with(user_id)
        redis_mock.exists.assert_awaited_once_with(f"jwt:revoked:{old_jti}")
        redis_mock.set.assert_awaited_once()
        assert redis_mock.set.await_args.args == (f"jwt:revoked:{old_jti}", "1")
        assert (
            0 < redis_mock.set.await_args.kwargs["ex"] <= settings.jwt_refresh_token_ttl
        )
        assert f"jwt:revoked:{old_jti}" in store
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.await_args.kwargs
        assert audit_kwargs["action"] == "auth.refresh"
        assert audit_kwargs["resource_type"] == "auth"
        assert audit_kwargs["tenant_id"] == user.tenant_id
        assert audit_kwargs["user_id"] == user.id
        assert audit_kwargs["before_state"] == {"old_jti": old_jti}
        assert audit_kwargs["after_state"] == {"new_jti": new_jti}
        assert old_refresh_token not in repr(audit_kwargs)
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refresh_with_revoked_token_returns_401(
        self, app: FastAPI, client: AsyncClient
    ):
        """A refresh token already in the blacklist must not be rotated again."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_id = uuid4()
        refresh_token = jwt_svc.create_refresh_token(str(user_id))

        import jwt as _jwt

        payload = _jwt.decode(refresh_token, settings.jwt_secret, algorithms=["HS256"])
        old_jti = payload["jti"]
        store[f"jwt:revoked:{old_jti}"] = "1"

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user
        audit_repo = _make_audit_repo_mock()

        session, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                refresh_token,
                headers={"user-agent": "refresh-revoked-audit-test"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Refresh token has been revoked"}
        _assert_refresh_cookie_cleared(resp)
        user_repo.get_by_id.assert_not_awaited()
        _assert_refresh_failed_audit(
            audit_repo,
            reason="revoked_refresh_token",
            user_agent="refresh-revoked-audit-test",
            forbidden_values=[refresh_token],
        )
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()


class TestLogoutRevokesTokens:
    @pytest.mark.asyncio
    async def test_logout_revokes_access_token(self, app: FastAPI, client: AsyncClient):
        """logout must add the access token jti to the blacklist."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        access_token = jwt_svc.create_access_token("user-1", "developer", "tenant-1")

        import jwt as _jwt

        payload = _jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        access_jti = payload["jti"]

        _, session_cm = _session_mock()

        _setup_overrides(
            app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc
        )
        resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert resp.status_code == 204
        assert resp.content == b""
        assert f"jwt:revoked:{access_jti}" in store
        redis_mock.set.assert_awaited_once()
        assert redis_mock.set.await_args.args == (f"jwt:revoked:{access_jti}", "1")
        assert (
            0 < redis_mock.set.await_args.kwargs["ex"] <= settings.jwt_access_token_ttl
        )
        _assert_refresh_cookie_cleared(resp)

    @pytest.mark.asyncio
    async def test_logout_revokes_refresh_token(
        self, app: FastAPI, client: AsyncClient
    ):
        """logout must add the refresh token jti to the blacklist."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        refresh_token = jwt_svc.create_refresh_token("user-1")

        import jwt as _jwt

        payload = _jwt.decode(refresh_token, settings.jwt_secret, algorithms=["HS256"])
        refresh_jti = payload["jti"]

        _, session_cm = _session_mock()

        _setup_overrides(
            app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc
        )
        resp = await _post_with_refresh_cookie(
            client,
            "/api/v1/auth/logout",
            refresh_token,
        )

        assert resp.status_code == 204
        assert resp.content == b""
        assert f"jwt:revoked:{refresh_jti}" in store
        redis_mock.set.assert_awaited_once()
        assert redis_mock.set.await_args.args == (f"jwt:revoked:{refresh_jti}", "1")
        assert (
            0 < redis_mock.set.await_args.kwargs["ex"] <= settings.jwt_refresh_token_ttl
        )
        _assert_refresh_cookie_cleared(resp)

    @pytest.mark.asyncio
    async def test_logout_revokes_both_tokens(self, app: FastAPI, client: AsyncClient):
        """logout with both tokens present must revoke both jtis."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        access_token = jwt_svc.create_access_token("user-1", "developer", "tenant-1")
        refresh_token = jwt_svc.create_refresh_token("user-1")

        import jwt as _jwt

        a_payload = _jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        r_payload = _jwt.decode(
            refresh_token, settings.jwt_secret, algorithms=["HS256"]
        )

        _, session_cm = _session_mock()

        _setup_overrides(
            app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc
        )
        resp = await _post_with_refresh_cookie(
            client,
            "/api/v1/auth/logout",
            refresh_token,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert resp.status_code == 204
        assert resp.content == b""
        assert f"jwt:revoked:{a_payload['jti']}" in store
        assert f"jwt:revoked:{r_payload['jti']}" in store
        revoke_calls = redis_mock.set.await_args_list
        assert [call.args for call in revoke_calls] == [
            (f"jwt:revoked:{a_payload['jti']}", "1"),
            (f"jwt:revoked:{r_payload['jti']}", "1"),
        ]
        assert 0 < revoke_calls[0].kwargs["ex"] <= settings.jwt_access_token_ttl
        assert 0 < revoke_calls[1].kwargs["ex"] <= settings.jwt_refresh_token_ttl
        _assert_refresh_cookie_cleared(resp)

    @pytest.mark.asyncio
    async def test_logout_no_tokens_still_returns_204(
        self, app: FastAPI, client: AsyncClient
    ):
        """logout with no tokens at all must still succeed (idempotent)."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)

        _, session_cm = _session_mock()

        _setup_overrides(
            app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc
        )
        resp = await client.post("/api/v1/auth/logout")

        assert resp.status_code == 204
        assert resp.content == b""
        assert store == {}
        redis_mock.set.assert_not_awaited()
        _assert_refresh_cookie_cleared(resp)


class TestRevokedTokenMiddleware:
    """Verify that a blacklisted access token is rejected by get_current_user."""

    @pytest.mark.asyncio
    async def test_revoked_access_token_returns_401(self):
        """A token whose jti is in the blacklist must be rejected with 'revoked'."""
        import jwt as _jwt
        from fastapi import Depends, FastAPI
        from httpx import ASGITransport, AsyncClient

        from qaplatform.api.auth.middleware import get_current_user

        settings = _settings()
        jwt_svc = JWTService(settings)
        access_token = jwt_svc.create_access_token(
            str(uuid4()),
            "developer",
            str(uuid4()),
        )

        payload = _jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        jti = payload["jti"]

        redis_mock, _ = _make_redis_mock(revoked_jtis={jti})

        container = MagicMock()
        container.settings = settings
        container.redis_client = redis_mock
        container.db_session_factory = MagicMock(
            side_effect=AssertionError("revoked access token must not open DB sessions")
        )

        app = FastAPI()

        @app.get("/protected")
        async def protected(user=Depends(get_current_user)):
            return {"user_id": user.user_id}

        with patch(
            "qaplatform.api.auth.middleware._get_container",
            return_value=container,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/protected",
                    headers={"Authorization": f"Bearer {access_token}"},
                )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Token has been revoked"}
        redis_mock.exists.assert_awaited_once_with(f"jwt:revoked:{jti}")
        container.db_session_factory.assert_not_called()
        assert access_token not in resp.text
        assert jti not in resp.text

    @pytest.mark.asyncio
    async def test_jti_missing_token_passes_through(self):
        """A token without jti (legacy) must not be treated as revoked."""
        import time

        import jwt as _jwt
        from fastapi import Depends, FastAPI
        from httpx import ASGITransport, AsyncClient

        from qaplatform.api.auth.middleware import get_current_user

        settings = _settings()
        # Manually craft a token without jti
        now = int(time.time())
        user_id = str(uuid4())
        payload_no_jti = {
            "sub": user_id,
            "role": "developer",
            "tenant_id": str(uuid4()),
            "is_platform_admin": False,
            "exp": now + 1800,
            "iat": now,
            "type": "access",
        }
        token_no_jti = _jwt.encode(
            payload_no_jti, settings.jwt_secret, algorithm="HS256"
        )

        redis_mock, _ = _make_redis_mock()

        container = MagicMock()
        container.settings = settings
        container.redis_client = redis_mock
        container.db_session_factory = None

        app = FastAPI()

        @app.get("/protected")
        async def protected(user=Depends(get_current_user)):
            return {"user_id": user.user_id}

        with patch(
            "qaplatform.api.auth.middleware._get_container",
            return_value=container,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/protected",
                    headers={"Authorization": f"Bearer {token_no_jti}"},
                )

        assert resp.status_code == 200
        assert resp.json() == {"user_id": user_id}
        redis_mock.exists.assert_not_awaited()
        assert token_no_jti not in resp.text


# ---------------------------------------------------------------------------
# P1-8: Audit event tests
# ---------------------------------------------------------------------------


def _make_audit_repo_mock():
    """Return an AsyncMock AuditEventRepository with a tracked .create()."""
    repo = AsyncMock()
    repo.create = AsyncMock(return_value=MagicMock())
    return repo


def _assert_logout_audit(
    audit_repo,
    *,
    tenant_id: UUID | None,
    user_id: UUID | None,
    had_access_token: bool,
    user_agent: str,
    forbidden_values: list[str] | None = None,
) -> None:
    audit_repo.create.assert_awaited_once()
    call_kwargs = audit_repo.create.await_args.kwargs
    assert call_kwargs == {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "action": "auth.logout",
        "resource_type": "auth",
        "resource_id": None,
        "after_state": {"had_access_token": had_access_token},
        "ip_address": "127.0.0.1",
        "user_agent": user_agent,
    }

    rendered = repr(call_kwargs)
    for value in forbidden_values or []:
        assert value not in rendered


def _assert_refresh_failed_audit(
    audit_repo,
    *,
    reason: str,
    user_agent: str,
    forbidden_values: list[str] | None = None,
) -> None:
    audit_repo.create.assert_awaited_once()
    call_kwargs = audit_repo.create.await_args.kwargs
    assert call_kwargs == {
        "tenant_id": None,
        "user_id": None,
        "action": "auth.refresh_failed",
        "resource_type": "auth",
        "resource_id": None,
        "after_state": {"reason": reason},
        "ip_address": "127.0.0.1",
        "user_agent": user_agent,
    }

    rendered = repr(call_kwargs)
    for value in forbidden_values or []:
        assert value not in rendered


class TestAuditLogin:
    @pytest.mark.asyncio
    async def test_login_success_emits_audit(self, app: FastAPI, client: AsyncClient):
        from argon2 import PasswordHasher

        settings = _settings()
        jwt_svc = JWTService(settings)
        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("correct-password"))
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user
        user_repo.update_last_login = AsyncMock()

        audit_repo = _make_audit_repo_mock()
        session, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth._resolve_tenant_id",
                new_callable=AsyncMock,
                return_value=uuid4(),
            ),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/login",
                headers={"user-agent": "auth-audit-test"},
                json={"username": "alice", "password": "correct-password"},
            )

        assert resp.status_code == 200
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.await_args.kwargs
        assert call_kwargs == {
            "tenant_id": user.tenant_id,
            "user_id": user.id,
            "action": "auth.login",
            "resource_type": "auth",
            "resource_id": None,
            "after_state": {"username": user.username},
            "ip_address": "127.0.0.1",
            "user_agent": "auth-audit-test",
        }
        assert "correct-password" not in repr(call_kwargs)
        user_repo.update_last_login.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()


class TestAuditRegister:
    @pytest.mark.asyncio
    async def test_register_success_emits_audit(
        self, app: FastAPI, client: AsyncClient
    ):
        settings = _settings()
        jwt_svc = JWTService(settings)
        audit_repo = _make_audit_repo_mock()
        session, session_cm = _register_session_mock()
        tenant = SimpleNamespace(id=uuid4(), name="bob")
        user = SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant.id,
            username="bob",
            email="bob@example.com",
            role="owner",
            is_platform_admin=False,
        )
        tenant_repo = AsyncMock()
        tenant_repo.get_by_name.return_value = None
        tenant_repo.create.return_value = tenant
        user_repo = AsyncMock()
        user_repo.create.return_value = user

        with (
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
            patch("qaplatform.api.v1.auth.TenantRepository", return_value=tenant_repo),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await client.post(
                "/api/v1/auth/register",
                headers={"user-agent": "register-audit-test"},
                json={
                    "username": "bob",
                    "email": "bob@example.com",
                    "password": "secure-password-1",
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body == {
            "access_token": body["access_token"],
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "username": "bob",
                "email": "bob@example.com",
                "role": "owner",
                "tenant_id": str(tenant.id),
            },
        }
        assert "refresh_token" not in body
        assert "refresh_token" in resp.cookies
        _assert_access_token_claims(
            jwt_svc,
            body["access_token"],
            user_id=str(user.id),
            role="owner",
            tenant_id=str(tenant.id),
            is_platform_admin=False,
        )
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.await_args.kwargs
        assert call_kwargs == {
            "tenant_id": tenant.id,
            "user_id": user.id,
            "action": "auth.register",
            "resource_type": "auth",
            "resource_id": None,
            "after_state": {"username": "bob", "email": "bob@example.com"},
            "ip_address": "127.0.0.1",
            "user_agent": "register-audit-test",
        }
        rendered_audit = repr(call_kwargs)
        assert "secure-password-1" not in rendered_audit
        assert user_repo.create.await_args.kwargs["password_hash"] not in rendered_audit
        tenant_repo.get_by_name.assert_awaited_once_with("bob")
        tenant_repo.create.assert_awaited_once_with(name="bob")
        user_repo.create.assert_awaited_once_with(
            tenant_id=tenant.id,
            username="bob",
            email="bob@example.com",
            password_hash=user_repo.create.await_args.kwargs["password_hash"],
            role="owner",
        )
        session.execute.assert_not_awaited()
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()


class TestAuditLogout:
    @pytest.mark.asyncio
    async def test_logout_emits_audit_without_storing_tokens(
        self,
        app: FastAPI,
        client: AsyncClient,
    ):
        settings = _settings()
        redis_mock, _ = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_uuid = uuid4()
        tenant_uuid = uuid4()
        access_token = jwt_svc.create_access_token(
            str(user_uuid), "developer", str(tenant_uuid)
        )
        refresh_token = jwt_svc.create_refresh_token(str(user_uuid))

        audit_repo = _make_audit_repo_mock()
        session, session_cm = _session_mock()

        with patch(
            "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
        ):
            _setup_overrides(
                app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/logout",
                refresh_token,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "user-agent": "logout-audit-test",
                },
            )

        assert resp.status_code == 204
        assert resp.content == b""
        _assert_refresh_cookie_cleared(resp)
        _assert_logout_audit(
            audit_repo,
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            had_access_token=True,
            user_agent="logout-audit-test",
            forbidden_values=[access_token, refresh_token],
        )
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_logout_without_token_still_emits_audit(
        self, app: FastAPI, client: AsyncClient
    ):
        """Logout with no token still writes an audit record with user_id=None."""
        settings = _settings()
        redis_mock, _ = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)

        audit_repo = _make_audit_repo_mock()
        session, session_cm = _session_mock()

        with patch(
            "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
        ):
            _setup_overrides(
                app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc
            )
            resp = await client.post(
                "/api/v1/auth/logout",
                headers={"user-agent": "logout-empty-audit-test"},
            )

        assert resp.status_code == 204
        assert resp.content == b""
        _assert_logout_audit(
            audit_repo,
            tenant_id=None,
            user_id=None,
            had_access_token=False,
            user_agent="logout-empty-audit-test",
        )
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()


class TestAuditRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success_emits_audit_with_jti(
        self, app: FastAPI, client: AsyncClient
    ):
        settings = _settings()
        redis_mock, _ = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_id = uuid4()
        old_refresh_token = jwt_svc.create_refresh_token(str(user_id))

        import jwt as _jwt

        old_payload = _jwt.decode(
            old_refresh_token, settings.jwt_secret, algorithms=["HS256"]
        )
        old_jti = old_payload["jti"]

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user

        audit_repo = _make_audit_repo_mock()
        session, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch(
                "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
            ),
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                old_refresh_token,
                headers={"user-agent": "refresh-audit-test"},
            )

        assert resp.status_code == 200
        new_refresh_payload = jwt_svc.decode_token(resp.cookies["refresh_token"])
        new_jti = new_refresh_payload["jti"]
        assert new_jti != old_jti
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.await_args.kwargs
        assert call_kwargs == {
            "tenant_id": user.tenant_id,
            "user_id": user.id,
            "action": "auth.refresh",
            "resource_type": "auth",
            "resource_id": None,
            "before_state": {"old_jti": old_jti},
            "after_state": {"new_jti": new_jti},
            "ip_address": "127.0.0.1",
            "user_agent": "refresh-audit-test",
        }
        assert old_refresh_token not in repr(call_kwargs)
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refresh_failed_emits_audit(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        audit_repo = _make_audit_repo_mock()
        session, session_cm = _session_mock()

        with patch(
            "qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo
        ):
            _setup_overrides(
                app,
                session_factory=_make_session_factory(session_cm),
                jwt_svc=jwt_svc,
                settings=settings,
            )
            resp = await _post_with_refresh_cookie(
                client,
                "/api/v1/auth/refresh",
                "not-a-valid-token",
                headers={"user-agent": "refresh-failed-audit-test"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid refresh token"}
        _assert_refresh_cookie_cleared(resp)
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.await_args.kwargs
        assert call_kwargs == {
            "tenant_id": None,
            "user_id": None,
            "action": "auth.refresh_failed",
            "resource_type": "auth",
            "resource_id": None,
            "after_state": {"reason": "invalid_refresh_token"},
            "ip_address": "127.0.0.1",
            "user_agent": "refresh-failed-audit-test",
        }
        assert "not-a-valid-token" not in repr(call_kwargs)
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
