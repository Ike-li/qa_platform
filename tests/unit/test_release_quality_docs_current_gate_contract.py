from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _contract_maintenance_counts,
    _quality_ops_row,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
TESTING_STRATEGY = ROOT / "docs" / "testing-strategy.md"
DOCS_CONTRACT = ROOT / "tests" / "unit" / "test_release_quality_docs_contract.py"

CURRENT_GATE_CONTRACTS = [
    (
        "current gate evidence",
        Path("tests/unit/test_release_quality_current_gate_evidence_contract.py"),
        "def test_quality_ops_records_current_gate_" + "evidence",
    ),
    (
        "current gate E2E/static evidence",
        Path("tests/unit/test_release_quality_current_gate_e2e_contract.py"),
        "def test_quality_ops_records_current_gate_e2e_static_" + "evidence",
    ),
    (
        "current gate runner/source evidence",
        Path("tests/unit/test_release_quality_current_gate_runner_contract.py"),
        "def test_quality_ops_records_current_gate_runner_source_" + "evidence",
    ),
    (
        "current gate runner/artifact evidence",
        Path("tests/unit/test_release_quality_current_gate_runner_artifact_contract.py"),
        "def test_quality_ops_records_current_gate_runner_artifact_" + "evidence",
    ),
    (
        "current gate failure-path evidence",
        Path("tests/unit/test_release_quality_current_gate_failure_path_contract.py"),
        "def test_quality_ops_records_current_gate_failure_path_" + "evidence",
    ),
    (
        "current gate validation/error evidence",
        Path("tests/unit/test_release_quality_current_gate_validation_contract.py"),
        "def test_quality_ops_records_current_gate_validation_error_" + "evidence",
    ),
    (
        "current gate settings/domain validation evidence",
        Path(
            "tests/unit/"
            "test_release_quality_current_gate_settings_domain_validation_contract.py"
        ),
        "def test_quality_ops_records_current_gate_settings_domain_validation_"
        + "evidence",
    ),
    (
        "current gate summary evidence",
        Path("tests/unit/test_release_quality_current_gate_summary_contract.py"),
        "def test_quality_ops_records_current_gate_summary_" + "evidence",
    ),
    (
        "current gate summary freshness evidence",
        Path(
            "tests/unit/"
            "test_release_quality_current_gate_summary_freshness_contract.py"
        ),
        "def test_quality_ops_records_current_gate_summary_freshness_" + "evidence",
    ),
    (
        "current gate config evidence",
        Path("tests/unit/test_release_quality_current_gate_config_contract.py"),
        "def test_quality_ops_records_current_gate_config_" + "evidence",
    ),
    (
        "current gate source/plugin evidence",
        Path("tests/unit/test_release_quality_current_gate_source_contract.py"),
        "def test_quality_ops_records_current_gate_source_" + "evidence",
    ),
    (
        "current gate API/request evidence",
        Path("tests/unit/test_release_quality_current_gate_api_contract.py"),
        "def test_quality_ops_records_current_gate_api_" + "evidence",
    ),
    (
        "current gate API boundary evidence",
        Path("tests/unit/test_release_quality_current_gate_api_boundary_contract.py"),
        "def test_quality_ops_records_current_gate_api_boundary_" + "evidence",
    ),
    (
        "current gate pipeline/API evidence",
        Path("tests/unit/test_release_quality_current_gate_pipeline_api_contract.py"),
        "def test_quality_ops_records_current_gate_pipeline_api_" + "evidence",
    ),
    (
        "current gate auth/security evidence",
        Path("tests/unit/test_release_quality_current_gate_auth_security_contract.py"),
        "def test_quality_ops_records_current_gate_auth_security_" + "evidence",
    ),
    (
        "current gate access-control evidence",
        Path("tests/unit/test_release_quality_current_gate_access_control_contract.py"),
        "def test_quality_ops_records_current_gate_access_control_" + "evidence",
    ),
    (
        "current gate data/runtime evidence",
        Path("tests/unit/test_release_quality_current_gate_data_runtime_contract.py"),
        "def test_quality_ops_records_current_gate_data_runtime_" + "evidence",
    ),
    (
        "current gate runtime-ops evidence",
        Path("tests/unit/test_release_quality_current_gate_runtime_ops_contract.py"),
        "def test_quality_ops_records_current_gate_runtime_ops_" + "evidence",
    ),
]


def test_testing_strategy_records_current_gate_contract_splits():
    testing_strategy = _read(TESTING_STRATEGY)
    docs_contract_source = _read(DOCS_CONTRACT)
    quality_row = _quality_ops_row(
        "| 2026-06-01 | N/A（质量门禁维护分层 / release-quality helper 收敛）"
    )
    evidence_path = Path(
        "tests/unit/test_release_quality_current_gate_evidence_contract.py"
    )
    current_gate_evidence_source = _read(ROOT / evidence_path)
    contract_sources = []

    for label, relative_path, test_marker in CURRENT_GATE_CONTRACTS:
        split_marker = f"{label} 契约拆到 `{relative_path.as_posix()}`"
        contract_source = _read(ROOT / relative_path)
        contract_sources.append(contract_source)

        assert split_marker in testing_strategy
        assert split_marker in quality_row
        assert split_marker not in docs_contract_source
        if relative_path == evidence_path:
            assert test_marker not in docs_contract_source
        else:
            assert test_marker not in current_gate_evidence_source
        assert test_marker in contract_source

    assert _contract_maintenance_counts(*contract_sources) == {
        "direct_read_calls": 0,
        "direct_next_calls": 0,
        "manual_block_split_slices": 0,
        "manual_single_split_slices": 0,
        "manual_index_find_calls": 0,
        "quality_ops_join_assignments": 0,
        "quality_ops_read_calls": 0,
    }
