from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from qaplatform.api.v1.run_imports import (
    DEFAULT_IMPORT_ENVIRONMENT_NAME,
    DEFAULT_IMPORT_PIPELINE_NAME,
    MAX_IMPORT_XML_BYTES,
    merge_duplicate_results,
    resolve_import_timestamps,
)
from qaplatform.plugins.protocols import TestResultData

PASSING_XML = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="suite1" tests="2">
    <testcase classname="tests.unit.test_a" name="test_ok" time="0.5"/>
    <testcase classname="tests.unit.test_a" name="test_also_ok" time="0.25"/>
  </testsuite>
</testsuites>"""

FAILING_XML = """<?xml version="1.0"?>
<testsuite name="suite1" tests="2">
  <testcase classname="tests.unit.test_a" name="test_ok" time="0.1"/>
  <testcase classname="tests.unit.test_a" name="test_bad" time="0.2">
    <failure message="assert 1 == 2">Traceback...</failure>
  </testcase>
</testsuite>"""

DUPLICATE_CASE_XML = """<?xml version="1.0"?>
<testsuite name="suite1">
  <testcase classname="tests.unit.test_a" name="test_flap" time="0.1">
    <failure message="first attempt">boom</failure>
  </testcase>
  <testcase classname="tests.unit.test_a" name="test_flap" time="0.2"/>
