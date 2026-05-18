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
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def other_tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    return user


@pytest.fixture
def mock_run_repo():
    return AsyncMock()


@pytest.fixture
def mock_repos(mock_run_repo):
    repos = MagicMock()
    repos.run = mock_run_repo
    return repos


@pytest.fixture
async def app(mock_redis, mock_user, mock_repos):
    from qaplatform.api.deps import (
        UserIdentity,
        _get_db_session,
        _get_repos,
    )
    from qaplatform.api.v1.sse import _authenticate_sse_ticket
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = mock_redis
    app = create_app(container=container)

    async def _override_ticket():
        return UserIdentity(
            user_id=mock_user.user_id,
            role=mock_user.role,
            tenant_id=mock_user.tenant_id,
        )

    async def _override_repos():
        return mock_repos

    async def _override_session():
        # tests don't touch the session; enforce_project_action is patched
        # via tenant role short-circuit (platform_admin / OWNER bypass).
        yield MagicMock()

    app.dependency_overrides[_authenticate_sse_ticket] = _override_ticket
    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[_get_db_session] = _override_session
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _make_run(*, run_id, tenant_id, project_id=None):
    run = MagicMock()
    run.id = run_id
    run.tenant_id = tenant_id
    run.project_id = project_id or uuid.uuid4()
    return run


@pytest.mark.asyncio
async def test_logs_sse_endpoint_exists(client, mock_redis, mock_run_repo, tenant_id):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(run_id=run_id, tenant_id=tenant_id)

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
async def test_events_sse_endpoint_exists(client, mock_redis, mock_run_repo, tenant_id):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(run_id=run_id, tenant_id=tenant_id)

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


# ── P0-A regression: SSE cross-tenant log leak (F-AU-03) ────────────────────


@pytest.mark.asyncio
async def test_stream_logs_cross_tenant_returns_404(
    client, mock_redis, mock_run_repo, other_tenant_id
):
    """A user holding a valid ticket for tenant_A must not be able to
    subscribe to a run owned by tenant_B by tampering the path run_id.

    Expected: HTTP 404 ("Run not found"), and redis.xread is never called
    (i.e. the request is rejected before entering the stream loop).
    """
    run_id = uuid.uuid4()
    # run lives in a *different* tenant than the authenticated user
    # — get_for_tenant filters in SQL, so it surfaces as None.
    mock_run_repo.get_for_tenant.return_value = None
    mock_redis.xread = AsyncMock()

    resp = await client.get(f"/api/v1/runs/{run_id}/logs?ticket=test-ticket")

    assert resp.status_code == 404
    body = resp.json()
    message = body.get("detail") or body.get("error", {}).get("message", "")
    assert message == "Run not found"
    mock_redis.xread.assert_not_called()


@pytest.mark.asyncio
async def test_stream_events_cross_tenant_returns_404(
    client, mock_redis, mock_run_repo, other_tenant_id
):
    """Same cross-tenant guard for the events endpoint."""
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = None
    mock_redis.xread = AsyncMock()

    resp = await client.get(f"/api/v1/runs/{run_id}/events?ticket=test-ticket")

    assert resp.status_code == 404
    body = resp.json()
    message = body.get("detail") or body.get("error", {}).get("message", "")
    assert message == "Run not found"
    mock_redis.xread.assert_not_called()


@pytest.mark.asyncio
async def test_stream_logs_run_not_found_returns_404(
    client, mock_redis, mock_run_repo
):
    """Non-existent run_id must yield 404 just like cross-tenant access."""
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = None
    mock_redis.xread = AsyncMock()

    resp = await client.get(f"/api/v1/runs/{run_id}/logs?ticket=test-ticket")

    assert resp.status_code == 404
    mock_redis.xread.assert_not_called()


@pytest.mark.asyncio
async def test_stream_logs_same_tenant_no_project_perm_returns_403(
    mock_redis, mock_repos, mock_run_repo, tenant_id
):
    """User belongs to the same tenant but has no ProjectMember row for
    the project owning the run. enforce_project_action must reject with 403.
    """
    from qaplatform.api.deps import (
        UserIdentity,
        _get_db_session,
        _get_repos,
    )
    from qaplatform.api.v1.sse import _authenticate_sse_ticket
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = mock_redis
    app = create_app(container=container)

    # Use a non-admin role so enforce_project_action falls through to
    # ProjectMember lookup.
    member_user_id = uuid.uuid4()

    async def _override_ticket():
        return UserIdentity(
            user_id=member_user_id,
            role="member",
            tenant_id=tenant_id,
        )

    async def _override_repos():
        return mock_repos

    async def _override_session():
        yield MagicMock()

    app.dependency_overrides[_authenticate_sse_ticket] = _override_ticket
    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[_get_db_session] = _override_session

    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(
        run_id=run_id, tenant_id=tenant_id
    )
    mock_redis.xread = AsyncMock()

    # Patch the project-role resolver to simulate "no membership".
    import qaplatform.api.deps as deps_mod
    from unittest.mock import patch

    async def _no_project_role(session, user, project_id):
        return None

    with patch.object(deps_mod, "_resolve_project_role", _no_project_role):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/runs/{run_id}/logs?ticket=test-ticket")

    assert resp.status_code == 403
    mock_redis.xread.assert_not_called()


