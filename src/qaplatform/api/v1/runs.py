from __future__ import annotations

from datetime import datetime
from typing import get_args
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.run_access import get_run_for_action
from qaplatform.api.run_batch_commands import (
    batch_cancel_run_command,
    batch_retry_run_command,
)
from qaplatform.api.run_commands import (
    build_project_run_metadata,
    resolve_project_run_environment_id,
)
from qaplatform.api.run_presenters import (
    is_allure_report_index,
    to_artifact_response,
    to_notification_log_response,
    to_result_response,
    to_run_response,
)
from qaplatform.api.run_retry_failed_command import (
    RetryFailedError,
    retry_failed_run_command,
)
from qaplatform.api.run_triage import (
    TRIAGE_FLAKY_MIN_RUNS,
    TRIAGE_FLAKY_SCAN_LIMIT,
    TRIAGE_HISTORY_LENGTH,
    build_run_triage,
    triage_history_cutoff,
)
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
    RunStatusValue,
    RunTriageResponse,
    RunTrigger,
    TestResultResponse,
    TestResultStatusValue,
)
from qaplatform.domain.services.execution import (
    CANCELABLE_STATUSES,
    is_cancelable_status,
)
from qaplatform.infra.database.models import RunStatusEnum
from qaplatform.infra.log_stream import ArchivedLogsNotFound, LogStream

router = APIRouter(prefix="/runs", tags=["runs"])

