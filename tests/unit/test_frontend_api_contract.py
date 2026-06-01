from __future__ import annotations

import re
from pathlib import Path

import pytest

from qaplatform.config import Settings
from qaplatform.main import create_app


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_TYPES = ROOT / "frontend" / "src" / "types" / "api.ts"
RUN_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-runs.ts"
API_TOKENS_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-api-tokens.ts"
PROJECTS_LIST_PAGE = ROOT / "frontend" / "src" / "pages" / "projects" / "list.tsx"
RUNS_LIST_PAGE = ROOT / "frontend" / "src" / "pages" / "runs" / "list.tsx"
RUN_DETAIL_PAGE = ROOT / "frontend" / "src" / "pages" / "runs" / "detail.tsx"
TEST_STATUS_ICON = ROOT / "frontend" / "src" / "components" / "test-status-icon.tsx"
TEST_RESULTS_TABLE = ROOT / "frontend" / "src" / "components" / "test-results-table.tsx"
NOTIFICATION_RULES_PANEL = ROOT / "frontend" / "src" / "components" / "projects" / "notification-rules-panel.tsx"
ANALYTICS_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-analytics.ts"
ANALYTICS_PANEL = ROOT / "frontend" / "src" / "components" / "projects" / "analytics-panel.tsx"
SETTINGS_PAGE = ROOT / "frontend" / "src" / "pages" / "settings.tsx"
E2E_HELPERS = ROOT / "tests" / "e2e" / "helpers.ts"

_SCHEMA_REF_TYPE_ALIASES = {
    "CollectorDefinitionInput": "PipelineCollector",
    "NotificationChannelPayload": "NotificationChannel",
    "StageDefinitionInput": "PipelineStage",
}


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
        _env_file=None,
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
    return set(_interface_members(interface_name))


def _interface_members(interface_name: str) -> dict[str, dict[str, object]]:
    source = _frontend_source()
    match = re.search(
        rf"export interface {re.escape(interface_name)}(?:<[^>]+>)?\s*\{{(?P<body>.*?)\n\}}",
        source,
        re.DOTALL,
    )
    assert match is not None, f"{interface_name} interface missing"
    members: dict[str, dict[str, object]] = {}
    for member in re.finditer(
        r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<optional>\?)?:\s*(?P<type>.*?);",
        match.group("body"),
        re.MULTILINE,
    ):
        members[member.group("name")] = {
            "optional": bool(member.group("optional")),
            "type": member.group("type").strip(),
        }
    return members


def _type_aliases() -> dict[str, str]:
    source = _frontend_source()
    return {
        match.group("name"): match.group("body").strip()
        for match in re.finditer(
            r"export type (?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<body>.*?);",
            source,
            re.DOTALL,
        )
    }


def _literal_values(type_source: str) -> set[str]:
    aliases = _type_aliases()
    values = set(re.findall(r'"([^"]+)"', type_source))
    for token in re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", type_source):
        values.update(re.findall(r'"([^"]+)"', aliases.get(token, "")))
    return values


def _union_parts(type_source: str) -> set[str]:
    return {part.strip() for part in type_source.split("|")}


def _ref_schema_name(schema: dict) -> str | None:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return None
    return ref.rsplit("/", 1)[-1]


def _base_schema_name(schema_name: str | None) -> str | None:
    if schema_name is None:
        return None
    return re.sub(r"-(Input|Output)$", "", schema_name)


def _expected_ts_ref_name(schema_name: str) -> str:
    return _SCHEMA_REF_TYPE_ALIASES.get(schema_name, schema_name)


def _array_item_type(ts_type: str) -> str | None:
    match = re.fullmatch(r"(?P<item>.+)\[\]", ts_type)
    if match:
        return match.group("item").strip()
    match = re.fullmatch(r"Array<(?P<item>.+)>", ts_type)
    if match:
        return match.group("item").strip()
    return None


