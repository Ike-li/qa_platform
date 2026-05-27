"""Tests for /projects/{id}/pipelines CRUD endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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
    repos.pipeline.create = AsyncMock(return_value=pipeline)
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


@pytest.mark.asyncio
async def test_list_pipelines_returns_paginated_response(app, mock_repos, project_id):
    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/pipelines")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["data"][0]["name"] == "Smoke Pipeline"
    mock_repos.pipeline.list_by_project.assert_awaited_once_with(
        project_id,
        offset=0,
        limit=20,
    )


@pytest.mark.asyncio
async def test_create_pipeline_persists_nested_payload_and_writes_audit(
    app, mock_repos, project_id
):
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
                        "config": {"command": "pytest -q"},
                    }
                ],
                "selector": {"include_paths": ["tests/unit"], "on_empty": "warn"},
                "trigger_config": {"type": "manual"},
                "retry_policy": {"max_attempts": 2, "retry_on": ["infra"]},
                "timeout_seconds": 600,
            },
        )

    assert resp.status_code == 201, resp.text
    create_kwargs = mock_repos.pipeline.create.call_args.kwargs
    assert create_kwargs["project_id"] == project_id
    assert create_kwargs["stages"][0]["config"] == {"command": "pytest -q"}
    assert create_kwargs["selector"]["include_paths"] == ["tests/unit"]
    assert create_kwargs["retry_policy"]["max_attempts"] == 2
    mock_repos.audit.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_pipeline_returns_404_for_missing_or_other_project(
    app, mock_repos, project_id
):
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=None)
    async with await _make_client(app) as client:
        missing = await client.get(f"/api/v1/projects/{project_id}/pipelines/{uuid.uuid4()}")

    assert missing.status_code == 404

    other = _make_orm_pipeline(uuid.uuid4())
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=other)
    async with await _make_client(app) as client:
        wrong_project = await client.get(
            f"/api/v1/projects/{project_id}/pipelines/{other.id}"
        )

    assert wrong_project.status_code == 404


@pytest.mark.asyncio
async def test_update_pipeline_translates_partial_nested_updates(
    app, mock_repos, project_id
):
    pipeline = _make_orm_pipeline(project_id)
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=pipeline)
    raw_token = "pipeline-token-should-not-enter-audit"

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
                        "clone_url": f"https://x-access-token:{raw_token}@git.example/repo.git",
                    },
                },
                "retry_policy": None,
                "enabled": False,
            },
        )

    assert resp.status_code == 200, resp.text
    update_kwargs = mock_repos.pipeline.update.call_args.kwargs
    assert update_kwargs["name"] == "Updated"
    assert update_kwargs["stages"][0]["config"]["env"]["API_TOKEN"] == raw_token
    assert update_kwargs["selector"]["exclude_paths"] == ["tests/e2e"]
    assert update_kwargs["trigger_config"]["source"]["webhook_secret"] == raw_token
    assert update_kwargs["retry_policy"] is None
    assert update_kwargs["enabled"] is False
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
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


@pytest.mark.asyncio
async def test_delete_pipeline_removes_existing_pipeline_and_audits(
    app, mock_repos, project_id
):
    pipeline = _make_orm_pipeline(project_id)
    mock_repos.pipeline.get_by_id = AsyncMock(return_value=pipeline)

    async with await _make_client(app) as client:
        resp = await client.delete(f"/api/v1/projects/{project_id}/pipelines/{pipeline.id}")

    assert resp.status_code == 204
    mock_repos.pipeline.delete.assert_awaited_once_with(pipeline)
    mock_repos.audit.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_routes_hide_missing_project(app, mock_repos, project_id):
    mock_repos.project.get_for_tenant = AsyncMock(return_value=None)

    async with await _make_client(app) as client:
        resp = await client.get(f"/api/v1/projects/{project_id}/pipelines")

    assert resp.status_code == 404
    body = resp.json()
    assert (body.get("detail") or body.get("error", {}).get("message")) == "Project not found"
