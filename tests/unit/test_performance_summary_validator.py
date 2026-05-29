from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "validate_performance_summary.py"
    spec = importlib.util.spec_from_file_location("validate_performance_summary", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_validate_performance_summary_accepts_manifest_contract(
    monkeypatch,
    tmp_path: Path,
):
    validator = _load_validator_module()
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.jsonl"
    thresholds_path = tmp_path / "thresholds.json"
    _write_json(
        manifest_path,
        {
            "version": 1,
            "slos": [
                {
                    "name": "read API",
                    "threshold_env": "PERF_READ_API_MS",
                    "min_samples": 3,
                    "kind": "api_p99",
                },
                {
                    "name": "worker elapsed",
                    "threshold_env": "PERF_WORKER_MS",
                    "min_samples": 1,
                    "kind": "external_stack_elapsed",
                },
            ],
        },
    )
    _write_jsonl(
        summary_path,
        [
            {
                "name": "read API",
                "gate_profile": "release_candidate",
                "passed": True,
                "threshold_ms": 100,
                "p50_ms": 10,
                "p99_ms": 90,
                "max_ms": 95,
                "samples": 3,
            },
            {
                "name": "worker elapsed",
                "gate_profile": "release_candidate",
                "passed": True,
                "threshold_ms": 250,
                "elapsed_ms": 200,
                "samples": 1,
            },
        ],
    )
    monkeypatch.setenv("PERF_READ_API_MS", "100")
    monkeypatch.setenv("PERF_WORKER_MS", "250")

    errors = validator.validate(
        summary_path=summary_path,
        manifest_path=manifest_path,
        thresholds_path=thresholds_path,
        expected_gate_profile="release_candidate",
    )

    assert errors == []
    assert json.loads(thresholds_path.read_text(encoding="utf-8")) == {
        "gate_profile": "release_candidate",
        "manifest": str(manifest_path),
        "thresholds_ms": {
            "read API": 100.0,
            "worker elapsed": 250.0,
        },
    }


def test_validate_performance_summary_writes_trend_against_baseline(
    monkeypatch,
    tmp_path: Path,
):
    validator = _load_validator_module()
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.jsonl"
    thresholds_path = tmp_path / "thresholds.json"
    baseline_path = tmp_path / "baseline.json"
    trend_path = tmp_path / "trend.json"
    _write_json(
        manifest_path,
        {
            "version": 1,
            "slos": [
                {
                    "name": "read API",
                    "threshold_env": "PERF_READ_API_MS",
                    "min_samples": 3,
                    "kind": "api_p99",
                },
            ],
        },
    )
    _write_json(
        baseline_path,
        {
            "version": 1,
            "slos": [
                {
                    "name": "read API",
                    "metric": "p99_ms",
                    "baseline_ms": 80,
                    "max_regression_ratio": 1.25,
                },
            ],
        },
    )
    _write_jsonl(
        summary_path,
        [
            {
                "name": "read API",
                "gate_profile": "release_candidate",
                "passed": True,
                "threshold_ms": 100,
                "p50_ms": 10,
                "p99_ms": 90,
                "max_ms": 95,
                "samples": 3,
            },
        ],
    )
    monkeypatch.setenv("PERF_READ_API_MS", "100")

    errors = validator.validate(
        summary_path=summary_path,
        manifest_path=manifest_path,
        thresholds_path=thresholds_path,
        expected_gate_profile="release_candidate",
        baseline_path=baseline_path,
        trend_path=trend_path,
    )

    assert errors == []
    trend = json.loads(trend_path.read_text(encoding="utf-8"))
    assert trend["trends"] == [
        {
            "baseline_ms": 80.0,
            "current_ms": 90.0,
            "max_regression_ratio": 1.25,
            "metric": "p99_ms",
            "name": "read API",
            "regression_budget_ms": 100.0,
            "regression_ratio": 1.125,
            "status": "passed",
        }
    ]


def test_validate_performance_summary_rejects_bad_summary_rows(
    monkeypatch,
    tmp_path: Path,
):
    validator = _load_validator_module()
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.jsonl"
    thresholds_path = tmp_path / "thresholds.json"
    _write_json(
        manifest_path,
        {
            "version": 1,
            "slos": [
                {
                    "name": "read API",
                    "threshold_env": "PERF_READ_API_MS",
                    "min_samples": 3,
                    "kind": "api_p99",
                },
                {
                    "name": "write API",
                    "threshold_env": "PERF_WRITE_API_MS",
                    "min_samples": 2,
                    "kind": "api_p99",
                },
            ],
        },
    )
    _write_jsonl(
        summary_path,
        [
            {
                "name": "read API",
                "gate_profile": "nightly",
                "passed": False,
                "threshold_ms": 99,
                "p50_ms": 10,
                "p99_ms": 120,
                "max_ms": 130,
                "samples": 1,
            },
            {
                "name": "unexpected API",
                "gate_profile": "release_candidate",
                "passed": True,
                "threshold_ms": 50,
                "p50_ms": 10,
                "p99_ms": 40,
                "max_ms": 45,
                "samples": 5,
            },
        ],
    )
    monkeypatch.setenv("PERF_READ_API_MS", "100")
    monkeypatch.setenv("PERF_WRITE_API_MS", "200")

    errors = validator.validate(
        summary_path=summary_path,
        manifest_path=manifest_path,
        thresholds_path=thresholds_path,
        expected_gate_profile="release_candidate",
    )

    assert "performance_gate_profile_mismatch=read API expected=release_candidate actual=nightly" in errors
    assert "performance_slo_failed=read API" in errors
    assert "performance_threshold_mismatch=read API expected=100.0 actual=99" in errors
    assert "performance_samples_below_minimum=read API minimum=3 actual=1" in errors
    assert (
        "performance_metric_exceeds_threshold=read API metric=p99_ms threshold=100.0 actual=120"
        in errors
    )
    assert "unexpected_performance_slo=unexpected API" in errors
    assert "missing_performance_slo=write API" in errors


def test_validate_performance_summary_rejects_trend_regression(
    monkeypatch,
    tmp_path: Path,
):
    validator = _load_validator_module()
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.jsonl"
    thresholds_path = tmp_path / "thresholds.json"
    baseline_path = tmp_path / "baseline.json"
    trend_path = tmp_path / "trend.json"
    _write_json(
        manifest_path,
        {
            "version": 1,
            "slos": [
                {
                    "name": "read API",
                    "threshold_env": "PERF_READ_API_MS",
                    "min_samples": 1,
                    "kind": "api_p99",
                },
            ],
        },
    )
    _write_json(
        baseline_path,
        {
            "version": 1,
            "slos": [
                {
                    "name": "read API",
                    "metric": "p99_ms",
                    "baseline_ms": 80,
                    "max_regression_ratio": 1.1,
                },
            ],
        },
    )
    _write_jsonl(
        summary_path,
        [
            {
                "name": "read API",
                "gate_profile": "release_candidate",
                "passed": True,
                "threshold_ms": 200,
                "p50_ms": 10,
                "p99_ms": 100,
                "max_ms": 110,
                "samples": 1,
            },
        ],
    )
    monkeypatch.setenv("PERF_READ_API_MS", "200")

    errors = validator.validate(
        summary_path=summary_path,
        manifest_path=manifest_path,
        thresholds_path=thresholds_path,
        expected_gate_profile="release_candidate",
        baseline_path=baseline_path,
        trend_path=trend_path,
    )

    assert (
        "performance_regression_exceeds_budget=read API metric=p99_ms "
        "baseline=80.0 budget=88.0 actual=100.0"
    ) in errors
    assert json.loads(trend_path.read_text(encoding="utf-8"))["trends"][0]["status"] == "regressed"


def test_validate_performance_summary_rejects_missing_measurement_values(
    monkeypatch,
    tmp_path: Path,
):
    validator = _load_validator_module()
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.jsonl"
    thresholds_path = tmp_path / "thresholds.json"
    _write_json(
        manifest_path,
        {
            "version": 1,
            "slos": [
                {
                    "name": "read API",
                    "threshold_env": "PERF_READ_API_MS",
                    "min_samples": 1,
                    "kind": "api_p99",
                },
                {
                    "name": "worker elapsed",
                    "threshold_env": "PERF_WORKER_MS",
                    "min_samples": 1,
                    "kind": "external_stack_elapsed",
                },
            ],
        },
    )
    _write_jsonl(
        summary_path,
        [
            {
                "name": "read API",
                "gate_profile": "release_candidate",
                "passed": True,
                "threshold_ms": 100,
                "samples": 1,
            },
            {
                "name": "worker elapsed",
                "gate_profile": "release_candidate",
                "passed": True,
                "threshold_ms": 250,
                "samples": 1,
            },
        ],
    )
    monkeypatch.setenv("PERF_READ_API_MS", "100")
    monkeypatch.setenv("PERF_WORKER_MS", "250")

    errors = validator.validate(
        summary_path=summary_path,
        manifest_path=manifest_path,
        thresholds_path=thresholds_path,
        expected_gate_profile="release_candidate",
    )

    assert "performance_metric_invalid=read API metric=p50_ms value=None" in errors
    assert "performance_metric_invalid=read API metric=p99_ms value=None" in errors
    assert "performance_metric_invalid=read API metric=max_ms value=None" in errors
    assert "performance_metric_invalid=worker elapsed metric=elapsed_ms value=None" in errors
