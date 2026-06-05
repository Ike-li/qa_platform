from __future__ import annotations

import pytest

from qaplatform.main import create_app
from tests.unit.frontend_contract_helpers import (
    ANALYTICS_HELPERS,
    ANALYTICS_HOOK,
    ANALYTICS_PANEL,
    ANALYTICS_RELEASE_SUMMARY_PANEL,
    ANALYTICS_TEST_HISTORY_TABLE,
    API_TOKENS_HOOK,
    E2E_HELPERS,
    NOTIFICATION_RULES_CHANNEL_CONFIG,
    NOTIFICATION_RULES_HELPERS,
    NOTIFICATION_RULES_PANEL,
    NOTIFICATION_RULES_RULE_FORM,
    PIPELINE_MODAL,
    PROJECTS_LIST_PAGE,
    ROOT,
    RUN_DETAIL_PAGE,
    RUN_HOOK,
    RUNS_LIST_PAGE,
    SETTINGS_API_TOKEN_DIALOG,
    SETTINGS_API_TOKEN_TABLE,
    SETTINGS_API_TOKEN_UTILS,
    SETTINGS_PAGE,
    TEST_RESULTS_TABLE,
    TEST_STATUS_ICON,
    assert_frontend_type_matches_schema as _assert_frontend_type_matches_schema,
    base_schema_name as _base_schema_name,
    combined_source as _combined_source,
    contract_settings as _settings,
    frontend_source as _frontend_source,
    interface_members as _interface_members,
    interface_properties as _interface_properties,
    non_null_schema as _non_null_schema,
    ref_schema_name as _ref_schema_name,
    type_aliases as _type_aliases,
)


@pytest.fixture(scope="module")
def openapi_schemas() -> dict:
    app = create_app(container=None, settings=_settings())
    return app.openapi()["components"]["schemas"]


def _schema_properties(schemas: dict, schema_name: str) -> set[str]:
    return set(schemas[schema_name]["properties"])


def _schema_required(schemas: dict, schema_name: str) -> set[str]:
    return set(schemas[schema_name].get("required", []))


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
        ("ReleaseTestDelta", "ReleaseTestDelta"),
        ("ReleaseSummaryResponse", "ReleaseSummary"),
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
        ("ReleaseTestDelta", "ReleaseTestDelta"),
        ("ReleaseSummaryResponse", "ReleaseSummary"),
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
    notification_rules_source = _combined_source(
        NOTIFICATION_RULES_PANEL,
        NOTIFICATION_RULES_HELPERS,
        NOTIFICATION_RULES_RULE_FORM,
        NOTIFICATION_RULES_CHANNEL_CONFIG,
    )

    assert (
        'export type NotificationChannelType = "email" | "webhook" | "dingtalk" | "wecom";'
        in types_source
    )
    assert 'const CHANNEL_TYPES: NotificationChannel["type"][] = [' in notification_rules_source
    for channel_type in ('"email"', '"webhook"', '"dingtalk"', '"wecom"'):
        assert channel_type in notification_rules_source
    assert '"slack"' not in types_source

    assert "to_addresses" in notification_rules_source
    assert 'update("to",' not in notification_rules_source
    assert "smtp_host" in notification_rules_source
    assert "from_address" in notification_rules_source
    assert "access_token" in notification_rules_source
    assert "webhook_key" in notification_rules_source
    assert "normalized.template = template" in notification_rules_source

    assert "function nextAvailableChannelType" in notification_rules_source
    assert "function channelTypeOptions" in notification_rules_source
    assert "hasDuplicateChannelTypes" in notification_rules_source
    assert 'toast.error(t("notifications.duplicateChannels"))' in notification_rules_source
    assert "disabled={!nextChannelType}" in notification_rules_source

    assert '"consecutive_failures"' in types_source
    assert '"consecutive_failed_runs"' not in types_source
    assert "NotificationConditionExpression" in types_source
    assert "all?: NotificationConditionExpression[]" in types_source
    assert "any?: NotificationConditionExpression[]" in types_source
    assert "function isConditionLeaf" in notification_rules_source
    assert "condition is NotificationCondition" in notification_rules_source
    assert "const CONDITION_MODES = [\"all\", \"any\"] as const" in notification_rules_source
    assert "conditionModeFromRule" in notification_rules_source
    assert "NotificationConditionInputExpression[]" in notification_rules_source
    assert "serializeConditionsForSave(conditionMode, conditions)" in notification_rules_source
    assert "notifications.condition.field.${f}" in notification_rules_source


def test_analytics_ui_exposes_single_test_history_contract(openapi_schemas: dict):
    types_source = _frontend_source()
    hook_source = ANALYTICS_HOOK.read_text(encoding="utf-8")
    panel_source = ANALYTICS_PANEL.read_text(encoding="utf-8")
    history_table_source = ANALYTICS_TEST_HISTORY_TABLE.read_text(encoding="utf-8")

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
    assert "analytics.status.${point.status}" in history_table_source


