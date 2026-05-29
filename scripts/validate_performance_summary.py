#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    slos = data.get("slos")
    if not isinstance(slos, list) or not slos:
        raise ValueError(f"manifest has no slos: {path}")

    by_name: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(slos, 1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest slo #{index} must be an object")
        name = item.get("name")
        threshold_env = item.get("threshold_env")
        min_samples = item.get("min_samples")
        kind = item.get("kind")
        if not isinstance(name, str) or not name:
            raise ValueError(f"manifest slo #{index} has invalid name")
        if name in by_name:
            raise ValueError(f"manifest duplicate slo name: {name}")
        if not isinstance(threshold_env, str) or not threshold_env:
            raise ValueError(f"manifest slo {name} has invalid threshold_env")
        if not isinstance(min_samples, int) or min_samples < 1:
            raise ValueError(f"manifest slo {name} has invalid min_samples")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"manifest slo {name} has invalid kind")
        _metric_fields_for_kind(kind)
        by_name[name] = item
    return by_name


def _metric_fields_for_kind(kind: str) -> tuple[str, ...]:
    if kind in {"external_stack_elapsed", "external_stack_capacity"}:
        return ("elapsed_ms",)
    if kind.endswith("_p99"):
        return ("p50_ms", "p99_ms", "max_ms")
    raise ValueError(f"unsupported performance slo kind: {kind}")


def _finite_nonnegative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and value >= 0


