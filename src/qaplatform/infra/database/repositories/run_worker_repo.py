from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Collection
from uuid import UUID

from sqlalchemy import select, update

from qaplatform.domain.services.execution import (
    CANCELABLE_STATUSES,
    FINISHABLE_STATUSES,
)
from qaplatform.infra.database.models import Run, RunStatusEnum
from qaplatform.infra.database.repositories.run_status_helpers import (
    coerce_run_status_enum,
    run_status_enums,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunWorkerRepositoryMixin:
    _FINISH_EXPECTED = run_status_enums(FINISHABLE_STATUSES)
    _FAIL_EXPECTED = run_status_enums(CANCELABLE_STATUSES)
    _CANCEL_EXPECTED = run_status_enums(CANCELABLE_STATUSES)

    @staticmethod
    def _coerce_status(status: RunStatusEnum | str | PyEnum) -> RunStatusEnum:
        return coerce_run_status_enum(status)

    @classmethod
    def _expected_statuses(
        cls,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None,
        default: frozenset[RunStatusEnum],
    ) -> frozenset[RunStatusEnum]:
        if expected_in is None:
            return default
        return run_status_enums(expected_in)

    async def claim_for_worker(self, run_id: UUID, worker_id: str) -> Run | None:
        """Atomically claim a queued run for a worker. Returns the run or None if already claimed."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatusEnum.QUEUED,
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.PREPARING,
                worker_id=worker_id,
                status_updated_at=now,
                updated_at=now,
            )
            .returning(Run)
        )
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        if run:
            await self.session.flush()
            await self.session.refresh(run)
        return run

    async def set_retry_group_id(self, run_id: UUID | str, group_id: UUID | str) -> None:
        """Set retry_group_id for a run (typically to its own id)."""
        stmt = (
            update(Run)
            .where(Run.id == run_id, Run.deleted_at.is_(None))
            .values(retry_group_id=group_id, updated_at=_utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def finish_if_current(
        self,
        run_id: UUID,
        *,
        status: RunStatusEnum | str | PyEnum,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None = None,
        summary: dict | None = None,
    ) -> bool:
        """Set terminal status only if current status matches expected set."""
        now = _utcnow()
        values: dict = {
            "status": self._coerce_status(status),
            "finished_at": now,
            "status_updated_at": now,
            "updated_at": now,
        }
        if summary is not None:
            values["summary"] = summary
        expected = self._expected_statuses(expected_in, self._FINISH_EXPECTED)
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected),
                Run.deleted_at.is_(None),
            )
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def fail_if_current(
        self,
        run_id: UUID,
        *,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None = None,
        message: str | None = None,
    ) -> bool:
        """Mark run as failed only if current status matches."""
        now = _utcnow()
        values: dict = {
            "status": RunStatusEnum.FAILED,
            "finished_at": now,
            "error_message": message,
            "status_updated_at": now,
            "updated_at": now,
        }
        expected = self._expected_statuses(expected_in, self._FAIL_EXPECTED)
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected),
                Run.deleted_at.is_(None),
            )
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def cancel_if_current(
        self,
        run_id: UUID,
        *,
        expected_in: Collection[RunStatusEnum | str | PyEnum] | None = None,
    ) -> bool:
        """Cancel run only if current status matches."""
        now = _utcnow()
        expected = self._expected_statuses(expected_in, self._CANCEL_EXPECTED)
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected),
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.CANCELLED,
                finished_at=now,
                status_updated_at=now,
                updated_at=now,
                cancel_requested_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def timeout_if_current(
        self,
        run_id: UUID,
        *,
        expected_in: Collection[RunStatusEnum | str | PyEnum],
    ) -> bool:
        """Mark run as timeout only if current status matches."""
        now = _utcnow()
        expected = self._expected_statuses(expected_in, frozenset())
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(expected),
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.TIMEOUT,
                finished_at=now,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def mark_running(self, run_id: UUID) -> bool:
        """Set PREPARING -> RUNNING. Returns True if the row was updated."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatusEnum.PREPARING,
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.RUNNING,
                started_at=now,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def mark_collecting(self, run_id: UUID) -> bool:
        """Set RUNNING -> COLLECTING. Returns True if the row was updated."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatusEnum.RUNNING,
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.COLLECTING,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def is_cancel_requested(self, run_id: UUID) -> bool:
        """Has cancel been requested for this run?"""
        stmt = select(Run.cancel_requested_at).where(
            Run.id == run_id,
            Run.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        value = result.scalar_one_or_none()
        return value is not None

    async def release_worker(self, run_id: UUID, worker_id: str) -> None:
        """Clear worker_id after run completes (best-effort)."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.worker_id == worker_id,
                Run.deleted_at.is_(None),
            )
            .values(worker_id=None, updated_at=now)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_worker_lost(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        message: str,
    ) -> bool:
        """Mark a non-terminal run as failed because its worker heartbeat expired."""
        now = _utcnow()
        stmt = (
            update(Run)
            .where(
                Run.id == run_id,
                Run.worker_id == worker_id,
                Run.status.in_(self._FAIL_EXPECTED),
                Run.deleted_at.is_(None),
            )
            .values(
                status=RunStatusEnum.FAILED,
                finished_at=now,
                error_message=message,
                worker_id=None,
                status_updated_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0
