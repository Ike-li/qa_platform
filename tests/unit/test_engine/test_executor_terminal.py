from __future__ import annotations

from datetime import datetime, timezone

from qaplatform.domain.models.run import RunStatus
from qaplatform.engine import executor as executor_module
from qaplatform.engine import executor_terminal as terminal
from qaplatform.engine.docker_backend import ExitResult


def _exit_result(
    exit_code: int,
    *,
    oom_killed: bool = False,
    timed_out: bool = False,
) -> ExitResult:
    now = datetime.now(timezone.utc)
    return ExitResult(
        exit_code=exit_code,
        started_at=now,
        finished_at=now,
        oom_killed=oom_killed,
        timed_out=timed_out,
    )


def test_terminal_status_for_successful_exit_is_done():
    assert terminal.terminal_status_for_exit(_exit_result(0)) == RunStatus.DONE


def test_terminal_status_for_nonzero_exit_is_failed():
    assert terminal.terminal_status_for_exit(_exit_result(1)) == RunStatus.FAILED


def test_terminal_status_for_resource_termination_is_timeout():
    assert (
        terminal.terminal_status_for_exit(_exit_result(137, oom_killed=True))
        == RunStatus.TIMEOUT
    )
    assert (
        terminal.terminal_status_for_exit(_exit_result(-1, timed_out=True))
        == RunStatus.TIMEOUT
    )


def test_pipeline_failure_message_matches_run_log_contract():
    assert terminal.pipeline_failure_message(137) == "Pipeline failed with code 137"


def test_resource_termination_log_message_matches_run_log_contract():
    assert terminal.resource_termination_log_message(
        {
            "reason": "oom+timeout",
            "exit_code": 137,
            "duration_ms": 3042,
            "oom_killed": True,
            "timed_out": True,
        }
    ) == (
        "Resource termination: reason=oom+timeout exit_code=137 "
        "duration_ms=3042 oom_killed=True timed_out=True"
    )


def test_executor_module_keeps_terminal_helper_compatibility_exports():
    assert (
        executor_module._terminal_status_for_exit
        is terminal.terminal_status_for_exit
    )
    assert (
        executor_module._pipeline_failure_message
        is terminal.pipeline_failure_message
    )
    assert (
        executor_module._resource_termination_log_message
        is terminal.resource_termination_log_message
    )
