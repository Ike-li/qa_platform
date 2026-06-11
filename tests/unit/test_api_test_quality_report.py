from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORTER_PATH = ROOT / "scripts" / "report_api_test_quality.py"


def _load_reporter():
    spec = importlib.util.spec_from_file_location(
        "report_api_test_quality",
        REPORTER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reporter = _load_reporter()


def test_api_test_quality_report_writes_summary_and_dashboard(tmp_path: Path) -> None:
    summary = reporter.build_report(
        output_dir=tmp_path,
        generated_at="2026-06-04T00:00:00+00:00",
    )

    summary_path = tmp_path / "summary.json"
    dashboard_path = tmp_path / "index.md"
    written_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    dashboard = dashboard_path.read_text(encoding="utf-8")

    assert written_summary == summary
    assert summary["quality_gate"]["passed"] is True
    assert summary["metrics"]["operation_count"] == 75
    assert summary["metrics"]["operation_covered"] == 75
    assert summary["metrics"]["operation_covered_pct"] == 100.0
    assert summary["metrics"]["case_count"] == 450
    assert summary["metrics"]["case_covered"] == 450
    assert summary["metrics"]["case_covered_pct"] == 100.0
    assert summary["metrics"]["blocked_case_count"] == 0
    assert summary["metrics"]["missing_case_count"] == 0
    assert {
        item["dimension"]
        for item in summary["breakdowns"]["cases_by_dimension"]
    } == {
        "auth",
        "contract",
        "declared_responses",
        "rbac_tenant",
        "schema_negative",
        "success",
    }
    assert "# API Test Quality Dashboard" in dashboard
    assert "- quality_gate: PASS" in dashboard
    assert "| auth | 75 | 0 | 0 |" in dashboard
    assert "| webhooks | 2 | 2 | 0 | 0 |" in dashboard


def test_api_test_quality_report_computes_previous_summary_deltas(
    tmp_path: Path,
) -> None:
    previous_summary = tmp_path / "previous-summary.json"
    previous_summary.write_text(
        json.dumps(
            {
                "metrics": {
                    "operation_covered": 68,
                    "operation_covered_pct": 97.14,
                    "case_covered": 410,
                    "case_covered_pct": 97.62,
                }
            }
        ),
        encoding="utf-8",
    )

    summary = reporter.build_report(
        output_dir=tmp_path / "report",
        previous_summary_path=previous_summary,
        generated_at="2026-06-04T00:00:00+00:00",
    )

    assert summary["trend"]["delta_from_previous"] == {
        "operation_covered": 7,
        "operation_covered_pct": 2.86,
        "case_covered": 40,
        "case_covered_pct": 2.38,
    }
