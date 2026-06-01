"""Tests for /projects/{id}/pipelines CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_pipeline(project_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    obj.name = "Smoke Pipeline"
    obj.stages = [
        {
            "name": "Smoke",
            "plugin": "pytest",
            "phase": "execute",
            "config": {"command": "pytest"},
        }
    ]
    obj.selector = {"include_paths": ["tests"], "on_empty": "warn"}
    obj.trigger_config = {"type": "manual"}
    obj.collectors = [{"plugin": "junit", "config": {}, "enabled": True}]
    obj.timeout_seconds = 300
    obj.retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 5,
        "scope": "pipeline",
    }
    obj.enabled = True
    obj.created_at = datetime.now(timezone.utc)
    obj.updated_at = datetime.now(timezone.utc)
    return obj


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
    project = MagicMock()
    project.id = project_id
    project.tenant_id = tenant_id
    project.status = "active"
    return project


@pytest.fixture
def mock_repos(mock_project, project_id):
    pipeline = _make_orm_pipeline(project_id)
    repos = MagicMock()
    repos.project.get_for_tenant = AsyncMock(return_value=mock_project)
    repos.pipeline.list_by_project = AsyncMock(return_value=([pipeline], 1))
    repos.pipeline.get_by_id = AsyncMock(return_value=None)
    repos.pipeline.create = AsyncMock(side_effect=lambda **kw: _apply(pipeline, kw))
    repos.pipeline.update = AsyncMock(side_effect=lambda obj, **kw: _apply(obj, kw))
    repos.pipeline.delete = AsyncMock()
    repos.audit.create = AsyncMock()
    return repos


def _apply(obj, data):
    for key, value in data.items():
        setattr(obj, key, value)
    obj.updated_at = datetime.now(timezone.utc)
    return obj


@pytest.fixture
def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)
    app.state.container = container

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    async def _override_session():
        yield MagicMock()

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
async def test_list_pipelines_returns_paginated_response(app, mock_repos, project_id):
    pipeline = mock_repos.pipeline.list_by_project.return_value[0][0]
    pipeline.created_at = datetime(2026, 6, 1, 1, 2, 3, tzinfo=timezone.utc)
    pipeline.updated_at = datetime(2026, 6, 1, 4, 5, 6, tzinfo=timezone.utc)

    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/pipelines")

    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "data": [
            {
                "id": str(pipeline.id),
                "project_id": str(project_id),
                "name": "Smoke Pipeline",
                "stages": [
                    {
                        "name": "Smoke",
                        "plugin": "pytest",
                        "config": {"command": "pytest"},
                        "continue_on_error": False,
                        "phase": "execute",
                    }
                ],
                "selector": {
                    "include_paths": ["tests"],
                    "exclude_paths": [],
                    "tags": [],
                    "expression": None,
                    "regex": None,
                    "on_empty": "warn",
                },
                "trigger_config": {
                    "type": "manual",
                    "dedup_window_seconds": None,
                    "source": {},
                    "conditions": {},
                    "target": {},
                },
                "collectors": [
                    {"plugin": "junit", "config": {}, "enabled": True}
                ],
                "timeout_seconds": 300,
                "retry_policy": {
                    "max_attempts": 2,
                    "retry_on": ["infra"],
                    "backoff_seconds": 5,
                    "scope": "pipeline",
                },
                "enabled": True,
                "created_at": pipeline.created_at.isoformat().replace("+00:00", "Z"),
                "updated_at": pipeline.updated_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 1,
        "per_page": 20,
        "total": 1,
    }
    mock_repos.pipeline.list_by_project.assert_awaited_once_with(
        project_id,
        offset=0,
        limit=20,
    )


@pytest.mark.asyncio
async def test_create_pipeline_persists_nested_payload_and_writes_audit(
    app, mock_repos, mock_user, project_id
):
    raw_token = "pipeline-create-token-should-not-enter-audit"
    raw_clone_url = f"https://x-access-token:{raw_token}@git.example/repo.git"

    async with await _make_client(app) as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            json={
                "name": "Smoke Pipeline",
                "stages": [
                    {
                        "name": "Smoke",
                        "plugin": "pytest",
                        "phase": "execute",
                        "config": {
                            "command": "pytest -q",
                            "env": {"API_TOKEN": raw_token, "REGION": "ap-east-1"},
                        },
                    }
                ],
                "selector": {"include_paths": ["tests/unit"], "on_empty": "warn"},
                "trigger_config": {
                    "type": "webhook",
                    "source": {
                        "webhook_secret": raw_token,
                        "clone_url": raw_clone_url,
                    },
                },
                "collectors": [
                    {
                        "plugin": "junit",
                        "config": {"path": "reports/junit.xml", "api_token": raw_token},
                        "enabled": True,
                    }
                ],
                "retry_policy": {"max_attempts": 2, "retry_on": ["infra"]},
                "timeout_seconds": 600,
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    expected_stages = [
        {
            "name": "Smoke",
            "plugin": "pytest",
            "config": {
                "command": "pytest -q",
                "env": {"API_TOKEN": raw_token, "REGION": "ap-east-1"},
            },
            "continue_on_error": False,
            "phase": "execute",
        }
    ]
    expected_selector = {
        "include_paths": ["tests/unit"],
        "exclude_paths": [],
        "tags": [],
        "expression": None,
        "regex": None,
        "on_empty": "warn",
    }
    expected_trigger_config = {
        "type": "webhook",
        "dedup_window_seconds": None,
        "source": {
            "webhook_secret": raw_token,
            "clone_url": raw_clone_url,
        },
        "conditions": {},
        "target": {},
    }
    expected_collectors = [
        {
            "plugin": "junit",
            "config": {"path": "reports/junit.xml", "api_token": raw_token},
            "enabled": True,
        }
    ]
    expected_retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
        "scope": "pipeline",
    }
    mock_repos.pipeline.create.assert_awaited_once_with(
        project_id=project_id,
        name="Smoke Pipeline",
        stages=expected_stages,
        selector=expected_selector,
        trigger_config=expected_trigger_config,
        collectors=expected_collectors,
        timeout_seconds=600,
        retry_policy=expected_retry_policy,
        enabled=True,
    )
    assert body["stages"] == expected_stages
    assert body["selector"] == expected_selector
    assert body["trigger_config"] == expected_trigger_config
    assert body["collectors"] == expected_collectors
    assert body["retry_policy"] == expected_retry_policy
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["tenant_id"] == mock_user.tenant_id
    assert audit_kwargs["user_id"] == mock_user.user_id
    assert audit_kwargs["action"] == "pipeline.create"
    assert audit_kwargs["resource_type"] == "pipeline"
    assert audit_kwargs["resource_id"] == uuid.UUID(body["id"])
    assert audit_kwargs["before_state"] is None
    assert audit_kwargs["after_state"]["project_id"] == str(project_id)
    assert audit_kwargs["after_state"]["name"] == "Smoke Pipeline"
    assert audit_kwargs["after_state"]["stages"][0]["config"]["command"] == "pytest -q"
    assert audit_kwargs["after_state"]["stages"][0]["config"]["env"]["API_TOKEN"] == {
        "redacted": True
    }
    assert audit_kwargs["after_state"]["stages"][0]["config"]["env"]["REGION"] == "ap-east-1"
    assert audit_kwargs["after_state"]["trigger_config"]["source"]["webhook_secret"] == {
        "redacted": True
    }
    assert audit_kwargs["after_state"]["trigger_config"]["source"]["clone_url"] == (
        "https://***@git.example/repo.git"
    )
    assert audit_kwargs["after_state"]["collectors"][0]["config"]["api_token"] == {
        "redacted": True
    }
    assert audit_kwargs["after_state"]["retry_policy"]["max_attempts"] == 2
    serialized_audit = repr(audit_kwargs["after_state"])
    assert raw_token not in serialized_audit
    assert "x-access-token" not in serialized_audit


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ({"name": ""}, "body -> name: String should have at least 1 character"),
        (
            {"name": "   "},
            "body -> name: Value error, pipeline name must not be blank",
        ),
        (
            {"name": "Invalid Schema Pipeline", "timeout_seconds": 0},
            "body -> timeout_seconds: Input should be greater than or equal to 1",
        ),
        (
            {
                "name": "Invalid Schema Pipeline",
                "stages": [{"name": "", "plugin": "pytest"}],
            },
            "body -> stages -> 0 -> name: String should have at least 1 character",
        ),
        (
            {
                "name": "Invalid Schema Pipeline",
                "stages": [{"name": "   ", "plugin": "pytest"}],
            },
            "body -> stages -> 0 -> name: Value error, pipeline stage name must not be blank",
        ),
        (
            {
                "name": "Invalid Schema Pipeline",
                "stages": [{"name": "Smoke", "plugin": ""}],
            },
            "body -> stages -> 0 -> plugin: String should have at least 1 character",
        ),
        (
            {
                "name": "Invalid Schema Pipeline",
                "stages": [{"name": "Smoke", "plugin": "   "}],
            },
            "body -> stages -> 0 -> plugin: Value error, pipeline stage plugin must not be blank",
        ),
        (
            {
                "name": "Invalid Schema Pipeline",
                "collectors": [{"plugin": "   "}],
            },
            "body -> collectors -> 0 -> plugin: Value error, pipeline collector plugin must not be blank",
        ),
    ],
)
@pytest.mark.asyncio
async def test_pipeline_routes_reject_invalid_schema_before_side_effects(
    app,
    mock_repos,
    project_id,
    payload,
    expected_detail,
):
    pipeline_id = uuid.uuid4()

    async with await _make_client(app) as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            json=payload,
        )
        update_resp = await client.put(
            f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
            json=payload,
        )

    assert create_resp.status_code == 422, create_resp.text
    assert update_resp.status_code == 422, update_resp.text
    for response in (create_resp, update_resp):
        assert _validation_detail_lines(response) == [expected_detail]
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.pipeline.list_by_project.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.pipeline.create.assert_not_awaited()
    mock_repos.pipeline.update.assert_not_awaited()
    mock_repos.pipeline.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.parametrize(
    ("selector", "expected_detail"),
    [
        (
            {"include_paths": [""]},
            "body -> selector -> include_paths -> 0: String should have at least 1 character",
        ),
        (
            {"include_paths": ["   "]},
            "body -> selector -> include_paths: Value error, pipeline selector include_paths[0] must not be blank",
        ),
        (
            {"exclude_paths": [""]},
            "body -> selector -> exclude_paths -> 0: String should have at least 1 character",
        ),
        (
            {"exclude_paths": ["   "]},
            "body -> selector -> exclude_paths: Value error, pipeline selector exclude_paths[0] must not be blank",
        ),
        (
            {"tags": [""]},
            "body -> selector -> tags -> 0: String should have at least 1 character",
        ),
        (
            {"tags": ["   "]},
            "body -> selector -> tags: Value error, pipeline selector tags[0] must not be blank",
        ),
        (
            {"include_paths": [f"tests/{index}.py" for index in range(101)]},
            "body -> selector -> include_paths: List should have at most 100 items after validation, not 101",
        ),
    ],
)
@pytest.mark.asyncio
async def test_pipeline_routes_reject_invalid_selector_before_side_effects(
    app,
    mock_repos,
    project_id,
    selector,
    expected_detail,
):
    pipeline_id = uuid.uuid4()

    async with await _make_client(app) as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            json={"name": "Invalid Selector Pipeline", "selector": selector},
        )
        update_resp = await client.put(
            f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
            json={"selector": selector},
        )

    assert create_resp.status_code == 422, create_resp.text
    assert update_resp.status_code == 422, update_resp.text
    for response in (create_resp, update_resp):
        assert _validation_detail_lines(response) == [expected_detail]
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.pipeline.list_by_project.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.pipeline.create.assert_not_awaited()
    mock_repos.pipeline.update.assert_not_awaited()
    mock_repos.pipeline.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.parametrize(
    ("retry_policy", "expected_detail"),
    [
        (
            {"max_attempts": 2, "retry_on": [""]},
            "body -> retry_policy -> retry_on -> 0: String should have at least 1 character",
        ),
        (
            {"max_attempts": 2, "retry_on": ["   "]},
            "body -> retry_policy -> retry_on: Value error, pipeline retry_policy retry_on[0] must not be blank",
        ),
        (
            {"max_attempts": 2, "retry_on": [f"reason-{index}" for index in range(21)]},
            "body -> retry_policy -> retry_on: List should have at most 20 items after validation, not 21",
        ),
    ],
)
@pytest.mark.asyncio
async def test_pipeline_routes_reject_invalid_retry_policy_before_side_effects(
    app,
    mock_repos,
    project_id,
    retry_policy,
    expected_detail,
):
    pipeline_id = uuid.uuid4()

    async with await _make_client(app) as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            json={"name": "Invalid Retry Pipeline", "retry_policy": retry_policy},
        )
        update_resp = await client.put(
            f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
            json={"retry_policy": retry_policy},
        )

    assert create_resp.status_code == 422, create_resp.text
    assert update_resp.status_code == 422, update_resp.text
    for response in (create_resp, update_resp):
        assert _validation_detail_lines(response) == [expected_detail]
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.pipeline.list_by_project.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.pipeline.create.assert_not_awaited()
    mock_repos.pipeline.update.assert_not_awaited()
    mock_repos.pipeline.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.parametrize(
    ("trigger_config", "expected_detail"),
    [
        (
            {"type": ""},
            "body -> trigger_config -> type: String should have at least 1 character",
        ),
        (
            {"type": "   "},
            "body -> trigger_config -> type: Value error, pipeline trigger_config type must not be blank",
        ),
        (
            {"type": "webhook", "dedup_window_seconds": -1},
            "body -> trigger_config -> dedup_window_seconds: Input should be greater than or equal to 0",
        ),
    ],
)
@pytest.mark.asyncio
async def test_pipeline_routes_reject_invalid_trigger_config_before_side_effects(
    app,
    mock_repos,
    project_id,
    trigger_config,
    expected_detail,
):
    pipeline_id = uuid.uuid4()

    async with await _make_client(app) as client:
        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            json={"name": "Invalid Trigger Pipeline", "trigger_config": trigger_config},
        )
        update_resp = await client.put(
            f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
            json={"trigger_config": trigger_config},
        )

    assert create_resp.status_code == 422, create_resp.text
    assert update_resp.status_code == 422, update_resp.text
    for response in (create_resp, update_resp):
        assert _validation_detail_lines(response) == [expected_detail]
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.pipeline.list_by_project.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.pipeline.create.assert_not_awaited()
    mock_repos.pipeline.update.assert_not_awaited()
    mock_repos.pipeline.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_pipeline_returns_404_for_missing_or_other_project(
    app, mock_repos, mock_user, project_id
):
    missing_id = uuid.uuid4()
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=None)
    async with await _make_client(app) as client:
        missing = await client.get(f"/api/v1/projects/{project_id}/pipelines/{missing_id}")

    assert missing.status_code == 404
    mock_repos.pipeline.get_by_id.assert_awaited_once_with(missing_id)

    other = _make_orm_pipeline(uuid.uuid4())
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=other)
    async with await _make_client(app) as client:
        wrong_project = await client.get(
            f"/api/v1/projects/{project_id}/pipelines/{other.id}"
        )

    assert wrong_project.status_code == 404
    mock_repos.pipeline.get_by_id.assert_awaited_once_with(other.id)
    missing_body = missing.json()
    wrong_project_body = wrong_project.json()
    assert missing_body == wrong_project_body == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Pipeline not found",
            "details": [],
        }
    }
    assert str(other.project_id) not in wrong_project.text
    assert [args.args for args in mock_repos.project.get_for_tenant.await_args_list] == [
        (project_id, mock_user.tenant_id),
        (project_id, mock_user.tenant_id),
    ]
    mock_repos.pipeline.list_by_project.assert_not_awaited()
    mock_repos.pipeline.create.assert_not_awaited()
    mock_repos.pipeline.update.assert_not_awaited()
    mock_repos.pipeline.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_item_routes_hide_other_project_pipeline_without_side_effects(
    app,
    mock_repos,
    mock_user,
    project_id,
):
    pipeline = _make_orm_pipeline(uuid.uuid4())
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=pipeline)

    async with await _make_client(app) as client:
        responses = [
            await client.get(f"/api/v1/projects/{project_id}/pipelines/{pipeline.id}"),
            await client.put(
                f"/api/v1/projects/{project_id}/pipelines/{pipeline.id}",
                json={"name": "Updated"},
            ),
            await client.delete(
                f"/api/v1/projects/{project_id}/pipelines/{pipeline.id}",
            ),
        ]

    for resp in responses:
        assert resp.status_code == 404, resp.text
        assert resp.json() == {
            "error": {
                "code": "NOT_FOUND",
                "message": "Pipeline not found",
                "details": [],
            }
        }
        assert str(pipeline.project_id) not in resp.text

    assert mock_repos.project.get_for_tenant.await_args_list == [
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
        call(project_id, mock_user.tenant_id),
    ]
    assert mock_repos.pipeline.get_by_id.await_args_list == [
        call(pipeline.id),
        call(pipeline.id),
        call(pipeline.id),
    ]
    mock_repos.pipeline.list_by_project.assert_not_awaited()
    mock_repos.pipeline.create.assert_not_awaited()
    mock_repos.pipeline.update.assert_not_awaited()
    mock_repos.pipeline.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_pipeline_translates_partial_nested_updates(
    app, mock_repos, mock_user, project_id
):
    pipeline = _make_orm_pipeline(project_id)
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=pipeline)
    raw_token = "pipeline-token-should-not-enter-audit"
    raw_clone_url = f"https://x-access-token:{raw_token}@git.example/repo.git"

    async with await _make_client(app) as client:
        resp = await client.put(
            f"/api/v1/projects/{project_id}/pipelines/{pipeline.id}",
            json={
                "name": "Updated",
                "stages": [
                    {
                        "name": "Smoke",
                        "plugin": "pytest",
                        "phase": "execute",
                        "config": {
                            "command": f"pytest --index-url https://u:{raw_token}@pkg.example/simple",
                            "env": {"API_TOKEN": raw_token, "REGION": "ap-east-1"},
                        },
                    }
                ],
                "selector": {"exclude_paths": ["tests/e2e"]},
                "trigger_config": {
                    "type": "webhook",
                    "source": {
                        "webhook_secret": raw_token,
                        "clone_url": raw_clone_url,
                    },
                },
                "collectors": [
                    {
                        "plugin": "junit",
                        "config": {"path": "custom/junit.xml", "api_token": raw_token},
                        "enabled": True,
                    }
                ],
                "retry_policy": None,
                "enabled": False,
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_stages = [
        {
            "name": "Smoke",
            "plugin": "pytest",
            "config": {
                "command": f"pytest --index-url https://u:{raw_token}@pkg.example/simple",
                "env": {"API_TOKEN": raw_token, "REGION": "ap-east-1"},
            },
            "continue_on_error": False,
            "phase": "execute",
        }
    ]
    expected_selector = {
        "include_paths": [],
        "exclude_paths": ["tests/e2e"],
        "tags": [],
        "expression": None,
        "regex": None,
        "on_empty": "fail",
    }
    expected_trigger_config = {
        "type": "webhook",
        "dedup_window_seconds": None,
        "source": {
            "webhook_secret": raw_token,
            "clone_url": raw_clone_url,
        },
        "conditions": {},
        "target": {},
    }
    expected_collectors = [
        {
            "plugin": "junit",
            "config": {"path": "custom/junit.xml", "api_token": raw_token},
            "enabled": True,
        }
    ]
    mock_repos.pipeline.update.assert_awaited_once_with(
        pipeline,
        name="Updated",
        stages=expected_stages,
        selector=expected_selector,
        trigger_config=expected_trigger_config,
        collectors=expected_collectors,
        retry_policy=None,
        enabled=False,
    )
    assert body["name"] == "Updated"
    assert body["enabled"] is False
    assert body["retry_policy"] is None
    assert body["stages"] == expected_stages
    assert body["selector"] == expected_selector
    assert body["trigger_config"] == expected_trigger_config
    assert body["collectors"] == expected_collectors
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["tenant_id"] == mock_user.tenant_id
    assert audit_kwargs["user_id"] == mock_user.user_id
    assert audit_kwargs["action"] == "pipeline.update"
    assert audit_kwargs["resource_type"] == "pipeline"
    assert audit_kwargs["resource_id"] == pipeline.id
    assert audit_kwargs["before_state"]["id"] == str(pipeline.id)
    assert audit_kwargs["before_state"]["project_id"] == str(project_id)
    assert audit_kwargs["before_state"]["name"] == "Smoke Pipeline"
    assert audit_kwargs["before_state"]["enabled"] is True
    assert audit_kwargs["before_state"]["stages"][0]["config"] == {
        "command": "pytest"
    }
    assert audit_kwargs["before_state"]["trigger_config"] == {
        "type": "manual",
        "source": {},
        "conditions": {},
        "target": {},
        "dedup_window_seconds": None,
    }
    assert audit_kwargs["before_state"]["retry_policy"]["max_attempts"] == 2
    assert audit_kwargs["after_state"]["id"] == str(pipeline.id)
    assert audit_kwargs["after_state"]["project_id"] == str(project_id)
    assert audit_kwargs["after_state"]["name"] == "Updated"
    assert audit_kwargs["after_state"]["enabled"] is False
    assert audit_kwargs["after_state"]["retry_policy"] is None
    serialized_audit = repr([audit_kwargs["before_state"], audit_kwargs["after_state"]])
    assert raw_token not in serialized_audit
    assert "x-access-token" not in serialized_audit
    assert audit_kwargs["after_state"]["stages"][0]["config"]["env"]["API_TOKEN"] == {
        "redacted": True
    }
    assert audit_kwargs["after_state"]["stages"][0]["config"]["env"]["REGION"] == "ap-east-1"
    assert audit_kwargs["after_state"]["trigger_config"]["source"]["webhook_secret"] == {
        "redacted": True
    }
    assert audit_kwargs["after_state"]["trigger_config"]["source"]["clone_url"] == (
        "https://***@git.example/repo.git"
    )
    assert audit_kwargs["after_state"]["collectors"][0]["config"]["api_token"] == {
        "redacted": True
    }


@pytest.mark.asyncio
async def test_delete_pipeline_removes_existing_pipeline_and_audits(
    app, mock_repos, project_id
):
    pipeline = _make_orm_pipeline(project_id)
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=pipeline)

    async with await _make_client(app) as client:
        resp = await client.delete(f"/api/v1/projects/{project_id}/pipelines/{pipeline.id}")

    assert resp.status_code == 204
    assert resp.content == b""
    mock_repos.pipeline.delete.assert_awaited_once_with(pipeline)
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["action"] == "pipeline.delete"
    assert audit_kwargs["resource_type"] == "pipeline"
    assert audit_kwargs["resource_id"] == pipeline.id
    assert audit_kwargs["before_state"]["id"] == str(pipeline.id)
    assert audit_kwargs["before_state"]["project_id"] == str(project_id)
    assert audit_kwargs["before_state"]["name"] == "Smoke Pipeline"
    assert audit_kwargs["before_state"]["enabled"] is True
    assert audit_kwargs["before_state"]["stages"][0]["plugin"] == "pytest"
    assert audit_kwargs["before_state"]["trigger_config"] == {
        "type": "manual",
        "source": {},
        "conditions": {},
        "target": {},
        "dedup_window_seconds": None,
    }
    assert audit_kwargs["before_state"]["retry_policy"]["max_attempts"] == 2
    assert audit_kwargs["after_state"] is None


@pytest.mark.asyncio
async def test_pipeline_routes_hide_missing_project(app, mock_repos, mock_user, project_id):
    mock_repos.project.get_for_tenant = AsyncMock(return_value=None)
    pipeline_id = uuid.uuid4()
    create_payload = {
        "name": "Hidden Project Pipeline",
        "stages": [
            {
                "name": "Smoke",
                "plugin": "pytest",
                "phase": "execute",
                "config": {"command": "pytest -q"},
            }
        ],
    }

    async with await _make_client(app) as client:
        responses = [
            await client.get(f"/api/v1/projects/{project_id}/pipelines"),
            await client.post(
                f"/api/v1/projects/{project_id}/pipelines",
                json=create_payload,
            ),
            await client.get(f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}"),
            await client.put(
                f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
                json={"name": "Still Hidden"},
            ),
            await client.delete(f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}"),
        ]

    bodies = [resp.json() for resp in responses]
    assert [resp.status_code for resp in responses] == [404, 404, 404, 404, 404]
    assert bodies == [
        {
            "error": {
                "code": "NOT_FOUND",
                "message": "Project not found",
                "details": [],
            }
        }
    ] * 5
    assert [args.args for args in mock_repos.project.get_for_tenant.await_args_list] == [
        (project_id, mock_user.tenant_id),
        (project_id, mock_user.tenant_id),
        (project_id, mock_user.tenant_id),
        (project_id, mock_user.tenant_id),
        (project_id, mock_user.tenant_id),
    ]
    mock_repos.pipeline.list_by_project.assert_not_awaited()
    mock_repos.pipeline.get_by_id.assert_not_awaited()
    mock_repos.pipeline.create.assert_not_awaited()
    mock_repos.pipeline.update.assert_not_awaited()
    mock_repos.pipeline.delete.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()
