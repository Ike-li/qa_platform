"""集成测试：worker mark_running 后状态在独立连接立刻可见。

回归覆盖 P0-B step 1+2 的 commit：worker 在 claim_for_worker / mark_running /
mark_collecting 之后都各自 commit，所以一个独立连接能在 worker 还在跑容器的
时候 SELECT 出 RUNNING 状态。如果 commit 被回退到原来的"整个 run 跑完才提交"
模式，本测试会在 30s 内观察不到 RUNNING -> 失败。

Skipped by default; set RUN_INTEGRATION_TESTS=1 to enable. macOS 不 skip。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from unittest.mock import AsyncMock, MagicMock

import aiodocker
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from qaplatform.domain.models.run import Run as RunDomain
from qaplatform.engine.cancel import publish_cancel
from qaplatform.engine.docker_backend import DockerBackend, ResourceLimits
from qaplatform.engine.executor import (
    PipelineConfig,
    RunExecutor,
    StageDefinition,
)
from qaplatform.infra.database.models import Run as RunORM, RunStatusEnum
from qaplatform.infra.database.repositories.run_repo import (
    ArtifactRepository,
    RunRepository,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


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
def alpine_image_pulled(docker_available):
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
    from redis.asyncio import Redis as AsyncRedis

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client = AsyncRedis.from_url(
        f"redis://{host}:{port}", decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_mark_running_visible_on_other_connection(
    docker_available,
    alpine_image_pulled,
    aiodocker_client,
    async_redis,
    seed_run,
    integration_db_engine,
):
    run_id = seed_run["run"].id
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)

    # 1. claim_for_worker (queued -> preparing) and commit, mirroring tasks.py
    async with factory() as worker_session:
        wr = RunRepository(worker_session)
        claimed = await wr.claim_for_worker(run_id, worker_id="test-worker-1")
        assert claimed is not None, "could not claim seeded run"
        await worker_session.commit()

    # 2. mock plugin registry: runner.build_command -> "sleep 60"
    plugin_registry = MagicMock()
    runner = MagicMock()
    runner.build_command = MagicMock(return_value="sleep 60")
    plugin_registry.get_runner.return_value = runner
    collector = MagicMock()
    collector.collect = AsyncMock(return_value=[])
    plugin_registry.get_collector.return_value = collector

    backend = DockerBackend(aiodocker_client)
    log_stream = AsyncMock()

    exec_session = factory()
    executor = RunExecutor(
        backend=backend,
        log_stream=log_stream,
        run_repo=RunRepository(exec_session),
        plugin_registry=plugin_registry,
        s3_client=None,
        artifact_repo=ArtifactRepository(exec_session),
        redis=async_redis,
    )

    run_domain = RunDomain(
        id=run_id,
        tenant_id=seed_run["tenant"].id,
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        environment_id=seed_run["environment"].id,
        git_ref="main",
        metadata={},
    )
    pipeline = PipelineConfig(
        image=alpine_image_pulled,
        stages=[
            StageDefinition(name="exec", plugin="pytest", phase="execute"),
        ],
        env_vars={},
        resource_limits=ResourceLimits(
            memory_bytes=128 * 1024 * 1024, cpu_cores=0.5,
        ),
        network_policy="allow",
        timeout_seconds=120,
    )

    execute_task = asyncio.create_task(executor.execute(run_domain, pipeline))

    try:
        # 3. independent connection observes RUNNING
        deadline = time.monotonic() + 30
        observed_running = False
        while time.monotonic() < deadline:
            async with factory() as observer:
                row = await observer.get(RunORM, run_id)
                if row is not None and row.status == RunStatusEnum.RUNNING:
                    observed_running = True
                    break
            if execute_task.done():
                # surface any startup error
                await execute_task
                break
            await asyncio.sleep(0.2)

        assert observed_running, (
            "RUNNING transition was not visible on a separate connection "
            "within 30s; mark_running commit did not flush"
        )
    finally:
        # cancel to wind down the sleep 60 container
        try:
            await publish_cancel(async_redis, run_id)
        except Exception:
            pass
        try:
            await asyncio.wait_for(execute_task, timeout=15)
        except (asyncio.TimeoutError, Exception):
            if not execute_task.done():
                execute_task.cancel()
                try:
                    await execute_task
                except (asyncio.CancelledError, Exception):
                    pass
        try:
            await exec_session.close()
        except Exception:
            pass
