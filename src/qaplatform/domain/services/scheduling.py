from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from croniter import croniter

# 正常滴答本身就有延迟：cron 每分钟第 15 秒扫描，一次触发晚几秒到几十秒是常态。
# 超过这个窗口才算真的错过，否则 skip 策略会让 schedule 永远不触发。
MISSED_FIRE_GRACE = timedelta(seconds=90)
# 单个 schedule 一次最多补跑多少个槽。小时级 cron 约等于一个班次；分钟级 cron
# 的老尾巴本来就没有补跑价值。
MAX_CATCHUP_RUNS = 10
# croniter 枚举上限，与停机时长无关的硬边界：防止「* * * * * 停机一年」把 tick
# 卡在空转里。
MAX_MISSED_SCAN = 1000


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


@dataclass(frozen=True)
class MissedFirePlan:
    """一次 tick 里对某个 schedule 的处置决定。"""

    fire_at: list[datetime]
    next_run_at: datetime
    missed_count: int
    dropped_count: int
    reason: str


def plan_missed_fires(
    *,
    cron_expr: str,
    timezone_name: str,
    scheduled_at: datetime,
    now: datetime,
    policy: str,
    grace: timedelta = MISSED_FIRE_GRACE,
    max_catchup: int = MAX_CATCHUP_RUNS,
    max_scan: int = MAX_MISSED_SCAN,
) -> MissedFirePlan:
    """决定一个到期的 schedule 这次要补跑哪些槽，以及 next_run_at 落在哪。

    纯函数，不碰 IO，``now`` 由调用方注入——否则「停机三小时后恢复」这种场景
    只能靠真实等待来测。

    为什么需要宽限窗口：cron 每分钟第 15 秒扫描，正常触发本身就晚几秒到几十秒。
    没有宽限的话任何一次正常滴答都会被判成「错过」，skip 策略下 schedule 将
    永远不触发。只有超出 grace 才算真的停机。
    """
    slots = [scheduled_at]
    cron = croniter(cron_expr, scheduled_at)
    while len(slots) <= max_scan:
        nxt = cron.get_next(datetime)
        if nxt > now:
            break
        slots.append(nxt)

    missed_count = len(slots) - 1
    # next_run_at 一律从 now 起算。只前进一格会让 schedule 始终处于 due 状态，
    # 下一个 tick 立刻又捞到它，长时间停机后会变成活锁。
    next_run_at = compute_next_run_at(cron_expr, timezone_name, now)

    if now - scheduled_at <= grace:
        # 宽限窗口内一律按准点处理，与 missed_count 无关：对 "* * * * *" 这种
        # 每分钟的 cron，延迟 60 秒就必然多出一个槽，但那仍是一次正常滴答而不是
        # 停机。只判 missed_count == 0 的话，分钟级 schedule 在 skip 策略下会被
        # 一次寻常的调度抖动打掉。
        return MissedFirePlan(
            fire_at=[slots[-1]],
            next_run_at=next_run_at,
            missed_count=missed_count,
            dropped_count=len(slots) - 1,
            reason="on_time",
        )

    if policy == "skip":
        return MissedFirePlan(
            fire_at=[],
            next_run_at=next_run_at,
            missed_count=missed_count,
            dropped_count=len(slots),
            reason="skipped_missed",
        )

    if policy == "run_all":
        fire_at = slots[-max_catchup:]
        dropped = len(slots) - len(fire_at)
        return MissedFirePlan(
            fire_at=fire_at,
            next_run_at=next_run_at,
            missed_count=missed_count,
            dropped_count=dropped,
            reason="catchup_capped" if dropped else "catchup",
        )

    # run_once，以及任何未知取值。DB 列是裸 Text 没有 CHECK 约束，未知值退化成
    # 「补跑一次」而不是「一次都不跑」——后者是更糟的失败模式（静默停止触发）。
    # 取最新的槽而非最老的：回归跑的是 HEAD，补一个几小时前的槽，clone 出来的
    # 仍是当前代码，那个槽的身份是虚构的。
    return MissedFirePlan(
        fire_at=[slots[-1]],
        next_run_at=next_run_at,
        missed_count=missed_count,
        dropped_count=len(slots) - 1,
        reason="coalesced",
    )


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
