from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.auth.middleware import (
    get_current_user as _mw_get_current_user,
)
from qaplatform.api.auth.permissions import (
    PROJECT_SCOPED_ACTIONS,
    Action,
    PermissionContext,
    ProjectRole,
    Role,
    check_permission,
    normalize_tenant_role,
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
    is_platform_admin: bool = False


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
        is_platform_admin=getattr(mw_user, "is_platform_admin", False),
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
        is_platform_admin=getattr(mw_user, "is_platform_admin", False),
    )


# ── Type aliases for route signatures ────────────────────────────────────────

Container = Annotated[Any, Depends(lambda r: r.app.state.container)]
Repos = Annotated[RepositoryBundle, Depends(_get_repos)]
RedisClient = Annotated[object, Depends(get_redis)]
CurrentUser = Annotated[UserIdentity, Depends(get_current_user)]


def require_permission(action: "Action"):
    """FastAPI dependency factory that enforces tenant-level RBAC for ``action``.

    Use :func:`require_project_permission` when ``action`` is project-scoped
    and the request carries a ``project_id`` (path or body). Tenant-only check
    keeps backward-compatible behaviour for endpoints without a project
    context (e.g. ``project.create``, account-scoped tokens).
    """
    from qaplatform.api.auth.permissions import Action, PermissionContext, check_permission

    def _check(user: CurrentUser):
        ctx = PermissionContext(
            user_id=str(user.user_id),
            role=user.role,
            tenant_id=str(user.tenant_id),
            is_platform_admin=getattr(user, "is_platform_admin", False),
        )
        if not check_permission(ctx, action):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return Depends(_check)


# ── Project-scoped permission enforcement ────────────────────────────────────

async def _resolve_project_role(
    session: AsyncSession,
    user: "UserIdentity",
    project_id: UUID,
) -> ProjectRole | None:
    """Look up the caller's project-level role.

    Returns ``None`` when no ``project_member`` row exists; tenant Owner/Admin
    bypass is applied at the :func:`check_permission` level so this stays
    purely a fact lookup.
    """
    from qaplatform.infra.database.models import ProjectMember

    stmt = select(ProjectMember.role).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.user_id,
        ProjectMember.tenant_id == user.tenant_id,
        ProjectMember.deleted_at.is_(None),
    )
    raw = (await session.execute(stmt)).scalar_one_or_none()
    if raw is None:
        return None
    try:
        return ProjectRole(raw)
    except ValueError:
        return None


def require_project_permission(action: Action, *, project_id_param: str = "project_id"):
    """FastAPI dependency factory that enforces tenant ∩ project RBAC.

    The dependency reads ``project_id`` from path parameters via FastAPI's
    request scope, looks up the caller's :class:`ProjectRole`, and runs
    :func:`check_permission` with the intersection semantics. Tenant
    Owner/Admin bypass the project-level check inside their own tenant.
    """
    if action not in PROJECT_SCOPED_ACTIONS:
        raise ValueError(
            f"require_project_permission used for non-project-scoped action: {action}"
        )

    async def _check(
        request: Request,
        user: CurrentUser,
        session: AsyncSession = Depends(_get_db_session),
    ):
        raw_project_id = request.path_params.get(project_id_param)
        if raw_project_id is None:
            raise HTTPException(
                status_code=500,
                detail=f"project_id missing from path; expected '{project_id_param}'",
            )
        try:
            project_id = UUID(str(raw_project_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid project_id")

        tenant_role = normalize_tenant_role(user.role)
        project_role: ProjectRole | None = None
        if not getattr(user, "is_platform_admin", False) and tenant_role not in (Role.OWNER, Role.ADMIN):
            project_role = await _resolve_project_role(session, user, project_id)

        ctx = PermissionContext(
            user_id=str(user.user_id),
            role=user.role,
            tenant_id=str(user.tenant_id),
            project_id=str(project_id),
            project_role=project_role,
            is_platform_admin=getattr(user, "is_platform_admin", False),
        )
        if not check_permission(ctx, action):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return Depends(_check)


async def enforce_project_action(
    session: AsyncSession,
    user: "UserIdentity",
    project_id: UUID,
    action: Action,
    *,
    is_own_resource: bool = False,
) -> None:
    """Enforce a project-scoped action when ``project_id`` is only known
    after a body/path lookup (e.g. trigger_run -> pipeline -> project).

    Tenant Owner/Admin bypass project-membership lookup. All other roles
    require a matching :class:`ProjectMember` row to authorise the action.
    """
    if action not in PROJECT_SCOPED_ACTIONS:
        raise ValueError(
            f"enforce_project_action used for non-project-scoped action: {action}"
        )

    tenant_role = normalize_tenant_role(user.role)
    project_role: ProjectRole | None = None
    if not getattr(user, "is_platform_admin", False) and tenant_role not in (Role.OWNER, Role.ADMIN):
        project_role = await _resolve_project_role(session, user, project_id)

    ctx = PermissionContext(
        user_id=str(user.user_id),
        role=user.role,
        tenant_id=str(user.tenant_id),
        project_id=str(project_id),
        project_role=project_role,
        is_own_resource=is_own_resource,
        is_platform_admin=getattr(user, "is_platform_admin", False),
    )
    if not check_permission(ctx, action):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
