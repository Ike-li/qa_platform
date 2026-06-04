from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_run(**overrides):
    from qaplatform.infra.database.models import RunStatusEnum
    pipeline_name = overrides.pop("pipeline_name", "test-pipeline")
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        pipeline_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        status=RunStatusEnum.QUEUED,
        trigger_type="manual",
        priority=1,
        triggered_by=None,
        git_ref="main",
        git_sha=None,
        attempt=1,
        started_at=None,
        finished_at=None,
        duration_ms=None,
        summary=None,
        error_message=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    obj.pipeline = MagicMock()
    obj.pipeline.name = pipeline_name
    return obj


def _assert_run_not_found_response(resp):
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Run not found",
            "details": [],
        }
    }


def _assert_pipeline_not_found_response(resp, *, forbidden_values=()):
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Pipeline not found",
            "details": [],
        }
    }
    for value in forbidden_values:
        assert str(value) not in resp.text


def _render_filters(filters) -> list[str]:
    return [
        str(filter_.compile(compile_kwargs={"literal_binds": True}))
        for filter_ in filters
    ]


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


def _assert_empty_paginated_response(resp, *, page: int = 1, per_page: int = 20) -> None:
    assert resp.status_code == 200
    assert resp.json() == {
        "data": [],
        "page": page,
        "per_page": per_page,
        "total": 0,
    }


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _expected_run_response(run) -> dict:
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "project_id": str(run.project_id),
        "pipeline_id": str(run.pipeline_id),
        "pipeline_name": run.pipeline.name if run.pipeline is not None else "",
        "environment_id": str(run.environment_id),
        "status": run.status.value if hasattr(run.status, "value") else run.status,
        "trigger_type": run.trigger_type,
        "priority": run.priority,
        "triggered_by": str(run.triggered_by) if run.triggered_by is not None else None,
        "git_ref": run.git_ref,
        "git_sha": run.git_sha,
        "attempt": run.attempt,
        "started_at": _json_datetime(run.started_at) if run.started_at else None,
        "finished_at": _json_datetime(run.finished_at) if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "summary": run.summary,
        "error_message": run.error_message,
        "created_at": _json_datetime(run.created_at),
        "updated_at": _json_datetime(run.updated_at),
    }


def _make_orm_test_result(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        suite="checkout",
        name="test_cart_total",
        status="failed",
        duration_ms=123,
        error_message="AssertionError: expected total",
        stack_trace="traceback",
        tags=["regression", "checkout"],
        metadata_={"browser": "chromium"},
    )
    defaults.update(overrides)
    obj = MagicMock()
    for key, value in defaults.items():
        setattr(obj, key, value)
    return obj


def _expected_test_result_response(result) -> dict:
    return {
        "id": str(result.id),
        "run_id": str(result.run_id),
        "suite": result.suite,
        "name": result.name,
        "status": result.status.value if hasattr(result.status, "value") else result.status,
        "duration_ms": result.duration_ms,
        "error_message": result.error_message,
        "stack_trace": result.stack_trace,
        "tags": result.tags,
        "metadata": result.metadata_,
    }


def _assert_run_trigger_audit(mock_repos, mock_user, run, after_state: dict) -> None:
    mock_repos.audit.create.assert_awaited_once()
    assert mock_repos.audit.create.await_args.kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "run.trigger",
        "resource_type": "run",
        "resource_id": run.id,
        "before_state": None,
        "after_state": after_state,
    }


_TOO_LONG_RESULT_FILTER = "x" * 501
_TOO_LONG_RUN_GIT_REF = "feature/" + ("x" * 193)


class _RateLimitPipeline:
    def zremrangebyscore(self, *args, **kwargs):
        return None

    def zadd(self, *args, **kwargs):
        return None

    def zcard(self, *args, **kwargs):
        return None

    def expire(self, *args, **kwargs):
        return None

    async def execute(self):
        return [None, None, 1, None]


class _RunsRedis:
    def __init__(self) -> None:
        self.publish = AsyncMock()
        self.xadd = AsyncMock()
        self.hset = AsyncMock()

    async def time(self):
        return (1, 0)

    def pipeline(self):
        return _RateLimitPipeline()


@pytest.fixture
def mock_run_repo():
    return AsyncMock()


@pytest.fixture
def mock_project_repo():
    return AsyncMock()


@pytest.fixture
def mock_project_member_repo():
    return AsyncMock()


@pytest.fixture
def mock_pipeline_repo():
    return AsyncMock()


@pytest.fixture
def mock_environment_repo():
    return AsyncMock()


@pytest.fixture
def mock_result_repo():
    return AsyncMock()


@pytest.fixture
def mock_artifact_repo():
    return AsyncMock()


@pytest.fixture
def mock_repos(
    mock_run_repo,
    mock_project_repo,
    mock_project_member_repo,
    mock_pipeline_repo,
    mock_environment_repo,
    mock_result_repo,
    mock_artifact_repo,
):
    repos = MagicMock()
    repos.run = mock_run_repo
    repos.project = mock_project_repo
    repos.project_member = mock_project_member_repo
    repos.pipeline = mock_pipeline_repo
    repos.environment = mock_environment_repo
    repos.test_result = mock_result_repo
    repos.artifact = mock_artifact_repo
    repos.audit = AsyncMock()
    return repos


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = str(uuid.uuid4())
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    return user


@pytest.fixture
async def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_repos, get_current_user
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_trigger_run(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    mock_user,
    tenant_id,
    app,
):
    from qaplatform.api.auth.permissions import Action

    project_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    env_id = uuid.uuid4()
    run = _make_orm_run(project_id=project_id, pipeline_id=pipeline_id, environment_id=env_id, tenant_id=tenant_id)

    pl = MagicMock()
    pl.id = pipeline_id
    pl.project_id = project_id
    mock_pipeline_repo.get_by_id.return_value = pl

    proj = MagicMock()
    proj.id = project_id
    proj.tenant_id = tenant_id
    proj.status = "active"
    proj.git_url = "https://github.com/example/repo.git"
    proj.git_auth_method = "none"
    proj.credential_id = None
    proj.shallow_clone = True
    proj.default_branch = "main"
    proj.default_env_id = env_id
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    # Mock arq_pool on container
    mock_arq = AsyncMock()

    async def _enqueue_job(*_args, **_kwargs):
        assert mock_run_repo.commit.await_count == 1
        return MagicMock(job_id=f"run:{run.id}")

    mock_arq.enqueue_job.side_effect = _enqueue_job
    app.state.container.arq_pool = mock_arq
    app.state.container.settings = MagicMock(max_concurrent_runs=5, max_concurrent_per_project=3)
    mock_run_repo.count_active_or_enqueued.return_value = 0
    mock_run_repo.count_active_or_enqueued_by_project.return_value = 0

    @asynccontextmanager
    async def _fake_lock():
        yield

    mock_run_repo.scheduler_lock = _fake_lock

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.post(
            "/api/v1/runs",
            json={"pipeline_id": str(pipeline_id)},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body == _expected_run_response(run)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.kwargs == {}
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_TRIGGER,
    )

    create_kwargs = mock_run_repo.create.await_args.kwargs
    assert create_kwargs["tenant_id"] == tenant_id
    assert create_kwargs["project_id"] == project_id
    assert create_kwargs["pipeline_id"] == pipeline_id
    assert create_kwargs["environment_id"] == env_id
    assert create_kwargs["git_ref"] == "main"
    assert create_kwargs["trigger_type"] == "manual"
    assert create_kwargs["priority"] == 1
    assert create_kwargs["metadata_"] == {
        "git_url": "https://github.com/example/repo.git",
        "shallow_clone": True,
        "default_branch": "main",
    }
    mock_run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
    mock_run_repo.commit.assert_awaited_once()
    mock_arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name="queue:medium",
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    mock_run_repo.mark_enqueued.assert_awaited_once()
    mark_kwargs = mock_run_repo.mark_enqueued.await_args.kwargs
    assert mock_run_repo.mark_enqueued.await_args.args == (run.id,)
    assert mark_kwargs["queue_name"] == "queue:medium"
    assert mark_kwargs["arq_job_id"] == f"run:{run.id}"
    assert mark_kwargs["enqueued_at"].tzinfo is not None
    mock_run_repo.mark_waiting.assert_not_awaited()
    _assert_run_trigger_audit(mock_repos, mock_user, run, body)


