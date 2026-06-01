from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.domain.models.run import RunStatus


class _RateLimitPipeline:
    def zremrangebyscore(self, *args, **kwargs):
        return self

    def zadd(self, *args, **kwargs):
        return self

    def zcard(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    async def execute(self):
        return [0, 1, 1, True]


@pytest.fixture
def mock_redis():
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    redis.getdel = AsyncMock(return_value=None)
    redis.time = AsyncMock(return_value=(1_700_000_000, 0))
    redis.pipeline = MagicMock(return_value=_RateLimitPipeline())
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


def _assert_run_not_found_response(resp, run_id):
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Run not found",
            "details": [],
        }
    }
    assert str(run_id) not in resp.text


def _parse_sse_events(text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        if not block:
            continue
        event: dict[str, str] = {}
        data_lines: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data":
                data_lines.append(value)
            else:
                event[field] = value
        if data_lines:
            event["data"] = "\n".join(data_lines)
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_logs_sse_streams_log_event_payload(
    client,
    mock_redis,
    mock_run_repo,
    tenant_id,
):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(run_id=run_id, tenant_id=tenant_id)

    stream_key = f"run:{run_id}:logs"
    mock_redis.xread = AsyncMock(
        side_effect=[
            [(stream_key.encode(), [(b"1234-0", {"stream": "stdout", "line": "hello"})])],
            [],
        ]
    )
    mock_redis.hget = AsyncMock(return_value=RunStatus.DONE.value)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/logs?ticket=test-ticket",
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    events = _parse_sse_events(resp.text)
    assert [event["event"] for event in events] == ["log", "done"]
    assert events[0]["id"] == "1234-0"
    assert json.loads(events[0]["data"]) == {"stream": "stdout", "line": "hello"}
    assert "id" not in events[1]
    assert json.loads(events[1]["data"]) == {"status": RunStatus.DONE.value}
    first_xread = mock_redis.xread.await_args_list[0]
    assert first_xread.args[0] == {stream_key: "0"}
    assert first_xread.kwargs == {"count": 100, "block": 5000}


@pytest.mark.asyncio
async def test_events_sse_streams_status_event_payload(
    client,
    mock_redis,
    mock_run_repo,
    tenant_id,
):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(run_id=run_id, tenant_id=tenant_id)

    stream_key = f"run:{run_id}:events"
    mock_redis.xread = AsyncMock(
        side_effect=[
            [
                (
                    stream_key.encode(),
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
    events = _parse_sse_events(resp.text)
    assert [event["event"] for event in events] == ["status_change", "done"]
    assert events[0]["id"] == "5678-0"
    assert json.loads(events[0]["data"]) == {
        "type": "status_change",
        "status": "running",
        "summary": "",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    assert "id" not in events[1]
    assert json.loads(events[1]["data"]) == {"status": RunStatus.DONE.value}
    first_xread = mock_redis.xread.await_args_list[0]
    assert first_xread.args[0] == {stream_key: "0"}
    assert first_xread.kwargs == {"count": 50, "block": 5000}


@pytest.mark.asyncio
async def test_logs_sse_no_ticket_returns_401_without_touching_redis(app, mock_redis):
    from qaplatform.api.v1.sse import _authenticate_sse_ticket

    app.dependency_overrides.pop(_authenticate_sse_ticket, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/runs/{uuid.uuid4()}/logs")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid or expired SSE ticket"}
    mock_redis.getdel.assert_not_awaited()


@pytest.mark.asyncio
async def test_events_sse_no_ticket_returns_401_without_touching_redis(app, mock_redis):
    from qaplatform.api.v1.sse import _authenticate_sse_ticket

    app.dependency_overrides.pop(_authenticate_sse_ticket, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/runs/{uuid.uuid4()}/events")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid or expired SSE ticket"}
    mock_redis.getdel.assert_not_awaited()


# ── P0-A regression: SSE cross-tenant log leak (F-AU-03) ────────────────────


@pytest.mark.asyncio
async def test_stream_logs_cross_tenant_returns_404(
    client, mock_redis, mock_run_repo, tenant_id, other_tenant_id
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
    mock_redis.hget = AsyncMock()

    resp = await client.get(f"/api/v1/runs/{run_id}/logs?ticket=test-ticket")

    _assert_run_not_found_response(resp, run_id)
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    mock_redis.xread.assert_not_awaited()
    mock_redis.hget.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_events_cross_tenant_returns_404(
    client, mock_redis, mock_run_repo, tenant_id, other_tenant_id
):
    """Same cross-tenant guard for the events endpoint."""
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = None
    mock_redis.xread = AsyncMock()
    mock_redis.hget = AsyncMock()

    resp = await client.get(f"/api/v1/runs/{run_id}/events?ticket=test-ticket")

    _assert_run_not_found_response(resp, run_id)
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    mock_redis.xread.assert_not_awaited()
    mock_redis.hget.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_logs_run_not_found_returns_404(
    client, mock_redis, mock_run_repo, tenant_id
):
    """Non-existent run_id must yield 404 just like cross-tenant access."""
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = None
    mock_redis.xread = AsyncMock()
    mock_redis.hget = AsyncMock()

    resp = await client.get(f"/api/v1/runs/{run_id}/logs?ticket=test-ticket")

    _assert_run_not_found_response(resp, run_id)
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    mock_redis.xread.assert_not_awaited()
    mock_redis.hget.assert_not_awaited()


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
    run = _make_run(run_id=run_id, tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run
    mock_redis.xread = AsyncMock()
    mock_redis.hget = AsyncMock()

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
    assert resp.json() == {"detail": "Insufficient permissions"}
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    mock_redis.xread.assert_not_awaited()
    mock_redis.hget.assert_not_awaited()


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
    run = _make_run(run_id=run_id, tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run
    mock_redis.xread = AsyncMock()
    mock_redis.hget = AsyncMock()

    import qaplatform.api.deps as deps_mod
    from unittest.mock import patch

    async def _no_project_role(session, user, project_id):
        return None

    with patch.object(deps_mod, "_resolve_project_role", _no_project_role):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/runs/{run_id}/events?ticket=test-ticket")

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Insufficient permissions"}
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    mock_redis.xread.assert_not_awaited()
    mock_redis.hget.assert_not_awaited()


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
    events = _parse_sse_events(resp.text)
    assert [event["event"] for event in events] == ["log", "done"]
    assert events[0]["id"] == "1234-0"
    assert json.loads(events[0]["data"]) == log_payload
    assert json.loads(events[1]["data"]) == {"status": RunStatus.DONE.value}


@pytest.mark.asyncio
async def test_stream_logs_accepts_last_event_id_query_param(
    client, mock_redis, mock_run_repo, tenant_id
):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(
        run_id=run_id, tenant_id=tenant_id
    )

    stream_key = f"run:{run_id}:logs"
    mock_redis.xread = AsyncMock(
        side_effect=[
            [(stream_key.encode(), [(b"1235-0", {"message": "resumed"})])],
            [],
        ]
    )
    mock_redis.hget = AsyncMock(return_value=RunStatus.DONE.value)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/logs?ticket=test-ticket&last_event_id=1234-0"
    )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    events = _parse_sse_events(resp.text)
    assert [event["event"] for event in events] == ["log", "done"]
    assert events[0]["id"] == "1235-0"
    assert json.loads(events[0]["data"]) == {"message": "resumed"}
    assert "id" not in events[1]
    assert json.loads(events[1]["data"]) == {"status": RunStatus.DONE.value}
    first_xread = mock_redis.xread.await_args_list[0]
    assert first_xread.args[0] == {stream_key: "1234-0"}
    assert first_xread.kwargs == {"count": 100, "block": 5000}


@pytest.mark.asyncio
async def test_stream_events_accepts_last_event_id_query_param(
    client, mock_redis, mock_run_repo, tenant_id
):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_run(
        run_id=run_id, tenant_id=tenant_id
    )

    stream_key = f"run:{run_id}:events"
    mock_redis.xread = AsyncMock(
        side_effect=[
            [
                (
                    stream_key.encode(),
                    [(b"5679-0", {"type": "status_change", "status": "done"})],
                )
            ],
            [],
        ]
    )
    mock_redis.hget = AsyncMock(return_value=RunStatus.DONE.value)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/events?ticket=test-ticket&last_event_id=5678-0"
    )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    events = _parse_sse_events(resp.text)
    assert [event["event"] for event in events] == ["status_change", "done"]
    assert events[0]["id"] == "5679-0"
    assert json.loads(events[0]["data"]) == {
        "type": "status_change",
        "status": "done",
    }
    assert "id" not in events[1]
    assert json.loads(events[1]["data"]) == {"status": RunStatus.DONE.value}
    first_xread = mock_redis.xread.await_args_list[0]
    assert first_xread.args[0] == {stream_key: "5678-0"}
    assert first_xread.kwargs == {"count": 50, "block": 5000}


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
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "role": role,
            "tenant_id": str(tenant_id),
            "scopes": None,
        }
    )

    mock_redis = MagicMock()
    mock_redis.getdel = AsyncMock(side_effect=[payload, None])
    mock_redis.get = AsyncMock(return_value=payload)
    mock_redis.delete = AsyncMock()

    # Mock request with redis client
    mock_request = MagicMock()
    mock_request.app.state.container.redis_client = mock_redis

    # Run two concurrent calls with the same ticket
    results = await asyncio.gather(
        _authenticate_sse_ticket(mock_request, ticket),
        _authenticate_sse_ticket(mock_request, ticket),
        return_exceptions=True,
    )

    def _project_result(result):
        if isinstance(result, UserIdentity):
            return (
                "success",
                str(result.user_id),
                result.role,
                str(result.tenant_id),
                result.scopes,
            )
        if isinstance(result, HTTPException):
            return ("failure", result.status_code, result.detail)
        return ("unexpected", type(result).__name__, repr(result))

    assert sorted(_project_result(result) for result in results) == [
        ("failure", 401, "Invalid or expired SSE ticket"),
        ("success", str(user_id), role, str(tenant_id), None),
    ]

    failure = next(result for result in results if isinstance(result, HTTPException))
    assert failure.detail == "Invalid or expired SSE ticket"
    assert ticket not in failure.detail
    assert ticket not in repr(results)

    # Verify getdel was called exactly twice (not get+delete separately)
    assert [call.args for call in mock_redis.getdel.await_args_list] == [
        (f"sse_ticket:{ticket}",),
        (f"sse_ticket:{ticket}",),
    ]
    mock_redis.get.assert_not_awaited()
    mock_redis.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticate_sse_ticket_rejects_legacy_payload_without_scopes():
    from fastapi import HTTPException

    from qaplatform.api.v1.sse import _authenticate_sse_ticket

    mock_redis = MagicMock()
    mock_redis.getdel = AsyncMock(
        return_value=f"{uuid.uuid4()}:owner:{uuid.uuid4()}"
    )
    mock_redis.get = AsyncMock()
    mock_redis.delete = AsyncMock()

    mock_request = MagicMock()
    mock_request.app.state.container.redis_client = mock_redis

    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_sse_ticket(mock_request, "legacy-ticket")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired SSE ticket"
    mock_redis.getdel.assert_awaited_once_with("sse_ticket:legacy-ticket")
    mock_redis.get.assert_not_awaited()
    mock_redis.delete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "secret_marker"),
    [
        ("not-json-secret-fragment", "secret-fragment"),
        (json.dumps(["not", "a", "json", "object", "secret-list"]), "secret-list"),
        (
            json.dumps(
                {
                    "user_id": str(uuid.uuid4()),
                    "role": "owner",
                    "scopes": None,
                    "secret": "missing-tenant-secret",
                }
            ),
            "missing-tenant-secret",
        ),
        (
            json.dumps(
                {
                    "user_id": str(uuid.uuid4()),
                    "role": ["owner"],
                    "tenant_id": str(uuid.uuid4()),
                    "scopes": None,
                    "secret": "bad-role-secret",
                }
            ),
            "bad-role-secret",
        ),
        (
            json.dumps(
                {
                    "user_id": str(uuid.uuid4()),
                    "role": "owner",
                    "tenant_id": str(uuid.uuid4()),
                    "scopes": "run.read",
                    "secret": "bad-scopes-secret",
                }
            ),
            "bad-scopes-secret",
        ),
        (
            json.dumps(
                {
                    "user_id": str(uuid.uuid4()),
                    "role": "owner",
                    "tenant_id": str(uuid.uuid4()),
                    "scopes": ["run.read", 123],
                    "secret": "bad-scope-item-secret",
                }
            ),
            "bad-scope-item-secret",
        ),
        (
            json.dumps(
                {
                    "user_id": "not-a-uuid-secret-user",
                    "role": "owner",
                    "tenant_id": str(uuid.uuid4()),
                    "scopes": None,
                }
            ),
            "not-a-uuid-secret-user",
        ),
        (
            json.dumps(
                {
                    "user_id": str(uuid.uuid4()),
                    "role": "owner",
                    "tenant_id": "not-a-uuid-secret-tenant",
                    "scopes": None,
                }
            ),
            "not-a-uuid-secret-tenant",
        ),
    ],
)
async def test_authenticate_sse_ticket_rejects_malformed_payload_without_leaking(
    payload,
    secret_marker,
):
    from fastapi import HTTPException

    from qaplatform.api.v1.sse import _authenticate_sse_ticket

    mock_redis = MagicMock()
    mock_redis.getdel = AsyncMock(return_value=payload)
    mock_redis.get = AsyncMock()
    mock_redis.delete = AsyncMock()

    mock_request = MagicMock()
    mock_request.app.state.container.redis_client = mock_redis

    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_sse_ticket(mock_request, "malformed-ticket")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired SSE ticket"
    serialized_error = repr(exc_info.value.detail) + repr(exc_info.value.args)
    assert secret_marker not in serialized_error
    assert "malformed-ticket" not in serialized_error
    mock_redis.getdel.assert_awaited_once_with("sse_ticket:malformed-ticket")
    mock_redis.get.assert_not_awaited()
    mock_redis.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticate_sse_ticket_preserves_api_token_scopes():
    from fastapi import HTTPException

    from qaplatform.api.v1.sse import _authenticate_sse_ticket

    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "role": "owner",
            "tenant_id": str(tenant_id),
            "scopes": ["run.read"],
        }
    )
    mock_redis = MagicMock()
    mock_redis.getdel = AsyncMock(return_value=payload)

    mock_request = MagicMock()
    mock_request.app.state.container.redis_client = mock_redis

    identity = await _authenticate_sse_ticket(mock_request, "scoped-ticket")

    assert identity.user_id == user_id
    assert identity.role == "owner"
    assert identity.tenant_id == tenant_id
    assert identity.scopes == ["run.read"]

    mock_redis.getdel.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_sse_ticket(mock_request, "scoped-ticket")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired SSE ticket"
    assert [call.args for call in mock_redis.getdel.await_args_list] == [
        ("sse_ticket:scoped-ticket",),
        ("sse_ticket:scoped-ticket",),
    ]
