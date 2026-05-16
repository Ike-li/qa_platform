from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.auth.middleware import (
    get_current_user as _mw_get_current_user,
)
from qaplatform.dependencies import RepositoryBundle


# ── Database session (request-scoped with commit/rollback) ───────────────────

async def _get_db_session(request: Request):
    """Yield a DB session with automatic commit/rollback, scoped to request."""
    container = request.app.state.container
    async with container.db_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Repository bundle (scoped to request DB session) ─────────────────────────

async def _get_repos(request: Request, session: AsyncSession = Depends(_get_db_session)):
    """Create a RepositoryBundle scoped to the request's DB session."""
    container = request.app.state.container
    return container.get_repositories(session)


# ── Redis client ─────────────────────────────────────────────────────────────

async def get_redis(request: Request):
    """Return the Redis client from the dependency container."""
    return request.app.state.container.redis_client


# ── Authentication ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserIdentity:
    """Resolved identity for the current request.

    ``user_id`` and ``tenant_id`` are stored as :class:`uuid.UUID` so route
    handlers can compare them directly with ORM foreign-key columns.
    """

    user_id: UUID
    role: str
    tenant_id: UUID


def get_container(request: Request):
    """Return the DependencyContainer from app state."""
    return request.app.state.container


async def get_current_user(
    mw_user=Depends(_mw_get_current_user),
) -> UserIdentity:
    """Authenticate request via JWT Bearer token or API token.

    Delegates to worker-2's auth middleware and normalises IDs to UUID.
    """
    return UserIdentity(
        user_id=UUID(str(mw_user.user_id)),
        role=mw_user.role,
        tenant_id=UUID(str(mw_user.tenant_id)),
    )


async def get_current_user_bearer_only(
    mw_user=Depends(_mw_get_current_user),
) -> UserIdentity:
    """Authenticate request via Bearer token only (no Cookie fallback).

    Used for SSE endpoints per security constraints.
    """
    return UserIdentity(
        user_id=UUID(str(mw_user.user_id)),
        role=mw_user.role,
        tenant_id=UUID(str(mw_user.tenant_id)),
    )


# ── Type aliases for route signatures ────────────────────────────────────────

Container = Annotated[Any, Depends(lambda r: r.app.state.container)]
Repos = Annotated[RepositoryBundle, Depends(_get_repos)]
RedisClient = Annotated[object, Depends(get_redis)]
CurrentUser = Annotated[UserIdentity, Depends(get_current_user)]


def require_permission(action: "Action"):
    """FastAPI dependency factory that enforces RBAC for a given action."""
    from qaplatform.api.auth.permissions import Action, PermissionContext, check_permission

    def _check(user: CurrentUser):
        ctx = PermissionContext(
            user_id=str(user.user_id),
            role=user.role,
            tenant_id=str(user.tenant_id),
        )
        if not check_permission(ctx, action):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return Depends(_check)
