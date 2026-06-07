"""Tests for /projects/{id}/schedules CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _settings():
    from qaplatform.config import Settings

    return Settings(
        database_url="postgresql+asyncpg://qa:qa@localhost:5432/qa",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="test-secret-key-at-least-32-bytes",
        encryption_key="0" * 64,
        debug=True,
        environment="test",
        _env_file=None,
    )


def _make_orm_schedule(project_id, pipeline_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    obj.pipeline_id = pipeline_id
    obj.cron_expr = "0 * * * *"
    obj.timezone = "Asia/Shanghai"
    obj.missed_fire_policy = "skip"
    obj.quiet_windows = []
    obj.enabled = True
    obj.last_run_at = None
    obj.next_run_at = datetime.now(timezone.utc)
    obj.last_error = None
    obj.created_at = datetime.now(timezone.utc)
    return obj


def _json_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _expected_schedule_response(schedule) -> dict:
    return {
        "id": str(schedule.id),
        "project_id": str(schedule.project_id),
        "pipeline_id": str(schedule.pipeline_id),
        "cron_expr": schedule.cron_expr,
        "timezone": schedule.timezone,
        "missed_fire_policy": schedule.missed_fire_policy,
        "quiet_windows": schedule.quiet_windows,
        "enabled": schedule.enabled,
        "last_run_at": _json_datetime(schedule.last_run_at),
        "next_run_at": _json_datetime(schedule.next_run_at),
        "last_error": schedule.last_error,
        "created_at": _json_datetime(schedule.created_at),
    }


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def project_id():
    return uuid.uuid4()


@pytest.fixture
def pipeline_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.tenant_id = tenant_id
    user.role = "owner"
    user.is_platform_admin = False
    return user


@pytest.fixture
def mock_project(project_id, tenant_id):
    obj = MagicMock()
    obj.id = project_id
    obj.tenant_id = tenant_id
    obj.status = "active"
    obj.default_branch = "main"
    return obj


@pytest.fixture
def mock_pipeline(pipeline_id, project_id):
    obj = MagicMock()
    obj.id = pipeline_id
    obj.project_id = project_id
    return obj


@pytest.fixture
def mock_repos(mock_project, mock_pipeline):
    repos = MagicMock()
    repos.project.get_for_tenant = AsyncMock(return_value=mock_project)
    repos.pipeline.get_by_id = AsyncMock(return_value=mock_pipeline)
    repos.schedule = AsyncMock()
    repos.schedule.list_by_project = AsyncMock(return_value=([], 0))
    repos.schedule.get_for_project = AsyncMock(return_value=None)
    repos.schedule.create = AsyncMock()
    repos.schedule.update = AsyncMock()
    repos.schedule.delete = AsyncMock()
    repos.audit = AsyncMock()
    repos.audit.create = AsyncMock()
    return repos


@pytest.fixture
def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    container_mock = MagicMock()
    container_mock.redis_client = None
    container_mock.settings = _settings()
    app = create_app(container=container_mock)
    app.state.container = container_mock

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


async def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _validation_detail_lines(response) -> list[str]:
    body = response.json()
    if "error" in body:
        return body["error"]["details"]
    return [
        f"{' -> '.join(str(part) for part in item.get('loc', []))}: {item.get('msg', '')}"
        for item in body.get("detail", [])
    ]


@pytest.mark.asyncio
async def test_list_schedules_uses_project_access_and_pagination(
    app,
    mock_repos,
    mock_user,
    project_id,
    pipeline_id,
):
    schedule = _make_orm_schedule(project_id, pipeline_id)
    schedule.last_run_at = datetime(2026, 6, 1, 6, 7, 8, tzinfo=timezone.utc)
    schedule.next_run_at = datetime(2026, 6, 1, 7, 8, 9, tzinfo=timezone.utc)
    schedule.created_at = datetime(2026, 6, 1, 8, 9, 10, tzinfo=timezone.utc)
    mock_repos.schedule.list_by_project = AsyncMock(return_value=([schedule], 1))

    async with await _make_client(app) as client:
        resp = await client.get(
            f"/api/v1/projects/{project_id}/schedules?page=2&per_page=1",
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data == {
        "data": [
            {
                "id": str(schedule.id),
                "project_id": str(project_id),
                "pipeline_id": str(pipeline_id),
                "cron_expr": "0 * * * *",
                "timezone": "Asia/Shanghai",
                "missed_fire_policy": "skip",
                "quiet_windows": [],
                "enabled": True,
                "last_run_at": schedule.last_run_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "next_run_at": schedule.next_run_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "last_error": None,
                "created_at": schedule.created_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 2,
        "per_page": 1,
        "total": 1,
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.schedule.list_by_project.assert_awaited_once_with(
        project_id,
        offset=1,
        limit=1,
    )
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_schedule(app, mock_repos, mock_user, project_id, pipeline_id):
    from qaplatform.api.auth.permissions import Action

    next_run_at = datetime(2026, 5, 29, 3, 15, tzinfo=timezone.utc)

    def create_schedule_from_kwargs(**kwargs):
        schedule = _make_orm_schedule(kwargs["project_id"], kwargs["pipeline_id"])
        schedule.cron_expr = kwargs["cron_expr"]
        schedule.timezone = kwargs["timezone"]
        schedule.missed_fire_policy = kwargs["missed_fire_policy"]
        schedule.quiet_windows = kwargs["quiet_windows"]
        schedule.enabled = kwargs["enabled"]
        schedule.next_run_at = kwargs["next_run_at"]
        schedule.last_run_at = None
        schedule.last_error = None
        schedule.created_at = datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc)
        return schedule

    mock_repos.schedule.create = AsyncMock(side_effect=create_schedule_from_kwargs)

    with (
        patch("qaplatform.api.v1.schedules.compute_next_run_at", return_value=next_run_at) as compute_next,
        patch(
            "qaplatform.api.v1.schedules.enforce_project_action",
            new_callable=AsyncMock,
        ) as enforce_project_action,
    ):
        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/projects/{project_id}/schedules",
                json={
                    "pipeline_id": str(pipeline_id),
                    "cron_expr": "15 3 * * *",
                    "timezone": "UTC",
                    "missed_fire_policy": "run_once",
                    "quiet_windows": [{"start": "23:00", "end": "23:30"}],
                    "enabled": False,
                },
            )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    schedule_id = uuid.UUID(data["id"])
    assert data == {
        "id": str(schedule_id),
        "project_id": str(project_id),
        "pipeline_id": str(pipeline_id),
        "cron_expr": "15 3 * * *",
        "timezone": "UTC",
        "missed_fire_policy": "run_once",
        "quiet_windows": [
            {"start": "23:00", "end": "23:30", "timezone": "Asia/Shanghai"}
        ],
        "enabled": False,
        "last_run_at": None,
        "next_run_at": "2026-05-29T03:15:00Z",
        "last_error": None,
        "created_at": "2026-05-31T20:21:22Z",
    }
    compute_next.assert_called_once_with("15 3 * * *", "UTC")
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.SCHEDULE_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.pipeline.get_by_id.assert_awaited_once_with(pipeline_id)
    mock_repos.schedule.create.assert_awaited_once_with(
        project_id=project_id,
        pipeline_id=pipeline_id,
        cron_expr="15 3 * * *",
        timezone="UTC",
        missed_fire_policy="run_once",
        quiet_windows=[
            {"start": "23:00", "end": "23:30", "timezone": "Asia/Shanghai"}
        ],
        enabled=False,
        next_run_at=next_run_at,
    )
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "schedule.create",
        "resource_type": "schedule",
        "resource_id": schedule_id,
        "before_state": None,
        "after_state": data,
    }


@pytest.mark.asyncio
async def test_create_schedule_rejects_pipeline_outside_project_without_side_effects(
    app,
    mock_repos,
    project_id,
    pipeline_id,
):
    mock_repos.pipeline.get_by_id = AsyncMock(
        return_value=MagicMock(id=pipeline_id, project_id=uuid.uuid4()),
    )

    with patch("qaplatform.api.v1.schedules.compute_next_run_at") as compute_next:
        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/projects/{project_id}/schedules",
                json={
                    "pipeline_id": str(pipeline_id),
                    "cron_expr": "0 * * * *",
                },
            )

    assert resp.status_code == 404, resp.text
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Pipeline not found",
            "details": [],
        }
    }
    compute_next.assert_not_called()
    mock_repos.schedule.list_by_project.assert_not_awaited()
    mock_repos.schedule.get_for_project.assert_not_awaited()
    mock_repos.schedule.create.assert_not_awaited()
    mock_repos.schedule.update.assert_not_awaited()
    mock_repos.schedule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_routes_reject_invalid_cron_before_side_effects(
    app,
    mock_repos,
    project_id,
    pipeline_id,
):
    schedule_id = uuid.uuid4()

    with patch("qaplatform.api.v1.schedules.compute_next_run_at") as compute_next:
        async with await _make_client(app) as client:
            create_resp = await client.post(
                f"/api/v1/projects/{project_id}/schedules",
                json={
                    "pipeline_id": str(pipeline_id),
                    "cron_expr": "not cron",
                },
            )
            update_resp = await client.put(
                f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
                json={"cron_expr": "not cron"},
            )

    assert create_resp.status_code == 422, create_resp.text
    assert update_resp.status_code == 422, update_resp.text
    expected_detail = "body -> cron_expr: Value error, invalid cron expression: not cron"
    assert _validation_detail_lines(create_resp) == [expected_detail]
    assert _validation_detail_lines(update_resp) == [expected_detail]
    compute_next.assert_not_called()
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.schedule.list_by_project.assert_not_awaited()
    mock_repos.schedule.get_for_project.assert_not_awaited()
    mock_repos.schedule.create.assert_not_awaited()
    mock_repos.schedule.update.assert_not_awaited()
    mock_repos.schedule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_routes_reject_invalid_timezone_before_side_effects(
    app,
    mock_repos,
    project_id,
    pipeline_id,
):
    schedule_id = uuid.uuid4()

    with patch("qaplatform.api.v1.schedules.compute_next_run_at") as compute_next:
        async with await _make_client(app) as client:
            create_resp = await client.post(
                f"/api/v1/projects/{project_id}/schedules",
                json={
                    "pipeline_id": str(pipeline_id),
                    "cron_expr": "0 * * * *",
                    "timezone": "Mars/Base",
                },
            )
            update_resp = await client.put(
                f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
                json={"timezone": "Mars/Base"},
            )

    assert create_resp.status_code == 422, create_resp.text
    assert update_resp.status_code == 422, update_resp.text
    expected_detail = "body -> timezone: Value error, invalid timezone: Mars/Base"
    assert _validation_detail_lines(create_resp) == [expected_detail]
    assert _validation_detail_lines(update_resp) == [expected_detail]
    compute_next.assert_not_called()
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.schedule.list_by_project.assert_not_awaited()
    mock_repos.schedule.get_for_project.assert_not_awaited()
    mock_repos.schedule.create.assert_not_awaited()
    mock_repos.schedule.update.assert_not_awaited()
    mock_repos.schedule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_routes_reject_invalid_quiet_windows_before_side_effects(
    app,
    mock_repos,
    project_id,
    pipeline_id,
):
    schedule_id = uuid.uuid4()

    with patch("qaplatform.api.v1.schedules.compute_next_run_at") as compute_next:
        async with await _make_client(app) as client:
            create_resp = await client.post(
                f"/api/v1/projects/{project_id}/schedules",
                json={
                    "pipeline_id": str(pipeline_id),
                    "cron_expr": "0 * * * *",
                    "quiet_windows": [
                        {
                            "start": "25:00",
                            "end": "01:00",
                            "timezone": "Asia/Shanghai",
                        }
                    ],
                },
            )
            update_resp = await client.put(
                f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
                json={
                    "quiet_windows": [
                        {
                            "start": "00:00",
                            "end": "01:00",
                            "timezone": "Mars/Base",
                        }
                    ]
                },
            )

    assert create_resp.status_code == 422, create_resp.text
    assert update_resp.status_code == 422, update_resp.text
    assert _validation_detail_lines(create_resp) == [
        "body -> quiet_windows: Value error, quiet_windows[0].start must use HH:MM"
    ]
    assert _validation_detail_lines(update_resp) == [
        "body -> quiet_windows: Value error, invalid timezone: Mars/Base"
    ]
    compute_next.assert_not_called()
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.schedule.list_by_project.assert_not_awaited()
    mock_repos.schedule.get_for_project.assert_not_awaited()
    mock_repos.schedule.create.assert_not_awaited()
    mock_repos.schedule.update.assert_not_awaited()
    mock_repos.schedule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_schedule_not_found_has_no_write_side_effects(
    app,
    mock_repos,
    project_id,
):
    schedule_id = uuid.uuid4()

    with patch("qaplatform.api.v1.schedules.compute_next_run_at") as compute_next:
        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
            )

    assert resp.status_code == 404, resp.text
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Schedule not found",
            "details": [],
        }
    }
    compute_next.assert_not_called()
    mock_repos.schedule.get_for_project.assert_awaited_once_with(schedule_id, project_id)
    mock_repos.schedule.list_by_project.assert_not_awaited()
    mock_repos.schedule.create.assert_not_awaited()
    mock_repos.schedule.update.assert_not_awaited()
    mock_repos.schedule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_item_routes_hide_other_project_schedule_without_side_effects(
    app,
    mock_repos,
    mock_user,
    project_id,
    pipeline_id,
):
    schedule_id = uuid.uuid4()
    mock_repos.schedule.get_for_project = AsyncMock(return_value=None)

    with patch("qaplatform.api.v1.schedules.compute_next_run_at") as compute_next:
        async with await _make_client(app) as client:
            responses = [
                await client.get(
                    f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
                ),
                await client.put(
                    f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
                    json={"enabled": False},
                ),
                await client.delete(
                    f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
                ),
            ]

    for resp in responses:
        assert resp.status_code == 404, resp.text
        assert resp.json() == {
            "error": {
                "code": "NOT_FOUND",
                "message": "Schedule not found",
                "details": [],
            }
        }

    assert mock_repos.project.get_for_tenant.await_args_list == [
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
    ]
    assert mock_repos.schedule.get_for_project.await_args_list == [
        call(schedule_id, project_id),
        call(schedule_id, project_id),
        call(schedule_id, project_id),
    ]
    compute_next.assert_not_called()
    mock_repos.schedule.list_by_project.assert_not_awaited()
    mock_repos.schedule.create.assert_not_awaited()
    mock_repos.schedule.update.assert_not_awaited()
    mock_repos.schedule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_routes_hide_missing_project_without_side_effects(
    app,
    mock_repos,
    mock_user,
    project_id,
    pipeline_id,
):
    mock_repos.project.get_for_tenant = AsyncMock(return_value=None)
    schedule_id = uuid.uuid4()

    with patch("qaplatform.api.v1.schedules.compute_next_run_at") as compute_next:
        async with await _make_client(app) as client:
            responses = [
                await client.get(f"/api/v1/projects/{project_id}/schedules"),
                await client.post(
                    f"/api/v1/projects/{project_id}/schedules",
                    json={
                        "pipeline_id": str(pipeline_id),
                        "cron_expr": "0 * * * *",
                    },
                ),
                await client.get(f"/api/v1/projects/{project_id}/schedules/{schedule_id}"),
                await client.put(
                    f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
                    json={"enabled": False},
                ),
                await client.delete(f"/api/v1/projects/{project_id}/schedules/{schedule_id}"),
            ]

    for resp in responses:
        assert resp.status_code == 404, resp.text
        assert resp.json() == {
            "error": {
                "code": "NOT_FOUND",
                "message": "Project not found",
                "details": [],
            }
        }
        assert str(project_id) not in resp.text
        assert str(schedule_id) not in resp.text
    assert mock_repos.project.get_for_tenant.await_args_list == [
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
    ]
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.schedule.list_by_project.assert_not_awaited()
    mock_repos.schedule.get_for_project.assert_not_awaited()
    mock_repos.schedule.create.assert_not_awaited()
    mock_repos.schedule.update.assert_not_awaited()
    mock_repos.schedule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
    compute_next.assert_not_called()


@pytest.mark.asyncio
async def test_delete_schedule(app, mock_repos, mock_user, project_id, pipeline_id):
    from qaplatform.api.auth.permissions import Action

    schedule = _make_orm_schedule(project_id, pipeline_id)
    schedule.next_run_at = datetime(2026, 5, 31, 21, 22, 23, tzinfo=timezone.utc)
    schedule.created_at = datetime(2026, 5, 31, 22, 23, 24, tzinfo=timezone.utc)
    before_state = _expected_schedule_response(schedule)
    mock_repos.schedule.get_for_project = AsyncMock(return_value=schedule)
    mock_repos.schedule.delete = AsyncMock()

    with patch(
        "qaplatform.api.v1.schedules.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        async with await _make_client(app) as client:
            resp = await client.delete(
                f"/api/v1/projects/{project_id}/schedules/{schedule.id}"
            )

    assert resp.status_code == 204
    assert resp.content == b""
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.SCHEDULE_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.schedule.get_for_project.assert_awaited_once_with(schedule.id, project_id)
    mock_repos.schedule.delete.assert_awaited_once_with(schedule)
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "schedule.delete",
        "resource_type": "schedule",
        "resource_id": schedule.id,
        "before_state": before_state,
        "after_state": None,
    }


@pytest.mark.asyncio
async def test_update_schedule_recomputes_next_run(
    app,
    mock_repos,
    mock_user,
    project_id,
    pipeline_id,
):
    from qaplatform.api.auth.permissions import Action

    schedule = _make_orm_schedule(project_id, pipeline_id)
    schedule.next_run_at = datetime(2026, 5, 31, 23, 24, 25, tzinfo=timezone.utc)
    schedule.created_at = datetime(2026, 6, 1, 1, 2, 3, tzinfo=timezone.utc)
    before_state = _expected_schedule_response(schedule)
    mock_repos.schedule.get_for_project = AsyncMock(return_value=schedule)

    async def update_schedule(instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    mock_repos.schedule.update = AsyncMock(side_effect=update_schedule)
    new_next = datetime(2026, 6, 1, 2, 30, tzinfo=timezone.utc)
    with (
        patch(
            "qaplatform.api.v1.schedules.compute_next_run_at",
            return_value=new_next,
        ) as compute_next,
        patch(
            "qaplatform.api.v1.schedules.enforce_project_action",
            new_callable=AsyncMock,
        ) as enforce_project_action,
    ):
        async with await _make_client(app) as client:
            resp = await client.put(
                f"/api/v1/projects/{project_id}/schedules/{schedule.id}",
                json={"cron_expr": "30 2 * * *"},
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data == _expected_schedule_response(schedule)
    assert schedule.cron_expr == "30 2 * * *"
    compute_next.assert_called_once_with("30 2 * * *", "Asia/Shanghai")
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.SCHEDULE_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.schedule.get_for_project.assert_awaited_once_with(schedule.id, project_id)
    mock_repos.schedule.update.assert_awaited_once_with(
        schedule,
        cron_expr="30 2 * * *",
        next_run_at=new_next,
    )
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "schedule.update",
        "resource_type": "schedule",
        "resource_id": schedule.id,
        "before_state": before_state,
        "after_state": _expected_schedule_response(schedule),
    }
