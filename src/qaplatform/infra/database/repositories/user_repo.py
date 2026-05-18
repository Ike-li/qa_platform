"""User and ApiToken repositories."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import ApiToken, AppUser
from qaplatform.infra.database.repositories.base import BaseRepository


class UserRepository(BaseRepository[AppUser]):
    model = AppUser

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_username(self, tenant_id: UUID, username: str) -> AppUser | None:
        stmt = select(AppUser).where(
            AppUser.tenant_id == tenant_id,
            AppUser.username == username,
            AppUser.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, tenant_id: UUID, email: str) -> AppUser | None:
        stmt = select(AppUser).where(
            AppUser.tenant_id == tenant_id,
            AppUser.email == email,
            AppUser.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_tenant(
        self, tenant_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[AppUser], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[AppUser.tenant_id == tenant_id],
        )

    async def update_last_login(self, user: AppUser, at: datetime) -> AppUser:
        return await self.update(user, last_login_at=at)


class ApiTokenRepository(BaseRepository[ApiToken]):
    model = ApiToken

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_token_id(self, token_id: str) -> ApiToken | None:
        stmt = select(ApiToken).where(
            ApiToken.token_id == token_id,
            ApiToken.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[ApiToken], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            filters=[ApiToken.user_id == user_id],
        )

    async def revoke(self, token: ApiToken) -> ApiToken:
        return await self.update(token, is_revoked=True)

    async def update_last_used(self, token: ApiToken, at: datetime, ip: str | None = None) -> ApiToken:
        kwargs: dict = {"last_used_at": at}
        if ip:
            kwargs["last_used_ip"] = ip
        return await self.update(token, **kwargs)
