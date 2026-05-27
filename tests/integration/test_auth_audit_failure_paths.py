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

    plugin_registry = PluginRegistry()
    plugin_registry.register_builtins()
    container.plugin_registry = plugin_registry

    app = create_app(container=container, settings=test_settings)
    app.state.container = container

    yield app

    app.dependency_overrides.clear()
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
        await conn.execute(
            text(
                """
                INSERT INTO app_user
                    (tenant_id, username, email, password_hash, role,
                     is_platform_admin, is_active)
                VALUES
                    (:tid, :uname, :email, :phash, 'member', false, true)
                """
            ),
            {
                "tid": tenant_id,
                "uname": f"audit-user-{sfx}",
                "email": f"audit-user-{sfx}@test.local",
                "phash": ph.hash(password),
            },
        )

    return {
        "username": f"audit-user-{sfx}",
        "password": password,
        "tenant_id": tenant_id,
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
    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "totally-nonexistent-user", "password": "wrong"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    row = await _latest_audit_row(integration_db_engine, "auth.login_failed")
    assert row is not None, "audit.login_failed row must be written"
    assert row.tenant_id is None, "tenant_id must be NULL for unknown-user path"
    assert "invalid_credentials" in str(row.after_state)


@pytest.mark.asyncio
async def test_auth_login_rate_limit_uses_real_redis_token_hash_bucket(
    auth_app,
    auth_client,
):
    """Auth abuse protection uses real Redis and never stores the raw bearer token."""
    token = f"rate-limit-secret-{uuid4().hex}"
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    bucket_key = f"rate_limit:token:{token_hash}:/api/v1/auth/login"
    redis = auth_app.state.container.redis_client
    assert redis is not None
    await redis.delete(bucket_key)

    headers = {"Authorization": f"Bearer {token}"}
    for index in range(5):
        resp = await auth_client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={
                "username": f"rate-limit-missing-{index}-{uuid4().hex}",
                "password": "wrong-password",
            },
        )
        assert resp.status_code == 401, resp.text

    limited = await auth_client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={
            "username": f"rate-limit-missing-final-{uuid4().hex}",
            "password": "wrong-password",
        },
    )
    assert limited.status_code == 429, limited.text
    assert limited.headers["Retry-After"] == str(
        auth_app.state.container.settings.rate_limit_auth_failure_window
    )
    assert limited.json()["error"]["code"] == "TOO_MANY_REQUESTS"

    keys = [
        key
        async for key in redis.scan_iter("rate_limit:token:*:/api/v1/auth/login")
        if token_hash in key
    ]
    assert keys == [bucket_key]
    assert token not in keys[0]
    assert await redis.zcard(bucket_key) == 6


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401_when_audit_write_fails(
    auth_client,
    monkeypatch,
    caplog,
):
    """Audit storage outage must not turn auth failure into a 500."""
    _force_auth_audit_writes_to_fail(monkeypatch)
    caplog.set_level(logging.WARNING, logger="qaplatform.api.v1.auth")

    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "audit-outage-user", "password": "wrong"},
    )

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert "audit_write_failed" in caplog.text


@pytest.mark.asyncio
async def test_login_valid_user_wrong_password_returns_401_with_tenant_id(
    auth_client, integration_db_engine, seeded_user
):
    """Contrast test: known user + wrong password → 401, audit has real tenant_id.

    This verifies the happy-path audit write (tenant resolved) still works
    correctly after the schema change.
    """
    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={
            "username": seeded_user["username"],
            "password": "definitely-wrong",
            "tenant_id": str(seeded_user["tenant_id"]),
        },
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    row = await _latest_audit_row(integration_db_engine, "auth.login_failed")
    assert row is not None, "audit.login_failed row must be written"
    # tenant_id is resolved because the user was found before password check
    assert row.tenant_id is not None, "tenant_id must be set when user is found"
    assert "invalid_credentials" in str(row.after_state)


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

    row = await _latest_audit_row(integration_db_engine, "auth.refresh_failed")
    assert row is not None, "audit.refresh_failed row must be written"
    assert row.tenant_id is None
    assert row.user_id is None


@pytest.mark.asyncio
async def test_refresh_invalid_token_returns_401_when_audit_write_fails(
    auth_client,
    monkeypatch,
    caplog,
):
    """Invalid refresh tokens stay 401 even if failure audit cannot be written."""
    _force_auth_audit_writes_to_fail(monkeypatch)
    caplog.set_level(logging.WARNING, logger="qaplatform.api.v1.auth")
    auth_client.cookies.set(
        "refresh_token",
        "this.is.not.a.valid.jwt",
        path="/api/v1/auth",
    )

    resp = await auth_client.post("/api/v1/auth/refresh")

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert "audit_write_failed" in caplog.text


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

    row = await _latest_audit_row(integration_db_engine, "auth.logout")
    assert row is not None, "audit.logout row must be written"
    assert row.tenant_id is None
    assert row.user_id is None


@pytest.mark.asyncio
async def test_logout_without_authorization_returns_204_when_audit_write_fails(
    auth_client,
    monkeypatch,
    caplog,
):
    """Logout is idempotent and must survive an audit write outage."""
    _force_auth_audit_writes_to_fail(monkeypatch)
    caplog.set_level(logging.WARNING, logger="qaplatform.api.v1.auth")

    resp = await auth_client.post("/api/v1/auth/logout")

    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"
    assert "audit_write_failed" in caplog.text