@pytest.mark.asyncio
async def test_trigger_run_includes_git_auth_metadata_without_plaintext(
    client, mock_pipeline_repo, mock_project_repo, mock_run_repo, tenant_id, app
):
    project_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    env_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    run = _make_orm_run(
        project_id=project_id,
        pipeline_id=pipeline_id,
        environment_id=env_id,
        tenant_id=tenant_id,
    )

    pl = MagicMock()
    pl.id = pipeline_id
    pl.project_id = project_id
    mock_pipeline_repo.get_by_id.return_value = pl

    proj = MagicMock()
    proj.id = project_id
    proj.tenant_id = tenant_id
    proj.status = "active"
    proj.git_url = "https://github.com/example/repo.git"
    proj.git_auth_method = "none"
    proj.credential_id = None
    proj.shallow_clone = True
    proj.default_branch = "main"
    proj.default_env_id = env_id
    proj.git_url = "https://github.com/example/private.git"
    proj.git_auth_method = "token"
    proj.credential_id = credential_id
    proj.shallow_clone = True
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    app.state.container.arq_pool = None

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id)},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 201, resp.text
    assert resp.json() == _expected_run_response(run)
    mock_run_repo.create.assert_awaited_once()
    metadata = mock_run_repo.create.await_args.kwargs["metadata_"]
    assert metadata == {
        "git_url": "https://github.com/example/private.git",
        "git_auth_method": "token",
        "credential_id": str(credential_id),
        "shallow_clone": True,
        "default_branch": "main",
    }


@pytest.mark.asyncio
async def test_trigger_run_stays_queued_and_audited_without_arq_pool(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    mock_user,
    tenant_id,
    app,
):
    """When arq_pool is None, run stays queued (cron will pick it up)."""
    from qaplatform.api.auth.permissions import Action

    project_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    env_id = uuid.uuid4()
    run = _make_orm_run(
        project_id=project_id,
        pipeline_id=pipeline_id,
        environment_id=env_id,
        tenant_id=tenant_id,
    )

    pl = MagicMock()
    pl.id = pipeline_id
    pl.project_id = project_id
    mock_pipeline_repo.get_by_id.return_value = pl

    proj = MagicMock()
    proj.id = project_id
    proj.tenant_id = tenant_id
    proj.status = "active"
    proj.git_url = "https://github.com/example/repo.git"
    proj.git_auth_method = "none"
    proj.credential_id = None
    proj.shallow_clone = True
    proj.default_branch = "main"
    proj.default_env_id = env_id
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    app.state.container.arq_pool = None

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.post(
            "/api/v1/runs",
            json={"pipeline_id": str(pipeline_id)},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body == _expected_run_response(run)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.kwargs == {}
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_TRIGGER,
    )

    create_kwargs = mock_run_repo.create.await_args.kwargs
    assert create_kwargs["tenant_id"] == tenant_id
    assert create_kwargs["project_id"] == project_id
    assert create_kwargs["pipeline_id"] == pipeline_id
    assert create_kwargs["environment_id"] == env_id
    assert create_kwargs["git_ref"] == "main"
    assert create_kwargs["trigger_type"] == "manual"
    assert create_kwargs["metadata_"] == {
        "git_url": "https://github.com/example/repo.git",
        "shallow_clone": True,
        "default_branch": "main",
    }
    mock_run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
    mock_run_repo.commit.assert_not_awaited()
    mock_run_repo.mark_enqueued.assert_not_awaited()
    mock_run_repo.mark_waiting.assert_not_awaited()
    _assert_run_trigger_audit(mock_repos, mock_user, run, body)


@pytest.mark.asyncio
async def test_trigger_run_queue_unavailable_returns_created_waiting_run(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    mock_user,
    tenant_id,
    app,
):
    """Queue outages should degrade to a waiting run instead of a 500."""
    from qaplatform.api.auth.permissions import Action

    project_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    env_id = uuid.uuid4()
    run = _make_orm_run(
        project_id=project_id,
        pipeline_id=pipeline_id,
        environment_id=env_id,
        tenant_id=tenant_id,
    )

    pl = MagicMock()
    pl.id = pipeline_id
    pl.project_id = project_id
    mock_pipeline_repo.get_by_id.return_value = pl

    proj = MagicMock()
    proj.id = project_id
    proj.tenant_id = tenant_id
    proj.status = "active"
    proj.git_url = "https://github.com/example/repo.git"
    proj.git_auth_method = "none"
    proj.credential_id = None
    proj.shallow_clone = True
    proj.default_branch = "main"
    proj.default_env_id = env_id
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    mock_arq = AsyncMock()
    mock_arq.enqueue_job.side_effect = RuntimeError(
        "redis://user:manual-trigger-secret@localhost/0"
    )
    app.state.container.arq_pool = mock_arq
    app.state.container.settings = MagicMock(
        max_concurrent_runs=5,
        max_concurrent_per_project=3,
    )
    mock_run_repo.count_active_or_enqueued.return_value = 0
    mock_run_repo.count_active_or_enqueued_by_project.return_value = 0

    @asynccontextmanager
    async def _fake_lock():
        yield

    mock_run_repo.scheduler_lock = _fake_lock

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.post(
            "/api/v1/runs",
            json={"pipeline_id": str(pipeline_id)},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201, resp.text
    assert "manual-trigger-secret" not in resp.text
    body = resp.json()
    assert body == _expected_run_response(run)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_TRIGGER,
    )
    mock_run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
    mock_run_repo.commit.assert_awaited_once()
    mock_arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name="queue:medium",
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    mock_run_repo.mark_waiting.assert_awaited_once_with(
        run.id,
        reason="queue unavailable",
    )
    mock_run_repo.mark_enqueued.assert_not_awaited()
    _assert_run_trigger_audit(mock_repos, mock_user, run, body)


