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
        response = await integration_client.post(f"/api/v1/runs/{run_id}/cancel")
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


# --------------------------------------------------------------------------- #
# P1-D race regressions on real PG + redis + docker
# --------------------------------------------------------------------------- #


def _p1d_plugin_registry(command: str):
    """Build a plugin_registry mock that runs a single shell command."""
    plugin_registry = MagicMock()
    runner = MagicMock()
    runner.build_command = MagicMock(return_value=command)
    plugin_registry.get_runner.return_value = runner
    collector = MagicMock()
    collector.collect = AsyncMock(return_value=[])
    plugin_registry.get_collector.return_value = collector
    return plugin_registry


def _p1d_run_domain(seed_run, run_id):
    return RunDomain(
        id=run_id,
        tenant_id=seed_run["tenant"].id,
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        environment_id=seed_run["environment"].id,
        git_ref="main",
        metadata={},
    )


def _p1d_pipeline(image: str, stage_names: list[str]):
    return PipelineConfig(
        image=image,
        stages=[
            StageDefinition(name=n, plugin="pytest", phase="execute")
            for n in stage_names
        ],
        env_vars={},
        resource_limits=ResourceLimits(
            memory_bytes=128 * 1024 * 1024, cpu_cores=0.5,
        ),
        network_policy="allow",
        timeout_seconds=120,
    )


def _spy_create_execution(backend: DockerBackend):
    """Wrap backend.create_execution to count invocations without
    replacing behaviour. Returns the AsyncMock spy."""
    real = backend.create_execution

    async def _wrapper(*args, **kwargs):
        return await real(*args, **kwargs)

    spy = AsyncMock(side_effect=_wrapper)
    backend.create_execution = spy  # type: ignore[method-assign]
    return spy


@pytest.mark.asyncio
async def test_cancel_at_stage_boundary_skips_next_stage(
    docker_available,
    alpine_image_pulled,
    aiodocker_client,
    integration_app,
    seed_run,
    integration_db_engine,
):
    """P1-D regression: cancel that lands while ``_active_execution_id`` is
    None (between stages) used to be silently dropped — the watcher
    callback returned without setting any persistent flag, and the second
    stage started normally.

    We force the race by writing ``cancel_requested_at`` directly to the
    DB (skipping ``publish_cancel``) while stage 1 is running. When stage
    1 exits naturally the executor must hit ``_check_cancel_boundary``,
    pick up the cancel via the fresh SELECT fallback, and break out of
    the stage loop instead of starting stage 2.
    """
    run_id = seed_run["run"].id
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)

    async with factory() as worker_session:
        wr = RunRepository(worker_session)
        claimed = await wr.claim_for_worker(
            run_id, worker_id="test-worker-p1d-boundary"
        )
        assert claimed is not None, "could not claim seeded run"
        await worker_session.commit()

    backend = DockerBackend(aiodocker_client)
    create_execution_spy = _spy_create_execution(backend)
    exec_session = factory()
    executor = RunExecutor(
        backend=backend,
        log_stream=AsyncMock(),
        run_repo=RunRepository(exec_session),
        plugin_registry=_p1d_plugin_registry("sleep 1"),
        s3_client=None,
        artifact_repo=ArtifactRepository(exec_session),
        redis=integration_app.state.container.redis_client,
    )

    execute_task = asyncio.create_task(
        executor.execute(
            _p1d_run_domain(seed_run, run_id),
            _p1d_pipeline(alpine_image_pulled, ["stage-1", "stage-2"]),
        )
    )

    try:
        deadline = time.monotonic() + 30.0
        while getattr(executor, "_active_execution_id", None) is None:
            if time.monotonic() > deadline:
                pytest.fail("stage-1 container never became active within 30s")
            if execute_task.done():
                await execute_task
                pytest.fail("execute() returned before stage-1 active")
            await asyncio.sleep(0.05)

        # DB-only cancel: simulate a pub/sub message that was dropped or
        # arrived during the brief stage transition window.
        async with factory() as cancel_session:
            cancelled = await RunRepository(cancel_session).cancel_if_current(run_id)
            assert cancelled, "direct DB cancel did not update the active run"
            await cancel_session.commit()

        t_cancel = time.monotonic()
        try:
            await asyncio.wait_for(execute_task, timeout=15.0)
        except asyncio.TimeoutError:
            pytest.fail("executor did not stop at the stage boundary within 15s")

        elapsed = time.monotonic() - t_cancel
        # Stage 1 was already running ``sleep 1``; the boundary check
        # must fire on the next stage transition without waiting for
        # any extra timeout.
        assert elapsed < 10.0, f"stage-boundary cancel took {elapsed:.2f}s"
        # Stage 2 must NOT have been launched — that is the whole point
        # of the boundary check.
        execution_specs = [
            call.args[0] for call in create_execution_spy.await_args_list
        ]
        assert [
            {"labels": spec.labels, "command": spec.command}
            for spec in execution_specs
        ] == [
            {
                "labels": {
                    "run_id": str(run_id),
                    "stage": "stage-1",
                },
                "command": ["sh", "-c", "sleep 1"],
            }
        ]

        async with factory() as observer:
            row = await observer.get(RunORM, run_id)
            assert row is not None
            assert row.status == RunStatusEnum.CANCELLED
            assert row.cancel_requested_at is not None
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


