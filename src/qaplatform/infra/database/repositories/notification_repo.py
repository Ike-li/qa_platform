"""Notification rule and delivery log repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import NotificationLog, NotificationRule
from qaplatform.infra.database.repositories.base import BaseRepository


class NotificationRuleRepository(BaseRepository[NotificationRule]):
    model = NotificationRule

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_project(
        self, project_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[NotificationRule], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[NotificationRule.project_id == project_id],
        )

    async def find_enabled_by_project(self, project_id: UUID) -> list[NotificationRule]:
        """Find all enabled notification rules for a project."""
        stmt = select(NotificationRule).where(
            NotificationRule.project_id == project_id,
            NotificationRule.enabled.is_(True),
            NotificationRule.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_project(self, id: UUID, project_id: UUID) -> NotificationRule | None:
        """Fetch notification rule by ID, scoped to a project.

        Returns None when the rule does not exist OR exists in another project.
        This prevents cross-tenant information leakage through timing attacks.
        """
        stmt = select(NotificationRule).where(
            NotificationRule.id == id,
            NotificationRule.project_id == project_id,
            NotificationRule.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class NotificationLogRepository(BaseRepository[NotificationLog]):
    model = NotificationLog

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_delivery(
        self,
        *,
        run_id: UUID,
        rule_id: UUID,
        channel_type: str,
    ) -> NotificationLog | None:
        stmt = select(NotificationLog).where(
            NotificationLog.run_id == run_id,
            NotificationLog.rule_id == rule_id,
            NotificationLog.channel_type == channel_type,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_run(
        self, run_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[NotificationLog], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[NotificationLog.run_id == run_id],
            order_by=NotificationLog.sent_at.desc(),
        )