def _non_null_schema(schema: dict) -> dict:
    for branch_key in ("anyOf", "oneOf"):
        if branch_key in schema:
            branches = [
                branch for branch in schema[branch_key]
                if branch.get("type") != "null"
            ]
            assert len(branches) == 1, f"ambiguous schema branch: {schema}"
            return branches[0]
    return schema


def _schema_allows_null(schema: dict) -> bool:
    return any(
        branch.get("type") == "null"
        for branch_key in ("anyOf", "oneOf")
        for branch in schema.get(branch_key, [])
    )


def _assert_frontend_type_matches_schema(field_name: str, schema: dict, ts_type: str):
    non_null_schema = _non_null_schema(schema)
    schema_type = non_null_schema.get("type")

    if _schema_allows_null(schema):
        assert "null" in ts_type, f"{field_name} can be null in OpenAPI"
    else:
        assert "null" not in _union_parts(ts_type), f"{field_name} cannot be null in OpenAPI"

    if "enum" in non_null_schema:
        expected_values = set(non_null_schema["enum"])
        assert _literal_values(ts_type) == expected_values, field_name
        assert "string" not in _union_parts(ts_type), f"{field_name} is broader than OpenAPI enum"
    elif schema_type in {"integer", "number"}:
        assert "number" in ts_type, field_name
    elif schema_type == "boolean":
        assert "boolean" in ts_type, field_name
    elif schema_type == "string":
        assert "string" in ts_type or _literal_values(ts_type), field_name
    elif schema_type == "array":
        item_type = _array_item_type(ts_type)
        assert item_type is not None, field_name
        item_schema = non_null_schema["items"]
        item_union_refs = {
            _base_schema_name(_ref_schema_name(_non_null_schema(branch)))
            for branch_key in ("anyOf", "oneOf")
            for branch in item_schema.get(branch_key, [])
        }
        notification_condition_union_refs = {
            frozenset(
                {
                    "NotificationConditionLeaf",
                    "NotificationConditionAllGroup",
                    "NotificationConditionAnyGroup",
                }
            ),
            frozenset(
                {
                    "NotificationConditionLeaf",
                    "NotificationConditionResponseAllGroup",
                    "NotificationConditionResponseAnyGroup",
                    "NotificationInvalidCondition",
                }
            ),
        }
        if frozenset(item_union_refs) in notification_condition_union_refs:
            assert item_type == "NotificationConditionExpression", field_name
            return
        item_schema = _non_null_schema(item_schema)
        item_ref = _ref_schema_name(item_schema)
        if item_ref is not None:
            assert item_type == _expected_ts_ref_name(item_ref), field_name
        elif item_schema.get("type") == "string":
            assert item_type == "string" or _literal_values(item_type), field_name
        elif item_schema.get("type") in {"integer", "number"}:
            assert item_type == "number", field_name
        elif item_schema.get("type") == "boolean":
            assert item_type == "boolean", field_name
        elif item_schema.get("type") == "object":
            assert (
                item_type.startswith("Record<")
                or item_type == "unknown"
                or re.fullmatch(r"[A-Z][A-Za-z0-9_]*", item_type)
            ), field_name
        else:
            raise AssertionError(f"unsupported array item schema for {field_name}: {schema}")
    elif schema_type == "object":
        assert (
            "Record<" in ts_type
            or "unknown" in ts_type
            or re.search(r"\b[A-Z][A-Za-z0-9_]*\b", ts_type)
        ), field_name
    elif "$ref" in non_null_schema:
        assert ts_type and ts_type != "unknown", field_name
    else:
        raise AssertionError(f"unsupported schema for {field_name}: {schema}")


@pytest.mark.parametrize(
    ("schema_name", "interface_name"),
    [
        ("ProjectResponse", "Project"),
        ("PipelineResponse", "Pipeline"),
        ("EnvironmentResponse", "EnvironmentResponse"),
        ("RunResponse", "RunResponse"),
        ("ArtifactResponse", "Artifact"),
        ("TestResultResponse", "TestResult"),
        ("TestHistoryPoint", "TestHistoryPoint"),
        ("NotificationRuleResponse", "NotificationRule"),
        ("ApiTokenResponse", "ApiTokenResponse"),
        ("ApiTokenListItem", "ApiTokenListItem"),
    ],
)
def test_frontend_response_models_include_backend_openapi_fields(
    openapi_schemas: dict,
    schema_name: str,
    interface_name: str,
):
    backend_fields = _schema_properties(openapi_schemas, schema_name)
    frontend_fields = _interface_properties(interface_name)

    assert frontend_fields == backend_fields


