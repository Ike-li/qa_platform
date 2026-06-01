"""P1-8 regression tests: auth failure paths must write audit rows with
NULL tenant_id and still return the correct HTTP status (401/204).

Before the fix, audit.event.tenant_id was NOT NULL, so passing None caused
PG to raise IntegrityError, which the global 500 handler caught — turning
every 401/204 into a 500.  These tests exercise the real PG schema (via
alembic upgrade head in integration_db_schema) so the NOT NULL constraint
is present or absent exactly as production sees it.

Fixtures used
-------------
* ``integration_db_schema`` — runs alembic upgrade head once per session.
* ``integration_db_engine``  — async engine scoped to the test function.
* ``auth_app`` / ``auth_client`` — bare FastAPI app WITHOUT the
  get_current_user override so real auth logic runs end-to-end.
* ``seeded_user`` — a real AppUser row with a known password for the
  "valid username, wrong password" contrast test.
"""
from __future__ import annotations

import hashlib
import logging
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


# --------------------------------------------------------------------------- #
# Fixtures: bare app (no auth override) + seeded user
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def auth_app(test_settings, integration_db_schema, seed_run):
    """FastAPI app wired to testcontainers PG/Redis, no dependency overrides.

    Depends on ``seed_run`` so at least one tenant row exists in the DB —
    ``_resolve_tenant_id`` does a ``SELECT tenant LIMIT 1`` fallback when no
    tenant_id is supplied in the request body, and raises 500 if the table is
    empty.  Auth endpoints run with real JWT + password verification so failure
    paths are exercised exactly as production does.
    """
    from qaplatform.api import create_app
    from qaplatform.dependencies import init_container
    from qaplatform.plugins.registry import PluginRegistry

    container = init_container(test_settings)
    await container.init_db()
    await container.init_redis()
    if container.redis_client is not None:
        await _delete_redis_keys(container.redis_client, "rate_limit:*")

    plugin_registry = PluginRegistry()
    plugin_registry.register_builtins()
    container.plugin_registry = plugin_registry

    app = create_app(container=container, settings=test_settings)
    app.state.container = container

    yield app

    app.dependency_overrides.clear()
    if container.redis_client is not None:
        await _delete_redis_keys(container.redis_client, "rate_limit:*")
    await container.close()


@pytest_asyncio.fixture
async def auth_client(auth_app) -> AsyncClient:
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def seeded_user(integration_db_engine):
    """Insert a real AppUser with a known password into the test DB.

    Returns a dict with ``username``, ``password``, and ``tenant_id``.
    Used by the contrast test that verifies audit is written with a real
    tenant_id when the user *is* found but the password is wrong.
    """
    from argon2 import PasswordHasher
    from uuid import uuid4
    ph = PasswordHasher()
    password = "correct-horse-battery"
    sfx = uuid4().hex[:8]
    username = f"audit_user_{sfx}"

    async with integration_db_engine.begin() as conn:
        # Insert tenant
        tenant_row = await conn.execute(
            text(
                "INSERT INTO tenant (name) VALUES (:name) RETURNING id"
            ),
            {"name": f"audit-test-tenant-{sfx}"},
        )
        tenant_id = tenant_row.fetchone()[0]

        # Insert user
        user_row = await conn.execute(
            text(
                """
                INSERT INTO app_user
                    (tenant_id, username, email, password_hash, role,
                     is_platform_admin, is_active)
                VALUES
                    (:tid, :uname, :email, :phash, 'member', false, true)
                RETURNING id
                """
            ),
            {
                "tid": tenant_id,
                "uname": username,
                "email": f"{username}@test.local",
                "phash": ph.hash(password),
            },
        )
        user_id = user_row.fetchone()[0]

    return {
        "username": username,
        "password": password,
        "tenant_id": tenant_id,
        "user_id": user_id,
    }


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #


async def _latest_audit_row(engine, action: str):
    """Return the most recent audit.event row for the given action, or None."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT action, tenant_id, user_id, after_state "
                "FROM audit.event "
                "WHERE action = :action "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"action": action},
        )
        return result.fetchone()


async def _delete_redis_keys(redis, pattern: str) -> None:
    keys = [key async for key in redis.scan_iter(pattern)]
    if keys:
        await redis.delete(*keys)


async def _audit_count(engine, action: str) -> int:
    """Count audit.event rows for one action."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT count(*) FROM audit.event WHERE action = :action"),
            {"action": action},
        )
        return result.scalar_one()


