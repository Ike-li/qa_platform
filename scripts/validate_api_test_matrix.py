from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from qaplatform.config import Settings
from qaplatform.main import create_app

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "tests" / "api_matrix" / "openapi_operation_matrix.yml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
TARGET_PATHS = {"/health", "/ready", "/webhooks/{provider}"}
ALLOWED_STATUSES = {
    "covered",
    "partial",
    "blocked_by_missing_public_setup",
    "missing",
}
REQUIRED_DIMENSIONS = {
    "contract",
    "auth",
    "success",
    "schema_negative",
    "rbac_tenant",
    "declared_responses",
}


class MatrixValidationError(AssertionError):
    """Raised when the OpenAPI API test matrix drifts from the contract."""


def _contract_settings() -> Settings:
    return Settings(
        database_url=(
            "postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform"
        ),
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="contract-test-secret-at-least-32bytes!",
        encryption_key=(
            "0123456789abcdef0123456789abcdef"
            "0123456789abcdef0123456789abcdef"
        ),
        debug=True,
        environment="test",
        _env_file=None,
    )


def build_openapi() -> dict[str, Any]:
    app = create_app(container=None, settings=_contract_settings())
    return app.openapi()


def _is_target_path(path: str) -> bool:
    return path.startswith("/api/v1/") or path in TARGET_PATHS


def _has_http_bearer_security(operation: dict[str, Any]) -> bool:
    return any("HTTPBearer" in requirement for requirement in operation.get("security") or [])


def openapi_operations(openapi: dict[str, Any]) -> dict[str, dict[str, Any]]:
    operations: dict[str, dict[str, Any]] = {}
    for path, path_item in sorted(openapi["paths"].items()):
        if not _is_target_path(path):
            continue
        for method, operation in sorted(path_item.items()):
            if method not in HTTP_METHODS:
                continue
            method_upper = method.upper()
            key = f"{method_upper} {path}"
            operations[key] = {
                "method": method_upper,
                "path": path,
                "tag": (operation.get("tags") or ["untagged"])[0],
                "auth_type": (
                    "HTTPBearer" if _has_http_bearer_security(operation) else "public"
                ),
                "request_schema": "body" if operation.get("requestBody") else "none",
                "declared_responses": set(operation.get("responses", {})),
            }
    return operations


def load_matrix(matrix_path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    with matrix_path.open(encoding="utf-8") as file:
        matrix = yaml.safe_load(file)
    if not isinstance(matrix, dict):
        raise MatrixValidationError("matrix root must be a mapping")
    return matrix


def _normalize_responses(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(status) for status in value}


def _normalize_cases(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(case) for case in value}


def validate_matrix(
    matrix_path: Path = DEFAULT_MATRIX,
    openapi: dict[str, Any] | None = None,
) -> dict[str, int]:
    matrix = load_matrix(matrix_path)
    operations = openapi_operations(openapi or build_openapi())
    errors: list[str] = []

    metadata = matrix.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata must be a mapping")
        metadata = {}
    if metadata.get("operation_count") != len(operations):
        errors.append(
            "metadata.operation_count must equal OpenAPI target operation count "
            f"({len(operations)})"
        )

    entries = matrix.get("operations")
    if not isinstance(entries, list):
        errors.append("operations must be a list")
        entries = []

    seen: dict[str, dict[str, Any]] = {}
    duplicate_keys: set[str] = set()
    operation_ids: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"operations[{index}] must be a mapping")
            continue

        method = str(entry.get("method", "")).upper()
        path = str(entry.get("path", ""))
        key = f"{method} {path}"
        if key in seen:
            duplicate_keys.add(key)
        seen[key] = entry

        operation_id = entry.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            errors.append(f"{key}: operation_id is required")
        elif operation_id in operation_ids:
            errors.append(f"{key}: duplicate operation_id {operation_id}")
        else:
            operation_ids.add(operation_id)

        spec = operations.get(key)
        if spec is None:
            continue

        for field in ("tag", "auth_type", "request_schema"):
            if entry.get(field) != spec[field]:
                errors.append(
                    f"{key}: {field}={entry.get(field)!r} does not match OpenAPI "
                    f"{spec[field]!r}"
                )

        matrix_responses = _normalize_responses(entry.get("declared_responses"))
        if matrix_responses != spec["declared_responses"]:
            errors.append(
                f"{key}: declared_responses={sorted(matrix_responses)} does not "
                f"match OpenAPI {sorted(spec['declared_responses'])}"
            )

        coverage_status = entry.get("coverage_status")
        if coverage_status not in ALLOWED_STATUSES:
            errors.append(f"{key}: invalid coverage_status {coverage_status!r}")
        elif coverage_status == "missing":
            errors.append(f"{key}: coverage_status cannot remain missing")

        test_cases = _normalize_cases(entry.get("test_cases"))
        required_dimensions = set(REQUIRED_DIMENSIONS)
        if coverage_status == "blocked_by_missing_public_setup":
            required_dimensions.remove("success")
            if not entry.get("blocked_reason"):
                errors.append(f"{key}: blocked status requires blocked_reason")
        elif coverage_status == "partial" and not entry.get("gap_notes"):
            errors.append(f"{key}: partial status requires gap_notes")

        missing_dimensions = required_dimensions - test_cases
        if missing_dimensions:
            errors.append(
                f"{key}: missing test_cases dimensions "
                f"{sorted(missing_dimensions)}"
            )

    if duplicate_keys:
        errors.append(f"duplicate operation rows: {sorted(duplicate_keys)}")

    expected_keys = set(operations)
    seen_keys = set(seen)
    missing_keys = expected_keys - seen_keys
    extra_keys = seen_keys - expected_keys
    if missing_keys:
        errors.append(f"missing OpenAPI operations: {sorted(missing_keys)}")
    if extra_keys:
        errors.append(f"matrix has operations not present in OpenAPI: {sorted(extra_keys)}")

    if errors:
        raise MatrixValidationError("\n".join(errors))

    status_counts = Counter(str(entry["coverage_status"]) for entry in entries)
    return {
        "operations": len(operations),
        "covered": status_counts["covered"],
        "partial": status_counts["partial"],
        "blocked": status_counts["blocked_by_missing_public_setup"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the API test matrix against create_app().openapi()."
    )
    parser.add_argument(
        "matrix",
        nargs="?",
        default=str(DEFAULT_MATRIX),
        help="Path to the OpenAPI operation test matrix YAML.",
    )
    args = parser.parse_args()

    summary = validate_matrix(Path(args.matrix))
    print(
        "api_test_matrix_validation=passed "
        f"operations={summary['operations']} "
        f"covered={summary['covered']} "
        f"partial={summary['partial']} "
        f"blocked={summary['blocked']}"
    )


if __name__ == "__main__":
    main()
