from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import (
    Run,
    RunStatusEnum,
    TestResult,
    TestResultStatusEnum,
)
from qaplatform.infra.database.repositories.base import BaseRepository
from qaplatform.infra.database.repositories.run_query_helpers import (
    analytics_run_filters,
    escape_like,
)


class TestResultRepository(BaseRepository[TestResult]):
    model = TestResult

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_run(
        self, run_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[TestResult], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[TestResult.run_id == run_id],
        )

    async def list_filtered_by_run(
        self,
        *,
        run_id: UUID,
        offset: int = 0,
        limit: int = 100,
        status: str | TestResultStatusEnum | None = None,
        suite: str | None = None,
        query: str | None = None,
    ) -> tuple[list[TestResult], int]:
        filters: list[Any] = [TestResult.run_id == run_id]
        if status:
            filters.append(TestResult.status == status)
        if suite:
            filters.append(TestResult.suite == suite)
        if query:
            pattern = f"%{escape_like(query)}%"
            filters.append(
                or_(
                    TestResult.name.ilike(pattern, escape="\\"),
                    TestResult.error_message.ilike(pattern, escape="\\"),
                )
            )

        items, total = await self.list(offset=offset, limit=limit, filters=filters)
        return list(items), total

    async def list_by_run_and_status(
        self, run_id: UUID, status: str
    ) -> list[TestResult]:
        stmt = select(TestResult).where(
            TestResult.run_id == run_id,
            TestResult.status == status,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_create(self, results: list[dict]) -> list[TestResult]:
        instances = [TestResult(**r) for r in results]
        self.session.add_all(instances)
        await self.session.flush()
        for inst in instances:
            await self.session.refresh(inst)
        return instances

    async def list_flaky_tests(
        self,
        *,
        project_id: UUID,
        cutoff: datetime,
        min_runs: int,
        offset: int,
        limit: int,
        git_ref: str | None = None,
    ) -> tuple[list[Any], int]:
        filters = analytics_run_filters(
            project_id=project_id,
            cutoff=cutoff,
            git_ref=git_ref,
        )
        failed_filter = TestResult.status.in_([
            TestResultStatusEnum.FAILED,
            TestResultStatusEnum.ERROR,
        ])
        having_cond = and_(
            func.count() >= min_runs,
            func.sum(
                case((TestResult.status == TestResultStatusEnum.PASSED, 1), else_=0)
            )
            > 0,
            func.sum(case((failed_filter, 1), else_=0)) > 0,
        )
        failed_expr = func.sum(case((failed_filter, 1), else_=0))

        count_stmt = (
            select(func.count())
            .select_from(
                select(TestResult.suite, TestResult.name)
                .join(Run, Run.id == TestResult.run_id)
                .where(*filters)
                .group_by(TestResult.suite, TestResult.name)
                .having(having_cond)
                .subquery()
            )
        )
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(
                TestResult.suite,
                TestResult.name,
                func.count().label("total_runs"),
                func.sum(
                    case((TestResult.status == TestResultStatusEnum.PASSED, 1), else_=0)
                ).label("passed_count"),
                failed_expr.label("failed_count"),
            )
            .join(Run, Run.id == TestResult.run_id)
            .where(*filters)
            .group_by(TestResult.suite, TestResult.name)
            .having(having_cond)
            .order_by(failed_expr.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.all()), total

    async def list_test_history(
        self,
        *,
        project_id: UUID,
        suite: str,
        name: str,
        cutoff: datetime,
        offset: int,
        limit: int,
    ) -> tuple[list[Any], int]:
        filters = (
            Run.project_id == project_id,
            Run.created_at >= cutoff,
            Run.deleted_at.is_(None),
            Run.status.in_([
                RunStatusEnum.DONE,
                RunStatusEnum.FAILED,
                RunStatusEnum.TIMEOUT,
            ]),
            TestResult.suite == suite,
            TestResult.name == name,
        )
        count_stmt = (
            select(func.count())
            .select_from(TestResult)
            .join(Run, Run.id == TestResult.run_id)
            .where(*filters)
        )
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(
                TestResult.run_id,
                TestResult.status,
                TestResult.duration_ms,
                TestResult.error_message,
                Run.created_at.label("run_created_at"),
                Run.status.label("run_status"),
                Run.git_ref,
            )
            .join(Run, Run.id == TestResult.run_id)
            .where(*filters)
            .order_by(Run.created_at.asc(), Run.id.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.all()), total
