"""Lightweight OpenAPI response schema checks for integration tests."""
from __future__ import annotations

import re
from contextvars import ContextVar, Token
from typing import Any

from httpx import Response


_CURRENT_OPENAPI: ContextVar[dict[str, Any] | None] = ContextVar(
    "current_openapi",
    default=None,
)


def set_current_openapi(openapi: dict[str, Any]) -> Token[dict[str, Any] | None]:
    return _CURRENT_OPENAPI.set(openapi)


def reset_current_openapi(token: Token[dict[str, Any] | None]) -> None:
    _CURRENT_OPENAPI.reset(token)


def assert_current_openapi_response(
    response: Response,
    expected_status: int,
    body: Any | None = None,
) -> None:
    openapi = _CURRENT_OPENAPI.get()
    if openapi is None or expected_status < 200 or expected_status >= 300:
        return

    path = response.request.url.path
    method = response.request.method.upper()
    operation_path, operation = _operation_for(openapi, method, path)
    responses = operation.get("responses", {})
    response_spec = responses.get(str(expected_status))
    assert response_spec is not None, (
        f"{method} {operation_path} returned {expected_status}, "
        "but OpenAPI does not declare that response"
    )

    content = response_spec.get("content") or {}
    if expected_status == 204:
        assert content == {}, f"{method} {operation_path} 204 response declares content"
        return

    media_schema = content.get("application/json", {}).get("schema")
    if media_schema is None:
        assert not response.content, (
            f"{method} {operation_path} {expected_status} response has a body "
            "but OpenAPI does not declare application/json content"
        )
        return

    errors = _validate(openapi, media_schema, body, "$", ())
    assert errors == [], (
        f"{method} {operation_path} {expected_status} response does not match "
        f"OpenAPI schema: {errors[:8]}"
    )


def _operation_for(
    openapi: dict[str, Any],
    method: str,
    request_path: str,
) -> tuple[str, dict[str, Any]]:
    method_key = method.lower()
    path_item = openapi["paths"].get(request_path)
    if path_item and method_key in path_item:
        return request_path, path_item[method_key]

    candidates = []
    for template, candidate_item in openapi["paths"].items():
        if method_key not in candidate_item:
            continue
        regex = _template_regex(template)
        if regex.fullmatch(request_path):
            static_segments = sum(
                1
                for segment in template.split("/")
                if segment and not segment.startswith("{")
            )
            candidates.append((static_segments, template, candidate_item[method_key]))

    assert candidates, f"{method} {request_path} is not declared in OpenAPI"
    candidates.sort(reverse=True, key=lambda item: item[0])
    _, template, operation = candidates[0]
    return template, operation


def _template_regex(template: str) -> re.Pattern[str]:
    parts = []
    segments = template.split("/")
    for index, segment in enumerate(segments):
        if index > 0:
            parts.append("/")
        if not segment:
            continue
        if segment.startswith("{") and segment.endswith("}"):
            raw_name = segment[1:-1].split(":", 1)[0]
            if raw_name == "artifact_path" and index == len(segments) - 1:
                parts.append(".+")
            else:
                parts.append("[^/]+")
        else:
            parts.append(re.escape(segment))
    return re.compile("^" + "".join(parts) + "$")


def _validate(
    openapi: dict[str, Any],
    schema: dict[str, Any],
    value: Any,
    path: str,
    ref_stack: tuple[str, ...],
) -> list[str]:
    schema = _resolve_ref(openapi, schema, ref_stack)

    if "anyOf" in schema:
        variants = schema["anyOf"]
        if any(
            not _validate(openapi, variant, value, path, ref_stack)
            for variant in variants
        ):
            return []
        return [f"{path} does not match any anyOf variant"]

    if "oneOf" in schema:
        matches = [
            variant
            for variant in schema["oneOf"]
            if not _validate(openapi, variant, value, path, ref_stack)
        ]
        if len(matches) == 1:
            return []
        return [f"{path} matches {len(matches)} oneOf variants"]

    errors: list[str] = []
    for variant in schema.get("allOf", []):
        errors.extend(_validate(openapi, variant, value, path, ref_stack))
    if errors:
        return errors

    if "const" in schema and value != schema["const"]:
        return [f"{path} expected const {schema['const']!r}, got {value!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path} expected one of {schema['enum']!r}, got {value!r}"]

    schema_type = _schema_type(schema)
    if isinstance(schema_type, list):
        variant_errors = []
        for candidate_type in schema_type:
            candidate_schema = dict(schema)
            candidate_schema["type"] = candidate_type
            candidate_errors = _validate(
                openapi,
                candidate_schema,
                value,
                path,
                ref_stack,
            )
            if not candidate_errors:
                return []
            variant_errors.extend(candidate_errors)
        return [f"{path} does not match any type in {schema_type!r}: {variant_errors[:3]}"]

    if schema_type == "null":
        return [] if value is None else [f"{path} expected null, got {type(value).__name__}"]
    if schema_type == "object":
        return _validate_object(openapi, schema, value, path, ref_stack)
    if schema_type == "array":
        return _validate_array(openapi, schema, value, path, ref_stack)
    if schema_type == "string":
        return _validate_string(schema, value, path)
    if schema_type == "integer":
        return _validate_integer(schema, value, path)
    if schema_type == "number":
        return _validate_number(schema, value, path)
    if schema_type == "boolean":
        return [] if isinstance(value, bool) else [f"{path} expected boolean"]

    return []


