from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import uuid

import aiodocker
from arq import cron, func
from arq.connections import RedisSettings

from qaplatform.observability.tracing import instrument_infra, setup_tracing
from qaplatform.worker.schedule_firing import (
    _schedule_run_audit_state as _schedule_run_audit_state,
    _schedule_skip_audit_state as _schedule_skip_audit_state,
    fire_due_schedules,
)
from qaplatform.worker.tasks import execute_run

log = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    """arq on_startup hook: initialise worker dependencies."""
    from qaplatform.config import Settings
    from qaplatform.dependencies import DependencyContainer
    from qaplatform.engine.docker_backend import DockerBackend
    from qaplatform.infra.log_stream import LogStream
    from qaplatform.logging import configure_logging
    from qaplatform.plugins.registry import PluginRegistry

    settings = Settings()
    configure_logging(settings)
    container = DependencyContainer(settings)
    await container.init_db()
    await container.init_redis()
    await container.init_arq()
    await container.init_s3()
    container.init_crypto()
    provider = setup_tracing(settings)
    if provider is not None:
        instrument_infra(container, provider)

    worker_id = f"worker-{uuid.uuid4().hex[:8]}"

    log_stream = LogStream(container.redis_client)
    plugin_registry = PluginRegistry(
        git_allowed_private_hosts=settings.git_allowed_private_hosts,
        git_clone_timeout_seconds=settings.preparing_timeout_seconds,
    )
    plugin_registry.register_builtins()
    docker_client = aiodocker.Docker()
    ctx["docker_client"] = docker_client
    backend = DockerBackend(docker_client)

    ctx["docker_backend"] = backend
    ctx["plugin_registry"] = plugin_registry
    ctx["container"] = container
    ctx["settings"] = settings
    ctx["worker_id"] = worker_id
    ctx["redis"] = container.redis_client
    ctx["arq_pool"] = container.arq_pool
    ctx["log_stream"] = log_stream
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
    from qaplatform.engine.events import publish_status_event
    from qaplatform.observability.metrics import run_queue_depth, runs_in_flight
    from qaplatform.infra.database.models import RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.worker.tasks import _schedule_retry_for_run

    session_factory = ctx.get("db_session_factory")
    redis = ctx.get("redis")
    arq = ctx.get("arq_pool")
    settings = ctx.get("settings")
    if session_factory is None or redis is None or settings is None:
        return

    async with session_factory() as session:
        run_repo = RunRepository(session)

        async def _retry_reclaimed(run, message: str) -> None:
            if arq is None:
                return
            await _schedule_retry_for_run(
                run,
                ConnectionError(message),
                run_repo=run_repo,
                arq=arq,
                settings=settings,
            )

        try:
            await reclaim_worker_lost(
                run_repo=run_repo,
                redis=redis,
                backend=ctx.get("docker_backend"),
                on_reclaimed=_retry_reclaimed,
            )
            now = datetime.now(timezone.utc)
            stale_preparing = await run_repo.find_stale(
                status=RunStatusEnum.PREPARING,
                older_than=now - timedelta(seconds=settings.preparing_timeout_seconds),
            )
            for run in stale_preparing:
                updated = await run_repo.fail_if_current(
                    run.id,
                    expected_in=[RunStatusEnum.PREPARING],
                    message=(
                        "preparing_timeout: exceeded "
                        f"{settings.preparing_timeout_seconds}s"
                    ),
                )
                if updated:
                    await publish_status_event(
                        redis, run.id, "failed", previous="preparing"
                    )
                    if run.worker_id:
                        await run_repo.release_worker(run.id, worker_id=run.worker_id)

            stale_collecting = await run_repo.find_stale(
                status=RunStatusEnum.COLLECTING,
                older_than=now - timedelta(seconds=settings.collecting_timeout_seconds),
            )
            for run in stale_collecting:
                updated = await run_repo.finish_if_current(
                    run.id,
                    status=RunStatusEnum.TIMEOUT,
                    expected_in=[RunStatusEnum.COLLECTING],
                    summary={
                        "resource_termination": {
                            "reason": "collecting_timeout",
                            "timeout_seconds": settings.collecting_timeout_seconds,
                        }
                    },
                )
                if updated:
                    await publish_status_event(
                        redis, run.id, "timeout", previous="collecting"
                    )
                    if run.worker_id:
                        await run_repo.release_worker(run.id, worker_id=run.worker_id)

            # Update gauges after reclaim so values reflect post-cleanup state
            in_flight = await run_repo.count_active_or_enqueued()
            runs_in_flight.set(in_flight)
            queue_depth = await run_repo.count_queued_waiting()
            run_queue_depth.set(queue_depth)
        finally:
            await session.commit()


