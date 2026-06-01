from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.api.auth.permissions import Action


def _assert_cutoff_window(
    cutoff: datetime,
    *,
    days: int,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    assert cutoff.tzinfo is timezone.utc
    assert started_at - timedelta(days=days) <= cutoff <= finished_at - timedelta(
        days=days
    )


def _assert_run_read_enforced(
    enforce_project_action: AsyncMock,
    *,
    user: object,
    project_id: uuid.UUID,
) -> None:
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.kwargs == {}
    _session, enforced_user, enforced_project_id, enforced_action = (
        enforce_project_action.await_args.args
    )
    assert enforced_user is user
    assert enforced_project_id == project_id
    assert enforced_action is Action.RUN_READ


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def project_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    user.is_platform_admin = True
    return user


@pytest.fixture
def mock_repos():
    repos = MagicMock()
    repos.project = AsyncMock()
    repos.run = AsyncMock()
    repos.run.list_trend_points = AsyncMock(return_value=([], 0))
    repos.test_result = AsyncMock()
    repos.test_result.list_flaky_tests = AsyncMock(return_value=([], 0))
    repos.test_result.list_test_history = AsyncMock(return_value=([], 0))
    return repos


@pytest.fixture
async def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    async def _override_session():
        yield AsyncMock()

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_db_session] = _override_session
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_trends_success_uses_project_rbac_and_repository_pagination(
    client,
    mock_repos,
    mock_user,
    project_id,
):
    from qaplatform.api.v1 import analytics

    project = SimpleNamespace(id=project_id)
    row = SimpleNamespace(
        date=date(2026, 5, 30),
        total_runs=4,
        passed_runs=3,
        failed_runs=1,
    )
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.run.list_trend_points.return_value = ([row], 1)
    enforce_project_action = AsyncMock()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            analytics,
            "enforce_project_action",
            enforce_project_action,
        )
        request_started = datetime.now(timezone.utc)
        resp = await client.get(
            f"/api/v1/projects/{project_id}/analytics/trends",
            params={"days": "7", "offset": "5", "limit": "25"},
            headers={"Authorization": "Bearer fake"},
        )
        request_finished = datetime.now(timezone.utc)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "data": [
            {
                "date": "2026-05-30",
                "total_runs": 4,
                "passed_runs": 3,
                "failed_runs": 1,
                "pass_rate": 0.75,
            }
        ],
        "pagination": {"offset": 5, "limit": 25, "total": 1},
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    _assert_run_read_enforced(
        enforce_project_action,
        user=mock_user,
        project_id=project_id,
    )
    mock_repos.run.list_trend_points.assert_awaited_once()
    assert mock_repos.run.list_trend_points.await_args.args == ()
    trend_kwargs = dict(mock_repos.run.list_trend_points.await_args.kwargs)
    trend_cutoff = trend_kwargs.pop("cutoff")
    assert trend_kwargs == {"project_id": project_id, "offset": 5, "limit": 25}
    _assert_cutoff_window(
        trend_cutoff,
        days=7,
        started_at=request_started,
        finished_at=request_finished,
    )


