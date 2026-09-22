"""集成测试：worker 执行期间 cancel API 不被长事务阻塞。

回归覆盖 P0-B step 1+2：worker claim 之后立刻 commit，cancel API 用独立 session
取 row lock + UPDATE，应该 < 2s 返回。然后 cancel 信号经 redis 推到 watcher
-> SIGTERM 容器 -> executor 终态写 CANCELLED（< 10s 满足 F-EX-06）。

如果 worker 长事务回退（claim_for_worker 之后不 commit），cancel API 会被
PG 行锁阻塞到容器跑完，本测试在第一处 < 2s 断言上失败。

Skipped by default; set RUN_INTEGRATION_TESTS=1 to enable.
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
from qaplatform.engine.docker_backend import DockerBackend, ResourceLimits
from qaplatform.engine.executor import (
    PipelineConfig,
    RunExecutor,
    StageDefinition,
)
from qaplatform.infra.database.models import Run as RunORM
from qaplatform.infra.database.models import RunStatusEnum
from qaplatform.infra.database.repositories.run_repo import (
    ArtifactRepository,
    RunRepository,
)

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
async def test_cancel_api_not_blocked_by_worker(
    docker_available,
    alpine_image_pulled,
    aiodocker_client,
    integration_app,
    integration_client,
    seed_run,
    integration_db_engine,
):
    run_id = seed_run["run"].id
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)

    # 1. claim_for_worker -> commit (mirrors tasks.execute_run after step 1)
    async with factory() as worker_session:
        wr = RunRepository(worker_session)
        claimed = await wr.claim_for_worker(run_id, worker_id="test-worker-2")
        assert claimed is not None, "could not claim seeded run"
        await worker_session.commit()

    # 2. start executor inline; build_command -> sleep 60 inside container
    plugin_registry = MagicMock()
    runner = MagicMock()
    runner.build_command = MagicMock(return_value="sleep 60")
    plugin_registry.get_runner.return_value = runner
    collector = MagicMock()
    collector.collect = AsyncMock(return_value=[])
    plugin_registry.get_collector.return_value = collector

    redis = integration_app.state.container.redis_client
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
        redis=redis,
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
        stages=[StageDefinition(name="exec", plugin="pytest", phase="execute")],
        env_vars={},
        resource_limits=ResourceLimits(
            memory_bytes=128 * 1024 * 1024, cpu_cores=0.5,
        ),
        network_policy="allow",
        timeout_seconds=120,
    )

    execute_task = asyncio.create_task(executor.execute(run_domain, pipeline))

    try:
        # wait until the watcher has subscribed and the container has started
        deadline = time.monotonic() + 30.0
        while getattr(executor, "_active_execution_id", None) is None:
            if time.monotonic() > deadline:
                pytest.fail("container never became active within 30s")
            if execute_task.done():
                await execute_task
                pytest.fail("execute() returned before container active")
            await asyncio.sleep(0.1)
        # extra grace for pubsub.subscribe + status -> RUNNING commit
        await asyncio.sleep(0.5)

        # 3. cancel API must return quickly (worker holds no row lock)
        start = time.monotonic()
        response = await integration_client.post(f"/api/v1/runs/{run_id}/cancel")
        api_latency = time.monotonic() - start

        assert response.status_code == 200, response.text
        assert api_latency < 2.0, (
            f"cancel API blocked by worker: {api_latency:.2f}s"
        )

        # 4. < 10s for executor to receive cancel + SIGTERM container + return
        cancel_window = time.monotonic()
        try:
            await asyncio.wait_for(execute_task, timeout=15.0)
        except asyncio.TimeoutError:
            execute_task.cancel()
            pytest.fail("executor did not return within 15s of cancel")
        propagation = time.monotonic() - cancel_window
        assert propagation < 10.0, (
            f"F-EX-06: cancel propagation took {propagation:.2f}s"
        )

        # 5. terminal status MUST be CANCELLED. Cancel API wrote CANCELLED via
        # cancel_if_current; executor's fail_if_current uses the default
        # expected_in (active states) and rowcount=0 against terminal CANCELLED.
        async with factory() as observer:
            row = await observer.get(RunORM, run_id)
            assert row is not None
            assert row.status == RunStatusEnum.CANCELLED, (
                f"expected CANCELLED terminal, got {row.status}"
            )
    finally:
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
