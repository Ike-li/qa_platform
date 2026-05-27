"""Nightly/manual backend nonfunctional smoke checks.

These tests are intentionally opt-in because local and hosted CI runners vary
too much for p99 product SLOs to be reliable PR blockers. They provide a stable
trend signal for the backend paths called out in the test strategy.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from time import perf_counter
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
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


async def _timed(awaitable) -> tuple[float, object]:
    started = perf_counter()
    result = await awaitable
    return (perf_counter() - started) * 1000, result


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
