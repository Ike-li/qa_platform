from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from qaplatform.domain.models.project import SilentWindow
from qaplatform.domain.services.schedule import is_in_silent_window


def _window(start_at: datetime, end_at: datetime, reason: str = "freeze") -> SilentWindow:
    return SilentWindow(start_at=start_at, end_at=end_at, reason=reason)


def test_is_in_silent_window_includes_start_and_end_boundaries():
    start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    window = _window(start, end)

    assert is_in_silent_window([window], start) == window
    assert is_in_silent_window([window], end) == window


def test_is_in_silent_window_handles_cross_midnight_absolute_range():
    tz = ZoneInfo("Asia/Shanghai")
    window = _window(
        datetime(2026, 6, 1, 23, 0, tzinfo=tz),
        datetime(2026, 6, 2, 2, 0, tzinfo=tz),
    )

    assert is_in_silent_window([window], datetime(2026, 6, 1, 16, 30, tzinfo=timezone.utc)) == window


def test_is_in_silent_window_compares_different_timezones():
    shanghai = ZoneInfo("Asia/Shanghai")
    new_york = ZoneInfo("America/New_York")
    window = _window(
        datetime(2026, 6, 1, 8, 0, tzinfo=shanghai),
        datetime(2026, 6, 1, 12, 0, tzinfo=shanghai),
    )

    assert is_in_silent_window([window], datetime(2026, 5, 31, 21, 0, tzinfo=new_york)) == window


def test_is_in_silent_window_rejects_naive_now():
    window = _window(
        datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        is_in_silent_window([window], datetime(2026, 6, 1, 9, 30))
