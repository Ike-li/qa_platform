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

    assert [entry["category"] for entry in entries] == [
        "env_gate.integration_opt_in",
        "env_gate.performance_opt_in",
        "infra.docker_daemon",
    ]
    assert entries[0]["gate_policy"] == "required_in_ci"
    assert entries[1]["gate_policy"] == "nightly_and_release_candidate"
    assert entries[2]["gate_policy"] == "allowed_only_when_prerequisite_unavailable"


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
    assert payload["total_skipped"] == 1
    assert payload["categories"] == {"unknown": 1}
    assert payload["entries"][0]["gate_policy"] == "investigate_before_release"
    markdown = output_md.read_text(encoding="utf-8")
    assert "# Integration Skip Inventory" in markdown
    assert "temporary local fixture unavailable" in markdown


def test_report_integration_skips_ignores_missing_junit_files(tmp_path: Path):
    reporter = _load_skip_report_module()

    entries = reporter.collect_skips([tmp_path / "missing.xml"])

    assert entries == []