@pytest.mark.asyncio
async def test_trigger_run_pipeline_not_found(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_run_repo,
    mock_repos,
    app,
):
    mock_pipeline_repo.get_by_id.return_value = None
    app.state.container.arq_pool = AsyncMock()
    pipeline_id = uuid.uuid4()

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id)},
        headers={"Authorization": "Bearer fake"},
    )
    _assert_pipeline_not_found_response(
        resp,
        forbidden_values=[pipeline_id],
    )
    mock_pipeline_repo.get_by_id.assert_awaited_once_with(pipeline_id)
    mock_project_repo.get_for_tenant.assert_not_awaited()
    mock_run_repo.create.assert_not_awaited()
    mock_run_repo.set_retry_group_id.assert_not_awaited()
    app.state.container.arq_pool.enqueue_job.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_run_cross_tenant_pipeline_returns_same_404(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    tenant_id,
    app,
):
    """A pipeline belonging to a foreign tenant must look identical to
    'pipeline does not exist' — otherwise an attacker can enumerate
    pipeline_ids across tenants by status-code/message differential.
    """
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    pipeline.project_id = uuid.uuid4()
    mock_pipeline_repo.get_by_id.return_value = pipeline
    app.state.container.arq_pool = AsyncMock()

    # get_for_tenant returns None for cross-tenant projects, identical to
    # 'project does not exist'.
    mock_project_repo.get_for_tenant.return_value = None

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline.id)},
        headers={"Authorization": "Bearer fake"},
    )
    _assert_pipeline_not_found_response(
        resp,
        forbidden_values=[pipeline.id, pipeline.project_id],
    )
    mock_pipeline_repo.get_by_id.assert_awaited_once_with(pipeline.id)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(
        pipeline.project_id,
        tenant_id,
    )
    mock_environment_repo.list_by_project.assert_not_awaited()
    mock_environment_repo.get_by_id.assert_not_awaited()
    mock_run_repo.create.assert_not_awaited()
    mock_run_repo.set_retry_group_id.assert_not_awaited()
    app.state.container.arq_pool.enqueue_job.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_run_hides_missing_or_other_project_environment_without_side_effects(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    tenant_id,
    app,
):
    project_id = uuid.uuid4()
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    pipeline.project_id = project_id
    mock_pipeline_repo.get_by_id.return_value = pipeline

    project = MagicMock()
    project.id = project_id
    project.tenant_id = tenant_id
    project.status = "active"
    project.default_branch = "main"
    project.default_env_id = uuid.uuid4()
    mock_project_repo.get_for_tenant.return_value = project
    app.state.container.arq_pool = AsyncMock()

    missing_environment_id = uuid.uuid4()
    other_project_environment = MagicMock()
    other_project_environment.id = uuid.uuid4()
    other_project_environment.project_id = uuid.uuid4()
    mock_environment_repo.get_by_id.side_effect = [
        None,
        other_project_environment,
    ]

    missing_resp = await client.post(
        "/api/v1/runs",
        json={
            "pipeline_id": str(pipeline.id),
            "environment_id": str(missing_environment_id),
        },
        headers={"Authorization": "Bearer fake"},
    )
    wrong_project_resp = await client.post(
        "/api/v1/runs",
        json={
            "pipeline_id": str(pipeline.id),
            "environment_id": str(other_project_environment.id),
        },
        headers={"Authorization": "Bearer fake"},
    )

    for resp in (missing_resp, wrong_project_resp):
        assert resp.status_code == 404, resp.text
        assert resp.json() == {
            "error": {
                "code": "NOT_FOUND",
                "message": "Environment not found",
                "details": [],
            }
        }
    assert missing_resp.json() == wrong_project_resp.json()
    assert str(other_project_environment.project_id) not in wrong_project_resp.text
    assert mock_pipeline_repo.get_by_id.await_args_list == [
        call(pipeline.id),
        call(pipeline.id),
    ]
    assert mock_project_repo.get_for_tenant.await_args_list == [
        call(project_id, tenant_id),
        call(project_id, tenant_id),
    ]
    assert mock_environment_repo.get_by_id.await_args_list == [
        call(missing_environment_id),
        call(other_project_environment.id),
    ]
    mock_environment_repo.list_by_project.assert_not_awaited()
    mock_run_repo.create.assert_not_awaited()
    mock_run_repo.set_retry_group_id.assert_not_awaited()
    app.state.container.arq_pool.enqueue_job.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs(client, mock_run_repo, mock_repos, tenant_id):
    run = _make_orm_run(tenant_id=tenant_id)
    mock_run_repo.list_filtered_for_tenant.return_value = ([run], 1)

    resp = await client.get(
        "/api/v1/runs?status=queued&page=1&per_page=10",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "data": [_expected_run_response(run)],
        "page": 1,
        "per_page": 10,
        "total": 1,
    }
    mock_run_repo.list_filtered_for_tenant.assert_awaited_once()
    list_kwargs = mock_run_repo.list_filtered_for_tenant.await_args.kwargs
    assert list_kwargs["tenant_id"] == tenant_id
    assert list_kwargs["offset"] == 0
    assert list_kwargs["limit"] == 10
    assert list_kwargs["statuses"] == ["queued"]
    assert list_kwargs["project_ids"] is None
    assert list_kwargs["sort"] == "-created_at"
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs_member_user_uses_project_member_repository(
    app,
    client,
    mock_run_repo,
    mock_project_member_repo,
    mock_user,
    tenant_id,
):
    from qaplatform.api.deps import _get_db_session

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=AssertionError("run list membership must use repository")
    )

    async def _override_db_session():
        yield session

    app.dependency_overrides[_get_db_session] = _override_db_session
    project_id = uuid.uuid4()
    mock_user.user_id = uuid.uuid4()
    mock_user.role = "viewer"
    mock_user.is_platform_admin = False
    mock_project_member_repo.list_project_ids_by_user.return_value = [project_id]
    mock_run_repo.list_filtered_for_tenant.return_value = ([], 0)

    resp = await client.get("/api/v1/runs", headers={"Authorization": "Bearer fake"})

    assert resp.status_code == 200
    mock_project_member_repo.list_project_ids_by_user.assert_awaited_once_with(
        mock_user.user_id,
        tenant_id,
    )
    list_kwargs = mock_run_repo.list_filtered_for_tenant.await_args.kwargs
    assert list_kwargs["tenant_id"] == tenant_id
    assert list_kwargs["project_ids"] == [project_id]
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs_member_user_with_no_projects_returns_empty_without_querying_runs(
    app,
    client,
    mock_run_repo,
    mock_project_member_repo,
    mock_user,
    tenant_id,
):
    from qaplatform.api.deps import _get_db_session

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=AssertionError("run list membership must use repository")
    )

    async def _override_db_session():
        yield session

    app.dependency_overrides[_get_db_session] = _override_db_session
    mock_user.user_id = uuid.uuid4()
    mock_user.role = "viewer"
    mock_user.is_platform_admin = False
    mock_project_member_repo.list_project_ids_by_user.return_value = []

    resp = await client.get("/api/v1/runs", headers={"Authorization": "Bearer fake"})

    assert resp.status_code == 200
    assert resp.json() == {"data": [], "page": 1, "per_page": 20, "total": 0}
    mock_project_member_repo.list_project_ids_by_user.assert_awaited_once_with(
        mock_user.user_id,
        tenant_id,
    )
    mock_run_repo.list_filtered_for_tenant.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run(client, mock_run_repo, tenant_id, mock_user):
    from qaplatform.api.auth.permissions import Action

    run = _make_orm_run(tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.get(
            f"/api/v1/runs/{run.id}",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200
    assert resp.json() == _expected_run_response(run)
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run.id, tenant_id)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        run.project_id,
        Action.RUN_READ,
    )


@pytest.mark.asyncio
async def test_get_run_not_found(client, mock_run_repo, tenant_id):
    mock_run_repo.get_for_tenant.return_value = None
    run_id = uuid.uuid4()

    resp = await client.get(f"/api/v1/runs/{run_id}", headers={"Authorization": "Bearer fake"})

    _assert_run_not_found_response(resp)
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)


@pytest.mark.asyncio
async def test_run_resource_routes_hide_missing_run_without_side_effects(
    client,
    app,
    mock_run_repo,
    mock_result_repo,
    mock_artifact_repo,
    mock_repos,
    tenant_id,
):
    mock_run_repo.get_for_tenant.return_value = None
    run_id = uuid.uuid4()
    redis = _RunsRedis()
    s3_client = AsyncMock()
    mock_repos.notification_log = AsyncMock()
    mock_repos.notification_log.list_by_run = AsyncMock()
    app.state.container.redis_client = redis
    app.state.container.s3_client = s3_client

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        responses = [
            await client.get(
                f"/api/v1/runs/{run_id}",
                headers={"Authorization": "Bearer fake"},
            ),
            await client.post(
                f"/api/v1/runs/{run_id}/cancel",
                headers={"Authorization": "Bearer fake"},
            ),
            await client.get(
                f"/api/v1/runs/{run_id}/results",
                headers={"Authorization": "Bearer fake"},
            ),
            await client.get(
                f"/api/v1/runs/{run_id}/artifacts",
                headers={"Authorization": "Bearer fake"},
            ),
            await client.get(
                f"/api/v1/runs/{run_id}/artifacts/allure-report",
                headers={"Authorization": "Bearer fake"},
            ),
            await client.get(
                f"/api/v1/runs/{run_id}/logs/archive",
                headers={"Authorization": "Bearer fake"},
            ),
            await client.get(
                f"/api/v1/runs/{run_id}/notifications",
                headers={"Authorization": "Bearer fake"},
            ),
        ]

    for resp in responses:
        _assert_run_not_found_response(resp)
    assert [args.args for args in mock_run_repo.get_for_tenant.await_args_list] == [
        (run_id, tenant_id)
    ] * len(responses)
    enforce_project_action.assert_not_awaited()
    mock_run_repo.cancel_if_current.assert_not_awaited()
    mock_result_repo.list_filtered_by_run.assert_not_awaited()
    mock_artifact_repo.list_by_run.assert_not_awaited()
    mock_repos.notification_log.list_by_run.assert_not_awaited()
    s3_client.get_object.assert_not_awaited()
    redis.publish.assert_not_awaited()
    redis.xadd.assert_not_awaited()
    redis.hset.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_run(client, mock_run_repo, mock_repos, tenant_id, mock_user, app):
    from qaplatform.infra.database.models import RunStatusEnum

    run_id = uuid.uuid4()
    before_run = _make_orm_run(id=run_id, status=RunStatusEnum.RUNNING, tenant_id=tenant_id)
    after_run = _make_orm_run(id=run_id, status=RunStatusEnum.CANCELLED, tenant_id=tenant_id)
    expected_before = _expected_run_response(before_run)
    expected_after = _expected_run_response(after_run)
    expected_after_audit = {**expected_after, "cancel_reason": "operator-request"}
    mock_run_repo.get_for_tenant.side_effect = [before_run, after_run]
    mock_run_repo.cancel_if_current.return_value = True

    redis = _RunsRedis()
    app.state.container.redis_client = redis

    resp = await client.post(
        f"/api/v1/runs/{run_id}/cancel",
        json={"reason": "operator-request"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == expected_after
    mock_run_repo.cancel_if_current.assert_awaited_once()
    cancel_args = mock_run_repo.cancel_if_current.await_args
    assert cancel_args.args == (run_id,)
    assert cancel_args.kwargs == {
        "expected_in": {
            RunStatusEnum.QUEUED,
            RunStatusEnum.PREPARING,
            RunStatusEnum.RUNNING,
            RunStatusEnum.COLLECTING,
        }
    }
    redis.publish.assert_awaited_once()
    assert redis.publish.await_args.args == (f"run:cancel:{run_id}", "cancel")
    redis.xadd.assert_awaited_once()
    assert redis.xadd.await_args.args[0] == f"run:{run_id}:events"
    event = redis.xadd.await_args.args[1]
    event_timestamp = datetime.fromisoformat(event["timestamp"])
    assert event_timestamp.tzinfo is not None
    assert event_timestamp.utcoffset() == timezone.utc.utcoffset(event_timestamp)
    assert event == {
        "run_id": str(run_id),
        "status": "cancelled",
        "timestamp": event["timestamp"],
        "previous": "running",
    }
    redis.hset.assert_awaited_once()
    assert redis.hset.await_args.args == (f"run:{run_id}:status",)
    assert redis.hset.await_args.kwargs == {
        "mapping": {"status": "cancelled", "timestamp": event["timestamp"]}
    }
    mock_repos.audit.create.assert_awaited_once()
    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs == {
        "tenant_id": mock_user.tenant_id,
        "user_id": mock_user.user_id,
        "action": "run.cancel",
        "resource_type": "run",
        "resource_id": run_id,
        "before_state": expected_before,
        "after_state": expected_after_audit,
    }


@pytest.mark.asyncio
async def test_cancel_run_rejects_overlong_reason_without_side_effects(
    client,
    mock_run_repo,
    mock_repos,
    tenant_id,
    app,
):
    run_id = uuid.uuid4()
    redis = _RunsRedis()
    app.state.container.redis_client = redis

    resp = await client.post(
        f"/api/v1/runs/{run_id}/cancel",
        json={"reason": "x" * 501},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": "string_too_long",
            "loc": ["body", "reason"],
            "msg": "String should have at most 500 characters",
            "input": "x" * 501,
        }
    ]
    mock_run_repo.get_for_tenant.assert_not_awaited()
    mock_run_repo.cancel_if_current.assert_not_awaited()
    redis.publish.assert_not_awaited()
    redis.xadd.assert_not_awaited()
    redis.hset.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_already_terminal(client, mock_run_repo, mock_repos, tenant_id, app):
    from qaplatform.infra.database.models import RunStatusEnum

    run = _make_orm_run(status=RunStatusEnum.DONE, tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run
    redis = _RunsRedis()
    app.state.container.redis_client = redis

    resp = await client.post(f"/api/v1/runs/{run.id}/cancel", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Run already in terminal status: done"}
    mock_run_repo.cancel_if_current.assert_not_awaited()
    redis.publish.assert_not_awaited()
    redis.xadd.assert_not_awaited()
    redis.hset.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_results(
    client,
    mock_run_repo,
    mock_result_repo,
    mock_repos,
    tenant_id,
    mock_user,
):
    from qaplatform.api.auth.permissions import Action

    run_id = uuid.uuid4()
    run = _make_orm_run(id=run_id, tenant_id=tenant_id)
    result = _make_orm_test_result(run_id=run_id)
    mock_run_repo.get_for_tenant.return_value = run
    mock_result_repo.list_filtered_by_run.return_value = ([result], 42)

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.get(
            f"/api/v1/runs/{run_id}/results?page=3&per_page=7",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "data": [_expected_test_result_response(result)],
        "page": 3,
        "per_page": 7,
        "total": 42,
    }
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        run.project_id,
        Action.RUN_READ,
    )
    mock_result_repo.list_filtered_by_run.assert_awaited_once()
    list_kwargs = mock_result_repo.list_filtered_by_run.await_args.kwargs
    assert list_kwargs["run_id"] == run_id
    assert list_kwargs["offset"] == 14
    assert list_kwargs["limit"] == 7
    assert list_kwargs["status"] is None
    assert list_kwargs["suite"] is None
    assert list_kwargs["query"] is None
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_results_rejects_unknown_status(
    client,
    mock_run_repo,
    mock_result_repo,
):
    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results?status=unknown",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": "literal_error",
            "loc": ["query", "status"],
            "msg": "Input should be 'passed', 'failed', 'error', 'skipped' or 'xfail'",
            "input": "unknown",
        }
    ]
    mock_run_repo.get_for_tenant.assert_not_awaited()
    mock_result_repo.list_filtered_by_run.assert_not_awaited()


