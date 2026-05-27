from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.v1._filters import escape_like
from qaplatform.api.schemas import (
    ArtifactResponse,
    BatchRunRequest,
    BatchRunResponse,
    ErrorResponse,
    NotificationLogResponse,
    PaginatedResponse,
    RunCancel,
    RunLogEntryResponse,
    RunResponse,
    RunTrigger,
    TestResultResponse,
)
from qaplatform.engine.log_stream import ArchivedLogsNotFound, LogStream
from qaplatform.infra.database.models import (
    Artifact as ArtifactORM,
    NotificationLog as NotificationLogORM,
    Run as RunORM,
    RunStatusEnum,
    TestResult as TestResultORM,
)

router = APIRouter(prefix="/runs", tags=["runs"])

_CANCELABLE = {RunStatusEnum.QUEUED, RunStatusEnum.PREPARING, RunStatusEnum.RUNNING, RunStatusEnum.COLLECTING}


def _to_run_response(orm: RunORM) -> RunResponse:
    return RunResponse(
        id=orm.id,
        tenant_id=orm.tenant_id,
        project_id=orm.project_id,
        pipeline_id=orm.pipeline_id,
        pipeline_name=orm.pipeline.name if orm.pipeline is not None else "",
        environment_id=orm.environment_id,
        status=orm.status.value if isinstance(orm.status, RunStatusEnum) else orm.status,
        trigger_type=orm.trigger_type,
        priority=orm.priority,
        triggered_by=orm.triggered_by,
        git_ref=orm.git_ref,
        git_sha=orm.git_sha,
        attempt=orm.attempt,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
        duration_ms=orm.duration_ms,
        summary=orm.summary,
        error_message=orm.error_message,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _to_result_response(orm: TestResultORM) -> TestResultResponse:
    return TestResultResponse(
        id=orm.id,
        run_id=orm.run_id,
        suite=orm.suite,
        name=orm.name,
        status=orm.status.value if hasattr(orm.status, "value") else orm.status,
        duration_ms=orm.duration_ms,
        error_message=orm.error_message,
        stack_trace=orm.stack_trace,
        tags=orm.tags or [],
        metadata=orm.metadata_ or {},
    )


def _to_artifact_response(orm: ArtifactORM) -> ArtifactResponse:
    return ArtifactResponse.model_validate(orm)


@router.post(
    "",
    response_model=RunResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="触发执行",
)
async def trigger_run(
    body: RunTrigger,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    pipeline = await repos.pipeline.get_by_id(body.pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Treat 'pipeline belongs to a different tenant' identically to
    # 'pipeline does not exist' — otherwise an attacker can enumerate
    # pipeline_ids across tenants by status-code differential.
    project = await repos.project.get_for_tenant(pipeline.project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if project.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Project is archived; new runs cannot be triggered",
        )

    await enforce_project_action(session, user, project.id, Action.RUN_TRIGGER)

    git_ref = body.git_ref or project.default_branch

    environment_id = project.default_env_id
    if environment_id is None:
        envs, _ = await repos.environment.list_by_project(project.id, limit=1)
        if envs:
            environment_id = envs[0].id
        else:
            raise HTTPException(status_code=409, detail="No environment configured for project")
            
    metadata = {'git_url': project.git_url}
    if project.git_auth_method != 'none' and project.credential_id:
        metadata['credential_id'] = str(project.credential_id)
    if project.shallow_clone:
        metadata['shallow_clone'] = True
    if project.default_branch:
        metadata['default_branch'] = project.default_branch

    run = await repos.run.create(
        tenant_id=user.tenant_id,
        project_id=project.id,
        pipeline_id=pipeline.id,
        environment_id=environment_id,
        git_ref=git_ref,
        triggered_by=user.user_id,
        trigger_type="manual",
        priority=body.priority,
        metadata_=metadata,
    )
    # Set retry_group_id to the run's own id so retries share the same group.
    await repos.run.set_retry_group_id(run.id, run.id)

    container = request.app.state.container
    arq_pool = getattr(container, "arq_pool", None)
    if arq_pool is not None:
        from qaplatform.worker.scheduler import enqueue_run

        await enqueue_run(arq_pool, repos.run, run, "manual", container.settings)

    response = _to_run_response(run)
    await write_audit(
        repos, user,
        action="run.trigger",
        resource_type="run",
        resource_id=run.id,
        after=response,
    )
    return response


@router.get(
    "",
    response_model=PaginatedResponse[RunResponse],
    summary="执行列表",
)
async def list_runs(
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(
        None,
        description="按状态筛选；支持多值，逗号分隔（如 'queued,running'）",
    ),
    sort: str = Query("-created_at", description="排序字段"),
    project_id: UUID | None = Query(None, description="按项目筛选"),
    session: AsyncSession = Depends(_get_db_session),
):
    filters = [RunORM.tenant_id == user.tenant_id]
    if status:
        # F-LS-01: support comma-separated multi-status filtering
        # (e.g. 'queued,running' to show in-flight runs).
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            filters.append(RunORM.status == statuses[0])
        elif statuses:
            filters.append(RunORM.status.in_(statuses))

    if project_id is not None:
        # Single-project listing: enforce project-level read.
        await enforce_project_action(session, user, project_id, Action.RUN_READ)
        filters.append(RunORM.project_id == project_id)
    else:
        # Cross-project listing: tenant Owner/Admin (and platform admin) see
        # all runs in the tenant; everyone else is restricted to projects
        # they're a member of.
        from qaplatform.api.auth.permissions import Role, normalize_tenant_role
        from qaplatform.infra.database.models import ProjectMember

        tenant_role = normalize_tenant_role(user.role)
        if not getattr(user, "is_platform_admin", False) and tenant_role not in (Role.OWNER, Role.ADMIN):
            member_projects = (
                await session.execute(
                    select(ProjectMember.project_id).where(
                        ProjectMember.user_id == user.user_id,
                        ProjectMember.tenant_id == user.tenant_id,
                        ProjectMember.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            if not member_projects:
                return PaginatedResponse(data=[], page=page, per_page=per_page, total=0)
            filters.append(RunORM.project_id.in_(member_projects))

    order_by = desc(RunORM.created_at) if sort == "-created_at" else RunORM.created_at

    items, total = await repos.run.list(
        offset=(page - 1) * per_page,
        limit=per_page,
        order_by=order_by,
        filters=filters,
    )
    return PaginatedResponse(
        data=[_to_run_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "/batch/cancel",
    response_model=BatchRunResponse,
    summary="批量取消执行",
)
async def batch_cancel_runs(
    body: BatchRunRequest,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    processed = 0
    failed = 0
    errors: list[str] = []

    container = request.app.state.container
    redis = getattr(container, "redis_client", None)

    for run_id in body.run_ids:
        try:
            run = await repos.run.get_for_tenant(run_id, user.tenant_id)
            if run is None:
                errors.append(f"{run_id}: not found")
                failed += 1
                continue

            if run.status not in _CANCELABLE:
                errors.append(f"{run_id}: already terminal ({run.status})")
                failed += 1
                continue

            before_response = _to_run_response(run)
            cancelled = await repos.run.cancel_if_current(run_id, expected_in=_CANCELABLE)
            if not cancelled:
                errors.append(f"{run_id}: status changed concurrently")
                failed += 1
                continue

            if redis is not None:
                from qaplatform.engine.cancel import publish_cancel
                from qaplatform.engine.events import publish_status_event

                await publish_cancel(redis, run_id)
                previous = run.status.value if isinstance(run.status, RunStatusEnum) else str(run.status)
                await publish_status_event(redis, run_id, "cancelled", previous=previous)

            run_after = await repos.run.get_for_tenant(run_id, user.tenant_id)
            after_response = _to_run_response(run_after) if run_after is not None else {"status": "cancelled"}
            await write_audit(
                repos, user,
                action="run.batch_cancel",
                resource_type="run",
                resource_id=run_id,
                before=before_response,
                after=after_response,
            )
            processed += 1
        except (SQLAlchemyError, ValueError) as exc:
            errors.append(f"{run_id}: {exc}")
            failed += 1

    return BatchRunResponse(processed=processed, failed=failed, errors=errors)


@router.post(
    "/batch/retry",
    response_model=BatchRunResponse,
    summary="批量重试执行",
)
async def batch_retry_runs(
    body: BatchRunRequest,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    processed = 0
    failed = 0
    errors: list[str] = []

    container = request.app.state.container
    arq_pool = getattr(container, "arq_pool", None)

    for run_id in body.run_ids:
        try:
            original = await repos.run.get_for_tenant(run_id, user.tenant_id)
            if original is None:
                errors.append(f"{run_id}: not found")
                failed += 1
                continue

            terminal = {RunStatusEnum.DONE, RunStatusEnum.FAILED, RunStatusEnum.TIMEOUT, RunStatusEnum.CANCELLED}
            if original.status not in terminal:
                errors.append(f"{run_id}: not terminal ({original.status})")
                failed += 1
                continue

            before_response = _to_run_response(original)
            await session.refresh(original, ['pipeline', 'environment'])

            new_run = await repos.run.create(
                tenant_id=original.tenant_id,
                project_id=original.project_id,
                pipeline_id=original.pipeline_id,
                environment_id=original.environment_id,
                git_ref=original.git_ref,
                git_sha=original.git_sha,
                priority=original.priority,
                triggered_by=user.user_id,
                trigger_type="manual",
                metadata_=dict(original.metadata_ or {}),
                source_run_id=original.id,
                chain_depth=(original.chain_depth or 0) + 1,
            )
            await repos.run.set_retry_group_id(new_run.id, new_run.id)

            if arq_pool is not None:
                from qaplatform.worker.scheduler import enqueue_run

                await enqueue_run(arq_pool, repos.run, new_run, "manual", container.settings)

            await write_audit(
                repos, user,
                action="run.batch_retry",
                resource_type="run",
                resource_id=original.id,
                before=before_response,
                after={
                    "retry_run_id": str(new_run.id),
                    "source_run_id": str(original.id),
                    "status": "queued",
                    "attempt": getattr(new_run, "attempt", None),
                },
            )
            processed += 1
        except (SQLAlchemyError, ValueError) as exc:
            errors.append(f"{run_id}: {exc}")
            failed += 1

    return BatchRunResponse(processed=processed, failed=failed, errors=errors)


@router.get(
    "/{run_id}",
    response_model=RunResponse,
    responses={404: {"model": ErrorResponse}},
    summary="执行详情",
)
async def get_run(
    run_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await enforce_project_action(session, user, run.project_id, Action.RUN_READ)
    return _to_run_response(run)


@router.post(
    "/{run_id}/cancel",
    response_model=RunResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="取消执行",
)
async def cancel_run(
    run_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    body: RunCancel | None = None,
    session: AsyncSession = Depends(_get_db_session),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    is_own = str(run.triggered_by) == str(user.user_id)
    await enforce_project_action(
        session, user, run.project_id, Action.RUN_CANCEL, is_own_resource=is_own,
    )

    if run.status not in _CANCELABLE:
        raise HTTPException(status_code=409, detail=f"Run already in terminal status: {run.status}")

    cancelled = await repos.run.cancel_if_current(run_id, expected_in=_CANCELABLE)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Run status changed concurrently")

    previous_status = run.status.value if isinstance(run.status, RunStatusEnum) else str(run.status)
    before_response = _to_run_response(run)

    # Notify worker to stop the container
    container = request.app.state.container
    redis = getattr(container, "redis_client", None)
    if redis is not None:
        from qaplatform.engine.cancel import publish_cancel
        from qaplatform.engine.events import publish_status_event

        await publish_cancel(redis, run_id)
        await publish_status_event(redis, run_id, "cancelled", previous=previous_status)

    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    after_response = _to_run_response(run)
    await write_audit(
        repos, user,
        action="run.cancel",
        resource_type="run",
        resource_id=run_id,
        before=before_response,
        after=after_response,
    )
    return after_response


@router.get(
    "/{run_id}/results",
    response_model=PaginatedResponse[TestResultResponse],
    responses={404: {"model": ErrorResponse}},
    summary="测试结果",
)
async def get_run_results(
    run_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="passed / failed / error / skipped / xfail"),
    suite: str | None = Query(None, description="精确匹配 suite 名称"),
    q: str | None = Query(None, description="按用例名称/错误信息搜索"),
    session: AsyncSession = Depends(_get_db_session),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await enforce_project_action(session, user, run.project_id, Action.RUN_READ)

    filters = [TestResultORM.run_id == run_id]
    if status:
        filters.append(TestResultORM.status == status)
    if suite:
        filters.append(TestResultORM.suite == suite)
    if q:
        pattern = f"%{escape_like(q)}%"
        filters.append(
            or_(
                TestResultORM.name.ilike(pattern, escape="\\"),
                TestResultORM.error_message.ilike(pattern, escape="\\"),
            )
        )

    items, total = await repos.test_result.list(
        offset=(page - 1) * per_page,
        limit=per_page,
        filters=filters,
    )
    return PaginatedResponse(
        data=[_to_result_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.get(
    "/{run_id}/artifacts",
    response_model=PaginatedResponse[ArtifactResponse],
    responses={404: {"model": ErrorResponse}},
    summary="产物列表",
)
async def get_run_artifacts(
    run_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(_get_db_session),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await enforce_project_action(session, user, run.project_id, Action.RUN_READ)

    items, total = await repos.artifact.list_by_run(
        run_id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[_to_artifact_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.get(
    "/{run_id}/logs/archive",
    response_model=PaginatedResponse[RunLogEntryResponse],
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="归档日志回看",
)
async def get_archived_run_logs(
    run_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(_get_db_session),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await enforce_project_action(session, user, run.project_id, Action.RUN_READ)

    container = request.app.state.container
    if container.s3_client is None:
        raise HTTPException(
            status_code=503,
            detail="Archived logs are not available",
        )

    log_stream = LogStream(container.redis_client)
    try:
        entries = await log_stream.read_archived_logs(
            run_id,
            container.s3_client,
            container.settings.s3_bucket,
        )
    except ArchivedLogsNotFound:
        raise HTTPException(status_code=404, detail="Archived logs not found") from None

    offset = (page - 1) * per_page
    window = entries[offset : offset + per_page]
    return PaginatedResponse(
        data=[RunLogEntryResponse.model_validate(entry) for entry in window],
        page=page,
        per_page=per_page,
        total=len(entries),
    )


def _to_notification_log_response(orm: NotificationLogORM) -> NotificationLogResponse:
    return NotificationLogResponse(
        id=orm.id,
        project_id=orm.project_id,
        run_id=orm.run_id,
        rule_id=orm.rule_id,
        channel_type=orm.channel_type,
        status=orm.status.value if hasattr(orm.status, "value") else orm.status,
        error_message=orm.error_message,
        sent_at=orm.sent_at,
    )


@router.get(
    "/{run_id}/notifications",
    response_model=PaginatedResponse[NotificationLogResponse],
    responses={404: {"model": ErrorResponse}},
    summary="通知日志",
)
async def get_run_notifications(
    run_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(_get_db_session),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await enforce_project_action(session, user, run.project_id, Action.NOTIFICATION_READ)

    items, total = await repos.notification_log.list_by_run(
        run_id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[_to_notification_log_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )
