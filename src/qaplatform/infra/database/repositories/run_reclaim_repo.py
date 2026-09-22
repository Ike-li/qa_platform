from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Collection

from sqlalchemy import select, text

from qaplatform.domain.services.execution import IN_FLIGHT_STATUSES
from qaplatform.infra.database.models import Pipeline, Run, RunStatusEnum
from qaplatform.infra.database.repositories.run_status_helpers import (
    coerce_run_status_enum,
    run_status_enums,
)

_IN_FLIGHT_STATUS_ENUMS = run_status_enums(IN_FLIGHT_STATUSES)


class RunReclaimRepositoryMixin:
    async def find_stale(
        self,
        *,
        status: RunStatusEnum | str | PyEnum,
        older_than: datetime,
    ) -> list[Run]:
        """Find runs stuck in a status older than threshold."""
        stmt = select(Run).where(
            Run.status == coerce_run_status_enum(status),
            Run.status_updated_at < older_than,
            Run.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_with_worker(self) -> list[Run]:
        """Find in-flight runs that have a worker assigned."""
        stmt = select(Run).where(
            Run.status.in_(_IN_FLIGHT_STATUS_ENUMS),
            Run.worker_id.isnot(None),
            Run.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_past_pipeline_deadline(
        self,
        statuses: Collection[RunStatusEnum | str | PyEnum],
        buffer_seconds: int = 120,
    ) -> list[Run]:
        """Find runs exceeding their pipeline timeout."""
        stmt = (
            select(Run)
            .join(Pipeline, Pipeline.id == Run.pipeline_id)
            .where(
                Run.status.in_(run_status_enums(statuses)),
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
