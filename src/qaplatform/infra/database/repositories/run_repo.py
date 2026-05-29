"""Run, TestResult, and Artifact repositories with conditional status updates."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import AsyncIterator, Collection
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import (
    Artifact,
    Pipeline,
    Run,
    RunStatusEnum,
    TestResult,
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
            .where(Run.id == run_id)
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
            .where(Run.id == run_id, Run.status.in_(expected))
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
            .where(Run.id == run_id, Run.status.in_(expected))
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
            .where(Run.id == run_id, Run.status.in_(expected))
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
            .where(Run.id == run_id, Run.status.in_(expected_in))
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
            .where(Run.id == run_id)
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
            .where(Run.id == run_id)
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
            .where(Run.id == run_id, Run.status == RunStatusEnum.PREPARING)
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
            .where(Run.id == run_id, Run.status == RunStatusEnum.RUNNING)
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
            .where(Run.id == run_id, Run.worker_id == worker_id)
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
            .where(Run.id == run_id)
            .values(git_sha=sha, updated_at=_utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_execution_id(self, run_id: UUID, execution_id: str) -> None:
        """Write the container execution ID to the run record."""
        stmt = (
            update(Run)
            .where(Run.id == run_id)
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