@pytest.mark.parametrize(
    ("query", "expected_error"),
    [
        (
            "suite=",
            {
                "type": "string_too_short",
                "loc": ["query", "suite"],
                "msg": "String should have at least 1 character",
                "input": "",
            },
        ),
        (
            f"suite={_TOO_LONG_RESULT_FILTER}",
            {
                "type": "string_too_long",
                "loc": ["query", "suite"],
                "msg": "String should have at most 500 characters",
                "input": _TOO_LONG_RESULT_FILTER,
            },
        ),
        (
            "q=",
            {
                "type": "string_too_short",
                "loc": ["query", "q"],
                "msg": "String should have at least 1 character",
                "input": "",
            },
        ),
        (
            f"q={_TOO_LONG_RESULT_FILTER}",
            {
                "type": "string_too_long",
                "loc": ["query", "q"],
                "msg": "String should have at most 500 characters",
                "input": _TOO_LONG_RESULT_FILTER,
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_get_run_results_rejects_invalid_text_filters_before_side_effects(
    client,
    mock_run_repo,
    mock_result_repo,
    query,
    expected_error,
):
    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results?{query}",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        expected_error
    ]
    mock_run_repo.get_for_tenant.assert_not_awaited()
    mock_result_repo.list_filtered_by_run.assert_not_awaited()


def test_get_run_results_status_filter_is_openapi_enum(app):
    params = app.openapi()["paths"]["/api/v1/runs/{run_id}/results"]["get"]["parameters"]
    status_schema = next(p["schema"] for p in params if p["name"] == "status")
    enum_branch = next(
        branch for branch in status_schema["anyOf"]
        if branch.get("type") != "null"
    )

    assert set(enum_branch["enum"]) == {"passed", "failed", "error", "skipped", "xfail"}


@pytest.mark.asyncio
async def test_get_run_results_filters_by_suite(client, mock_run_repo, mock_result_repo, tenant_id):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(id=run_id, tenant_id=tenant_id)
    mock_result_repo.list_filtered_by_run.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/results?suite=checkout",
        headers={"Authorization": "Bearer fake"},
    )

    _assert_empty_paginated_response(resp)
    mock_result_repo.list_filtered_by_run.assert_awaited_once()
    list_kwargs = mock_result_repo.list_filtered_by_run.await_args.kwargs
    assert list_kwargs["run_id"] == run_id
    assert list_kwargs["offset"] == 0
    assert list_kwargs["limit"] == 20
    assert list_kwargs["suite"] == "checkout"
    assert list_kwargs["status"] is None
    assert list_kwargs["query"] is None


@pytest.mark.asyncio
async def test_get_run_results_filters_by_keyword(client, mock_run_repo, mock_result_repo, tenant_id):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(id=run_id, tenant_id=tenant_id)
    mock_result_repo.list_filtered_by_run.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/results?q=timeout",
        headers={"Authorization": "Bearer fake"},
    )

    _assert_empty_paginated_response(resp)
    mock_result_repo.list_filtered_by_run.assert_awaited_once()
    list_kwargs = mock_result_repo.list_filtered_by_run.await_args.kwargs
    assert list_kwargs["run_id"] == run_id
    assert list_kwargs["offset"] == 0
    assert list_kwargs["limit"] == 20
    assert list_kwargs["query"] == "timeout"
    assert list_kwargs["status"] is None
    assert list_kwargs["suite"] is None


@pytest.mark.asyncio
async def test_get_run_results_combines_suite_and_keyword(client, mock_run_repo, mock_result_repo, tenant_id):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(id=run_id, tenant_id=tenant_id)
    mock_result_repo.list_filtered_by_run.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/results?status=failed&suite=checkout&q=timeout",
        headers={"Authorization": "Bearer fake"},
    )

    _assert_empty_paginated_response(resp)
    mock_result_repo.list_filtered_by_run.assert_awaited_once()
    list_kwargs = mock_result_repo.list_filtered_by_run.await_args.kwargs
    assert list_kwargs["run_id"] == run_id
    assert list_kwargs["offset"] == 0
    assert list_kwargs["limit"] == 20
    assert list_kwargs["status"] == "failed"
    assert list_kwargs["suite"] == "checkout"
    assert list_kwargs["query"] == "timeout"


@pytest.mark.asyncio
async def test_get_run_results_escapes_keyword_like_wildcards(client, mock_run_repo, mock_result_repo, tenant_id):
    run_id = uuid.uuid4()
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(id=run_id, tenant_id=tenant_id)
    mock_result_repo.list_filtered_by_run.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{run_id}/results?q=case%25_%5C",
        headers={"Authorization": "Bearer fake"},
    )

    _assert_empty_paginated_response(resp)
    mock_result_repo.list_filtered_by_run.assert_awaited_once()
    list_kwargs = mock_result_repo.list_filtered_by_run.await_args.kwargs
    assert list_kwargs["run_id"] == run_id
    assert list_kwargs["offset"] == 0
    assert list_kwargs["limit"] == 20
    assert list_kwargs["query"] == "case%_\\"


