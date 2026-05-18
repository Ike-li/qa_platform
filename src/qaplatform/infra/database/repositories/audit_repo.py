"""Audit event repository (audit schema)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import AuditEvent


class AuditEventRepository:
    """Repository for audit events in the audit schema."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: UUID | None,
        user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        before_state: dict | None = None,
        after_state: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_state=before_state,
            after_state=after_state,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def list_by_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditEvent], int]:
        filters = [
            AuditEvent.resource_type == resource_type,
            AuditEvent.resource_id == resource_id,
        ]
        return await self._list(offset=offset, limit=limit, filters=filters)

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditEvent], int]:
        return await self._list(
            offset=offset, limit=limit, filters=[AuditEvent.user_id == user_id]
        )

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditEvent], int]:
        return await self._list(
            offset=offset, limit=limit, filters=[AuditEvent.tenant_id == tenant_id]
        )

    async def _list(
        self,
        *,
        offset: int,
        limit: int,
        filters: list,
    ) -> tuple[list[AuditEvent], int]:
        stmt = select(AuditEvent)
        count_stmt = select(func.count()).select_from(AuditEvent)
        for f in filters:
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)

        stmt = stmt.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)

        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        return items, total
