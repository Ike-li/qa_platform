"""Tests for /api/v1/admin/status endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def admin_user():
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.role = "platform_admin"
    user.tenant_id = uuid.uuid4()
    user.is_platform_admin = True
    return user


@pytest.fixture
def non_admin_user():
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.role = "member"
    user.tenant_id = uuid.uuid4()
    user.is_platform_admin = False
    return user


def _make_app(user):
    from qaplatform.api.v1.admin import _require_platform_admin
    from qaplatform.main import create_app

    app = create_app(container=MagicMock())

    async def _override_admin():
        return user

    app.dependency_overrides[_require_platform_admin] = _override_admin
    return app


def _mock_session(*scalars):
    """Return a mock session whose execute() returns scalars in order."""
    session = AsyncMock()
    results = []
    for val in scalars:
        r = MagicMock()
        r.scalar = MagicMock(return_value=val)
        results.append(r)
    session.execute = AsyncMock(side_effect=results)

    from qaplatform.api.deps import _get_db_session

    async def _gen():
        yield session

    return session


@pytest.mark.asyncio
async def test_status_returns_expected_shape(admin_user):
    app = _make_app(admin_user)
    session = _mock_session(5, 2, 10, 8)  # queue, flight, total, passed

    from qaplatform.api.deps import _get_db_session

    async def _gen():
        yield session

    app.dependency_overrides[_get_db_session] = _gen

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/status",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["queue_depth"] == 5
    assert body["in_flight"] == 2
    assert body["total_runs_1h"] == 10
    assert body["success_rate_1h"] == 0.8


@pytest.mark.asyncio
async def test_status_zero_runs_returns_100_percent(admin_user):
    app = _make_app(admin_user)
    session = _mock_session(0, 0, 0, 0)

    from qaplatform.api.deps import _get_db_session

    async def _gen():
        yield session

    app.dependency_overrides[_get_db_session] = _gen

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/status",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success_rate_1h"] == 1.0


@pytest.mark.asyncio
async def test_status_non_admin_gets_403(non_admin_user):
    from qaplatform.api.deps import get_current_user
    from qaplatform.main import create_app

    app = create_app(container=MagicMock())

    async def _override_user():
        return non_admin_user

    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/status",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 403
