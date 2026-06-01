from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_environments.py"
P3_TEST = ROOT / "tests" / "unit" / "test_api" / "test_p3.py"
PROJECTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_projects.py"
AUTH_ROUTES_TEST = ROOT / "tests" / "unit" / "test_auth" / "test_auth_routes.py"
RUNS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_runs.py"
PROJECT_MEMBERS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_project_members.py"
CREDENTIALS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_credentials.py"
NOTIFICATIONS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_notifications.py"


def test_quality_ops_records_current_gate_validation_error_evidence():
    environments_test = _read(ENVIRONMENTS_TEST)
    p3_test = _read(P3_TEST)
    projects_test = _read(PROJECTS_TEST)
    auth_routes_test = _read(AUTH_ROUTES_TEST)
    runs_test = _read(RUNS_TEST)
    project_members_test = _read(PROJECT_MEMBERS_TEST)
    credentials_test = _read(CREDENTIALS_TEST)
    notifications_test = _read(NOTIFICATIONS_TEST)
    environment_validation_errors_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Environment validation errors 精确契约）"
    )
    batch_duplicate_run_ids_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Batch duplicate run_ids validation 精确契约）"
    )
    p3_pagination_validation_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（P3 analytics pagination validation 精确契约）"
    )
    webhook_git_input_validation_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Webhook trigger git input validation 精确契约）"
    )
    project_validation_errors_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project validation errors 精确契约）"
    )
    auth_validation_errors_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Auth request validation errors 精确契约）"
    )
    run_validation_errors_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run validation errors 精确契约）"
    )
    run_trigger_results_validation_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run trigger/results validation helper 精确契约）"
    )
    project_member_role_validation_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project member role validation 精确契约）"
    )
    credential_create_validation_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Credential create validation errors 精确契约）"
    )
    notification_update_channels_validation_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification update channels validation 精确契约）"
    )
    notification_validation_helper_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification validation helper 精确契约）"
    )
    project_silent_windows_validation_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project silent_windows validation 精确契约）"
    )
    assert (
        "`tests/unit/test_api/test_environments.py::test_environment_schema_rejects_unpinned_or_moving_base_images tests/unit/test_api/test_environments.py::test_environment_schema_rejects_empty_name_or_cache_key tests/unit/test_api/test_environments.py::test_environment_schema_rejects_blank_name_or_cache_key tests/unit/test_api/test_environments.py::test_environment_schema_rejects_non_positive_resource_limits tests/unit/test_api/test_environments.py::test_environment_routes_reject_empty_name_or_cache_key_without_side_effects` 13 passed"
        in (environment_validation_errors_exact_row)
    )
    assert "`{type, loc, msg, input}` 投影" in (environment_validation_errors_exact_row)
    assert "`cpu_cores` 是 `greater_than > 0`" in (
        environment_validation_errors_exact_row
    )
    assert "整数资源限制是 `greater_than_equal >= 1`" in (
        environment_validation_errors_exact_row
    )
    assert '`any(error["loc"] == ...)`' in environment_validation_errors_exact_row
    assert "某字段有个错误" in environment_validation_errors_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in (
        environments_test
    )
    assert '"type": expected_type' in environments_test
    assert '"loc": ["body", field]' in environments_test
    assert '"input": bad_value' in environments_test
    assert '"cpu_cores", 0, "greater_than", "Input should be greater than 0"' in (
        environments_test
    )
    assert "for error in create_exc.value.errors()" not in environments_test
    assert "for error in update_exc.value.errors()" not in environments_test
    assert 'for error in resp.json()["detail"]' not in environments_test
    assert 'error["loc"] == ["body", field]' not in environments_test
    assert (
        "`tests/unit/test_api/test_p3.py::TestBatchCancel::test_batch_cancel_rejects_duplicate_run_ids_without_side_effects tests/unit/test_api/test_p3.py::TestBatchRetry::test_batch_retry_rejects_duplicate_run_ids_without_side_effects` 2 passed"
        in (batch_duplicate_run_ids_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        batch_duplicate_run_ids_exact_row
    )
    assert "`any(...)` 在错误列表里找" in batch_duplicate_run_ids_exact_row
    assert "有一条重复 ID 错误" in batch_duplicate_run_ids_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in p3_test
    assert '"type": "value_error"' in p3_test
    assert '"loc": ["body", "run_ids"]' in p3_test
    assert '"msg": "Value error, duplicate run_ids are not allowed"' in p3_test
    assert '"input": duplicate_run_ids' in p3_test
    assert "duplicate_run_ids = [str(run_id), str(run_id)]" in p3_test
    assert 'duplicate run_ids are not allowed" in error["msg"]' not in p3_test
    assert (
        "`tests/unit/test_api/test_p3.py::TestAnalytics::test_trends_rejects_invalid_pagination tests/unit/test_api/test_p3.py::TestAnalytics::test_flaky_rejects_invalid_pagination` 2 passed"
        in (p3_pagination_validation_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        p3_pagination_validation_exact_row
    )
    assert "offset 是 `greater_than_equal >= 0`" in (p3_pagination_validation_exact_row)
    assert "trends limit 是 `less_than_equal <= 365`" in (
        p3_pagination_validation_exact_row
    )
    assert "flaky limit 是 `less_than_equal <= 200`" in (
        p3_pagination_validation_exact_row
    )
    assert "只用 `any(...)` 找 `query.<field>` loc" in (
        p3_pagination_validation_exact_row
    )
    assert "某个 query 字段报错" in p3_pagination_validation_exact_row
    assert "def _assert_validation_error_response(" in p3_test
    assert "expected_type: str" in p3_test
    assert "expected_msg: str" in p3_test
    assert "expected_input: str" in p3_test
    assert '"type": expected_type' in p3_test
    assert '"loc": ["query", field]' in p3_test
    assert '"msg": expected_msg' in p3_test
    assert '"input": expected_input' in p3_test
    assert 'any(error["loc"] == ["query", field] for error in details)' not in (p3_test)
    assert (
        "`tests/unit/test_api/test_p3.py::TestWebhookTrigger::test_webhook_trigger_rejects_invalid_git_inputs_without_side_effects` 4 passed"
        in (webhook_git_input_validation_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        webhook_git_input_validation_exact_row
    )
    assert "blank git_ref" in webhook_git_input_validation_exact_row
    assert "空/空白/超长 git_sha" in webhook_git_input_validation_exact_row
    assert "先按 `body.<field>` 过滤错误，再只看首条消息片段" in (
        webhook_git_input_validation_exact_row
    )
    assert "某个 git 字段有错误文本" in webhook_git_input_validation_exact_row
    assert '_TOO_LONG_GIT_SHA = "a" * 101' in p3_test
    assert '"type": "string_too_short"' in p3_test
    assert '"type": "string_too_long"' in p3_test
    assert '"msg": "Value error, webhook git_ref must not be blank"' in p3_test
    assert '"msg": "Value error, webhook git_sha must not be blank"' in p3_test
    assert 'assert _validation_error_projection(resp.json()["detail"]) == [' in (
        p3_test
    )
    assert "field_errors = [" not in p3_test
    assert 'message in field_errors[0]["msg"]' not in p3_test
    assert (
        "`tests/unit/test_api/test_projects.py::test_create_project_rejects_invalid_core_fields_without_side_effects tests/unit/test_api/test_projects.py::test_update_project_rejects_empty_core_fields_without_side_effects tests/unit/test_api/test_projects.py::test_create_project_rejects_invalid_allowed_branches tests/unit/test_api/test_projects.py::test_update_project_rejects_invalid_allowed_branches` 28 passed"
        in (project_validation_errors_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        project_validation_errors_exact_row
    )
    assert "slug pattern" in project_validation_errors_exact_row
    assert "settings.allowed_branches 类型/长度/元素约束" in (
        project_validation_errors_exact_row
    )
    assert "`any(...)` 找字段和消息片段" in project_validation_errors_exact_row
    assert "`repr(detail)` 消息片段" in project_validation_errors_exact_row
    assert "某字段有个相似错误" in project_validation_errors_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in projects_test
    assert "string_pattern_mismatch" in projects_test
    assert "String should match pattern '^[a-z0-9-]+$'" in projects_test
    assert '"msg": f"Value error, {expected_error}"' in projects_test
    assert '"input": settings' in projects_test
    assert 'assert _validation_error_projection(resp.json()["detail"]) == [' in (
        projects_test
    )
    assert 'error["loc"] == ["body", field] and expected_msg in error["msg"]' not in (
        projects_test
    )
    assert (
        'detail["loc"] == ["body", "settings"] and expected_error in detail["msg"]'
        not in (projects_test)
    )
    assert '"settings.allowed_branches must be a list of strings" in repr(' not in (
        projects_test
    )
    assert (
        "`tests/unit/test_api/test_projects.py::test_update_project_rejects_invalid_silent_windows` 5 passed"
        in (project_silent_windows_validation_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        project_silent_windows_validation_exact_row
    )
    assert "settings 内嵌窗口错误落点 `body.settings.start_at`" in (
        project_silent_windows_validation_exact_row
    )
    assert "loc 前缀和消息片段" in project_silent_windows_validation_exact_row
    assert "某个前缀位置有相似错误" in (project_silent_windows_validation_exact_row)
    assert "_TOO_MANY_SILENT_WINDOWS" in projects_test
    assert '"loc": ["body", "settings", "start_at"]' in projects_test
    assert '"type": "too_long"' in projects_test
    assert "List should have at most 20 items after validation, not 21" in (
        projects_test
    )
    assert 'error["loc"][: len(expected_loc)] == expected_loc' not in projects_test
    assert 'and expected_msg in error["msg"]' not in projects_test
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_rejects_invalid_body_without_side_effects tests/unit/test_auth/test_auth_routes.py::TestRegister::test_register_rejects_invalid_username tests/unit/test_auth/test_auth_routes.py::TestRegister::test_register_rejects_invalid_password tests/unit/test_auth/test_auth_routes.py::TestRegister::test_register_rejects_bad_email tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_create_token_rejects_invalid_body_without_side_effects` 21 passed"
        in (auth_validation_errors_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        auth_validation_errors_exact_row
    )
    assert "username 长度/pattern" in auth_validation_errors_exact_row
    assert "register email" in auth_validation_errors_exact_row
    assert "token name/scope 空/空白/超长" in auth_validation_errors_exact_row
    assert "`any(...)` 找 loc 和消息片段" in auth_validation_errors_exact_row
    assert "某个字段出现过某段错误文本" in auth_validation_errors_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in (
        auth_routes_test
    )
    assert "String should match pattern '^[a-zA-Z0-9_]+$'" in auth_routes_test
    assert "Value error, login password must not be blank" in auth_routes_test
    assert (
        "value is not a valid email address: An email address must have an @-sign."
        in auth_routes_test
    )
    assert "Value error, api token scope must not be blank" in auth_routes_test
    assert (
        'assert _validation_error_projection(resp.json()["detail"]) == [expected_error]'
        in (auth_routes_test)
    )
    assert 'error["loc"] == expected_loc and expected_message in error["msg"]' not in (
        auth_routes_test
    )
    assert (
        'assert any(expected_message in item["msg"] for item in resp.json()["detail"])'
        not in (auth_routes_test)
    )
    assert 'assert any(item["loc"] == ["body", field] for item in detail)' not in (
        auth_routes_test
    )
    assert (
        "`tests/unit/test_api/test_runs.py::test_cancel_run_rejects_overlong_reason_without_side_effects tests/unit/test_api/test_runs.py::test_get_run_results_rejects_unknown_status` 2 passed"
        in (run_validation_errors_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        run_validation_errors_exact_row
    )
    assert "run cancel reason 过长" in run_validation_errors_exact_row
    assert "run results status 非法值" in run_validation_errors_exact_row
    assert "`any(...)` 确认 status 错误里包含 `passed/xfail`" in (
        run_validation_errors_exact_row
    )
    assert "某段错误文本出现过" in run_validation_errors_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in runs_test
    assert '"type": "literal_error"' in runs_test
    assert (
        "\"msg\": \"Input should be 'passed', 'failed', 'error', 'skipped' or 'xfail'\""
        in runs_test
    )
    assert '"type": "string_too_long"' in runs_test
    assert '"loc": ["body", "reason"]' in runs_test
    assert 'if error["loc"] == ["body", "reason"]' not in runs_test
    assert 'error["loc"] == ["query", "status"]' not in runs_test
    assert '"passed" in error["msg"]' not in runs_test
    assert (
        "`tests/unit/test_api/test_runs.py::test_get_run_results_rejects_invalid_text_filters_before_side_effects tests/unit/test_api/test_runs.py::test_trigger_run_priority_validation tests/unit/test_api/test_runs.py::test_trigger_run_rejects_invalid_git_inputs_without_side_effects` 9 passed"
        in (run_trigger_results_validation_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        run_trigger_results_validation_exact_row
    )
    assert "`string_too_short`" in run_trigger_results_validation_exact_row
    assert "`string_too_long`" in run_trigger_results_validation_exact_row
    assert "`less_than_equal`" in run_trigger_results_validation_exact_row
    assert "`string_pattern_mismatch`" in run_trigger_results_validation_exact_row
    assert "按 `query/body.<field>` 过滤错误后只看首条消息片段" in (
        run_trigger_results_validation_exact_row
    )
    assert "某个字段有错误文本" in run_trigger_results_validation_exact_row
    assert '_TOO_LONG_RESULT_FILTER = "x" * 501' in runs_test
    assert '_TOO_LONG_RUN_GIT_REF = "feature/" + ("x" * 193)' in runs_test
    assert '"loc": ["query", "suite"]' in runs_test
    assert '"loc": ["query", "q"]' in runs_test
    assert '"type": "less_than_equal"' in runs_test
    assert '"loc": ["body", "priority"]' in runs_test
    assert '"type": "string_pattern_mismatch"' in runs_test
    assert '"msg": "String should match pattern \'^[0-9a-fA-F]{40}$\'"' in (runs_test)
    assert "field_errors = [" not in runs_test
    assert 'message in field_errors[0]["msg"]' not in runs_test
    assert "priority_errors = [" not in runs_test
    assert (
        "`tests/unit/test_api/test_project_members.py::test_project_member_routes_reject_invalid_role_without_side_effects` 1 passed"
        in (project_member_role_validation_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        project_member_role_validation_exact_row
    )
    assert "`owner` 只能触发 `body.role` Literal 错误" in (
        project_member_role_validation_exact_row
    )
    assert "`any(...)` 找 `body.role` 和 `Input should be` 片段" in (
        project_member_role_validation_exact_row
    )
    assert "非法 role 有某段错误文本" in project_member_role_validation_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in (
        project_members_test
    )
    assert "\"msg\": \"Input should be 'admin', 'developer' or 'viewer'\"" in (
        project_members_test
    )
    assert '"input": "owner"' in project_members_test
    assert (
        'error["loc"] == ["body", "role"] and "Input should be" in error["msg"]'
        not in (project_members_test)
    )
    assert (
        "`tests/unit/test_api/test_credentials.py::test_create_credential_rejects_invalid_body_without_side_effects` 1 passed"
        in (credential_create_validation_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        credential_create_validation_exact_row
    )
    assert "空/空白 name、空 value、非法 type" in (
        credential_create_validation_exact_row
    )
    assert (
        "不查 project、不查 credential name、不加密、不创建 credential、不写 audit"
        in (credential_create_validation_exact_row)
    )
    assert "`any(...)` 找字段和消息片段" in credential_create_validation_exact_row
    assert "某字段有个相似错误" in credential_create_validation_exact_row
    assert "def _validation_error_projection(errors) -> list[dict]:" in credentials_test
    assert "Value error, credential name must not be blank" in credentials_test
    assert "\"msg\": \"Input should be 'token', 'ssh_key' or 'password'\"" in (
        credentials_test
    )
    assert '"input": "oauth"' in credentials_test
    assert 'error["loc"] == ["body", field] and expected_msg in error["msg"]' not in (
        credentials_test
    )
    assert (
        "`tests/unit/test_api/test_notifications.py::test_update_rule_rejects_empty_channels` 1 passed"
        in (notification_update_channels_validation_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        notification_update_channels_validation_exact_row
    )
    assert "`body.channels` 是 `too_short` 且 input 保留 `[]`" in (
        notification_update_channels_validation_exact_row
    )
    assert "不查 project/rule、不 create/update/delete、不写 audit" in (
        notification_update_channels_validation_exact_row
    )
    assert "`any(...)` 找 `body.channels` 和 `at least 1 item` 片段" in (
        notification_update_channels_validation_exact_row
    )
    assert "空 channels 有某段错误文本" in (
        notification_update_channels_validation_exact_row
    )
    assert "def _validation_error_projection(errors) -> list[dict]:" in (
        notifications_test
    )
    assert '"type": "too_short"' in notifications_test
    assert '"input": []' in notifications_test
    assert "List should have at least 1 item after validation, not 0" in (
        notifications_test
    )
    assert 'error["loc"] == ["body", "channels"]' not in notifications_test
    assert '"at least 1 item" in error["msg"]' not in notifications_test
    assert (
        "`tests/unit/test_api/test_notifications.py::test_create_rule_rejects_duplicate_channel_types tests/unit/test_api/test_notifications.py::test_create_rule_rejects_unsupported_channel_type tests/unit/test_api/test_notifications.py::test_create_rule_rejects_non_object_channel_config tests/unit/test_api/test_notifications.py::test_rule_routes_reject_blank_name_before_side_effects tests/unit/test_api/test_notifications.py::test_create_rule_rejects_invalid_conditions tests/unit/test_api/test_notifications.py::test_create_rule_rejects_undocumented_condition_alias tests/unit/test_api/test_notifications.py::test_update_rule_rejects_invalid_conditions_before_side_effects tests/unit/test_api/test_notifications.py::test_update_rule_rejects_duplicate_channel_types` 8 passed"
        in (notification_validation_helper_exact_row)
    )
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in (
        notification_validation_helper_exact_row
    )
    assert "duplicate channel" in notification_validation_helper_exact_row
    assert "unsupported channel" in notification_validation_helper_exact_row
    assert "非法/别名 condition field" in notification_validation_helper_exact_row
    assert "非法 condition operator" in notification_validation_helper_exact_row
    assert "只用 `any(...)` 找 `body.<field>` 和消息片段" in (
        notification_validation_helper_exact_row
    )
    assert "某个 body 字段有相似错误文本" in (notification_validation_helper_exact_row)
    assert "expected_msg: str" in notifications_test
    assert "expected_input" in notifications_test
    assert 'expected_type: str = "value_error"' in notifications_test
    assert '"type": expected_type' in notifications_test
    assert '"loc": ["body", field]' in notifications_test
    assert '"msg": expected_msg' in notifications_test
    assert '"input": expected_input' in notifications_test
    assert "Value error, duplicate notification channel type: webhook" in (
        notifications_test
    )
    assert "unsupported notification channel type: slack; " in notifications_test
    assert "conditions[0].operator must be one of: " in notifications_test
    assert "assert any(" not in notifications_test
    assert 'expected_message in error["msg"]' not in notifications_test
    assert 'error["loc"] == ["body", field]' not in notifications_test