def _resolve_ref(
    openapi: dict[str, Any],
    schema: dict[str, Any],
    ref_stack: tuple[str, ...],
) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if ref in ref_stack:
        return {}
    target = openapi
    for part in ref.removeprefix("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        target = target[part]
    merged = dict(target)
    merged.update({key: value for key, value in schema.items() if key != "$ref"})
    if "$ref" in merged:
        return _resolve_ref(openapi, merged, (*ref_stack, ref))
    return merged


def _schema_type(schema: dict[str, Any]) -> Any:
    if "type" in schema:
        return schema["type"]
    if "properties" in schema or "additionalProperties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return None


def _validate_object(
    openapi: dict[str, Any],
    schema: dict[str, Any],
    value: Any,
    path: str,
    ref_stack: tuple[str, ...],
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path} expected object, got {type(value).__name__}"]

    errors: list[str] = []
    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in value:
            errors.append(f"{path}.{key} is required")

    for key, property_schema in properties.items():
        if key not in value:
            continue
        errors.extend(
            _validate(openapi, property_schema, value[key], f"{path}.{key}", ref_stack)
        )

    additional = schema.get("additionalProperties")
    extra_keys = set(value) - set(properties)
    if additional is False and extra_keys:
        errors.append(f"{path} has undeclared properties {sorted(extra_keys)!r}")
    elif isinstance(additional, dict):
        for key in extra_keys:
            errors.extend(
                _validate(openapi, additional, value[key], f"{path}.{key}", ref_stack)
            )
    return errors


def _validate_array(
    openapi: dict[str, Any],
    schema: dict[str, Any],
    value: Any,
    path: str,
    ref_stack: tuple[str, ...],
) -> list[str]:
    if not isinstance(value, list):
        return [f"{path} expected array, got {type(value).__name__}"]

    errors: list[str] = []
    items = schema.get("items")
    if isinstance(items, dict):
        for index, item in enumerate(value):
            errors.extend(_validate(openapi, items, item, f"{path}[{index}]", ref_stack))
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{path} expected at least {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path} expected at most {schema['maxItems']} items")
    return errors


def _validate_string(schema: dict[str, Any], value: Any, path: str) -> list[str]:
    if not isinstance(value, str):
        return [f"{path} expected string, got {type(value).__name__}"]
    errors: list[str] = []
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{path} shorter than minLength {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(f"{path} longer than maxLength {schema['maxLength']}")
    if "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path} does not match pattern {schema['pattern']!r}")
    return errors


def _validate_integer(schema: dict[str, Any], value: Any, path: str) -> list[str]:
    if not isinstance(value, int) or isinstance(value, bool):
        return [f"{path} expected integer, got {type(value).__name__}"]
    return _validate_number_bounds(schema, value, path)


def _validate_number(schema: dict[str, Any], value: Any, path: str) -> list[str]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return [f"{path} expected number, got {type(value).__name__}"]
    return _validate_number_bounds(schema, value, path)


def _validate_number_bounds(
    schema: dict[str, Any],
    value: int | float,
    path: str,
) -> list[str]:
    errors: list[str] = []
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path} below minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path} above maximum {schema['maximum']}")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        errors.append(f"{path} below exclusiveMinimum {schema['exclusiveMinimum']}")
    if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
        errors.append(f"{path} above exclusiveMaximum {schema['exclusiveMaximum']}")
    return errors