@pytest.mark.parametrize(
    ("schema_name", "interface_name"),
    [
        ("ProjectResponse", "Project"),
        ("PipelineResponse", "Pipeline"),
        ("EnvironmentResponse", "EnvironmentResponse"),
        ("RunResponse", "RunResponse"),
        ("ArtifactResponse", "Artifact"),
        ("TestResultResponse", "TestResult"),
        ("TestHistoryPoint", "TestHistoryPoint"),
        ("NotificationRuleResponse", "NotificationRule"),
        ("ApiTokenResponse", "ApiTokenResponse"),
        ("ApiTokenListItem", "ApiTokenListItem"),
    ],
)
def test_frontend_response_models_match_backend_types_and_nullability(
    openapi_schemas: dict,
    schema_name: str,
    interface_name: str,
):
    backend_properties = openapi_schemas[schema_name]["properties"]
    backend_required = _schema_required(openapi_schemas, schema_name)
    frontend_members = _interface_members(interface_name)

    for field_name, schema in backend_properties.items():
        frontend_member = frontend_members[field_name]
        if field_name in backend_required:
            assert frontend_member["optional"] is False, field_name
        _assert_frontend_type_matches_schema(
            field_name,
            schema,
            str(frontend_member["type"]),
        )


@pytest.mark.parametrize(
    ("schema_name", "interface_name"),
    [
        ("ProjectCreate", "ProjectCreatePayload"),
        ("PipelineCreate", "PipelineCreatePayload"),
        ("EnvironmentCreate", "CreateEnvironmentPayload"),
        ("CreateTokenRequest", "CreateApiTokenPayload"),
    ],
)
def test_frontend_create_payloads_keep_backend_required_fields(
    openapi_schemas: dict,
    schema_name: str,
    interface_name: str,
):
    backend_properties = openapi_schemas[schema_name]["properties"]
    backend_required = _schema_required(openapi_schemas, schema_name)
    frontend_members = _interface_members(interface_name)

    assert set(frontend_members) == set(backend_properties)
    for field_name, schema in backend_properties.items():
        if field_name not in backend_required:
            assert frontend_members[field_name]["optional"] is True, field_name
            _assert_frontend_type_matches_schema(
                field_name,
                schema,
                str(frontend_members[field_name]["type"]),
            )
            continue
        assert frontend_members[field_name]["optional"] is False, field_name
        _assert_frontend_type_matches_schema(
            field_name,
            schema,
            str(frontend_members[field_name]["type"]),
        )