</testsuite>"""

EMPTY_SUITE_XML = '<?xml version="1.0"?><testsuite name="empty" tests="0"></testsuite>'


def _make_orm_run(**overrides):
    from qaplatform.infra.database.models import RunStatusEnum

    pipeline_name = overrides.pop("pipeline_name", "external-import")
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        pipeline_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        status=RunStatusEnum.DONE,
        trigger_type="import",
        priority=1,
        triggered_by=None,
        git_ref="main",
        git_sha=None,
        attempt=1,
        started_at=now,
        finished_at=now,
        duration_ms=750,
        summary={"total": 2},
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    obj = MagicMock()
    for key, value in defaults.items():
        setattr(obj, key, value)
    obj.pipeline = MagicMock()
    obj.pipeline.name = pipeline_name
    return obj


@pytest.fixture
def mock_repos():
    repos = MagicMock()
    repos.run = AsyncMock()
    repos.project = AsyncMock()
    repos.pipeline = AsyncMock()
    repos.environment = AsyncMock()
    repos.test_result = AsyncMock()
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
def project(tenant_id):
    proj = MagicMock()
    proj.id = uuid.uuid4()
    proj.tenant_id = tenant_id
    proj.status = "active"
    return proj


@pytest.fixture
def mock_session():
    # AsyncSession.begin_nested 是同步方法，返回 async context manager；
    # MagicMock 的 __aexit__ 默认返回 False，异常正常传播。
    session = MagicMock()
    session.begin_nested = MagicMock(return_value=MagicMock())
    return session


@pytest.fixture
async def app(mock_repos, mock_user, mock_session):
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
        yield mock_session

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_db_session] = _override_session
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _import_url(project_id, **params) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/api/v1/projects/{project_id}/runs/import?git_ref=main" + (
        f"&{query}" if query else ""
    )


def _post_kwargs(xml: str | bytes = PASSING_XML) -> dict:
    return {
        "content": xml,
        "headers": {
            "Content-Type": "application/xml",
            "Authorization": "Bearer fake",
        },
    }


def _seed_success_mocks(mock_repos, project, run=None):
    mock_repos.project.get_for_tenant.return_value = project
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    mock_repos.pipeline.get_by_name.return_value = pipeline
    environment = MagicMock()
    environment.id = uuid.uuid4()
    mock_repos.environment.get_by_name.return_value = environment
    run = run or _make_orm_run(project_id=project.id, tenant_id=project.tenant_id)
    mock_repos.run.create.return_value = run
    return pipeline, environment, run


# --------------------------------------------------------------------------- #
# 纯函数：merge_duplicate_results / resolve_import_timestamps
# --------------------------------------------------------------------------- #


def _result(suite="s", name="n", status="passed", duration_ms=0):
    return TestResultData(suite=suite, name=name, status=status, duration_ms=duration_ms)


class TestMergeDuplicateResults:
    def test_keeps_last_occurrence(self):
        merged = merge_duplicate_results([
            _result(name="a", status="failed"),
            _result(name="b"),
            _result(name="a", status="passed", duration_ms=5),
        ])
        assert [(r.name, r.status) for r in merged] == [("a", "passed"), ("b", "passed")]
        assert merged[0].duration_ms == 5

    def test_distinct_suites_not_merged(self):
        merged = merge_duplicate_results([
            _result(suite="s1", name="a"),
            _result(suite="s2", name="a"),
        ])
        assert len(merged) == 2

    def test_empty_input(self):
        assert merge_duplicate_results([]) == []


class TestResolveImportTimestamps:
    def test_both_given(self):
        start = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        finish = start + timedelta(seconds=90)
        s, f, d = resolve_import_timestamps(start, finish, total_duration_ms=500)
        assert (s, f, d) == (start, finish, 90_000)

    def test_naive_datetimes_treated_as_utc(self):
        start = datetime(2026, 6, 10, 12, 0)
        finish = datetime(2026, 6, 10, 12, 1)
        s, f, d = resolve_import_timestamps(start, finish, total_duration_ms=0)
        assert s.tzinfo == timezone.utc
        assert f.tzinfo == timezone.utc
        assert d == 60_000

    def test_finished_before_started_rejected(self):
        start = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        with pytest.raises(HTTPException) as exc:
            resolve_import_timestamps(start, start - timedelta(seconds=1), 0)
        assert exc.value.status_code == 422

    def test_only_started_given(self):
        start = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        s, f, d = resolve_import_timestamps(start, None, total_duration_ms=750)
        assert s == start
        assert f == start + timedelta(milliseconds=750)
        assert d == 750

    def test_only_finished_given(self):
        finish = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        s, f, d = resolve_import_timestamps(None, finish, total_duration_ms=750)
        assert f == finish
        assert s == finish - timedelta(milliseconds=750)
        assert d == 750

    def test_neither_given_uses_now(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        s, f, d = resolve_import_timestamps(None, None, total_duration_ms=1500, now=now)
        assert f == now
        assert s == now - timedelta(milliseconds=1500)
        assert d == 1500


# --------------------------------------------------------------------------- #
# 路由行为
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_import_success_done_status(client, mock_repos, mock_user, project):
    from qaplatform.api.auth.permissions import Action
    from qaplatform.infra.database.models import RunStatusEnum

    _, _, run = _seed_success_mocks(mock_repos, project)

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ) as enforce,
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ) as notify,
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(run.id)
    assert body["trigger_type"] == "import"

    assert enforce.await_args.args[1:] == (mock_user, project.id, Action.RUN_TRIGGER)

    create_kwargs = mock_repos.run.create.await_args.kwargs
    assert create_kwargs["tenant_id"] == project.tenant_id
    assert create_kwargs["project_id"] == project.id
    assert create_kwargs["status"] == RunStatusEnum.DONE
    assert create_kwargs["trigger_type"] == "import"
    assert create_kwargs["triggered_by"] == mock_user.user_id
    assert create_kwargs["git_ref"] == "main"
    assert create_kwargs["duration_ms"] == 750
    assert (
        create_kwargs["finished_at"] - create_kwargs["started_at"]
    ) == timedelta(milliseconds=750)
    assert create_kwargs["summary"] == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "error": 0,
        "pass_rate": 1.0,
    }
    assert create_kwargs["metadata_"] == {"import": {"source": "junit-xml"}}

    rows = mock_repos.test_result.bulk_create.await_args.args[0]
    assert [(r["suite"], r["name"], r["status"]) for r in rows] == [
        ("tests.unit.test_a", "test_ok", "passed"),
        ("tests.unit.test_a", "test_also_ok", "passed"),
    ]
    assert all(r["run_id"] == run.id for r in rows)

    # 落库后补偿通知：先 commit 再 evaluate_and_notify
    mock_repos.run.commit.assert_awaited_once()
    notify.assert_awaited_once()
    notify_kwargs = notify.await_args.kwargs
    assert notify_kwargs["run_id"] == run.id
    assert notify_kwargs["project_id"] == project.id
    assert notify_kwargs["status"] == "done"
    assert notify_kwargs["summary"]["total"] == 2

    audit_kwargs = mock_repos.audit.create.await_args.kwargs
    assert audit_kwargs["action"] == "run.import"
    assert audit_kwargs["resource_type"] == "run"
    assert audit_kwargs["resource_id"] == run.id
    assert audit_kwargs["after_state"]["import_counts"] == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "error": 0,
    }
    assert "<?xml" not in str(audit_kwargs["after_state"])


@pytest.mark.asyncio
async def test_import_failed_results_set_failed_status(client, mock_repos, project):
    from qaplatform.infra.database.models import RunStatusEnum

    _seed_success_mocks(mock_repos, project)

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ) as notify,
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs(FAILING_XML))

    assert resp.status_code == 201
    create_kwargs = mock_repos.run.create.await_args.kwargs
    assert create_kwargs["status"] == RunStatusEnum.FAILED
    assert create_kwargs["summary"]["failed"] == 1
    assert create_kwargs["summary"]["failed_tests"] == [
        {"suite": "tests.unit.test_a", "name": "test_bad", "status": "failed"}
    ]
    assert notify.await_args.kwargs["status"] == "failed"


@pytest.mark.asyncio
async def test_import_query_metadata_recorded(client, mock_repos, project):
    _seed_success_mocks(mock_repos, project)
    sha = "a" * 40

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            _import_url(
                project.id,
                git_sha=sha,
                branch="feature/x",
                pipeline_name="ci-backend",
                environment_name="ci",
            ),
            **_post_kwargs(),
        )

    assert resp.status_code == 201
    create_kwargs = mock_repos.run.create.await_args.kwargs
    assert create_kwargs["git_sha"] == sha
    assert create_kwargs["metadata_"]["import"]["branch"] == "feature/x"
    mock_repos.pipeline.get_by_name.assert_awaited_once_with(project.id, "ci-backend")
    mock_repos.environment.get_by_name.assert_awaited_once_with(project.id, "ci")


@pytest.mark.asyncio
async def test_import_explicit_timestamps_used(client, mock_repos, project):
    _seed_success_mocks(mock_repos, project)
    start = "2026-06-10T10:00:00Z"
    finish = "2026-06-10T10:05:00Z"

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            _import_url(project.id, started_at=start, finished_at=finish),
            **_post_kwargs(),
        )

    assert resp.status_code == 201
    create_kwargs = mock_repos.run.create.await_args.kwargs
    assert create_kwargs["duration_ms"] == 300_000
    assert create_kwargs["started_at"] == datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_import_finished_before_started_is_422(client, mock_repos, project):
    _seed_success_mocks(mock_repos, project)

    with patch(
        "qaplatform.api.v1.run_imports.enforce_project_action",
        new_callable=AsyncMock,
    ):
        resp = await client.post(
            _import_url(
                project.id,
                started_at="2026-06-10T10:05:00Z",
                finished_at="2026-06-10T10:00:00Z",
            ),
            **_post_kwargs(),
        )

    assert resp.status_code == 422
    mock_repos.run.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_duplicate_suite_name_keeps_last(client, mock_repos, project):
    from qaplatform.infra.database.models import RunStatusEnum

    _seed_success_mocks(mock_repos, project)

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            _import_url(project.id), **_post_kwargs(DUPLICATE_CASE_XML)
        )

    assert resp.status_code == 201
    rows = mock_repos.test_result.bulk_create.await_args.args[0]
    assert len(rows) == 1
    assert rows[0]["status"] == "passed"
    assert rows[0]["duration_ms"] == 200
    # 最后一条是 passed → run 状态 done
    assert mock_repos.run.create.await_args.kwargs["status"] == RunStatusEnum.DONE


@pytest.mark.asyncio
async def test_import_empty_suite_creates_done_run_without_rows(
    client, mock_repos, project
):
    from qaplatform.infra.database.models import RunStatusEnum

    _seed_success_mocks(mock_repos, project)

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            _import_url(project.id), **_post_kwargs(EMPTY_SUITE_XML)
        )

    assert resp.status_code == 201
    create_kwargs = mock_repos.run.create.await_args.kwargs
    assert create_kwargs["status"] == RunStatusEnum.DONE
    assert create_kwargs["summary"]["total"] == 0
    mock_repos.test_result.bulk_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_project_not_found_is_404(client, mock_repos, project):
    mock_repos.project.get_for_tenant.return_value = None

    resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 404
    mock_repos.run.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_archived_project_is_409(client, mock_repos, project):
    project.status = "archived"
    mock_repos.project.get_for_tenant.return_value = project

    resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 409
    mock_repos.run.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_insufficient_permission_is_403(client, mock_repos, project):
    mock_repos.project.get_for_tenant.return_value = project

    with patch(
        "qaplatform.api.v1.run_imports.enforce_project_action",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=403, detail="Insufficient permissions"),
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 403
    mock_repos.run.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_invalid_xml_is_422(client, mock_repos, project):
    mock_repos.project.get_for_tenant.return_value = project

    with patch(
        "qaplatform.api.v1.run_imports.enforce_project_action",
        new_callable=AsyncMock,
    ):
        resp = await client.post(
            _import_url(project.id), **_post_kwargs("<testsuite><unclosed")
        )

    assert resp.status_code == 422
    assert "Invalid JUnit XML" in resp.text
    mock_repos.run.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_doctype_rejected_is_422(client, mock_repos, project):
    xml = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY a "b">]><testsuite/>'
    resp = await client.post(_import_url(project.id), **_post_kwargs(xml))

    assert resp.status_code == 422
    assert "DOCTYPE" in resp.text


@pytest.mark.asyncio
async def test_import_empty_body_is_422(client, mock_repos, project):
    resp = await client.post(_import_url(project.id), **_post_kwargs(""))

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_oversize_content_length_is_413(client, mock_repos, project):
    kwargs = _post_kwargs()
    kwargs["headers"]["Content-Length"] = str(MAX_IMPORT_XML_BYTES + 1)

    resp = await client.post(_import_url(project.id), **kwargs)

    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_import_oversize_actual_body_is_413(client, mock_repos, project):
    oversized = b"<testsuite>" + b" " * MAX_IMPORT_XML_BYTES + b"</testsuite>"

    resp = await client.post(_import_url(project.id), **_post_kwargs(oversized))

    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_import_missing_git_ref_is_422(client, mock_repos, project):
    resp = await client.post(
        f"/api/v1/projects/{project.id}/runs/import", **_post_kwargs()
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_invalid_git_sha_is_422(client, mock_repos, project):
    resp = await client.post(
        _import_url(project.id, git_sha="not-a-sha"), **_post_kwargs()
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_creates_disabled_placeholder_pipeline_and_environment(
    client, mock_repos, project
):
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.pipeline.get_by_name.return_value = None
    created_pipeline = MagicMock()
    created_pipeline.id = uuid.uuid4()
    mock_repos.pipeline.create.return_value = created_pipeline
    mock_repos.environment.get_by_name.return_value = None
    created_env = MagicMock()
    created_env.id = uuid.uuid4()
    mock_repos.environment.create.return_value = created_env
    run = _make_orm_run(project_id=project.id, tenant_id=project.tenant_id)
    mock_repos.run.create.return_value = run

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 201
    pipeline_kwargs = mock_repos.pipeline.create.await_args.kwargs
    assert pipeline_kwargs["name"] == DEFAULT_IMPORT_PIPELINE_NAME
    assert pipeline_kwargs["enabled"] is False
    assert pipeline_kwargs["stages"][0]["plugin"] == "pytest"
    env_kwargs = mock_repos.environment.create.await_args.kwargs
    assert env_kwargs["name"] == DEFAULT_IMPORT_ENVIRONMENT_NAME
    assert env_kwargs["base_image"] == "import/none"
    assert mock_repos.run.create.await_args.kwargs["pipeline_id"] == created_pipeline.id
    assert mock_repos.run.create.await_args.kwargs["environment_id"] == created_env.id


@pytest.mark.asyncio
async def test_import_pipeline_create_conflict_retries_lookup(
    client, mock_repos, project
):
    mock_repos.project.get_for_tenant.return_value = project
    winner = MagicMock()
    winner.id = uuid.uuid4()
    # 第一次 get 没有 → create 撞唯一约束 → 重查拿到并发胜者
    mock_repos.pipeline.get_by_name.side_effect = [None, winner]
    mock_repos.pipeline.create.side_effect = IntegrityError("stmt", {}, Exception())
    environment = MagicMock()
    environment.id = uuid.uuid4()
    mock_repos.environment.get_by_name.return_value = environment
    run = _make_orm_run(project_id=project.id, tenant_id=project.tenant_id)
    mock_repos.run.create.return_value = run

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 201
    assert mock_repos.run.create.await_args.kwargs["pipeline_id"] == winner.id


@pytest.mark.asyncio
async def test_import_pipeline_name_held_by_soft_deleted_is_409(
    client, mock_repos, project
):
    mock_repos.project.get_for_tenant.return_value = project
    mock_repos.pipeline.get_by_name.side_effect = [None, None]
    mock_repos.pipeline.create.side_effect = IntegrityError("stmt", {}, Exception())

    with patch(
        "qaplatform.api.v1.run_imports.enforce_project_action",
        new_callable=AsyncMock,
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 409
    mock_repos.run.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_notification_failure_does_not_fail_request(
    client, mock_repos, project
):
    _seed_success_mocks(mock_repos, project)

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
            side_effect=RuntimeError("notify backend down"),
        ),
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_import_environment_create_conflict_retries_lookup(
    client, mock_repos, project
):
    mock_repos.project.get_for_tenant.return_value = project
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    mock_repos.pipeline.get_by_name.return_value = pipeline
    winner = MagicMock()
    winner.id = uuid.uuid4()
    mock_repos.environment.get_by_name.side_effect = [None, winner]
    mock_repos.environment.create.side_effect = IntegrityError("stmt", {}, Exception())
    run = _make_orm_run(project_id=project.id, tenant_id=project.tenant_id)
    mock_repos.run.create.return_value = run

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 201
    assert mock_repos.run.create.await_args.kwargs["environment_id"] == winner.id


@pytest.mark.asyncio
async def test_import_environment_name_held_by_soft_deleted_is_409(
    client, mock_repos, project
):
    mock_repos.project.get_for_tenant.return_value = project
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    mock_repos.pipeline.get_by_name.return_value = pipeline
    mock_repos.environment.get_by_name.side_effect = [None, None]
    mock_repos.environment.create.side_effect = IntegrityError("stmt", {}, Exception())

    with patch(
        "qaplatform.api.v1.run_imports.enforce_project_action",
        new_callable=AsyncMock,
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 409
    mock_repos.run.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_blank_git_ref_is_422(client, mock_repos, project):
    resp = await client.post(
        f"/api/v1/projects/{project.id}/runs/import?git_ref=%20%20",
        **_post_kwargs(),
    )

    assert resp.status_code == 422
    mock_repos.project.get_for_tenant.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_without_session_factory_skips_notification(
    app, client, mock_repos, project
):
    _seed_success_mocks(mock_repos, project)
    app.state.container.db_session_factory = None

    with (
        patch(
            "qaplatform.api.v1.run_imports.enforce_project_action",
            new_callable=AsyncMock,
        ),
        patch(
            "qaplatform.worker.notifications.evaluate_and_notify",
            new_callable=AsyncMock,
        ) as notify,
    ):
        resp = await client.post(_import_url(project.id), **_post_kwargs())

    assert resp.status_code == 201
    notify.assert_not_awaited()
