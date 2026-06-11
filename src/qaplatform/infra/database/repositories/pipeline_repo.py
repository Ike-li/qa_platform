"""Pipeline repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Pipeline
from qaplatform.infra.database.repositories.base import BaseRepository


class PipelineRepository(BaseRepository[Pipeline]):
    model = Pipeline

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_project(
        self, project_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Pipeline], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Pipeline.project_id == project_id],
        )

    async def get_by_name(self, project_id: UUID, name: str) -> Pipeline | None:
        stmt = select(Pipeline).where(
            Pipeline.project_id == project_id,
            Pipeline.name == name,
            Pipeline.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_by_project(self, project_id: UUID) -> list[Pipeline]:
        stmt = select(Pipeline).where(
            Pipeline.project_id == project_id,
            Pipeline.enabled.is_(True),
            Pipeline.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