async def dequeue_waiting(ctx: dict) -> None:
    """Periodic task: enqueue waiting runs when capacity is available."""
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.infra.queue.scheduler import FairScheduler

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


async def cleanup_old_runs(ctx: dict) -> None:
    """Periodic task: delete terminal runs older than retention_runs_days."""
    from datetime import timedelta

    from qaplatform.infra.database.repositories.run_repo import RunRepository

    session_factory = ctx.get("db_session_factory")
    settings = ctx.get("settings")
    if session_factory is None or settings is None:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_runs_days)
    async with session_factory() as session:
        run_repo = RunRepository(session)
        deleted = await run_repo.delete_terminal_older_than(cutoff=cutoff)
        await session.commit()
    if deleted:
        log.info(
            "retention_cleanup_done deleted=%s cutoff=%s", deleted, cutoff.isoformat()
        )


async def cleanup_old_audit_events(ctx: dict) -> None:
    """Periodic task: delete audit events older than retention_audit_days."""
    from datetime import timedelta

    from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository

    session_factory = ctx.get("db_session_factory")
    settings = ctx.get("settings")
    if session_factory is None or settings is None:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_audit_days)
    async with session_factory() as session:
        audit_repo = AuditEventRepository(session)
        deleted = await audit_repo.delete_older_than(cutoff=cutoff)
        await session.commit()
    if deleted:
        log.info(
            "audit_retention_cleanup_done deleted=%s cutoff=%s",
            deleted,
            cutoff.isoformat(),
        )


async def retry_failed_archives(ctx: dict) -> None:
    """Periodic task: retry failed log archival."""
    log_stream = ctx.get("log_stream")
    s3_client = ctx.get("s3_client")
    bucket = ctx.get("s3_bucket")
    if log_stream is None or s3_client is None or not bucket:
        return

    retried = await log_stream.retry_failed_archives(s3_client, bucket)
    if retried:
        log.info("log_archive_retry_done retried=%s", retried)


async def check_schedules(ctx: dict) -> None:
    """Periodic task: fire due schedules by creating runs and enqueueing them."""
    await fire_due_schedules(ctx)


async def after_job_end(ctx: dict) -> None:
    """arq after_job_end hook: compensate failed jobs."""
    if ctx.get("success"):
        return

    job_id = ctx.get("job_id", "")
    if not job_id.startswith("run:"):
        return

    from qaplatform.domain.services.execution import is_terminal_status
    from qaplatform.engine.redact import redact_url_userinfo
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    try:
        run_id = uuid.UUID(job_id.removeprefix("run:"))
    except ValueError:
        return

    session_factory = ctx.get("db_session_factory")
    if session_factory is None:
        return

    async with session_factory() as session:
        run_repo = RunRepository(session)
        run = await run_repo.get_by_id(run_id)
        if run is None:
            return

        if is_terminal_status(run.status):
            return

        await run_repo.fail_if_current(
            run.id,
            message=redact_url_userinfo(
                f"arq job failed: {ctx.get('result', 'unknown error')}"
            ),
        )
        await session.commit()


def _get_redis_settings() -> RedisSettings:
    redis_url = os.environ.get("QAP_REDIS_URL", "redis://localhost:6379/0")
    return RedisSettings.from_dsn(redis_url)


def _get_worker_max_jobs() -> int:
    raw_value = os.environ.get("QAP_WORKER_MAX_JOBS", "10")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("QAP_WORKER_MAX_JOBS must be an integer") from exc
    if value < 1:
        raise ValueError("QAP_WORKER_MAX_JOBS must be >= 1")
    return value


class WorkerSettings:
    """arq WorkerSettings for the QA Platform."""

    queue_name: str = os.environ.get("QAP_WORKER_QUEUE", "queue:medium")
    max_jobs: int = _get_worker_max_jobs()
    functions = [func(execute_run, name="execute_run", max_tries=1)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    on_job_end = after_job_end
    cron_jobs = [
        cron(reclaim_resources, second={0}),
        cron(dequeue_waiting, second={30}),
        cron(check_schedules, second={15}),
        cron(retry_failed_archives, second={45}),
        cron(cleanup_old_runs, minute={0}, second={0}),  # hourly retention sweep
        cron(
            cleanup_old_audit_events, minute={5}, second={0}
        ),  # hourly audit retention sweep
    ]
    redis_settings = _get_redis_settings()
