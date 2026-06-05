from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Artifact
from qaplatform.infra.database.repositories.base import BaseRepository


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