@pytest.mark.asyncio
async def test_get_run_artifacts(
    client,
    app,
    mock_run_repo,
    mock_artifact_repo,
    tenant_id,
    mock_user,
):
    from qaplatform.api.auth.permissions import Action

    run_id = uuid.uuid4()
    project_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    created_at = datetime(2026, 5, 31, 12, 13, 14, tzinfo=timezone.utc)
    expires_at = datetime(2026, 6, 1, 12, 13, 14, tzinfo=timezone.utc)
    artifact = MagicMock()
    artifact.id = artifact_id
    artifact.run_id = run_id
    artifact.type = "junit"
    artifact.name = "reports/junit.xml"
    artifact.storage_path = f"s3://qa-platform/artifacts/{run_id}/junit.xml"
    artifact.size_bytes = 4096
    artifact.mime_type = "application/xml"
    artifact.expires_at = expires_at
    artifact.created_at = created_at
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    mock_artifact_repo.list_by_run.return_value = ([artifact], 42)
    s3_client = AsyncMock()
    app.state.container.s3_client = s3_client

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.get(
            f"/api/v1/runs/{run_id}/artifacts?page=3&per_page=7",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "data": [
            {
                "id": str(artifact_id),
                "run_id": str(run_id),
                "type": "junit",
                "name": "reports/junit.xml",
                "storage_path": f"s3://qa-platform/artifacts/{run_id}/junit.xml",
                "size_bytes": 4096,
                "mime_type": "application/xml",
                "expires_at": _json_datetime(expires_at),
                "created_at": _json_datetime(created_at),
            }
        ],
        "page": 3,
        "per_page": 7,
        "total": 42,
    }
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_READ,
    )
    mock_artifact_repo.list_by_run.assert_awaited_once_with(
        run_id,
        offset=14,
        limit=7,
    )
    s3_client.get_object.assert_not_awaited()
    s3_client.generate_presigned_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_allure_report_artifact_scans_beyond_first_page(
    client,
    mock_run_repo,
    mock_artifact_repo,
    tenant_id,
    mock_user,
):
    from qaplatform.api.auth.permissions import Action

    run_id = uuid.uuid4()
    project_id = uuid.uuid4()
    created_at = datetime(2026, 5, 31, 12, 13, 14, tzinfo=timezone.utc)

    asset = MagicMock()
    asset.type = "allure-report"
    asset.name = "allure-report/assets/app.js"

    index_id = uuid.uuid4()
    index = MagicMock()
    index.id = index_id
    index.run_id = run_id
    index.type = "allure-report"
    index.name = "allure-report/index.html"
    index.storage_path = f"reports/{run_id}/allure-report/index.html"
    index.size_bytes = 128
    index.mime_type = "text/html"
    index.expires_at = None
    index.created_at = created_at

    mock_run_repo.get_for_tenant.return_value = _make_orm_run(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    mock_artifact_repo.list_by_run.side_effect = [
        ([asset], 2),
        ([index], 2),
    ]

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.get(
            f"/api/v1/runs/{run_id}/artifacts/allure-report",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "id": str(index_id),
        "run_id": str(run_id),
        "type": "allure-report",
        "name": "allure-report/index.html",
        "storage_path": f"reports/{run_id}/allure-report/index.html",
        "size_bytes": 128,
        "mime_type": "text/html",
        "expires_at": None,
        "created_at": _json_datetime(created_at),
    }
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_READ,
    )
    assert mock_artifact_repo.list_by_run.await_args_list == [
        call(run_id, offset=0, limit=100),
        call(run_id, offset=1, limit=100),
    ]


@pytest.mark.asyncio
async def test_get_archived_run_logs_reads_s3_jsonl(
    client, mock_run_repo, tenant_id, app, mock_user
):
    from qaplatform.api.auth.permissions import Action

    project_id = uuid.uuid4()
    run = _make_orm_run(tenant_id=tenant_id, project_id=project_id)
    mock_run_repo.get_for_tenant.return_value = run

    s3_client = AsyncMock()
    s3_client.get_object.return_value = {
        "Body": b'{"stream": "stdout", "line": "first"}\n'
        b'{"stream": "stderr", "line": "second"}\n'
    }
    app.state.container.s3_client = s3_client
    app.state.container.settings.s3_bucket = "qa-platform"

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.get(
            f"/api/v1/runs/{run.id}/logs/archive?page=2&per_page=1",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "data": [{"stream": "stderr", "line": "second"}],
        "page": 2,
        "per_page": 1,
        "total": 2,
    }
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run.id, tenant_id)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_READ,
    )
    s3_client.get_object.assert_awaited_once_with(
        Bucket="qa-platform",
        Key=f"logs/{run.id}.jsonl",
    )
    s3_client.generate_presigned_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_archived_run_logs_returns_503_without_s3(
    client, mock_run_repo, tenant_id, app
):
    run = _make_orm_run(tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run
    app.state.container.s3_client = None

    with patch("qaplatform.api.v1.runs.LogStream") as log_stream_cls:
        resp = await client.get(
            f"/api/v1/runs/{run.id}/logs/archive",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 503
    assert resp.json() == {"detail": "Archived logs are not available"}
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run.id, tenant_id)
    log_stream_cls.assert_not_called()


@pytest.mark.asyncio
async def test_get_run_notifications_returns_exact_page_and_rbac(
    client,
    mock_run_repo,
    mock_repos,
    tenant_id,
    mock_user,
):
    from qaplatform.api.auth.permissions import Action

    run_id = uuid.uuid4()
    project_id = uuid.uuid4()
    rule_id = uuid.uuid4()
    log_id = uuid.uuid4()
    sent_at = datetime(2026, 5, 31, 15, 16, 17, tzinfo=timezone.utc)
    run = _make_orm_run(id=run_id, tenant_id=tenant_id, project_id=project_id)
    log = MagicMock()
    log.id = log_id
    log.project_id = project_id
    log.run_id = run_id
    log.rule_id = rule_id
    log.channel_type = "email"
    log.status = "failed"
    log.error_message = "SMTP timeout"
    log.sent_at = sent_at
    mock_run_repo.get_for_tenant.return_value = run
    mock_repos.notification_log = AsyncMock()
    mock_repos.notification_log.list_by_run.return_value = ([log], 9)

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.get(
            f"/api/v1/runs/{run_id}/notifications?page=3&per_page=4",
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "data": [
            {
                "id": str(log_id),
                "project_id": str(project_id),
                "run_id": str(run_id),
                "rule_id": str(rule_id),
                "channel_type": "email",
                "status": "failed",
                "error_message": "SMTP timeout",
                "sent_at": _json_datetime(sent_at),
            }
        ],
        "page": 3,
        "per_page": 4,
        "total": 9,
    }
    mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.NOTIFICATION_READ,
    )
    mock_repos.notification_log.list_by_run.assert_awaited_once_with(
        run_id,
        offset=8,
        limit=4,
    )
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_run_archived_project_returns_409(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    tenant_id,
    app,
):
    """F-PM-03: archived projects must reject new runs."""
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    pipeline.project_id = uuid.uuid4()
    mock_pipeline_repo.get_by_id.return_value = pipeline

    project = MagicMock()
    project.id = pipeline.project_id
    project.tenant_id = tenant_id
    project.status = "archived"
    mock_project_repo.get_for_tenant.return_value = project
    app.state.container.arq_pool = AsyncMock()

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline.id)},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 409
    assert resp.json() == {
        "detail": "Project is archived; new runs cannot be triggered",
    }
    assert str(project.id) not in resp.text
    assert str(pipeline.id) not in resp.text
    mock_pipeline_repo.get_by_id.assert_awaited_once_with(pipeline.id)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(
        pipeline.project_id,
        tenant_id,
    )
    mock_environment_repo.list_by_project.assert_not_awaited()
    mock_environment_repo.get_by_id.assert_not_awaited()
    mock_run_repo.create.assert_not_awaited()
    mock_run_repo.set_retry_group_id.assert_not_awaited()
    app.state.container.arq_pool.enqueue_job.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs_multi_status_filter(client, mock_run_repo, tenant_id):
    """F-LS-01: comma-separated status values must produce an IN clause
    so the caller can fetch e.g. 'queued,running' (in-flight) in one
    call instead of polling each status separately.
    """
    mock_run_repo.list_filtered_for_tenant.return_value = ([], 0)

    resp = await client.get(
        "/api/v1/runs?status=queued,running",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200

    mock_run_repo.list_filtered_for_tenant.assert_awaited_once()
    list_kwargs = mock_run_repo.list_filtered_for_tenant.await_args.kwargs
    assert list_kwargs["tenant_id"] == tenant_id
    assert list_kwargs["statuses"] == ["queued", "running"]


@pytest.mark.asyncio
async def test_list_runs_rejects_unknown_status_without_querying_runs(
    client,
    mock_run_repo,
):
    resp = await client.get(
        "/api/v1/runs?status=queued,typo",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid run status: typo",
            "details": [],
        }
    }
    mock_run_repo.list_filtered_for_tenant.assert_not_awaited()


