from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Artifact, Run
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

    async def get_with_run(self, artifact_id: UUID) -> tuple[Artifact, Run] | None:
        """Fetch artifact joined with its run, or None if not found.

        Returns an (Artifact, Run) tuple. The caller is responsible for any
        tenant or ownership verification.
        """
        stmt = (
            select(Artifact, Run)
            .join(Run, Artifact.run_id == Run.id)
            .where(
                Artifact.id == artifact_id,
                Artifact.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        row = result.first()
        return row if row is not None else None

    async def get_for_run(self, id: UUID, run_id: UUID) -> Artifact | None:
        """Fetch artifact by ID, scoped to a run.

        Returns None when the artifact does not exist OR exists in another run.
        Since Artifact has no tenant_id, we verify via run_id relationship.
        The caller must verify run ownership separately.
        """
        stmt = select(Artifact).where(
            Artifact.id == id,
            Artifact.run_id == run_id,
            Artifact.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
