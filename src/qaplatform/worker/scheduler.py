from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import IntEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import redis.asyncio as redis

if TYPE_CHECKING:
    from arq.connections import ArqRedis

log = logging.getLogger(__name__)


class Priority(IntEnum):
    """Queue priority levels mapped from trigger types."""

    HIGH = 0    # manual triggers
    MEDIUM = 1  # webhook / api / event triggers
    LOW = 2     # schedule triggers


PRIORITY_QUEUES: dict[Priority, str] = {
    Priority.HIGH: "queue:high",
    Priority.MEDIUM: "queue:medium",
    Priority.LOW: "queue:low",
}

TRIGGER_PRIORITY: dict[str, Priority] = {
    "manual": Priority.MEDIUM,
    "webhook": Priority.MEDIUM,
    "api": Priority.MEDIUM,
    "event": Priority.MEDIUM,
    "schedule": Priority.MEDIUM,
}


class FairScheduler:
    """Fair scheduler (enqueue-side): prevents a single project from monopolizing workers.

    Strategy:
    1. Map trigger type to priority -> write to corresponding queue
    2. Per-priority per-project quota limiting
    3. Global concurrency cap

    Runs that exceed quota stay in PostgreSQL (status=queued, enqueued_at=NULL)
    and are picked up later by try_dequeue_waiting().
    """

    def __init__(
        self,
        arq: ArqRedis,
        run_repo: Any,
        settings: Any,
    ) -> None:
        self.arq = arq
        self.run_repo = run_repo
        self.max_total = settings.max_concurrent_runs
        self.max_per_project = settings.max_concurrent_per_project

    async def enqueue(self, run: Any) -> bool:
        """Try to enqueue a run. Returns True if enqueued immediately, False if queued waiting."""
        async with self.run_repo.scheduler_lock():
            return await self._enqueue_if_capacity(run)

    async def _enqueue_if_capacity(self, run: Any) -> bool:
        """Check quotas under the scheduler lock, then enqueue or mark waiting."""
        if await self._active_or_enqueued_count() >= self.max_total:
            await self.run_repo.mark_waiting(run.id)
            return False

        if await self._project_active_or_enqueued_count(run.project_id) >= self.max_per_project:
            await self.run_repo.mark_waiting(run.id)
            return False

        return await self._enqueue_run(run)

    async def _enqueue_run(self, run: Any) -> bool:
        """Perform the actual arq enqueue and persist queue metadata."""
        priority = TRIGGER_PRIORITY.get(run.trigger_type, Priority.MEDIUM)
        queue = PRIORITY_QUEUES[priority]
        job_id = f"run:{run.id}"

        job = await self.arq.enqueue_job(
            "execute_run",
            str(run.id),
            _queue_name=queue,
            _job_id=job_id,
        )
        if job is None:
            # arq dedup: check if this is the same run idempotently re-enqueued
            existing = await self.run_repo.get_by_arq_job_id(job_id)
            if existing and existing.id == run.id and existing.enqueued_at:
                return True  # idempotent re-enqueue of the same run

            await self.run_repo.mark_waiting(
                run.id,
                reason=f"arq job id conflict: {job_id}",
            )
            return False

        await self.run_repo.mark_enqueued(
            run.id,
            queue_name=queue,
            arq_job_id=job.job_id,
            enqueued_at=datetime.now(timezone.utc),
        )
        return True

    async def _active_or_enqueued_count(self) -> int:
        """Count globally active or enqueued runs."""
        return await self.run_repo.count_active_or_enqueued()

    async def _project_active_or_enqueued_count(self, project_id: UUID) -> int:
        """Count active or enqueued runs for a specific project."""
        return await self.run_repo.count_active_or_enqueued_by_project(project_id)

    async def try_dequeue_waiting(self) -> int:
        """Periodic call (via arq cron_job): enqueue waiting runs when capacity is available.

        Uses SELECT ... FOR UPDATE SKIP LOCKED to avoid duplicate dequeuing
        across multiple workers.
        """
        dequeued = 0
        async with self.run_repo.scheduler_lock():
            waiting = await self.run_repo.find_waiting(limit=10)
            for run in waiting:
                if await self._active_or_enqueued_count() >= self.max_total:
                    break

                if await self._project_active_or_enqueued_count(run.project_id) >= self.max_per_project:
                    continue

                if await self._enqueue_run(run):
                    dequeued += 1

        return dequeued


async def enqueue_run(
    arq: ArqRedis,
    run_repo: Any,
    run: Any,
    trigger_type: str,
    settings: Any,
) -> bool:
    """Convenience function to enqueue a run through the FairScheduler."""
    scheduler = FairScheduler(arq, run_repo, settings)
    return await scheduler.enqueue(run)
