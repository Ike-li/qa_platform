from __future__ import annotations

from uuid import uuid4

from qaplatform.engine import executor as executor_module
from qaplatform.engine import executor_results as results_module
from qaplatform.plugins.protocols import TestResultData


def test_build_results_summary_counts_statuses_and_resource_termination():
    resource_termination = {
        "reason": "timeout",
        "exit_code": 124,
        "timed_out": True,
    }
    results = [
        TestResultData(suite="api", name="test_pass", status="passed"),
        TestResultData(suite="api", name="test_skip", status="skipped"),
        TestResultData(suite="ui", name="test_xfail", status="xfail"),
        TestResultData(suite="api", name="test_login", status="failed"),
        TestResultData(suite="ui", name="test_checkout", status="error"),
    ]

    summary = results_module.build_results_summary(results, resource_termination)

    assert summary == {
        "total": 5,
        "passed": 1,
        "failed": 1,
        "skipped": 2,
        "error": 1,
        "pass_rate": 0.2,
        "failed_tests": [
            {"suite": "api", "name": "test_login", "status": "failed"},
            {"suite": "ui", "name": "test_checkout", "status": "error"},
        ],
        "resource_termination": resource_termination,
    }


def test_build_results_summary_handles_empty_collector_output():
    assert results_module.build_results_summary([]) == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "error": 0,
        "pass_rate": 0.0,
    }


def test_build_results_summary_caps_failed_test_names():
    results = [
        TestResultData(suite="suite", name=f"test_{index}", status="failed")
        for index in range(25)
    ]

    summary = results_module.build_results_summary(results)

    assert summary["failed_tests"] == [
        {"suite": "suite", "name": f"test_{index}", "status": "failed"}
        for index in range(20)
    ]
    assert summary["failed_tests_omitted"] == 5


def test_build_test_result_rows_maps_collector_results_for_repository():
    run_id = uuid4()
    result = TestResultData(
        suite="worker-suite",
        name="test_worker_smoke",
        status="failed",
        duration_ms=12,
        error_message="assertion failed",
        stack_trace="traceback",
        tags=["e2e"],
        metadata={"source": "junit"},
    )

    rows = results_module.build_test_result_rows(run_id, [result])

    assert rows == [
        {
            "run_id": run_id,
            "suite": "worker-suite",
            "name": "test_worker_smoke",
            "status": "failed",
            "duration_ms": 12,
            "error_message": "assertion failed",
            "stack_trace": "traceback",
            "tags": ["e2e"],
            "metadata_": {"source": "junit"},
        }
    ]


def test_executor_module_keeps_private_result_helper_exports():
    assert executor_module._build_results_summary is results_module.build_results_summary
    assert (
        executor_module._build_test_result_rows
        is results_module.build_test_result_rows
    )
