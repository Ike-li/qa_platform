from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from qaplatform.domain.models.project import SilentWindow


class ScheduleSkippedSilentWindowAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    schedule_id: UUID
    window: SilentWindow


def silent_windows_from_settings(settings: dict | None) -> list[SilentWindow]:
    raw_windows = (settings or {}).get("silent_windows", [])
    if not isinstance(raw_windows, list):
        return []
    return [SilentWindow.model_validate(window) for window in raw_windows]


def is_in_silent_window(
    windows: list[SilentWindow],
    now: datetime,
) -> SilentWindow | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return next((window for window in windows if window.start_at <= now <= window.end_at), None)
