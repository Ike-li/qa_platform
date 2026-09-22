"""Project repository and compatibility exports for project resource repositories."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Project
from qaplatform.infra.database.repositories.base import BaseRepository
from qaplatform.infra.database.repositories.credential_repo import CredentialRepository
from qaplatform.infra.database.repositories.environment_repo import (
    EnvironmentRepository,
)
from qaplatform.infra.database.repositories.notification_repo import (
    NotificationLogRepository,
    NotificationRuleRepository,
)
from qaplatform.infra.database.repositories.pipeline_repo import PipelineRepository
from qaplatform.infra.database.repositories.project_member_repo import (
    ProjectMemberRepository,
)
from qaplatform.infra.database.repositories.schedule_repo import ScheduleRepository


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ProjectRepository(BaseRepository[Project]):
    model = Project

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_slug(self, tenant_id: UUID, slug: str) -> Project | None:
        stmt = select(Project).where(
            Project.tenant_id == tenant_id,
            Project.slug == slug,
            Project.deleted_at.is_(None),
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

    async def list_filtered_by_tenant(
        self,
        tenant_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
        status: str | None = None,
        query: str | None = None,
    ) -> tuple[list[Project], int]:
        filters = [Project.tenant_id == tenant_id]
        if status is not None:
            filters.append(Project.status == status)
        if query is not None:
            pattern = f"%{_escape_like(query)}%"
            filters.append(
                or_(
                    Project.name.ilike(pattern, escape="\\"),
                    Project.description.ilike(pattern, escape="\\"),
                    Project.slug.ilike(pattern, escape="\\"),
                    Project.git_url.ilike(pattern, escape="\\"),
                )
            )

        order_by = Project.name.asc() if query is not None else Project.created_at.asc()
        items, total = await self.list(
            offset=offset,
            limit=limit,
            filters=filters,
            order_by=order_by,
        )
        return list(items), total

    async def list_by_git_urls(self, git_urls: Collection[str]) -> list[Project]:
        candidates = {url for url in git_urls if url}
        if not candidates:
            return []
        stmt = (
            select(Project)
            .where(
                Project.git_url.in_(candidates),
                Project.deleted_at.is_(None),
            )
            .order_by(Project.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


__all__ = [
    "ProjectRepository",
    "EnvironmentRepository",
    "PipelineRepository",
    "CredentialRepository",
    "ProjectMemberRepository",
    "ScheduleRepository",
    "NotificationRuleRepository",
    "NotificationLogRepository",
]