_CANCELABLE = frozenset(RunStatusEnum(status.value) for status in CANCELABLE_STATUSES)
_RUN_STATUS_VALUES = set(get_args(RunStatusValue))
_RUN_SORT_VALUES = {"created_at", "-created_at"}
_RUN_GIT_REF_MAX_LENGTH = 200


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
    session: AsyncSession = Depends(_get_db_session, scope="function"),
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

    environment_id = await resolve_project_run_environment_id(
        repos=repos,
        project=project,
        requested_environment_id=body.environment_id,
    )
    metadata = build_project_run_metadata(project)

    run = await repos.run.create(
        tenant_id=user.tenant_id,
        project_id=project.id,
        pipeline_id=pipeline.id,
        environment_id=environment_id,
        git_ref=git_ref,
        git_sha=body.git_sha,
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
        await repos.run.commit()
        from qaplatform.infra.queue.scheduler import enqueue_run

        await enqueue_run(arq_pool, repos.run, run, "manual", container.settings)

    response = to_run_response(run)
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
    responses={422: {"model": ErrorResponse}},
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
    pipeline_id: UUID | None = Query(None, description="按管道筛选"),
    git_ref: str | None = Query(None, description="按分支或 Git ref 筛选"),
    created_from: datetime | None = Query(None, description="按创建时间下限筛选"),
    created_to: datetime | None = Query(None, description="按创建时间上限筛选"),
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    if sort not in _RUN_SORT_VALUES:
        raise HTTPException(status_code=422, detail=f"Invalid run sort: {sort}")

    if git_ref is not None:
        if git_ref.strip() == "":
            raise HTTPException(status_code=422, detail="Invalid run git_ref: empty")
        if len(git_ref) > _RUN_GIT_REF_MAX_LENGTH:
            raise HTTPException(status_code=422, detail="Invalid run git_ref: too long")
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(
            status_code=422,
            detail="Invalid run created range: created_from must be before created_to",
        )

    statuses: list[str] | None = None
    if status is not None:
        # F-LS-01: support comma-separated multi-status filtering
        # (e.g. 'queued,running' to show in-flight runs).
        statuses = [s.strip() for s in status.split(",")]
        if any(s == "" for s in statuses):
            raise HTTPException(status_code=422, detail="Invalid run status: empty")
        invalid_statuses = sorted(set(statuses) - _RUN_STATUS_VALUES)
        if invalid_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid run status: {', '.join(invalid_statuses)}",
            )

    if project_id is not None:
        # Single-project listing: enforce project-level read.
        await enforce_project_action(session, user, project_id, Action.RUN_READ)
        project_ids: list[UUID] | None = [project_id]
    else:
        # Cross-project listing: tenant Owner/Admin (and platform admin) see
        # all runs in the tenant; everyone else is restricted to projects
        # they're a member of.
        from qaplatform.api.auth.permissions import Role, normalize_tenant_role

        tenant_role = normalize_tenant_role(user.role)
        if not getattr(user, "is_platform_admin", False) and tenant_role not in (Role.OWNER, Role.ADMIN):
            member_projects = await repos.project_member.list_project_ids_by_user(
                user.user_id,
                user.tenant_id,
            )
            if not member_projects:
                return PaginatedResponse(data=[], page=page, per_page=per_page, total=0)
            project_ids = list(member_projects)
        else:
            project_ids = None

    items, total = await repos.run.list_filtered_for_tenant(
        tenant_id=user.tenant_id,
        offset=(page - 1) * per_page,
        limit=per_page,
        statuses=statuses,
        project_ids=project_ids,
        pipeline_id=pipeline_id,
        git_ref=git_ref,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
    )
    return PaginatedResponse(
        data=[to_run_response(i) for i in items],
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
    _session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    container = request.app.state.container
    return await batch_cancel_run_command(
        run_ids=body.run_ids,
        repos=repos,
        user=user,
        redis=getattr(container, "redis_client", None),
    )


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
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    container = request.app.state.container
    return await batch_retry_run_command(
        run_ids=body.run_ids,
        repos=repos,
        user=user,
        session=session,
        arq_pool=getattr(container, "arq_pool", None),
        settings=container.settings,
    )


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
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    run = await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
        enforce_action=enforce_project_action,
    )
    return to_run_response(run)


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
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    run = await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_CANCEL,
        allow_own_resource=True,
        enforce_action=enforce_project_action,
    )

    if not is_cancelable_status(run.status):
        terminal_status = (
            run.status.value if isinstance(run.status, RunStatusEnum) else str(run.status)
        )
        raise HTTPException(
            status_code=409,
            detail=f"Run already in terminal status: {terminal_status}",
        )

    previous_status = run.status.value if isinstance(run.status, RunStatusEnum) else str(run.status)
    before_response = to_run_response(run)
    cancelled = await repos.run.cancel_if_current(run_id, expected_in=_CANCELABLE)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Run status changed concurrently")

    # Notify worker to stop the container
    container = request.app.state.container
    redis = getattr(container, "redis_client", None)
    if redis is not None:
        from qaplatform.engine.cancel import publish_cancel
        from qaplatform.engine.events import publish_status_event

        await publish_cancel(redis, run_id)
        await publish_status_event(redis, run_id, "cancelled", previous=previous_status)

    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    after_response = to_run_response(run)
    after_state = after_response.model_dump(mode="json")
    if body is not None and body.reason:
        after_state["cancel_reason"] = body.reason
    await write_audit(
        repos, user,
        action="run.cancel",
        resource_type="run",
        resource_id=run_id,
        before=before_response,
        after=after_state,
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
    status: TestResultStatusValue | None = Query(None, description="passed / failed / error / skipped / xfail"),
    suite: str | None = Query(
        None,
        min_length=1,
        max_length=500,
        description="精确匹配 suite 名称",
    ),
    q: str | None = Query(
        None,
        min_length=1,
        max_length=500,
        description="按用例名称/错误信息搜索",
    ),
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
        enforce_action=enforce_project_action,
    )

    items, total = await repos.test_result.list_filtered_by_run(
        run_id=run_id,
        offset=(page - 1) * per_page,
        limit=per_page,
        status=status,
        suite=suite,
        query=q,
    )
    return PaginatedResponse(
        data=[to_result_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.get(
    "/{run_id}/triage",
    response_model=RunTriageResponse,
    responses={404: {"model": ErrorResponse}},
    summary="失败分诊",
    description=(
        "把 run 内每个 failed/error 用例归入 新增失败 / 已知 flaky / 持续失败"
        "三类（优先级 known_flaky > persistent > new），同错误签名折叠为一组，"
        "每项附最近 10 次观测履历与置信度（观测 <10 次为 observing）。"
    ),
)
async def get_run_triage(
    run_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    run = await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
        enforce_action=enforce_project_action,
    )

    failed_results = await repos.test_result.list_failed_by_run(run_id)
    if not failed_results:
        return RunTriageResponse(run_id=run_id, total_failed=0)

    cutoff = triage_history_cutoff(run)
    flaky_rows, _ = await repos.test_result.list_flaky_tests(
        project_id=run.project_id,
        cutoff=cutoff,
        min_runs=TRIAGE_FLAKY_MIN_RUNS,
        offset=0,
        limit=TRIAGE_FLAKY_SCAN_LIMIT,
    )
    flaky_keys = {(row.suite, row.name) for row in flaky_rows}

    prior_history, prior_counts = (
        await repos.test_result.list_prior_observations_for_failed_cases(
            run_id=run_id,
            project_id=run.project_id,
            cutoff=cutoff,
            before_created_at=run.created_at,
            before_run_id=run.id,
            per_case_limit=TRIAGE_HISTORY_LENGTH - 1,
        )
    )

    quarantined = await repos.quarantine.list_keys(run.project_id)
    return build_run_triage(
        run=run,
        failed_results=failed_results,
        flaky_keys=flaky_keys,
        prior_history=prior_history,
        prior_counts=prior_counts,
        quarantined=quarantined,
    )


@router.post(
    "/{run_id}/retry-failed",
    response_model=RunResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="重跑失败用例",
    description=(
        "创建只重跑失败用例的新 Run。v1 仅支持 pytest runner。"
        "失败用例 > 200 个时拒绝（命令行长度风险）。"
        "要求原 Run 为终态且存在 failed/error 测试结果。"
    ),
)
async def retry_failed_run(
    run_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    # 权限检查：需要 RUN_TRIGGER（Developer+）
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_TRIGGER,
        enforce_action=enforce_project_action,
    )

    container = request.app.state.container
    try:
        result = await retry_failed_run_command(
            run_id=run_id,
            repos=repos,
            user=user,
            session=session,
            arq_pool=getattr(container, "arq_pool", None),
            settings=container.settings,
        )
        await write_audit(
            repos, user,
            action="run.retry_failed",
            resource_type="run",
            resource_id=result.id,
            after=result,
        )
        return result
    except RetryFailedError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get(
    "/{run_id}/artifacts/allure-report",
    response_model=ArtifactResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Allure 报告入口",
)
async def get_run_allure_report_artifact(
    run_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
        enforce_action=enforce_project_action,
    )

    offset = 0
    page_size = 100
    while True:
        items, total = await repos.artifact.list_by_run(
            run_id,
            offset=offset,
            limit=page_size,
        )
        for artifact in items:
            if is_allure_report_index(artifact):
                return to_artifact_response(artifact)
        offset += len(items)
        if offset >= total or not items:
            break

    raise HTTPException(status_code=404, detail="Allure report not found")


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
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
        enforce_action=enforce_project_action,
    )

    items, total = await repos.artifact.list_by_run(
        run_id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[to_artifact_response(i) for i in items],
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
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
        enforce_action=enforce_project_action,
    )

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
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.NOTIFICATION_READ,
        enforce_action=enforce_project_action,
    )

    items, total = await repos.notification_log.list_by_run(
        run_id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[to_notification_log_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )
