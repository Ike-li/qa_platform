"""Repository for report share token operations."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import ReportShareToken
from qaplatform.infra.database.repositories.base import BaseRepository


class ReportShareTokenRepository(BaseRepository[ReportShareToken]):
    """Repository for managing report share tokens."""

    model = ReportShareToken

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_token(self, token: str) -> ReportShareToken | None:
        """Get a share token by its token string."""
        stmt = select(ReportShareToken).where(ReportShareToken.token == token)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_token(self, token: str) -> ReportShareToken | None:
        """Get an active (non-expired) share token."""
        now = datetime.now(timezone.utc)
        stmt = select(ReportShareToken).where(
            ReportShareToken.token == token,
            ReportShareToken.expires_at > now,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_run(self, run_id: UUID) -> list[ReportShareToken]:
        """List all share tokens for a specific run."""
        stmt = (
            select(ReportShareToken)
            .where(ReportShareToken.run_id == run_id)
            .order_by(ReportShareToken.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def increment_access_count(self, token_id: UUID) -> None:
        """Increment the access count for a token."""
        token = await self.get_by_id(token_id)
        if token:
            token.access_count += 1
            token.last_accessed_at = datetime.now(timezone.utc)
            await self.session.flush()
