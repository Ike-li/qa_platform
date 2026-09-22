from __future__ import annotations

import argparse
import importlib.util
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_MATRIX = ROOT / "tests" / "api_matrix" / "openapi_test_case_matrix.yml"
DEFAULT_OPERATION_MATRIX = ROOT / "tests" / "api_matrix" / "openapi_operation_matrix.yml"


class CaseMatrixValidationError(AssertionError):
    """Raised when the atomic API test case matrix drifts from operation coverage."""


@dataclass(frozen=True)
class AtomicCase:
    case_id: str
    operation_id: str
    method: str
    path: str
    tag: str
    dimension: str
    status: str
    test_reference: str
    blocked_reason: str | None = None


def _load_operation_validator():
    validator_path = Path(__file__).with_name("validate_api_test_matrix.py")
    spec = importlib.util.spec_from_file_location(
        "validate_api_test_matrix",
        validator_path,
    )
    if spec is None or spec.loader is None:
        raise CaseMatrixValidationError("cannot load validate_api_test_matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


operation_validator = _load_operation_validator()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise CaseMatrixValidationError(f"{path}: root must be a mapping")
    return data


def _dimension_map(matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dimensions = matrix.get("dimensions")
    if not isinstance(dimensions, list):
        raise CaseMatrixValidationError("dimensions must be a list")

    result: dict[str, dict[str, Any]] = {}
    for index, dimension in enumerate(dimensions):
        if not isinstance(dimension, dict):
            raise CaseMatrixValidationError(f"dimensions[{index}] must be a mapping")
        dimension_id = dimension.get("id")
        if not isinstance(dimension_id, str) or not dimension_id:
            raise CaseMatrixValidationError(f"dimensions[{index}].id is required")
        if dimension_id in result:
            raise CaseMatrixValidationError(f"duplicate dimension {dimension_id}")
        if not isinstance(dimension.get("purpose"), str) or not dimension["purpose"]:
            raise CaseMatrixValidationError(f"{dimension_id}: purpose is required")
        if (
            not isinstance(dimension.get("test_reference"), str)
            or not dimension["test_reference"]
        ):
            raise CaseMatrixValidationError(f"{dimension_id}: test_reference is required")
        result[dimension_id] = dimension
    return result


def build_atomic_cases(
    case_matrix_path: Path = DEFAULT_CASE_MATRIX,
    operation_matrix_path: Path = DEFAULT_OPERATION_MATRIX,
) -> list[AtomicCase]:
    case_matrix = _load_yaml(case_matrix_path)
    operation_matrix = operation_validator.load_matrix(operation_matrix_path)
    dimensions = _dimension_map(case_matrix)
    required_dimensions = set(operation_validator.REQUIRED_DIMENSIONS)
    errors: list[str] = []

    if set(dimensions) != required_dimensions:
        errors.append(
            "dimensions must match required operation dimensions "
            f"{sorted(required_dimensions)}"
        )

    pattern = case_matrix.get("case_id_pattern")
    if pattern != "{operation_id}::{dimension}":
        errors.append("case_id_pattern must be {operation_id}::{dimension}")

    operations = operation_matrix.get("operations")
    if not isinstance(operations, list):
        errors.append("operation matrix operations must be a list")
        operations = []

    cases: list[AtomicCase] = []
    seen_case_ids: set[str] = set()

    for operation in operations:
        if not isinstance(operation, dict):
            errors.append("operation rows must be mappings")
            continue

        operation_id = str(operation.get("operation_id", ""))
        operation_key = f"{operation.get('method')} {operation.get('path')}"
        test_cases = set(operation.get("test_cases") or [])
        coverage_status = operation.get("coverage_status")

        for dimension_id, dimension in dimensions.items():
            blocked_reason: str | None = None
            if dimension_id in test_cases:
                status = "covered"
            elif (
                coverage_status == "blocked_by_missing_public_setup"
                and dimension_id == "success"
            ):
                status = "blocked_by_missing_public_setup"
                blocked_reason = operation.get("blocked_reason")
                if not isinstance(blocked_reason, str) or not blocked_reason:
                    errors.append(f"{operation_key}: blocked success lacks reason")
                    blocked_reason = None
            else:
                status = "missing"
                errors.append(
                    f"{operation_key}: missing atomic coverage for {dimension_id}"
                )

            case_id = f"{operation_id}::{dimension_id}"
            if case_id in seen_case_ids:
                errors.append(f"duplicate case_id {case_id}")
            seen_case_ids.add(case_id)

            cases.append(
                AtomicCase(
                    case_id=case_id,
                    operation_id=operation_id,
                    method=str(operation.get("method", "")),
                    path=str(operation.get("path", "")),
                    tag=str(operation.get("tag", "")),
                    dimension=dimension_id,
                    status=status,
                    test_reference=str(dimension["test_reference"]),
                    blocked_reason=blocked_reason,
                )
            )

    if errors:
        raise CaseMatrixValidationError("\n".join(errors))
    return cases


def validate_case_matrix(
    case_matrix_path: Path = DEFAULT_CASE_MATRIX,
    operation_matrix_path: Path = DEFAULT_OPERATION_MATRIX,
) -> dict[str, int]:
    try:
        operation_summary = operation_validator.validate_matrix(operation_matrix_path)
    except operation_validator.MatrixValidationError as exc:
        raise CaseMatrixValidationError(
            f"operation matrix validation failed:\n{exc}"
        ) from exc
    case_matrix = _load_yaml(case_matrix_path)
    dimensions = _dimension_map(case_matrix)
    cases = build_atomic_cases(case_matrix_path, operation_matrix_path)
    status_counts = Counter(case.status for case in cases)
    operation_ids = {case.operation_id for case in cases}

    summary = {
        "operations": len(operation_ids),
        "dimensions": len(dimensions),
        "cases": len(cases),
        "covered": status_counts["covered"],
        "blocked": status_counts["blocked_by_missing_public_setup"],
        "missing": status_counts["missing"],
    }

    metadata = case_matrix.get("metadata")
    errors: list[str] = []
    if not isinstance(metadata, dict):
        errors.append("metadata must be a mapping")
        metadata = {}

    expected_metadata = {
        "operation_count": summary["operations"],
        "dimension_count": summary["dimensions"],
        "case_count": summary["cases"],
        "covered_case_count": summary["covered"],
        "blocked_case_count": summary["blocked"],
        "missing_case_count": summary["missing"],
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            errors.append(f"metadata.{key} must equal {expected}")

    if metadata.get("operation_count") != operation_summary["operations"]:
        errors.append(
            "metadata.operation_count must match validated operation matrix count"
        )
    if summary["missing"]:
        errors.append("missing atomic cases are not allowed")

    if errors:
        raise CaseMatrixValidationError("\n".join(errors))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate atomic API test cases generated from the operation matrix."
    )
    parser.add_argument(
        "case_matrix",
        nargs="?",
        default=str(DEFAULT_CASE_MATRIX),
        help="Path to the atomic API test case matrix YAML.",
    )
    parser.add_argument(
        "--operation-matrix",
        default=str(DEFAULT_OPERATION_MATRIX),
        help="Path to the OpenAPI operation matrix YAML.",
    )
    args = parser.parse_args()

    summary = validate_case_matrix(
        Path(args.case_matrix),
        Path(args.operation_matrix),
    )
    print(
        "api_test_case_matrix_validation=passed "
        f"operations={summary['operations']} "
        f"dimensions={summary['dimensions']} "
        f"cases={summary['cases']} "
        f"covered={summary['covered']} "
        f"blocked={summary['blocked']} "
        f"missing={summary['missing']}"
    )


if __name__ == "__main__":
    main()
