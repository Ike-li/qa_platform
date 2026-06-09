from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "tests" / "api_matrix" / "openapi_operation_matrix.yml"
VALIDATOR_PATH = ROOT / "scripts" / "validate_api_test_matrix.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_api_test_matrix",
        VALIDATOR_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    return validator.build_openapi()


def _matrix_data() -> dict[str, Any]:
    with MATRIX_PATH.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def _write_matrix(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_api_test_matrix_matches_current_openapi(openapi: dict[str, Any]) -> None:
    summary = validator.validate_matrix(MATRIX_PATH, openapi=openapi)

    assert summary == {
        "operations": 72,
        "covered": 72,
        "partial": 0,
        "blocked": 0,
    }


def test_api_test_matrix_rejects_missing_openapi_operation(
    tmp_path: Path,
    openapi: dict[str, Any],
) -> None:
    data = _matrix_data()
    data["operations"] = [
        operation
        for operation in data["operations"]
        if not (
            operation["method"] == "GET"
            and operation["path"] == "/api/v1/projects"
        )
    ]
    matrix_path = tmp_path / "matrix.yml"
    _write_matrix(matrix_path, data)

    with pytest.raises(validator.MatrixValidationError, match="missing OpenAPI"):
        validator.validate_matrix(matrix_path, openapi=openapi)


def test_api_test_matrix_rejects_incomplete_partial_row(
    tmp_path: Path,
    openapi: dict[str, Any],
) -> None:
    data = _matrix_data()
    data = deepcopy(data)
    row = next(
        operation
        for operation in data["operations"]
        if operation["method"] == "GET"
        and operation["path"] == "/api/v1/projects"
    )
    row["coverage_status"] = "partial"
    row["test_cases"].remove("schema_negative")
    row.pop("gap_notes")
    matrix_path = tmp_path / "matrix.yml"
    _write_matrix(matrix_path, data)

    with pytest.raises(validator.MatrixValidationError) as error:
        validator.validate_matrix(matrix_path, openapi=openapi)

    message = str(error.value)
    assert "partial status requires gap_notes" in message
    assert "missing test_cases dimensions ['schema_negative']" in message


def test_api_test_matrix_rejects_blocked_row_without_reason(
    tmp_path: Path,
    openapi: dict[str, Any],
) -> None:
    data = _matrix_data()
    data = deepcopy(data)
    row = next(
        operation
        for operation in data["operations"]
        if operation["method"] == "GET"
        and operation["path"] == "/api/v1/admin/status"
    )
    row["coverage_status"] = "blocked_by_missing_public_setup"
    row["test_cases"].remove("success")
    row.pop("gap_notes")
    matrix_path = tmp_path / "matrix.yml"
    _write_matrix(matrix_path, data)

    with pytest.raises(validator.MatrixValidationError, match="blocked_reason"):
        validator.validate_matrix(matrix_path, openapi=openapi)
