"""Pipeline repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Pipeline
from qaplatform.infra.database.repositories.base import BaseRepository


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

    async def get_latest_enabled(self, project_id: UUID) -> Pipeline | None:
        """取该项目最新的启用中 pipeline。

        供自动触发路径（webhook）挑选 pipeline 用，不能复用 list_by_project：
        后者不看 enabled，而外部结果导入会建一个名为 external-import 的占位
        pipeline 并显式置为 enabled=False。只要用过一次导入，占位 pipeline
        就是最新的那个，此后所有 webhook 都会挂到它身上。

        pipeline 列表接口仍走 list_by_project——那里需要把禁用的也显示出来。
        """
        stmt = (
            select(Pipeline)
            .where(
                Pipeline.project_id == project_id,
                Pipeline.enabled.is_(True),
                Pipeline.deleted_at.is_(None),
            )
            .order_by(Pipeline.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_name(self, project_id: UUID, name: str) -> Pipeline | None:
        stmt = select(Pipeline).where(
            Pipeline.project_id == project_id,
            Pipeline.name == name,
            Pipeline.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_by_project(self, project_id: UUID) -> list[Pipeline]:
        stmt = select(Pipeline).where(
            Pipeline.project_id == project_id,
            Pipeline.enabled.is_(True),
            Pipeline.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
