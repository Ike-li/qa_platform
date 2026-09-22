"""Quarantine repository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
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
        # populate_existing：调用方通常先 get_quarantine 查过一次（为了审计的
        # before_state），那一行已进 identity map。没有这个选项时 RETURNING 的
        # 结果会被换成缓存里的旧实例，接口和审计的 after_state 都会拿到更新前
        # 的 reason，尽管库里已经改对了。
        res = await self.session.execute(
            stmt, execution_options={"populate_existing": True}
        )
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

    async def list_keys(
        self, project_id: UUID, *, at: datetime | None = None
    ) -> set[tuple[str, str]]:
        """取此刻仍然生效的隔离键 (suite, name)。

        三个消费方（triage 的 quarantined 标记、release-summary 的排除、通知的
        new_failed 排除）问的都是「这个用例此刻是否被隔离」，所以过期判定放在
        查询层而不是交给清理任务：否则从 expires_at 到下次清扫之间，一条已经
        过期的隔离仍会压制 release 判断里的失败。

        ``at`` 只给测试用来固定时点，生产路径一律取当前时间。不要把它接成
        run.created_at —— release-summary 回答的是「现在能不能发」，一条早已
        过期的隔离不该追溯性地遮蔽今天的判断。
        """
        moment = at or datetime.now(timezone.utc)
        stmt = select(TestQuarantine.suite, TestQuarantine.name).where(
            TestQuarantine.project_id == project_id,
            or_(
                TestQuarantine.expires_at.is_(None),
                TestQuarantine.expires_at > moment,
            ),
        )
        res = await self.session.execute(stmt)
        return {(row[0], row[1]) for row in res.all()}

    async def delete_expired(self, *, cutoff: datetime) -> int:
        """物理删除 expires_at 早于 cutoff 的隔离，返回删除行数。

        只做清扫，不承担「是否生效」的判定——那个由 list_keys 在查询层完成，
        不能依赖定时任务是否跑过。cutoff 相对当前时间留出宽限期，好让人还能
        在列表里看到「这条失效了」并决定要不要续期。
        """
        stmt = (
            sa_delete(TestQuarantine)
            .where(
                TestQuarantine.expires_at.is_not(None),
                TestQuarantine.expires_at < cutoff,
            )
            .execution_options(synchronize_session=False)
        )
        res = await self.session.execute(stmt)
        return int(res.rowcount or 0)

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
