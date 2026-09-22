from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select

from qaplatform.infra.database.models import (
    Run,
    RunStatusEnum,
    TestResult,
    TestResultStatusEnum,
)
from qaplatform.infra.database.repositories.run_query_helpers import (
    analytics_run_filters,
)


class RunAnalyticsRepositoryMixin:
    async def count_consecutive_failures(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        limit: int = 100,
    ) -> int:
        """Count terminal failed runs ending with ``run_id`` within a project."""
        current_stmt = select(Run).where(
            Run.id == run_id,
            Run.project_id == project_id,
            Run.deleted_at.is_(None),
        )
        current_result = await self.session.execute(current_stmt)
        current = current_result.scalar_one_or_none()
        if current is None or current.status != RunStatusEnum.FAILED:
            return 0

        terminal_statuses = (
            RunStatusEnum.DONE,
            RunStatusEnum.FAILED,
            RunStatusEnum.CANCELLED,
            RunStatusEnum.TIMEOUT,
        )
        stmt = (
            select(Run.status)
            .where(
                Run.project_id == project_id,
                Run.deleted_at.is_(None),
                Run.status.in_(terminal_statuses),
                Run.created_at <= current.created_at,
            )
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)

        count = 0
        for status in result.scalars():
            if status != RunStatusEnum.FAILED:
                break
            count += 1
        return count

    async def list_trend_points(
        self,
        *,
        project_id: UUID,
        cutoff: datetime,
        offset: int,
        limit: int,
        git_ref: str | None = None,
    ) -> tuple[list[Any], int]:
        filters = analytics_run_filters(
            project_id=project_id,
            cutoff=cutoff,
            git_ref=git_ref,
        )
        count_stmt = select(func.count(func.distinct(func.date(Run.created_at)))).where(
            *filters
        )
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(
                func.date(Run.created_at).label("date"),
                func.count().label("total_runs"),
                func.sum(case((Run.status == RunStatusEnum.DONE, 1), else_=0)).label(
                    "passed_runs"
                ),
                func.sum(
                    case(
                        (
                            Run.status.in_([
                                RunStatusEnum.FAILED,
                                RunStatusEnum.TIMEOUT,
                            ]),
                            1,
                        ),
                        else_=0,
                    )
                ).label("failed_runs"),
            )
            .where(*filters)
            .group_by(func.date(Run.created_at))
            .order_by(func.date(Run.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.all()), total

    async def get_release_summary(
        self,
        *,
        project_id: UUID,
        cutoff: datetime,
        git_ref: str,
        baseline_git_ref: str,
        delta_limit: int = 20,
        quarantined: set[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        target_filters = analytics_run_filters(
            project_id=project_id,
            cutoff=cutoff,
            git_ref=git_ref,
        )
        baseline_filters = analytics_run_filters(
            project_id=project_id,
            cutoff=cutoff,
            git_ref=baseline_git_ref,
        )
        failed_run_filter = Run.status.in_([
            RunStatusEnum.FAILED,
            RunStatusEnum.TIMEOUT,
        ])

        stats_stmt = select(
            func.count().label("total_runs"),
            func.sum(case((Run.status == RunStatusEnum.DONE, 1), else_=0)).label(
                "passed_runs"
            ),
            func.sum(case((failed_run_filter, 1), else_=0)).label("failed_runs"),
        ).where(*target_filters)
        stats = (await self.session.execute(stats_stmt)).one()
        total_runs = int(stats.total_runs or 0)
        passed_runs = int(stats.passed_runs or 0)
        failed_runs = int(stats.failed_runs or 0)

        async def grouped_results(filters: tuple[Any, ...]) -> list[Any]:
            failed_result_filter = TestResult.status.in_([
                TestResultStatusEnum.FAILED,
                TestResultStatusEnum.ERROR,
            ])
            stmt = (
                select(
                    TestResult.suite,
                    TestResult.name,
                    func.count().label("total_count"),
                    func.sum(
                        case(
                            (TestResult.status == TestResultStatusEnum.PASSED, 1),
                            else_=0,
                        )
                    ).label("passed_count"),
                    func.sum(case((failed_result_filter, 1), else_=0)).label(
                        "failed_count"
                    ),
                )
                .join(Run, Run.id == TestResult.run_id)
                .where(*filters)
                .group_by(TestResult.suite, TestResult.name)
            )
            result = await self.session.execute(stmt)
            return list(result.all())

        target_results = await grouped_results(target_filters)
        baseline_results = await grouped_results(baseline_filters)
        quarantine_set = quarantined or set()
        flaky_keys = {
            (row.suite, row.name)
            for row in target_results
            if int(row.passed_count or 0) > 0 and int(row.failed_count or 0) > 0
        }
        stable_results = [
            row
            for row in target_results
            if (row.suite, row.name) not in flaky_keys
            and (row.suite, row.name) not in quarantine_set
        ]
        stable_total = sum(int(row.total_count or 0) for row in stable_results)
        stable_passed = sum(int(row.passed_count or 0) for row in stable_results)
        flaky_adjusted_pass_rate = (
            round(stable_passed / stable_total, 4) if stable_total > 0 else None
        )

        target_failed_all = {
            (row.suite, row.name): int(row.failed_count or 0)
            for row in target_results
            if int(row.failed_count or 0) > 0
        }
        quarantined_excluded = sorted(
            [
                {"suite": s, "name": n}
                for (s, n) in quarantine_set
                if (s, n) in target_failed_all
            ],
            key=lambda x: (x["suite"], x["name"]),
        )

        target_failed = {
            k: v for k, v in target_failed_all.items() if k not in quarantine_set
        }
        baseline_failed = {
            (row.suite, row.name): int(row.failed_count or 0)
            for row in baseline_results
            if int(row.failed_count or 0) > 0 and (row.suite, row.name) not in quarantine_set
        }

        def deltas(source: dict[tuple[str, str], int], other: dict[tuple[str, str], int]):
            rows = [
                {"suite": suite, "name": name, "failed_count": count}
                for (suite, name), count in source.items()
                if (suite, name) not in other
            ]
            return sorted(
                rows,
                key=lambda row: (-row["failed_count"], row["suite"], row["name"]),
            )[:delta_limit]

        return {
            "git_ref": git_ref,
            "baseline_git_ref": baseline_git_ref,
            "total_runs": total_runs,
            "passed_runs": passed_runs,
            "failed_runs": failed_runs,
            "raw_pass_rate": round(passed_runs / total_runs, 4)
            if total_runs > 0
            else 0.0,
            "flaky_adjusted_pass_rate": flaky_adjusted_pass_rate,
            "new_failing_tests": deltas(target_failed, baseline_failed),
            "recovered_tests": deltas(baseline_failed, target_failed),
            "quarantined_excluded": quarantined_excluded,
        }
