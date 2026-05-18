from __future__ import annotations

import os
import uuid

import aiodocker
from arq import cron, func
from arq.connections import RedisSettings

from qaplatform.worker.tasks import execute_run


async def on_startup(ctx: dict) -> None:
    """arq on_startup hook: initialise worker dependencies."""
    from qaplatform.config import Settings
    from qaplatform.dependencies import DependencyContainer
    from qaplatform.engine.docker_backend import DockerBackend
    from qaplatform.engine.executor import RunExecutor
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.plugins.registry import PluginRegistry

    settings = Settings()
    container = DependencyContainer(settings)
    await container.init_db()
    await container.init_redis()
    await container.init_arq()
    await container.init_s3()

    worker_id = f"worker-{uuid.uuid4().hex[:8]}"

    log_stream = LogStream(container.redis_client)
    plugin_registry = PluginRegistry()
    plugin_registry.register_builtins()
    docker_client = aiodocker.Docker()
    ctx["docker_client"] = docker_client
    backend = DockerBackend(docker_client)
    executor = RunExecutor(
        backend=backend,
        log_stream=log_stream,
        run_repo=None,  # set per-job from session-scoped repo
        plugin_registry=plugin_registry,
    )

    ctx["docker_backend"] = backend
    ctx["plugin_registry"] = plugin_registry
    ctx["container"] = container
    ctx["settings"] = settings
    ctx["worker_id"] = worker_id
    ctx["redis"] = container.redis_client
    ctx["arq_pool"] = container.arq_pool
    ctx["log_stream"] = log_stream
    ctx["executor"] = executor
    ctx["s3_client"] = container.s3_client
    ctx["s3_bucket"] = settings.s3_bucket
    ctx["db_session_factory"] = container.db_session_factory


async def on_shutdown(ctx: dict) -> None:
    """arq on_shutdown hook: clean up resources."""
    container = ctx.get("container")
    try:
        if container and hasattr(container, "close"):
            await container.close()
    finally:
        docker_client = ctx.get("docker_client")
        if docker_client is not None:
            await docker_client.close()


async def reclaim_resources(ctx: dict) -> None:
    """Periodic task: reclaim orphan containers and timeout stale runs."""
    from qaplatform.engine.reclaim import reclaim_worker_lost
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    session_factory = ctx.get("db_session_factory")
    redis = ctx.get("redis")
    if session_factory is None or redis is None:
        return

    async with session_factory() as session:
        run_repo = RunRepository(session)
        try:
            await reclaim_worker_lost(
                run_repo=run_repo,
                redis=redis,
                backend=ctx.get("docker_backend"),
            )
        finally:
            await session.commit()


async def dequeue_waiting(ctx: dict) -> None:
    """Periodic task: enqueue waiting runs when capacity is available."""
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.worker.scheduler import FairScheduler

    session_factory = ctx.get("db_session_factory")
    if session_factory is None:
        return

    async with session_factory() as session:
        run_repo = RunRepository(session)
        scheduler = FairScheduler(
            arq=ctx["arq_pool"],
            run_repo=run_repo,
            settings=ctx["settings"],
        )
        await scheduler.try_dequeue_waiting()
        await session.commit()


async def retry_failed_archives(ctx: dict) -> None:
    """Periodic task: retry failed log archival."""


async def after_job_end(ctx: dict) -> None:
    """arq after_job_end hook: compensate failed jobs."""
    if ctx.get("success"):
        return

    job_id = ctx.get("job_id", "")
    if not job_id.startswith("run:"):
        return

    from qaplatform.domain.models.run import TERMINAL_STATUSES

    run_id = job_id.removeprefix("run:")
    run_repo = ctx.get("run_repo")
    if run_repo is None:
        return

    run = await run_repo.get(run_id)
    if run and run.status not in TERMINAL_STATUSES:
        from qaplatform.worker._redact import redact_url_userinfo
        await run_repo.fail_if_current(
            run.id,
            message=redact_url_userinfo(
                f"arq job failed: {ctx.get('result', 'unknown error')}"
            ),
        )


def _get_redis_settings() -> RedisSettings:
    redis_url = os.environ.get("QAP_REDIS_URL", "redis://localhost:6379/0")
    return RedisSettings.from_dsn(redis_url)


class WorkerSettings:
    """arq WorkerSettings for the QA Platform."""

    queue_name: str = os.environ.get("QAP_WORKER_QUEUE", "queue:medium")
    functions = [func(execute_run, name="execute_run", max_tries=1)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    on_job_end = after_job_end
    cron_jobs = [
        cron(reclaim_resources, second={0}),
        cron(dequeue_waiting, second={30}),
        cron(retry_failed_archives, second={45}),
    ]
    redis_settings = _get_redis_settings()
