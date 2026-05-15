from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _make_orm_run(**overrides):
    from qaplatform.infra.database.models import RunStatusEnum
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
    user.role = "admin"
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
async def test_trigger_run(client, mock_pipeline_repo, mock_project_repo, mock_environment_repo, mock_run_repo, tenant_id):
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
    mock_project_repo.get_by_id.return_value = proj
    mock_run_repo.create.return_value = run

    resp = await client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id)},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 201
    assert resp.json()["pipeline_id"] == str(pipeline_id)


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
    mock_run_repo.get_by_id.return_value = run

    resp = await client.get(f"/api/v1/runs/{run.id}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(run.id)


@pytest.mark.asyncio
async def test_get_run_not_found(client, mock_run_repo):
    mock_run_repo.get_by_id.return_value = None

    resp = await client.get(f"/api/v1/runs/{uuid.uuid4()}", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_run(client, mock_run_repo, tenant_id):
    from qaplatform.infra.database.models import RunStatusEnum

    run = _make_orm_run(status=RunStatusEnum.RUNNING, tenant_id=tenant_id)
    mock_run_repo.get_by_id.side_effect = [run, run]
    mock_run_repo.cancel_if_current.return_value = True

    resp = await client.post(f"/api/v1/runs/{run.id}/cancel", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cancel_already_terminal(client, mock_run_repo, tenant_id):
    from qaplatform.infra.database.models import RunStatusEnum

    run = _make_orm_run(status=RunStatusEnum.DONE, tenant_id=tenant_id)
    mock_run_repo.get_by_id.return_value = run

    resp = await client.post(f"/api/v1/runs/{run.id}/cancel", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_run_results(client, mock_run_repo, mock_result_repo, tenant_id):
    mock_run_repo.get_by_id.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_result_repo.list.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/results",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_run_artifacts(client, mock_run_repo, mock_artifact_repo, tenant_id):
    mock_run_repo.get_by_id.return_value = _make_orm_run(tenant_id=tenant_id)
    mock_artifact_repo.list_by_run.return_value = ([], 0)

    resp = await client.get(
        f"/api/v1/runs/{uuid.uuid4()}/artifacts",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
