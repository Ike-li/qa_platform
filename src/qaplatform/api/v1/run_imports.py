"""外部测试结果导入 API（入口 B）。

外部 CI 用一次 HTTP 调用上传原始 JUnit XML，生成一条终态 Run +
TestResult 行，直接进入现有 Analytics / 通知管线（不入队、不经 executor）。

请求体为原始 XML（``curl --data-binary`` 即可），元数据走 query 参数；
刻意不用 multipart/form-data——那需要 python-multipart 依赖。
导入不去重：重复上传同一文件生成两条独立 Run，幂等性由调用方负责。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.run_presenters import to_run_response
from qaplatform.api.schemas import ErrorResponse, RunResponse
from qaplatform.engine.executor_results import (
    build_results_summary,
    build_test_result_rows,
)
from qaplatform.infra.database.models import Environment, Pipeline, RunStatusEnum
from qaplatform.plugins.builtin.junit_collector import (
    JUnitParseError,
    parse_junit_xml_content,
)
from qaplatform.plugins.protocols import TestResultData

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["runs"])

MAX_IMPORT_XML_BYTES = 10 * 1024 * 1024

DEFAULT_IMPORT_PIPELINE_NAME = "external-import"
DEFAULT_IMPORT_ENVIRONMENT_NAME = "external"

# Environment.base_image 是无默认值的 NOT NULL 列；导入占位环境从不执行。
_IMPORT_PLACEHOLDER_BASE_IMAGE = "import/none"

# Pipeline.stages 是无默认值的 NOT NULL JSONB；给一个能通过
# engine/pipeline_config_builder 解析的最小 stage。配合 enabled=False，
# 该占位 pipeline 不会被调度或手动触发执行。
_IMPORT_PLACEHOLDER_STAGES = [
    {
        "name": "external-import",
        "plugin": "pytest",
        "phase": "execute",
        "config": {},
    }
]


def merge_duplicate_results(results: list[TestResultData]) -> list[TestResultData]:
    """同一 ``(suite, name)`` 重复出现时保留最后一条。

    满足 ``uq_test_result_run_suite_name`` 唯一约束；dict 保插入序，
    后出现的结果覆盖先出现的同名结果。
    """
    merged: dict[tuple[str, str], TestResultData] = {}
    for result in results:
        merged[(result.suite, result.name)] = result
    return list(merged.values())


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def resolve_import_timestamps(
    started_at: datetime | None,
    finished_at: datetime | None,
    total_duration_ms: int,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime, int]:
    """推导导入 Run 的起止时间与时长。

    缺省时用服务器当前时间与 XML 各用例 time 总和推导；只给一端时
    用总时长补出另一端。
    """
    if started_at is not None:
        started_at = _ensure_utc(started_at)
    if finished_at is not None:
        finished_at = _ensure_utc(finished_at)

    if started_at is not None and finished_at is not None:
        if finished_at < started_at:
            raise HTTPException(
                status_code=422,
                detail="finished_at must not be earlier than started_at",
            )
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        return started_at, finished_at, duration_ms

    span = timedelta(milliseconds=total_duration_ms)
    if started_at is not None:
        return started_at, started_at + span, total_duration_ms
    if finished_at is not None:
        return finished_at - span, finished_at, total_duration_ms

    resolved_finish = now or datetime.now(timezone.utc)
    return resolved_finish - span, resolved_finish, total_duration_ms


async def _get_or_create_import_pipeline(
    repos: Repos,
    session: AsyncSession,
    project_id: UUID,
    name: str,
) -> Pipeline:
    """按名字 get-or-create 导入占位 Pipeline（幂等、并发安全）。

    先查后建；并发竞争撞 ``uq_pipeline_project_name`` 时回滚 SAVEPOINT
    再查一次。重查仍不可见说明名字被软删除的 pipeline 占用 → 409。
    """
    existing = await repos.pipeline.get_by_name(project_id, name)
    if existing is not None:
        return existing
    try:
        async with session.begin_nested():
            return await repos.pipeline.create(
                project_id=project_id,
                name=name,
                stages=_IMPORT_PLACEHOLDER_STAGES,
                enabled=False,
            )
    except IntegrityError:
        existing = await repos.pipeline.get_by_name(project_id, name)
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail=f"Pipeline name '{name}' is occupied by a deleted pipeline",
            ) from None
        return existing


async def _get_or_create_import_environment(
    repos: Repos,
    session: AsyncSession,
    project_id: UUID,
    name: str,
) -> Environment:
    """按名字 get-or-create 导入占位 Environment（幂等、并发安全）。"""
    existing = await repos.environment.get_by_name(project_id, name)
    if existing is not None:
        return existing
    try:
        async with session.begin_nested():
            return await repos.environment.create(
                project_id=project_id,
                name=name,
                base_image=_IMPORT_PLACEHOLDER_BASE_IMAGE,
            )
    except IntegrityError:
        existing = await repos.environment.get_by_name(project_id, name)
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail=f"Environment name '{name}' is occupied by a deleted environment",
            ) from None
        return existing


async def _read_xml_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            declared = None
        if declared is not None and declared > MAX_IMPORT_XML_BYTES:
            raise HTTPException(
                status_code=413,
                detail="JUnit XML payload exceeds the 10MB limit",
            )
    body = await request.body()
    if len(body) > MAX_IMPORT_XML_BYTES:
        raise HTTPException(
            status_code=413,
            detail="JUnit XML payload exceeds the 10MB limit",
        )
    if not body.strip():
        raise HTTPException(status_code=422, detail="Request body is empty")
    # JUnit XML 从不带 DOCTYPE；拒绝 DTD 防实体展开攻击（标准库 ET 不防）。
    if b"<!DOCTYPE" in body:
        raise HTTPException(
            status_code=422,
            detail="XML with DOCTYPE declarations is not accepted",
        )
    return body


@router.post(
    "/import",
    response_model=RunResponse,
    status_code=201,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="导入外部测试结果",
    description=(
        "请求体为原始 JUnit XML（Content-Type: application/xml，≤10MB），"
        "元数据走 query 参数。生成一条终态 Run，立即进入 Analytics 与通知管线。"
        "导入不去重：重复上传同一文件生成两条独立 Run，幂等性由调用方负责。"
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/xml": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def import_run_results(
    project_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    git_ref: str = Query(..., min_length=1, max_length=200),
    git_sha: str | None = Query(
        None,
        pattern=r"^[0-9a-fA-F]{40}$",
        description="可选完整 Git commit SHA",
    ),
    branch: str | None = Query(None, min_length=1, max_length=200),
    pipeline_name: str = Query(
        DEFAULT_IMPORT_PIPELINE_NAME, min_length=1, max_length=100
    ),
    environment_name: str = Query(
        DEFAULT_IMPORT_ENVIRONMENT_NAME, min_length=1, max_length=100
    ),
    started_at: datetime | None = Query(None, description="ISO8601；缺省自动推导"),
    finished_at: datetime | None = Query(None, description="ISO8601；缺省自动推导"),
    session: AsyncSession = Depends(_get_db_session),
):
    if git_ref.strip() == "":
        raise HTTPException(status_code=422, detail="Invalid git_ref: empty")

    body = await _read_xml_body(request)

    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Project is archived; results cannot be imported",
        )

    await enforce_project_action(session, user, project.id, Action.RUN_TRIGGER)

    try:
        parsed = parse_junit_xml_content(body)
    except JUnitParseError as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid JUnit XML: {exc}"
        ) from None

    results = merge_duplicate_results(parsed)
    summary = build_results_summary(results)
    has_failures = any(r.status in {"failed", "error"} for r in results)
    status = RunStatusEnum.FAILED if has_failures else RunStatusEnum.DONE

    total_duration_ms = sum(r.duration_ms for r in results)
    run_started_at, run_finished_at, duration_ms = resolve_import_timestamps(
        started_at, finished_at, total_duration_ms
    )

    pipeline = await _get_or_create_import_pipeline(
        repos, session, project.id, pipeline_name
    )
    environment = await _get_or_create_import_environment(
        repos, session, project.id, environment_name
    )

    import_metadata: dict = {"source": "junit-xml"}
    if branch is not None:
        import_metadata["branch"] = branch

    run = await repos.run.create(
        tenant_id=user.tenant_id,
        project_id=project.id,
        pipeline_id=pipeline.id,
        environment_id=environment.id,
        status=status,
        trigger_type="import",
        triggered_by=user.user_id,
        git_ref=git_ref,
        git_sha=git_sha,
        started_at=run_started_at,
        finished_at=run_finished_at,
        duration_ms=duration_ms,
        summary=summary,
        metadata_={"import": import_metadata},
    )
    if results:
        await repos.test_result.bulk_create(
            build_test_result_rows(run.id, results)
        )

    response = to_run_response(run)
    after_state = response.model_dump(mode="json")
    after_state["import_counts"] = {
        "total": summary["total"],
        "passed": summary["passed"],
        "failed": summary["failed"],
        "skipped": summary["skipped"],
        "error": summary["error"],
    }
    await write_audit(
        repos, user,
        action="run.import",
        resource_type="run",
        resource_id=run.id,
        after=after_state,
    )

    # 通知评估只在 worker 收尾路径触发；import 绕过 worker，落库后补偿调用。
    # 先 commit 使 run 对通知评估的独立 session 可见。
    await repos.run.commit()

    container = request.app.state.container
    session_factory = getattr(container, "db_session_factory", None)
    if session_factory is not None:
        try:
            from qaplatform.worker.notifications import evaluate_and_notify

            await evaluate_and_notify(
                run_id=run.id,
                project_id=project.id,
                status=status.value,
                summary=summary,
                session_factory=session_factory,
            )
        except Exception:
            log.warning(
                "notification_evaluation_failed_for_import",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )

    return response
