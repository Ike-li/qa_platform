"""Admin-only endpoints: system status dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from qaplatform.api.deps import (
    UserIdentity,
    _get_repos,
    get_current_user,
)
from qaplatform.dependencies import RepositoryBundle
from qaplatform.infra.database.models import RunStatusEnum


class SystemStatusResponse(BaseModel):
    queue_depth: int
    in_flight: int
    success_rate_1h: float
    total_runs_1h: int


ADMIN_FORBIDDEN_RESPONSE = {
    "description": "Platform admin role is required",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
                "required": ["detail"],
            }
        }
    },
}


router = APIRouter(prefix="/admin", tags=["admin"])


async def _require_platform_admin(
    user: UserIdentity = Depends(get_current_user),
) -> UserIdentity:
    """Dependency that rejects non-platform-admin callers with 403."""
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admin required")
    return user


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    responses={403: ADMIN_FORBIDDEN_RESPONSE},
)
async def system_status(
    _user: UserIdentity = Depends(_require_platform_admin),
    repos: RepositoryBundle = Depends(_get_repos),
):
    """Return system-level queue / in-flight / success-rate metrics."""
    queue_depth = await repos.run.count_by_statuses(
        [RunStatusEnum.QUEUED, RunStatusEnum.PREPARING],
    )
    in_flight = await repos.run.count_by_statuses(
        [RunStatusEnum.RUNNING, RunStatusEnum.COLLECTING],
    )
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    total = await repos.run.count_finished_since_by_statuses(
        since=one_hour_ago,
        statuses=[
            RunStatusEnum.DONE,
            RunStatusEnum.FAILED,
            RunStatusEnum.CANCELLED,
            RunStatusEnum.TIMEOUT,
        ],
    )
    passed = await repos.run.count_finished_since_by_statuses(
        since=one_hour_ago,
        statuses=[RunStatusEnum.DONE],
    )

    return {
        "queue_depth": queue_depth,
        "in_flight": in_flight,
        "success_rate_1h": round(passed / total, 4) if total > 0 else 1.0,
        "total_runs_1h": total,
    }
