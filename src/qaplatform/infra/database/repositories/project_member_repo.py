"""Project member repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qaplatform.infra.database.models import ProjectMember
from qaplatform.infra.database.repositories.base import BaseRepository


class ProjectMemberRepository(BaseRepository[ProjectMember]):
    model = ProjectMember

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_project_tenant(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[ProjectMember], int]:
        stmt = (
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.tenant_id == tenant_id,
                ProjectMember.deleted_at.is_(None),
            )
            .options(selectinload(ProjectMember.user))
            .order_by(ProjectMember.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.tenant_id == tenant_id,
            ProjectMember.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        count_result = await self.session.execute(count_stmt)
        return list(result.scalars().all()), count_result.scalar_one()

    async def get_by_project_user(
        self, project_id: UUID, user_id: UUID, tenant_id: UUID
    ) -> ProjectMember | None:
        stmt = (
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.tenant_id == tenant_id,
                ProjectMember.deleted_at.is_(None),
            )
            .options(selectinload(ProjectMember.user))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_existing(
        self, project_id: UUID, user_id: UUID, tenant_id: UUID
    ) -> ProjectMember | None:
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.tenant_id == tenant_id,
            ProjectMember.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_project_ids_by_user(
        self, user_id: UUID, tenant_id: UUID
    ) -> list[UUID]:
        stmt = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user_id,
            ProjectMember.tenant_id == tenant_id,
            ProjectMember.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
