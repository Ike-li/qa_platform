"""F-EX-06 cancel E2E：HTTP POST /runs/{id}/cancel 触发，10s 内容器 SIGTERM 退出。

完整链路：
    HTTP POST /runs/{run_id}/cancel
        -> cancel_if_current (DB 终态写 CANCELLED)
        -> publish_cancel(redis, run_id)
        -> watch_for_cancel picks up message
        -> RunExecutor._handle_cancel_signal -> _graceful_stop
        -> DockerBackend.cancel() -> container SIGTERM
        -> sleep 60 退出，executor.execute() 返回
        -> fail_if_current rowcount=0（终态 CANCELLED 已不在 expected）

终态：CANCELLED（不是原 mock 版本的 FAILED）。

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


@pytest.mark.asyncio
async def test_cancel_via_http_terminates_within_10s(
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

    # claim_for_worker -> commit
    async with factory() as worker_session:
        wr = RunRepository(worker_session)
        claimed = await wr.claim_for_worker(run_id, worker_id="test-worker-3")
        assert claimed is not None, "could not claim seeded run"
        await worker_session.commit()

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
        # 等容器进入 active + watcher 完成订阅
        deadline = time.monotonic() + 30.0
        while getattr(executor, "_active_execution_id", None) is None:
            if time.monotonic() > deadline:
                pytest.fail("container never became active within 30s")
            if execute_task.done():
                await execute_task
                pytest.fail("execute() returned before container active")
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.5)

        # F-EX-06: HTTP POST cancel 触发的全链路完成 < 10s
        t_cancel = time.monotonic()
        response = await integration_client.post(f"/runs/{run_id}/cancel")
        assert response.status_code == 200, response.text

        try:
            await asyncio.wait_for(execute_task, timeout=15.0)
        except asyncio.TimeoutError:
            execute_task.cancel()
            pytest.fail(
                "executor did not return within 15s of HTTP cancel"
            )
        elapsed = time.monotonic() - t_cancel
        assert elapsed < 10.0, (
            f"F-EX-06: HTTP cancel -> container exit took {elapsed:.2f}s"
        )

        # 终态：CANCELLED（cancel API 写入；executor 的 fail_if_current
        # 因 expected_in 不含 CANCELLED 而 rowcount=0，不会覆盖）
        async with factory() as observer:
            row = await observer.get(RunORM, run_id)
            assert row is not None
            assert row.status == RunStatusEnum.CANCELLED, (
                f"expected terminal CANCELLED, got {row.status}"
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
