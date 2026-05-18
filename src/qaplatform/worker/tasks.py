from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from qaplatform.domain.models.run import RunStatus, TERMINAL_STATUSES

log = logging.getLogger(__name__)


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


async def execute_run(ctx: dict, run_id: str) -> None:
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
        from qaplatform.infra.database.models import Project
        from sqlalchemy import select as _select

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

        try:
            # 2. Execute the pipeline
            config = _build_pipeline_config(run, run.pipeline, run.environment)
            status = await executor.execute(run, config)

            # 3. Write terminal state (conditional update)
            updated = await run_repo.finish_if_current(
                run.id,
                status=status,
            )
            if updated:
                log.info("run %s completed with status: %s", run_id, status.value)

        except Exception as exc:
            log.exception("execute_run failed for run %s", run_id)
            from qaplatform.worker._redact import redact_url_userinfo
            updated = await run_repo.fail_if_current(
                run.id,
                message=redact_url_userinfo(str(exc)),
            )
            if updated:
                log.info("run %s marked as failed: %s", run_id, exc)

        finally:
            # Cancel heartbeat
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

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

def _build_pipeline_config(run, pipeline_orm, environment_orm):
    from qaplatform.engine.executor import PipelineConfig, StageDefinition
    from qaplatform.engine.docker_backend import ResourceLimits
    
    stages = []
    for stage_dict in pipeline_orm.stages:
        stages.append(StageDefinition(
            name=stage_dict.get('name', 'stage'),
            plugin=stage_dict.get('plugin', 'pytest'),
            phase=stage_dict.get('phase', 'execute'),
            config=stage_dict.get('config', {}),
            continue_on_error=stage_dict.get('continue_on_error', False),
        ))
    
    return PipelineConfig(
        image=environment_orm.base_image,
        stages=stages,
        env_vars=dict(environment_orm.env_vars or {}),
        resource_limits=ResourceLimits(
            memory_bytes=environment_orm.memory_mb * 1024 * 1024,
            cpu_cores=environment_orm.cpu_cores,
        ),
        network_policy=environment_orm.network_policy,
        timeout_seconds=pipeline_orm.timeout_seconds or 1800,
        setup_script=environment_orm.setup_script,
    )
