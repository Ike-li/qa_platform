from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CASE_MATRIX_PATH = ROOT / "tests" / "api_matrix" / "openapi_test_case_matrix.yml"
OPERATION_MATRIX_PATH = ROOT / "tests" / "api_matrix" / "openapi_operation_matrix.yml"
VALIDATOR_PATH = ROOT / "scripts" / "validate_api_test_case_matrix.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_api_test_case_matrix",
        VALIDATOR_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _yaml_data(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_api_test_case_matrix_expands_operation_dimensions() -> None:
    summary = validator.validate_case_matrix(CASE_MATRIX_PATH, OPERATION_MATRIX_PATH)

    assert summary == {
        "operations": 73,
        "dimensions": 6,
        "cases": 438,
        "covered": 438,
        "blocked": 0,
        "missing": 0,
    }

    cases = validator.build_atomic_cases(CASE_MATRIX_PATH, OPERATION_MATRIX_PATH)
    assert cases[0].case_id.endswith("::contract")
    blocked_success_cases = [
        case
        for case in cases
        if case.dimension == "success"
        and case.status == "blocked_by_missing_public_setup"
    ]
    assert blocked_success_cases == []


def test_api_test_case_matrix_rejects_stale_metadata(tmp_path: Path) -> None:
    data = _yaml_data(CASE_MATRIX_PATH)
    data = deepcopy(data)
    data["metadata"]["case_count"] = 1
    case_matrix_path = tmp_path / "case-matrix.yml"
    _write_yaml(case_matrix_path, data)

    with pytest.raises(validator.CaseMatrixValidationError, match="case_count"):
        validator.validate_case_matrix(case_matrix_path, OPERATION_MATRIX_PATH)


def test_api_test_case_matrix_rejects_missing_dimension(tmp_path: Path) -> None:
    data = _yaml_data(CASE_MATRIX_PATH)
    data = deepcopy(data)
    data["dimensions"] = [
        dimension for dimension in data["dimensions"] if dimension["id"] != "auth"
    ]
    case_matrix_path = tmp_path / "case-matrix.yml"
    _write_yaml(case_matrix_path, data)

    with pytest.raises(validator.CaseMatrixValidationError, match="dimensions"):
        validator.validate_case_matrix(case_matrix_path, OPERATION_MATRIX_PATH)


def test_api_test_case_matrix_rejects_missing_operation_case(
    tmp_path: Path,
) -> None:
    case_matrix_data = _yaml_data(CASE_MATRIX_PATH)
    case_matrix_path = tmp_path / "case-matrix.yml"
    _write_yaml(case_matrix_path, case_matrix_data)

    operation_matrix_data = _yaml_data(OPERATION_MATRIX_PATH)
    operation_matrix_data = deepcopy(operation_matrix_data)
    row = next(
        operation
        for operation in operation_matrix_data["operations"]
        if operation["method"] == "GET"
        and operation["path"] == "/api/v1/projects"
    )
    row["test_cases"].remove("auth")
    operation_matrix_path = tmp_path / "operation-matrix.yml"
    _write_yaml(operation_matrix_path, operation_matrix_data)

    with pytest.raises(
        validator.CaseMatrixValidationError,
        match="missing test_cases dimensions",
    ):
        validator.validate_case_matrix(case_matrix_path, operation_matrix_path)
