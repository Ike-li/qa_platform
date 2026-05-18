from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.schemas import (
    ErrorResponse,
    PaginatedResponse,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
)
from qaplatform.domain.services.scheduling import compute_next_run_at

router = APIRouter(
    prefix="/projects/{project_id}/schedules",
    tags=["schedules"],
)


def _to_response(orm) -> ScheduleResponse:
    return ScheduleResponse(
        id=orm.id,
        project_id=orm.project_id,
        pipeline_id=orm.pipeline_id,
        cron_expr=orm.cron_expr,
        timezone=orm.timezone,
        missed_fire_policy=orm.missed_fire_policy,
        quiet_windows=orm.quiet_windows or [],
        enabled=orm.enabled,
        last_run_at=orm.last_run_at,
        next_run_at=orm.next_run_at,
        last_error=orm.last_error,
        created_at=orm.created_at,
    )


@router.get(
    "",
    response_model=PaginatedResponse[ScheduleResponse],
    summary="定时任务列表",
)
async def list_schedules(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.SCHEDULE_READ)

    items, total = await repos.schedule.list_by_project(
        project.id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[_to_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}},
    summary="创建定时任务",
)
async def create_schedule(
    project_id: UUID,
    body: ScheduleCreate,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.SCHEDULE_EDIT)

    pipeline = await repos.pipeline.get_by_id(body.pipeline_id)
    if pipeline is None or pipeline.project_id != project.id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    next_run_at = compute_next_run_at(body.cron_expr, body.timezone)

    schedule = await repos.schedule.create(
        project_id=project.id,
        pipeline_id=body.pipeline_id,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        missed_fire_policy=body.missed_fire_policy,
        quiet_windows=body.quiet_windows,
        enabled=body.enabled,
        next_run_at=next_run_at,
    )

    response = _to_response(schedule)
    await write_audit(
        repos, user,
        action="schedule.create",
        resource_type="schedule",
        resource_id=schedule.id,
        after=response,
    )
    return response


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    responses={404: {"model": ErrorResponse}},
    summary="定时任务详情",
)
async def get_schedule(
    project_id: UUID,
    schedule_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.SCHEDULE_READ)

    schedule = await repos.schedule.get_by_id(schedule_id)
    if schedule is None or schedule.project_id != project.id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _to_response(schedule)


@router.put(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    responses={404: {"model": ErrorResponse}},
    summary="更新定时任务",
)
async def update_schedule(
    project_id: UUID,
    schedule_id: UUID,
    body: ScheduleUpdate,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.SCHEDULE_EDIT)

    schedule = await repos.schedule.get_by_id(schedule_id)
    if schedule is None or schedule.project_id != project.id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    before = _to_response(schedule)

    if body.cron_expr is not None:
        schedule.cron_expr = body.cron_expr
    if body.timezone is not None:
        schedule.timezone = body.timezone
    if body.missed_fire_policy is not None:
        schedule.missed_fire_policy = body.missed_fire_policy
    if body.quiet_windows is not None:
        schedule.quiet_windows = body.quiet_windows
    if body.enabled is not None:
        schedule.enabled = body.enabled

    # Recompute next_run_at if cron or timezone changed
    if body.cron_expr is not None or body.timezone is not None:
        schedule.next_run_at = compute_next_run_at(
            schedule.cron_expr, schedule.timezone,
        )

    response = _to_response(schedule)
    await write_audit(
        repos, user,
        action="schedule.update",
        resource_type="schedule",
        resource_id=schedule.id,
        before=before,
        after=response,
    )
    return response


@router.delete(
    "/{schedule_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
    summary="删除定时任务",
)
async def delete_schedule(
    project_id: UUID,
    schedule_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.SCHEDULE_EDIT)

    schedule = await repos.schedule.get_by_id(schedule_id)
    if schedule is None or schedule.project_id != project.id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    await repos.schedule.delete(schedule)
    await write_audit(
        repos, user,
        action="schedule.delete",
        resource_type="schedule",
        resource_id=schedule_id,
    )
