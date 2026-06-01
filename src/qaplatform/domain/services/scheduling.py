from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter


def compute_next_run_at(
    cron_expr: str,
    timezone_name: str,
    base_time: datetime | None = None,
) -> datetime:
    """Compute the next fire time for a cron expression in the given timezone."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo(timezone_name)
    base = base_time or datetime.now(tz)
    if base.tzinfo is None:
        base = base.replace(tzinfo=tz)
    else:
        base = base.astimezone(tz)
    cron = croniter(cron_expr, base)
    return cron.get_next(datetime)


def should_fire(
    schedule,
    now: datetime | None = None,
) -> bool:
    """Check whether a schedule should fire at the given time.

    Considers:
    - enabled flag
    - next_run_at <= now
    - quiet windows
    """
    if not schedule.enabled:
        return False

    now = now or datetime.now(timezone.utc)
    if schedule.next_run_at is None:
        return False
    if schedule.next_run_at > now:
        return False

    # Check quiet windows
    if schedule.quiet_windows:
        import zoneinfo

        for qw in schedule.quiet_windows:
            # JSONB loads as plain dicts, not objects — use key access.
            qw_tz = zoneinfo.ZoneInfo(qw["timezone"])
            local_now = now.astimezone(qw_tz)
            start_h, start_m = map(int, qw["start"].split(":"))
            end_h, end_m = map(int, qw["end"].split(":"))
            current_minutes = local_now.hour * 60 + local_now.minute
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m

            if start_minutes <= end_minutes:
                if start_minutes <= current_minutes <= end_minutes:
                    return False
            else:  # Wraps midnight
                if current_minutes >= start_minutes or current_minutes <= end_minutes:
                    return False

    return True


class SchedulingService:
    """Domain service for schedule management."""

    def create_scheduled_run(self, schedule) -> dict:
        """Build parameters for creating a Run from a schedule.

        Returns a dict suitable for ExecutionService.create_run().
        """
        return {
            "project_id": schedule.project_id,
            "pipeline_id": schedule.pipeline_id,
            "trigger_type": "schedule",
            "git_ref": "main",  # default; should be resolved from pipeline/project
        }
