from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from qaplatform.engine import executor as executor_module
from qaplatform.engine.docker_backend import ExitResult, ResourceUsageSample
from qaplatform.engine.executor_summaries import (
    ResourceUsageTracker,
    attach_resource_usage,
    failed_tests_summary,
    resource_termination_summary,
)


def test_failed_tests_summary_keeps_first_twenty_failures():
    results = [
        SimpleNamespace(suite="suite", name=f"test_{index}", status="failed")
        for index in range(21)
    ]
    results.append(SimpleNamespace(suite="suite", name="test_error", status="error"))
    results.append(SimpleNamespace(suite="suite", name="test_pass", status="passed"))

    failed_tests, omitted = failed_tests_summary(results)

    assert failed_tests == [
        {"suite": "suite", "name": f"test_{index}", "status": "failed"}
        for index in range(20)
    ]
    assert omitted == 2


def test_resource_termination_summary_includes_resource_usage_when_terminal_by_resource():
    started_at = datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)
    finished_at = started_at + timedelta(seconds=3, milliseconds=42)
    resource_usage = {"memory_peak_bytes": 1024}

    summary = resource_termination_summary(
        ExitResult(
            exit_code=-1,
            started_at=started_at,
            finished_at=finished_at,
            oom_killed=True,
            timed_out=True,
            resource_usage=resource_usage,
        )
    )

    assert summary == {
        "reason": "oom+timeout",
        "exit_code": -1,
        "oom_killed": True,
        "timed_out": True,
        "duration_ms": 3042,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "resource_usage": resource_usage,
    }


def test_resource_termination_summary_ignores_normal_exit():
    now = datetime.now(timezone.utc)

    assert (
        resource_termination_summary(
            ExitResult(exit_code=0, started_at=now, finished_at=now)
        )
        is None
    )


def test_resource_usage_tracker_reports_peaks_and_percentages():
    tracker = ResourceUsageTracker()

    assert tracker.summary() is None

    tracker.observe(
        ResourceUsageSample(
            timestamp=datetime.now(timezone.utc),
            memory_usage_bytes=100,
            memory_limit_bytes=200,
            memory_max_usage_bytes=150,
            cpu_percent=12.5,
            pids_current=3,
        )
    )
    tracker.observe(
        ResourceUsageSample(
            timestamp=datetime.now(timezone.utc),
            memory_usage_bytes=175,
            memory_limit_bytes=200,
            cpu_percent=7.0,
            pids_current=5,
        )
    )

    assert tracker.summary() == {
        "sample_count": 2,
        "memory_peak_bytes": 175,
        "memory_limit_bytes": 200,
        "memory_peak_percent": 87.5,
        "cpu_peak_percent": 12.5,
        "pids_peak": 5,
    }


def test_attach_resource_usage_preserves_original_without_usage():
    now = datetime.now(timezone.utc)
    exit_result = ExitResult(exit_code=0, started_at=now, finished_at=now)

    assert attach_resource_usage(exit_result, None) is exit_result


def test_attach_resource_usage_returns_exit_result_with_usage():
    now = datetime.now(timezone.utc)
    exit_result = ExitResult(exit_code=0, started_at=now, finished_at=now)

    updated = attach_resource_usage(exit_result, {"sample_count": 1})

    assert updated is not exit_result
    assert updated.resource_usage == {"sample_count": 1}


def test_executor_module_keeps_private_summary_helper_exports():
    import qaplatform.engine.executor_summaries as summaries

    assert executor_module._failed_tests_summary is summaries.failed_tests_summary
    assert (
        executor_module._resource_termination_summary
        is summaries.resource_termination_summary
    )
    assert executor_module._ResourceUsageTracker is summaries.ResourceUsageTracker
    assert executor_module._attach_resource_usage is summaries.attach_resource_usage
