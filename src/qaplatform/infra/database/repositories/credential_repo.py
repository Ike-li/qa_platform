"""Credential repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Credential
from qaplatform.infra.database.repositories.base import BaseRepository


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
            Credential.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_project_tenant(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Credential], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[
                Credential.project_id == project_id,
                Credential.tenant_id == tenant_id,
            ],
        )

    async def get_by_project_tenant(
        self, credential_id: UUID, project_id: UUID, tenant_id: UUID
    ) -> Credential | None:
        stmt = select(Credential).where(
            Credential.id == credential_id,
            Credential.project_id == project_id,
            Credential.tenant_id == tenant_id,
            Credential.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_name_exists(self, project_id: UUID, name: str) -> bool:
        stmt = select(Credential.id).where(
            Credential.project_id == project_id,
            Credential.name == name,
            Credential.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
