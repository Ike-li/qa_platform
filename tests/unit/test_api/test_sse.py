from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.domain.models.run import RunStatus


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.user_id = str(uuid.uuid4())
    user.role = "platform_admin"
    user.tenant_id = uuid.uuid4()
    return user


@pytest.fixture
async def app(mock_redis, mock_user):
    from qaplatform.api.v1.sse import _authenticate_sse_ticket
    from qaplatform.api.deps import UserIdentity
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = mock_redis
    app = create_app(container=container)

    async def _override_ticket():
        return UserIdentity(
            user_id=uuid.UUID(mock_user.user_id),
            role=mock_user.role,
            tenant_id=mock_user.tenant_id,
        )

    app.dependency_overrides[_authenticate_sse_ticket] = _override_ticket
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_logs_sse_endpoint_exists(client, mock_redis):
    run_id = uuid.uuid4()

    mock_redis.xread = AsyncMock(
        side_effect=[
            [(f"run:{run_id}:logs".encode(), [(b"1234-0", {"level": "info", "message": "hello"})])],
            [],
        ]
    )
    mock_redis.hget = AsyncMock(return_value=RunStatus.DONE.value)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/logs?ticket=test-ticket",
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_events_sse_endpoint_exists(client, mock_redis):
    run_id = uuid.uuid4()

    mock_redis.xread = AsyncMock(
        side_effect=[
            [
                (
                    f"run:{run_id}:events".encode(),
                    [(b"5678-0", {"type": "status_change", "status": "running", "summary": "", "timestamp": "2026-01-01T00:00:00Z"})],
                )
            ],
            [],
        ]
    )
    mock_redis.hget = AsyncMock(return_value=RunStatus.DONE.value)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/events?ticket=test-ticket",
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_logs_sse_no_ticket(app):
    from qaplatform.api.v1.sse import _authenticate_sse_ticket

    app.dependency_overrides.pop(_authenticate_sse_ticket, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/runs/{uuid.uuid4()}/logs")
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_events_sse_no_ticket(app):
    from qaplatform.api.v1.sse import _authenticate_sse_ticket

    app.dependency_overrides.pop(_authenticate_sse_ticket, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/runs/{uuid.uuid4()}/events")
    assert resp.status_code in (401, 422)
