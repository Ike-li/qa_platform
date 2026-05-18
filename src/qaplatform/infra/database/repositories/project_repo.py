"""Project, Environment, Pipeline, Credential, and Schedule repositories."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import (
    Credential,
    Environment,
    Pipeline,
    Project,
    Schedule,
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
            Pipeline.deleted_at.is_(None),
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
            Credential.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ScheduleRepository(BaseRepository[Schedule]):
    model = Schedule

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_project(
        self, project_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Schedule], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[Schedule.project_id == project_id],
        )

    async def find_due_schedules(self, now: datetime, *, limit: int = 50) -> list[Schedule]:
        """Find enabled schedules where next_run_at <= now."""
        stmt = (
            select(Schedule)
            .where(
                Schedule.enabled.is_(True),
                Schedule.next_run_at <= now,
            )
            .order_by(Schedule.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_after_fire(
        self,
        schedule_id: UUID,
        *,
        last_run_at: datetime,
        next_run_at: datetime | None,
        last_error: str | None = None,
    ) -> None:
        """Update schedule timestamps after a fire event."""
        schedule = await self.get_by_id(schedule_id)
        if schedule is None:
            return
        schedule.last_run_at = last_run_at
        schedule.next_run_at = next_run_at
        schedule.last_error = last_error
