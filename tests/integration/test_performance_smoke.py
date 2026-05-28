"""Nightly/manual backend nonfunctional smoke checks.

These tests are intentionally opt-in because local and hosted CI runners vary
too much for p99 product SLOs to be reliable PR blockers. They provide a stable
trend signal for the backend paths called out in the test strategy.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import socket
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from sqlalchemy import func, select

pytestmark = [
    pytest.mark.performance,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
    pytest.mark.skipif(
        os.environ.get("RUN_PERFORMANCE_TESTS") != "1",
        reason="set RUN_PERFORMANCE_TESTS=1 to run performance smoke tests",
    ),
]


def _threshold(name: str, default_ms: float) -> float:
    return float(os.environ.get(name, str(default_ms)))


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _assert_p99_under(name: str, samples: list[float], threshold_ms: float) -> None:
    p50 = _percentile(samples, 0.50)
    p99 = _percentile(samples, 0.99)
    worst = max(samples)
    if p99 > threshold_ms:
        pytest.fail(
            f"{name} p99 {p99:.1f}ms exceeded {threshold_ms:.1f}ms "
            f"(p50={p50:.1f}ms max={worst:.1f}ms samples={len(samples)})"
        )


def _decode_redis_mapping(mapping: dict) -> dict[str, str]:
    return {
        key.decode() if isinstance(key, bytes) else key: (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in mapping.items()
    }


async def _timed(awaitable) -> tuple[float, object]:
    started = perf_counter()
    result = await awaitable
    return (perf_counter() - started) * 1000, result


@asynccontextmanager
async def _real_auth_perf_client(test_settings):
    from qaplatform.api import create_app
    from qaplatform.dependencies import init_container
    from qaplatform.plugins.registry import PluginRegistry

    settings = test_settings.model_copy(
        update={
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
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield app, client
    finally:
        app.dependency_overrides.clear()
        await container.close()


async def _register_perf_user(client, *, prefix: str) -> dict:
    suffix = uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_perf_api_token(
    client,
    access_token: str,
    *,
    name: str,
    scopes: list[str],
) -> str:
    response = await client.post(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": name, "scopes": scopes, "expires_days": 7},
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


async def _create_perf_project_environment_and_pipeline(
    client,
    access_token: str,
) -> dict:
    suffix = uuid4().hex[:8]
    headers = {"Authorization": f"Bearer {access_token}"}

    project_resp = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"perf-project-{suffix}",
            "slug": f"perf-project-{suffix}",
            "git_url": "https://example.com/perf-project.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 201, project_resp.text
    project = project_resp.json()

    env_resp = await client.post(
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

    pipeline_resp = await client.post(
        f"/api/v1/projects/{project['id']}/pipelines",
        headers=headers,
        json={
            "name": "perf-pipeline",
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


@asynccontextmanager
async def _live_asgi_server(app):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    host, port = sock.getsockname()

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        lifespan="off",
        log_level="warning",
        access_log=False,
        ws="none",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("uvicorn server did not start")

        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5)
        with suppress(OSError):
            sock.close()


class _MemoryBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.presign_calls: list[dict] = []
        self.get_calls: list[dict] = []

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
        self.get_calls.append({"bucket": Bucket, "key": Key})
        try:
            data = self.objects[(Bucket, Key)]
        except KeyError:
            raise _NoSuchKey(Key)
        return {"Body": _MemoryBody(data)}

    async def generate_presigned_url(self, method, *, Params, ExpiresIn):
        self.presign_calls.append(
            {
                "method": method,
                "params": dict(Params),
                "expires_in": ExpiresIn,
            }
        )
        return (
            f"https://s3.test/{Params['Bucket']}/{Params['Key']}"
            f"?method={method}&expires={ExpiresIn}"
        )

    async def __aexit__(self, *_args):
        return None


class _FakeArq:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(job_id=kwargs["_job_id"])


class _SummaryRunner:
    def build_command(self, _config):
        return "pytest --junitxml=results/junit.xml"


class _SummaryPluginRegistry:
    def __init__(self, collector) -> None:
        self._collector = collector

    def get_runner(self, _name):
        return _SummaryRunner()

    def get_collector(self, _name):
        return self._collector


class _SummaryBackend:
    def __init__(self, *, passed: int, failed: int, skipped: int, error: int) -> None:
        self._counts = {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "error": error,
        }
        self._workspace: Path | None = None

    async def create_execution(self, spec):
        self._workspace = next(
            Path(mount.source) for mount in spec.mounts if mount.target == "/workspace"
        )
        return f"summary-{uuid4().hex}"

    async def start(self, _execution_id):
        return None

    async def wait(self, _execution_id, _timeout):
        assert self._workspace is not None
        _write_junit_xml(self._workspace / "results" / "junit.xml", self._counts)
        now = datetime.now(timezone.utc)
        from qaplatform.engine.docker_backend import ExitResult

        return ExitResult(exit_code=0, started_at=now, finished_at=now)

    async def cleanup(self, _execution_id):
        return None

    async def stream_logs(self, _execution_id):
        if False:
            yield


def _write_junit_xml(path: Path, counts: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cases: list[str] = []
    index = 0
    for _ in range(counts["passed"]):
        cases.append(
            f'<testcase classname="perf.summary" name="test_pass_{index}" time="0.001" />'
        )
        index += 1
    for _ in range(counts["failed"]):
        cases.append(
            "<testcase classname=\"perf.summary\" "
            f'name="test_fail_{index}" time="0.001">'
            '<failure message="expected failure">stack</failure></testcase>'
        )
        index += 1
    for _ in range(counts["skipped"]):
        cases.append(
            "<testcase classname=\"perf.summary\" "
            f'name="test_skip_{index}" time="0.001">'
            '<skipped message="not selected" /></testcase>'
        )
        index += 1
    for _ in range(counts["error"]):
        cases.append(
            "<testcase classname=\"perf.summary\" "
            f'name="test_error_{index}" time="0.001">'
            '<error message="boom">trace</error></testcase>'
        )
        index += 1

    total = sum(counts.values())
    path.write_text(
        "<testsuite "
        'name="perf-summary" '
        f'tests="{total}" failures="{counts["failed"]}" '
        f'errors="{counts["error"]}" skipped="{counts["skipped"]}">'
        + "".join(cases)
        + "</testsuite>",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_read_run_api_p99_smoke(integration_client, seed_run):
    run_id = seed_run["run"].id
    samples: list[float] = []

    for _ in range(3):
        response = await integration_client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text

    for _ in range(30):
        elapsed_ms, response = await _timed(
            integration_client.get(f"/api/v1/runs/{run_id}")
        )
        assert response.status_code == 200, response.text
        samples.append(elapsed_ms)

    _assert_p99_under("read run API", samples, _threshold("PERF_READ_P99_MS", 750))


@pytest.mark.asyncio
async def test_write_run_api_p99_smoke(integration_app, integration_client, seed_run):
    integration_app.state.container.arq_pool = None
    pipeline_id = seed_run["pipeline"].id
    samples: list[float] = []

    for _ in range(20):
        elapsed_ms, response = await _timed(
            integration_client.post(
                "/api/v1/runs",
                json={
                    "pipeline_id": str(pipeline_id),
                    "git_ref": f"perf/{uuid4().hex}",
                    "priority": 1,
                },
            )
        )
        assert response.status_code == 201, response.text
        samples.append(elapsed_ms)

    _assert_p99_under("write run API", samples, _threshold("PERF_WRITE_P99_MS", 1500))


@pytest.mark.asyncio
async def test_trigger_run_enqueue_slo_smoke(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import AuditEvent, Run

    arq = _FakeArq()
    settings = integration_app.state.container.settings
    old_arq_pool = integration_app.state.container.arq_pool
    old_total = settings.max_concurrent_runs
    old_per_project = settings.max_concurrent_per_project
    integration_app.state.container.arq_pool = arq
    settings.max_concurrent_runs = 100
    settings.max_concurrent_per_project = 100

    pipeline_id = seed_run["pipeline"].id
    tenant_id = seed_run["tenant"].id
    user_id = seed_run["user"].id
    samples: list[float] = []
    triggered_refs: dict[UUID, str] = {}
    try:
        for _ in range(10):
            git_ref = f"perf-enqueue/{uuid4().hex}"
            started_at = datetime.now(timezone.utc)
            response = await integration_client.post(
                "/api/v1/runs",
                json={
                    "pipeline_id": str(pipeline_id),
                    "git_ref": git_ref,
                    "priority": 1,
                },
            )
            assert response.status_code == 201, response.text
            run_id = UUID(response.json()["id"])
            triggered_refs[run_id] = git_ref

            integration_db_session.expire_all()
            row = (
                await integration_db_session.execute(
                    select(Run).where(Run.id == run_id)
                )
            ).scalar_one()
            assert row.enqueued_at is not None, "triggered run was not enqueued"
            assert row.queue_name == "queue:medium"
            samples.append((row.enqueued_at - started_at).total_seconds() * 1000)
    finally:
        settings.max_concurrent_runs = old_total
        settings.max_concurrent_per_project = old_per_project
        integration_app.state.container.arq_pool = old_arq_pool

    audit_result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.user_id == user_id,
            AuditEvent.action == "run.trigger",
            AuditEvent.resource_type == "run",
            AuditEvent.resource_id.in_(list(triggered_refs)),
        )
    )
    audits_by_run_id = {event.resource_id: event for event in audit_result.scalars()}
    assert set(audits_by_run_id) == set(triggered_refs)
    for run_id, git_ref in triggered_refs.items():
        event = audits_by_run_id[run_id]
        assert event.before_state is None
        assert event.after_state is not None
        assert event.after_state["id"] == str(run_id)
        assert event.after_state["status"] == "queued"
        assert event.after_state["trigger_type"] == "manual"
        assert event.after_state["git_ref"] == git_ref
        assert event.after_state["priority"] == 1
        assert event.after_state["pipeline_id"] == str(pipeline_id)

    assert len(arq.calls) == 10
    _assert_p99_under(
        "trigger enqueue SLO",
        samples,
        _threshold("PERF_TRIGGER_ENQUEUE_P99_MS", 5000),
    )


@pytest.mark.asyncio
async def test_webhook_trigger_enqueue_slo_smoke(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import AuditEvent, Run

    arq = _FakeArq()
    settings = integration_app.state.container.settings
    old_arq_pool = integration_app.state.container.arq_pool
    old_total = settings.max_concurrent_runs
    old_per_project = settings.max_concurrent_per_project
    integration_app.state.container.arq_pool = arq
    settings.max_concurrent_runs = 100
    settings.max_concurrent_per_project = 100

    project = seed_run["project"]
    pipeline_id = seed_run["pipeline"].id
    environment_id = seed_run["environment"].id
    tenant_id = seed_run["tenant"].id
    user_id = seed_run["user"].id
    leaked_url = "https://attacker.example/secret.git"
    leaked_credential = str(uuid4())
    samples: list[float] = []
    triggered_payloads: dict[UUID, dict[str, str]] = {}
    try:
        for _ in range(10):
            delivery_id = f"perf-webhook-{uuid4().hex}"
            git_sha = f"perf-webhook-{uuid4().hex}"
            started_at = datetime.now(timezone.utc)
            response = await integration_client.post(
                f"/api/v1/webhooks/{project.id}/trigger",
                json={
                    "git_ref": "refs/heads/main",
                    "git_sha": git_sha,
                    "metadata": {
                        "provider": "github",
                        "delivery_id": delivery_id,
                        "git_url": leaked_url,
                        "credential_id": leaked_credential,
                        "default_branch": "evil",
                    },
                },
            )
            assert response.status_code == 201, response.text
            run_id = UUID(response.json()["id"])
            triggered_payloads[run_id] = {
                "delivery_id": delivery_id,
                "git_sha": git_sha,
            }

            integration_db_session.expire_all()
            row = (
                await integration_db_session.execute(
                    select(Run).where(Run.id == run_id)
                )
            ).scalar_one()
            assert row.enqueued_at is not None, "webhook run was not enqueued"
            assert row.queue_name == "queue:medium"
            assert row.trigger_type == "webhook"
            assert row.pipeline_id == pipeline_id
            assert row.environment_id == environment_id
            assert row.metadata_["git_url"] == project.git_url
            assert row.metadata_["delivery_id"] == delivery_id
            serialized_metadata = repr(row.metadata_)
            assert leaked_url not in serialized_metadata
            assert leaked_credential not in serialized_metadata
            assert "evil" not in serialized_metadata
            samples.append((row.enqueued_at - started_at).total_seconds() * 1000)
    finally:
        settings.max_concurrent_runs = old_total
        settings.max_concurrent_per_project = old_per_project
        integration_app.state.container.arq_pool = old_arq_pool

    audit_result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.user_id == user_id,
            AuditEvent.action == "run.trigger",
            AuditEvent.resource_type == "run",
            AuditEvent.resource_id.in_(list(triggered_payloads)),
        )
    )
    audits_by_run_id = {event.resource_id: event for event in audit_result.scalars()}
    assert set(audits_by_run_id) == set(triggered_payloads)
    for run_id, payload in triggered_payloads.items():
        event = audits_by_run_id[run_id]
        assert event.before_state is None
        assert event.after_state is not None
        assert event.after_state["id"] == str(run_id)
        assert event.after_state["status"] == "queued"
        assert event.after_state["trigger_type"] == "webhook"
        assert event.after_state["git_ref"] == "refs/heads/main"
        assert event.after_state["git_sha"] == payload["git_sha"]
        assert event.after_state["pipeline_id"] == str(pipeline_id)
        assert event.after_state["environment_id"] == str(environment_id)
        serialized_audit = repr(event.after_state)
        assert leaked_url not in serialized_audit
        assert leaked_credential not in serialized_audit
        assert payload["delivery_id"] not in serialized_audit

    assert len(arq.calls) == 10
    _assert_p99_under(
        "webhook trigger enqueue SLO",
        samples,
        _threshold("PERF_WEBHOOK_TRIGGER_ENQUEUE_P99_MS", 5000),
    )


@pytest.mark.asyncio
async def test_schedule_tick_enqueue_slo_smoke(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from qaplatform.infra.database.models import AuditEvent, Run, Schedule
    from qaplatform.worker.settings import check_schedules

    arq = _FakeArq()
    ctx = {
        "db_session_factory": async_sessionmaker(
            integration_db_engine,
            expire_on_commit=False,
        ),
        "arq_pool": arq,
        "settings": SimpleNamespace(
            max_concurrent_runs=100,
            max_concurrent_per_project=100,
        ),
    }
    project = seed_run["project"]
    project_id = project.id
    tenant_id = project.tenant_id
    project_default_branch = project.default_branch
    pipeline_id = seed_run["pipeline"].id
    environment_id = seed_run["environment"].id
    samples: list[float] = []
    run_schedule_ids: dict[UUID, UUID] = {}

    for _ in range(10):
        schedule = Schedule(
            project_id=project_id,
            pipeline_id=pipeline_id,
            cron_expr="* * * * *",
            timezone="UTC",
            missed_fire_policy="skip",
            quiet_windows=[],
            enabled=True,
            next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        integration_db_session.add(schedule)
        await integration_db_session.commit()
        await integration_db_session.refresh(schedule)
        schedule_id = schedule.id

        started_at = datetime.now(timezone.utc)
        await check_schedules(ctx)

        integration_db_session.expire_all()
        refreshed_schedule = await integration_db_session.get(Schedule, schedule_id)
        assert refreshed_schedule is not None
        assert refreshed_schedule.last_run_at is not None
        assert refreshed_schedule.last_error is None
        assert refreshed_schedule.next_run_at is not None

        run_result = await integration_db_session.execute(
            select(Run).where(
                Run.project_id == project_id,
                Run.trigger_type == "schedule",
            )
        )
        schedule_runs = [
            run
            for run in run_result.scalars()
            if (run.metadata_ or {}).get("schedule_id") == str(schedule_id)
        ]
        assert len(schedule_runs) == 1
        run = schedule_runs[0]
        assert run.enqueued_at is not None, "schedule run was not enqueued"
        assert run.queue_name == "queue:low"
        assert run.arq_job_id == f"run:{run.id}"
        assert run.pipeline_id == pipeline_id
        assert run.environment_id == environment_id
        assert run.git_ref == project_default_branch
        assert run.triggered_by is None
        run_schedule_ids[run.id] = schedule_id
        samples.append((run.enqueued_at - started_at).total_seconds() * 1000)

    audit_result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.user_id.is_(None),
            AuditEvent.action == "run.trigger",
            AuditEvent.resource_type == "run",
            AuditEvent.resource_id.in_(list(run_schedule_ids)),
        )
    )
    audits_by_run_id = {event.resource_id: event for event in audit_result.scalars()}
    assert set(audits_by_run_id) == set(run_schedule_ids)
    for run_id, schedule_id in run_schedule_ids.items():
        event = audits_by_run_id[run_id]
        assert event.before_state is None
        assert event.after_state is not None
        assert event.after_state["id"] == str(run_id)
        assert event.after_state["status"] == "queued"
        assert event.after_state["trigger_type"] == "schedule"
        assert event.after_state["triggered_by"] is None
        assert event.after_state["git_ref"] == project_default_branch
        assert event.after_state["project_id"] == str(project_id)
        assert event.after_state["pipeline_id"] == str(pipeline_id)
        assert event.after_state["environment_id"] == str(environment_id)
        assert event.after_state["schedule_id"] == str(schedule_id)
        assert event.after_state["metadata"]["schedule_id"] == str(schedule_id)
        assert event.after_state["enqueued"] is True

    assert len(arq.calls) == 10
    assert {call["kwargs"]["_queue_name"] for call in arq.calls} == {"queue:low"}
    _assert_p99_under(
        "schedule tick enqueue SLO",
        samples,
        _threshold("PERF_SCHEDULE_TICK_ENQUEUE_P99_MS", 5000),
    )


@pytest.mark.asyncio
async def test_dequeue_waiting_runs_slo_smoke(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.worker.settings import dequeue_waiting

    arq = _FakeArq()
    ctx = {
        "db_session_factory": async_sessionmaker(
            integration_db_engine,
            expire_on_commit=False,
        ),
        "arq_pool": arq,
        "settings": SimpleNamespace(
            max_concurrent_runs=10_000,
            max_concurrent_per_project=10_000,
        ),
    }
    tenant_id = seed_run["tenant"].id
    project_id = seed_run["project"].id
    pipeline_id = seed_run["pipeline"].id
    environment_id = seed_run["environment"].id
    user_id = seed_run["user"].id
    seed_run["run"].queue_name = "queue:medium"
    seed_run["run"].arq_job_id = f"run:{seed_run['run'].id}"
    seed_run["run"].enqueued_at = datetime.now(timezone.utc)
    await integration_db_session.commit()

    queue_by_priority = {
        0: "queue:high",
        1: "queue:medium",
        2: "queue:low",
    }
    priorities = [0, 1, 2, 0, 1, 2, 0, 1, 2, 1]
    waiting_runs: dict[UUID, tuple[int, str]] = {}
    base_created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    for index, priority in enumerate(priorities):
        run = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            pipeline_id=pipeline_id,
            environment_id=environment_id,
            status=RunStatusEnum.QUEUED,
            trigger_type="manual",
            priority=priority,
            triggered_by=user_id,
            git_ref=f"perf-dequeue/{priority}/{uuid4().hex}",
            attempt=1,
            chain_depth=0,
            metadata_={"perf_dequeue": True, "priority": priority},
            created_at=base_created_at + timedelta(milliseconds=index),
        )
        integration_db_session.add(run)
        await integration_db_session.flush()
        waiting_runs[run.id] = (priority, queue_by_priority[priority])
    await integration_db_session.commit()

    started_at = datetime.now(timezone.utc)
    rows_by_id: dict[UUID, Run] = {}
    # The integration DB is shared across this smoke file, so the cron may drain
    # older waiting seed runs before reaching the rows created by this test.
    for _ in range(100):
        await dequeue_waiting(ctx)
        integration_db_session.expire_all()
        result = await integration_db_session.execute(
            select(Run).where(Run.id.in_(list(waiting_runs)))
        )
        rows_by_id = {run.id: run for run in result.scalars()}
        if rows_by_id and all(run.enqueued_at is not None for run in rows_by_id.values()):
            break
    else:
        missing = [
            str(run_id)
            for run_id, run in rows_by_id.items()
            if run.enqueued_at is None
        ]
        pytest.fail(f"waiting runs were not dequeued: {missing}")

    assert set(rows_by_id) == set(waiting_runs)
    samples: list[float] = []
    for run_id, (priority, expected_queue) in waiting_runs.items():
        row = rows_by_id[run_id]
        assert row.status == RunStatusEnum.QUEUED
        assert row.priority == priority
        assert row.queue_name == expected_queue
        assert row.arq_job_id == f"run:{run_id}"
        assert row.enqueued_at is not None, "waiting run was not dequeued"
        assert row.metadata_ == {"perf_dequeue": True, "priority": priority}
        samples.append((row.enqueued_at - started_at).total_seconds() * 1000)

    expected_job_ids = {f"run:{run_id}" for run_id in waiting_runs}
    our_calls = [
        call for call in arq.calls if call["kwargs"]["_job_id"] in expected_job_ids
    ]
    assert len(our_calls) == len(waiting_runs)
    assert {call["kwargs"]["_queue_name"] for call in our_calls} == {
        "queue:high",
        "queue:medium",
        "queue:low",
    }
    assert {call["kwargs"]["_job_id"] for call in our_calls} == expected_job_ids
    _assert_p99_under(
        "dequeue waiting runs SLO",
        samples,
        _threshold("PERF_DEQUEUE_WAITING_P99_MS", 5000),
    )


@pytest.mark.asyncio
async def test_cancel_run_api_p99_smoke(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import STATUS_HASH_KEY
    from qaplatform.infra.database.models import AuditEvent, Run, RunStatusEnum

    tenant_id = seed_run["tenant"].id
    project_id = seed_run["project"].id
    pipeline_id = seed_run["pipeline"].id
    environment_id = seed_run["environment"].id
    user_id = seed_run["user"].id
    redis = integration_app.state.container.redis_client
    samples: list[float] = []

    for _ in range(10):
        run = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            pipeline_id=pipeline_id,
            environment_id=environment_id,
            status=RunStatusEnum.RUNNING,
            trigger_type="manual",
            priority=1,
            triggered_by=user_id,
            git_ref=f"perf-cancel/{uuid4().hex}",
            attempt=1,
            chain_depth=0,
            metadata_={"perf_cancel": True},
        )
        integration_db_session.add(run)
        await integration_db_session.commit()
        await integration_db_session.refresh(run)
        run_id = run.id

        elapsed_ms, response = await _timed(
            integration_client.post(f"/api/v1/runs/{run_id}/cancel")
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"
        samples.append(elapsed_ms)

        integration_db_session.expire_all()
        persisted = await integration_db_session.get(Run, run_id)
        assert persisted is not None
        assert persisted.status == RunStatusEnum.CANCELLED
        assert persisted.cancel_requested_at is not None

        status_hash = await redis.hgetall(STATUS_HASH_KEY.format(run_id=str(run_id)))
        assert _decode_redis_mapping(status_hash)["status"] == "cancelled"

        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "run.cancel",
                    AuditEvent.resource_id == run_id,
                )
            )
        ).scalar_one()
        assert audit.before_state["status"] == "running"
        assert audit.after_state["status"] == "cancelled"

    _assert_p99_under(
        "cancel run API",
        samples,
        _threshold("PERF_CANCEL_RUN_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_log_stream_round_trip_smoke(integration_app):
    from qaplatform.engine.log_stream import LogStream

    stream = LogStream(integration_app.state.container.redis_client)
    run_id = uuid4()
    samples: list[float] = []

    for index in range(20):
        elapsed_ms, _ = await _timed(
            stream.write_log(run_id, f"line-{index}", stream="stdout")
        )
        samples.append(elapsed_ms)

    entries = await stream.read_logs(run_id, count=20)
    assert len(entries) == 20
    assert entries[-1]["line"] == "line-19"
    _assert_p99_under("log stream write", samples, _threshold("PERF_LOG_WRITE_P99_MS", 2000))


@pytest.mark.asyncio
async def test_realtime_log_sse_delivery_latency_smoke(
    integration_app,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import publish_status_event
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import Run, RunStatusEnum

    tenant_id = seed_run["tenant"].id
    project_id = seed_run["project"].id
    pipeline_id = seed_run["pipeline"].id
    environment_id = seed_run["environment"].id
    user_id = seed_run["user"].id
    redis = integration_app.state.container.redis_client
    stream = LogStream(redis)
    samples: list[float] = []

    timeout = httpx.Timeout(5.0, connect=5.0, read=5.0)
    async with _live_asgi_server(integration_app) as base_url:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for index in range(5):
                run = Run(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    pipeline_id=pipeline_id,
                    environment_id=environment_id,
                    status=RunStatusEnum.RUNNING,
                    trigger_type="manual",
                    priority=1,
                    triggered_by=user_id,
                    git_ref=f"perf-sse/{uuid4().hex}",
                    attempt=1,
                    chain_depth=0,
                    metadata_={"perf_sse": True},
                )
                integration_db_session.add(run)
                await integration_db_session.commit()
                await integration_db_session.refresh(run)
                run_id = run.id

                ticket = f"perf-sse-{uuid4().hex}"
                await redis.setex(
                    f"sse_ticket:{ticket}",
                    90,
                    f"{user_id}:owner:{tenant_id}",
                )

                url = f"{base_url}/api/v1/runs/{run_id}/logs?ticket={ticket}"
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        pytest.fail(
                            f"SSE log stream returned {response.status_code}: "
                            f"{body.decode('utf-8', errors='replace')}"
                        )
                    assert "text/event-stream" in response.headers.get(
                        "content-type", ""
                    )

                    chunks: list[str] = []
                    line_seen_ms: float | None = None
                    expected_line = f"sse-latency-{index}-{uuid4().hex}"
                    started = perf_counter()
                    await stream.write_log(run_id, expected_line, stream="stdout")
                    await publish_status_event(
                        redis,
                        run_id,
                        RunStatusEnum.DONE.value,
                        previous=RunStatusEnum.RUNNING.value,
                    )
                    async for chunk in response.aiter_text():
                        chunks.append(chunk)
                        body = "".join(chunks)
                        if expected_line in body:
                            line_seen_ms = (perf_counter() - started) * 1000
                            break

                assert line_seen_ms is not None, "SSE log line was not delivered"
                samples.append(line_seen_ms)

    _assert_p99_under(
        "realtime log SSE delivery",
        samples,
        _threshold("PERF_SSE_LOG_DELIVERY_P99_MS", 2000),
    )


@pytest.mark.asyncio
async def test_realtime_status_event_sse_delivery_latency_smoke(
    integration_app,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import publish_status_event
    from qaplatform.infra.database.models import Run, RunStatusEnum

    tenant_id = seed_run["tenant"].id
    project_id = seed_run["project"].id
    pipeline_id = seed_run["pipeline"].id
    environment_id = seed_run["environment"].id
    user_id = seed_run["user"].id
    redis = integration_app.state.container.redis_client
    samples: list[float] = []

    timeout = httpx.Timeout(5.0, connect=5.0, read=5.0)
    async with _live_asgi_server(integration_app) as base_url:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for index in range(5):
                run = Run(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    pipeline_id=pipeline_id,
                    environment_id=environment_id,
                    status=RunStatusEnum.RUNNING,
                    trigger_type="manual",
                    priority=1,
                    triggered_by=user_id,
                    git_ref=f"perf-sse-events/{uuid4().hex}",
                    attempt=1,
                    chain_depth=0,
                    metadata_={"perf_sse_events": True},
                )
                integration_db_session.add(run)
                await integration_db_session.commit()
                await integration_db_session.refresh(run)
                run_id = run.id

                ticket = f"perf-sse-events-{uuid4().hex}"
                await redis.setex(
                    f"sse_ticket:{ticket}",
                    90,
                    f"{user_id}:owner:{tenant_id}",
                )

                url = f"{base_url}/api/v1/runs/{run_id}/events?ticket={ticket}"
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        pytest.fail(
                            f"SSE status event stream returned {response.status_code}: "
                            f"{body.decode('utf-8', errors='replace')}"
                        )
                    assert "text/event-stream" in response.headers.get(
                        "content-type", ""
                    )

                    chunks: list[str] = []
                    event_seen_ms: float | None = None
                    started = perf_counter()
                    await publish_status_event(
                        redis,
                        run_id,
                        RunStatusEnum.COLLECTING.value,
                        previous=RunStatusEnum.RUNNING.value,
                    )
                    await publish_status_event(
                        redis,
                        run_id,
                        RunStatusEnum.DONE.value,
                        previous=RunStatusEnum.COLLECTING.value,
                    )
                    async for chunk in response.aiter_text():
                        chunks.append(chunk)
                        body = "".join(chunks)
                        if (
                            "event: status_change" in body
                            and '"status": "collecting"' in body
                        ):
                            event_seen_ms = (perf_counter() - started) * 1000
                            break

                assert event_seen_ms is not None, (
                    f"SSE status event was not delivered for sample {index}"
                )
                samples.append(event_seen_ms)

    _assert_p99_under(
        "realtime status event SSE delivery",
        samples,
        _threshold("PERF_SSE_EVENT_DELIVERY_P99_MS", 2000),
    )


@pytest.mark.asyncio
async def test_archived_log_replay_api_p99_smoke(
    integration_app,
    integration_client,
    seed_run,
):
    from qaplatform.engine.log_stream import LogStream

    run_id = seed_run["run"].id
    s3 = _MemoryS3()
    old_s3 = integration_app.state.container.s3_client
    integration_app.state.container.s3_client = s3
    try:
        stream = LogStream(integration_app.state.container.redis_client)
        for index in range(50):
            await stream.write_log(run_id, f"archived-line-{index}", stream="stdout")
        assert await stream.archive_logs(
            run_id,
            s3,
            integration_app.state.container.settings.s3_bucket,
        )

        for _ in range(3):
            response = await integration_client.get(
                f"/api/v1/runs/{run_id}/logs/archive"
            )
            assert response.status_code == 200, response.text

        samples: list[float] = []
        for _ in range(20):
            elapsed_ms, response = await _timed(
                integration_client.get(f"/api/v1/runs/{run_id}/logs/archive")
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 50
            assert body["data"][-1]["line"] == "archived-line-49"
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    expected_get_call = {
        "bucket": integration_app.state.container.settings.s3_bucket,
        "key": f"logs/{run_id}.jsonl",
    }
    assert s3.get_calls == [expected_get_call] * 23
    assert s3.presign_calls == []
    _assert_p99_under(
        "archived log replay API",
        samples,
        _threshold("PERF_LOG_ARCHIVE_READ_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_archived_log_replay_large_page_p99_smoke(
    integration_app,
    integration_client,
    seed_run,
):
    run_id = seed_run["run"].id
    s3 = _MemoryS3()
    bucket = integration_app.state.container.settings.s3_bucket
    entries = [
        {
            "stream": "stderr" if index % 97 == 0 else "stdout",
            "line": f"archived-large-line-{index:04}",
        }
        for index in range(1500)
    ]
    archive_body = "\n".join(json.dumps(entry) for entry in entries).encode("utf-8")

    old_s3 = integration_app.state.container.s3_client
    integration_app.state.container.s3_client = s3
    try:
        await s3.put_object(
            Bucket=bucket,
            Key=f"logs/{run_id}.jsonl",
            Body=archive_body,
            ContentType="application/x-ndjson",
        )

        params = {"page": 15, "per_page": 100}
        for _ in range(3):
            response = await integration_client.get(
                f"/api/v1/runs/{run_id}/logs/archive",
                params=params,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 1500
            assert body["data"][0]["line"] == "archived-large-line-1400"

        samples: list[float] = []
        for _ in range(20):
            elapsed_ms, response = await _timed(
                integration_client.get(
                    f"/api/v1/runs/{run_id}/logs/archive",
                    params=params,
                )
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 1500
            assert body["page"] == 15
            assert body["per_page"] == 100
            assert len(body["data"]) == 100
            assert body["data"][0] == {
                "stream": "stdout",
                "line": "archived-large-line-1400",
            }
            assert body["data"][-1] == {
                "stream": "stdout",
                "line": "archived-large-line-1499",
            }
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    expected_get_call = {
        "bucket": bucket,
        "key": f"logs/{run_id}.jsonl",
    }
    assert s3.get_calls == [expected_get_call] * 23
    assert s3.presign_calls == []
    _assert_p99_under(
        "archived log large-page replay API",
        samples,
        _threshold("PERF_LOG_ARCHIVE_LARGE_PAGE_P99_MS", 1500),
    )


@pytest.mark.asyncio
async def test_archived_log_missing_object_p99_smoke(
    integration_app,
    integration_client,
    seed_run,
):
    run_id = seed_run["run"].id
    bucket = integration_app.state.container.settings.s3_bucket
    s3 = _MemoryS3()
    old_s3 = integration_app.state.container.s3_client
    integration_app.state.container.s3_client = s3
    try:
        for _ in range(3):
            response = await integration_client.get(
                f"/api/v1/runs/{run_id}/logs/archive"
            )
            assert response.status_code == 404, response.text
            error = response.json()["error"]
            assert error["code"] == "NOT_FOUND"
            assert error["message"] == "Archived logs not found"

        samples: list[float] = []
        for _ in range(20):
            elapsed_ms, response = await _timed(
                integration_client.get(f"/api/v1/runs/{run_id}/logs/archive")
            )
            assert response.status_code == 404, response.text
            error = response.json()["error"]
            assert error["code"] == "NOT_FOUND"
            assert error["message"] == "Archived logs not found"
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    expected_get_call = {
        "bucket": bucket,
        "key": f"logs/{run_id}.jsonl",
    }
    assert s3.get_calls == [expected_get_call] * 23
    assert s3.presign_calls == []
    _assert_p99_under(
        "archived log missing-object API",
        samples,
        _threshold("PERF_LOG_ARCHIVE_MISSING_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_archived_log_storage_unavailable_p99_smoke(
    integration_app,
    integration_client,
    seed_run,
):
    run_id = seed_run["run"].id
    headers = {"Authorization": f"Bearer perf-archive-storage-{run_id}"}
    old_s3 = integration_app.state.container.s3_client
    integration_app.state.container.s3_client = None
    try:
        for _ in range(3):
            response = await integration_client.get(
                f"/api/v1/runs/{run_id}/logs/archive",
                headers=headers,
            )
            assert response.status_code == 503, response.text
            assert response.json()["detail"] == "Archived logs are not available"

        samples: list[float] = []
        for _ in range(20):
            elapsed_ms, response = await _timed(
                integration_client.get(
                    f"/api/v1/runs/{run_id}/logs/archive",
                    headers=headers,
                )
            )
            assert response.status_code == 503, response.text
            assert response.json()["detail"] == "Archived logs are not available"
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    _assert_p99_under(
        "archived log storage-unavailable API",
        samples,
        _threshold("PERF_LOG_ARCHIVE_UNAVAILABLE_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_archived_log_denied_no_s3_read_p99_smoke(
    integration_app,
    integration_client_as,
    seed_run,
    seed_second_tenant,
):
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    run_b_id = seed_second_tenant["run"].id

    s3 = _MemoryS3()
    old_s3 = integration_app.state.container.s3_client
    integration_app.state.container.s3_client = s3
    samples: list[float] = []
    try:
        async with integration_client_as(user_a.id, tenant_a.id) as client:
            random_response = await client.get(
                f"/api/v1/runs/{uuid4()}/logs/archive"
            )
            assert random_response.status_code == 404, random_response.text
            expected_404 = random_response.json()

            for _ in range(3):
                response = await client.get(
                    f"/api/v1/runs/{run_b_id}/logs/archive"
                )
                assert response.status_code == 404, response.text
                assert response.json() == expected_404

            for _ in range(20):
                elapsed_ms, response = await _timed(
                    client.get(f"/api/v1/runs/{run_b_id}/logs/archive")
                )
                assert response.status_code == 404, response.text
                assert response.json() == expected_404
                assert s3.get_calls == []
                samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    assert s3.get_calls == []
    _assert_p99_under(
        "archived log denied no-S3-read API",
        samples,
        _threshold("PERF_LOG_ARCHIVE_DENIED_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_artifact_list_api_p99_smoke(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    repo = ArtifactRepository(integration_db_session)
    marker = f"perf-list-{uuid4().hex}"
    expected_names: set[str] = set()
    for index in range(80):
        name = f"{marker}-{index:03}.html"
        expected_names.add(name)
        await repo.create(
            run_id=run_id,
            type="report",
            name=name,
            storage_path=f"reports/{run_id}/{name}",
            size_bytes=1024 + index,
            mime_type="text/html",
        )
    await integration_db_session.commit()

    old_s3 = integration_app.state.container.s3_client
    s3 = _MemoryS3()
    integration_app.state.container.s3_client = s3
    params = {"page": 1, "per_page": 100}
    try:
        for _ in range(3):
            response = await integration_client.get(
                f"/api/v1/runs/{run_id}/artifacts",
                params=params,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] >= 80
            returned_names = {item["name"] for item in body["data"]}
            assert expected_names <= returned_names

        samples: list[float] = []
        for _ in range(20):
            elapsed_ms, response = await _timed(
                integration_client.get(
                    f"/api/v1/runs/{run_id}/artifacts",
                    params=params,
                )
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["page"] == 1
            assert body["per_page"] == 100
            assert body["total"] >= 80
            returned = {item["name"]: item for item in body["data"]}
            assert expected_names <= set(returned)
            for name in expected_names:
                item = returned[name]
                assert item["run_id"] == str(run_id)
                assert item["storage_path"] == f"reports/{run_id}/{name}"
                assert item["size_bytes"] >= 1024
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    assert s3.presign_calls == []
    assert s3.get_calls == []

    _assert_p99_under(
        "artifact list API",
        samples,
        _threshold("PERF_ARTIFACT_LIST_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_artifact_list_denied_no_metadata_p99_smoke(
    integration_client_as,
    integration_db_session,
    seed_run,
    seed_second_tenant,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    run_a_id = seed_run["run"].id
    run_b_id = seed_second_tenant["run"].id

    repo = ArtifactRepository(integration_db_session)
    marker = f"denied-list-{uuid4().hex}"
    artifact_names: set[str] = set()
    for index in range(20):
        name = f"{marker}-tenant-a-{index:02}.html"
        artifact_names.add(name)
        await repo.create(
            run_id=run_a_id,
            type="report",
            name=name,
            storage_path=f"reports/{run_a_id}/{name}",
            size_bytes=512 + index,
            mime_type="text/html",
        )
    tenant_b_name = f"{marker}-tenant-b-secret.html"
    artifact_names.add(tenant_b_name)
    await repo.create(
        run_id=run_b_id,
        type="report",
        name=tenant_b_name,
        storage_path=f"reports/{run_b_id}/{tenant_b_name}",
        size_bytes=2048,
        mime_type="text/html",
    )
    await integration_db_session.commit()

    def assert_no_artifact_metadata(response_text: str) -> None:
        assert marker not in response_text
        assert "reports/" not in response_text
        for name in artifact_names:
            assert name not in response_text

    samples: list[float] = []
    for role in ("member", "viewer"):
        async with integration_client_as(user_a.id, tenant_a.id, role=role) as client:
            for _ in range(6):
                elapsed_ms, response = await _timed(
                    client.get(
                        f"/api/v1/runs/{run_a_id}/artifacts",
                        params={"page": 1, "per_page": 100},
                    )
                )
                assert response.status_code == 403, response.text
                assert_no_artifact_metadata(response.text)
                samples.append(elapsed_ms)

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        for _ in range(8):
            elapsed_ms, response = await _timed(
                client.get(
                    f"/api/v1/runs/{run_b_id}/artifacts",
                    params={"page": 1, "per_page": 100},
                )
            )
            assert response.status_code == 404, response.text
            assert_no_artifact_metadata(response.text)
            samples.append(elapsed_ms)

    _assert_p99_under(
        "artifact list denied no-metadata API",
        samples,
        _threshold("PERF_ARTIFACT_LIST_DENIED_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_artifact_download_url_api_p99_smoke(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    repo = ArtifactRepository(integration_db_session)
    artifact = await repo.create(
        run_id=run_id,
        type="report",
        name="perf-summary.html",
        storage_path=f"reports/{run_id}/perf-summary.html",
        size_bytes=1024,
        mime_type="text/html",
    )
    await integration_db_session.commit()

    old_s3 = integration_app.state.container.s3_client
    s3 = _MemoryS3()
    integration_app.state.container.s3_client = s3
    samples: list[float] = []
    try:
        for _ in range(3):
            response = await integration_client.get(
                f"/api/v1/artifacts/{artifact.id}/download"
            )
            assert response.status_code == 200, response.text

        for _ in range(20):
            elapsed_ms, response = await _timed(
                integration_client.get(f"/api/v1/artifacts/{artifact.id}/download")
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert (
                body["expires_in"]
                == integration_app.state.container.settings.s3_presigned_url_ttl
            )
            assert f"/reports/{run_id}/perf-summary.html" in body["download_url"]
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    assert s3.get_calls == []
    assert len(s3.presign_calls) == 23
    assert all(call["method"] == "get_object" for call in s3.presign_calls)
    assert all(
        call["params"]
        == {
            "Bucket": integration_app.state.container.settings.s3_bucket,
            "Key": artifact.storage_path,
        }
        for call in s3.presign_calls
    )
    assert all(
        call["expires_in"]
        == integration_app.state.container.settings.s3_presigned_url_ttl
        for call in s3.presign_calls
    )
    _assert_p99_under(
        "artifact download URL API",
        samples,
        _threshold("PERF_ARTIFACT_DOWNLOAD_URL_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_artifact_download_storage_unavailable_p99_smoke(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    repo = ArtifactRepository(integration_db_session)
    artifact = await repo.create(
        run_id=run_id,
        type="report",
        name="perf-storage-unavailable.html",
        storage_path=f"reports/{run_id}/perf-storage-unavailable.html",
        size_bytes=2048,
        mime_type="text/html",
    )
    await integration_db_session.commit()

    headers = {"Authorization": f"Bearer perf-artifact-storage-{artifact.id}"}
    old_s3 = integration_app.state.container.s3_client
    integration_app.state.container.s3_client = None
    try:
        for _ in range(3):
            response = await integration_client.get(
                f"/api/v1/artifacts/{artifact.id}/download",
                headers=headers,
            )
            assert response.status_code == 503, response.text
            assert response.json()["detail"] == "Artifact download is not available"

        samples: list[float] = []
        for _ in range(20):
            elapsed_ms, response = await _timed(
                integration_client.get(
                    f"/api/v1/artifacts/{artifact.id}/download",
                    headers=headers,
                )
            )
            assert response.status_code == 503, response.text
            assert response.json()["detail"] == "Artifact download is not available"
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    _assert_p99_under(
        "artifact download storage-unavailable API",
        samples,
        _threshold("PERF_ARTIFACT_DOWNLOAD_UNAVAILABLE_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_artifact_download_url_burst_p99_smoke(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    repo = ArtifactRepository(integration_db_session)
    artifacts = []
    for index in range(40):
        name = f"burst-download-{index:03}.html"
        artifact = await repo.create(
            run_id=run_id,
            type="report",
            name=name,
            storage_path=f"reports/{run_id}/{name}",
            size_bytes=2048 + index,
            mime_type="text/html",
        )
        artifacts.append(artifact)
    await integration_db_session.commit()

    old_s3 = integration_app.state.container.s3_client
    s3 = _MemoryS3()
    integration_app.state.container.s3_client = s3
    samples: list[float] = []
    try:
        for artifact in artifacts[:3]:
            response = await integration_client.get(
                f"/api/v1/artifacts/{artifact.id}/download"
            )
            assert response.status_code == 200, response.text

        for artifact in artifacts:
            elapsed_ms, response = await _timed(
                integration_client.get(f"/api/v1/artifacts/{artifact.id}/download")
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert (
                body["expires_in"]
                == integration_app.state.container.settings.s3_presigned_url_ttl
            )
            assert f"/{artifact.storage_path}" in body["download_url"]
            samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    expected_presigned_keys = [
        artifact.storage_path for artifact in artifacts[:3]
    ] + [artifact.storage_path for artifact in artifacts]
    assert s3.get_calls == []
    assert [call["method"] for call in s3.presign_calls] == [
        "get_object"
    ] * len(expected_presigned_keys)
    assert [call["params"] for call in s3.presign_calls] == [
        {
            "Bucket": integration_app.state.container.settings.s3_bucket,
            "Key": key,
        }
        for key in expected_presigned_keys
    ]
    assert [call["expires_in"] for call in s3.presign_calls] == [
        integration_app.state.container.settings.s3_presigned_url_ttl
    ] * len(expected_presigned_keys)
    _assert_p99_under(
        "artifact download URL burst API",
        samples,
        _threshold("PERF_ARTIFACT_DOWNLOAD_BURST_P99_MS", 1500),
    )


@pytest.mark.asyncio
async def test_artifact_download_denied_no_presign_p99_smoke(
    integration_app,
    integration_client_as,
    seed_run,
    seed_second_tenant,
):
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    artifact_b_id = seed_second_tenant["artifact"].id

    s3 = _MemoryS3()
    old_s3 = integration_app.state.container.s3_client
    integration_app.state.container.s3_client = s3
    samples: list[float] = []
    try:
        async with integration_client_as(user_a.id, tenant_a.id) as client:
            random_response = await client.get(
                f"/api/v1/artifacts/{uuid4()}/download"
            )
            assert random_response.status_code == 404, random_response.text
            expected_404 = random_response.json()

            for _ in range(3):
                response = await client.get(
                    f"/api/v1/artifacts/{artifact_b_id}/download"
                )
                assert response.status_code == 404, response.text
                assert response.json() == expected_404

            for _ in range(20):
                elapsed_ms, response = await _timed(
                    client.get(f"/api/v1/artifacts/{artifact_b_id}/download")
                )
                assert response.status_code == 404, response.text
                assert response.json() == expected_404
                assert s3.presign_calls == []
                samples.append(elapsed_ms)
    finally:
        integration_app.state.container.s3_client = old_s3

    assert s3.presign_calls == []
    assert s3.get_calls == []
    _assert_p99_under(
        "artifact download denied no-presign API",
        samples,
        _threshold("PERF_ARTIFACT_DOWNLOAD_DENIED_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_audit_events_list_api_p99_smoke(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import AuditEvent

    tenant_id = seed_run["tenant"].id
    user_id = seed_run["user"].id
    project_id = seed_run["project"].id
    action = "audit.performance_probe"
    now = datetime.now(timezone.utc)

    for index in range(120):
        integration_db_session.add(
            AuditEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                resource_type="project",
                resource_id=project_id,
                after_state={"index": index},
                created_at=now - timedelta(seconds=index),
            )
        )
    await integration_db_session.commit()

    async def count_self_audits() -> int:
        result = await integration_db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.user_id == user_id,
                AuditEvent.action == "audit_events.list",
                AuditEvent.resource_type == "audit_event",
            )
        )
        return result.scalar_one()

    before_self_audits = await count_self_audits()
    params = {
        "action": action,
        "resource_type": "project",
        "per_page": 50,
    }
    for _ in range(3):
        response = await integration_client.get("/api/v1/audit-events", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 120
        assert len(body["data"]) == 50

    samples: list[float] = []
    for _ in range(20):
        elapsed_ms, response = await _timed(
            integration_client.get("/api/v1/audit-events", params=params)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 120
        assert {item["action"] for item in body["data"]} == {action}
        samples.append(elapsed_ms)

    assert await count_self_audits() == before_self_audits + 23
    _assert_p99_under(
        "audit events list API",
        samples,
        _threshold("PERF_AUDIT_EVENTS_LIST_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_audit_events_denied_queries_no_self_audit_p99_smoke(
    integration_client_as,
    integration_db_session,
    seed_run,
    seed_second_tenant,
):
    from qaplatform.infra.database.models import AuditEvent

    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    tenant_b = seed_second_tenant["tenant"]
    user_b = seed_second_tenant["user"]
    project_b = seed_second_tenant["project"]

    integration_db_session.add(
        AuditEvent(
            tenant_id=tenant_b.id,
            user_id=user_b.id,
            action="audit.denied_probe",
            resource_type="project",
            resource_id=project_b.id,
            after_state={"tenant": "b"},
        )
    )
    await integration_db_session.commit()

    async def count_self_audits() -> int:
        result = await integration_db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_a.id,
                AuditEvent.user_id == user_a.id,
                AuditEvent.action == "audit_events.list",
                AuditEvent.resource_type == "audit_event",
            )
        )
        return result.scalar_one()

    before_count = await count_self_audits()
    samples: list[float] = []

    async with integration_client_as(user_a.id, tenant_a.id, role="member") as client:
        for _ in range(7):
            elapsed_ms, response = await _timed(client.get("/api/v1/audit-events"))
            assert response.status_code == 403, response.text
            samples.append(elapsed_ms)

    async with integration_client_as(user_a.id, tenant_a.id, role="viewer") as client:
        for _ in range(7):
            elapsed_ms, response = await _timed(client.get("/api/v1/audit-events"))
            assert response.status_code == 403, response.text
            samples.append(elapsed_ms)

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        for _ in range(7):
            elapsed_ms, response = await _timed(
                client.get(
                    "/api/v1/audit-events",
                    params={
                        "resource_type": "project",
                        "resource_id": str(project_b.id),
                    },
                )
            )
            assert response.status_code == 404, response.text
            samples.append(elapsed_ms)

    assert await count_self_audits() == before_count
    _assert_p99_under(
        "audit events denied no-self-audit API",
        samples,
        _threshold("PERF_AUDIT_EVENTS_DENIED_P99_MS", 1000),
    )


@pytest.mark.asyncio
async def test_real_api_token_concurrent_read_paths_p99_smoke(
    test_settings,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    async with _real_auth_perf_client(test_settings) as (app, client):
        registration = await _register_perf_user(
            client,
            prefix="perf_concurrent",
        )
        access_token = registration["access_token"]
        user = registration["user"]
        tenant_id = UUID(user["tenant_id"])
        user_id = UUID(user["id"])
        stack = await _create_perf_project_environment_and_pipeline(
            client,
            access_token,
        )
        trigger_resp = await client.post(
            "/api/v1/runs",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
        )
        assert trigger_resp.status_code == 201, trigger_resp.text
        run_id = UUID(trigger_resp.json()["id"])
        project_id = UUID(stack["project_id"])
        bucket = app.state.container.settings.s3_bucket
        marker = f"concurrent-read-{uuid4().hex}"

        archive_entries = [
            {
                "stream": "stderr" if index % 31 == 0 else "stdout",
                "line": f"{marker}-archived-line-{index:03}",
            }
            for index in range(240)
        ]
        archive_body = "\n".join(
            json.dumps(entry) for entry in archive_entries
        ).encode("utf-8")

        artifact_repo = ArtifactRepository(integration_db_session)
        artifact = await artifact_repo.create(
            run_id=run_id,
            type="report",
            name=f"{marker}-report.html",
            storage_path=f"reports/{run_id}/{marker}-report.html",
            size_bytes=4096,
            mime_type="text/html",
        )

        audit_action = f"audit.concurrent_probe.{marker}"
        now = datetime.now(timezone.utc)
        for index in range(90):
            integration_db_session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=audit_action,
                    resource_type="project",
                    resource_id=project_id,
                    after_state={"index": index, "marker": marker},
                    created_at=now - timedelta(seconds=index),
                )
            )
        await integration_db_session.commit()

        async def count_self_audits() -> int:
            result = await integration_db_session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.user_id == user_id,
                    AuditEvent.action == "audit_events.list",
                    AuditEvent.resource_type == "audit_event",
                )
            )
            return result.scalar_one()

        read_token = await _create_perf_api_token(
            client,
            access_token,
            name="concurrent-read-token",
            scopes=["run.read", "audit.read"],
        )
        headers = {"Authorization": f"Bearer {read_token}"}

        s3 = _MemoryS3()
        await s3.put_object(
            Bucket=bucket,
            Key=f"logs/{run_id}.jsonl",
            Body=archive_body,
            ContentType="application/x-ndjson",
        )
        old_s3 = app.state.container.s3_client
        app.state.container.s3_client = s3

        archive_params = {"page": 3, "per_page": 40}
        audit_params = {
            "action": audit_action,
            "resource_type": "project",
            "per_page": 30,
        }

        async def read_archived_logs() -> float:
            elapsed_ms, response = await _timed(
                client.get(
                    f"/api/v1/runs/{run_id}/logs/archive",
                    params=archive_params,
                    headers=headers,
                )
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 240
            assert body["page"] == 3
            assert body["per_page"] == 40
            assert body["data"][0]["line"] == f"{marker}-archived-line-080"
            assert body["data"][-1]["line"] == f"{marker}-archived-line-119"
            return elapsed_ms

        async def download_artifact() -> float:
            elapsed_ms, response = await _timed(
                client.get(
                    f"/api/v1/artifacts/{artifact.id}/download",
                    headers=headers,
                )
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["expires_in"] == app.state.container.settings.s3_presigned_url_ttl
            assert f"/{artifact.storage_path}" in body["download_url"]
            return elapsed_ms

        async def list_audit_events() -> float:
            elapsed_ms, response = await _timed(
                client.get(
                    "/api/v1/audit-events",
                    params=audit_params,
                    headers=headers,
                )
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 90
            assert len(body["data"]) == 30
            assert {item["action"] for item in body["data"]} == {audit_action}
            return elapsed_ms

        before_self_audits = await count_self_audits()
        try:
            warmup_samples = await asyncio.gather(
                read_archived_logs(),
                download_artifact(),
                list_audit_events(),
            )
            assert len(warmup_samples) == 3

            samples: list[float] = []
            for _ in range(6):
                samples.extend(
                    await asyncio.gather(
                        read_archived_logs(),
                        download_artifact(),
                        list_audit_events(),
                    )
                )
        finally:
            app.state.container.s3_client = old_s3

        expected_log_get_call = {"bucket": bucket, "key": f"logs/{run_id}.jsonl"}
        assert s3.get_calls == [expected_log_get_call] * 7
        assert len(s3.presign_calls) == 7
        assert all(call["method"] == "get_object" for call in s3.presign_calls)
        assert all(
            call["params"] == {"Bucket": bucket, "Key": artifact.storage_path}
            for call in s3.presign_calls
        )
        assert all(
            call["expires_in"] == app.state.container.settings.s3_presigned_url_ttl
            for call in s3.presign_calls
        )
        assert await count_self_audits() == before_self_audits + 7

        _assert_p99_under(
            "real API token log/artifact/audit concurrent read paths",
            samples,
            _threshold("PERF_REAL_TOKEN_CONCURRENT_READ_PATHS_P99_MS", 3000),
        )


@pytest.mark.asyncio
async def test_execution_summary_generation_slo_smoke(
    integration_app,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.executor import PipelineConfig, RunExecutor, StageDefinition
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.plugins.builtin.junit_collector import JUnitCollector

    counts = {"passed": 920, "failed": 40, "skipped": 25, "error": 15}
    total = sum(counts.values())
    expected_summary = {
        "total": total,
        **counts,
        "pass_rate": counts["passed"] / total,
    }
    tenant_id = seed_run["tenant"].id
    project_id = seed_run["project"].id
    pipeline_id = seed_run["pipeline"].id
    environment_id = seed_run["environment"].id
    user_id = seed_run["user"].id
    samples: list[float] = []

    for _ in range(5):
        run = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            pipeline_id=pipeline_id,
            environment_id=environment_id,
            status=RunStatusEnum.PREPARING,
            trigger_type="manual",
            priority=1,
            triggered_by=user_id,
            git_ref=f"perf-summary/{uuid4().hex}",
            attempt=1,
            chain_depth=0,
            metadata_={"perf_summary": True},
        )
        integration_db_session.add(run)
        await integration_db_session.commit()
        await integration_db_session.refresh(run)
        run_id = run.id

        run_repo = RunRepository(integration_db_session)
        executor = RunExecutor(
            backend=_SummaryBackend(**counts),
            log_stream=LogStream(integration_app.state.container.redis_client),
            run_repo=run_repo,
            plugin_registry=_SummaryPluginRegistry(JUnitCollector()),
            redis=integration_app.state.container.redis_client,
        )
        pipeline = PipelineConfig(
            image="python:3.12-alpine",
            stages=[StageDefinition(name="summary", plugin="pytest")],
            timeout_seconds=30,
        )

        elapsed_ms, status = await _timed(executor.execute(run, pipeline))
        assert status.value == "done"
        samples.append(elapsed_ms)

        integration_db_session.expire_all()
        persisted = await integration_db_session.get(Run, run_id)
        assert persisted is not None
        assert persisted.status == RunStatusEnum.DONE
        assert persisted.summary == expected_summary

    _assert_p99_under(
        "execution summary generation",
        samples,
        _threshold("PERF_EXECUTION_SUMMARY_P99_MS", 3000),
    )
