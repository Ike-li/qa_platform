"""Generic async CRUD base repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, Sequence, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Base async repository with generic CRUD operations."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- soft-delete helpers ----

    @staticmethod
    def _is_soft_deletable(model: type) -> bool:
        return getattr(model, "__soft_deletable__", True)

    def _soft_delete_filter(self) -> list:
        """Return [deleted_at IS None] filter if the model supports soft-delete."""
        if self._is_soft_deletable(self.model):
            return [self.model.deleted_at.is_(None)]
        return []

    # ---- CRUD ----

    async def create(self, **kwargs) -> ModelT:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_id(self, id: UUID) -> ModelT | None:
        stmt = select(self.model).where(self.model.id == id)
        for f in self._soft_delete_filter():
            stmt = stmt.where(f)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_tenant(self, id: UUID, tenant_id: UUID) -> ModelT | None:
        """Fetch by primary key, scoped to a tenant.

        Returns None when the row does not exist OR exists in another tenant —
        the API layer maps both to 404 to avoid leaking existence across
        tenants. Models without a ``tenant_id`` column must use a join-based
        repo method (e.g. Artifact via Run.tenant_id) and not call this.
        """
        if not hasattr(self.model, "tenant_id"):
            raise TypeError(
                f"{self.model.__name__} has no tenant_id column; "
                "use a join-based lookup instead of get_for_tenant"
            )
        stmt = select(self.model).where(
            self.model.id == id,  # type: ignore[attr-defined]
            self.model.tenant_id == tenant_id,  # type: ignore[attr-defined]
        )
        for f in self._soft_delete_filter():
            stmt = stmt.where(f)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by=None,
        filters: list | None = None,
    ) -> tuple[Sequence[ModelT], int]:
        stmt = select(self.model)
        count_stmt = select(func.count()).select_from(self.model)

        for f in self._soft_delete_filter():
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)

        if filters:
            for f in filters:
                stmt = stmt.where(f)
                count_stmt = count_stmt.where(f)

        if order_by is not None:
            stmt = stmt.order_by(order_by)
        else:
            stmt = stmt.order_by(self.model.created_at.desc())  # type: ignore[attr-defined]

        stmt = stmt.offset(offset).limit(limit)

        result = await self.session.execute(stmt)
        items = result.scalars().all()

        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        return items, total

    async def update(self, instance: ModelT, **kwargs) -> ModelT:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        if self._is_soft_deletable(self.model):
            instance.deleted_at = datetime.now(timezone.utc)
            await self.session.flush()
        else:
            await self.session.delete(instance)
            await self.session.flush()

    async def commit(self) -> None:
        """Commit the current transaction. Use to release row locks mid-task."""
        await self.session.commit()
