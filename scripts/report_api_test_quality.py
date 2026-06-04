from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPERATION_MATRIX = ROOT / "tests" / "api_matrix" / "openapi_operation_matrix.yml"
DEFAULT_CASE_MATRIX = ROOT / "tests" / "api_matrix" / "openapi_test_case_matrix.yml"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "api-test-quality"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


operation_validator = _load_module(
    "validate_api_test_matrix_for_quality_report",
    Path(__file__).with_name("validate_api_test_matrix.py"),
)
case_validator = _load_module(
    "validate_api_test_case_matrix_for_quality_report",
    Path(__file__).with_name("validate_api_test_case_matrix.py"),
)


def _percent(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _load_previous_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: previous summary must be a JSON object")
    return data


def _delta(
    previous: dict[str, Any] | None,
    metrics: dict[str, int | float | bool],
    metric: str,
) -> int | float | None:
    if previous is None:
        return None
    previous_metrics = previous.get("metrics")
    if not isinstance(previous_metrics, dict):
        return None
    previous_value = previous_metrics.get(metric)
    current_value = metrics[metric]
    if not isinstance(previous_value, (int, float)) or isinstance(previous_value, bool):
        return None
    if not isinstance(current_value, (int, float)) or isinstance(current_value, bool):
        return None
    return round(current_value - previous_value, 2)


def _operation_breakdown(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tag: dict[str, Counter[str]] = defaultdict(Counter)
    for operation in operations:
        tag = str(operation["tag"])
        status = str(operation["coverage_status"])
        by_tag[tag]["operations"] += 1
        by_tag[tag][status] += 1

    return [
        {
            "tag": tag,
            "operations": counts["operations"],
            "covered": counts["covered"],
            "partial": counts["partial"],
            "blocked": counts["blocked_by_missing_public_setup"],
        }
        for tag, counts in sorted(by_tag.items())
    ]


def _case_breakdown(cases: list[Any]) -> list[dict[str, Any]]:
    by_dimension: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        by_dimension[case.dimension][case.status] += 1

    return [
        {
            "dimension": dimension,
            "covered": counts["covered"],
            "blocked": counts["blocked_by_missing_public_setup"],
            "missing": counts["missing"],
        }
        for dimension, counts in sorted(by_dimension.items())
    ]


def _response_status_breakdown(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    response_counts: Counter[str] = Counter()
    for operation in operations:
        response_counts.update(str(status) for status in operation["declared_responses"])
    return [
        {"status": status, "operations": count}
        for status, count in sorted(response_counts.items())
    ]


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _format_delta(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    if value > 0:
        return f"+{value}"
    return str(value)


def _build_markdown(summary: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    deltas = summary["trend"]["delta_from_previous"]
    status = "PASS" if summary["quality_gate"]["passed"] else "FAIL"

    metric_rows = [
        ["operations", str(metrics["operation_count"]), "n/a"],
        [
            "covered operations",
            str(metrics["operation_covered"]),
            _format_delta(deltas["operation_covered"]),
        ],
        [
            "operation coverage pct",
            f"{metrics['operation_covered_pct']:.2f}",
            _format_delta(deltas["operation_covered_pct"]),
        ],
        ["atomic cases", str(metrics["case_count"]), "n/a"],
        [
            "covered cases",
            str(metrics["case_covered"]),
            _format_delta(deltas["case_covered"]),
        ],
        [
            "case coverage pct",
            f"{metrics['case_covered_pct']:.2f}",
            _format_delta(deltas["case_covered_pct"]),
        ],
        ["blocked cases", str(metrics["blocked_case_count"]), "n/a"],
        ["missing cases", str(metrics["missing_case_count"]), "n/a"],
    ]
    tag_rows = [
        [
            item["tag"],
            str(item["operations"]),
            str(item["covered"]),
            str(item["partial"]),
            str(item["blocked"]),
        ]
        for item in summary["breakdowns"]["operations_by_tag"]
    ]
    dimension_rows = [
        [
            item["dimension"],
            str(item["covered"]),
            str(item["blocked"]),
            str(item["missing"]),
        ]
        for item in summary["breakdowns"]["cases_by_dimension"]
    ]
    response_rows = [
        [item["status"], str(item["operations"])]
        for item in summary["breakdowns"]["declared_responses"]
    ]

    return "\n\n".join(
        [
            "# API Test Quality Dashboard",
            f"- generated_at: {summary['generated_at']}",
            f"- quality_gate: {status}",
            f"- operation_matrix: {summary['inputs']['operation_matrix']}",
            f"- case_matrix: {summary['inputs']['case_matrix']}",
            "## Snapshot",
            _markdown_table(["metric", "value", "delta"], metric_rows),
            "## Operation Coverage By Tag",
            _markdown_table(
                ["tag", "operations", "covered", "partial", "blocked"],
                tag_rows,
            ),
            "## Atomic Case Coverage By Dimension",
            _markdown_table(["dimension", "covered", "blocked", "missing"], dimension_rows),
            "## Declared Response Statuses",
            _markdown_table(["status", "operations"], response_rows),
            "## Commands",
            "```bash\n"
            ".venv/bin/python scripts/validate_api_test_matrix.py\n"
            ".venv/bin/python scripts/validate_api_test_case_matrix.py\n"
            ".venv/bin/python scripts/report_api_test_quality.py\n"
            "```",
        ]
    ) + "\n"


def build_report(
    *,
    operation_matrix_path: Path = DEFAULT_OPERATION_MATRIX,
    case_matrix_path: Path = DEFAULT_CASE_MATRIX,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    previous_summary_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    operation_summary = operation_validator.validate_matrix(operation_matrix_path)
    case_summary = case_validator.validate_case_matrix(
        case_matrix_path,
        operation_matrix_path,
    )
    matrix = operation_validator.load_matrix(operation_matrix_path)
    cases = case_validator.build_atomic_cases(case_matrix_path, operation_matrix_path)
    operations = matrix["operations"]

    metrics: dict[str, int | float | bool] = {
        "operation_count": operation_summary["operations"],
        "operation_covered": operation_summary["covered"],
        "operation_partial": operation_summary["partial"],
        "operation_blocked": operation_summary["blocked"],
        "operation_covered_pct": _percent(
            operation_summary["covered"],
            operation_summary["operations"],
        ),
        "dimension_count": case_summary["dimensions"],
        "case_count": case_summary["cases"],
        "case_covered": case_summary["covered"],
        "case_covered_pct": _percent(case_summary["covered"], case_summary["cases"]),
        "blocked_case_count": case_summary["blocked"],
        "missing_case_count": case_summary["missing"],
    }
    previous_summary = _load_previous_summary(previous_summary_path)
    delta_metrics = (
        "operation_covered",
        "operation_covered_pct",
        "case_covered",
        "case_covered_pct",
    )
    summary: dict[str, Any] = {
        "version": 1,
        "generated_at": generated_at
        or datetime.now(UTC).replace(microsecond=0).isoformat(),
        "inputs": {
            "operation_matrix": str(operation_matrix_path.relative_to(ROOT)),
            "case_matrix": str(case_matrix_path.relative_to(ROOT)),
            "previous_summary": (
                str(previous_summary_path)
                if previous_summary_path is not None
                else None
            ),
        },
        "quality_gate": {
            "passed": (
                operation_summary["partial"] == 0
                and operation_summary["blocked"] == 0
                and case_summary["blocked"] == 0
                and case_summary["missing"] == 0
            ),
            "rules": [
                "operation matrix validates against runtime OpenAPI",
                "case matrix has no missing atomic cases",
                "partial and blocked operation counts are zero",
            ],
        },
        "metrics": metrics,
        "trend": {
            "delta_from_previous": {
                metric: _delta(previous_summary, metrics, metric)
                for metric in delta_metrics
            }
        },
        "breakdowns": {
            "operations_by_tag": _operation_breakdown(operations),
            "cases_by_dimension": _case_breakdown(cases),
            "declared_responses": _response_status_breakdown(operations),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    dashboard_path = output_dir / "index.md"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    dashboard_path.write_text(_build_markdown(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write API test quality trend artifacts from the OpenAPI matrices."
    )
    parser.add_argument(
        "--operation-matrix",
        default=str(DEFAULT_OPERATION_MATRIX),
        help="Path to tests/api_matrix/openapi_operation_matrix.yml.",
    )
    parser.add_argument(
        "--case-matrix",
        default=str(DEFAULT_CASE_MATRIX),
        help="Path to tests/api_matrix/openapi_test_case_matrix.yml.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for summary.json and index.md.",
    )
    parser.add_argument(
        "--previous-summary",
        default=None,
        help="Optional previous summary.json to compute metric deltas.",
    )
    args = parser.parse_args()

    summary = build_report(
        operation_matrix_path=Path(args.operation_matrix),
        case_matrix_path=Path(args.case_matrix),
        output_dir=Path(args.output_dir),
        previous_summary_path=(
            Path(args.previous_summary) if args.previous_summary else None
        ),
    )
    print(
        "api_test_quality_report=written "
        f"quality_gate_passed={summary['quality_gate']['passed']} "
        f"operations={summary['metrics']['operation_count']} "
        f"cases={summary['metrics']['case_count']} "
        f"output_dir={args.output_dir}"
    )


if __name__ == "__main__":
    main()
