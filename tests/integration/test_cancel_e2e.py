"""E2E test: redis cancel signal -> real docker container SIGTERM termination.

Validates PRD F-EX-06 (cancel semantics): a publish_cancel() against the
redis cancel channel must terminate a running container in < 10 seconds.

Wiring under test:
    publish_cancel(redis, run_id)
        -> watch_for_cancel() picks up message on run:cancel:{run_id}
        -> RunExecutor._handle_cancel_signal()
        -> RunExecutor._graceful_stop()
        -> DockerBackend.cancel() -> container.kill(SIGTERM)
        -> the in-container `sleep 60` exits immediately on SIGTERM
        -> backend.wait() returns with non-zero exit code
        -> RunExecutor.execute() proceeds through collect -> finish

Note on terminal status: the redis-cancel path produces RunStatus.FAILED
(non-zero exit mapped at executor.py:230-231), not RunStatus.CANCELLED.
The CANCELLED transition only occurs for pre-execute cancellation in
worker/tasks.py:75. This test asserts the F-EX-06 timing contract and
that the run reaches a terminal state, not the specific status label.

Skipped by default; set RUN_INTEGRATION_TESTS=1 to enable.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import aiodocker
import pytest
import pytest_asyncio
from redis.asyncio import Redis as AsyncRedis

from qaplatform.domain.models.run import Run, RunStatus
from qaplatform.engine.cancel import publish_cancel
from qaplatform.engine.docker_backend import DockerBackend, ResourceLimits
from qaplatform.engine.executor import (
    PipelineConfig,
    RunExecutor,
    StageDefinition,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


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
def alpine_image_pulled(docker_available):
    """Pull alpine:3.19 once per module so the cancel timing isn't dominated
    by a first-time image pull. The < 10s assertion measures cancel
    propagation, not docker pull throughput."""
    subprocess.run(
        ["docker", "pull", "alpine:3.19"],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return "alpine:3.19"


@pytest_asyncio.fixture
async def aiodocker_client():
    client = aiodocker.Docker()
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def async_redis(redis_container):
    """Async redis client connected to the session-scoped redis_container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client = AsyncRedis.from_url(f"redis://{host}:{port}", decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


# --------------------------------------------------------------------------- #
# Test
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cancel_signal_terminates_running_container_within_10s(
    docker_available, alpine_image_pulled, aiodocker_client, async_redis
):
    """End-to-end: redis publish('run:cancel:{run_id}', 'cancel')
    -> watch_for_cancel picks it up
    -> _handle_cancel_signal -> _graceful_stop sends SIGTERM
    -> alpine container running `sleep 60` exits immediately
    -> RunExecutor.execute() returns within 10 seconds.
    """
    run_id = uuid4()

    # Real DockerBackend + real redis. Everything else is mocked or stubbed
    # because this test scopes itself to the cancel pathway only.
    backend = DockerBackend(aiodocker_client)
    log_stream = AsyncMock()

    # run_repo: AsyncMock returning safe defaults. finish_if_current returns
    # True so the executor logs completion; cancel_if_current/fail_if_current
    # also return True for any branch we hit.
    run_repo = AsyncMock()
    run_repo.finish_if_current.return_value = True
    run_repo.fail_if_current.return_value = True
    run_repo.cancel_if_current.return_value = True

    # Init=True (HostConfig) makes tini PID 1; sleep receives SIGTERM directly.
    # The collector returns no results (no junit XML inside the container, but
    # JUnitCollector returns [] gracefully when results_dir is empty --
    # see junit_collector.py:38).
    plugin_registry = MagicMock()
    runner = MagicMock()
    runner.build_command = MagicMock(return_value="sleep 60")
    plugin_registry.get_runner.return_value = runner
    collector = MagicMock()
    collector.collect = AsyncMock(return_value=[])
    plugin_registry.get_collector.return_value = collector

    executor = RunExecutor(
        backend=backend,
        log_stream=log_stream,
        run_repo=run_repo,
        plugin_registry=plugin_registry,
        s3_client=None,
        artifact_repo=None,
        redis=async_redis,
    )

    # Run with empty metadata so _clone_repo short-circuits (no git_url ->
    # no source plugin lookup, no actual clone).
    run = Run(
        id=run_id,
        tenant_id=uuid4(),
        project_id=uuid4(),
        pipeline_id=uuid4(),
        environment_id=uuid4(),
        git_ref="main",
        metadata={},
    )

    pipeline = PipelineConfig(
        image=alpine_image_pulled,
        stages=[
            StageDefinition(
                name="cancel-test",
                plugin="pytest",  # build_command is mocked, plugin name irrelevant
                phase="execute",
                config={},
            )
        ],
        env_vars={},
        resource_limits=ResourceLimits(
            memory_bytes=128 * 1024 * 1024,
            cpu_cores=0.5,
        ),
        # network_policy=allow avoids the qap-restricted custom network
        # (which the docker daemon may not have configured locally).
        network_policy="allow",
        # timeout high enough that we never trip the timeout path.
        timeout_seconds=120,
    )

    execute_task = asyncio.create_task(executor.execute(run, pipeline))

    # Wait until the executor has actually started the container before
    # publishing cancel. Polling _active_execution_id is more deterministic
    # than a fixed sleep.
    deadline = time.monotonic() + 30.0
    while getattr(executor, "_active_execution_id", None) is None:
        if time.monotonic() > deadline:
            execute_task.cancel()
            pytest.fail("container never reached active state within 30s")
        if execute_task.done():
            # Surface any startup error rather than spinning forever.
            await execute_task
            pytest.fail("execute() returned before container became active")
        await asyncio.sleep(0.1)

    container_id = executor._active_execution_id

    # Fire the cancel and time how long until execute() returns.
    cancel_sent_at = time.monotonic()
    await publish_cancel(async_redis, run_id)

    try:
        terminal_status = await asyncio.wait_for(execute_task, timeout=15.0)
    except asyncio.TimeoutError:
        execute_task.cancel()
        pytest.fail(
            f"execute() did not return within 15s of cancel; "
            f"container={container_id} run_repo.calls={run_repo.method_calls}"
        )

    elapsed = time.monotonic() - cancel_sent_at

    assert elapsed < 10.0, (
        f"cancel propagation took {elapsed:.2f}s, F-EX-06 requires < 10s; "
        f"terminal_status={terminal_status} run_repo.calls={run_repo.method_calls}"
    )

    # Sanity: a terminal state must have been written. The redis-cancel
    # path lands on FAILED (non-zero exit from SIGTERM) per executor.py
    # status mapping; we accept any terminal status to keep this test
    # focused on the timing contract rather than the label.
    assert terminal_status in {
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMEOUT,
        RunStatus.DONE,
    }, f"unexpected terminal status: {terminal_status}"

    # The executor must have written *some* terminal update through run_repo.
    terminal_updates = (
        run_repo.finish_if_current.await_count
        + run_repo.fail_if_current.await_count
        + run_repo.cancel_if_current.await_count
    )
    assert terminal_updates >= 1, (
        f"expected at least one terminal status write; "
        f"run_repo.calls={run_repo.method_calls}"
    )