def _load_summary(path: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    rows_by_name: dict[str, dict[str, Any]] = {}
    if not path.exists():
        errors.append(f"missing_performance_summary={path}")
        return rows_by_name

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid_performance_summary_json line={line_number} error={exc}")
            continue
        name = row.get("name", f"line-{line_number}")
        if name in rows_by_name:
            errors.append(f"duplicate_performance_slo={name}")
        rows_by_name[name] = row
    return rows_by_name


def _load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    slos = data.get("slos")
    if not isinstance(slos, list) or not slos:
        raise ValueError(f"baseline has no slos: {path}")

    by_name: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(slos, 1):
        if not isinstance(item, dict):
            raise ValueError(f"baseline slo #{index} must be an object")
        name = item.get("name")
        metric = item.get("metric")
        baseline_ms = item.get("baseline_ms")
        max_regression_ratio = item.get("max_regression_ratio")
        if not isinstance(name, str) or not name:
            raise ValueError(f"baseline slo #{index} has invalid name")
        if name in by_name:
            raise ValueError(f"baseline duplicate slo name: {name}")
        if not isinstance(metric, str) or not metric:
            raise ValueError(f"baseline slo {name} has invalid metric")
        if not _finite_nonnegative_number(baseline_ms) or float(baseline_ms) <= 0:
            raise ValueError(f"baseline slo {name} has invalid baseline_ms")
        if not isinstance(max_regression_ratio, (int, float)) or float(max_regression_ratio) < 1:
            raise ValueError(f"baseline slo {name} has invalid max_regression_ratio")
        by_name[name] = item
    return by_name


def _validate_trends(
    *,
    rows_by_name: dict[str, dict[str, Any]],
    manifest: dict[str, dict[str, Any]],
    baseline_path: Path,
    trend_path: Path,
) -> list[str]:
    errors: list[str] = []
    try:
        baselines = _load_baseline(baseline_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"invalid_performance_baseline={baseline_path} error={exc}"]

    trends: list[dict[str, Any]] = []
    for name, slo in manifest.items():
        baseline = baselines.get(name)
        row = rows_by_name.get(name)
        if baseline is None:
            errors.append(f"missing_performance_baseline={name}")
            continue
        if row is None:
            continue

        metric = baseline["metric"]
        if metric not in _metric_fields_for_kind(slo["kind"]):
            errors.append(f"performance_baseline_metric_mismatch={name} metric={metric}")
            continue
        current_ms = row.get(metric)
        if not _finite_nonnegative_number(current_ms):
            errors.append(
                f"performance_trend_metric_invalid={name} metric={metric} value={current_ms}"
            )
            continue

        baseline_ms = float(baseline["baseline_ms"])
        max_regression_ratio = float(baseline["max_regression_ratio"])
        regression_budget_ms = baseline_ms * max_regression_ratio
        current_float = float(current_ms)
        regression_ratio = current_float / baseline_ms
        status = "passed" if current_float <= regression_budget_ms else "regressed"
        trends.append(
            {
                "name": name,
                "metric": metric,
                "current_ms": current_float,
                "baseline_ms": baseline_ms,
                "max_regression_ratio": max_regression_ratio,
                "regression_budget_ms": regression_budget_ms,
                "regression_ratio": regression_ratio,
                "status": status,
            }
        )
        if status != "passed":
            errors.append(
                "performance_regression_exceeds_budget="
                f"{name} metric={metric} baseline={baseline_ms} "
                f"budget={regression_budget_ms} actual={current_float}"
            )

    unexpected = sorted(set(baselines) - set(manifest))
    for name in unexpected:
        errors.append(f"unexpected_performance_baseline={name}")

    trend_path.write_text(
        json.dumps(
            {
                "version": 1,
                "baseline": str(baseline_path),
                "trends": trends,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return errors


def validate(
    *,
    summary_path: Path,
    manifest_path: Path,
    thresholds_path: Path,
    expected_gate_profile: str,
    baseline_path: Path | None = None,
    trend_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        manifest = _load_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"invalid_performance_slo_manifest={manifest_path} error={exc}"]

    thresholds: dict[str, float] = {}
    for name, slo in manifest.items():
        env_var = slo["threshold_env"]
        raw_value = os.environ.get(env_var)
        if raw_value is None:
            errors.append(f"missing_performance_threshold_env={env_var}")
            continue
        try:
            threshold = float(raw_value)
        except ValueError:
            errors.append(f"invalid_performance_threshold_env={env_var} value={raw_value}")
            continue
        if threshold <= 0:
            errors.append(f"invalid_performance_threshold_env={env_var} value={raw_value}")
        thresholds[name] = threshold

    thresholds_path.write_text(
        json.dumps(
            {
                "gate_profile": expected_gate_profile,
                "manifest": str(manifest_path),
                "thresholds_ms": thresholds,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    rows_by_name = _load_summary(summary_path, errors)
    for name, row in rows_by_name.items():
        if name not in manifest:
            errors.append(f"unexpected_performance_slo={name}")
            continue

        if row.get("gate_profile") != expected_gate_profile:
            errors.append(
                "performance_gate_profile_mismatch="
                f"{name} expected={expected_gate_profile} actual={row.get('gate_profile')}"
            )
        if row.get("passed") is not True:
            errors.append(f"performance_slo_failed={name}")

        threshold_ms = row.get("threshold_ms")
        expected_threshold = thresholds.get(name)
        if not isinstance(threshold_ms, (int, float)) or threshold_ms <= 0:
            errors.append(f"performance_threshold_invalid={name}")
        elif expected_threshold is not None and abs(float(threshold_ms) - expected_threshold) > 0.001:
            errors.append(
                "performance_threshold_mismatch="
                f"{name} expected={expected_threshold} actual={threshold_ms}"
            )

        samples = row.get("samples")
        min_samples = manifest[name]["min_samples"]
        if not isinstance(samples, int) or samples < min_samples:
            errors.append(
                f"performance_samples_below_minimum={name} "
                f"minimum={min_samples} actual={samples}"
            )

        kind = manifest[name]["kind"]
        metric_fields = _metric_fields_for_kind(kind)
        for metric_field in metric_fields:
            metric_value = row.get(metric_field)
            if not _finite_nonnegative_number(metric_value):
                errors.append(
                    f"performance_metric_invalid={name} metric={metric_field} value={metric_value}"
                )
                continue
            if expected_threshold is not None and float(metric_value) > expected_threshold:
                errors.append(
                    "performance_metric_exceeds_threshold="
                    f"{name} metric={metric_field} threshold={expected_threshold} actual={metric_value}"
                )
        if kind.endswith("_p99"):
            p50_ms = row.get("p50_ms")
            p99_ms = row.get("p99_ms")
            max_ms = row.get("max_ms")
            if all(_finite_nonnegative_number(value) for value in (p50_ms, p99_ms, max_ms)):
                if not (float(p50_ms) <= float(max_ms) and float(p99_ms) <= float(max_ms)):
                    errors.append(f"performance_percentiles_inconsistent={name}")

    for name in manifest:
        if name not in rows_by_name:
            errors.append(f"missing_performance_slo={name}")
    if baseline_path is not None and trend_path is not None:
        errors.extend(
            _validate_trends(
                rows_by_name=rows_by_name,
                manifest=manifest,
                baseline_path=baseline_path,
                trend_path=trend_path,
            )
        )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) not in {5, 7}:
        print(
            "usage: validate_performance_summary.py "
            "<summary.jsonl> <manifest.json> <thresholds.json> <expected_gate_profile> "
            "[<baseline.json> <trend.json>]",
            file=sys.stderr,
        )
        return 2

    summary_path = Path(argv[1])
    manifest_path = Path(argv[2])
    thresholds_path = Path(argv[3])
    expected_gate_profile = argv[4]
    baseline_path = Path(argv[5]) if len(argv) == 7 else None
    trend_path = Path(argv[6]) if len(argv) == 7 else None
    errors = validate(
        summary_path=summary_path,
        manifest_path=manifest_path,
        thresholds_path=thresholds_path,
        expected_gate_profile=expected_gate_profile,
        baseline_path=baseline_path,
        trend_path=trend_path,
    )
    if errors:
        print("\n".join(errors))
        return 1
    print(f"performance_summary_gate_profile={expected_gate_profile}")
    print(f"performance_slo_manifest={manifest_path}")
    print(f"performance_thresholds_file={thresholds_path}")
    if trend_path is not None:
        print("performance_trend_validation=passed")
        print(f"performance_trend_file={trend_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
