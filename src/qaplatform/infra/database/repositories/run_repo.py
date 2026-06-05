"""Run repository with conditional status updates."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Any, Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.domain.services.execution import ACTIVE_STATUSES
from qaplatform.infra.database.models import (
    Run,
    RunStatusEnum,
)
from qaplatform.infra.database.repositories.artifact_repo import ArtifactRepository
from qaplatform.infra.database.repositories.base import BaseRepository
from qaplatform.infra.database.repositories.run_execution_metadata_repo import (
    RunExecutionMetadataRepositoryMixin,
)
from qaplatform.infra.database.repositories.run_analytics_repo import (
    RunAnalyticsRepositoryMixin,
)
from qaplatform.infra.database.repositories.run_maintenance_repo import (
    RunMaintenanceRepositoryMixin,
)
from qaplatform.infra.database.repositories.run_reclaim_repo import (
    RunReclaimRepositoryMixin,
)
from qaplatform.infra.database.repositories.run_scheduler_repo import (
    RunSchedulerRepositoryMixin,
)
from qaplatform.infra.database.repositories.run_status_helpers import (
    coerce_run_status_enum,
    run_status_enums,
)
from qaplatform.infra.database.repositories.run_worker_repo import (
    RunWorkerRepositoryMixin,
)
from qaplatform.infra.database.repositories.test_result_repo import TestResultRepository


class RunRepository(
    RunExecutionMetadataRepositoryMixin,
    RunMaintenanceRepositoryMixin,
    RunReclaimRepositoryMixin,
    RunWorkerRepositoryMixin,
    RunSchedulerRepositoryMixin,
    RunAnalyticsRepositoryMixin,
    BaseRepository[Run],
):
    model = Run
    _DEDUP_ACTIVE_STATUSES = run_status_enums(ACTIVE_STATUSES)

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

    async def list_filtered_for_tenant(
        self,
        *,
        tenant_id: UUID,
        offset: int = 0,
        limit: int = 20,
        statuses: Collection[RunStatusEnum | str | PyEnum] | None = None,
        project_ids: Collection[UUID] | None = None,
        pipeline_id: UUID | None = None,
        git_ref: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort: str = "-created_at",
    ) -> tuple[list[Run], int]:
        filters: list[Any] = [Run.tenant_id == tenant_id]

        if statuses:
            coerced_statuses = [coerce_run_status_enum(status) for status in statuses]
            if len(coerced_statuses) == 1:
                filters.append(Run.status == coerced_statuses[0])
            else:
                filters.append(Run.status.in_(coerced_statuses))

        if project_ids is not None:
            project_id_list = list(project_ids)
            if not project_id_list:
                return [], 0
            if len(project_id_list) == 1:
                filters.append(Run.project_id == project_id_list[0])
            else:
                filters.append(Run.project_id.in_(project_id_list))

        if pipeline_id is not None:
            filters.append(Run.pipeline_id == pipeline_id)
        if git_ref is not None:
            filters.append(Run.git_ref == git_ref)
        if created_from is not None:
            filters.append(Run.created_at >= created_from)
        if created_to is not None:
            filters.append(Run.created_at <= created_to)

        order_by = Run.created_at.desc() if sort == "-created_at" else Run.created_at
        items, total = await self.list(
            offset=offset,
            limit=limit,
            order_by=order_by,
            filters=filters,
        )
        return list(items), total

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

__all__ = ["RunRepository", "TestResultRepository", "ArtifactRepository"]
