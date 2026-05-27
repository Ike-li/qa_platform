from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from sqlalchemy import select as _select

from qaplatform.domain.models.run import RunStatus
from qaplatform.infra.database.models import Project

log = logging.getLogger(__name__)

# Exceptions that represent infrastructure failures (not test logic errors).
# Only these trigger automatic retries per PRD F-EX-07.
_INFRA_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)


async def _heartbeat_loop(worker_id: str, redis: Any, interval: int = 30) -> None:
    """Background task: refresh worker heartbeat key every interval seconds.

    Transient errors (Redis blip) are logged and the loop continues — only
    CancelledError exits cleanly. This prevents the heartbeat task from
    silently dying and causing the reclaimer to flag a still-alive worker
    as worker_lost.
    """
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            await redis.set(f"worker:{worker_id}:heartbeat", now, ex=90)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("worker_heartbeat_set_failed", extra={"worker_id": worker_id}, exc_info=True)
        # Use separate try/except for sleep to ensure CancelledError propagates cleanly
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


def _should_retry(exc: Exception, retry_policy: dict | None, current_attempt: int) -> bool:
    """Determine if a failed run should be retried.

    Only infrastructure failures (Docker, network, OS errors) trigger retries.
    Test failures (exit_code != 0) are handled through finish_if_current and
    never reach this path.
    """
    if retry_policy is None:
        return False
    if not retry_policy.get("enabled", True):
        return False
    retry_on = retry_policy.get("retry_on") or []
    if retry_on and "infra" not in retry_on:
        return False
    max_retries = _max_retries_from_policy(retry_policy)
    if max_retries <= 0:
        return False
    if current_attempt >= max_retries + 1:
        return False
    if not isinstance(exc, _INFRA_EXCEPTIONS):
        return False
    return True


def _max_retries_from_policy(retry_policy: dict) -> int:
    """Return retry count from legacy max_retries or API-facing max_attempts."""
    if "max_retries" in retry_policy:
        return int(retry_policy.get("max_retries") or 0)
    if "max_attempts" in retry_policy:
        return max(0, int(retry_policy.get("max_attempts") or 1) - 1)
    return 0


async def _schedule_retry_for_run(
    original: Any,
    exc: Exception,
    *,
    run_repo: Any,
    arq: Any,
    settings: Any,
) -> bool:
    """Create a retry run and put it in the scheduler lane.

    ``False`` means no retry run was created. A retry run that is waiting due to
    capacity still counts as scheduled because the dequeue cron can pick it up.
    """
    from qaplatform.worker.scheduler import FairScheduler

    retry_policy = getattr(original.pipeline, "retry_policy", None)
    if not _should_retry(exc, retry_policy, original.attempt):
        return False

    backoff = retry_policy.get("backoff_seconds", 30)
    delay = backoff * (2 ** (original.attempt - 1))
    retry_group_id = original.retry_group_id or original.id

    retry_run = await run_repo.create(
        tenant_id=original.tenant_id,
        project_id=original.project_id,
        pipeline_id=original.pipeline_id,
        environment_id=original.environment_id,
        git_ref=original.git_ref,
        git_sha=original.git_sha,
        priority=original.priority,
        triggered_by=original.triggered_by,
        trigger_type=original.trigger_type,
        metadata_=dict(original.metadata_ or {}),
        retry_group_id=retry_group_id,
        attempt=original.attempt + 1,
        source_run_id=original.id,
        chain_depth=(original.chain_depth or 0) + 1,
    )

    scheduler = FairScheduler(arq, run_repo, settings)
    enqueued = await scheduler.enqueue(retry_run, _defer_by=delay)
    if enqueued:
        log.info(
            "retry_scheduled",
            extra={
                "original_run_id": str(original.id),
                "retry_run_id": str(retry_run.id),
                "attempt": retry_run.attempt,
                "delay_seconds": delay,
            },
        )
    else:
        log.info(
            "retry_waiting",
            extra={
                "original_run_id": str(original.id),
                "retry_run_id": str(retry_run.id),
            },
        )
    return True


async def _attempt_retry(
    run_id: str,
    exc: Exception,
    ctx: dict,
    session_factory: Any,
) -> bool:
    """Create a retry run and enqueue it. Returns True if a retry was scheduled."""
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    async with session_factory() as session:
        run_repo = RunRepository(session)
        original = await run_repo.get_by_id(run_id)
        if original is None:
            return False

        await session.refresh(original, ["pipeline"])
        retry_policy = getattr(original.pipeline, "retry_policy", None)
        if not _should_retry(exc, retry_policy, original.attempt):
            return False

        scheduled = await _schedule_retry_for_run(
            original,
            exc,
            run_repo=run_repo,
            arq=ctx["arq_pool"],
            settings=ctx["settings"],
        )
        await session.commit()
        return scheduled


async def execute_run(ctx: dict, run_id: str) -> None:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("execute_run", attributes={"run.id": str(run_id)}):
        return await _execute_run(ctx, run_id)


async def _execute_run(ctx: dict, run_id: str) -> None:
    """arq task entry point: execute a QA pipeline run.

    Flow:
    1. claim_for_worker (queued -> preparing)
    2. executor.execute()
    3. On exception: fail_if_current
    4. Finally: archive logs, release worker
    """
    from qaplatform.infra.database.repositories.run_repo import (
        ArtifactRepository,
        RunRepository,
    )
    from qaplatform.engine.events import publish_status_event
    from qaplatform.engine.executor import RunExecutor

    log_stream = ctx["log_stream"]
    worker_id = ctx["worker_id"]
    redis = ctx["redis"]
    session_factory = ctx["db_session_factory"]

    # We create a new executor instance per task to avoid concurrent DB session issues
    executor = RunExecutor(
        backend=ctx["docker_backend"],
        log_stream=ctx["log_stream"],
        run_repo=None,  # will be set below
        plugin_registry=ctx["plugin_registry"],
        s3_client=ctx.get("s3_client"),
        s3_bucket=ctx.get("s3_bucket", "qa-platform"),
        redis=redis,
    )

    async with session_factory() as session:
        run_repo = RunRepository(session)
        artifact_repo = ArtifactRepository(session)
        executor.run_repo = run_repo
        executor.artifact_repo = artifact_repo

        # 1. Claim the run
        run = await run_repo.claim_for_worker(run_id, worker_id=worker_id)
        if not run:
            log.warning("could not claim run %s (not in queued state or not found)", run_id)
            return

        # Release the PREPARING row lock immediately so cancel API / status reads aren't blocked.
        await session.commit()

        await publish_status_event(redis, run_id, "preparing", previous="queued")

        await session.refresh(run, ['pipeline', 'environment'])

        # Check if cancellation was requested before we started
        if run.cancel_requested_at:
            if await run_repo.cancel_if_current(run.id):
                log.info("run %s cancelled before execution started", run_id)
                await publish_status_event(redis, run_id, "cancelled", previous="preparing")
            await session.commit()
            return

        # Check if project is archived — skip execution
        proj_result = await session.execute(
            _select(Project).where(
                Project.id == run.project_id,
                Project.deleted_at.is_(None),
            )
        )
        project = proj_result.scalar_one_or_none()
        if project is None or project.status == "archived":
            if await run_repo.cancel_if_current(run.id):
                log.info("run %s skipped: project archived or deleted", run_id)
                await publish_status_event(redis, run_id, "cancelled", previous="preparing")
            await session.commit()
            return

        # Start heartbeat
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(worker_id, redis)
        )

        status = None
        try:
            # 2. Execute the pipeline
            crypto = getattr(ctx.get("container"), "crypto_service", None)
            config = _build_pipeline_config(run, run.pipeline, run.environment, crypto)
            status = await executor.execute(run, config)
            # Terminal state (finish_if_current / fail_if_current) is written
            # inside executor.execute() with summary; no redundant write here.

            # Retry is handled in the except branch below — when the executor
            # returns FAILED the real infra exception is already swallowed
            # inside executor.execute() and cannot be recovered here.

        except Exception as exc:
            log.exception("execute_run failed for run %s", run_id)
            from qaplatform.worker._redact import redact_url_userinfo
            updated = await run_repo.fail_if_current(
                run.id,
                message=redact_url_userinfo(str(exc)),
            )
            if updated:
                log.info("run %s marked as failed: %s", run_id, exc)

            # Release the failed-row update before the retry scheduler opens a
            # fresh session to inspect the original run and create the child
            # retry. Without this commit, PostgreSQL can make the retry path
            # wait on the worker's own uncommitted row lock.
            await session.commit()

            # Auto-retry on infrastructure exception
            await _attempt_retry(run_id, exc, ctx, session_factory)

        finally:
            # Cancel heartbeat
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

            # Send notifications for terminal run (best-effort)
            try:
                from qaplatform.worker.notifications import evaluate_and_notify
                terminal_status = status if status in (
                    RunStatus.DONE, RunStatus.FAILED, RunStatus.TIMEOUT
                ) else None
                if terminal_status:
                    await evaluate_and_notify(
                        run_id=run.id,
                        project_id=run.project_id,
                        status=terminal_status.value,
                        summary=getattr(run, "summary", None),
                        session_factory=session_factory,
                    )
            except Exception:
                log.warning("notification_evaluation_failed", exc_info=True)

            # Best-effort log archival
            try:
                if ctx.get("s3_client"):
                    await log_stream.archive_logs(
                        run_id, ctx["s3_client"], ctx.get("s3_bucket", "qa-platform")
                    )
            except Exception:
                log.warning("failed to archive logs for run %s", run_id)

            # Release worker association
            try:
                await run_repo.release_worker(run_id, worker_id=worker_id)
            except Exception:
                log.warning("failed to release worker for run %s", run_id)

            await session.commit()