async def _audit_count_for_user(engine, action: str, user_id: str) -> int:
    """Count audit.event rows for one authenticated user and action."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) "
                "FROM audit.event "
                "WHERE action = :action AND user_id = :user_id"
            ),
            {"action": action, "user_id": user_id},
        )
        return result.scalar_one()


async def _register_auth_user(auth_client, prefix: str) -> dict:
    suffix = uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    password = "correct-horse-battery"

    resp = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _force_auth_audit_writes_to_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject an audit repository outage without replacing auth/DB/Redis wiring."""
    from qaplatform.api.v1 import auth as auth_module

    async def _raise_audit_outage(self, *args, **kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(
        auth_module.AuditEventRepository,
        "create",
        _raise_audit_outage,
    )


def _assert_auth_audit_warning(caplog, action: str) -> None:
    records = [
        record
        for record in caplog.records
        if record.name == "qaplatform.api.v1.auth"
        and record.levelno == logging.WARNING
        and getattr(record, "action", None) == action
    ]
    assert [
        {
            "message": record.getMessage(),
            "exc_type": type(record.exc_info[1]) if record.exc_info else None,
            "exc_message": str(record.exc_info[1]) if record.exc_info else None,
        }
        for record in records
    ] == [
        {
            "message": "audit_write_failed",
            "exc_type": RuntimeError,
            "exc_message": "audit store unavailable",
        }
    ]


def _assert_rate_limited_response(response, retry_after: int) -> None:
    assert response.status_code == 429, response.text
    assert response.headers["Retry-After"] == str(retry_after)
    assert response.json() == {
        "error": {
            "code": "TOO_MANY_REQUESTS",
            "message": "Rate limit exceeded. Please try again later.",
        }
    }


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401_not_500(
    auth_client, integration_db_engine
):
    """P1-8 regression: login with unknown username must return 401, not 500.

    Before the fix, audit_repo.create(tenant_id=None) raised IntegrityError
    (NOT NULL violation) which the global handler turned into 500.
    """
    username = "totally_nonexistent_user"
    password = "wrong"
    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": "Invalid credentials"}

    row = await _latest_audit_row(integration_db_engine, "auth.login_failed")
    assert row is not None, "audit.login_failed row must be written"
    assert row.action == "auth.login_failed"
    assert row.tenant_id is None, "tenant_id must be NULL for unknown-user path"
    assert row.user_id is None
    assert row.after_state == {
        "reason": "invalid_credentials",
        "username": username,
    }
    assert password not in repr(row.after_state)


@pytest.mark.asyncio
async def test_auth_login_rate_limit_uses_real_redis_token_hash_bucket(
    auth_app,
    auth_client,
    integration_db_engine,
):
    """Auth abuse protection uses real Redis and never stores the raw bearer token."""
    token = f"rate-limit-secret-{uuid4().hex}"
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    bucket_key = f"rate_limit:token:{token_hash}:/api/v1/auth/login"
    redis = auth_app.state.container.redis_client
    assert redis is not None
    await redis.delete(bucket_key)

    before_count = await _audit_count(integration_db_engine, "auth.login_failed")
    headers = {"Authorization": f"Bearer {token}"}
    for index in range(5):
        resp = await auth_client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={
                "username": f"rl_missing_{index}_{uuid4().hex[:8]}",
                "password": "wrong-password",
            },
        )
        assert resp.status_code == 401, resp.text

    limited = await auth_client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={
            "username": f"rl_missing_final_{uuid4().hex[:8]}",
            "password": "wrong-password",
        },
    )
    _assert_rate_limited_response(
        limited,
        auth_app.state.container.settings.rate_limit_auth_failure_window,
    )

    keys = [
        key
        async for key in redis.scan_iter("rate_limit:token:*:/api/v1/auth/login")
        if token_hash in key
    ]
    assert keys == [bucket_key]
    assert token not in keys[0]
    assert await redis.zcard(bucket_key) == 6

    after_count = await _audit_count(integration_db_engine, "auth.login_failed")
    assert after_count - before_count == 5