@pytest.mark.asyncio
async def test_cancel_recovered_when_published_before_subscribe(
    docker_available,
    alpine_image_pulled,
    aiodocker_client,
    integration_app,
    seed_run,
    integration_db_engine,
):
    """P1-D regression: redis pub/sub is fire-and-forget, so a cancel
    that publishes before the executor's ``pubsub.subscribe`` completes
    is gone forever. The DB write of ``cancel_requested_at`` is the
    durable truth source — the boundary check before stage 1 must pick
    it up via the fresh SELECT and short-circuit the run before any
    container starts.
    """
    from qaplatform.engine.cancel import publish_cancel

    run_id = seed_run["run"].id
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    redis = integration_app.state.container.redis_client

    async with factory() as worker_session:
        wr = RunRepository(worker_session)
        claimed = await wr.claim_for_worker(
            run_id, worker_id="test-worker-p1d-presub"
        )
        assert claimed is not None, "could not claim seeded run"
        await worker_session.commit()

    # Cancel happens BEFORE the executor exists — the publish hits an
    # empty pub/sub channel and is lost; only the DB row carries the
    # signal forward.
    async with factory() as cancel_session:
        cancelled = await RunRepository(cancel_session).cancel_if_current(run_id)
        assert cancelled, "pre-subscribe DB cancel did not update the run"
        await cancel_session.commit()
    await publish_cancel(redis, run_id)

    backend = DockerBackend(aiodocker_client)
    create_execution_spy = _spy_create_execution(backend)
    exec_session = factory()
    executor = RunExecutor(
        backend=backend,
        log_stream=AsyncMock(),
        run_repo=RunRepository(exec_session),
        plugin_registry=_p1d_plugin_registry("sleep 30"),
        s3_client=None,
        artifact_repo=ArtifactRepository(exec_session),
        redis=redis,
    )

    execute_task = asyncio.create_task(
        executor.execute(
            _p1d_run_domain(seed_run, run_id),
            _p1d_pipeline(alpine_image_pulled, ["stage-1"]),
        )
    )

    try:
        started = time.monotonic()
        try:
            await asyncio.wait_for(execute_task, timeout=15.0)
        except asyncio.TimeoutError:
            pytest.fail("executor missed pre-subscribe cancel and did not return")

        elapsed = time.monotonic() - started
        assert elapsed < 10.0, f"pre-subscribe cancel recovery took {elapsed:.2f}s"
        # Boundary check must fire BEFORE the first container launch.
        create_execution_spy.assert_not_awaited()

        async with factory() as observer:
            row = await observer.get(RunORM, run_id)
            assert row is not None
            assert row.status == RunStatusEnum.CANCELLED
            assert row.cancel_requested_at is not None
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


@pytest.mark.asyncio
async def test_repeated_http_cancel_is_idempotent(
    docker_available,
    alpine_image_pulled,
    aiodocker_client,
    integration_app,
    integration_client,
    seed_run,
    integration_db_engine,
):
    """P1-D regression: duplicate cancel requests happen in practice
    (user double-clicks, retries during pub/sub races). The second call
    must not 5xx, must not overwrite ``cancel_requested_at`` with a
    later timestamp, and must not strand the executor.
    """
    run_id = seed_run["run"].id
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)

    async with factory() as worker_session:
        wr = RunRepository(worker_session)
        claimed = await wr.claim_for_worker(
            run_id, worker_id="test-worker-p1d-idem"
        )
        assert claimed is not None, "could not claim seeded run"
        await worker_session.commit()

    backend = DockerBackend(aiodocker_client)
    exec_session = factory()
    executor = RunExecutor(
        backend=backend,
        log_stream=AsyncMock(),
        run_repo=RunRepository(exec_session),
        plugin_registry=_p1d_plugin_registry("sleep 60"),
        s3_client=None,
        artifact_repo=ArtifactRepository(exec_session),
        redis=integration_app.state.container.redis_client,
    )

    execute_task = asyncio.create_task(
        executor.execute(
            _p1d_run_domain(seed_run, run_id),
            _p1d_pipeline(alpine_image_pulled, ["exec"]),
        )
    )

    try:
        deadline = time.monotonic() + 30.0
        while getattr(executor, "_active_execution_id", None) is None:
            if time.monotonic() > deadline:
                pytest.fail("container never became active within 30s")
            if execute_task.done():
                await execute_task
                pytest.fail("execute() returned before container active")
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.5)

        t_cancel = time.monotonic()
        first = await integration_client.post(f"/api/v1/runs/{run_id}/cancel")
        assert first.status_code == 200, first.text

        async with factory() as observer:
            row = await observer.get(RunORM, run_id)
            assert row is not None
            first_cancel_requested_at = row.cancel_requested_at
            assert first_cancel_requested_at is not None

        # Second cancel: once the first request writes the terminal
        # CANCELLED state, the API contract is an explicit conflict.
        # Returning 200 here would hide duplicate event/audit side effects.
        second = await integration_client.post(f"/api/v1/runs/{run_id}/cancel")
        assert second.status_code == 409, second.text
        assert second.json() == {"detail": "Run already in terminal status: cancelled"}

        async with factory() as observer:
            row = await observer.get(RunORM, run_id)
            assert row is not None
            assert row.status == RunStatusEnum.CANCELLED
            # Idempotency: cancel_requested_at must not be moved forward.
            assert row.cancel_requested_at == first_cancel_requested_at

        try:
            await asyncio.wait_for(execute_task, timeout=15.0)
        except asyncio.TimeoutError:
            pytest.fail("executor did not return after repeated HTTP cancel")

        elapsed = time.monotonic() - t_cancel
        assert elapsed < 10.0, f"repeated HTTP cancel path took {elapsed:.2f}s"

        async with factory() as observer:
            row = await observer.get(RunORM, run_id)
            assert row is not None
            assert row.status == RunStatusEnum.CANCELLED
            assert row.cancel_requested_at == first_cancel_requested_at
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
