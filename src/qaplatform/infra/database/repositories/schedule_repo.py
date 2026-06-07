"""Schedule repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Schedule
from qaplatform.infra.database.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository[Schedule]):
    model = Schedule

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_project(
        self, project_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Schedule], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Schedule.project_id == project_id],
        )

    async def find_due_schedules(self, now: datetime, *, limit: int = 50) -> list[Schedule]:
        """Find enabled schedules where next_run_at <= now."""
        stmt = (
            select(Schedule)
            .where(
                Schedule.enabled.is_(True),
                Schedule.deleted_at.is_(None),
                Schedule.next_run_at <= now,
            )
            .order_by(Schedule.next_run_at)
            .limit(limit)
            .with_for_update(of=Schedule, skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_after_fire(
        self,
        schedule_id: UUID,
        *,
        last_run_at: datetime,
        next_run_at: datetime | None,
        last_error: str | None = None,
    ) -> None:
        """Update schedule timestamps after a fire event."""
        schedule = await self.get_by_id(schedule_id)
        if schedule is None:
            return
        schedule.last_run_at = last_run_at
        schedule.next_run_at = next_run_at
        schedule.last_error = last_error
        await self.session.flush()
