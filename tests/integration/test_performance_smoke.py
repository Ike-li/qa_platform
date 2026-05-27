"""Nightly/manual backend nonfunctional smoke checks.

These tests are intentionally opt-in because local and hosted CI runners vary
too much for p99 product SLOs to be reliable PR blockers. They provide a stable
trend signal for the backend paths called out in the test strategy.
"""

from __future__ import annotations

import math
import os
from time import perf_counter
from uuid import uuid4

import pytest

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

    async def __aexit__(self, *_args):
        return None


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