@pytest.mark.asyncio
async def test_auth_register_rate_limit_uses_real_redis_ip_bucket_and_audit_count(
    auth_app,
    auth_client,
    integration_db_engine,
):
    """Self-service registration strict limit uses real Redis and audit rows."""
    redis = auth_app.state.container.redis_client
    assert redis is not None
    await _delete_redis_keys(redis, "rate_limit:ip:*:/api/v1/auth/register")

    before_count = await _audit_count(integration_db_engine, "auth.register")
    prefix = f"register_limit_{uuid4().hex[:8]}"
    password = "correct-horse-battery"
    for index in range(5):
        username = f"{prefix}_{index}"
        resp = await auth_client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": password,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["access_token"]

    limited_username = f"{prefix}_final"
    limited = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": limited_username,
            "email": f"{limited_username}@example.com",
            "password": password,
        },
    )
    _assert_rate_limited_response(
        limited,
        auth_app.state.container.settings.rate_limit_auth_failure_window,
    )

    keys = [
        key async for key in redis.scan_iter("rate_limit:ip:*:/api/v1/auth/register")
    ]
    (bucket_key,) = keys
    assert prefix not in bucket_key
    assert password not in bucket_key
    assert await redis.zcard(bucket_key) == 6

    after_count = await _audit_count(integration_db_engine, "auth.register")
    assert after_count - before_count == 5


def _refresh_cookie(auth_client) -> str:
    cookie = auth_client.cookies.get("refresh_token")
    assert cookie
    return cookie


def _assert_refresh_cookie_clear_header(response) -> None:
    clear_cookie = next(
        (
            header
            for header in response.headers.get_list("set-cookie")
            if header.startswith("refresh_token=")
        ),
        None,
    )
    assert clear_cookie is not None
    clear_cookie = clear_cookie.lower()
    assert "max-age=0" in clear_cookie
    assert "path=/api/v1/auth" in clear_cookie
    assert "httponly" in clear_cookie
    assert "secure" in clear_cookie
    assert "samesite=strict" in clear_cookie


@pytest.mark.asyncio
async def test_auth_refresh_rate_limit_uses_real_redis_ip_bucket_and_audit_count(
    auth_app,
    auth_client,
    integration_db_engine,
):
    """Refresh strict limit uses real secure cookie rotation, Redis, and audit rows."""
    redis = auth_app.state.container.redis_client
    assert redis is not None
    registered = await _register_auth_user(auth_client, prefix="refresh_limit")
    user_id = registered["user"]["id"]
    await _delete_redis_keys(redis, "rate_limit:ip:*:/api/v1/auth/refresh")

    before_count = await _audit_count_for_user(
        integration_db_engine,
        "auth.refresh",
        user_id,
    )
    refresh_tokens = [_refresh_cookie(auth_client)]
    for _ in range(5):
        refresh_token = _refresh_cookie(auth_client)
        assert refresh_token == refresh_tokens[-1]
        resp = await auth_client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token={refresh_token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]
        refresh_tokens.append(_refresh_cookie(auth_client))

    (
        initial_refresh_token,
        first_rotated_token,
        second_rotated_token,
        third_rotated_token,
        fourth_rotated_token,
        fifth_rotated_token,
    ) = refresh_tokens
    assert sorted(refresh_tokens) == sorted(
        {
            initial_refresh_token,
            first_rotated_token,
            second_rotated_token,
            third_rotated_token,
            fourth_rotated_token,
            fifth_rotated_token,
        }
    )
    limited_refresh_token = _refresh_cookie(auth_client)
    limited = await auth_client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={limited_refresh_token}"},
    )
    _assert_rate_limited_response(
        limited,
        auth_app.state.container.settings.rate_limit_auth_failure_window,
    )
    assert _refresh_cookie(auth_client) == limited_refresh_token

    keys = [
        key async for key in redis.scan_iter("rate_limit:ip:*:/api/v1/auth/refresh")
    ]
    (bucket_key,) = keys
    for token in refresh_tokens:
        assert token not in bucket_key
    assert await redis.zcard(bucket_key) == 6

    after_count = await _audit_count_for_user(
        integration_db_engine,
        "auth.refresh",
        user_id,
    )
    assert after_count - before_count == 5


