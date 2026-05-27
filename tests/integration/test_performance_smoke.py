"""Nightly/manual backend nonfunctional smoke checks.

These tests are intentionally opt-in because local and hosted CI runners vary
too much for p99 product SLOs to be reliable PR blockers. They provide a stable
trend signal for the backend paths called out in the test strategy.
"""

from __future__ import annotations

import asyncio
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
from sqlalchemy import select

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


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

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
        return {"Body": _MemoryBody(self.objects[(Bucket, Key)])}

    async def generate_presigned_url(self, method, *, Params, ExpiresIn):
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
    from qaplatform.infra.database.models import Run

    arq = _FakeArq()
    settings = integration_app.state.container.settings
    old_arq_pool = integration_app.state.container.arq_pool
    old_total = settings.max_concurrent_runs
    old_per_project = settings.max_concurrent_per_project
    integration_app.state.container.arq_pool = arq
    settings.max_concurrent_runs = 100
    settings.max_concurrent_per_project = 100

    pipeline_id = seed_run["pipeline"].id
    samples: list[float] = []
    try:
        for _ in range(10):
            started_at = datetime.now(timezone.utc)
            response = await integration_client.post(
                "/api/v1/runs",
                json={
                    "pipeline_id": str(pipeline_id),
                    "git_ref": f"perf-enqueue/{uuid4().hex}",
                    "priority": 1,
                },
            )
            assert response.status_code == 201, response.text
            run_id = UUID(response.json()["id"])

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

    assert len(arq.calls) == 10
    _assert_p99_under(
        "trigger enqueue SLO",
        samples,
        _threshold("PERF_TRIGGER_ENQUEUE_P99_MS", 5000),
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
async def test_archived_log_replay_api_p99_smoke(
    integration_app,
    integration_client,
    seed_run,
):
    from qaplatform.engine.log_stream import LogStream

    run_id = seed_run["run"].id
    s3 = _MemoryS3()
    integration_app.state.container.s3_client = s3
    stream = LogStream(integration_app.state.container.redis_client)
    for index in range(50):
        await stream.write_log(run_id, f"archived-line-{index}", stream="stdout")
    assert await stream.archive_logs(
        run_id,
        s3,
        integration_app.state.container.settings.s3_bucket,
    )

    for _ in range(3):
        response = await integration_client.get(f"/api/v1/runs/{run_id}/logs/archive")
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

    _assert_p99_under(
        "archived log replay API",
        samples,
        _threshold("PERF_LOG_ARCHIVE_READ_P99_MS", 1000),
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
    integration_app.state.container.s3_client = _MemoryS3()
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

    _assert_p99_under(
        "artifact download URL API",
        samples,
        _threshold("PERF_ARTIFACT_DOWNLOAD_URL_P99_MS", 1000),
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

    _assert_p99_under(
        "audit events list API",
        samples,
        _threshold("PERF_AUDIT_EVENTS_LIST_P99_MS", 1000),
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