def test_notification_create_payload_matches_backend_required_field_contract(
    openapi_schemas: dict,
):
    backend_required = _schema_required(openapi_schemas, "NotificationRuleCreate")
    channel_schema = openapi_schemas["NotificationChannelPayload"]
    condition_schema = openapi_schemas["NotificationConditionLeaf"]
    invalid_condition_schema = openapi_schemas["NotificationInvalidCondition"]
    condition_refs = {
        _base_schema_name(_ref_schema_name(_non_null_schema(branch)))
        for branch in openapi_schemas["NotificationRuleCreate"]["properties"]["conditions"][
            "items"
        ]["anyOf"]
    }
    response_condition_refs = {
        _base_schema_name(_ref_schema_name(_non_null_schema(branch)))
        for branch in openapi_schemas["NotificationRuleResponse"]["properties"]["conditions"][
            "items"
        ]["anyOf"]
    }
    source = _frontend_source()

    assert backend_required == {"name", "channels"}
    assert openapi_schemas["NotificationRuleCreate"]["properties"]["channels"]["items"] == {
        "$ref": "#/components/schemas/NotificationChannelPayload"
    }
    assert openapi_schemas["NotificationRuleResponse"]["properties"]["channels"]["items"] == {
        "$ref": "#/components/schemas/NotificationChannelPayload"
    }
    assert _schema_required(openapi_schemas, "NotificationChannelPayload") == {"type"}
    assert set(channel_schema["properties"]) == {"type", "config", "template"}
    assert set(channel_schema["properties"]["type"]["enum"]) == {
        "email",
        "webhook",
        "dingtalk",
        "wecom",
    }
    assert condition_refs == {
        "NotificationConditionLeaf",
        "NotificationConditionAllGroup",
        "NotificationConditionAnyGroup",
    }
    assert response_condition_refs == {
        "NotificationConditionLeaf",
        "NotificationConditionResponseAllGroup",
        "NotificationConditionResponseAnyGroup",
        "NotificationInvalidCondition",
    }
    assert "NotificationInvalidCondition" not in repr(
        openapi_schemas["NotificationRuleCreate"]["properties"]["conditions"]
    )
    assert set(invalid_condition_schema["properties"]) == {
        "invalid",
        "reason",
        "raw_field",
        "raw_operator",
    }
    assert set(condition_schema["properties"]["field"]["enum"]) == {
        "status",
        "pass_rate",
        "failed",
        "consecutive_failures",
    }
    assert set(condition_schema["properties"]["operator"]["enum"]) == {
        "eq",
        "ne",
        "lt",
        "gt",
        "lte",
        "gte",
    }
    assert "consecutive_failed_runs" not in repr(openapi_schemas)
    aliases = _type_aliases()
    assert "export interface NotificationInvalidCondition" in source
    assert "raw_operator?: string | null" in source
    assert "export type NotificationConditionInputExpression" in source
    assert "NotificationInvalidCondition" not in aliases[
        "NotificationConditionInputExpression"
    ]
    assert "export interface NotificationRuleCreatePayload" in source
    create_members = _interface_members("NotificationRuleCreatePayload")
    assert set(create_members) == {"name", "enabled", "conditions", "channels", "template"}
    assert create_members["conditions"]["type"] == "NotificationConditionInputExpression[]"
    assert create_members["channels"]["type"] == "NotificationChannel[]"


def test_notification_rule_ui_matches_supported_channel_contract():
    types_source = _frontend_source()
    panel_source = NOTIFICATION_RULES_PANEL.read_text(encoding="utf-8")

    assert (
        'export type NotificationChannelType = "email" | "webhook" | "dingtalk" | "wecom";'
        in types_source
    )
    assert 'const CHANNEL_TYPES: NotificationChannel["type"][] = [' in panel_source
    for channel_type in ('"email"', '"webhook"', '"dingtalk"', '"wecom"'):
        assert channel_type in panel_source
    assert '"slack"' not in types_source

    assert "to_addresses" in panel_source
    assert 'update("to",' not in panel_source
    assert "smtp_host" in panel_source
    assert "from_address" in panel_source
    assert "access_token" in panel_source
    assert "webhook_key" in panel_source
    assert "normalized.template = template" in panel_source

    assert "function nextAvailableChannelType" in panel_source
    assert "function channelTypeOptions" in panel_source
    assert "hasDuplicateChannelTypes" in panel_source
    assert 'toast.error(t("notifications.duplicateChannels"))' in panel_source
    assert "disabled={!nextChannelType}" in panel_source

    assert '"consecutive_failures"' in types_source
    assert '"consecutive_failed_runs"' not in types_source
    assert "NotificationConditionExpression" in types_source
    assert "all?: NotificationConditionExpression[]" in types_source
    assert "any?: NotificationConditionExpression[]" in types_source
    assert "function isConditionLeaf" in panel_source
    assert "condition is NotificationCondition" in panel_source
    assert "const CONDITION_MODES = [\"all\", \"any\"] as const" in panel_source
    assert "conditionModeFromRule" in panel_source
    assert "NotificationConditionInputExpression[]" in panel_source
    assert "serializeConditionsForSave(conditionMode, conditions)" in panel_source
    assert "notifications.condition.field.${f}" in panel_source


