from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from qaplatform.infra.database.models import Run, RunStatusEnum


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def analytics_run_filters(
    *,
    project_id: UUID,
    cutoff: datetime,
    git_ref: str | None = None,
) -> tuple[Any, ...]:
    filters: list[Any] = [
        Run.project_id == project_id,
        Run.created_at >= cutoff,
        Run.deleted_at.is_(None),
        Run.status.in_([
            RunStatusEnum.DONE,
            RunStatusEnum.FAILED,
            RunStatusEnum.TIMEOUT,
        ]),
    ]
    if git_ref is not None:
        filters.append(Run.git_ref == git_ref)
    return tuple(filters)
