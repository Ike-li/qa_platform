from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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

    async def list_failed_by_run(self, run_id: UUID) -> list[TestResult]:
        """本 run 的全部 failed/error 结果（triage 的分诊对象，xfail 不算失败）。"""
        stmt = (
            select(TestResult)
            .where(
                TestResult.run_id == run_id,
                TestResult.status.in_([
                    TestResultStatusEnum.FAILED,
                    TestResultStatusEnum.ERROR,
                ]),
            )
            .order_by(TestResult.suite.asc(), TestResult.name.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_prior_observations_for_failed_cases(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        cutoff: datetime,
        before_created_at: datetime,
        before_run_id: UUID,
        per_case_limit: int,
    ) -> tuple[dict[tuple[str, str], list[Any]], dict[tuple[str, str], int]]:
        """批量取本 run 全部 failed/error 用例在本 run 之前的最近观测。

        test-history 端点查询模式的批量版：用 (suite, name) 自连接本 run 的
        失败行替代 IN 列表，窗口函数按用例分组限行，一次查询取齐全部历史，
        避免按用例循环的 N+1。历史口径与 analytics 一致：project 级按
        (suite, name) 聚合（经 ``analytics_run_filters``），不按 pipeline 切分。

        返回 ``(history, counts)``：history 每用例按时间降序（最新在前）最多
        ``per_case_limit`` 条；counts 是窗口内本 run 之前的总观测数。
        """
        current = aliased(TestResult)
        filters = analytics_run_filters(project_id=project_id, cutoff=cutoff)
        rn = (
            func.row_number()
            .over(
                partition_by=(TestResult.suite, TestResult.name),
                order_by=(Run.created_at.desc(), Run.id.desc()),
            )
            .label("rn")
        )
        prior_count = (
            func.count()
            .over(partition_by=(TestResult.suite, TestResult.name))
            .label("prior_count")
        )
        subq = (
            select(
                TestResult.suite,
                TestResult.name,
                TestResult.status,
                TestResult.run_id,
                Run.created_at.label("run_created_at"),
                rn,
                prior_count,
            )
            .join(Run, Run.id == TestResult.run_id)
            .join(
                current,
                and_(
                    current.run_id == run_id,
                    current.status.in_([
                        TestResultStatusEnum.FAILED,
                        TestResultStatusEnum.ERROR,
                    ]),
                    current.suite == TestResult.suite,
                    current.name == TestResult.name,
                ),
            )
            .where(*filters)
            .where(
                tuple_(Run.created_at, Run.id)
                < tuple_(before_created_at, before_run_id)
            )
            .subquery()
        )
        stmt = (
            select(subq)
            .where(subq.c.rn <= per_case_limit)
            .order_by(subq.c.suite.asc(), subq.c.name.asc(), subq.c.rn.asc())
        )
        rows = (await self.session.execute(stmt)).all()

        history: dict[tuple[str, str], list[Any]] = {}
        counts: dict[tuple[str, str], int] = {}
        for row in rows:
            key = (row.suite, row.name)
            history.setdefault(key, []).append(row)
            counts[key] = row.prior_count
        return history, counts

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
