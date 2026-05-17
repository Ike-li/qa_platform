from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.middleware import CurrentUser, get_current_user
from qaplatform.api.v1.auth import router


# --- Helpers ---


def _settings(jwt_secret="test-secret-key-for-jwt-32bytes!"):
    s = MagicMock()
    s.jwt_secret = jwt_secret
    s.jwt_access_token_ttl = 1800
    s.jwt_refresh_token_ttl = 604800
    return s


def _session_mock():
    """Return (mock_session, async_context_manager) for patching _new_session."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    @asynccontextmanager
    async def _cm():
        yield mock_session

    return mock_session, _cm()


def _make_orm_user(**overrides):
    user = MagicMock()
    user.id = overrides.get("id", uuid4())
    user.tenant_id = overrides.get("tenant_id", uuid4())
    user.username = overrides.get("username", "alice")
    user.email = overrides.get("email", "alice@example.com")
    user.password_hash = overrides.get("password_hash", "")
    user.role = overrides.get("role", "developer")
    user.is_active = overrides.get("is_active", True)
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


def _session_mock():
    """Create a mock session and its async context manager factory."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def _factory():
        yield session

    return session, _factory()


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


# --- Login tests ---


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient):
        from argon2 import PasswordHasher

        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("correct-password"))
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user
        user_repo.update_last_login = AsyncMock()

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_resolve.return_value = uuid4()
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "correct-password"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" not in data
        assert data["user"]["username"] == "alice"
        assert "refresh_token" in resp.cookies

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient):
        from argon2 import PasswordHasher

        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("correct-password"))
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_resolve.return_value = uuid4()
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "wrong"},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_user_not_found(self, client: AsyncClient):
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = None

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_resolve.return_value = uuid4()
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "x"},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, client: AsyncClient):
        from argon2 import PasswordHasher

        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("pw"), is_active=False)
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_resolve.return_value = uuid4()
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "pw"},
            )

        assert resp.status_code == 401


# --- Register tests ---


def _register_session_mock(existing_tenant=None):
    """Session mock for register: tracks add() and populates IDs on flush()."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    def add(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
    session.add = add  # sync, like real SQLAlchemy

    session.flush = AsyncMock()

    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=existing_tenant)
    session.execute = AsyncMock(return_value=select_result)

    @asynccontextmanager
    async def factory():
        yield session

    return session, factory()


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        _, session_cm = _register_session_mock()
        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with patch("qaplatform.api.v1.auth._get_container", return_value=container):
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
        assert "access_token" in data
        assert data["user"]["username"] == "alice"
        assert data["user"]["email"] == "alice@example.com"
        assert data["user"]["role"] == "owner"
        assert "refresh_token" in resp.cookies

    @pytest.mark.asyncio
    async def test_register_username_conflict(self, client: AsyncClient):
        existing = MagicMock()
        existing.name = "alice"
        _, session_cm = _register_session_mock(existing_tenant=existing)
        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with patch("qaplatform.api.v1.auth._get_container", return_value=container):
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "alice",
                    "email": "alice@example.com",
                    "password": "secure-password-1",
                },
            )

        assert resp.status_code == 409
        assert "already taken" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "username",
        ["ab", "x" * 33, "has space", "with-dash", "umlautü"],
    )
    async def test_register_rejects_invalid_username(self, client: AsyncClient, username):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "email": "alice@example.com",
                "password": "secure-password-1",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_rejects_short_password(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "alice",
                "email": "alice@example.com",
                "password": "short",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_rejects_bad_email(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "alice",
                "email": "not-an-email",
                "password": "secure-password-1",
            },
        )
        assert resp.status_code == 422


# --- Refresh tests ---


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        user_id = uuid4()
        refresh_token = jwt_svc.create_refresh_token(str(user_id))

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = settings
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
        ):
            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": refresh_token},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" not in data
        assert "refresh_token" in resp.cookies

    @pytest.mark.asyncio
    async def test_refresh_missing_cookie(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_rejected(self, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        access_token = jwt_svc.create_access_token("user-1", "viewer", "t1")

        container = MagicMock()
        container.settings = settings

        with patch("qaplatform.api.v1.auth._get_container", return_value=container):
            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": access_token},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_expired_token(self, client: AsyncClient):
        settings = _settings()
        settings.jwt_refresh_token_ttl = 0
        jwt_svc = JWTService(settings)
        import time

        refresh_token = jwt_svc.create_refresh_token("user-1")
        time.sleep(0.01)

        container = MagicMock()
        container.settings = settings

        with patch("qaplatform.api.v1.auth._get_container", return_value=container):
            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": refresh_token},
            )

        assert resp.status_code == 401


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
    async def test_create_token(self, auth_client: AsyncClient):
        fake_record = _make_orm_token(token_id="tok123", name="ci")
        api_token_repo = AsyncMock()
        api_token_repo.create.return_value = fake_record

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo),
        ):
            resp = await auth_client.post(
                "/api/v1/auth/tokens",
                json={"name": "ci", "scopes": ["*"], "expires_days": 90},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["token"].startswith("qap_")
        assert data["name"] == "ci"

    @pytest.mark.asyncio
    async def test_create_token_no_auth(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/tokens",
            json={"name": "ci"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_revoke_token(self, auth_client: AsyncClient):
        fake_token = _make_orm_token(
            token_id="tok123",
            user_id=UUID("a0000000-0000-0000-0000-000000000001"),
        )
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = fake_token
        api_token_repo.revoke = AsyncMock()

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo),
        ):
            resp = await auth_client.delete("/api/v1/auth/tokens/tok123")

        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, auth_client: AsyncClient):
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = None

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo),
        ):
            resp = await auth_client.delete("/api/v1/auth/tokens/nonexistent")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_tokens(self, auth_client: AsyncClient):
        now = datetime.now(timezone.utc)
        fake_token = _make_orm_token(
            token_id="tok1",
            name="ci",
            expires_at=now + timedelta(days=90),
        )
        api_token_repo = AsyncMock()
        api_token_repo.list_by_user.return_value = ([fake_token], 1)

        _, session_cm = _session_mock()

        container = MagicMock()
        container.settings = _settings()
        container.db_session_factory = MagicMock(return_value=session_cm)

        with (
            patch("qaplatform.api.v1.auth._get_container", return_value=container),
            patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo),
        ):
            resp = await auth_client.get("/api/v1/auth/tokens")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["token_id"] == "tok1"
        assert data[0]["name"] == "ci"
