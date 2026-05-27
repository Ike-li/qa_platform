from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def mock_run_repo():
    return AsyncMock()


@pytest.fixture
def mock_project_repo():
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
def mock_repos(mock_run_repo, mock_project_repo, mock_pipeline_repo, mock_environment_repo, mock_result_repo, mock_artifact_repo):
    repos = MagicMock()
    repos.run = mock_run_repo
    repos.project = mock_project_repo
    repos.pipeline = mock_pipeline_repo
    repos.environment = mock_environment_repo
    repos.test_result = mock_result_repo
    repos.artifact = mock_artifact_repo
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

    app = create_app(container=MagicMock())

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
async def test_trigger_run(client, mock_pipeline_repo, mock_project_repo, mock_environment_repo, mock_run_repo, tenant_id, app):
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
    proj.default_branch = "main"
    proj.default_env_id = env_id
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    # Mock arq_pool on container
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

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id)},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201
    assert resp.json()["pipeline_id"] == str(pipeline_id)
    mock_arq.enqueue_job.assert_called_once()


@pytest.mark.asyncio
async def test_trigger_run_enqueues_without_arq_pool(client, mock_pipeline_repo, mock_project_repo, mock_environment_repo, mock_run_repo, tenant_id, app):
    """When arq_pool is None, run stays queued (cron will pick it up)."""
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
    proj.default_branch = "main"
    proj.default_env_id = env_id
    mock_project_repo.get_for_tenant.return_value = proj
    mock_run_repo.create.return_value = run

    app.state.container.arq_pool = None

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id)},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_trigger_run_pipeline_not_found(client, mock_pipeline_repo):
    mock_pipeline_repo.get_by_id.return_value = None

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(uuid.uuid4())},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_run_cross_tenant_pipeline_returns_same_404(
    client, mock_pipeline_repo, mock_project_repo, tenant_id
):
    """A pipeline belonging to a foreign tenant must look identical to
    'pipeline does not exist' — otherwise an attacker can enumerate
    pipeline_ids across tenants by status-code/message differential.
    """
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    pipeline.project_id = uuid.uuid4()
    mock_pipeline_repo.get_by_id.return_value = pipeline

    # get_for_tenant returns None for cross-tenant projects, identical to
    # 'project does not exist'.
    mock_project_repo.get_for_tenant.return_value = None

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline.id)},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404
    # Detail must match the 'not found' case so they are indistinguishable.
    body = resp.json()
    detail = body.get("detail") or body.get("error", {}).get("message", "")
    assert "Pipeline not found" in detail or detail == ""


