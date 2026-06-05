"""Result aggregation helpers for run execution."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from qaplatform.engine.executor_summaries import failed_tests_summary
from qaplatform.plugins.protocols import TestResultData


def build_results_summary(
    results: list[TestResultData],
    resource_termination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    passed = sum(1 for result in results if result.status == "passed")
    failed = sum(1 for result in results if result.status == "failed")
    skipped = sum(1 for result in results if result.status in {"skipped", "xfail"})
    error = sum(1 for result in results if result.status == "error")
    total = passed + failed + skipped + error

    summary: dict[str, Any] = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "error": error,
        "pass_rate": passed / total if total > 0 else 0.0,
    }
    failed_tests, failed_tests_omitted = failed_tests_summary(results)
    if failed_tests:
        summary["failed_tests"] = failed_tests
    if failed_tests_omitted:
        summary["failed_tests_omitted"] = failed_tests_omitted
    if resource_termination:
        summary["resource_termination"] = resource_termination
    return summary


def build_test_result_rows(
    run_id: UUID,
    results: list[TestResultData],
) -> list[dict[str, Any]]:
    return [
        {
            "run_id": run_id,
            "suite": result.suite,
            "name": result.name,
            "status": result.status,
            "duration_ms": result.duration_ms,
            "error_message": result.error_message,
            "stack_trace": result.stack_trace,
            "tags": result.tags,
            "metadata_": result.metadata,
        }
        for result in results
    ]