def test_analytics_ui_exposes_single_test_history_contract(openapi_schemas: dict):
    types_source = _frontend_source()
    hook_source = ANALYTICS_HOOK.read_text(encoding="utf-8")
    panel_source = ANALYTICS_PANEL.read_text(encoding="utf-8")

    assert "TestHistoryResponse" in openapi_schemas
    assert "TestHistoryPoint" in types_source
    assert "run_created_at: string" in types_source
    assert "run_status: BackendRunStatus" in types_source
    assert "status: TestResultStatus" in types_source

    assert "useTestHistory" in hook_source
    assert "/analytics/test-history" in hook_source
    assert "params: { suite, name, days }" in hook_source

    assert "selectedTest" in panel_source
    assert "TestHistoryTable" in panel_source
    assert "analytics.historyTitle" in panel_source
    assert "analytics.status.${point.status}" in panel_source


def test_analytics_history_status_colors_match_result_status_semantics():
    panel_source = ANALYTICS_PANEL.read_text(encoding="utf-8")

    assert 'if (status === "passed") return "text-status-passed"' in panel_source
    assert 'status === "passed" || status === "xfail"' not in panel_source
    assert 'if (status === "failed" || status === "error") return "text-status-failed"' in panel_source
    assert 'if (status === "skipped" || status === "xfail") return "text-status-skipped"' in panel_source


def test_trigger_run_payload_maps_to_backend_run_trigger_contract(openapi_schemas: dict):
    backend_fields = _schema_properties(openapi_schemas, "RunTrigger")
    backend_required = _schema_required(openapi_schemas, "RunTrigger")
    payload_fields = _interface_properties("TriggerRunPayload")
    run_hook = RUN_HOOK.read_text(encoding="utf-8")

    assert backend_fields == {"pipeline_id", "git_ref", "git_sha", "environment_id", "priority"}
    assert backend_required == {"pipeline_id"}
    assert payload_fields == {
        "pipeline_id",
        "branch",
        "git_sha",
        "environment_id",
        "priority",
    }
    assert "git_ref: runData.branch" in run_hook
    assert "pipeline_id: runData.pipeline_id" in run_hook
    assert "git_sha: runData.git_sha" in run_hook
    assert "environment_id: runData.environment_id" in run_hook
    assert "priority: runData.priority ?? 1" in run_hook


def test_run_hooks_use_backend_terminal_status_for_polling_and_archived_logs():
    types_source = _frontend_source()
    run_hook = RUN_HOOK.read_text(encoding="utf-8")
    detail_page = RUN_DETAIL_PAGE.read_text(encoding="utf-8")

    assert "is_terminal: boolean" in types_source
    assert "BACKEND_TERMINAL_RUN_STATUSES: readonly BackendRunStatus[]" in run_hook
    for backend_status in ('"done"', '"failed"', '"cancelled"', '"timeout"'):
        assert backend_status in run_hook
    assert "is_terminal: BACKEND_TERMINAL_RUN_STATUSES.includes(run.status)" in run_hook
    assert "return query.state.data?.is_terminal ? false : 5000;" in run_hook
    assert "const TERMINAL_RUN_STATUSES" not in run_hook
    assert "const archivedLogsEnabled = run.is_terminal;" in detail_page
    assert "const terminalRunStatuses" not in detail_page


