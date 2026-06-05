"""Terminal status and log helpers for run execution."""

from __future__ import annotations

from typing import Any

from qaplatform.domain.models.run import RunStatus
from qaplatform.engine.docker_backend import ExitResult


def terminal_status_for_exit(exit_result: ExitResult) -> RunStatus:
    if exit_result.oom_killed is True or exit_result.timed_out is True:
        return RunStatus.TIMEOUT
    if exit_result.exit_code != 0:
        return RunStatus.FAILED
    return RunStatus.DONE


def pipeline_failure_message(exit_code: int) -> str:
    return f"Pipeline failed with code {exit_code}"


def resource_termination_log_message(summary: dict[str, Any]) -> str:
    return (
        "Resource termination: "
        f"reason={summary['reason']} "
        f"exit_code={summary['exit_code']} "
        f"duration_ms={summary['duration_ms']} "
        f"oom_killed={summary['oom_killed']} "
        f"timed_out={summary['timed_out']}"
    )
