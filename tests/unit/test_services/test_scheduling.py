from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from qaplatform.domain.services.scheduling import (
    SchedulingService,
    compute_next_run_at,
    should_fire,
)


def _schedule(**overrides):
    defaults = {
        "project_id": uuid4(),
        "pipeline_id": uuid4(),
        "enabled": True,
        "next_run_at": datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        "quiet_windows": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_compute_next_run_at_uses_schedule_timezone_for_naive_base():
    result = compute_next_run_at(
        "0 9 * * *",
        "Asia/Shanghai",
        base_time=datetime(2026, 6, 1, 8, 30),
    )

    assert result == datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_compute_next_run_at_converts_aware_base_to_schedule_timezone():
    result = compute_next_run_at(
        "0 9 * * *",
        "Asia/Shanghai",
        base_time=datetime(2026, 6, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert result == datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_should_fire_rejects_disabled_missing_or_future_schedule():
    now = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)

    assert should_fire(_schedule(enabled=False), now) is False
    assert should_fire(_schedule(next_run_at=None), now) is False
    assert should_fire(
        _schedule(next_run_at=datetime(2026, 6, 1, 9, 1, tzinfo=timezone.utc)),
        now,
    ) is False


def test_should_fire_allows_due_schedule_without_quiet_window():
    now = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)

    assert should_fire(_schedule(next_run_at=now), now) is True


def test_should_fire_blocks_inside_same_day_quiet_window():
    now = datetime(2026, 6, 1, 1, 30, tzinfo=timezone.utc)  # 09:30 Asia/Shanghai
    schedule = _schedule(
        next_run_at=now,
        quiet_windows=[
            {"timezone": "Asia/Shanghai", "start": "09:00", "end": "10:00"}
        ],
    )

    assert should_fire(schedule, now) is False


def test_should_fire_blocks_inside_midnight_wrapping_quiet_window():
    now = datetime(2026, 6, 1, 16, 30, tzinfo=timezone.utc)  # 00:30 Asia/Shanghai
    schedule = _schedule(
        next_run_at=now,
        quiet_windows=[
            {"timezone": "Asia/Shanghai", "start": "23:00", "end": "01:00"}
        ],
    )

    assert should_fire(schedule, now) is False


def test_should_fire_allows_outside_quiet_windows():
    now = datetime(2026, 6, 1, 4, 0, tzinfo=timezone.utc)  # 12:00 Asia/Shanghai
    schedule = _schedule(
        next_run_at=now,
        quiet_windows=[
            {"timezone": "Asia/Shanghai", "start": "09:00", "end": "10:00"},
            {"timezone": "Asia/Shanghai", "start": "23:00", "end": "01:00"},
        ],
    )

    assert should_fire(schedule, now) is True


def test_create_scheduled_run_uses_schedule_ids_and_trigger_type():
    project_id = uuid4()
    pipeline_id = uuid4()

    result = SchedulingService().create_scheduled_run(
        _schedule(project_id=project_id, pipeline_id=pipeline_id)
    )

    assert result == {
        "project_id": project_id,
        "pipeline_id": pipeline_id,
        "trigger_type": "schedule",
        "git_ref": "main",
    }