@pytest.mark.asyncio
async def test_auth_api_token_create_rate_limit_uses_real_redis_token_bucket(
    auth_app,
    auth_client,
    integration_db_engine,
):
    """API token creation strict limit uses real JWT auth, Redis, and audit rows."""
    redis = auth_app.state.container.redis_client
    assert redis is not None
    registered = await _register_auth_user(auth_client, prefix="api_token_limit")
    access_token = registered["access_token"]
    user_id = registered["user"]["id"]
    token_hash = hashlib.sha256(access_token.encode()).hexdigest()[:16]
    bucket_key = f"rate_limit:token:{token_hash}:/api/v1/auth/tokens"
    await redis.delete(bucket_key)

    before_count = await _audit_count_for_user(
        integration_db_engine,
        "auth.api_token_create",
        user_id,
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    for index in range(5):
        resp = await auth_client.post(
            "/api/v1/auth/tokens",
            headers=headers,
            json={
                "name": f"limited-token-{index}",
                "scopes": ["project.read"],
                "expires_days": 7,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["token"]

    limited = await auth_client.post(
        "/api/v1/auth/tokens",
        headers=headers,
        json={
            "name": "limited-token-final",
            "scopes": ["project.read"],
            "expires_days": 7,
        },
    )
    _assert_rate_limited_response(
        limited,
        auth_app.state.container.settings.rate_limit_auth_failure_window,
    )

    keys = [
        key
        async for key in redis.scan_iter("rate_limit:token:*:/api/v1/auth/tokens")
        if token_hash in key
    ]
    assert keys == [bucket_key]
    assert access_token not in keys[0]
    assert await redis.zcard(bucket_key) == 6

    after_count = await _audit_count_for_user(
        integration_db_engine,
        "auth.api_token_create",
        user_id,
    )
    assert after_count - before_count == 5


@pytest.mark.asyncio
async def test_auth_sse_ticket_rate_limit_uses_real_redis_token_hash_bucket(
    auth_app,
    auth_client,
    integration_db_engine,
):
    """SSE ticket abuse protection uses real JWT auth, Redis, and audit rows."""
    registered = await _register_auth_user(auth_client, prefix="sse_limit")
    access_token = registered["access_token"]
    user_id = registered["user"]["id"]
    token_hash = hashlib.sha256(access_token.encode()).hexdigest()[:16]
    bucket_key = f"rate_limit:token:{token_hash}:/api/v1/auth/sse-ticket"
    redis = auth_app.state.container.redis_client
    assert redis is not None
    await redis.delete(bucket_key)

    before_count = await _audit_count_for_user(
        integration_db_engine,
        "auth.sse_ticket_create",
        user_id,
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    issued_tickets: set[str] = set()
    for _ in range(5):
        resp = await auth_client.post(
            "/api/v1/auth/sse-ticket",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        ticket = resp.json()["ticket"]
        assert ticket
        assert ticket not in issued_tickets
        issued_tickets.add(ticket)

    limited = await auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers=headers,
    )
    _assert_rate_limited_response(
        limited,
        auth_app.state.container.settings.rate_limit_auth_failure_window,
    )

    keys = [
        key
        async for key in redis.scan_iter("rate_limit:token:*:/api/v1/auth/sse-ticket")
        if token_hash in key
    ]
    assert keys == [bucket_key]
    assert access_token not in keys[0]
    assert await redis.zcard(bucket_key) == 6

    after_count = await _audit_count_for_user(
        integration_db_engine,
        "auth.sse_ticket_create",
        user_id,
    )
    assert after_count - before_count == 5


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401_when_audit_write_fails(
    auth_client,
    integration_db_engine,
    monkeypatch,
    caplog,
):
    """Audit storage outage must not turn auth failure into a 500."""
    _force_auth_audit_writes_to_fail(monkeypatch)
    caplog.set_level(logging.WARNING, logger="qaplatform.api.v1.auth")
    before_count = await _audit_count(integration_db_engine, "auth.login_failed")

    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "audit_outage_user", "password": "wrong"},
    )

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": "Invalid credentials"}
    _assert_auth_audit_warning(caplog, "auth.login_failed")
    after_count = await _audit_count(integration_db_engine, "auth.login_failed")
    assert after_count == before_count


@pytest.mark.asyncio
async def test_login_valid_user_wrong_password_returns_401_with_tenant_id(
    auth_client, integration_db_engine, seeded_user
):
    """Contrast test: known user + wrong password → 401, audit has real tenant_id.

    This verifies the happy-path audit write (tenant resolved) still works
    correctly after the schema change.
    """
    wrong_password = "definitely-wrong"
    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={
            "username": seeded_user["username"],
            "password": wrong_password,
            "tenant_id": str(seeded_user["tenant_id"]),
        },
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": "Invalid credentials"}

    row = await _latest_audit_row(integration_db_engine, "auth.login_failed")
    assert row is not None, "audit.login_failed row must be written"
    assert row.tenant_id == seeded_user["tenant_id"]
    assert row.user_id == seeded_user["user_id"]
    assert row.after_state == {
        "reason": "invalid_credentials",
        "username": seeded_user["username"],
    }
    assert seeded_user["password"] not in repr(row.after_state)
    assert wrong_password not in repr(row.after_state)


@pytest.mark.asyncio
async def test_refresh_with_invalid_token_returns_401_not_500(
    auth_client, integration_db_engine
):
    """P1-8 regression: refresh with a garbage token must return 401, not 500."""
    auth_client.cookies.set(
        "refresh_token",
        "this.is.not.a.valid.jwt",
        path="/api/v1/auth",
    )
    resp = await auth_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": "Invalid refresh token"}
    _assert_refresh_cookie_clear_header(resp)

    row = await _latest_audit_row(integration_db_engine, "auth.refresh_failed")
    assert row is not None, "audit.refresh_failed row must be written"
    assert row.tenant_id is None
    assert row.user_id is None


@pytest.mark.asyncio
async def test_refresh_invalid_token_returns_401_when_audit_write_fails(
    auth_client,
    integration_db_engine,
    monkeypatch,
    caplog,
):
    """Invalid refresh tokens stay 401 even if failure audit cannot be written."""
    _force_auth_audit_writes_to_fail(monkeypatch)
    caplog.set_level(logging.WARNING, logger="qaplatform.api.v1.auth")
    before_count = await _audit_count(integration_db_engine, "auth.refresh_failed")
    auth_client.cookies.set(
        "refresh_token",
        "this.is.not.a.valid.jwt",
        path="/api/v1/auth",
    )

    resp = await auth_client.post("/api/v1/auth/refresh")

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": "Invalid refresh token"}
    _assert_refresh_cookie_clear_header(resp)
    _assert_auth_audit_warning(caplog, "auth.refresh_failed")
    after_count = await _audit_count(integration_db_engine, "auth.refresh_failed")
    assert after_count == before_count


@pytest.mark.asyncio
async def test_logout_without_authorization_returns_204_not_500(
    auth_client, integration_db_engine
):
    """P1-8 regression: logout with no tokens must return 204, not 500.

    audit_tenant_id is None when no valid access token is present; before the
    fix this caused IntegrityError → 500.
    """
    resp = await auth_client.post("/api/v1/auth/logout")
    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"
    assert resp.content == b""

    row = await _latest_audit_row(integration_db_engine, "auth.logout")
    assert row is not None, "audit.logout row must be written"
    assert row.tenant_id is None
    assert row.user_id is None


@pytest.mark.asyncio
async def test_logout_without_authorization_returns_204_when_audit_write_fails(
    auth_client,
    integration_db_engine,
    monkeypatch,
    caplog,
):
    """Logout is idempotent and must survive an audit write outage."""
    _force_auth_audit_writes_to_fail(monkeypatch)
    caplog.set_level(logging.WARNING, logger="qaplatform.api.v1.auth")
    before_count = await _audit_count(integration_db_engine, "auth.logout")

    resp = await auth_client.post("/api/v1/auth/logout")

    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"
    assert resp.content == b""
    _assert_auth_audit_warning(caplog, "auth.logout")
    after_count = await _audit_count(integration_db_engine, "auth.logout")
    assert after_count == before_count
