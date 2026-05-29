from __future__ import annotations

import re
from pathlib import Path

import pytest

from qaplatform.config import Settings
from qaplatform.main import create_app


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_TYPES = ROOT / "frontend" / "src" / "types" / "api.ts"
RUN_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-runs.ts"


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="contract-test-secret-at-least-32bytes!",
        encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        debug=True,
        environment="test",
    )


@pytest.fixture(scope="module")
def openapi_schemas() -> dict:
    app = create_app(container=None, settings=_settings())
    return app.openapi()["components"]["schemas"]


def _schema_properties(schemas: dict, schema_name: str) -> set[str]:
    return set(schemas[schema_name]["properties"])


def _schema_required(schemas: dict, schema_name: str) -> set[str]:
    return set(schemas[schema_name].get("required", []))


def _frontend_source() -> str:
    return FRONTEND_TYPES.read_text(encoding="utf-8")


def _interface_properties(interface_name: str) -> set[str]:
    source = _frontend_source()
    match = re.search(
        rf"export interface {re.escape(interface_name)}(?:<[^>]+>)?\s*\{{(?P<body>.*?)\n\}}",
        source,
        re.DOTALL,
    )
    assert match is not None, f"{interface_name} interface missing"
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??:", match.group("body"), re.MULTILINE))


@pytest.mark.parametrize(
    ("schema_name", "interface_name"),
    [
        ("ProjectResponse", "Project"),
        ("PipelineResponse", "Pipeline"),
        ("EnvironmentResponse", "EnvironmentResponse"),
        ("RunResponse", "RunResponse"),
        ("ArtifactResponse", "Artifact"),
        ("TestResultResponse", "TestResult"),
        ("NotificationRuleResponse", "NotificationRule"),
    ],
)
def test_frontend_response_models_include_backend_openapi_fields(
    openapi_schemas: dict,
    schema_name: str,
    interface_name: str,
):
    backend_fields = _schema_properties(openapi_schemas, schema_name)
    frontend_fields = _interface_properties(interface_name)

    assert backend_fields <= frontend_fields


@pytest.mark.parametrize(
    ("schema_name", "interface_name"),
    [
        ("ProjectCreate", "ProjectCreatePayload"),
        ("PipelineCreate", "PipelineCreatePayload"),
        ("EnvironmentCreate", "CreateEnvironmentPayload"),
    ],
)
def test_frontend_create_payloads_keep_backend_required_fields(
    openapi_schemas: dict,
    schema_name: str,
    interface_name: str,
):
    backend_required = _schema_required(openapi_schemas, schema_name)
    frontend_fields = _interface_properties(interface_name)

    assert backend_required <= frontend_fields


def test_notification_create_payload_keeps_backend_required_channels(openapi_schemas: dict):
    backend_required = _schema_required(openapi_schemas, "NotificationRuleCreate")
    source = _frontend_source()

    assert {"name", "channels"} <= backend_required
    assert 'export type NotificationRuleCreatePayload = Pick<' in source
    for field in ("name", "enabled", "conditions", "channels", "template"):
        assert f'"{field}"' in source


def test_trigger_run_payload_maps_to_backend_run_trigger_contract(openapi_schemas: dict):
    backend_fields = _schema_properties(openapi_schemas, "RunTrigger")
    backend_required = _schema_required(openapi_schemas, "RunTrigger")
    payload_fields = _interface_properties("TriggerRunPayload")
    run_hook = RUN_HOOK.read_text(encoding="utf-8")

    assert backend_fields == {"pipeline_id", "git_ref", "git_sha", "environment_id", "priority"}
    assert backend_required == {"pipeline_id"}
    assert {"pipeline_id", "branch", "git_sha", "environment_id", "priority"} <= payload_fields
    assert "git_ref: runData.branch" in run_hook
    assert "pipeline_id: runData.pipeline_id" in run_hook
    assert "git_sha: runData.git_sha" in run_hook
    assert "environment_id: runData.environment_id" in run_hook
    assert "priority: runData.priority ?? 1" in run_hook


def test_frontend_paginated_response_matches_backend_shape(openapi_schemas: dict):
    backend_fields = _schema_properties(openapi_schemas, "PaginatedResponse_RunResponse_")
    frontend_fields = _interface_properties("PaginatedResponse")

    assert backend_fields == {"data", "page", "per_page", "total"}
    assert backend_fields <= frontend_fields
