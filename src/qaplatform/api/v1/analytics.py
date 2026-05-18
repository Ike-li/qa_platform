from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, case, and_
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
    FlakyResponse,
    FlakyTest,
    TrendDataPoint,
    TrendsResponse,
)
from qaplatform.infra.database.models import (
    Run as RunORM,
    RunStatusEnum,
    TestResult as TestResultORM,
    TestResultStatusEnum,
)

router = APIRouter(prefix="/projects/{project_id}/analytics", tags=["analytics"])


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

    # Shared filter conditions
    filters = (
        RunORM.project_id == project_id,
        RunORM.created_at >= cutoff,
        RunORM.status.in_([RunStatusEnum.DONE, RunStatusEnum.FAILED, RunStatusEnum.TIMEOUT]),
    )

    # Total count of distinct dates
    count_sub = (
        select(func.count(func.distinct(func.date(RunORM.created_at))))
        .where(*filters)
    )
    total = (await session.execute(count_sub)).scalar_one()

    # Paginated data
    stmt = (
        select(
            func.date(RunORM.created_at).label("date"),
            func.count().label("total_runs"),
            func.sum(case((RunORM.status == RunStatusEnum.DONE, 1), else_=0)).label("passed_runs"),
            func.sum(case((RunORM.status.in_([RunStatusEnum.FAILED, RunStatusEnum.TIMEOUT]), 1), else_=0)).label("failed_runs"),
        )
        .where(*filters)
        .group_by(func.date(RunORM.created_at))
        .order_by(func.date(RunORM.created_at))
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

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

    # Shared filter conditions
    filters = (
        RunORM.project_id == project_id,
        RunORM.created_at >= cutoff,
        RunORM.status.in_([RunStatusEnum.DONE, RunStatusEnum.FAILED, RunStatusEnum.TIMEOUT]),
    )

    # HAVING conditions for flaky tests
    having_cond = and_(
        func.count() >= min_runs,
        func.sum(case((TestResultORM.status == TestResultStatusEnum.PASSED, 1), else_=0)) > 0,
        func.sum(case((TestResultORM.status.in_([TestResultStatusEnum.FAILED, TestResultStatusEnum.ERROR]), 1), else_=0)) > 0,
    )

    failed_expr = func.sum(case((TestResultORM.status.in_([TestResultStatusEnum.FAILED, TestResultStatusEnum.ERROR]), 1), else_=0))

    # Count total flaky test groups
    count_sub = (
        select(func.count())
        .select_from(
            select(
                TestResultORM.suite,
                TestResultORM.name,
            )
            .join(RunORM, RunORM.id == TestResultORM.run_id)
            .where(*filters)
            .group_by(TestResultORM.suite, TestResultORM.name)
            .having(having_cond)
            .subquery()
        )
    )
    total = (await session.execute(count_sub)).scalar_one()

    # Paginated data
    stmt = (
        select(
            TestResultORM.suite,
            TestResultORM.name,
            func.count().label("total_runs"),
            func.sum(case((TestResultORM.status == TestResultStatusEnum.PASSED, 1), else_=0)).label("passed_count"),
            func.sum(case((TestResultORM.status.in_([TestResultStatusEnum.FAILED, TestResultStatusEnum.ERROR]), 1), else_=0)).label("failed_count"),
        )
        .join(RunORM, RunORM.id == TestResultORM.run_id)
        .where(*filters)
        .group_by(TestResultORM.suite, TestResultORM.name)
        .having(having_cond)
        .order_by(failed_expr.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

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
