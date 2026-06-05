"""Summary helpers for run execution results."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from typing import Any

from qaplatform.engine.docker_backend import ExitResult, ResourceUsageSample

_FAILED_TESTS_SUMMARY_LIMIT = 20


def failed_tests_summary(results: list[Any]) -> tuple[list[dict[str, str]], int]:
    failed_tests = [
        {
            "suite": result.suite,
            "name": result.name,
            "status": result.status,
        }
        for result in results
        if result.status in {"failed", "error"}
    ]
    return (
        failed_tests[:_FAILED_TESTS_SUMMARY_LIMIT],
        max(0, len(failed_tests) - _FAILED_TESTS_SUMMARY_LIMIT),
    )


def resource_termination_summary(exit_result: ExitResult) -> dict[str, Any] | None:
    oom_killed = exit_result.oom_killed is True
    timed_out = exit_result.timed_out is True
    if not (oom_killed or timed_out):
        return None
    reasons = []
    if oom_killed:
        reasons.append("oom")
    if timed_out:
        reasons.append("timeout")
    duration_ms = max(
        0,
        int((exit_result.finished_at - exit_result.started_at).total_seconds() * 1000),
    )
    summary = {
        "reason": "+".join(reasons),
        "exit_code": exit_result.exit_code,
        "oom_killed": oom_killed,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
        "started_at": exit_result.started_at.isoformat(),
        "finished_at": exit_result.finished_at.isoformat(),
    }
    resource_usage = getattr(exit_result, "resource_usage", None)
    if resource_usage:
        summary["resource_usage"] = resource_usage
    return summary


class ResourceUsageTracker:
    def __init__(self) -> None:
        self.sample_count = 0
        self.memory_peak_bytes: int | None = None
        self.memory_limit_bytes: int | None = None
        self.cpu_peak_percent: float | None = None
        self.pids_peak: int | None = None

    def observe(self, sample: ResourceUsageSample) -> None:
        self.sample_count += 1
        memory_candidates = [
            value
            for value in (sample.memory_max_usage_bytes, sample.memory_usage_bytes)
            if value is not None
        ]
        if memory_candidates:
            memory_peak = max(memory_candidates)
            self.memory_peak_bytes = (
                memory_peak
                if self.memory_peak_bytes is None
                else max(self.memory_peak_bytes, memory_peak)
            )
        if sample.memory_limit_bytes is not None:
            self.memory_limit_bytes = sample.memory_limit_bytes
        if sample.cpu_percent is not None:
            self.cpu_peak_percent = (
                sample.cpu_percent
                if self.cpu_peak_percent is None
                else max(self.cpu_peak_percent, sample.cpu_percent)
            )
        if sample.pids_current is not None:
            self.pids_peak = (
                sample.pids_current
                if self.pids_peak is None
                else max(self.pids_peak, sample.pids_current)
            )

    def summary(self) -> dict[str, Any] | None:
        if self.sample_count == 0:
            return None
        summary: dict[str, Any] = {"sample_count": self.sample_count}
        if self.memory_peak_bytes is not None:
            summary["memory_peak_bytes"] = self.memory_peak_bytes
        if self.memory_limit_bytes is not None:
            summary["memory_limit_bytes"] = self.memory_limit_bytes
        if self.memory_peak_bytes is not None and self.memory_limit_bytes:
            summary["memory_peak_percent"] = (
                self.memory_peak_bytes / self.memory_limit_bytes
            ) * 100.0
        if self.cpu_peak_percent is not None:
            summary["cpu_peak_percent"] = self.cpu_peak_percent
        if self.pids_peak is not None:
            summary["pids_peak"] = self.pids_peak
        return summary


def attach_resource_usage(
    exit_result: ExitResult,
    resource_usage: dict[str, Any] | None,
) -> ExitResult:
    if not resource_usage:
        return exit_result
    if isinstance(exit_result, ExitResult):
        return replace(exit_result, resource_usage=resource_usage)
    with suppress(Exception):
        setattr(exit_result, "resource_usage", resource_usage)
    return exit_result
