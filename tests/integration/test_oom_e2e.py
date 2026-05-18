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
]


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
def python_image_pulled(docker_available):
    """Pull python:3.12-alpine once per module so tests don't pay pull cost."""
    subprocess.run(
        ["docker", "pull", "python:3.12-alpine"],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return "python:3.12-alpine"


@pytest.fixture(scope="module")
def alpine_image_pulled(docker_available):
    """Pull alpine:3.19 once per module."""
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
