"""Project, Environment, Pipeline, and Credential repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import (
    Credential,
    Environment,
    Pipeline,
    Project,
)
from qaplatform.infra.database.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_slug(self, tenant_id: UUID, slug: str) -> Project | None:
        stmt = select(Project).where(
            Project.tenant_id == tenant_id,
            Project.slug == slug,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_tenant(
        self, tenant_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Project], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Project.tenant_id == tenant_id],
        )


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
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


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

    async def list_active_by_project(self, project_id: UUID) -> list[Pipeline]:
        stmt = select(Pipeline).where(
            Pipeline.project_id == project_id,
            Pipeline.enabled.is_(True),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CredentialRepository(BaseRepository[Credential]):
    model = Credential

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_project(
        self, project_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Credential], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Credential.project_id == project_id],
        )

    async def get_by_name(self, project_id: UUID, name: str) -> Credential | None:
        stmt = select(Credential).where(
            Credential.project_id == project_id,
            Credential.name == name,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
