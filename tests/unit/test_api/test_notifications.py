"""Tests for /projects/{id}/notification-rules CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_rule(project_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    obj.name = "Test Rule"
    obj.enabled = True
    obj.conditions = [{"field": "status", "operator": "eq", "value": "failed"}]
    obj.channels = [
        {"type": "webhook", "config": {"url": "https://example.com/secret-token"}}
    ]
    obj.template = "Run {{run_id}} token"
    obj.created_at = datetime.now(timezone.utc)
    return obj


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _expected_rule_response(rule) -> dict:
    return {
        "id": str(rule.id),
        "project_id": str(rule.project_id),
        "name": rule.name,
        "enabled": rule.enabled,
        "conditions": rule.conditions,
        "channels": [
            {
                "type": channel["type"],
                "config": channel["config"],
                "template": channel.get("template"),
            }
            for channel in rule.channels
        ],
        "template": rule.template,
        "created_at": _json_datetime(rule.created_at),
    }


def _expected_rule_audit_state(rule) -> dict:
    return {
        "id": str(rule.id),
        "project_id": str(rule.project_id),
        "name": rule.name,
        "enabled": rule.enabled,
        "conditions": rule.conditions,
        "channels": {
            "redacted": True,
            "count": len(rule.channels),
            "types": [channel.get("type", "unknown") for channel in rule.channels],
        },
        "template": {
            "redacted": True,
            "present": rule.template is not None,
            "length": len(rule.template or ""),
        },
        "created_at": _json_datetime(rule.created_at),
    }


async def _apply_rule_update(instance, **kwargs):
    for key, value in kwargs.items():
        setattr(instance, key, value)
    return instance


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
    return obj


@pytest.fixture
def mock_repos(mock_project):
    repos = MagicMock()
    repos.project.get_for_tenant = AsyncMock(return_value=mock_project)
    repos.notification_rule = AsyncMock()
    repos.notification_rule.list_by_project = AsyncMock(return_value=([], 0))
    repos.notification_rule.get_for_project = AsyncMock(return_value=None)
    repos.notification_rule.create = AsyncMock()
    repos.notification_rule.update = AsyncMock()
    repos.notification_rule.delete = AsyncMock()
    repos.audit = AsyncMock()
    repos.audit.create = AsyncMock()
    return repos


@pytest.fixture
def app(mock_repos, mock_user):
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


async def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _validation_error_projection(errors) -> list[dict]:
    return [
        {
            "type": error["type"],
            "loc": error["loc"],
            "msg": error["msg"],
            "input": error.get("input"),
        }
        for error in errors
    ]


def _assert_notification_validation_short_circuited(mock_repos) -> None:
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.notification_rule.list_by_project.assert_not_awaited()
    mock_repos.notification_rule.get_for_project.assert_not_awaited()
    mock_repos.notification_rule.create.assert_not_awaited()
    mock_repos.notification_rule.update.assert_not_awaited()
    mock_repos.notification_rule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


def _assert_body_validation_error(
    resp,
    *,
    field: str,
    expected_msg: str,
    expected_input,
    expected_type: str = "value_error",
) -> None:
    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": expected_type,
            "loc": ["body", field],
            "msg": expected_msg,
            "input": expected_input,
        }
    ]


@pytest.mark.asyncio
async def test_list_rules_uses_project_access_pagination_and_returns_rules(
    app, mock_repos, project_id, tenant_id
):
    rule = _make_orm_rule(project_id)
    rule.created_at = datetime(2026, 5, 31, 23, 24, 25, tzinfo=timezone.utc)
    mock_repos.notification_rule.list_by_project = AsyncMock(return_value=([rule], 3))

    async with await _make_client(app) as client:
        resp = await client.get(
            f"/api/v1/projects/{project_id}/notification-rules?page=2&per_page=1"
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "data": [
            {
                "id": str(rule.id),
                "project_id": str(project_id),
                "name": "Test Rule",
                "enabled": True,
                "conditions": [
                    {"field": "status", "operator": "eq", "value": "failed"}
                ],
                "channels": [
                    {
                        "type": "webhook",
                        "config": {"url": "https://example.com/secret-token"},
                        "template": None,
                    }
                ],
                "template": "Run {{run_id}} token",
                "created_at": rule.created_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 2,
        "per_page": 1,
        "total": 3,
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.notification_rule.list_by_project.assert_awaited_once_with(
        project_id,
        offset=1,
        limit=1,
    )
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_rules_normalizes_legacy_channel_response_shape(
    app,
    mock_repos,
    project_id,
    tenant_id,
):
    rule = _make_orm_rule(project_id)
    rule.created_at = datetime(2026, 6, 1, 6, 7, 8, tzinfo=timezone.utc)
    rule.channels = [{"type": "webhook", "webhook_url": "https://hooks.example.com/legacy"}]
    rule.conditions = [
        {"field": "consecutive_failed_runs", "operator": "gte", "value": 3}
    ]
    mock_repos.notification_rule.list_by_project = AsyncMock(return_value=([rule], 1))

    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/notification-rules")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "data": [
            {
                "id": str(rule.id),
                "project_id": str(project_id),
                "name": "Test Rule",
                "enabled": True,
                "conditions": [
                    {"field": "consecutive_failures", "operator": "gte", "value": 3}
                ],
                "channels": [
                    {
                        "type": "webhook",
                        "config": {"url": "https://hooks.example.com/legacy"},
                        "template": None,
                    }
                ],
                "template": "Run {{run_id}} token",
                "created_at": "2026-06-01T06:07:08Z",
            }
        ],
        "page": 1,
        "per_page": 20,
        "total": 1,
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.notification_rule.list_by_project.assert_awaited_once_with(
        project_id,
        offset=0,
        limit=20,
    )
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_rules_marks_historical_invalid_conditions_without_500(
    app,
    mock_repos,
    project_id,
    tenant_id,
):
    rule = _make_orm_rule(project_id)
    rule.created_at = datetime(2026, 6, 1, 6, 7, 8, tzinfo=timezone.utc)
    rule.conditions = [
        {"field": "statuz", "operator": "eq", "value": "failed"},
        {"any": [{"field": "failed", "operator": "between", "value": 1}]},
        {"all": [{"field": "consecutive_failed_runs", "operator": "gte", "value": 3}]},
    ]
    mock_repos.notification_rule.list_by_project = AsyncMock(return_value=([rule], 1))

    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/notification-rules")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "data": [
            {
                "id": str(rule.id),
                "project_id": str(project_id),
                "name": "Test Rule",
                "enabled": True,
                "conditions": [
                    {
                        "invalid": True,
                        "reason": (
                            "conditions[0].field must be one of: "
                            "consecutive_failures, failed, new_failed, pass_rate, recovered, status"
                        ),
                        "raw_field": "statuz",
                        "raw_operator": "eq",
                    },
                    {
                        "any": [
                            {
                                "invalid": True,
                                "reason": (
                                    "conditions[1].any[0].operator must be one of: "
                                    "eq, gt, gte, lt, lte, ne"
                                ),
                                "raw_field": "failed",
                                "raw_operator": "between",
                            }
                        ]
                    },
                    {
                        "all": [
                            {
                                "field": "consecutive_failures",
                                "operator": "gte",
                                "value": 3,
                            }
                        ]
                    },
                ],
                "channels": [
                    {
                        "type": "webhook",
                        "config": {"url": "https://example.com/secret-token"},
                        "template": None,
                    }
                ],
                "template": "Run {{run_id}} token",
                "created_at": "2026-06-01T06:07:08Z",
            }
        ],
        "page": 1,
        "per_page": 20,
        "total": 1,
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.notification_rule.list_by_project.assert_awaited_once_with(
        project_id,
        offset=0,
        limit=20,
    )
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rule(app, mock_repos, mock_user, project_id):
    from qaplatform.api.auth.permissions import Action

    rule = _make_orm_rule(project_id)
    rule.created_at = datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc)

    async def _create(**kwargs):
        rule.project_id = kwargs["project_id"]
        rule.name = kwargs["name"]
        rule.enabled = kwargs["enabled"]
        rule.conditions = kwargs["conditions"]
        rule.channels = kwargs["channels"]
        rule.template = kwargs["template"]
        return rule

    mock_repos.notification_rule.create = AsyncMock(side_effect=_create)

    with patch(
        "qaplatform.api.v1.notifications.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/projects/{project_id}/notification-rules",
                json={
                    "name": "Test Rule",
                    "channels": [
                        {
                            "type": "webhook",
                            "webhook_url": "https://hooks.example.com/secret-token",
                        }
                    ],
                },
            )

    assert resp.status_code == 201
    assert resp.json() == _expected_rule_response(rule)
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.NOTIFICATION_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.notification_rule.create.assert_awaited_once_with(
        project_id=project_id,
        name="Test Rule",
        enabled=True,
        conditions=[],
        channels=[
            {
                "type": "webhook",
                "config": {"url": "https://hooks.example.com/secret-token"},
            }
        ],
        template=None,
    )
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "notification_rule.create",
        "resource_type": "notification_rule",
        "resource_id": rule.id,
        "before_state": None,
        "after_state": _expected_rule_audit_state(rule),
    }
    assert "secret-token" not in repr(audit_kwargs)
    assert "Run {{run_id}} token" not in repr(audit_kwargs)


@pytest.mark.asyncio
async def test_create_rule_rejects_duplicate_channel_types(app, mock_repos, project_id):
    channels = [
        {"type": "webhook", "config": {"url": "https://first.example.com"}},
        {"type": "webhook", "config": {"url": "https://second.example.com"}},
    ]

    async with await _make_client(app) as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "Duplicate Webhooks",
                "channels": channels,
            },
        )

    _assert_body_validation_error(
        resp,
        field="channels",
        expected_msg="Value error, duplicate notification channel type: webhook",
        expected_input=channels,
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_create_rule_rejects_unsupported_channel_type(app, mock_repos, project_id):
    channels = [
        {"type": "slack", "config": {"url": "https://hooks.example.com"}}
    ]

    async with await _make_client(app) as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "Slack is not first-class",
                "channels": channels,
            },
        )

    _assert_body_validation_error(
        resp,
        field="channels",
        expected_msg=(
            "Value error, unsupported notification channel type: slack; "
            "allowed: dingtalk, email, webhook, wecom"
        ),
        expected_input=channels,
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_create_rule_rejects_non_object_channel_config(app, mock_repos, project_id):
    channels = [{"type": "webhook", "config": "https://hooks.example.com"}]

    async with await _make_client(app) as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "Bad Config",
                "channels": channels,
            },
        )

    _assert_body_validation_error(
        resp,
        field="channels",
        expected_msg="Value error, channels[0].config must be an object",
        expected_input=channels,
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_rule_routes_reject_blank_name_before_side_effects(
    app,
    mock_repos,
    project_id,
):
    rule_id = uuid.uuid4()

    async with await _make_client(app) as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "   ",
                "channels": [{"type": "webhook", "config": {}}],
            },
        )
        update_resp = await client.put(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
            json={"name": "   "},
        )

    _assert_body_validation_error(
        create_resp,
        field="name",
        expected_msg="Value error, notification rule name must not be blank",
        expected_input="   ",
    )
    _assert_body_validation_error(
        update_resp,
        field="name",
        expected_msg="Value error, notification rule name must not be blank",
        expected_input="   ",
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_create_rule_rejects_invalid_conditions(app, mock_repos, project_id):
    conditions = [{"field": "statuz", "operator": "eq", "value": "failed"}]

    async with await _make_client(app) as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "Bad Conditions",
                "channels": [{"type": "webhook", "config": {}}],
                "conditions": conditions,
            },
        )

    _assert_body_validation_error(
        resp,
        field="conditions",
        expected_msg=(
            "Value error, conditions[0].field must be one of: "
            "consecutive_failures, failed, new_failed, pass_rate, recovered, status"
        ),
        expected_input=conditions,
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_create_rule_rejects_undocumented_condition_alias(app, mock_repos, project_id):
    conditions = [
        {"field": "consecutive_failed_runs", "operator": "gte", "value": 3}
    ]

    async with await _make_client(app) as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "Alias Conditions",
                "channels": [{"type": "webhook", "config": {}}],
                "conditions": conditions,
            },
        )

    _assert_body_validation_error(
        resp,
        field="conditions",
        expected_msg=(
            "Value error, conditions[0].field must be one of: "
            "consecutive_failures, failed, new_failed, pass_rate, recovered, status"
        ),
        expected_input=conditions,
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_get_rule_not_found(app, mock_repos, project_id, tenant_id):
    rule_id = uuid.uuid4()

    async with await _make_client(app) as client:
        resp = await client.get(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
        )

    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Notification rule not found",
            "details": [],
        }
    }
    mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_repos.notification_rule.get_for_project.assert_awaited_once_with(
        rule_id, project_id
    )
    mock_repos.notification_rule.update.assert_not_awaited()
    mock_repos.notification_rule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_notification_rule_item_routes_hide_other_project_rule_without_side_effects(
    app,
    mock_repos,
    mock_user,
    project_id,
):
    rule_id = uuid.uuid4()
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=None)

    async with await _make_client(app) as client:
        responses = [
            await client.get(
                f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
            ),
            await client.put(
                f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
                json={"name": "Updated Rule"},
            ),
            await client.delete(
                f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
            ),
        ]

    for resp in responses:
        assert resp.status_code == 404, resp.text
        assert resp.json() == {
            "error": {
                "code": "NOT_FOUND",
                "message": "Notification rule not found",
                "details": [],
            }
        }

    assert mock_repos.project.get_for_tenant.await_args_list == [
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
    ]
    assert mock_repos.notification_rule.get_for_project.await_args_list == [
        call(rule_id, project_id),
        call(rule_id, project_id),
        call(rule_id, project_id),
    ]
    mock_repos.notification_rule.list_by_project.assert_not_awaited()
    mock_repos.notification_rule.create.assert_not_awaited()
    mock_repos.notification_rule.update.assert_not_awaited()
    mock_repos.notification_rule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_rule(app, mock_repos, mock_user, project_id):
    from qaplatform.api.auth.permissions import Action

    rule = _make_orm_rule(project_id)
    rule.created_at = datetime(2026, 5, 31, 21, 22, 23, tzinfo=timezone.utc)
    before_state = _expected_rule_audit_state(rule)
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=rule)
    mock_repos.notification_rule.delete = AsyncMock()

    with patch(
        "qaplatform.api.v1.notifications.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        async with await _make_client(app) as client:
            resp = await client.delete(
                f"/api/v1/projects/{project_id}/notification-rules/{rule.id}"
            )

    assert resp.status_code == 204
    assert resp.content == b""
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.NOTIFICATION_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.notification_rule.get_for_project.assert_awaited_once_with(
        rule.id, project_id
    )
    mock_repos.notification_rule.delete.assert_awaited_once_with(rule)
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "notification_rule.delete",
        "resource_type": "notification_rule",
        "resource_id": rule.id,
        "before_state": before_state,
        "after_state": None,
    }
    assert "secret-token" not in repr(audit_kwargs)
    assert "Run {{run_id}} token" not in repr(audit_kwargs)


@pytest.mark.asyncio
async def test_update_rule(app, mock_repos, mock_user, project_id):
    from qaplatform.api.auth.permissions import Action

    rule = _make_orm_rule(project_id)
    rule.created_at = datetime(2026, 5, 31, 22, 23, 24, tzinfo=timezone.utc)
    before_state = _expected_rule_audit_state(rule)
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=rule)
    mock_repos.notification_rule.update = AsyncMock(side_effect=_apply_rule_update)

    with patch(
        "qaplatform.api.v1.notifications.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        async with await _make_client(app) as client:
            resp = await client.put(
                f"/api/v1/projects/{project_id}/notification-rules/{rule.id}",
                json={"name": "Updated Rule"},
            )

    assert resp.status_code == 200
    assert rule.name == "Updated Rule"
    assert resp.json() == _expected_rule_response(rule)
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.NOTIFICATION_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.notification_rule.get_for_project.assert_awaited_once_with(
        rule.id, project_id
    )
    mock_repos.notification_rule.update.assert_awaited_once_with(
        rule,
        name="Updated Rule",
    )
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "notification_rule.update",
        "resource_type": "notification_rule",
        "resource_id": rule.id,
        "before_state": before_state,
        "after_state": _expected_rule_audit_state(rule),
    }
    assert "secret-token" not in repr(audit_kwargs)
    assert "Run {{run_id}} token" not in repr(audit_kwargs)


@pytest.mark.asyncio
async def test_update_rule_normalizes_conditions_channels_and_redacts_audit(
    app,
    mock_repos,
    mock_user,
    project_id,
):
    from qaplatform.api.auth.permissions import Action

    rule = _make_orm_rule(project_id)
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=rule)
    mock_repos.notification_rule.update = AsyncMock(side_effect=_apply_rule_update)

    with patch(
        "qaplatform.api.v1.notifications.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        async with await _make_client(app) as client:
            resp = await client.put(
                f"/api/v1/projects/{project_id}/notification-rules/{rule.id}",
                json={
                    "conditions": [
                        {
                            "all": [
                                {
                                    "field": "status",
                                    "operator": "eq",
                                    "value": "failed",
                                },
                                {"field": "failed", "operator": "gt", "value": 0},
                            ]
                        }
                    ],
                    "channels": [
                        {
                            "type": "webhook",
                            "webhook_url": "https://hooks.example.com/update-secret",
                            "template": "Webhook {{status}}",
                        }
                    ],
                    "template": "Rule template with secret-token",
                },
            )

    assert resp.status_code == 200, resp.text
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.NOTIFICATION_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.notification_rule.get_for_project.assert_awaited_once_with(
        rule.id, project_id
    )
    mock_repos.notification_rule.update.assert_awaited_once()
    update_kwargs = mock_repos.notification_rule.update.await_args.kwargs
    assert update_kwargs["conditions"] == [
        {
            "all": [
                {"field": "status", "operator": "eq", "value": "failed"},
                {"field": "failed", "operator": "gt", "value": 0},
            ]
        }
    ]
    assert update_kwargs["channels"] == [
        {
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/update-secret"},
            "template": "Webhook {{status}}",
        }
    ]
    assert update_kwargs["template"] == "Rule template with secret-token"

    body = resp.json()
    assert body["conditions"] == update_kwargs["conditions"]
    assert body["channels"] == update_kwargs["channels"]
    assert body["template"] == "Rule template with secret-token"

    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["action"] == "notification_rule.update"
    assert audit_kwargs["resource_type"] == "notification_rule"
    assert audit_kwargs["resource_id"] == rule.id
    assert audit_kwargs["before_state"]["conditions"] == [
        {"field": "status", "operator": "eq", "value": "failed"}
    ]
    assert audit_kwargs["after_state"]["conditions"] == update_kwargs["conditions"]
    assert audit_kwargs["before_state"]["channels"] == {
        "redacted": True,
        "count": 1,
        "types": ["webhook"],
    }
    assert audit_kwargs["after_state"]["channels"] == {
        "redacted": True,
        "count": 1,
        "types": ["webhook"],
    }
    assert audit_kwargs["before_state"]["template"] == {
        "redacted": True,
        "present": True,
        "length": len("Run {{run_id}} token"),
    }
    assert audit_kwargs["after_state"]["template"] == {
        "redacted": True,
        "present": True,
        "length": len("Rule template with secret-token"),
    }
    serialized_audit = repr(audit_kwargs)
    assert "https://hooks.example.com/update-secret" not in serialized_audit
    assert "Webhook {{status}}" not in serialized_audit
    assert "Rule template with secret-token" not in serialized_audit
    assert "secret-token" not in serialized_audit


@pytest.mark.asyncio
async def test_update_rule_rejects_empty_channels(app, mock_repos, project_id):
    rule = _make_orm_rule(project_id)
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=rule)

    async with await _make_client(app) as client:
        resp = await client.put(
            f"/api/v1/projects/{project_id}/notification-rules/{rule.id}",
            json={"channels": []},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": "too_short",
            "loc": ["body", "channels"],
            "msg": "List should have at least 1 item after validation, not 0",
            "input": [],
        }
    ]
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_update_rule_rejects_invalid_conditions_before_side_effects(
    app,
    mock_repos,
    project_id,
):
    rule_id = uuid.uuid4()
    conditions = [{"field": "status", "operator": "around", "value": "failed"}]

    async with await _make_client(app) as client:
        resp = await client.put(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
            json={"conditions": conditions},
        )

    _assert_body_validation_error(
        resp,
        field="conditions",
        expected_msg=(
            "Value error, conditions[0].operator must be one of: "
            "eq, gt, gte, lt, lte, ne"
        ),
        expected_input=conditions,
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_update_rule_rejects_duplicate_channel_types(app, mock_repos, project_id):
    rule = _make_orm_rule(project_id)
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=rule)
    channels = [
        {"type": "email", "config": {"to_addresses": ["qa@example.com"]}},
        {"type": "email", "config": {"to_addresses": ["owner@example.com"]}},
    ]

    async with await _make_client(app) as client:
        resp = await client.put(
            f"/api/v1/projects/{project_id}/notification-rules/{rule.id}",
            json={"channels": channels},
        )

    _assert_body_validation_error(
        resp,
        field="channels",
        expected_msg="Value error, duplicate notification channel type: email",
        expected_input=channels,
    )
    _assert_notification_validation_short_circuited(mock_repos)


@pytest.mark.asyncio
async def test_update_rule_clears_template_when_null_submitted(
    app, mock_repos, mock_user, project_id
):
    from qaplatform.api.auth.permissions import Action

    rule = _make_orm_rule(project_id)
    before_state = _expected_rule_audit_state(rule)
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=rule)
    mock_repos.notification_rule.update = AsyncMock(side_effect=_apply_rule_update)

    with patch(
        "qaplatform.api.v1.notifications.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        async with await _make_client(app) as client:
            resp = await client.put(
                f"/api/v1/projects/{project_id}/notification-rules/{rule.id}",
                json={"template": None},
            )

    assert resp.status_code == 200
    assert rule.template is None
    assert resp.json() == _expected_rule_response(rule)
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.NOTIFICATION_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.notification_rule.get_for_project.assert_awaited_once_with(
        rule.id, project_id
    )
    mock_repos.notification_rule.update.assert_awaited_once_with(
        rule,
        template=None,
    )
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "notification_rule.update",
        "resource_type": "notification_rule",
        "resource_id": rule.id,
        "before_state": before_state,
        "after_state": _expected_rule_audit_state(rule),
    }
    assert audit_kwargs["before_state"]["template"] == {
        "redacted": True,
        "present": True,
        "length": len("Run {{run_id}} token"),
    }
    assert audit_kwargs["after_state"]["template"] == {
        "redacted": True,
        "present": False,
        "length": 0,
    }
    assert "secret-token" not in repr(audit_kwargs)
    assert "Run {{run_id}} token" not in repr(audit_kwargs)


@pytest.mark.asyncio
async def test_update_rule_keeps_template_when_omitted(
    app, mock_repos, mock_user, project_id
):
    from qaplatform.api.auth.permissions import Action

    rule = _make_orm_rule(project_id)
    original_template = rule.template
    before_state = _expected_rule_audit_state(rule)
    mock_repos.notification_rule.get_for_project = AsyncMock(return_value=rule)
    mock_repos.notification_rule.update = AsyncMock(side_effect=_apply_rule_update)

    with patch(
        "qaplatform.api.v1.notifications.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        async with await _make_client(app) as client:
            resp = await client.put(
                f"/api/v1/projects/{project_id}/notification-rules/{rule.id}",
                json={"name": "Updated Rule"},
            )

    assert resp.status_code == 200
    assert rule.template == original_template
    assert resp.json() == _expected_rule_response(rule)
    enforce_args = enforce_project_action.await_args.args
    assert enforce_args[1] is mock_user
    assert enforce_args[2] == project_id
    assert enforce_args[3] == Action.NOTIFICATION_EDIT
    mock_repos.project.get_for_tenant.assert_awaited_once_with(
        project_id,
        mock_user.tenant_id,
    )
    mock_repos.notification_rule.get_for_project.assert_awaited_once_with(
        rule.id, project_id
    )
    mock_repos.notification_rule.update.assert_awaited_once_with(
        rule,
        name="Updated Rule",
    )
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "notification_rule.update",
        "resource_type": "notification_rule",
        "resource_id": rule.id,
        "before_state": before_state,
        "after_state": _expected_rule_audit_state(rule),
    }
    assert audit_kwargs["before_state"]["template"] == {
        "redacted": True,
        "present": True,
        "length": len(original_template),
    }
    assert audit_kwargs["after_state"]["template"] == {
        "redacted": True,
        "present": True,
        "length": len(original_template),
    }
    assert "secret-token" not in repr(audit_kwargs)
    assert original_template not in repr(audit_kwargs)


@pytest.mark.asyncio
async def test_notification_rule_routes_hide_missing_project_without_side_effects(
    app, mock_repos, project_id, tenant_id
):
    mock_repos.project.get_for_tenant.return_value = None
    rule_id = uuid.uuid4()

    async with await _make_client(app) as client:
        responses = [
            await client.get(f"/api/v1/projects/{project_id}/notification-rules"),
            await client.post(
                f"/api/v1/projects/{project_id}/notification-rules",
                json={
                    "name": "Test Rule",
                    "channels": [{"type": "webhook", "config": {}}],
                },
            ),
            await client.get(
                f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
            ),
            await client.put(
                f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
                json={"name": "Updated Rule"},
            ),
            await client.delete(
                f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
            ),
        ]

    assert [resp.status_code for resp in responses] == [404, 404, 404, 404, 404]
    bodies = [resp.json() for resp in responses]
    expected_body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Project not found",
            "details": [],
        }
    }
    assert bodies == [expected_body] * 5
    assert [args.args for args in mock_repos.project.get_for_tenant.await_args_list] == [
        (project_id, tenant_id)
    ] * 5
    mock_repos.notification_rule.list_by_project.assert_not_awaited()
    mock_repos.notification_rule.get_for_project.assert_not_awaited()
    mock_repos.notification_rule.create.assert_not_awaited()
    mock_repos.notification_rule.update.assert_not_awaited()
    mock_repos.notification_rule.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


# --------------------------------------------------------------------------- #
# API 层与领域层的条件字段一致性
# --------------------------------------------------------------------------- #


def test_api_condition_field_literal_matches_domain_canonical_fields():
    """API 层的 Literal 必须覆盖领域层的全部 canonical 条件字段。

    这两处曾经漂移过：T15 给领域层加了 new_failed / recovered 并在 worker 里
    实现了求值，但 API 层的 Literal 没跟上，导致这两个条件无法通过接口配置，
    直接写库后读取还会因响应模型校验失败而 500。Literal 无法从 frozenset
    派生，只能靠这条测试兜住。
    """
    from typing import get_args

    from qaplatform.api.schemas.notifications import NotificationConditionField
    from qaplatform.domain.models.notification import (
        NOTIFICATION_CANONICAL_CONDITION_FIELDS,
    )

    assert set(get_args(NotificationConditionField)) == set(
        NOTIFICATION_CANONICAL_CONDITION_FIELDS
    )
