"""Schedule firing workflow for the arq cron hook."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)

# 单次 tick 内所有 schedule 合计最多创建多少 Run。find_due_schedules 一次取 50 条，
# 每条最多补 10 个槽，最坏 500 个 Run 在一个滴答里涌出。预算耗尽时只停补跑并直接
# 丢弃剩余的槽——留到下个 tick 只是把惊群推迟一分钟再制造一次。
MAX_RUNS_PER_TICK = 50


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
        plan_missed_fires,
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

        created_this_tick = 0
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

                scheduled_at = schedule.next_run_at
                plan = plan_missed_fires(
                    cron_expr=schedule.cron_expr,
                    timezone_name=schedule.timezone,
                    scheduled_at=scheduled_at,
                    now=now,
                    policy=schedule.missed_fire_policy or "run_once",
                )

                # 先抢槽再建 Run：条件 UPDATE 只有在 next_run_at 仍是我们读到的
                # 那个值时才成功。抢输说明另一个 worker 已经处理了这一槽。
                # 顺序反过来（先建 Run 后推进）会在 enqueue 崩溃时重复触发；
                # 对回归调度器来说，丢一个周期是比重复一个周期更好的失败模式。
                claimed = await schedule_repo.update_after_fire(
                    schedule.id,
                    last_run_at=now,
                    next_run_at=plan.next_run_at,
                    last_error=None,
                    expected_next_run_at=scheduled_at,
                )
                await session.commit()
                if not claimed:
                    continue

                if not plan.fire_at:
                    audit_repos = SimpleNamespace(audit=audit_repo)
                    audit_user = SimpleNamespace(
                        tenant_id=project.tenant_id, user_id=None
                    )
                    await write_audit(
                        audit_repos,
                        audit_user,
                        action="schedule_skipped_missed_fire",
                        resource_type="schedule",
                        resource_id=schedule.id,
                        after={
                            "schedule_id": str(schedule.id),
                            "reason": plan.reason,
                            "missed_count": plan.missed_count,
                            "dropped_count": plan.dropped_count,
                            "scheduled_at": scheduled_at.isoformat(),
                            "next_run_at": plan.next_run_at.isoformat(),
                        },
                    )
                    await session.commit()
                    log.info(
                        "schedule_missed_fires_skipped",
                        extra={
                            "schedule_id": str(schedule.id),
                            "missed_count": plan.missed_count,
                            "policy": schedule.missed_fire_policy,
                        },
                    )
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

                for index, slot in enumerate(plan.fire_at):
                    if created_this_tick >= MAX_RUNS_PER_TICK:
                        log.warning(
                            "schedule_catchup_budget_exhausted",
                            extra={
                                "schedule_id": str(schedule.id),
                                "remaining": len(plan.fire_at) - index,
                            },
                        )
                        break

                    slot_metadata = dict(metadata)
                    slot_metadata["scheduled_for"] = slot.isoformat()
                    if plan.reason != "on_time":
                        # 让「为什么突然冒出三个 Run」在 Run 详情页能看懂。
                        # 宽限窗口内的正常抖动不算补跑，不打这个标。
                        slot_metadata["missed_fire"] = True

                    run = await run_repo.create(
                        tenant_id=project.tenant_id,
                        project_id=schedule.project_id,
                        pipeline_id=schedule.pipeline_id,
                        environment_id=environment_id,
                        git_ref=git_ref,
                        trigger_type="schedule",
                        metadata_=slot_metadata,
                    )
                    await run_repo.set_retry_group_id(run.id, run.id)
                    await session.commit()
                    created_this_tick += 1

                    enqueued = await enqueue_run(
                        arq, run_repo, run, "schedule", settings
                    )
                    audit_repos = SimpleNamespace(audit=audit_repo)
                    audit_user = SimpleNamespace(
                        tenant_id=project.tenant_id, user_id=None
                    )
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
                    if not enqueued:
                        await schedule_repo.update_after_fire(
                            schedule.id,
                            last_run_at=now,
                            next_run_at=plan.next_run_at,
                            last_error="enqueue failed",
                        )
                    await session.commit()

                    log.info(
                        "schedule_fired",
                        extra={
                            "schedule_id": str(schedule.id),
                            "run_id": str(run.id),
                            "enqueued": enqueued,
                            "scheduled_for": slot.isoformat(),
                            "missed_count": plan.missed_count,
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
