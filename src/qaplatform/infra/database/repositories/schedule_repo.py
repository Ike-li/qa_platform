"""Schedule repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Schedule
from qaplatform.infra.database.repositories.base import BaseRepository


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
                Schedule.deleted_at.is_(None),
                Schedule.next_run_at <= now,
            )
            .order_by(Schedule.next_run_at)
            .limit(limit)
            .with_for_update(of=Schedule, skip_locked=True)
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
        expected_next_run_at: datetime | None = None,
    ) -> bool:
        """推进 schedule 的时间戳，返回是否写入成功。

        传 ``expected_next_run_at`` 时变成条件 UPDATE，只有 next_run_at 仍等于
        该值才写入——用它把「抢占这个触发槽」做成原子操作。

        为什么需要：find_due_schedules 用了 FOR UPDATE SKIP LOCKED，但
        fire_due_schedules 在循环体内部 commit，第一次 commit 就结束事务、
        释放了这批里剩余所有行的锁。而 compose 里 worker / worker-high /
        worker-low 三个服务加载同一份 WorkerSettings，都在跑
        cron(check_schedules)，晚几百毫秒的那个会重新捞到并重复触发。

        不传该参数时保持原来的无条件语义，供错误路径（pipeline 缺失、project
        缺失、异常兜底）继续使用。
        """
        stmt = (
            sa_update(Schedule)
            .where(Schedule.id == schedule_id)
            .values(
                last_run_at=last_run_at,
                next_run_at=next_run_at,
                last_error=last_error,
            )
            .execution_options(synchronize_session=False)
        )
        if expected_next_run_at is not None:
            stmt = stmt.where(Schedule.next_run_at == expected_next_run_at)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return bool(result.rowcount)