def test_test_result_status_ui_consumers_cover_backend_enum(openapi_schemas: dict):
    schema = openapi_schemas["TestResultResponse"]["properties"]["status"]
    expected_values = set(_non_null_schema(schema)["enum"])
    icon_source = TEST_STATUS_ICON.read_text(encoding="utf-8")
    table_source = TEST_RESULTS_TABLE.read_text(encoding="utf-8")
    e2e_helpers = E2E_HELPERS.read_text(encoding="utf-8")

    for value in expected_values:
        assert f"{value}:" in icon_source

    assert 'result.status === "xfail"' in table_source
    assert '"xfail"' in e2e_helpers
    assert '"failed": sum(1 for item in data["results"] if item["status"] == "failed")' in e2e_helpers
    assert '{"skipped", "xfail"}' in e2e_helpers
    assert '"error": sum(1 for item in data["results"] if item["status"] == "error")' in e2e_helpers
    assert '"pass_rate": passed / total if total else 0' in e2e_helpers


def test_frontend_paginated_response_matches_backend_shape(openapi_schemas: dict):
    backend_fields = _schema_properties(openapi_schemas, "PaginatedResponse_RunResponse_")
    frontend_fields = _interface_properties("PaginatedResponse")

    assert backend_fields == {"data", "page", "per_page", "total"}
    assert frontend_fields == backend_fields


def test_settings_page_uses_real_api_token_contract():
    settings_source = SETTINGS_PAGE.read_text(encoding="utf-8")
    hook_source = API_TOKENS_HOOK.read_text(encoding="utf-8")
    auth_flow_source = (ROOT / "tests" / "e2e" / "auth-flow.spec.ts").read_text(
        encoding="utf-8"
    )

    assert "settings.placeholder" not in settings_source
    assert "useApiTokens" in settings_source
    assert "useCreateApiToken" in settings_source
    assert "useRevokeApiToken" in settings_source
    assert "isError, refetch" in settings_source
    assert "const handleRetry = () =>" in settings_source
    assert "if (page === 1)" in settings_source
    assert "void refetch();" in settings_source
    assert "onClick={handleRetry}" in settings_source
    assert "onClick={() => setPage(1)}" not in settings_source
    assert "token.is_revoked" in settings_source
    assert "settings.tokens.status.revoked" in settings_source
    assert "disabled={token.is_revoked}" in settings_source
    assert 'api.get<PaginatedResponse<ApiTokenListItem>>' in hook_source
    assert 'api.post<ApiTokenResponse>("/auth/tokens", payload)' in hook_source
    assert 'api.delete(`/auth/tokens/${tokenId}`)' in hook_source
    assert "is_revoked: true" in auth_flow_source
    assert "apiTokens.filter((token)" not in auth_flow_source


def test_list_page_retry_buttons_refetch_current_failed_query():
    projects_source = PROJECTS_LIST_PAGE.read_text(encoding="utf-8")
    runs_source = RUNS_LIST_PAGE.read_text(encoding="utf-8")

    assert "isError, refetch" in projects_source
    assert "const handleRetry = () =>" in projects_source
    assert "if (search.trim() || deferredSearch.trim())" in projects_source
    assert "void refetch();" in projects_source
    assert "onClick={handleRetry}" in projects_source
    assert "onClick={() => setSearch(\"\")}" not in projects_source

    assert "isError, refetch" in runs_source
    assert "const handleRetry = () =>" in runs_source
    assert "if (page === 1)" in runs_source
    assert "void refetch();" in runs_source
    assert "onClick={handleRetry}" in runs_source
    assert "onClick={() => setPage(1)}" not in runs_source


def test_run_detail_previews_html_artifact_contract():
    run_detail_source = RUN_DETAIL_PAGE.read_text(encoding="utf-8")

    assert "function isPreviewableArtifact(artifact: Artifact): boolean" in run_detail_source
    assert 'artifact.type === "allure-report"' in run_detail_source
    assert 'artifact.type === "html"' in run_detail_source
    assert 'mimeType === "text/html"' in run_detail_source
    assert 'name.endsWith(".html")' in run_detail_source
    assert 'name.endsWith(".htm")' in run_detail_source
    assert "isPreviewableArtifact(artifact)" in run_detail_source
    assert 'artifact.type === "allure-report" && (' not in run_detail_source
    assert "getArtifactPreviewTitle(artifact)" in run_detail_source
    assert "getArtifactPreviewFrameTitle(artifact)" in run_detail_source