def test_analytics_ui_exposes_release_summary_and_git_ref_contract(openapi_schemas: dict):
    types_source = _frontend_source()
    hook_source = ANALYTICS_HOOK.read_text(encoding="utf-8")
    panel_source = ANALYTICS_PANEL.read_text(encoding="utf-8")
    release_summary_source = ANALYTICS_RELEASE_SUMMARY_PANEL.read_text(encoding="utf-8")

    assert "ReleaseSummaryResponse" in openapi_schemas
    assert "ReleaseTestDelta" in openapi_schemas
    assert _schema_properties(openapi_schemas, "ReleaseSummaryResponse") == {
        "git_ref",
        "baseline_git_ref",
        "total_runs",
        "passed_runs",
        "failed_runs",
        "raw_pass_rate",
        "flaky_adjusted_pass_rate",
        "new_failing_tests",
        "recovered_tests",
    }
    assert "export interface ReleaseSummary" in types_source
    assert "flaky_adjusted_pass_rate: number | null" in types_source
    assert "new_failing_tests: ReleaseTestDelta[]" in types_source
    assert "recovered_tests: ReleaseTestDelta[]" in types_source

    assert "useTrends(projectId: string, days: number = 30, gitRef?: string)" in hook_source
    assert "useFlakyTests(projectId: string, days: number = 30, minRuns: number = 3, gitRef?: string)" in hook_source
    assert "useReleaseSummary" in hook_source
    assert "/analytics/release-summary" in hook_source
    assert "git_ref: trimmedGitRef" in hook_source
    assert "baseline_git_ref: trimmedBaselineGitRef" in hook_source

    assert "defaultBranch" in panel_source
    assert "ReleaseSummaryPanel" in panel_source
    assert "analytics.release.targetRef" in panel_source
    assert "analytics.release.adjustedPassRate" in release_summary_source
    assert "initialSuite" in panel_source
    assert "initialTest" in panel_source


def test_analytics_history_status_colors_match_result_status_semantics():
    helpers_source = ANALYTICS_HELPERS.read_text(encoding="utf-8")

    assert 'if (status === "passed") return "text-status-passed"' in helpers_source
    assert 'status === "passed" || status === "xfail"' not in helpers_source
    assert 'if (status === "failed" || status === "error") return "text-status-failed"' in helpers_source
    assert 'if (status === "skipped" || status === "xfail") return "text-status-skipped"' in helpers_source


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
    settings_page_source = SETTINGS_PAGE.read_text(encoding="utf-8")
    settings_source = _combined_source(
        SETTINGS_PAGE,
        SETTINGS_API_TOKEN_DIALOG,
        SETTINGS_API_TOKEN_TABLE,
        SETTINGS_API_TOKEN_UTILS,
    )
    hook_source = API_TOKENS_HOOK.read_text(encoding="utf-8")
    auth_flow_source = (ROOT / "tests" / "e2e" / "auth-flow.spec.ts").read_text(
        encoding="utf-8"
    )

    assert "settings.placeholder" not in settings_page_source
    assert "useApiTokens" in settings_page_source
    assert "useCreateApiToken" in settings_source
    assert "useRevokeApiToken" in settings_page_source
    assert "isError, refetch" in settings_page_source
    assert "const handleRetry = () =>" in settings_page_source
    assert "if (page === 1)" in settings_page_source
    assert "void refetch();" in settings_page_source
    assert "onClick={handleRetry}" in settings_page_source
    assert "onClick={() => setPage(1)}" not in settings_page_source
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
    assert "useRunAllureReportArtifact" in run_detail_source
    assert '<TabsTrigger value="report">' in run_detail_source
    assert "getArtifactPreviewUrl(allureReportArtifact.id)" in run_detail_source
    assert "getArtifactPreviewUrl(artifact.id)" in run_detail_source
    assert "getArtifactPreviewTitle(artifact)" in run_detail_source
    assert "getArtifactPreviewFrameTitle(artifact)" in run_detail_source

    use_runs_source = (ROOT / "frontend" / "src" / "hooks" / "use-runs.ts").read_text(
        encoding="utf-8",
    )
    assert "useRunAllureReportArtifact" in use_runs_source
    assert 'api.get<Artifact>(`/runs/${id}/artifacts/allure-report`)' in use_runs_source


def test_pytest_pipeline_modal_does_not_enable_allure_by_default():
    source = PIPELINE_MODAL.read_text(encoding="utf-8")

    assert source.count("allure_enabled: false") >= 2
    assert "allure_enabled: true" not in source
    assert "setValue(\"allure_enabled\", checked === true)" in source
