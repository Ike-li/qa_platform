"""Environment repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Environment
from qaplatform.infra.database.repositories.base import BaseRepository


class EnvironmentRepository(BaseRepository[Environment]):
    model = Environment

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_project(
        self, project_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Environment], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Environment.project_id == project_id],
        )

    async def get_by_name(self, project_id: UUID, name: str) -> Environment | None:
        stmt = select(Environment).where(
            Environment.project_id == project_id,
            Environment.name == name,
            Environment.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
