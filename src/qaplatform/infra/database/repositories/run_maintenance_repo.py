from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Collection

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from qaplatform.domain.models.run import TERMINAL_STATUSES
from qaplatform.infra.database.models import Run, RunStatusEnum
from qaplatform.infra.database.repositories.run_status_helpers import run_status_enums


_TERMINAL_STATUS_ENUMS = run_status_enums(TERMINAL_STATUSES)


class RunMaintenanceRepositoryMixin:
    async def count_by_statuses(
        self,
        statuses: Collection[RunStatusEnum | str | PyEnum],
    ) -> int:
        """Count non-deleted runs whose status is in ``statuses``."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            Run.status.in_(run_status_enums(statuses)),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_finished_since_by_statuses(
        self,
        *,
        since: datetime,
        statuses: Collection[RunStatusEnum | str | PyEnum],
    ) -> int:
        """Count non-deleted terminal runs in ``statuses`` finished since ``since``."""
        stmt = select(func.count()).select_from(Run).where(
            Run.deleted_at.is_(None),
            Run.finished_at >= since,
            Run.status.in_(run_status_enums(statuses)),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def delete_terminal_older_than(self, *, cutoff: datetime) -> int:
        """Hard-delete terminal runs older than cutoff."""
        stmt = sa_delete(Run).where(
            Run.status.in_(_TERMINAL_STATUS_ENUMS),
            Run.finished_at < cutoff,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount
