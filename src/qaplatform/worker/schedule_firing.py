"""Schedule firing workflow for the arq cron hook."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)


def _schedule_run_audit_state(
    run: Any, *, schedule_id: UUID, enqueued: bool
) -> dict:
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


async def fire_due_schedules(ctx: dict) -> None:
    """Fire due schedules by creating runs and enqueueing them."""
    from qaplatform.domain.services.schedule import (
        ScheduleSkippedSilentWindowAudit,
        is_in_silent_window,
        silent_windows_from_settings,
    )
    from qaplatform.domain.services.scheduling import (
        compute_next_run_at,
        should_fire,
    )
    from qaplatform.infra.audit import write_audit
    from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository
    from qaplatform.infra.database.repositories.project_repo import (
        EnvironmentRepository,
        PipelineRepository,
        ProjectRepository,
        ScheduleRepository,
    )
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.infra.queue.scheduler import enqueue_run

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
                continue

            try:
                pipeline = await pipeline_repo.get_by_id(schedule.pipeline_id)
                if pipeline is None:
                    next_run = compute_next_run_at(
                        schedule.cron_expr, schedule.timezone, now
                    )
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
                        next_run_at=compute_next_run_at(
                            schedule.cron_expr, schedule.timezone, now
                        ),
                        last_error="project not found",
                    )
                    await session.commit()
                    continue

                silent_window = is_in_silent_window(
                    silent_windows_from_settings(project.settings),
                    now,
                )
                if silent_window is not None:
                    audit_repos = SimpleNamespace(audit=audit_repo)
                    audit_user = SimpleNamespace(
                        tenant_id=project.tenant_id, user_id=None
                    )
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

                environment_id = project.default_env_id
                if environment_id is None:
                    envs, _ = await env_repo.list_by_project(
                        schedule.project_id, limit=1
                    )
                    environment_id = envs[0].id if envs else None

                git_ref = project.default_branch or "main"
                metadata = {
                    "schedule_id": str(schedule.id),
                    "git_url": project.git_url,
                }
                if project.git_auth_method != "none" and project.credential_id:
                    metadata["git_auth_method"] = project.git_auth_method
                    metadata["credential_id"] = str(project.credential_id)
                if project.shallow_clone:
                    metadata["shallow_clone"] = True
                if project.default_branch:
                    metadata["default_branch"] = project.default_branch

                run = await run_repo.create(
                    tenant_id=project.tenant_id,
                    project_id=schedule.project_id,
                    pipeline_id=schedule.pipeline_id,
                    environment_id=environment_id,
                    git_ref=git_ref,
                    trigger_type="schedule",
                    metadata_=metadata,
                )
                await run_repo.set_retry_group_id(run.id, run.id)
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
                next_run = compute_next_run_at(
                    schedule.cron_expr, schedule.timezone, now
                )
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
                log.exception(
                    "schedule_fire_failed", extra={"schedule_id": str(schedule.id)}
                )
                try:
                    next_run = compute_next_run_at(
                        schedule.cron_expr, schedule.timezone, now
                    )
                    await schedule_repo.update_after_fire(
                        schedule.id,
                        last_run_at=now,
                        next_run_at=next_run,
                        last_error="internal error",
                    )
                    await session.commit()
                except Exception:
                    log.exception(
                        "schedule_update_failed",
                        extra={"schedule_id": str(schedule.id)},
                    )