@pytest.mark.asyncio
async def test_stream_events_same_tenant_no_project_perm_returns_403(
    mock_redis, mock_repos, mock_run_repo, tenant_id
):
    """Mirror of the logs 403 case for the events endpoint."""
    from qaplatform.api.deps import (
        UserIdentity,
        _get_db_session,
        _get_repos,
    )
    from qaplatform.api.v1.sse import _authenticate_sse_ticket
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = mock_redis
    app = create_app(container=container)

    member_user_id = uuid.uuid4()

    async def _override_ticket():
        return UserIdentity(
            user_id=member_user_id,
            role="member",
            tenant_id=tenant_id,
        )

    async def _override_repos():
        return mock_repos

    async def _override_session():
        yield MagicMock()

    app.dependency_overrides[_authenticate_sse_ticket] = _override_ticket
    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[_get_db_session] = _override_session

    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(
        run_id=run_id, tenant_id=tenant_id
    )
    mock_redis.xread = AsyncMock()

    import qaplatform.api.deps as deps_mod
    from unittest.mock import patch

    async def _no_project_role(session, user, project_id):
        return None

    with patch.object(deps_mod, "_resolve_project_role", _no_project_role):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/runs/{run_id}/events?ticket=test-ticket")

    assert resp.status_code == 403
    mock_redis.xread.assert_not_called()


@pytest.mark.asyncio
async def test_stream_logs_same_project_returns_200_event_stream(
    client, mock_redis, mock_run_repo, tenant_id
):
    """Happy path: user authorised for the run's project sees the stream."""
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(
        run_id=run_id, tenant_id=tenant_id
    )

    log_payload = {"level": "info", "message": "expected-log-line"}
    mock_redis.xread = AsyncMock(
        side_effect=[
            [(f"run:{run_id}:logs".encode(), [(b"1234-0", log_payload)])],
            [],
        ]
    )
    mock_redis.hget = AsyncMock(return_value=RunStatus.DONE.value)

    resp = await client.get(f"/api/v1/runs/{run_id}/logs?ticket=test-ticket")

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert "expected-log-line" in resp.text


@pytest.mark.asyncio
async def test_authenticate_sse_ticket_consumes_atomically():
    """Two concurrent calls with the same ticket must yield exactly one success
    and one failure — the getdel operation must be atomic.
    
    This test verifies that _authenticate_sse_ticket uses redis.getdel (atomic)
    and not the racy get+delete pattern.
    """
    import asyncio
    from qaplatform.api.v1.sse import _authenticate_sse_ticket
    from qaplatform.api.deps import UserIdentity
    from fastapi import HTTPException
    
    ticket = "test-ticket-atomic"
    user_id = uuid.uuid4()
    role = "platform_admin"
    tenant_id = uuid.uuid4()
    payload = f"{user_id}:{role}:{tenant_id}"
    
    # Mock redis with getdel that returns payload on first call, None on second
    call_count = 0
    
    async def mock_getdel(key):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return payload
        return None
    
    mock_redis = AsyncMock()
    mock_redis.getdel = mock_getdel
    
    # Mock request with redis client
    mock_request = MagicMock()
    mock_request.app.state.container.redis_client = mock_redis
    
    # Run two concurrent calls with the same ticket
    results = await asyncio.gather(
        _authenticate_sse_ticket(mock_request, ticket),
        _authenticate_sse_ticket(mock_request, ticket),
        return_exceptions=True,
    )
    
    # Verify exactly one success and one failure
    successes = [r for r in results if isinstance(r, UserIdentity)]
    failures = [r for r in results if isinstance(r, HTTPException)]
    
    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
    assert len(failures) == 1, f"Expected 1 failure, got {len(failures)}"
    
    # Verify the success has correct identity
    success = successes[0]
    assert success.user_id == user_id
    assert success.role == role
    assert success.tenant_id == tenant_id
    
    # Verify the failure is 401
    failure = failures[0]
    assert failure.status_code == 401
    
    # Verify getdel was called exactly twice (not get+delete separately)
    assert call_count == 2
    mock_redis.get.assert_not_called()
    mock_redis.delete.assert_not_called()
