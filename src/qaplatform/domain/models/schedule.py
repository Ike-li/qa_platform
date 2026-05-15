from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuietWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: str
    end: str
    timezone: str = "Asia/Shanghai"


class Schedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    pipeline_id: UUID
    cron_expr: str
    timezone: str = "Asia/Shanghai"
    missed_fire_policy: Literal["skip", "run_once", "run_all"] = "skip"
    quiet_windows: list[QuietWindow] = Field(default_factory=list)
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
