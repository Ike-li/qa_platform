"""OpenAPI-driven API contract smoke tests.

The OpenAPI document is the source of truth for route enumeration. Runtime
requests intentionally use an app with no auth dependency override so protected
operations prove their real unauthenticated rejection path.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import pytest

from qaplatform.config import Settings


pytestmark = [
    pytest.mark.openapi_contract,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
]

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
GLOBAL_DECLARED_STATUS_ALLOWLIST = {"401", "422"}
PROTECTED_REJECTION_STATUSES = {401, 422}
STABLE_UUID = "11111111-1111-4111-8111-111111111111"

PUBLIC_EXPECTED_STATUSES: dict[tuple[str, str], set[int]] = {
    ("GET", "/health"): {200},
    ("GET", "/ready"): {200},
    ("POST", "/api/v1/auth/login"): {422},
    ("POST", "/api/v1/auth/logout"): {204},
    ("POST", "/api/v1/auth/refresh"): {401},
    ("POST", "/api/v1/auth/register"): {422},
    ("GET", "/api/v1/artifacts/{artifact_id}/preview/{token}/{artifact_path}"): {
        503
    },
    ("GET", "/api/v1/runs/{run_id}/events"): {401},
    ("GET", "/api/v1/runs/{run_id}/logs"): {401},
    ("POST", "/api/v1/webhooks/{provider}"): {400},
    ("POST", "/webhooks/{provider}"): {400},
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    spec: dict[str, Any]


def _contract_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://contract:contract@localhost/contract",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        s3_bucket="qa-platform-contract",
        jwt_secret="test-secret-key-at-least-32bytes!",
        encryption_key="0" * 64,
        debug=True,
        environment="test",
        rate_limit_per_minute=10_000,
        rate_limit_auth_failure=10_000,
        _env_file=None,
    )


def _build_openapi() -> dict[str, Any]:
    from qaplatform.api import create_app
    from qaplatform.dependencies import init_container

    settings = _contract_settings()
    app = create_app(container=init_container(settings), settings=settings)
    return app.openapi()


def _is_target_path(path: str) -> bool:
    return (
        path.startswith("/api/v1/")
        or path in {"/health", "/ready", "/webhooks/{provider}"}
    )


def _operations_from(openapi: dict[str, Any]) -> tuple[Operation, ...]:
    operations: list[Operation] = []
    for path, path_item in sorted(openapi["paths"].items()):
        if not _is_target_path(path):
            continue
        for method, operation in sorted(path_item.items()):
            if method not in HTTP_METHODS:
                continue
            operations.append(Operation(method=method.upper(), path=path, spec=operation))
    return tuple(operations)


OPENAPI = _build_openapi()
CONTRACT_OPERATIONS = _operations_from(OPENAPI)


def _operation_id(operation: Operation) -> str:
    return f"{operation.method} {operation.path}"


def _operation_case_id(operation: Operation) -> str:
    path = operation.path.strip("/")
    path = re.sub(r"\{([^}:]+)(?::[^}]+)?\}", r"\1", path)
    path = re.sub(r"[^0-9A-Za-z]+", "_", path)
    path = re.sub(r"_+", "_", path).strip("_")
    return f"{operation.method.lower()}_{path}"


def _case_id(dimension: str):
    def build_id(operation: Operation) -> str:
        return f"{_operation_case_id(operation)}::{dimension}"

    return build_id


def _has_http_bearer_security(operation: Operation) -> bool:
    for requirement in operation.spec.get("security") or []:
        if "HTTPBearer" in requirement:
            return True
    return False


def _schema_without_null(schema: dict[str, Any]) -> dict[str, Any]:
    for key in ("anyOf", "oneOf"):
        variants = schema.get(key)
        if isinstance(variants, list):
            for variant in variants:
                if variant.get("type") != "null":
                    return variant
    return schema


def _parameter_value(name: str, schema: dict[str, Any]) -> Any:
    schema = _schema_without_null(schema)
    if name == "provider":
        return "github"
    if name == "token":
        return "invalid-token"
    if name == "artifact_path":
        return "index.html"
    if "enum" in schema:
        return schema["enum"][0]

    schema_type = schema.get("type")
    if schema.get("format") == "uuid" or name.endswith("_id"):
        return STABLE_UUID
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1
    if schema_type == "boolean":
        return True
    return "smoke"


def _parameter_specs(operation: Operation, location: str) -> dict[str, dict[str, Any]]:
    return {
        parameter["name"]: parameter
        for parameter in operation.spec.get("parameters", [])
        if parameter.get("in") == location
    }


def _request_path(operation: Operation) -> str:
    path_parameters = _parameter_specs(operation, "path")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).split(":", 1)[0]
        parameter = path_parameters.get(name, {})
        value = _parameter_value(name, parameter.get("schema", {}))
        return str(value)

    return re.sub(r"\{([^}]+)\}", replace, operation.path)


def _request_query(operation: Operation) -> dict[str, Any]:
    query: dict[str, Any] = {}
    for name, parameter in _parameter_specs(operation, "query").items():
        if not parameter.get("required"):
            continue
        query[name] = _parameter_value(name, parameter.get("schema", {}))
    return query


def _is_error_body(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    if "detail" in body:
        return body["detail"] not in (None, "", [])
    error = body.get("error")
    if not isinstance(error, dict):
        return False
    return isinstance(error.get("code"), str) and isinstance(
        error.get("message"), str
    )


def _assert_json_response(response) -> Any:
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type
    return response.json()


def _expected_runtime_statuses(operation: Operation) -> set[int]:
    if _has_http_bearer_security(operation):
        return PROTECTED_REJECTION_STATUSES
    return PUBLIC_EXPECTED_STATUSES[(operation.method, operation.path)]


def _assert_declared_runtime_status(operation: Operation, status_code: int) -> None:
    declared_statuses = set(operation.spec.get("responses", {}))
    allowed_statuses = declared_statuses | GLOBAL_DECLARED_STATUS_ALLOWLIST
    assert str(status_code) in allowed_statuses


def test_openapi_declares_bearer_scheme() -> None:
    assert OPENAPI["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }


def test_contract_enumerates_every_target_operation() -> None:
    target_keys = {
        (method.upper(), path)
        for path, path_item in OPENAPI["paths"].items()
        if _is_target_path(path)
        for method in path_item
        if method in HTTP_METHODS
    }
    covered_keys = {(operation.method, operation.path) for operation in CONTRACT_OPERATIONS}
    assert covered_keys == target_keys


def test_public_operations_are_explicitly_allowlisted() -> None:
    unlisted_public = [
        _operation_id(operation)
        for operation in CONTRACT_OPERATIONS
        if not _has_http_bearer_security(operation)
        and (operation.method, operation.path) not in PUBLIC_EXPECTED_STATUSES
    ]
    assert unlisted_public == []


@pytest.mark.parametrize(
    "operation",
    CONTRACT_OPERATIONS,
    ids=_case_id("contract"),
)
def test_openapi_atomic_contract_case(operation: Operation) -> None:
    assert operation.spec.get("responses")
    assert operation.spec.get("operationId")
    assert "{" not in _request_path(operation)
    assert "}" not in _request_path(operation)

    for status in operation.spec["responses"]:
        assert status == "default" or status.isdigit()

    if _has_http_bearer_security(operation):
        assert operation.spec.get("security")
    else:
        assert (operation.method, operation.path) in PUBLIC_EXPECTED_STATUSES


@pytest.mark.parametrize(
    "operation",
    CONTRACT_OPERATIONS,
    ids=_case_id("auth"),
)
async def test_openapi_atomic_auth_case(
    no_auth_integration_client,
    operation: Operation,
) -> None:
    is_protected = _has_http_bearer_security(operation)

    response = await no_auth_integration_client.request(
        operation.method,
        _request_path(operation),
        params=_request_query(operation),
    )

    assert response.status_code in _expected_runtime_statuses(operation), response.text

    if response.status_code == 204:
        assert response.content == b""
        return

    body = _assert_json_response(response)
    if is_protected:
        assert response.status_code in PROTECTED_REJECTION_STATUSES
        assert _is_error_body(body)


@pytest.mark.parametrize(
    "operation",
    CONTRACT_OPERATIONS,
    ids=_case_id("declared_responses"),
)
async def test_openapi_atomic_declared_responses_case(
    no_auth_integration_client,
    operation: Operation,
) -> None:
    response = await no_auth_integration_client.request(
        operation.method,
        _request_path(operation),
        params=_request_query(operation),
    )

    assert response.status_code in _expected_runtime_statuses(operation), response.text
    _assert_declared_runtime_status(operation, response.status_code)

    if response.status_code == 204:
        assert response.content == b""
        return

    body = _assert_json_response(response)
    if response.status_code >= 400:
        assert _is_error_body(body)
        return

    if operation.path == "/health":
        assert body["status"] == "ok"
        assert isinstance(body.get("version"), str)
    elif operation.path == "/ready":
        assert body["status"] == "ok"
        assert body["checks"] == {"db": "ok", "redis": "ok"}
