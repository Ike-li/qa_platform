"""Real Docker evidence for DockerBackend resource stats streaming."""

from __future__ import annotations

import asyncio
import os
import subprocess
from contextlib import suppress
from uuid import uuid4

import aiodocker
import pytest
import pytest_asyncio

from qaplatform.engine.docker_backend import DockerBackend

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
    pytest.mark.heavy_docker,
]


@pytest.fixture(scope="module")
def docker_available():
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
def alpine_image_pulled(docker_available, pull_docker_image):
    return pull_docker_image("alpine:3.19", timeout=120)


@pytest_asyncio.fixture
async def aiodocker_client():
    client = aiodocker.Docker()
    try:
        yield client
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_docker_backend_streams_real_resource_usage(
    docker_available,
    alpine_image_pulled,
    aiodocker_client,
):
    backend = DockerBackend(aiodocker_client)
    name = f"qap-resource-usage-e2e-{uuid4().hex}"
    container = await aiodocker_client.containers.create_or_replace(
        name=name,
        config={
            "Image": alpine_image_pulled,
            "Cmd": [
                "sh",
                "-c",
                "dd if=/dev/zero of=/tmp/qap-stats-blob bs=1M count=8 "
                ">/dev/null 2>&1; sleep 3",
            ],
            "HostConfig": {
                "Memory": 64 * 1024 * 1024,
                "MemorySwap": 64 * 1024 * 1024,
                "NetworkMode": "none",
                "Init": True,
            },
        },
    )
    usage_iter = None
    try:
        await container.start()
        usage_iter = backend.stream_resource_usage(container.id)
        sample = await asyncio.wait_for(anext(usage_iter), timeout=10.0)

        assert sample.memory_usage_bytes is not None
        assert sample.memory_usage_bytes > 0
        assert sample.memory_limit_bytes is not None
        assert sample.memory_limit_bytes > 0
        assert sample.timestamp.tzinfo is not None
        assert sample.pids_current is None or sample.pids_current >= 1
    finally:
        if usage_iter is not None:
            await usage_iter.aclose()
        with suppress(Exception):
            await container.delete(force=True)
