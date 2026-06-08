"""E2E test: container exceeding memory limit -> ExitResult.oom_killed True.

Validates PRD F-PL-03 (memory cap is a hard ceiling and an OOM-kill must be
detectable so executor.py can map it to RunStatus.TIMEOUT).

Wiring under test:
    DockerBackend.wait()
        -> container.wait()  (returns StatusCode only)
        -> container.show()  (returns State.OOMKilled)
        -> ExitResult(oom_killed=...)

Skipped by default; set RUN_INTEGRATION_TESTS=1 to enable.
Skipped on macOS because Docker Desktop's LinuxKit VM does not always
trigger the kernel OOM killer when a cgroup memory limit is exceeded
(allocations may fail with ENOMEM instead, leaving OOMKilled=False).
"""
from __future__ import annotations

import os
import subprocess
import sys

import aiodocker
import pytest
import pytest_asyncio

from qaplatform.engine.docker_backend import DockerBackend

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="Docker Desktop macOS OOM behavior unstable (cgroup hard limit "
        "may not trigger kernel OOM killer)",
    ),
    pytest.mark.skipif(
        os.environ.get("QAP_TEST_OOM") != "1",
        reason="OOM detection unreliable on GitHub Actions (cgroup v2 may not set "
        "OOMKilled=true even on exit 137); set QAP_TEST_OOM=1 on bare-metal Linux",
    ),
    pytest.mark.heavy_docker,
]


def _assert_log_line_once(lines: list[str], expected_line: str) -> None:
    assert [line for line in lines if line == expected_line] == [expected_line]


def _resource_termination_log_fields(line: str) -> dict[str, str]:
    prefix = "Resource termination: "
    assert line.startswith(prefix)
    return dict(part.split("=", 1) for part in line.removeprefix(prefix).split())


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def docker_available():
    """Skip if docker daemon not reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, check=False
        )
        if result.returncode != 0:
            pytest.skip("docker daemon not available")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("docker daemon not available")
    return True


@pytest.fixture(scope="module")
def python_image_pulled(docker_available, pull_docker_image):
    """Pull python:3.12-alpine once per module so tests don't pay pull cost."""
    return pull_docker_image("python:3.12-alpine", timeout=300)


@pytest.fixture(scope="module")
def alpine_image_pulled(docker_available, pull_docker_image):
    """Pull alpine:3.19 once per module."""
    return pull_docker_image("alpine:3.19", timeout=120)


@pytest_asyncio.fixture
async def aiodocker_client():
    client = aiodocker.Docker()
    try:
        yield client
    finally:
        await client.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _create_and_start(
    client: aiodocker.Docker,
    *,
    image: str,
    command: list[str],
    mem_bytes: int,
    name: str,
):
    """Create + start a minimal container with hard memory cap."""
    config = {
        "Image": image,
        "Cmd": command,
        "HostConfig": {
            "Memory": mem_bytes,
            # MemorySwap == Memory disables swap; otherwise Docker silently
            # grants 2× memory and the OOM may not fire at the configured cap.
            "MemorySwap": mem_bytes,
            "NetworkMode": "none",
            "Init": True,
        },
    }
    container = await client.containers.create_or_replace(name=name, config=config)
    await container.start()
    return container


class _OomRunner:
    def build_command(self, _config):
        return "python -c \"chunks = []; [chunks.append(bytearray(1024 * 1024)) for _ in range(512)]\""


class _EmptyCollector:
    async def collect(self, _run_id, _working_dir):
        return []


class _OomPluginRegistry:
    def get_runner(self, _name):
        return _OomRunner()

    def get_collector(self, _name):
        return _EmptyCollector()


