"""Quarantine repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import TestQuarantine
from qaplatform.infra.database.repositories.base import BaseRepository


class QuarantineRepository(BaseRepository[TestQuarantine]):
    model = TestQuarantine

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def add_to_quarantine(
        self,
        project_id: UUID,
        suite: str,
        name: str,
        reason: str,
        created_by: UUID | None,
        expires_at: datetime | None = None,
    ) -> TestQuarantine:
        """Idempotent upsert. Creates or updates a quarantined test."""
        stmt = (
            insert(TestQuarantine)
            .values(
                project_id=project_id,
                suite=suite,
                name=name,
                reason=reason,
                created_by=created_by,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint="uq_test_quarantine_project_suite_name",
                set_={"reason": reason, "created_by": created_by, "expires_at": expires_at},
            )
            .returning(TestQuarantine)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one()

    async def list_by_project(
        self,
        project_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[TestQuarantine], int]:
        """Fetch paginated list of quarantined tests for a project."""
        stmt = (
            select(TestQuarantine)
            .where(TestQuarantine.project_id == project_id)
            .order_by(TestQuarantine.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = (
            select(func.count())
            .select_from(TestQuarantine)
            .where(TestQuarantine.project_id == project_id)
        )
        res = await self.session.execute(stmt)
        count_res = await self.session.execute(count_stmt)
        return list(res.scalars().all()), count_res.scalar_one()

    async def list_keys(self, project_id: UUID) -> set[tuple[str, str]]:
        """Fast lookup of all quarantined keys (suite, name) for a project."""
        stmt = select(TestQuarantine.suite, TestQuarantine.name).where(
            TestQuarantine.project_id == project_id
        )
        res = await self.session.execute(stmt)
        return {(row[0], row[1]) for row in res.all()}

    async def get_quarantine(
        self,
        project_id: UUID,
        suite: str,
        name: str,
    ) -> TestQuarantine | None:
        """Fetch a quarantined test by key."""
        stmt = select(TestQuarantine).where(
            TestQuarantine.project_id == project_id,
            TestQuarantine.suite == suite,
            TestQuarantine.name == name,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def remove_from_quarantine(
        self,
        project_id: UUID,
        suite: str,
        name: str,
    ) -> bool:
        """Remove a test from quarantine. Returns True if deleted, False otherwise."""
        stmt = select(TestQuarantine).where(
            TestQuarantine.project_id == project_id,
            TestQuarantine.suite == suite,
            TestQuarantine.name == name,
        )
        res = await self.session.execute(stmt)
        instance = res.scalar_one_or_none()
        if instance is None:
            return False
        await self.session.delete(instance)
        await self.session.flush()
        return True
