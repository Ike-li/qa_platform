from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import uuid
from typing import Any

import aiodocker
from arq import cron, func
from arq.connections import RedisSettings

from qaplatform.observability.tracing import instrument_infra, setup_tracing
from qaplatform.worker.tasks import execute_run

log = logging.getLogger(__name__)


def _schedule_run_audit_state(run: Any, *, schedule_id: uuid.UUID, enqueued: bool) -> dict:
    status = run.status.value if hasattr(run.status, "value") else run.status
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "project_id": str(run.project_id),
        "pipeline_id": str(run.pipeline_id),
        "environment_id": str(run.environment_id) if run.environment_id else None,
        "status": status,
        "trigger_type": run.trigger_type,
        "triggered_by": str(run.triggered_by) if run.triggered_by else None,
        "git_ref": run.git_ref,
        "git_sha": run.git_sha,
        "priority": run.priority,
        "attempt": run.attempt,
        "metadata": run.metadata_ or {},
        "schedule_id": str(schedule_id),
        "enqueued": enqueued,
    }


def _schedule_skip_audit_state(
    schedule: Any,
    *,
    reason: str,
    last_error: str,
    next_run_at: datetime | None,
) -> dict:
    return {
        "schedule_id": str(schedule.id),
        "project_id": str(schedule.project_id),
        "pipeline_id": str(schedule.pipeline_id),
        "status": "skipped",
        "reason": reason,
        "last_error": last_error,
        "next_run_at": next_run_at.isoformat() if next_run_at is not None else None,
    }


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
    container.init_crypto()
    provider = setup_tracing(settings)
    if provider is not None:
        instrument_infra(container, provider)

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
    from qaplatform.api.metrics import run_queue_depth, runs_in_flight
    from qaplatform.engine.reclaim import reclaim_worker_lost
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.worker.tasks import _schedule_retry_for_run

    session_factory = ctx.get("db_session_factory")
    redis = ctx.get("redis")
    arq = ctx.get("arq_pool")
    settings = ctx.get("settings")
    if session_factory is None or redis is None:
        return

    async with session_factory() as session:
        run_repo = RunRepository(session)

        async def _retry_reclaimed(run, message: str) -> None:
            if arq is None or settings is None:
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
        log.info("retention_cleanup_done deleted=%s cutoff=%s", deleted, cutoff.isoformat())


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
    from types import SimpleNamespace

    from qaplatform.api.audit import write_audit
    from qaplatform.domain.services.schedule import (
        ScheduleSkippedSilentWindowAudit,
        is_in_silent_window,
        silent_windows_from_settings,
    )
    from qaplatform.domain.services.scheduling import (
        compute_next_run_at,
        should_fire,
    )
    from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository
    from qaplatform.infra.database.repositories.project_repo import (
        EnvironmentRepository,
        PipelineRepository,
        ProjectRepository,
        ScheduleRepository,
    )
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.worker.scheduler import enqueue_run

    session_factory = ctx.get("db_session_factory")
    arq = ctx.get("arq_pool")
    settings = ctx.get("settings")
    if session_factory is None or arq is None:
        return

    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        schedule_repo = ScheduleRepository(session)
        run_repo = RunRepository(session)
        project_repo = ProjectRepository(session)
        pipeline_repo = PipelineRepository(session)
        env_repo = EnvironmentRepository(session)
        audit_repo = AuditEventRepository(session)

        due = await schedule_repo.find_due_schedules(now)
        if not due:
            return

        for schedule in due:
            if not should_fire(schedule, now):
                # In quiet window or not yet due — just skip
                continue

            try:
                # Resolve pipeline for project context
                pipeline = await pipeline_repo.get_by_id(schedule.pipeline_id)
                if pipeline is None:
                    next_run = compute_next_run_at(schedule.cron_expr, schedule.timezone, now)
                    await schedule_repo.update_after_fire(
                        schedule.id,
                        last_run_at=now,
                        next_run_at=next_run,
                        last_error="pipeline not found",
                    )
                    project = await project_repo.get_by_id(schedule.project_id)
                    audit_repos = SimpleNamespace(audit=audit_repo)
                    audit_user = SimpleNamespace(
                        tenant_id=getattr(project, "tenant_id", None),
                        user_id=None,
                    )
                    await write_audit(
                        audit_repos,
                        audit_user,
                        action="schedule_skipped_missing_pipeline",
                        resource_type="schedule",
                        resource_id=schedule.id,
                        after=_schedule_skip_audit_state(
                            schedule,
                            reason="pipeline_not_found",
                            last_error="pipeline not found",
                            next_run_at=next_run,
                        ),
                    )
                    await session.commit()
                    continue

                project = await project_repo.get_by_id(schedule.project_id)
                if project is None:
                    await schedule_repo.update_after_fire(
                        schedule.id,
                        last_run_at=now,
                        next_run_at=compute_next_run_at(schedule.cron_expr, schedule.timezone, now),
                        last_error="project not found",
                    )
                    continue

                silent_window = is_in_silent_window(
                    silent_windows_from_settings(project.settings),
                    now,
                )
                if silent_window is not None:
                    audit_repos = SimpleNamespace(audit=audit_repo)
                    audit_user = SimpleNamespace(tenant_id=project.tenant_id, user_id=None)
                    await write_audit(
                        audit_repos,
                        audit_user,
                        action="schedule_skipped_silent_window",
                        resource_type="schedule",
                        resource_id=schedule.id,
                        after=ScheduleSkippedSilentWindowAudit(
                            schedule_id=schedule.id,
                            window=silent_window,
                        ),
                    )
                    await session.commit()
                    continue

                # Resolve environment
                envs, _ = await env_repo.list_by_project(schedule.project_id, limit=1)
                environment_id = envs[0].id if envs else None

                # Determine git_ref from pipeline's project default
                git_ref = project.default_branch or "main"

                run = await run_repo.create(
                    tenant_id=project.tenant_id,
                    project_id=schedule.project_id,
                    pipeline_id=schedule.pipeline_id,
                    environment_id=environment_id,
                    git_ref=git_ref,
                    trigger_type="schedule",
                    metadata_={"schedule_id": str(schedule.id)},
                )
                run.retry_group_id = run.id
                await session.commit()

                enqueued = await enqueue_run(arq, run_repo, run, "schedule", settings)
                audit_repos = SimpleNamespace(audit=audit_repo)
                audit_user = SimpleNamespace(tenant_id=project.tenant_id, user_id=None)
                await write_audit(
                    audit_repos,
                    audit_user,
                    action="run.trigger",
                    resource_type="run",
                    resource_id=run.id,
                    after=_schedule_run_audit_state(
                        run,
                        schedule_id=schedule.id,
                        enqueued=enqueued,
                    ),
                )
                next_run = compute_next_run_at(schedule.cron_expr, schedule.timezone, now)
                await schedule_repo.update_after_fire(
                    schedule.id,
                    last_run_at=now,
                    next_run_at=next_run,
                    last_error=None if enqueued else "enqueue failed",
                )
                await session.commit()

                log.info(
                    "schedule_fired",
                    extra={
                        "schedule_id": str(schedule.id),
                        "run_id": str(run.id),
                        "enqueued": enqueued,
                    },
                )
            except Exception:
                log.exception("schedule_fire_failed", extra={"schedule_id": str(schedule.id)})
                try:
                    next_run = compute_next_run_at(schedule.cron_expr, schedule.timezone, now)
                    await schedule_repo.update_after_fire(
                        schedule.id,
                        last_run_at=now,
                        next_run_at=next_run,
                        last_error="internal error",
                    )
                    await session.commit()
                except Exception:
                    log.exception("schedule_update_failed", extra={"schedule_id": str(schedule.id)})


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
        cron(check_schedules, second={15}),
        cron(retry_failed_archives, second={45}),
        cron(cleanup_old_runs, minute={0}, second={0}),  # hourly retention sweep
    ]
    redis_settings = _get_redis_settings()
