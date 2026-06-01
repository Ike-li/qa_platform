from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.schemas import (
    AnalyticsPaginationMeta,
    ErrorResponse,
    FlakyResponse,
    FlakyTest,
    TestHistoryPoint,
    TestHistoryResponse,
    TrendDataPoint,
    TrendsResponse,
)

router = APIRouter(prefix="/projects/{project_id}/analytics", tags=["analytics"])


def _validate_history_text_filter(name: str, value: str) -> None:
    if value.strip() == "":
        raise HTTPException(status_code=422, detail=f"Invalid analytics {name}: empty")


@router.get(
    "/trends",
    response_model=TrendsResponse,
    summary="历史趋势",
)
async def get_run_trends(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    days: int = Query(30, ge=1, le=365),
    offset: int = Query(0, ge=0),
    limit: int = Query(365, ge=1, le=365),
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.RUN_READ)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows, total = await repos.run.list_trend_points(
        project_id=project_id,
        cutoff=cutoff,
        offset=offset,
        limit=limit,
    )

    return TrendsResponse(
        data=[
            TrendDataPoint(
                date=str(row.date),
                total_runs=row.total_runs,
                passed_runs=row.passed_runs,
                failed_runs=row.failed_runs,
                pass_rate=round(row.passed_runs / row.total_runs, 4) if row.total_runs > 0 else 0.0,
            )
            for row in rows
        ],
        pagination=AnalyticsPaginationMeta(offset=offset, limit=limit, total=total),
    )


@router.get(
    "/flaky",
    response_model=FlakyResponse,
    summary="Flaky 测试检测",
)
async def get_flaky_tests(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    days: int = Query(30, ge=1, le=365),
    min_runs: int = Query(3, ge=2, le=100),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.RUN_READ)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows, total = await repos.test_result.list_flaky_tests(
        project_id=project_id,
        cutoff=cutoff,
        min_runs=min_runs,
        offset=offset,
        limit=limit,
    )

    return FlakyResponse(
        data=[
            FlakyTest(
                suite=row.suite,
                name=row.name,
                total_runs=row.total_runs,
                passed_count=row.passed_count,
                failed_count=row.failed_count,
                flaky_rate=round(row.failed_count / row.total_runs, 4),
            )
            for row in rows
        ],
        pagination=AnalyticsPaginationMeta(offset=offset, limit=limit, total=total),
    )


@router.get(
    "/test-history",
    response_model=TestHistoryResponse,
    responses={422: {"model": ErrorResponse}},
    summary="单用例历史趋势",
)
async def get_test_history(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    suite: str = Query(..., min_length=1, max_length=255),
    name: str = Query(..., min_length=1, max_length=500),
    days: int = Query(30, ge=1, le=365),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(_get_db_session),
):
    _validate_history_text_filter("suite", suite)
    _validate_history_text_filter("name", name)

    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.RUN_READ)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows, total = await repos.test_result.list_test_history(
        project_id=project_id,
        suite=suite,
        name=name,
        cutoff=cutoff,
        offset=offset,
        limit=limit,
    )

    return TestHistoryResponse(
        data=[
            TestHistoryPoint(
                run_id=row.run_id,
                run_created_at=row.run_created_at,
                run_status=row.run_status,
                status=row.status,
                duration_ms=row.duration_ms,
                error_message=row.error_message,
                git_ref=row.git_ref,
            )
            for row in rows
        ],
        pagination=AnalyticsPaginationMeta(offset=offset, limit=limit, total=total),
    )
