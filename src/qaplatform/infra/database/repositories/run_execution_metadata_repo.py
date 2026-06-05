from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import update

from qaplatform.infra.database.models import Run


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunExecutionMetadataRepositoryMixin:
    async def update_git_sha(self, run_id: UUID, sha: str) -> None:
        """Write the resolved git commit SHA back to the run record."""
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(git_sha=sha, updated_at=_utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_execution_id(self, run_id: UUID, execution_id: str) -> None:
        """Write the container execution ID to the run record."""
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(execution_id=execution_id, updated_at=_utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()
