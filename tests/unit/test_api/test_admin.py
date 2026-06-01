"""Tests for /api/v1/admin/status endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.infra.database.models import RunStatusEnum


_QUEUE_STATUSES = [RunStatusEnum.QUEUED, RunStatusEnum.PREPARING]
_IN_FLIGHT_STATUSES = [RunStatusEnum.RUNNING, RunStatusEnum.COLLECTING]
_TERMINAL_STATUSES = [
    RunStatusEnum.DONE,
    RunStatusEnum.FAILED,
    RunStatusEnum.CANCELLED,
    RunStatusEnum.TIMEOUT,
]
_PASSED_STATUSES = [RunStatusEnum.DONE]


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

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

    async def _override_admin():
        return user

    app.dependency_overrides[_require_platform_admin] = _override_admin
    return app


def _mock_repos(*counts):
    """Return repository bundle mock whose run count methods return in order."""
    repos = MagicMock()
    repos.run.count_by_statuses = AsyncMock(side_effect=counts[:2])
    repos.run.count_finished_since_by_statuses = AsyncMock(side_effect=counts[2:])
    return repos


def _assert_status_query_contract(repos):
    assert [
        await_args.args[0]
        for await_args in repos.run.count_by_statuses.await_args_list
    ] == [_QUEUE_STATUSES, _IN_FLIGHT_STATUSES]
    terminal_call, passed_call = repos.run.count_finished_since_by_statuses.await_args_list
    assert terminal_call.kwargs["statuses"] == _TERMINAL_STATUSES
    assert passed_call.kwargs["statuses"] == _PASSED_STATUSES
    assert terminal_call.kwargs["since"] is passed_call.kwargs["since"]
    assert terminal_call.kwargs["since"].tzinfo is not None


def test_status_documents_non_admin_403(admin_user):
    app = _make_app(admin_user)

    responses = app.openapi()["paths"]["/api/v1/admin/status"]["get"]["responses"]

    schema = responses["403"]["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["type"] == "string"


@pytest.mark.asyncio
async def test_status_returns_expected_shape(admin_user):
    app = _make_app(admin_user)
    repos = _mock_repos(5, 2, 12, 8)  # queue, flight, total terminal, passed

    from qaplatform.api.deps import _get_repos

    async def _repos():
        return repos

    app.dependency_overrides[_get_repos] = _repos

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/status",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "queue_depth": 5,
        "in_flight": 2,
        "success_rate_1h": 0.6667,
        "total_runs_1h": 12,
    }
    _assert_status_query_contract(repos)


@pytest.mark.asyncio
async def test_status_zero_runs_returns_100_percent(admin_user):
    app = _make_app(admin_user)
    repos = _mock_repos(0, 0, 0, 0)

    from qaplatform.api.deps import _get_repos

    async def _repos():
        return repos

    app.dependency_overrides[_get_repos] = _repos

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/status",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "queue_depth": 0,
        "in_flight": 0,
        "success_rate_1h": 1.0,
        "total_runs_1h": 0,
    }
    _assert_status_query_contract(repos)


@pytest.mark.asyncio
async def test_status_non_admin_gets_403(non_admin_user):
    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

    async def _override_user():
        return non_admin_user

    async def _repos_should_not_open():
        raise AssertionError("non-admin status request should not open repositories")

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_repos] = _repos_should_not_open

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/admin/status",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Platform admin required"}
