"""Run, TestResult, and Artifact repositories with conditional status updates."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Any, AsyncIterator, Collection
from uuid import UUID

from sqlalchemy import and_, case, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import (
    Artifact,
    Pipeline,
    Run,
    RunStatusEnum,
    TestResult,
    TestResultStatusEnum,
)
from qaplatform.infra.database.repositories.base import BaseRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunRepository(BaseRepository[Run]):
    model = Run
    _FINISH_EXPECTED = frozenset({RunStatusEnum.RUNNING, RunStatusEnum.COLLECTING})
    _FAIL_EXPECTED = frozenset({
        RunStatusEnum.QUEUED,
        RunStatusEnum.PREPARING,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    })
    _CANCEL_EXPECTED = frozenset({
        RunStatusEnum.QUEUED,
        RunStatusEnum.PREPARING,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    })
    _DEDUP_ACTIVE_STATUSES = frozenset({
        RunStatusEnum.QUEUED,
        RunStatusEnum.PREPARING,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    })

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _coerce_status(status: RunStatusEnum | str | PyEnum) -> RunStatusEnum:
        if isinstance(status, RunStatusEnum):
            return status
        if isinstance(status, PyEnum):
            return RunStatusEnum(status.value)
        return RunStatusEnum(status)

    @classmethod
    def _expected_statuses(
        cls,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None,
        default: frozenset[RunStatusEnum],
    ) -> frozenset[RunStatusEnum]:
        if expected_in is None:
            return default
        return frozenset(cls._coerce_status(status) for status in expected_in)

    async def list_by_project(
        self, project_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Run], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Run.project_id == project_id],
        )

    async def list_by_pipeline(
        self, pipeline_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Run], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Run.pipeline_id == pipeline_id],
        )

    async def get_by_arq_job_id(self, arq_job_id: str) -> Run | None:
        stmt = select(Run).where(
            Run.arq_job_id == arq_job_id,
            Run.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_dedup(
        self,
        *,
        project_id: UUID,
        pipeline_id: UUID,
        dedup_key: str,
    ) -> Run | None:
        stmt = (
            select(Run)
            .where(
                Run.project_id == project_id,
                Run.pipeline_id == pipeline_id,
                Run.dedup_key == dedup_key,
                Run.status.in_(self._DEDUP_ACTIVE_STATUSES),
                Run.deleted_at.is_(None),
            )
            .order_by(Run.created_at)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # --- Worker lifecycle (conditional updates) ---

    async def claim_for_worker(self, run_id: UUID, worker_id: str) -> Run | None:
        """Atomically claim a queued run for a worker. Returns the run or None if already claimed."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status == RunStatusEnum.QUEUED, Run.deleted_at.is_(None))
            .values(
                status=RunStatusEnum.PREPARING,
                worker_id=worker_id,
                status_updated_at=now,
                updated_at=now,
            )
            .returning(Run)
        )
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        if run:
            await self.session.flush()
            await self.session.refresh(run)
        return run

    async def set_retry_group_id(self, run_id: UUID | str, group_id: UUID | str) -> None:
        """Set retry_group_id for a run (typically to its own id)."""
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(retry_group_id=group_id, updated_at=_utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def finish_if_current(
        self,
        run_id: UUID,
        *,
        status: RunStatusEnum | str | PyEnum,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None = None,
        summary: dict | None = None,
    ) -> bool:
        """Set terminal status only if current status matches expected set. Returns True if updated."""
        now = _utcnow()
        values: dict = {
            "status": self._coerce_status(status),
            "finished_at": now,
            "status_updated_at": now,
            "updated_at": now,
        }
        if summary is not None:
            values["summary"] = summary
        expected = self._expected_statuses(expected_in, self._FINISH_EXPECTED)
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected),
                Run.deleted_at.is_(None),
            )
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def fail_if_current(
        self,
        run_id: UUID,
        *,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None = None,
        message: str | None = None,
    ) -> bool:
        """Mark run as failed only if current status matches. Returns True if updated."""
        now = _utcnow()
        values: dict = {
            "status": RunStatusEnum.FAILED,
            "finished_at": now,
            "error_message": message,
            "status_updated_at": now,
            "updated_at": now,
        }
        expected = self._expected_statuses(expected_in, self._FAIL_EXPECTED)
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected),
                Run.deleted_at.is_(None),
            )
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def cancel_if_current(
        self,
        run_id: UUID,
        *,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None = None,
    ) -> bool:
        """Cancel run only if current status matches. Returns True if updated."""
        now = _utcnow()
        expected = self._expected_statuses(expected_in, self._CANCEL_EXPECTED)
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected),
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.CANCELLED,
                finished_at=now,
                status_updated_at=now,
                updated_at=now,
                cancel_requested_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def timeout_if_current(
        self, run_id: UUID, *, expected_in: set[RunStatusEnum]
    ) -> bool:
        """Mark run as timeout only if current status matches. Returns True if updated."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected_in),
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.TIMEOUT,
                finished_at=now,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def mark_enqueued(
        self, run_id: UUID, *, queue_name: str, arq_job_id: str, enqueued_at: datetime
    ) -> None:
        now = _utcnow()
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(
                queue_name=queue_name,
                arq_job_id=arq_job_id,
                enqueued_at=enqueued_at,
                updated_at=now,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_waiting(self, run_id: UUID, reason: str | None = None) -> None:
        """Keep run in queued state (not yet enqueued)."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(updated_at=now)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_running(self, run_id: UUID) -> bool:
        """Set PREPARING → RUNNING. Returns True if the row was updated.

        Returns False when a concurrent CANCEL/FAIL has already moved the run
        out of PREPARING — caller should treat this as a state race, not an
        error.  Matches the pattern of ``finish_if_current`` /
        ``cancel_if_current``.
        """
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatusEnum.PREPARING,
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.RUNNING,
                started_at=now,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def mark_collecting(self, run_id: UUID) -> bool:
        """Set RUNNING → COLLECTING. Returns True if the row was updated.

        Returns False when a concurrent CANCEL/FAIL has already moved the run
        out of RUNNING — caller should treat this as a state race, not an
        error.  Matches the pattern of ``finish_if_current`` /
        ``cancel_if_current``.
        """
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatusEnum.RUNNING,
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.COLLECTING,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def is_cancel_requested(self, run_id: UUID) -> bool:
        """Has cancel been requested for this run?

        P1-D fallback for redis pub/sub: if the cancel signal was
        published before the worker subscribed, the message is gone
        forever (pub/sub is not persistent). The cancel API also writes
        ``cancel_requested_at`` on the row, so the executor can poll the
        DB at stage boundaries to recover any dropped notification.

        Uses a fresh SELECT to bypass the session's identity map; the
        cancel write happens in a separate connection and the cached
        ORM object would otherwise still show the old value.
        """
        stmt = select(Run.cancel_requested_at).where(Run.id == run_id, Run.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        value = result.scalar_one_or_none()
        return value is not None

    async def release_worker(self, run_id: UUID, worker_id: str) -> None:
        """Clear worker_id after run completes (best-effort)."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.worker_id == worker_id,
                Run.deleted_at.is_(None),
            )
            .values(worker_id=None, updated_at=now)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_worker_lost(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        message: str,
    ) -> bool:
        """Mark a non-terminal run as failed because its worker heartbeat expired.

        Conditional on (status non-terminal) AND (worker_id still matches), so a
        run that just got reclaimed by another worker, finished normally, or was
        cancelled in the meantime is left untouched.
        """
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.worker_id == worker_id,
                Run.status.in_(self._FAIL_EXPECTED),
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.FAILED,
                finished_at=now,
                error_message=message,
                worker_id=None,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    # --- Queries for scheduler / reclaimer ---

    async def find_waiting(self, limit: int = 10) -> list[Run]:
        """Find queued runs not yet enqueued, ordered by priority."""
        stmt = (
            select(Run)
            .where(Run.status == RunStatusEnum.QUEUED, Run.enqueued_at.is_(None), Run.deleted_at.is_(None))
            .order_by(Run.priority, Run.created_at)
            .limit(limit)
            .with_for_update(of=Run, skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_stale(
        self, *, status: RunStatusEnum, older_than: datetime
    ) -> list[Run]:
        """Find runs stuck in a status older than threshold."""
        stmt = select(Run).where(
            Run.status == status,
            Run.status_updated_at < older_than,
            Run.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_with_worker(self) -> list[Run]:
        """Find non-terminal runs that have a worker assigned."""
        stmt = select(Run).where(
            Run.status.in_([
                RunStatusEnum.PREPARING,
                RunStatusEnum.RUNNING,
                RunStatusEnum.COLLECTING,
            ]),
            Run.worker_id.isnot(None),
            Run.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_past_pipeline_deadline(
        self,
        statuses: list[RunStatusEnum],
        buffer_seconds: int = 120,
    ) -> list[Run]:
        """Find runs exceeding their pipeline timeout (stale running/collecting).

        A run is considered past deadline when:
            status_updated_at + GREATEST(pipeline.timeout_seconds, 1800) + buffer_seconds < now()

        ``buffer_seconds`` (default 120) gives the worker time to handle its own
        SIGTERM→SIGKILL sequence (~30 s) and for the status write-back + Redis
        pub/sub propagation to settle before reclaim forcibly marks the run failed.

        ``GREATEST(pipeline.timeout_seconds, 1800)`` is used instead of
        ``COALESCE`` because a pipeline with timeout_seconds=0 would otherwise
        produce an absurdly short deadline; treating any value below 1800 as 1800
        is the safer floor.
        """
        stmt = (
            select(Run)
            .join(Pipeline, Pipeline.id == Run.pipeline_id)
            .where(
                Run.status.in_(statuses),
                Run.deleted_at.is_(None),
                text(
                    "run.status_updated_at + "
                    "(INTERVAL '1 second' * ("
                    "GREATEST(pipeline.timeout_seconds, 1800) + :buffer_seconds"
                    ")) < now()"
                ).bindparams(buffer_seconds=buffer_seconds),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Scheduler support ---

    _ACTIVE_STATUSES = {
        RunStatusEnum.PREPARING,
        RunStatusEnum.RUNNING,
        RunStatusEnum.COLLECTING,
    }

    async def count_active_or_enqueued(self) -> int:
        """Count globally active or enqueued runs."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            (Run.status.in_(self._ACTIVE_STATUSES))
            | ((Run.status == RunStatusEnum.QUEUED) & (Run.enqueued_at.isnot(None)))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_active_or_enqueued_by_project(self, project_id: UUID) -> int:
        """Count active or enqueued runs for a specific project."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            Run.project_id == project_id,
            (Run.status.in_(self._ACTIVE_STATUSES))
            | ((Run.status == RunStatusEnum.QUEUED) & (Run.enqueued_at.isnot(None)))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_queued_waiting(self) -> int:
        """Count queued runs not yet dispatched to arq (enqueued_at IS NULL)."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            Run.status == RunStatusEnum.QUEUED,
            Run.enqueued_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_by_statuses(self, statuses: Collection[RunStatusEnum]) -> int:
        """Count non-deleted runs whose status is in ``statuses``."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            Run.status.in_(statuses),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_finished_since_by_statuses(
        self,
        *,
        since: datetime,
        statuses: Collection[RunStatusEnum],
    ) -> int:
        """Count non-deleted terminal runs in ``statuses`` finished since ``since``."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            Run.finished_at >= since,
            Run.status.in_(statuses),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

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

    @asynccontextmanager
    async def scheduler_lock(self) -> AsyncIterator[None]:
        """Acquire a PostgreSQL advisory lock for the scheduler."""
        lock_id = 8675309  # arbitrary fixed ID for scheduler
        await self.session.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))
        yield

    async def update_git_sha(self, run_id: UUID, sha: str) -> None:
        """Write the resolved git commit SHA back to the run record."""
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(git_sha=sha, updated_at=_utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_execution_id(self, run_id: UUID, execution_id: str) -> None:
        """Write the container execution ID to the run record."""
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(execution_id=execution_id, updated_at=_utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete_terminal_older_than(self, *, cutoff: datetime) -> int:
        """Hard-delete terminal runs (and cascade) older than cutoff.

        Any run in a terminal state with ``finished_at < cutoff`` is eligible,
        whether or not it was previously soft-deleted. Active or recently
        finished runs are kept. The caller is responsible for committing the
        session.
        """
        from sqlalchemy import delete as sa_delete

        stmt = (
            sa_delete(Run)
            .where(
                Run.status.in_([
                    RunStatusEnum.DONE,
                    RunStatusEnum.FAILED,
                    RunStatusEnum.CANCELLED,
                    RunStatusEnum.TIMEOUT,
                ]),
                Run.finished_at < cutoff,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount


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


class ArtifactRepository(BaseRepository[Artifact]):
    model = Artifact

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_run(
        self, run_id: UUID, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Artifact], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Artifact.run_id == run_id],
        )