@pytest.mark.asyncio
async def test_flaky_success_uses_project_rbac_and_repository_filters(
    client,
    mock_repos,
    mock_user,
    project_id,
):
    from qaplatform.api.v1 import analytics

    project = SimpleNamespace(id=project_id)
    row = SimpleNamespace(
        suite="checkout",
        name="test_payment",
        total_runs=8,
        passed_count=6,
        failed_count=2,
    )
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.test_result.list_flaky_tests.return_value = ([row], 1)
    enforce_project_action = AsyncMock()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            analytics,
            "enforce_project_action",
            enforce_project_action,
        )
        request_started = datetime.now(timezone.utc)
        resp = await client.get(
            f"/api/v1/projects/{project_id}/analytics/flaky",
            params={"days": "21", "min_runs": "4", "offset": "10", "limit": "20"},
            headers={"Authorization": "Bearer fake"},
        )
        request_finished = datetime.now(timezone.utc)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "data": [
            {
                "suite": "checkout",
                "name": "test_payment",
                "total_runs": 8,
                "passed_count": 6,
                "failed_count": 2,
                "flaky_rate": 0.25,
            }
        ],
        "pagination": {"offset": 10, "limit": 20, "total": 1},
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    _assert_run_read_enforced(
        enforce_project_action,
        user=mock_user,
        project_id=project_id,
    )
    mock_repos.test_result.list_flaky_tests.assert_awaited_once()
    assert mock_repos.test_result.list_flaky_tests.await_args.args == ()
    flaky_kwargs = dict(mock_repos.test_result.list_flaky_tests.await_args.kwargs)
    flaky_cutoff = flaky_kwargs.pop("cutoff")
    assert flaky_kwargs == {
        "project_id": project_id,
        "min_runs": 4,
        "offset": 10,
        "limit": 20,
    }
    _assert_cutoff_window(
        flaky_cutoff,
        days=21,
        started_at=request_started,
        finished_at=request_finished,
    )


@pytest.mark.asyncio
async def test_test_history_success_uses_project_rbac_and_repository_filters(
    client,
    mock_repos,
    mock_user,
    project_id,
):
    from qaplatform.api.v1 import analytics

    run_id = uuid.uuid4()
    project = SimpleNamespace(id=project_id)
    row = SimpleNamespace(
        run_id=run_id,
        run_created_at=datetime(2026, 5, 30, 8, 15, tzinfo=timezone.utc),
        run_status="done",
        status="failed",
        duration_ms=1234,
        error_message="assertion failed",
        git_ref="main",
    )
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.test_result.list_test_history.return_value = ([row], 1)
    enforce_project_action = AsyncMock()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            analytics,
            "enforce_project_action",
            enforce_project_action,
        )
        request_started = datetime.now(timezone.utc)
        resp = await client.get(
            f"/api/v1/projects/{project_id}/analytics/test-history",
            params={
                "suite": "checkout",
                "name": "test_payment",
                "days": "14",
                "offset": "20",
                "limit": "10",
            },
            headers={"Authorization": "Bearer fake"},
        )
        request_finished = datetime.now(timezone.utc)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "data": [
            {
                "run_id": str(run_id),
                "run_created_at": "2026-05-30T08:15:00Z",
                "run_status": "done",
                "status": "failed",
                "duration_ms": 1234,
                "error_message": "assertion failed",
                "git_ref": "main",
            }
        ],
        "pagination": {"offset": 20, "limit": 10, "total": 1},
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    _assert_run_read_enforced(
        enforce_project_action,
        user=mock_user,
        project_id=project_id,
    )
    mock_repos.test_result.list_test_history.assert_awaited_once()
    assert mock_repos.test_result.list_test_history.await_args.args == ()
    list_kwargs = dict(mock_repos.test_result.list_test_history.await_args.kwargs)
    history_cutoff = list_kwargs.pop("cutoff")
    assert list_kwargs == {
        "project_id": project_id,
        "suite": "checkout",
        "name": "test_payment",
        "offset": 20,
        "limit": 10,
    }
    _assert_cutoff_window(
        history_cutoff,
        days=14,
        started_at=request_started,
        finished_at=request_finished,
    )


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"suite": "   ", "name": "test_checkout"}, "Invalid analytics suite: empty"),
        ({"suite": "checkout", "name": "   "}, "Invalid analytics name: empty"),
    ],
)
@pytest.mark.asyncio
async def test_test_history_rejects_blank_text_filters_without_repo_lookup(
    client,
    mock_repos,
    project_id,
    params,
    message,
):
    resp = await client.get(
        f"/api/v1/projects/{project_id}/analytics/test-history",
        params=params,
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": message,
            "details": [],
        }
    }
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.test_result.list_test_history.assert_not_awaited()


def test_test_history_422_uses_error_response_schema(app):
    responses = app.openapi()["paths"][
        "/api/v1/projects/{project_id}/analytics/test-history"
    ]["get"]["responses"]
    schema = responses["422"]["content"]["application/json"]["schema"]

    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
