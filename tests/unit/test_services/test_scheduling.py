from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


# --------------------------------------------------------------------------- #
# missed_fire_policy
# --------------------------------------------------------------------------- #


class TestPlanMissedFires:
    """错过周期的补跑策略。

    missed_fire_policy 此前落库但从不被读取：不论停机多久，恢复后都只补跑
    一次——既不是 skip 也不是 run_all，而是隐含的 run_once。
    """

    CRON = "0 * * * *"  # 每小时整点

    def _plan(self, *, scheduled_at, now, policy, **kw):
        from qaplatform.domain.services.scheduling import plan_missed_fires

        return plan_missed_fires(
            cron_expr=self.CRON,
            timezone_name="UTC",
            scheduled_at=scheduled_at,
            now=now,
            policy=policy,
            **kw,
        )

    def test_on_time_tick_fires_once_regardless_of_policy(self):
        """正常滴答必须不受策略影响。

        cron 在每分钟第 15 秒扫描，正常触发本身就晚几秒；没有宽限窗口的话
        skip 会让 schedule 永远不触发。
        """
        scheduled = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        now = scheduled + timedelta(seconds=15)
        for policy in ("skip", "run_once", "run_all"):
            plan = self._plan(scheduled_at=scheduled, now=now, policy=policy)
            assert plan.fire_at == [scheduled], policy
            assert plan.missed_count == 0, policy
            assert plan.reason == "on_time", policy

    def test_skip_drops_everything_including_the_due_slot(self):
        scheduled = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        plan = self._plan(scheduled_at=scheduled, now=now, policy="skip")
        assert plan.fire_at == []
        assert plan.missed_count == 3
        assert plan.next_run_at == datetime(2026, 6, 1, 16, 0, tzinfo=timezone.utc)

    def test_run_once_fires_the_newest_slot_not_the_oldest(self):
        """补跑取最新的槽：回归跑的是 HEAD，补一个三小时前的槽身份是虚构的。"""
        scheduled = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        plan = self._plan(scheduled_at=scheduled, now=now, policy="run_once")
        assert plan.fire_at == [datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)]
        assert plan.missed_count == 3

    def test_run_all_fires_every_missed_slot_in_order(self):
        scheduled = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        plan = self._plan(scheduled_at=scheduled, now=now, policy="run_all")
        assert plan.fire_at == [
            datetime(2026, 6, 1, h, 0, tzinfo=timezone.utc) for h in (12, 13, 14, 15)
        ]
        assert plan.dropped_count == 0

    def test_run_all_caps_catchup_and_keeps_the_newest(self):
        """停机一天的分钟级 cron 会产生上千个槽，必须封顶且保留最新的。"""
        scheduled = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 2, 0, 30, tzinfo=timezone.utc)
        plan = self._plan(
            scheduled_at=scheduled, now=now, policy="run_all", max_catchup=10
        )
        assert len(plan.fire_at) == 10
        assert plan.fire_at[-1] == datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc)
        assert plan.dropped_count == plan.missed_count + 1 - 10
        assert plan.reason == "catchup_capped"

    def test_next_run_at_always_moves_past_now(self):
        """绝不能只前进一格：那会让 schedule 一直处于 due，长停机下变成活锁。"""
        scheduled = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        for policy in ("skip", "run_once", "run_all"):
            plan = self._plan(scheduled_at=scheduled, now=now, policy=policy)
            assert plan.next_run_at > now, policy

    def test_unknown_policy_degrades_to_run_once(self):
        """DB 列是裸 Text 无 CHECK 约束；未知值退化成补跑一次而不是静默停跑。"""
        scheduled = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        plan = self._plan(scheduled_at=scheduled, now=now, policy="nonsense")
        assert plan.fire_at == [datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)]

    def test_minute_cron_tolerates_delay_within_grace_even_with_a_missed_slot(self):
        """分钟级 cron 延迟 60 秒必然多出一个槽，但那是抖动不是停机。

        只判 missed_count == 0 的话，skip 策略下一次寻常的调度延迟就会把
        schedule 打掉。
        """
        from qaplatform.domain.services.scheduling import plan_missed_fires

        scheduled = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        now = scheduled + timedelta(seconds=60)
        plan = plan_missed_fires(
            cron_expr="* * * * *",
            timezone_name="UTC",
            scheduled_at=scheduled,
            now=now,
            policy="skip",
        )
        assert plan.reason == "on_time"
        assert plan.fire_at == [datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc)]