def _build_pipeline_config(run, pipeline_orm, environment_orm, crypto=None):
    from qaplatform.engine.executor import PipelineConfig, StageDefinition
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.domain.services.env_vars_crypto import (
        decrypt_env_vars,
        is_encrypted_env_vars,
    )
    
    stages = []
    for stage_dict in pipeline_orm.stages:
        stages.append(StageDefinition(
            name=stage_dict.get('name', 'stage'),
            plugin=stage_dict.get('plugin', 'pytest'),
            phase=stage_dict.get('phase', 'execute'),
            config=stage_dict.get('config', {}),
            continue_on_error=stage_dict.get('continue_on_error', False),
        ))
    
    raw_env_vars = environment_orm.env_vars or {}
    if is_encrypted_env_vars(raw_env_vars):
        if crypto is None:
            raise RuntimeError("Crypto service not initialised")
        env_vars = decrypt_env_vars(
            raw_env_vars,
            environment_id=environment_orm.id,
            crypto=crypto,
        )
    else:
        env_vars = dict(raw_env_vars)

    raw_resource_limits = environment_orm.resource_limits or {}
    max_artifact_size_mb = raw_resource_limits.get("max_artifact_size_mb", 100)
    max_artifacts_count = raw_resource_limits.get("max_artifacts_count", 50)

    return PipelineConfig(
        image=environment_orm.base_image,
        stages=stages,
        env_vars=env_vars,
        resource_limits=ResourceLimits(
            memory_bytes=environment_orm.memory_mb * 1024 * 1024,
            cpu_cores=environment_orm.cpu_cores,
            max_artifact_size_bytes=max_artifact_size_mb * 1024 * 1024,
            max_artifacts_count=max_artifacts_count,
        ),
        network_policy=environment_orm.network_policy,
        timeout_seconds=pipeline_orm.timeout_seconds or 1800,
        setup_script=environment_orm.setup_script,
    )