@pytest.mark.parametrize("status", ["", ",", "queued,,running"])
@pytest.mark.asyncio
async def test_list_runs_rejects_empty_status_segments_without_querying_runs(
    client,
    mock_run_repo,
    mock_project_member_repo,
    status,
):
    resp = await client.get(
        f"/api/v1/runs?status={status}",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid run status: empty",
            "details": [],
        }
    }
    mock_project_member_repo.list_project_ids_by_user.assert_not_awaited()
    mock_run_repo.list_filtered_for_tenant.assert_not_awaited()


def test_list_runs_status_filter_422_uses_error_response_schema(app):
    responses = app.openapi()["paths"]["/api/v1/runs"]["get"]["responses"]
    schema = responses["422"]["content"]["application/json"]["schema"]

    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


@pytest.mark.parametrize("sort", ["updated_at", "created_at desc"])
@pytest.mark.asyncio
async def test_list_runs_rejects_invalid_sort_without_querying_runs(
    client,
    mock_run_repo,
    mock_project_member_repo,
    sort,
):
    resp = await client.get(
        f"/api/v1/runs?sort={sort}",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": f"Invalid run sort: {sort}",
            "details": [],
        }
    }
    mock_project_member_repo.list_project_ids_by_user.assert_not_awaited()
    mock_run_repo.list_filtered_for_tenant.assert_not_awaited()