def _decode_redis_mapping(mapping: dict) -> dict[str, str]:
    return {
        key.decode() if isinstance(key, bytes) else key: (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in mapping.items()
    }


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_oom_kill_sets_oom_killed_true(
    docker_available, python_image_pulled, aiodocker_client
):
    """Container that allocates beyond mem_limit must surface oom_killed=True."""
    backend = DockerBackend(aiodocker_client)
    container = await _create_and_start(
        aiodocker_client,
        image=python_image_pulled,
        # Allocate ~100MB into a single string -> blows past 8MiB cap.
        # 8MB is the minimum that satisfies the kernel's 6MB floor while still
        # being small enough that a 100MB allocation reliably triggers OOM.
        command=["python", "-c", "x = ' ' * (10 ** 8)"],
        mem_bytes=8 * 1024 * 1024,
        name="qap-oom-e2e-kill",
    )
    try:
        result = await backend.wait(container.id, timeout=30)
        assert result.oom_killed is True, (
            f"expected oom_killed=True, got {result!r}"
        )
        assert result.exit_code != 0, (
            f"OOM-killed container should not exit 0; got {result.exit_code}"
        )
    finally:
        try:
            await container.delete(force=True)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_normal_exit_oom_killed_false(
    docker_available, alpine_image_pulled, aiodocker_client
):
    """Normal exit must report oom_killed=False."""
    backend = DockerBackend(aiodocker_client)
    container = await _create_and_start(
        aiodocker_client,
        image=alpine_image_pulled,
        command=["echo", "hi"],
        mem_bytes=64 * 1024 * 1024,
        name="qap-oom-e2e-normal",
    )
    try:
        result = await backend.wait(container.id, timeout=30)
        assert result.oom_killed is False, (
            f"expected oom_killed=False, got {result!r}"
        )
        assert result.exit_code == 0, (
            f"expected exit_code=0, got {result.exit_code}"
        )
    finally:
        try:
            await container.delete(force=True)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_executor_maps_real_oom_to_timeout_summary_and_redis(
    docker_available,
    python_image_pulled,
    aiodocker_client,
    integration_app,
    integration_db_session,
    seed_run,
):
    """Real Docker OOM must become the platform timeout/resource summary contract."""
    from qaplatform.domain.models.run import Run as RunDomain
    from qaplatform.domain.models.run import RunStatus
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.engine.events import EVENT_STREAM_KEY, STATUS_HASH_KEY
    from qaplatform.engine.executor import PipelineConfig, RunExecutor, StageDefinition
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    run_id = seed_run["run"].id
    run_repo = RunRepository(integration_db_session)
    claimed = await run_repo.claim_for_worker(run_id, worker_id="test-oom-e2e")
    assert claimed is not None, "could not claim seeded run"
    await integration_db_session.commit()

    redis = integration_app.state.container.redis_client
    executor = RunExecutor(
        backend=DockerBackend(aiodocker_client),
        log_stream=LogStream(redis),
        run_repo=run_repo,
        plugin_registry=_OomPluginRegistry(),
        redis=redis,
    )
    run_domain = RunDomain(
        id=run_id,
        tenant_id=seed_run["tenant"].id,
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        environment_id=seed_run["environment"].id,
        git_ref="main",
        triggered_by=seed_run["user"].id,
        metadata={},
    )
    pipeline = PipelineConfig(
        image=python_image_pulled,
        stages=[StageDefinition(name="oom", plugin="python")],
        resource_limits=ResourceLimits(
            memory_bytes=32 * 1024 * 1024,
            cpu_cores=0.5,
        ),
        network_policy="deny",
        timeout_seconds=30,
    )

    status = await executor.execute(run_domain, pipeline)
    assert status == RunStatus.TIMEOUT

    integration_db_session.expire_all()
    persisted = await integration_db_session.get(Run, run_id)
    assert persisted is not None
    assert persisted.status == RunStatusEnum.TIMEOUT
    assert persisted.summary is not None
    resource_termination = persisted.summary["resource_termination"]
    assert resource_termination["reason"] == "oom"
    assert resource_termination["oom_killed"] is True
    assert resource_termination["timed_out"] is False
    assert resource_termination["exit_code"] != 0
    assert resource_termination["duration_ms"] >= 0
    assert resource_termination["started_at"]
    assert resource_termination["finished_at"]

    status_hash = await redis.hgetall(STATUS_HASH_KEY.format(run_id=str(run_id)))
    assert _decode_redis_mapping(status_hash)["status"] == "timeout"

    events = await redis.xrange(EVENT_STREAM_KEY.format(run_id=str(run_id)))
    assert events, "OOM run did not publish Redis status events"
    _event_id, latest_event = events[-1]
    decoded_event = _decode_redis_mapping(latest_event)
    assert decoded_event["status"] == "timeout"
    assert decoded_event["previous"] == "collecting"

    logs = await executor.log_stream.read_logs(run_id, count=100)
    lines = [entry["line"] for entry in logs]
    _assert_log_line_once(lines, "Starting stage: oom")
    failure_line = f"Pipeline failed with code {resource_termination['exit_code']}"
    _assert_log_line_once(lines, failure_line)
    assert [
        _resource_termination_log_fields(line)
        for line in lines
        if line.startswith("Resource termination: ")
    ] == [
        {
            "reason": "oom",
            "exit_code": str(resource_termination["exit_code"]),
            "duration_ms": str(resource_termination["duration_ms"]),
            "oom_killed": "True",
            "timed_out": "False",
        }
    ]
    _assert_log_line_once(lines, "Run completed: timeout")
