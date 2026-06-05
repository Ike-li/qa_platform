from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import UserIdentity, enforce_project_action
from qaplatform.infra.database.models import Run as RunORM

ProjectActionEnforcer = Callable[..., Awaitable[None]]


async def enforce_run_action(
    *,
    session: AsyncSession,
    user: UserIdentity,
    run: RunORM,
    action: Action,
    allow_own_resource: bool = False,
    enforce_action: ProjectActionEnforcer = enforce_project_action,
) -> None:
    kwargs: dict[str, bool] = {}
    if allow_own_resource:
        kwargs["is_own_resource"] = str(run.triggered_by) == str(user.user_id)

    await enforce_action(
        session,
        user,
        run.project_id,
        action,
        **kwargs,
    )


async def get_run_for_action(
    *,
    repos: Any,
    session: AsyncSession,
    user: UserIdentity,
    run_id: UUID,
    action: Action,
    allow_own_resource: bool = False,
    enforce_action: ProjectActionEnforcer = enforce_project_action,
) -> RunORM:
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    await enforce_run_action(
        session=session,
        user=user,
        run=run,
        action=action,
        allow_own_resource=allow_own_resource,
        enforce_action=enforce_action,
    )
    return run
