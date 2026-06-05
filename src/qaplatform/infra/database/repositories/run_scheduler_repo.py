from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import func, select, text, update

from qaplatform.domain.services.execution import IN_FLIGHT_STATUSES
from qaplatform.infra.database.models import Run, RunStatusEnum
from qaplatform.infra.database.repositories.run_status_helpers import run_status_enums


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_IN_FLIGHT_STATUS_ENUMS = run_status_enums(IN_FLIGHT_STATUSES)


class RunSchedulerRepositoryMixin:
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

    async def find_waiting(self, limit: int = 10) -> list[Run]:
        """Find queued runs not yet enqueued, ordered by priority."""
        stmt = (
            select(Run)
            .where(
                Run.status == RunStatusEnum.QUEUED,
                Run.enqueued_at.is_(None),
                Run.deleted_at.is_(None),
            )
            .order_by(Run.priority, Run.created_at)
            .limit(limit)
            .with_for_update(of=Run, skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_active_or_enqueued(self) -> int:
        """Count globally active or enqueued runs."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            (Run.status.in_(_IN_FLIGHT_STATUS_ENUMS))
            | ((Run.status == RunStatusEnum.QUEUED) & (Run.enqueued_at.isnot(None))),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_active_or_enqueued_by_project(self, project_id: UUID) -> int:
        """Count active or enqueued runs for a specific project."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            Run.project_id == project_id,
            (Run.status.in_(_IN_FLIGHT_STATUS_ENUMS))
            | ((Run.status == RunStatusEnum.QUEUED) & (Run.enqueued_at.isnot(None))),
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