@pytest.mark.parametrize(
    ("git_ref", "message"),
    [
        ("", "Invalid run git_ref: empty"),
        ("   ", "Invalid run git_ref: empty"),
        ("feature/" + ("x" * 193), "Invalid run git_ref: too long"),
    ],
)
@pytest.mark.asyncio
async def test_list_runs_rejects_invalid_git_ref_without_querying_runs(
    client,
    mock_run_repo,
    mock_project_member_repo,
    git_ref,
    message,
):
    resp = await client.get(
        "/api/v1/runs",
        params={"git_ref": git_ref},
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
    mock_project_member_repo.list_project_ids_by_user.assert_not_awaited()
    mock_run_repo.list_filtered_for_tenant.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs_rejects_reversed_created_range_without_querying_runs(
    client,
    mock_run_repo,
    mock_project_member_repo,
):
    resp = await client.get(
        "/api/v1/runs",
        params={
            "created_from": "2026-05-31T00:00:00+00:00",
            "created_to": "2026-05-30T00:00:00+00:00",
        },
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid run created range: created_from must be before created_to",
            "details": [],
        }
    }
    mock_project_member_repo.list_project_ids_by_user.assert_not_awaited()
    mock_run_repo.list_filtered_for_tenant.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs_single_status_uses_equality(client, mock_run_repo, tenant_id):
    """When the caller supplies one status, keep an equality predicate."""
    mock_run_repo.list_filtered_for_tenant.return_value = ([], 0)

    resp = await client.get(
        "/api/v1/runs?status=queued",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200

    mock_run_repo.list_filtered_for_tenant.assert_awaited_once()
    list_kwargs = mock_run_repo.list_filtered_for_tenant.await_args.kwargs
    assert list_kwargs["tenant_id"] == tenant_id
    assert list_kwargs["statuses"] == ["queued"]


@pytest.mark.asyncio
async def test_trigger_run_with_high_priority(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    mock_user,
    tenant_id,
    app,
):
    """priority=0 should create a run with priority=0 (HIGH)."""
    from qaplatform.api.auth.permissions import Action

    project_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    env_id = uuid.uuid4()
    run = _make_orm_run(project_id=project_id, pipeline_id=pipeline_id, environment_id=env_id, tenant_id=tenant_id, priority=0)

    pl = MagicMock()
    pl.id = pipeline_id
    pl.project_id = project_id
    mock_pipeline_repo.get_by_id.return_value = pl

    proj = MagicMock()
    proj.id = project_id
    proj.tenant_id = tenant_id
    proj.status = "active"
    proj.git_url = "https://github.com/example/repo.git"
    proj.git_auth_method = "none"
    proj.credential_id = None
    proj.shallow_clone = True
    proj.default_branch = "main"
    proj.default_env_id = env_id
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    mock_arq = AsyncMock()
    mock_arq.enqueue_job.return_value = MagicMock(job_id=f"run:{run.id}")
    app.state.container.arq_pool = mock_arq
    app.state.container.settings = MagicMock(max_concurrent_runs=5, max_concurrent_per_project=3)
    mock_run_repo.count_active_or_enqueued.return_value = 0
    mock_run_repo.count_active_or_enqueued_by_project.return_value = 0

    @asynccontextmanager
    async def _fake_lock():
        yield

    mock_run_repo.scheduler_lock = _fake_lock

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.post(
            "/api/v1/runs",
            json={"pipeline_id": str(pipeline_id), "priority": 0},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body == _expected_run_response(run)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.kwargs == {}
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_TRIGGER,
    )
    mock_pipeline_repo.get_by_id.assert_awaited_once_with(pipeline_id)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_environment_repo.get_by_id.assert_not_awaited()
    mock_environment_repo.list_by_project.assert_not_awaited()
    mock_run_repo.create.assert_awaited_once_with(
        tenant_id=tenant_id,
        project_id=project_id,
        pipeline_id=pipeline_id,
        environment_id=env_id,
        git_ref="main",
        git_sha=None,
        triggered_by=mock_user.user_id,
        trigger_type="manual",
        priority=0,
        metadata_={
            "git_url": "https://github.com/example/repo.git",
            "shallow_clone": True,
            "default_branch": "main",
        },
    )
    mock_run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
    mock_arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name="queue:high",
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    assert mock_run_repo.mark_enqueued.await_args.args == (run.id,)
    assert mock_run_repo.mark_enqueued.await_args.kwargs["queue_name"] == "queue:high"
    assert mock_run_repo.mark_enqueued.await_args.kwargs["arq_job_id"] == f"run:{run.id}"
    assert mock_run_repo.mark_enqueued.await_args.kwargs["enqueued_at"].tzinfo is not None
    mock_run_repo.mark_waiting.assert_not_awaited()
    _assert_run_trigger_audit(mock_repos, mock_user, run, body)


@pytest.mark.asyncio
async def test_trigger_run_priority_validation(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
):
    """priority=3 is out of range (0-2) and must fail before side effects."""
    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(uuid.uuid4()), "priority": 3},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": "less_than_equal",
            "loc": ["body", "priority"],
            "msg": "Input should be less than or equal to 2",
            "input": 3,
        }
    ]
    mock_pipeline_repo.get_by_id.assert_not_awaited()
    mock_project_repo.get_for_tenant.assert_not_awaited()
    mock_environment_repo.get_by_id.assert_not_awaited()
    mock_run_repo.create.assert_not_awaited()
    mock_run_repo.set_retry_group_id.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        (
            {"git_ref": ""},
            {
                "type": "string_too_short",
                "loc": ["body", "git_ref"],
                "msg": "String should have at least 1 character",
                "input": "",
            },
        ),
        (
            {"git_ref": "   "},
            {
                "type": "value_error",
                "loc": ["body", "git_ref"],
                "msg": "Value error, run git_ref must not be blank",
                "input": "   ",
            },
        ),
        (
            {"git_ref": _TOO_LONG_RUN_GIT_REF},
            {
                "type": "string_too_long",
                "loc": ["body", "git_ref"],
                "msg": "String should have at most 200 characters",
                "input": _TOO_LONG_RUN_GIT_REF,
            },
        ),
        (
            {"git_sha": "abc123"},
            {
                "type": "string_pattern_mismatch",
                "loc": ["body", "git_sha"],
                "msg": "String should match pattern '^[0-9a-fA-F]{40}$'",
                "input": "abc123",
            },
        ),
    ],
)
async def test_trigger_run_rejects_invalid_git_inputs_without_side_effects(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    payload,
    expected_error,
):
    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(uuid.uuid4()), **payload},
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        expected_error
    ]
    mock_pipeline_repo.get_by_id.assert_not_awaited()
    mock_project_repo.get_for_tenant.assert_not_awaited()
    mock_environment_repo.get_by_id.assert_not_awaited()
    mock_run_repo.create.assert_not_awaited()
    mock_run_repo.set_retry_group_id.assert_not_awaited()
    mock_repos.audit.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_run_default_priority(
    client,
    mock_pipeline_repo,
    mock_project_repo,
    mock_environment_repo,
    mock_run_repo,
    mock_repos,
    mock_user,
    tenant_id,
    app,
):
    """Omitting priority should default to 1 (MEDIUM)."""
    from qaplatform.api.auth.permissions import Action

    project_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    env_id = uuid.uuid4()
    run = _make_orm_run(project_id=project_id, pipeline_id=pipeline_id, environment_id=env_id, tenant_id=tenant_id, priority=1)

    pl = MagicMock()
    pl.id = pipeline_id
    pl.project_id = project_id
    mock_pipeline_repo.get_by_id.return_value = pl

    proj = MagicMock()
    proj.id = project_id
    proj.tenant_id = tenant_id
    proj.status = "active"
    proj.git_url = "https://github.com/example/repo.git"
    proj.git_auth_method = "none"
    proj.credential_id = None
    proj.shallow_clone = True
    proj.default_branch = "main"
    proj.default_env_id = env_id
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    mock_arq = AsyncMock()
    mock_arq.enqueue_job.return_value = MagicMock(job_id=f"run:{run.id}")
    app.state.container.arq_pool = mock_arq
    app.state.container.settings = MagicMock(max_concurrent_runs=5, max_concurrent_per_project=3)
    mock_run_repo.count_active_or_enqueued.return_value = 0
    mock_run_repo.count_active_or_enqueued_by_project.return_value = 0

    @asynccontextmanager
    async def _fake_lock():
        yield

    mock_run_repo.scheduler_lock = _fake_lock

    with patch(
        "qaplatform.api.v1.runs.enforce_project_action",
        new_callable=AsyncMock,
    ) as enforce_project_action:
        resp = await client.post(
            "/api/v1/runs",
            json={"pipeline_id": str(pipeline_id)},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body == _expected_run_response(run)
    enforce_project_action.assert_awaited_once()
    assert enforce_project_action.await_args.kwargs == {}
    assert enforce_project_action.await_args.args[1:] == (
        mock_user,
        project_id,
        Action.RUN_TRIGGER,
    )
    mock_pipeline_repo.get_by_id.assert_awaited_once_with(pipeline_id)
    mock_project_repo.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)
    mock_environment_repo.get_by_id.assert_not_awaited()
    mock_environment_repo.list_by_project.assert_not_awaited()
    mock_run_repo.create.assert_awaited_once_with(
        tenant_id=tenant_id,
        project_id=project_id,
        pipeline_id=pipeline_id,
        environment_id=env_id,
        git_ref="main",
        git_sha=None,
        triggered_by=mock_user.user_id,
        trigger_type="manual",
        priority=1,
        metadata_={
            "git_url": "https://github.com/example/repo.git",
            "shallow_clone": True,
            "default_branch": "main",
        },
    )
    mock_run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
    mock_arq.enqueue_job.assert_awaited_once_with(
        "execute_run",
        str(run.id),
        _queue_name="queue:medium",
        _job_id=f"run:{run.id}",
        _defer_by=0,
    )
    assert mock_run_repo.mark_enqueued.await_args.args == (run.id,)
    assert mock_run_repo.mark_enqueued.await_args.kwargs["queue_name"] == "queue:medium"
    assert mock_run_repo.mark_enqueued.await_args.kwargs["arq_job_id"] == f"run:{run.id}"
    assert mock_run_repo.mark_enqueued.await_args.kwargs["enqueued_at"].tzinfo is not None
    mock_run_repo.mark_waiting.assert_not_awaited()
    _assert_run_trigger_audit(mock_repos, mock_user, run, body)
