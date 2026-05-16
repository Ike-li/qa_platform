"""Run, TestResult, and Artifact repositories with conditional status updates."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import (
    Artifact,
    Run,
    RunStatusEnum,
    TestResult,
)
from qaplatform.infra.database.repositories.base import BaseRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunRepository(BaseRepository[Run]):
    model = Run

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

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
        stmt = select(Run).where(Run.arq_job_id == arq_job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # --- Worker lifecycle (conditional updates) ---

    async def claim_for_worker(self, run_id: UUID, worker_id: str) -> Run | None:
        """Atomically claim a queued run for a worker. Returns the run or None if already claimed."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status == RunStatusEnum.QUEUED)
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

    async def finish_if_current(
        self, run_id: UUID, *, status: RunStatusEnum, expected_in: set[RunStatusEnum]
    ) -> bool:
        """Set terminal status only if current status matches expected set. Returns True if updated."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status.in_(expected_in))
            .values(
                status=status,
                finished_at=now,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def fail_if_current(
        self, run_id: UUID, *, expected_in: set[RunStatusEnum], message: str | None = None
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
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status.in_(expected_in))
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def cancel_if_current(
        self, run_id: UUID, *, expected_in: set[RunStatusEnum]
    ) -> bool:
        """Cancel run only if current status matches. Returns True if updated."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.status.in_(expected_in))
            .values(
                status=RunStatusEnum.CANCELLED,
                finished_at=now,
                status_updated_at=now,
                updated_at=now,
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

    async def mark_running(self, run_id: UUID) -> None:
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
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_collecting(self, run_id: UUID) -> None:
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
        await self.session.execute(stmt)
        await self.session.flush()

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

    # --- Queries for scheduler / reclaimer ---

    async def find_waiting(self, limit: int = 10) -> list[Run]:
        """Find queued runs not yet enqueued, ordered by priority."""
        stmt = (
            select(Run)
            .where(Run.status == RunStatusEnum.QUEUED, Run.enqueued_at.is_(None))
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
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_past_pipeline_deadline(
        self, statuses: list[RunStatusEnum]
    ) -> list[Run]:
        """Find runs exceeding their pipeline timeout (stale running/collecting)."""
        stmt = (
            select(Run)
            .where(
                Run.status.in_(statuses),
                text("status_updated_at + (INTERVAL '1 second' * 1800) < now()"),
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
            (Run.status.in_(self._ACTIVE_STATUSES))
            | ((Run.status == RunStatusEnum.QUEUED) & (Run.enqueued_at.isnot(None)))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_active_or_enqueued_by_project(self, project_id: UUID) -> int:
        """Count active or enqueued runs for a specific project."""
        stmt = select(func.count()).select_from(Run).where(
            Run.project_id == project_id,
            (Run.status.in_(self._ACTIVE_STATUSES))
            | ((Run.status == RunStatusEnum.QUEUED) & (Run.enqueued_at.isnot(None)))
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
