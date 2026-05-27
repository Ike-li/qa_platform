"""Real backend integration coverage for auth tokens, run results, and artifacts.

These tests intentionally exercise production wiring where it matters:

* JWT login -> API token creation -> API-token authenticated request -> revoke.
* Run result filtering and uniqueness against PostgreSQL constraints.
* Artifact soft-delete visibility through both repository and API paths.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


@pytest_asyncio.fixture
async def real_auth_app(test_settings, integration_db_schema):
    """FastAPI app with real auth dependencies and no current-user override."""
    from qaplatform.api import create_app
    from qaplatform.dependencies import init_container
    from qaplatform.plugins.registry import PluginRegistry

    settings = test_settings.model_copy(
        update={
            # This file intentionally registers multiple real users in one ASGI app.
            # Keep rate-limit middleware enabled, but avoid suite-order 429 noise.
            "rate_limit_auth_failure": 100,
            "rate_limit_auth_failure_window": 1,
        }
    )

    container = init_container(settings)
    await container.init_db()
    await container.init_redis()
    container.init_crypto()

    plugin_registry = PluginRegistry()
    plugin_registry.register_builtins()
    container.plugin_registry = plugin_registry

    app = create_app(container=container, settings=settings)
    app.state.container = container

    yield app

    app.dependency_overrides.clear()
    await container.close()


@pytest_asyncio.fixture
async def real_auth_client(real_auth_app):
    transport = ASGITransport(app=real_auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _register_real_user(real_auth_client, prefix: str = "api_token") -> str:
    suffix = uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    password = "correct-horse-battery"

    register_resp = await real_auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    return register_resp.json()["access_token"]


async def _create_real_api_token(
    real_auth_client,
    access_token: str,
    *,
    name: str,
    scopes: list[str],
) -> str:
    create_resp = await real_auth_client.post(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": name, "scopes": scopes, "expires_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    return create_resp.json()["token"]


async def _create_project_environment_and_pipeline(
    real_auth_client,
    access_token: str,
) -> dict:
    suffix = uuid4().hex[:8]
    headers = {"Authorization": f"Bearer {access_token}"}

    project_resp = await real_auth_client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"scope-project-{suffix}",
            "slug": f"scope-project-{suffix}",
            "git_url": "https://example.com/scope-project.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 201, project_resp.text
    project = project_resp.json()

    env_resp = await real_auth_client.post(
        f"/api/v1/projects/{project['id']}/environments",
        headers=headers,
        json={
            "name": "default",
            "base_image": "python:3.12-alpine",
            "memory_mb": 128,
            "cpu_cores": 0.5,
            "network_policy": "deny",
            "env_vars": {},
        },
    )
    assert env_resp.status_code == 201, env_resp.text

    pipeline_resp = await real_auth_client.post(
        f"/api/v1/projects/{project['id']}/pipelines",
        headers=headers,
        json={
            "name": "scope-pipeline",
            "stages": [
                {
                    "name": "run-tests",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {},
                }
            ],
            "trigger_config": {"type": "manual"},
            "timeout_seconds": 120,
        },
    )
    assert pipeline_resp.status_code == 201, pipeline_resp.text

    return {
        "project_id": project["id"],
        "environment_id": env_resp.json()["id"],
        "pipeline_id": pipeline_resp.json()["id"],
    }


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class _MemoryBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.presign_calls: list[dict] = []

    async def put_object(self, *, Bucket, Key, Body, **_kwargs):
        if hasattr(Body, "read"):
            data = Body.read()
            if hasattr(data, "__await__"):
                data = await data
        else:
            data = Body
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.objects[(Bucket, Key)] = bytes(data)

    async def get_object(self, *, Bucket, Key):
        try:
            data = self.objects[(Bucket, Key)]
        except KeyError:
            raise _NoSuchKey(Key)
        return {"Body": _MemoryBody(data)}

    async def generate_presigned_url(self, method, *, Params, ExpiresIn):
        self.presign_calls.append(
            {"method": method, "params": Params, "expires_in": ExpiresIn}
        )
        return f"http://s3.local/{Params['Key']}?expires={ExpiresIn}"

    async def __aexit__(self, *_args):
        return None


class _FailingS3:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []

    async def put_object(self, *, Bucket, Key, Body, **_kwargs):
        self.put_calls.append({"bucket": Bucket, "key": Key})
        raise RuntimeError("s3 upload unavailable")


class _FlakyOnceS3(_MemoryS3):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1
        self.put_calls: list[dict] = []

    async def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.put_calls.append({"bucket": Bucket, "key": Key})
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("s3 transient outage")
        await super().put_object(Bucket=Bucket, Key=Key, Body=Body, **kwargs)


@pytest.mark.asyncio
async def test_real_jwt_created_api_token_authenticates_updates_last_used_and_revokes(
    real_auth_client,
    integration_db_session,
):
    from qaplatform.api.auth.token_service import TokenService
    from qaplatform.infra.database.models import ApiToken, AuditEvent

    suffix = uuid4().hex[:8]
    username = f"api_token_{suffix}"
    password = "correct-horse-battery"

    register_resp = await real_auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    access_token = register_resp.json()["access_token"]

    create_resp = await real_auth_client.post(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "ci-smoke", "scopes": ["project.read"], "expires_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    full_api_token = created["token"]
    parsed = TokenService.parse_bearer_token(full_api_token)
    assert parsed is not None
    token_id, secret = parsed
    assert token_id == created["token_id"]

    record = (
        await integration_db_session.execute(
            select(ApiToken).where(ApiToken.token_id == token_id)
        )
    ).scalar_one()
    assert record.name == "ci-smoke"
    assert record.scopes == ["project.read"]
    assert record.secret_hash != secret
    assert TokenService.verify_token(secret, record.secret_hash)
    assert record.last_used_at is None

    token_auth_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {full_api_token}"},
    )
    assert token_auth_resp.status_code == 200, token_auth_resp.text

    await integration_db_session.refresh(record)
    assert record.last_used_at is not None

    revoke_resp = await real_auth_client.delete(
        f"/api/v1/auth/tokens/{token_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert revoke_resp.status_code == 204, revoke_resp.text

    await integration_db_session.refresh(record)
    assert record.is_revoked is True

    rejected_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {full_api_token}"},
    )
    assert rejected_resp.status_code == 401, rejected_resp.text

    audit_actions = (
        await integration_db_session.execute(
            select(AuditEvent.action).where(
                AuditEvent.user_id == record.user_id,
                AuditEvent.action.in_(
                    ["auth.api_token_create", "auth.api_token_revoke"]
                ),
            )
        )
    ).scalars().all()
    assert {"auth.api_token_create", "auth.api_token_revoke"}.issubset(
        set(audit_actions)
    )


@pytest.mark.asyncio
async def test_real_sse_ticket_writes_audit_without_storing_ticket(
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent

    access_token = await _register_real_user(real_auth_client, prefix="sse_audit")

    resp = await real_auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert resp.status_code == 200, resp.text
    ticket = resp.json()["ticket"]
    assert ticket

    audit = (
        await integration_db_session.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "auth.sse_ticket_create")
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    assert audit.after_state == {"ttl_seconds": 90, "single_use": True}
    assert ticket not in str(audit.after_state)


@pytest.mark.asyncio
async def test_real_sse_logs_resume_after_last_event_id_uses_ticket_rbac_and_redis(
    real_auth_app,
    real_auth_client,
):
    from qaplatform.engine.events import publish_status_event
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import RunStatusEnum

    access_token = await _register_real_user(real_auth_client, prefix="sse_resume")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    redis = real_auth_app.state.container.redis_client
    stream = LogStream(redis)
    first_line = f"resume-before-{uuid4().hex}"
    second_line = f"resume-after-{uuid4().hex}"
    await stream.write_log(run_id, first_line, stream="stdout")
    await stream.write_log(run_id, second_line, stream="stderr")
    entries = await stream.read_logs(run_id, count=10)
    assert [entry["line"] for entry in entries] == [first_line, second_line]

    await publish_status_event(
        redis,
        run_id,
        RunStatusEnum.DONE.value,
        previous=RunStatusEnum.RUNNING.value,
    )

    ticket_resp = await real_auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert ticket_resp.status_code == 200, ticket_resp.text
    ticket = ticket_resp.json()["ticket"]

    resume_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={ticket}",
        headers={"Last-Event-ID": entries[0]["id"]},
    )
    assert resume_resp.status_code == 200, resume_resp.text
    assert "text/event-stream" in resume_resp.headers.get("content-type", "")
    assert first_line not in resume_resp.text
    assert second_line in resume_resp.text
    assert "event: done" in resume_resp.text
    assert '"status": "done"' in resume_resp.text

    reuse_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={ticket}",
        headers={"Last-Event-ID": entries[0]["id"]},
    )
    assert reuse_resp.status_code == 401, reuse_resp.text


@pytest.mark.asyncio
async def test_archived_logs_api_replays_s3_jsonl_after_real_rbac(
    real_auth_app,
    real_auth_client,
):
    from qaplatform.engine.log_stream import LogStream

    access_token = await _register_real_user(real_auth_client, prefix="log_archive")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    stream = LogStream(real_auth_app.state.container.redis_client)
    for index in range(5):
        await stream.write_log(
            run_id,
            f"archived-line-{index}",
            stream="stderr" if index == 3 else "stdout",
        )

    archived = await stream.archive_logs(
        run_id,
        s3,
        real_auth_app.state.container.settings.s3_bucket,
    )
    assert archived is True

    replay_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert replay_resp.status_code == 200, replay_resp.text
    body = replay_resp.json()
    assert body["total"] == 5
    assert body["data"][:2] == [
        {"stream": "stdout", "line": "archived-line-0"},
        {"stream": "stdout", "line": "archived-line-1"},
    ]

    page_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"page": 2, "per_page": 2},
    )
    assert page_resp.status_code == 200, page_resp.text
    page_body = page_resp.json()
    assert page_body["total"] == 5
    assert page_body["page"] == 2
    assert page_body["per_page"] == 2
    assert page_body["data"] == [
        {"stream": "stdout", "line": "archived-line-2"},
        {"stream": "stderr", "line": "archived-line-3"},
    ]


@pytest.mark.asyncio
async def test_log_archive_retry_worker_uses_real_redis_marker(real_auth_app):
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.worker.settings import retry_failed_archives

    retry_set = "run:logs:archive_failed"
    run_id = uuid4()
    redis = real_auth_app.state.container.redis_client
    stream = LogStream(redis)
    bucket = real_auth_app.state.container.settings.s3_bucket
    s3 = _FlakyOnceS3()
    stream_key = LogStream._stream_key(run_id)

    try:
        await stream.write_log(run_id, "retry-line-0", stream="stdout")
        await stream.write_log(run_id, "retry-line-1", stream="stderr")

        first_archive = await stream.archive_logs(run_id, s3, bucket)
        assert first_archive is False
        assert await redis.sismember(retry_set, str(run_id))
        failure_ttl = await redis.ttl(stream_key)
        assert 0 < failure_ttl <= 86400

        await retry_failed_archives(
            {
                "log_stream": stream,
                "s3_client": s3,
                "s3_bucket": bucket,
            }
        )

        assert s3.put_calls == [
            {"bucket": bucket, "key": f"logs/{run_id}.jsonl"},
            {"bucket": bucket, "key": f"logs/{run_id}.jsonl"},
        ]
        assert not await redis.sismember(retry_set, str(run_id))
        success_ttl = await redis.ttl(stream_key)
        assert 0 < success_ttl <= 3600
        assert await stream.read_archived_logs(run_id, s3, bucket) == [
            {"stream": "stdout", "line": "retry-line-0"},
            {"stream": "stderr", "line": "retry-line-1"},
        ]
    finally:
        await redis.srem(retry_set, str(run_id))
        await redis.delete(stream_key)


@pytest.mark.asyncio
async def test_archived_logs_api_returns_404_when_s3_object_missing(
    real_auth_app,
    real_auth_client,
):
    access_token = await _register_real_user(real_auth_client, prefix="log_missing")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    real_auth_app.state.container.s3_client = _MemoryS3()
    replay_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert replay_resp.status_code == 404, replay_resp.text
    error = replay_resp.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["message"] == "Archived logs not found"


@pytest.mark.asyncio
async def test_artifact_download_url_uses_real_auth_rbac_and_db_row(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_dl")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    storage_path = f"reports/{run_id}/summary.html"
    artifact_repo = ArtifactRepository(integration_db_session)
    artifact = await artifact_repo.create(
        run_id=run_id,
        type="html",
        name="summary.html",
        storage_path=storage_path,
        size_bytes=128,
        mime_type="text/html",
    )
    await integration_db_session.commit()

    headers = {"Authorization": f"Bearer {access_token}"}
    list_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/artifacts",
        headers=headers,
    )
    assert list_resp.status_code == 200, list_resp.text
    list_body = list_resp.json()
    assert list_body["total"] == 1
    assert list_body["data"][0]["id"] == str(artifact.id)
    assert list_body["data"][0]["storage_path"] == storage_path

    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    download_resp = await real_auth_client.get(
        f"/api/v1/artifacts/{artifact.id}/download",
        headers=headers,
    )
    assert download_resp.status_code == 200, download_resp.text
    download_body = download_resp.json()
    ttl = real_auth_app.state.container.settings.s3_presigned_url_ttl
    assert download_body == {
        "download_url": f"http://s3.local/{storage_path}?expires={ttl}",
        "expires_in": ttl,
    }
    assert s3.presign_calls == [
        {
            "method": "get_object",
            "params": {
                "Bucket": real_auth_app.state.container.settings.s3_bucket,
                "Key": storage_path,
            },
            "expires_in": ttl,
        }
    ]


@pytest.mark.asyncio
async def test_artifact_upload_enforces_limits_before_real_db_rows(
    integration_db_session,
    seed_run,
    tmp_path,
):
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.engine.executor import RunExecutor
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "a.txt").write_bytes(b"ok")
    (results_dir / "b.txt").write_bytes(b"too-large")
    (results_dir / "c.txt").write_bytes(b"ok")
    (results_dir / "d.txt").write_bytes(b"ok")

    s3 = _MemoryS3()
    log_stream = AsyncMock()
    artifact_repo = ArtifactRepository(integration_db_session)
    executor = RunExecutor(
        backend=AsyncMock(),
        log_stream=log_stream,
        run_repo=AsyncMock(),
        s3_client=s3,
        s3_bucket="qa-platform-test",
        artifact_repo=artifact_repo,
    )

    await executor._upload_artifacts(
        str(run_id),
        tmp_path,
        ResourceLimits(max_artifact_size_bytes=2, max_artifacts_count=2),
    )
    await integration_db_session.commit()

    rows, total = await artifact_repo.list_by_run(run_id, limit=10)
    assert total == 2
    assert {row.name for row in rows} == {"a.txt", "c.txt"}
    assert {
        key for _bucket, key in s3.objects
    } == {
        f"reports/{run_id}/a.txt",
        f"reports/{run_id}/c.txt",
    }
    log_lines = [call.args[1] for call in log_stream.write_log.await_args_list]
    assert any("exceeds limit" in line and "b.txt" in line for line in log_lines)
    assert any("count limit exceeded" in line and "d.txt" in line for line in log_lines)


@pytest.mark.asyncio
async def test_artifact_upload_s3_failure_leaves_no_real_db_rows(
    integration_db_session,
    seed_run,
    tmp_path,
):
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.engine.executor import RunExecutor
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "summary.html").write_text("<html>failed upload</html>")

    s3 = _FailingS3()
    artifact_repo = ArtifactRepository(integration_db_session)
    executor = RunExecutor(
        backend=AsyncMock(),
        log_stream=AsyncMock(),
        run_repo=AsyncMock(),
        s3_client=s3,
        s3_bucket="qa-platform-test",
        artifact_repo=artifact_repo,
    )

    await executor._upload_artifacts(
        str(run_id),
        tmp_path,
        ResourceLimits(max_artifact_size_bytes=1024, max_artifacts_count=10),
    )
    await integration_db_session.commit()

    rows, total = await artifact_repo.list_by_run(run_id, limit=10)
    assert rows == []
    assert total == 0
    assert s3.put_calls == [
        {
            "bucket": "qa-platform-test",
            "key": f"reports/{run_id}/summary.html",
        }
    ]


@pytest.mark.asyncio
async def test_artifact_upload_recurses_allure_report_with_real_db_rows(
    integration_db_session,
    seed_run,
    tmp_path,
):
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.engine.executor import RunExecutor
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    results_dir = tmp_path / "results"
    (results_dir / "allure-report" / "assets").mkdir(parents=True)
    (results_dir / "allure-report" / "index.html").write_text("<html/>")
    (results_dir / "allure-report" / "assets" / "app.js").write_text("ok")

    s3 = _MemoryS3()
    artifact_repo = ArtifactRepository(integration_db_session)
    executor = RunExecutor(
        backend=AsyncMock(),
        log_stream=AsyncMock(),
        run_repo=AsyncMock(),
        s3_client=s3,
        s3_bucket="qa-platform-test",
        artifact_repo=artifact_repo,
    )

    await executor._upload_artifacts(
        str(run_id),
        tmp_path,
        ResourceLimits(max_artifact_size_bytes=1024, max_artifacts_count=10),
    )
    await integration_db_session.commit()

    rows, total = await artifact_repo.list_by_run(run_id, limit=10)
    by_name = {row.name: row for row in rows}
    assert total == 2
    assert set(by_name) == {
        "allure-report/assets/app.js",
        "allure-report/index.html",
    }
    assert by_name["allure-report/index.html"].type == "allure-report"
    assert by_name["allure-report/index.html"].mime_type == "text/html"
    assert by_name["allure-report/assets/app.js"].type == "allure-report"
    assert {
        key for _bucket, key in s3.objects
    } == {
        f"reports/{run_id}/allure-report/assets/app.js",
        f"reports/{run_id}/allure-report/index.html",
    }


@pytest.mark.asyncio
async def test_api_token_scope_matrix_enforced_by_real_routes(
    real_auth_client,
):
    access_token = await _register_real_user(real_auth_client, prefix="scope_matrix")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="read-only",
        scopes=["project.read"],
    )
    read_headers = {"Authorization": f"Bearer {read_token}"}
    read_resp = await real_auth_client.get("/api/v1/projects", headers=read_headers)
    assert read_resp.status_code == 200, read_resp.text

    denied_write = await real_auth_client.post(
        "/api/v1/projects",
        headers=read_headers,
        json={
            "name": "denied",
            "slug": f"denied-{uuid4().hex[:8]}",
            "git_url": "https://example.com/denied.git",
        },
    )
    assert denied_write.status_code == 403, denied_write.text

    run_trigger_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="run-trigger-only",
        scopes=["run.trigger"],
    )
    run_headers = {"Authorization": f"Bearer {run_trigger_token}"}
    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers=run_headers,
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text

    denied_schedule = await real_auth_client.post(
        f"/api/v1/projects/{stack['project_id']}/schedules",
        headers=run_headers,
        json={
            "pipeline_id": stack["pipeline_id"],
            "cron_expr": "*/15 * * * *",
            "timezone": "UTC",
            "missed_fire_policy": "skip",
            "quiet_windows": [],
            "enabled": True,
        },
    )
    assert denied_schedule.status_code == 403, denied_schedule.text

    wrong_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="wrong-scope",
        scopes=["run.read"],
    )
    wrong_scope_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {wrong_scope_token}"},
    )
    assert wrong_scope_resp.status_code == 403, wrong_scope_resp.text

    empty_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="empty-scope",
        scopes=[],
    )
    empty_scope_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {empty_scope_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert empty_scope_resp.status_code == 403, empty_scope_resp.text


@pytest.mark.asyncio
async def test_run_results_api_filters_real_rows_and_recovers_after_duplicate(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import TestResultStatusEnum
    from qaplatform.infra.database.repositories.run_repo import TestResultRepository

    run_id = seed_run["run"].id
    repo = TestResultRepository(integration_db_session)

    await repo.bulk_create(
        [
            {
                "run_id": run_id,
                "suite": "checkout",
                "name": "test_cart_total",
                "status": TestResultStatusEnum.PASSED,
                "duration_ms": 42,
                "tags": ["smoke"],
                "metadata_": {"node": "gw0"},
            },
            {
                "run_id": run_id,
                "suite": "checkout",
                "name": "test_payment_decline",
                "status": TestResultStatusEnum.FAILED,
                "duration_ms": 87,
                "error_message": "AssertionError: card declined",
                "tags": ["payments"],
                "metadata_": {"node": "gw1"},
            },
        ]
    )
    await integration_db_session.commit()

    resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"status": "failed", "suite": "checkout", "q": "card"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["name"] == "test_payment_decline"
    assert body["data"][0]["status"] == "failed"

    with pytest.raises(IntegrityError):
        await repo.bulk_create(
            [
                {
                    "run_id": run_id,
                    "suite": "checkout",
                    "name": "test_payment_decline",
                    "status": TestResultStatusEnum.ERROR,
                    "duration_ms": 1,
                    "tags": [],
                    "metadata_": {},
                }
            ]
        )
        await integration_db_session.commit()

    await integration_db_session.rollback()

    after_rollback_resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"suite": "checkout", "per_page": 100},
    )
    assert after_rollback_resp.status_code == 200, after_rollback_resp.text
    after_rollback_body = after_rollback_resp.json()
    assert after_rollback_body["total"] == 2
    assert {
        item["name"] for item in after_rollback_body["data"]
    } == {"test_cart_total", "test_payment_decline"}


@pytest.mark.asyncio
async def test_run_artifacts_api_hides_soft_deleted_real_rows(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    repo = ArtifactRepository(integration_db_session)

    visible = await repo.create(
        run_id=run_id,
        type="report",
        name="summary.html",
        storage_path=f"runs/{run_id}/summary.html",
        size_bytes=2048,
        mime_type="text/html",
    )
    deleted = await repo.create(
        run_id=run_id,
        type="trace",
        name="trace.zip",
        storage_path=f"runs/{run_id}/trace.zip",
        size_bytes=4096,
        mime_type="application/zip",
    )
    await repo.delete(deleted)
    await integration_db_session.commit()

    repo_items, repo_total = await repo.list_by_run(run_id, limit=100)
    assert repo_total == 1
    assert [item.id for item in repo_items] == [visible.id]

    resp = await integration_client.get(f"/api/v1/runs/{run_id}/artifacts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["id"] == str(visible.id)
    assert body["data"][0]["name"] == "summary.html"
