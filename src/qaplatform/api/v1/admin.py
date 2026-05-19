"""Admin-only endpoints: system status dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.deps import (
    UserIdentity,
    _get_db_session,
    get_current_user,
)
from qaplatform.infra.database.models import Run, RunStatusEnum

router = APIRouter(prefix="/admin", tags=["admin"])


async def _require_platform_admin(
    user: UserIdentity = Depends(get_current_user),
) -> UserIdentity:
    """Dependency that rejects non-platform-admin callers with 403."""
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admin required")
    return user


@router.get("/status")
async def system_status(
    db: AsyncSession = Depends(_get_db_session),
    _user: UserIdentity = Depends(_require_platform_admin),
):
    """Return system-level queue / in-flight / success-rate metrics."""
    # Queue depth: runs in queued/preparing status
    queue_q = select(func.count()).where(
        Run.status.in_([RunStatusEnum.QUEUED, RunStatusEnum.PREPARING]),
        Run.deleted_at.is_(None),
    )
    queue_depth = (await db.execute(queue_q)).scalar() or 0

    # In-flight: runs in running/collecting status
    flight_q = select(func.count()).where(
        Run.status.in_([RunStatusEnum.RUNNING, RunStatusEnum.COLLECTING]),
        Run.deleted_at.is_(None),
    )
    in_flight = (await db.execute(flight_q)).scalar() or 0

    # Success rate (last 1 hour)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    total_q = select(func.count()).where(
        Run.finished_at >= one_hour_ago,
        Run.status.in_([RunStatusEnum.DONE, RunStatusEnum.FAILED]),
        Run.deleted_at.is_(None),
    )
    total = (await db.execute(total_q)).scalar() or 0

    passed_q = select(func.count()).where(
        Run.finished_at >= one_hour_ago,
        Run.status == RunStatusEnum.DONE,
        Run.deleted_at.is_(None),
    )
    passed = (await db.execute(passed_q)).scalar() or 0

    return {
        "queue_depth": queue_depth,
        "in_flight": in_flight,
        "success_rate_1h": round(passed / total, 4) if total > 0 else 1.0,
        "total_runs_1h": total,
    }