@pytest.mark.asyncio
async def test_list_runs(client, mock_run_repo):
    run = _make_orm_run()
    mock_run_repo.list.return_value = ([run], 1)

    resp = await client.get(
        "/api/v1/runs?status=queued&page=1&per_page=10",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["data"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_get_run(client, mock_run_repo, tenant_id):
    run = _make_orm_run(tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run

    resp = await client.get(f"/api/v1/runs/{run.id}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(run.id)


@pytest.mark.asyncio
async def test_get_run_not_found(client, mock_run_repo):
    mock_run_repo.get_for_tenant.return_value = None

    resp = await client.get(f"/api/v1/runs/{uuid.uuid4()}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_run(client, mock_run_repo, tenant_id, app):
    from qaplatform.infra.database.models import RunStatusEnum

    run = _make_orm_run(status=RunStatusEnum.RUNNING, tenant_id=tenant_id)
    # First lookup is the tenant-scoped fetch; the second is the post-cancel
    # re-read inside the handler (still get_by_id, no tenant filter needed
    # because the run is already known to be in-tenant).
    mock_run_repo.get_for_tenant.return_value = run
    mock_run_repo.get_by_id.return_value = run
    mock_run_repo.cancel_if_current.return_value = True

    app.state.container.redis_client = AsyncMock()

    resp = await client.post(f"/api/v1/runs/{run.id}/cancel", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    app.state.container.redis_client.publish.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_already_terminal(client, mock_run_repo, tenant_id):
    from qaplatform.infra.database.models import RunStatusEnum

    run = _make_orm_run(status=RunStatusEnum.DONE, tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run

    resp = await client.post(f"/api/v1/runs/{run.id}/cancel", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_run_results(client, mock_run_repo, mock_result_repo, tenant_id):
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_result_repo.list.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_run_results_filters_by_suite(client, mock_run_repo, mock_result_repo, tenant_id):
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_result_repo.list.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results?suite=checkout",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    filters = mock_result_repo.list.call_args.kwargs["filters"]
    rendered = [str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters]
    assert any("suite = 'checkout'" in r for r in rendered), rendered


@pytest.mark.asyncio
async def test_get_run_results_filters_by_keyword(client, mock_run_repo, mock_result_repo, tenant_id):
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_result_repo.list.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results?q=timeout",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    filters = mock_result_repo.list.call_args.kwargs["filters"]
    rendered = [str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters]
    q_filter = next(r for r in rendered if "timeout" in r)
    assert "name" in q_filter
    assert "error_message" in q_filter
    assert "ESCAPE" in q_filter


@pytest.mark.asyncio
async def test_get_run_results_combines_suite_and_keyword(client, mock_run_repo, mock_result_repo, tenant_id):
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_result_repo.list.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results?status=failed&suite=checkout&q=timeout",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    filters = mock_result_repo.list.call_args.kwargs["filters"]
    rendered = [str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters]
    assert any("status = 'failed'" in r for r in rendered), rendered
    assert any("suite = 'checkout'" in r for r in rendered), rendered
    assert any("timeout" in r and "error_message" in r for r in rendered), rendered


@pytest.mark.asyncio
async def test_get_run_results_escapes_keyword_like_wildcards(client, mock_run_repo, mock_result_repo, tenant_id):
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_result_repo.list.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results?q=case%25_%5C",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    filters = mock_result_repo.list.call_args.kwargs["filters"]
    rendered = [str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters]
    q_filter = next(r for r in rendered if "case" in r)
    assert "%case\\%\\_\\\\%" in q_filter
    assert "ESCAPE" in q_filter


@pytest.mark.asyncio
async def test_get_run_artifacts(client, mock_run_repo, mock_artifact_repo, tenant_id):
    mock_run_repo.get_for_tenant.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_artifact_repo.list_by_run.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/artifacts",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_archived_run_logs_reads_s3_jsonl(
    client, mock_run_repo, tenant_id, app
):
    run = _make_orm_run(tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run

    s3_client = AsyncMock()
    s3_client.get_object.return_value = {
        "Body": b'{"stream": "stdout", "line": "first"}\n'
        b'{"stream": "stderr", "line": "second"}\n'
    }
    app.state.container.redis_client = AsyncMock()
    app.state.container.s3_client = s3_client
    app.state.container.settings.s3_bucket = "qa-platform"

    resp = await client.get(
        f"/api/v1/runs/{run.id}/logs/archive",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["data"] == [
        {"stream": "stdout", "line": "first"},
        {"stream": "stderr", "line": "second"},
    ]


@pytest.mark.asyncio
async def test_get_archived_run_logs_returns_503_without_s3(
    client, mock_run_repo, tenant_id, app
):
    run = _make_orm_run(tenant_id=tenant_id)
    mock_run_repo.get_for_tenant.return_value = run
    app.state.container.s3_client = None

    resp = await client.get(
        f"/api/v1/runs/{run.id}/logs/archive",
        headers={"Authorization": "Bearer fake"},
    )

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_trigger_run_archived_project_returns_409(
    client, mock_pipeline_repo, mock_project_repo, tenant_id
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

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline.id)},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 409
    body = resp.json()
    detail = body.get("detail") or body.get("error", {}).get("message", "")
    assert "archived" in detail.lower()


@pytest.mark.asyncio
async def test_list_runs_multi_status_filter(client, mock_run_repo):
    """F-LS-01: comma-separated status values must produce an IN clause
    so the caller can fetch e.g. 'queued,running' (in-flight) in one
    call instead of polling each status separately.
    """
    mock_run_repo.list.return_value = ([], 0)

    resp = await client.get(
        "/api/v1/runs?status=queued,running",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200

    mock_run_repo.list.assert_called_once()
    filters = mock_run_repo.list.call_args.kwargs["filters"]
    rendered = [
        str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters
    ]
    assert any(
        "IN" in r and "queued" in r and "running" in r for r in rendered
    ), f"expected IN-clause with both statuses, got: {rendered}"


@pytest.mark.asyncio
async def test_list_runs_single_status_uses_equality(client, mock_run_repo):
    """When the caller supplies one status, keep an equality predicate."""
    mock_run_repo.list.return_value = ([], 0)

    resp = await client.get(
        "/api/v1/runs?status=queued",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200

    filters = mock_run_repo.list.call_args.kwargs["filters"]
    rendered = [
        str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters
    ]
    assert any("= 'queued'" in r for r in rendered), rendered
    assert not any("IN" in r and "queued" in r for r in rendered), rendered


@pytest.mark.asyncio
async def test_trigger_run_with_high_priority(client, mock_pipeline_repo, mock_project_repo, mock_run_repo, tenant_id, app):
    """priority=0 should create a run with priority=0 (HIGH)."""
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

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id), "priority": 0},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201
    assert resp.json()["priority"] == 0
    create_kwargs = mock_run_repo.create.call_args.kwargs
    assert create_kwargs["priority"] == 0


@pytest.mark.asyncio
async def test_trigger_run_priority_validation(client):
    """priority=3 is out of range (0-2) and must return 422."""
    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(uuid.uuid4()), "priority": 3},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_trigger_run_default_priority(client, mock_pipeline_repo, mock_project_repo, mock_run_repo, tenant_id, app):
    """Omitting priority should default to 1 (MEDIUM)."""
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

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id)},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201
    assert resp.json()["priority"] == 1
    create_kwargs = mock_run_repo.create.call_args.kwargs
    assert create_kwargs["priority"] == 1
