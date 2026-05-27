from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qaplatform.api import deps as auth_deps
from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.middleware import CurrentUser, get_current_user
from qaplatform.api.v1.auth import router


# --- Helpers ---


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


def _setup_overrides(app: FastAPI, *, session_factory=None, jwt_svc=None, settings=None):
    """Install dependency overrides on the app for auth deps."""
    if session_factory is not None:
        app.dependency_overrides[auth_deps.get_session_factory] = lambda: session_factory
    if jwt_svc is not None:
        app.dependency_overrides[auth_deps.get_jwt_service] = lambda: jwt_svc
    if settings is not None:
        app.dependency_overrides[auth_deps.get_settings] = lambda: settings


# --- Login tests ---


class TestLogin:
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

        _, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_resolve.return_value = uuid4()
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
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
    async def test_login_wrong_password(self, app: FastAPI, client: AsyncClient):
        from argon2 import PasswordHasher

        settings = _settings()
        jwt_svc = JWTService(settings)
        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("correct-password"))
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=_make_audit_repo_mock()),
        ):
            mock_resolve.return_value = uuid4()
            _setup_overrides(app, session_factory=_multi_session_factory(), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "wrong"},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_user_not_found(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = None

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=_make_audit_repo_mock()),
        ):
            mock_resolve.return_value = uuid4()
            _setup_overrides(app, session_factory=_multi_session_factory(), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "x"},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, app: FastAPI, client: AsyncClient):
        from argon2 import PasswordHasher

        settings = _settings()
        jwt_svc = JWTService(settings)
        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("pw"), is_active=False)
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock) as mock_resolve,
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=_make_audit_repo_mock()),
        ):
            mock_resolve.return_value = uuid4()
            _setup_overrides(app, session_factory=_multi_session_factory(), jwt_svc=jwt_svc, settings=settings)
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
    async def test_register_success(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        _, session_cm = _register_session_mock()

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
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
    async def test_register_username_conflict(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        existing = MagicMock()
        existing.name = "alice"
        _, session_cm = _register_session_mock(existing_tenant=existing)

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
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
    async def test_register_rejects_invalid_username(self, app: FastAPI, client: AsyncClient, username):
        _setup_overrides(app, session_factory=_make_session_factory(AsyncMock()), jwt_svc=JWTService(_settings()), settings=_settings())
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
    async def test_register_rejects_short_password(self, app: FastAPI, client: AsyncClient):
        _setup_overrides(app, session_factory=_make_session_factory(AsyncMock()), jwt_svc=JWTService(_settings()), settings=_settings())
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
    async def test_register_rejects_bad_email(self, app: FastAPI, client: AsyncClient):
        _setup_overrides(app, session_factory=_make_session_factory(AsyncMock()), jwt_svc=JWTService(_settings()), settings=_settings())
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
    async def test_refresh_success(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        user_id = uuid4()
        refresh_token = jwt_svc.create_refresh_token(str(user_id))

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user

        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
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
    async def test_refresh_missing_cookie(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        _, session_cm = _session_mock()
        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_rejected(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        access_token = jwt_svc.create_access_token("user-1", "viewer", "t1")
        _, session_cm = _session_mock()

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
        resp = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": access_token},
        )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_expired_token(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        settings.jwt_refresh_token_ttl = 0
        jwt_svc = JWTService(settings)
        import time
        _, session_cm = _session_mock()

        refresh_token = jwt_svc.create_refresh_token("user-1")
        time.sleep(0.01)

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
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
    async def test_create_token(self, authenticated_app: FastAPI, auth_client: AsyncClient):
        fake_record = _make_orm_token(token_id="tok123", name="ci")
        api_token_repo = AsyncMock()
        api_token_repo.create.return_value = fake_record

        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo):
            _setup_overrides(authenticated_app, session_factory=_make_session_factory(session_cm))
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
    async def test_revoke_token(self, authenticated_app: FastAPI, auth_client: AsyncClient):
        fake_token = _make_orm_token(
            token_id="tok123",
            user_id=UUID("a0000000-0000-0000-0000-000000000001"),
        )
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = fake_token
        api_token_repo.revoke = AsyncMock()

        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo):
            _setup_overrides(authenticated_app, session_factory=_make_session_factory(session_cm))
            resp = await auth_client.delete("/api/v1/auth/tokens/tok123")

        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, authenticated_app: FastAPI, auth_client: AsyncClient):
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = None

        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo):
            _setup_overrides(authenticated_app, session_factory=_make_session_factory(session_cm))
            resp = await auth_client.delete("/api/v1/auth/tokens/nonexistent")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_tokens(self, authenticated_app: FastAPI, auth_client: AsyncClient):
        now = datetime.now(timezone.utc)
        fake_token = _make_orm_token(
            token_id="tok1",
            name="ci",
            expires_at=now + timedelta(days=90),
        )
        api_token_repo = AsyncMock()
        api_token_repo.list_by_user.return_value = ([fake_token], 1)

        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo):
            _setup_overrides(authenticated_app, session_factory=_make_session_factory(session_cm))
            resp = await auth_client.get("/api/v1/auth/tokens")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["token_id"] == "tok1"
        assert data[0]["name"] == "ci"


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
    async def test_refresh_revokes_old_refresh_token(self, app: FastAPI, client: AsyncClient):
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

        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": old_refresh_token},
            )

        assert resp.status_code == 200
        # Old jti must now be in the blacklist store
        assert f"jwt:revoked:{old_jti}" in store

    @pytest.mark.asyncio
    async def test_refresh_with_revoked_token_returns_401(self, app: FastAPI, client: AsyncClient):
        """After refresh, calling revoke() on the old jti is verified via mock."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_id = uuid4()
        refresh_token = jwt_svc.create_refresh_token(str(user_id))

        import jwt as _jwt
        payload = _jwt.decode(
            refresh_token, settings.jwt_secret, algorithms=["HS256"]
        )
        old_jti = payload["jti"]

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user

        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": refresh_token},
            )

        assert resp.status_code == 200
        # The old refresh token jti must now be blacklisted
        assert f"jwt:revoked:{old_jti}" in store


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

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc)
        resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert resp.status_code == 204
        assert f"jwt:revoked:{access_jti}" in store

    @pytest.mark.asyncio
    async def test_logout_revokes_refresh_token(self, app: FastAPI, client: AsyncClient):
        """logout must add the refresh token jti to the blacklist."""
        settings = _settings()
        redis_mock, store = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        refresh_token = jwt_svc.create_refresh_token("user-1")

        import jwt as _jwt
        payload = _jwt.decode(refresh_token, settings.jwt_secret, algorithms=["HS256"])
        refresh_jti = payload["jti"]

        _, session_cm = _session_mock()

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc)
        resp = await client.post(
            "/api/v1/auth/logout",
            cookies={"refresh_token": refresh_token},
        )

        assert resp.status_code == 204
        assert f"jwt:revoked:{refresh_jti}" in store

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
        r_payload = _jwt.decode(refresh_token, settings.jwt_secret, algorithms=["HS256"])

        _, session_cm = _session_mock()

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc)
        resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            cookies={"refresh_token": refresh_token},
        )

        assert resp.status_code == 204
        assert f"jwt:revoked:{a_payload['jti']}" in store
        assert f"jwt:revoked:{r_payload['jti']}" in store

    @pytest.mark.asyncio
    async def test_logout_no_tokens_still_returns_204(self, app: FastAPI, client: AsyncClient):
        """logout with no tokens at all must still succeed (idempotent)."""
        settings = _settings()
        redis_mock, _ = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)

        _, session_cm = _session_mock()

        _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc)
        resp = await client.post("/api/v1/auth/logout")

        assert resp.status_code == 204


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
        access_token = jwt_svc.create_access_token("user-1", "developer", "tenant-1")

        payload = _jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        jti = payload["jti"]

        # Redis already has this jti blacklisted
        redis_mock, _ = _make_redis_mock(revoked_jtis={jti})

        container = MagicMock()
        container.settings = settings
        container.redis_client = redis_mock

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
        assert "revoked" in resp.json()["detail"].lower()

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
        payload_no_jti = {
            "sub": "user-1",
            "role": "developer",
            "tenant_id": "tenant-1",
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
        assert resp.json()["user_id"] == "user-1"


# ---------------------------------------------------------------------------
# P1-8: Audit event tests
# ---------------------------------------------------------------------------


def _make_audit_repo_mock():
    """Return an AsyncMock AuditEventRepository with a tracked .create()."""
    repo = AsyncMock()
    repo.create = AsyncMock(return_value=MagicMock())
    return repo


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
        _, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock, return_value=uuid4()),
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo),
        ):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "correct-password"},
            )

        assert resp.status_code == 200
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.login"
        assert call_kwargs["resource_type"] == "auth"
        assert call_kwargs["user_id"] == user.id
        assert "ip_address" in call_kwargs

    @pytest.mark.asyncio
    async def test_login_failed_emits_audit(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = None

        audit_repo = _make_audit_repo_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock, return_value=uuid4()),
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo),
        ):
            _setup_overrides(app, session_factory=_multi_session_factory(), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "wrong"},
            )

        assert resp.status_code == 401
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.login_failed"
        assert call_kwargs["user_id"] is None
        assert call_kwargs["after_state"]["reason"] == "invalid_credentials"

    @pytest.mark.asyncio
    async def test_login_failed_wrong_password_emits_audit(self, app: FastAPI, client: AsyncClient):
        from argon2 import PasswordHasher

        settings = _settings()
        jwt_svc = JWTService(settings)
        ph = PasswordHasher()
        user = _make_orm_user(password_hash=ph.hash("correct-password"))
        user_repo = AsyncMock()
        user_repo.get_by_username.return_value = user

        audit_repo = _make_audit_repo_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth._resolve_tenant_id", new_callable=AsyncMock, return_value=uuid4()),
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo),
        ):
            _setup_overrides(app, session_factory=_multi_session_factory(), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "wrong-password"},
            )

        assert resp.status_code == 401
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.login_failed"
        assert call_kwargs["after_state"]["reason"] == "invalid_credentials"


class TestAuditRegister:
    @pytest.mark.asyncio
    async def test_register_success_emits_audit(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        audit_repo = _make_audit_repo_mock()
        _, session_cm = _register_session_mock()

        with patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "bob",
                    "email": "bob@example.com",
                    "password": "secure-password-1",
                },
            )

        assert resp.status_code == 201
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.register"
        assert call_kwargs["resource_type"] == "auth"
        assert call_kwargs["after_state"]["username"] == "bob"
        assert call_kwargs["after_state"]["email"] == "bob@example.com"


class TestAuditLogout:
    @pytest.mark.asyncio
    async def test_logout_emits_audit(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        redis_mock, _ = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_uuid = uuid4()
        tenant_uuid = uuid4()
        access_token = jwt_svc.create_access_token(
            str(user_uuid), "developer", str(tenant_uuid)
        )

        audit_repo = _make_audit_repo_mock()
        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc)
            resp = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        assert resp.status_code == 204
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.logout"
        assert call_kwargs["resource_type"] == "auth"
        assert call_kwargs["user_id"] == user_uuid

    @pytest.mark.asyncio
    async def test_logout_without_token_still_emits_audit(self, app: FastAPI, client: AsyncClient):
        """Logout with no token still writes an audit record with user_id=None."""
        settings = _settings()
        redis_mock, _ = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)

        audit_repo = _make_audit_repo_mock()
        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc)
            resp = await client.post("/api/v1/auth/logout")

        assert resp.status_code == 204
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.logout"
        assert call_kwargs["user_id"] is None


class TestAuditRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success_emits_audit_with_jti(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        redis_mock, _ = _make_redis_mock()
        jwt_svc = JWTService(settings, redis=redis_mock)
        user_id = uuid4()
        old_refresh_token = jwt_svc.create_refresh_token(str(user_id))

        import jwt as _jwt
        old_payload = _jwt.decode(old_refresh_token, settings.jwt_secret, algorithms=["HS256"])
        old_jti = old_payload["jti"]

        user = _make_orm_user(id=user_id)
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = user

        audit_repo = _make_audit_repo_mock()
        _, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.UserRepository", return_value=user_repo),
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo),
        ):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": old_refresh_token},
            )

        assert resp.status_code == 200
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.refresh"
        assert call_kwargs["before_state"]["old_jti"] == old_jti
        assert call_kwargs["user_id"] == user.id

    @pytest.mark.asyncio
    async def test_refresh_failed_emits_audit(self, app: FastAPI, client: AsyncClient):
        settings = _settings()
        jwt_svc = JWTService(settings)
        audit_repo = _make_audit_repo_mock()
        _, session_cm = _session_mock()

        with patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo):
            _setup_overrides(app, session_factory=_make_session_factory(session_cm), jwt_svc=jwt_svc, settings=settings)
            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": "not-a-valid-token"},
            )

        assert resp.status_code == 401
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.refresh_failed"
        assert call_kwargs["user_id"] is None


class TestAuditApiTokens:
    @pytest.mark.asyncio
    async def test_create_token_emits_audit(self, authenticated_app: FastAPI, auth_client: AsyncClient):
        fake_record = _make_orm_token(token_id="tok123", name="ci")
        api_token_repo = AsyncMock()
        api_token_repo.create.return_value = fake_record

        audit_repo = _make_audit_repo_mock()
        _, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo),
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo),
        ):
            _setup_overrides(authenticated_app, session_factory=_make_session_factory(session_cm))
            resp = await auth_client.post(
                "/api/v1/auth/tokens",
                json={"name": "ci", "scopes": ["*"], "expires_days": 90},
            )

        assert resp.status_code == 201
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.api_token_create"
        assert call_kwargs["after_state"]["name"] == "ci"
        assert call_kwargs["user_id"] == UUID("a0000000-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_revoke_token_emits_audit(self, authenticated_app: FastAPI, auth_client: AsyncClient):
        fake_token = _make_orm_token(
            token_id="tok123",
            user_id=UUID("a0000000-0000-0000-0000-000000000001"),
            name="ci",
        )
        api_token_repo = AsyncMock()
        api_token_repo.get_by_token_id.return_value = fake_token
        api_token_repo.revoke = AsyncMock()

        audit_repo = _make_audit_repo_mock()
        _, session_cm = _session_mock()

        with (
            patch("qaplatform.api.v1.auth.ApiTokenRepository", return_value=api_token_repo),
            patch("qaplatform.api.v1.auth.AuditEventRepository", return_value=audit_repo),
        ):
            _setup_overrides(authenticated_app, session_factory=_make_session_factory(session_cm))
            resp = await auth_client.delete("/api/v1/auth/tokens/tok123")

        assert resp.status_code == 204
        audit_repo.create.assert_awaited_once()
        call_kwargs = audit_repo.create.call_args.kwargs
        assert call_kwargs["action"] == "auth.api_token_revoke"
        assert call_kwargs["before_state"]["name"] == "ci"
        assert call_kwargs["user_id"] == UUID("a0000000-0000-0000-0000-000000000001")
