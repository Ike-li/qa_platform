from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_skip_report_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "report_integration_skips.py"
    spec = importlib.util.spec_from_file_location("report_integration_skips", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_integration_skips_classifies_known_gate_reasons(tmp_path: Path):
    reporter = _load_skip_report_module()
    junit = tmp_path / "integration.xml"
    junit.write_text(
        """
        <testsuite>
          <testcase classname="tests.integration.test_a" name="test_env">
            <skipped message="set RUN_INTEGRATION_TESTS=1 to run integration tests" />
          </testcase>
          <testcase classname="tests.integration.test_b" name="test_perf">
            <skipped message="set RUN_PERFORMANCE_TESTS=1 to run performance smoke tests" />
          </testcase>
          <testcase classname="tests.integration.test_c" name="test_docker">
            <skipped message="docker daemon not available" />
          </testcase>
        </testsuite>
        """,
        encoding="utf-8",
    )

    entries = reporter.collect_skips([junit])

    assert entries == [
        {
            "junit_path": str(junit),
            "classname": "tests.integration.test_a",
            "name": "test_env",
            "reason": "set RUN_INTEGRATION_TESTS=1 to run integration tests",
            "category": "env_gate.integration_opt_in",
            "gate_policy": "required_in_ci",
        },
        {
            "junit_path": str(junit),
            "classname": "tests.integration.test_b",
            "name": "test_perf",
            "reason": "set RUN_PERFORMANCE_TESTS=1 to run performance smoke tests",
            "category": "env_gate.performance_opt_in",
            "gate_policy": "nightly_and_release_candidate",
        },
        {
            "junit_path": str(junit),
            "classname": "tests.integration.test_c",
            "name": "test_docker",
            "reason": "docker daemon not available",
            "category": "infra.docker_daemon",
            "gate_policy": "allowed_only_when_prerequisite_unavailable",
        },
    ]


def test_report_integration_skips_writes_json_and_markdown_inventory(tmp_path: Path):
    reporter = _load_skip_report_module()
    junit = tmp_path / "integration.xml"
    output_json = tmp_path / "skip.json"
    output_md = tmp_path / "skip.md"
    junit.write_text(
        """
        <testsuite>
          <testcase classname="tests.integration.test_a" name="test_unknown">
            <skipped message="temporary local fixture unavailable" />
          </testcase>
        </testsuite>
        """,
        encoding="utf-8",
    )

    entries = reporter.collect_skips([junit])
    reporter.write_report(entries=entries, json_path=output_json, markdown_path=output_md)

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "total_skipped": 1,
        "categories": {"unknown": 1},
        "entries": [
            {
                "junit_path": str(junit),
                "classname": "tests.integration.test_a",
                "name": "test_unknown",
                "reason": "temporary local fixture unavailable",
                "category": "unknown",
                "gate_policy": "investigate_before_release",
            }
        ],
    }
    markdown = output_md.read_text(encoding="utf-8")
    assert markdown == (
        "# Integration Skip Inventory\n"
        "\n"
        "- total skipped: 1\n"
        "- unknown: 1\n"
        "\n"
        "| Category | Policy | Test | Reason |\n"
        "| --- | --- | --- | --- |\n"
        "| unknown | investigate_before_release | "
        "tests.integration.test_a::test_unknown | temporary local fixture unavailable |\n"
    )


def test_report_integration_skips_ignores_missing_junit_files(tmp_path: Path):
    reporter = _load_skip_report_module()

    entries = reporter.collect_skips([tmp_path / "missing.xml"])

    assert entries == []
