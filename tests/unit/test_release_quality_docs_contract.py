from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)

ROOT = Path(__file__).resolve().parents[2]
TESTING_STRATEGY = ROOT / "docs" / "testing-strategy.md"
API_INTEGRATION_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_api_integration_contract.py"
)
PROJECT_SURFACE_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_project_surface_contract.py"
)
DOCS_STATUS_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_docs_status_contract.py"
)
DOCS_CURRENT_GATE_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_docs_current_gate_contract.py"
)
EXECUTOR_ENGINE_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_executor_engine_contract.py"
)
PLUGIN_RUNNER_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_plugin_runner_contract.py"
)
RELEASE_GATE_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_release_gate_contract.py"
)
RESOURCE_API_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_resource_api_contract.py"
)
AUDIT_CONTRACT = ROOT / "tests" / "unit" / "test_release_quality_audit_contract.py"
PIPELINE_REPOSITORY_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_pipeline_repository_contract.py"
)
FRONTEND_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_frontend_contract.py"
)
API_GUARDRAILS_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_api_guardrails_contract.py"
)
OBSERVABILITY_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_observability_contract.py"
)
ANALYTICS_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_analytics_contract.py"
)
MIGRATION_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_migration_contract.py"
)
AUTH_CONTRACT = ROOT / "tests" / "unit" / "test_release_quality_auth_contract.py"
RUN_API_CONTRACT = ROOT / "tests" / "unit" / "test_release_quality_run_api_contract.py"
RUNTIME_SCHEDULER_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_runtime_scheduler_contract.py"
)
WORKER_NOTIFICATIONS_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_worker_notifications_contract.py"
)
WORKER_LIFECYCLE_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_worker_lifecycle_contract.py"
)
GIT_SOURCE_CONTRACT = (
    ROOT / "tests" / "unit" / "test_release_quality_git_source_contract.py"
)


def test_testing_strategy_defines_quality_gate_maintenance_layers():
    testing_strategy = _read(TESTING_STRATEGY)
    contract_source = _read(Path(__file__))
    api_integration_contract_source = _read(API_INTEGRATION_CONTRACT)
    project_surface_contract_source = _read(PROJECT_SURFACE_CONTRACT)
    docs_status_contract_source = _read(DOCS_STATUS_CONTRACT)
    docs_current_gate_contract_source = _read(DOCS_CURRENT_GATE_CONTRACT)
    executor_engine_contract_source = _read(EXECUTOR_ENGINE_CONTRACT)
    plugin_runner_contract_source = _read(PLUGIN_RUNNER_CONTRACT)
    release_gate_contract_source = _read(RELEASE_GATE_CONTRACT)
    resource_api_contract_source = _read(RESOURCE_API_CONTRACT)
    audit_contract_source = _read(AUDIT_CONTRACT)
    pipeline_repository_contract_source = _read(PIPELINE_REPOSITORY_CONTRACT)
    frontend_contract_source = _read(FRONTEND_CONTRACT)
    api_guardrails_contract_source = _read(API_GUARDRAILS_CONTRACT)
    observability_contract_source = _read(OBSERVABILITY_CONTRACT)
    analytics_contract_source = _read(ANALYTICS_CONTRACT)
    migration_contract_source = _read(MIGRATION_CONTRACT)
    auth_contract_source = _read(AUTH_CONTRACT)
    run_api_contract_source = _read(RUN_API_CONTRACT)
    runtime_scheduler_contract_source = _read(RUNTIME_SCHEDULER_CONTRACT)
    worker_notifications_contract_source = _read(WORKER_NOTIFICATIONS_CONTRACT)
    worker_lifecycle_contract_source = _read(WORKER_LIFECYCLE_CONTRACT)
    git_source_contract_source = _read(GIT_SOURCE_CONTRACT)
    row = _quality_ops_row(
        "| 2026-06-01 | N/A（质量门禁维护分层 / release-quality helper 收敛）"
    )

    assert "## 质量门禁维护分层" in testing_strategy
    assert "行为正确性优先由业务测试证明" in testing_strategy
    assert (
        "`tests/unit/test_release_quality_docs_contract.py` 只用于保护发版证据、台账口径和高风险防回退声明"
        in (testing_strategy)
    )
    assert "能由业务测试直接证明的，不再额外添加 release-quality 文档契约" in (
        testing_strategy
    )
    assert (
        "复用 `_read`、`_quality_ops_row`、`_quality_ops_row_containing`、`_quality_ops_rows_containing`、`_test_block`、`_block_between`、`_after`、`_marked_block`、`_marked_block_or_tail`"
        in (testing_strategy)
    )
    assert "整表 `QUALITY_OPS` 包含式断言" in testing_strategy
    assert (
        "台账行记录“为什么这类弱断言会漏问题、哪些 readiness/数量语义被合理保留、验证命令是什么”"
        in (testing_strategy)
    )
    assert "不是逐断言流水账" in testing_strategy
    assert "只把最近证据和未关闭风险留在台账" in testing_strategy
    assert "自检类 AST 计数统一放在 `_contract_maintenance_counts`" in (
        testing_strategy
    )
    assert "通用 helper 放在 `tests/unit/release_quality_contract_helpers.py`" in (
        testing_strategy
    )
    assert (
        "worker notification channel 契约拆到 `tests/unit/test_release_quality_notification_channels_contract.py`"
        in (testing_strategy)
    )
    assert (
        "performance smoke 契约拆到 `tests/unit/test_release_quality_performance_contract.py`"
        in (testing_strategy)
    )
    assert (
        "worker external-stack 契约拆到 `tests/unit/test_release_quality_worker_external_stack_contract.py`"
        in (testing_strategy)
    )
    assert (
        "real auth results/artifacts 契约拆到 `tests/unit/test_release_quality_real_auth_results_contract.py`"
        in (testing_strategy)
    )
    assert (
        "auth/API token 契约拆到 `tests/unit/test_release_quality_auth_contract.py`"
        in (testing_strategy)
    )
    assert (
        "run/SSE/artifact API 契约拆到 `tests/unit/test_release_quality_run_api_contract.py`"
        in (testing_strategy)
    )
    assert (
        "runtime scheduler/log stream 契约拆到 `tests/unit/test_release_quality_runtime_scheduler_contract.py`"
        in (testing_strategy)
    )
    assert (
        "worker notification execution 契约拆到 `tests/unit/test_release_quality_worker_notifications_contract.py`"
        in (testing_strategy)
    )
    assert (
        "worker lifecycle/retry/reclaim 契约拆到 `tests/unit/test_release_quality_worker_lifecycle_contract.py`"
        in (testing_strategy)
    )
    assert (
        "git source/worker Git 契约拆到 `tests/unit/test_release_quality_git_source_contract.py`"
        in (testing_strategy)
    )
    assert (
        "API integration/write-state 契约拆到 `tests/unit/test_release_quality_api_integration_contract.py`"
        in (testing_strategy)
    )
    assert (
        "project/webhook surface 契约拆到 `tests/unit/test_release_quality_project_surface_contract.py`"
        in (testing_strategy)
    )
    assert (
        "documentation/status 契约拆到 `tests/unit/test_release_quality_docs_status_contract.py`"
        in (testing_strategy)
    )
    assert (
        "current gate split self-check 契约拆到 `tests/unit/test_release_quality_docs_current_gate_contract.py`"
        in (testing_strategy)
    )
    assert (
        "docs maintenance helper/static self-check 契约拆到 `tests/unit/test_release_quality_docs_maintenance_contract.py`"
        in (testing_strategy)
    )
    assert (
        "docs runtime/external moved-index 契约拆到 `tests/unit/test_release_quality_docs_runtime_external_index_contract.py`"
        in (testing_strategy)
    )
    assert (
        "executor/engine 契约拆到 `tests/unit/test_release_quality_executor_engine_contract.py`"
        in (testing_strategy)
    )
    assert (
        "plugin runner/registry 契约拆到 `tests/unit/test_release_quality_plugin_runner_contract.py`"
        in (testing_strategy)
    )
    assert (
        "release gate/workflow 契约拆到 `tests/unit/test_release_quality_release_gate_contract.py`"
        in (testing_strategy)
    )
    assert (
        "resource API/control-plane 契约拆到 `tests/unit/test_release_quality_resource_api_contract.py`"
        in (testing_strategy)
    )
    assert (
        "audit/audit-events 契约拆到 `tests/unit/test_release_quality_audit_contract.py`"
        in (testing_strategy)
    )
    assert (
        "pipeline/repository 契约拆到 `tests/unit/test_release_quality_pipeline_repository_contract.py`"
        in (testing_strategy)
    )
    assert (
        "frontend/API 契约拆到 `tests/unit/test_release_quality_frontend_contract.py`"
        in (testing_strategy)
    )
    assert (
        "API guardrails 契约拆到 `tests/unit/test_release_quality_api_guardrails_contract.py`"
        in (testing_strategy)
    )
    assert (
        "observability/logging 契约拆到 `tests/unit/test_release_quality_observability_contract.py`"
        in (testing_strategy)
    )
    assert (
        "analytics/API 契约拆到 `tests/unit/test_release_quality_analytics_contract.py`"
        in (testing_strategy)
    )
    assert (
        "migration/env-vars 契约拆到 `tests/unit/test_release_quality_migration_contract.py`"
        in (testing_strategy)
    )

    assert "release quality docs contract self-check 1 passed" in row
    assert "release quality docs contract full 381 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "release-quality contract 只保护发版证据/台账口径/高风险防回退" in (row)
    assert (
        "worker notification channel 契约拆到 `tests/unit/test_release_quality_notification_channels_contract.py`"
        in (row)
    )
    assert (
        "performance smoke 契约拆到 `tests/unit/test_release_quality_performance_contract.py`"
        in row
    )
    assert (
        "worker external-stack 契约拆到 `tests/unit/test_release_quality_worker_external_stack_contract.py`"
        in row
    )
    assert (
        "real auth results/artifacts 契约拆到 `tests/unit/test_release_quality_real_auth_results_contract.py`"
        in row
    )
    assert (
        "auth/API token 契约拆到 `tests/unit/test_release_quality_auth_contract.py`"
        in row
    )
    assert (
        "run/SSE/artifact API 契约拆到 `tests/unit/test_release_quality_run_api_contract.py`"
        in row
    )
    assert (
        "runtime scheduler/log stream 契约拆到 `tests/unit/test_release_quality_runtime_scheduler_contract.py`"
        in row
    )
    assert (
        "worker notification execution 契约拆到 `tests/unit/test_release_quality_worker_notifications_contract.py`"
        in row
    )
    assert (
        "worker lifecycle/retry/reclaim 契约拆到 `tests/unit/test_release_quality_worker_lifecycle_contract.py`"
        in row
    )
    assert (
        "git source/worker Git 契约拆到 `tests/unit/test_release_quality_git_source_contract.py`"
        in row
    )
    assert (
        "API integration/write-state 契约拆到 `tests/unit/test_release_quality_api_integration_contract.py`"
        in row
    )
    assert (
        "project/webhook surface 契约拆到 `tests/unit/test_release_quality_project_surface_contract.py`"
        in row
    )
    assert (
        "documentation/status 契约拆到 `tests/unit/test_release_quality_docs_status_contract.py`"
        in row
    )
    assert (
        "current gate split self-check 契约拆到 `tests/unit/test_release_quality_docs_current_gate_contract.py`"
        in row
    )
    assert (
        "docs maintenance helper/static self-check 契约拆到 `tests/unit/test_release_quality_docs_maintenance_contract.py`"
        in row
    )
    assert (
        "docs runtime/external moved-index 契约拆到 `tests/unit/test_release_quality_docs_runtime_external_index_contract.py`"
        in row
    )
    assert (
        "executor/engine 契约拆到 `tests/unit/test_release_quality_executor_engine_contract.py`"
        in row
    )
    assert (
        "plugin runner/registry 契约拆到 `tests/unit/test_release_quality_plugin_runner_contract.py`"
        in row
    )
    assert (
        "release gate/workflow 契约拆到 `tests/unit/test_release_quality_release_gate_contract.py`"
        in row
    )
    assert (
        "resource API/control-plane 契约拆到 `tests/unit/test_release_quality_resource_api_contract.py`"
        in row
    )
    assert (
        "audit/audit-events 契约拆到 `tests/unit/test_release_quality_audit_contract.py`"
        in row
    )
    assert (
        "pipeline/repository 契约拆到 `tests/unit/test_release_quality_pipeline_repository_contract.py`"
        in row
    )
    assert (
        "frontend/API 契约拆到 `tests/unit/test_release_quality_frontend_contract.py`"
        in row
    )
    assert (
        "API guardrails 契约拆到 `tests/unit/test_release_quality_api_guardrails_contract.py`"
        in row
    )
    assert (
        "observability/logging 契约拆到 `tests/unit/test_release_quality_observability_contract.py`"
        in row
    )
    assert (
        "analytics/API 契约拆到 `tests/unit/test_release_quality_analytics_contract.py`"
        in row
    )
    assert (
        "migration/env-vars 契约拆到 `tests/unit/test_release_quality_migration_contract.py`"
        in row
    )
    for auth_contract in [
        "def test_quality_ops_capture_rate_limit_pass_through_response_identity_"
        + "contract",
        "def test_testing_docs_capture_api_token_missing_auth_" + "contract",
        "def test_quality_ops_capture_rate_limit_strict_redis_outage_" + "envelope",
        "def test_quality_ops_capture_rate_limit_multi_token_429_exact_response_"
        + "contract",
        "def test_quality_ops_capture_auth_real_rate_limit_429_exact_envelope_"
        + "contract",
        "def test_quality_ops_capture_api_token_list_exact_response_" + "contract",
        "def test_quality_ops_capture_auth_audit_outage_integration_exact_warning_"
        + "contract",
        "def test_quality_ops_capture_auth_rate_limit_audit_direct_projection_"
        + "contract",
        "def test_quality_ops_capture_auth_failure_401_exact_body_" + "contract",
        "def test_quality_ops_capture_login_unknown_user_exact_audit_no_secret_"
        + "contract",
        "def test_quality_ops_capture_auth_success_token_claims_exact_" + "contract",
        "def test_quality_ops_capture_auth_register_conflict_exact_rollback_"
        + "contract",
        "def test_quality_ops_capture_auth_refresh_rotation_exact_token_audit_"
        + "contract",
        "def test_quality_ops_capture_api_token_create_exact_response_" + "contract",
        "def test_quality_ops_capture_api_token_audit_redundant_weak_tests_"
        + "removed",
        "def test_quality_ops_capture_api_token_revoke_hidden_404_exact_body_"
        + "contract",
        "def test_quality_ops_capture_api_token_audit_complete_client_metadata_"
        + "contract",
        "def test_quality_ops_capture_auth_login_audit_success_contract_and_failure_"
        + "cleanup",
        "def test_quality_ops_capture_auth_login_failure_helper_complete_payload_"
        + "contract",
        "def test_quality_ops_capture_auth_register_audit_complete_payload_"
        + "contract",
        "def test_quality_ops_capture_auth_refresh_audit_complete_client_metadata_"
        + "contract",
        "def test_quality_ops_capture_auth_refresh_failed_audit_exact_response_"
        + "contract",
        "def test_quality_ops_capture_auth_refresh_failure_helper_complete_payload_"
        + "contract",
        "def test_quality_ops_capture_auth_logout_audit_complete_client_metadata_"
        + "contract",
        "def test_quality_ops_capture_logout_revoke_redis_" + "contract",
        "def test_quality_ops_capture_api_token_argon2_phc_parameter_exact_"
        + "contract",
        "def test_quality_ops_capture_api_token_generated_format_entropy_" + "contract",
        "def test_quality_ops_capture_auth_middleware_bearer_dispatch_exact_args_"
        + "contract",
        "def test_quality_ops_capture_api_token_last_used_success_exact_auth_flow_"
        + "contract",
        "def test_quality_ops_capture_jwt_blacklist_lookup_exact_jti_fail_open_"
        + "contract",
        "def test_quality_ops_capture_auth_revoked_access_route_exact_rejection_"
        + "contract",
        "def test_quality_ops_capture_api_token_last_used_failure_exact_auth_flow_"
        + "contract",
        "def test_quality_ops_capture_auth_middleware_exact_exception_detail_sweep_"
        + "contract",
        "def test_quality_ops_capture_api_token_invalid_records_exact_denial_detail_"
        + "contract",
        "def test_quality_ops_capture_auth_login_tenant_lookup_last_login_exact_"
        + "contract",
        "def test_quality_ops_capture_jwt_no_jti_pass_through_exact_no_blacklist_"
        + "contract",
    ]:
        assert auth_contract not in contract_source
        assert auth_contract in auth_contract_source
    for run_api_contract in [
        "def test_quality_ops_capture_sse_route_rejection_exact_body_" + "contract",
        "def test_quality_ops_capture_run_trigger_rejection_response_" + "contracts",
        "def test_quality_ops_capture_sse_stream_404_response_" + "contracts",
        "def test_quality_ops_capture_run_cancel_batch_real_api_exact_response_redis_audit_"
        + "contract",
        "def test_quality_ops_capture_run_list_filter_exact_results_" + "contract",
        "def test_quality_ops_capture_run_list_filter_exact_run_response_pagination_"
        + "contract",
        "def test_quality_ops_capture_run_trigger_get_integration_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_sse_stream_frame_payload_exact_" + "contract",
        "def test_quality_ops_capture_sse_resume_frame_cursor_exact_" + "contract",
        "def test_quality_ops_capture_route_rejection_detail_exact_body_" + "contract",
        "def test_quality_ops_capture_run_list_seeded_item_" + "contract",
        "def test_quality_ops_capture_run_list_exact_response_default_sort_"
        + "contract",
        "def test_quality_ops_capture_run_results_exact_page_rbac_" + "contract",
        "def test_quality_ops_capture_run_cancel_success_exact_response_redis_audit_"
        + "contract",
        "def test_quality_ops_capture_run_trigger_success_exact_response_audit_rbac_"
        + "contract",
        "def test_quality_ops_capture_run_trigger_priority_exact_queue_audit_"
        + "contract",
        "def test_quality_ops_capture_run_artifacts_list_exact_response_" + "contract",
        "def test_quality_ops_capture_run_archived_logs_s3_key_page_rbac_" + "contract",
        "def test_quality_ops_capture_run_notifications_exact_page_rbac_" + "contract",
        "def test_quality_ops_capture_run_detail_exact_response_rbac_" + "contract",
        "def test_quality_ops_capture_sse_ticket_atomic_exact_projection_" + "contract",
        "def test_quality_ops_capture_run_status_event_direct_payload_projection_"
        + "contract",
        "def test_quality_ops_capture_run_status_event_no_previous_exact_stream_hash_"
        + "contract",
        "def test_quality_ops_capture_run_status_event_previous_exact_stream_hash_"
        + "contract",
        "def test_quality_ops_capture_run_status_event_redis_failure_exact_log_no_hash_"
        + "contract",
        "def test_quality_ops_capture_run_results_filter_empty_page_exact_"
        + "contract",
    ]:
        assert run_api_contract not in contract_source
        assert run_api_contract in run_api_contract_source
    for runtime_scheduler_contract in [
        "def test_quality_ops_capture_log_stream_batch_truncation_exact_" + "contract",
        "def test_quality_ops_capture_log_stream_truncation_exact_byte_prefix_"
        + "contract",
        "def test_quality_ops_capture_scheduler_dequeue_capacity_metadata_exact_"
        + "contract",
        "def test_quality_ops_capture_scheduler_queue_choice_exact_metadata_"
        + "contract",
        "def test_quality_ops_capture_scheduler_arq_conflict_exact_dedup_" + "contract",
        "def test_quality_ops_capture_scheduler_capacity_short_circuit_exact_"
        + "contract",
        "def test_quality_ops_capture_log_stream_archive_retry_s3_ttl_exact_"
        + "contract",
        "def test_quality_ops_capture_cancel_watcher_repeated_message_keeps_"
        + "listening",
        "def test_quality_ops_capture_cancel_watcher_handler_exception_exact_log_"
        + "contract",
        "def test_quality_ops_capture_check_schedules_commit_order_exact_" + "contract",
        "def test_quality_ops_capture_check_schedules_failure_update_audit_exact_"
        + "contract",
        "def test_quality_ops_capture_check_schedules_enqueue_failure_commit_order_exact_"
        + "contract",
        "def test_quality_ops_capture_check_schedules_silent_window_audit_exact_"
        + "contract",
        "def test_quality_ops_capture_log_stream_archive_success_cursor_s3_exact_"
        + "contract",
    ]:
        assert runtime_scheduler_contract not in contract_source
        assert runtime_scheduler_contract in runtime_scheduler_contract_source
    for worker_notifications_contract in [
        "def test_quality_ops_capture_notification_matching_rule_log_create_exact_kwargs_"
        + "contract",
        "def test_quality_ops_capture_notification_template_rendering_exact_send_log_"
        + "contract",
        "def test_quality_ops_capture_notification_failure_log_exact_kwargs_error_"
        + "contract",
        "def test_quality_ops_capture_notification_existing_delivery_short_circuit_"
        + "contract",
        "def test_quality_ops_capture_notification_log_write_exception_attempted_log_"
        + "contract",
        "def test_quality_ops_capture_notification_multi_channel_log_create_exact_"
        + "contract",
        "def test_quality_ops_capture_notification_template_lazy_log_create_exact_"
        + "contract",
        "def test_quality_ops_capture_notification_consecutive_failures_exact_log_"
        + "contract",
    ]:
        assert worker_notifications_contract not in contract_source
        assert worker_notifications_contract in worker_notifications_contract_source
    for worker_lifecycle_contract in [
        "def test_quality_ops_capture_worker_claim_commit_sequence_" + "contract",
        "def test_quality_ops_capture_worker_claim_none_no_side_effect_" + "contract",
        "def test_quality_ops_capture_heartbeat_redis_set_parameter_" + "contract",
        "def test_quality_ops_capture_worker_early_cancel_release_order_exact_"
        + "contract",
        "def test_quality_ops_capture_worker_source_auth_credential_lookup_exact_filters_"
        + "contract",
        "def test_quality_ops_capture_worker_pipeline_collector_exact_list_"
        + "contract",
        "def test_quality_ops_capture_worker_auto_retry_waiting_exact_order_"
        + "contract",
        "def test_quality_ops_capture_worker_auto_retry_reject_no_side_effect_"
        + "contract",
        "def test_quality_ops_capture_worker_lost_reclaim_stale_update_no_side_effect_"
        + "contract",
        "def test_quality_ops_capture_worker_active_run_pipeline_config_exact_projection_"
        + "contract",
        "def test_quality_ops_capture_heartbeat_redis_set_exact_utc_arity_"
        + "contract",
    ]:
        assert worker_lifecycle_contract not in contract_source
        assert worker_lifecycle_contract in worker_lifecycle_contract_source
    for git_source_contract in [
        "def test_quality_ops_capture_worker_git_raises_exact_exception_" + "contract",
        "def test_quality_ops_capture_git_source_clone_failure_exact_redacted_message_"
        + "contract",
        "def test_quality_ops_capture_git_source_auth_env_path_ssh_argv_exact_"
        + "contract",
    ]:
        assert git_source_contract not in contract_source
        assert git_source_contract in git_source_contract_source
    for api_integration_contract in [
        "def test_quality_ops_capture_environment_and_schedule_404_envelope_"
        + "contracts",
        "def test_quality_ops_capture_real_api_archived_project_run_exact_rejection_"
        + "contract",
        "def test_quality_ops_capture_real_api_write_state_exact_audit_" + "actions",
        "def test_quality_ops_capture_project_real_api_lifecycle_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_project_member_real_api_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_pipeline_real_api_lifecycle_exact_audit_projection_"
        + "contract",
        "def test_quality_ops_capture_environment_real_api_lifecycle_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_notification_rule_real_api_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_notification_rule_integration_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_schedule_run_real_api_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_real_api_write_pagination_exact_response_"
        + "contract",
        "def test_quality_ops_capture_real_api_write_empty_pagination_exact_response_"
        + "contract",
        "def test_quality_ops_capture_integration_analytics_history_exact_response_"
        + "contract",
        "def test_quality_ops_capture_integration_analytics_trends_flaky_exact_response_"
        + "contract",
        "def test_quality_ops_capture_core_api_list_exact_response_" + "contracts",
        "def test_quality_ops_capture_project_delete_exact_audit_redacted_url_"
        + "contract",
        "def test_quality_ops_capture_notification_rule_delete_exact_audit_no_channel_leak_"
        + "contract",
        "def test_quality_ops_capture_credential_real_api_exact_response_no_secret_"
        + "contract",
        "def test_quality_ops_capture_notification_rule_soft_delete_exact_empty_list_"
        + "contract",
        "def test_quality_ops_capture_project_create_exact_response_" + "contract",
        "def test_quality_ops_capture_notification_invalid_condition_integration_exact_detail_"
        + "contract",
        "def test_quality_ops_capture_legacy_notification_channel_exact_response_"
        + "contract",
        "def test_quality_ops_capture_notification_invalid_condition_integration_exact_response_"
        + "contract",
        "def test_quality_ops_capture_core_list_exact_pagination_" + "contracts",
        "def test_quality_ops_capture_pipeline_integration_full_response_" + "contract",
        "def test_quality_ops_capture_project_get_update_integration_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_project_search_integration_exact_pagination_sort_"
        + "contract",
        "def test_quality_ops_capture_project_cross_tenant_direct_no_leak_list_"
        + "contract",
        "def test_quality_ops_capture_crud_delete_followup_404_exact_envelope_"
        + "contract",
        "def test_quality_ops_capture_integration_schema_bootstrap_fail_message_"
        + "contract",
    ]:
        assert api_integration_contract not in contract_source
        assert api_integration_contract in api_integration_contract_source
    for project_surface_contract in [
        "def test_quality_ops_capture_webhook_rejection_response_" + "contracts",
        "def test_quality_ops_capture_webhook_filtered_duplicate_exact_audit_ownership_"
        + "contract",
        "def test_quality_ops_capture_project_webhook_filtered_unit_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_project_webhook_reserved_metadata_integration_exact_audit_"
        + "contract",
        "def test_quality_ops_capture_webhook_terminal_same_commit_exact_response_db_"
        + "contract",
        "def test_quality_ops_capture_github_repo_url_candidates_exact_" + "contract",
        "def test_quality_ops_capture_project_list_exact_response_" + "contract",
        "def test_quality_ops_capture_project_silent_windows_update_success_exact_"
        + "contract",
        "def test_quality_ops_capture_project_duplicate_slug_exact_short_circuit_"
        + "contract",
        "def test_quality_ops_capture_project_credential_binding_update_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_project_crud_exact_response_audit_" + "contract",
        "def test_quality_ops_capture_project_silent_windows_integration_exact_audit_no_secret_"
        + "contract",
        "def test_quality_ops_capture_project_members_list_exact_response_"
        + "contract",
        "def test_quality_ops_capture_project_member_crud_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_webhook_trigger_run_create_exact_identity_enqueue_"
        + "contract",
        "def test_quality_ops_capture_webhook_metadata_reserved_key_exact_merge_"
        + "contract",
        "def test_quality_ops_capture_github_provider_webhook_success_exact_route_"
        + "contract",
        "def test_quality_ops_capture_analytics_repository_query_exact_kwargs_cutoff_"
        + "contract",
        "def test_quality_ops_capture_p3_analytics_custom_pagination_exact_empty_response_"
        + "contract",
        "def test_quality_ops_capture_missing_project_route_matrix_direct_error_"
        + "lists",
        "def test_quality_ops_capture_batch_internal_failure_exact_body_" + "contract",
        "def test_quality_ops_capture_batch_business_outcome_exact_body_" + "contract",
        "def test_quality_ops_capture_remaining_rejection_exact_body_" + "contract",
        "def test_quality_ops_capture_p3_analytics_exact_response_" + "contracts",
        "def test_quality_ops_capture_api_delete_204_empty_body_" + "contract",
        "def test_quality_ops_capture_project_creator_membership_exact_session_"
        + "contract",
    ]:
        assert project_surface_contract not in contract_source
        assert project_surface_contract in project_surface_contract_source
    for docs_status_contract in [
        "def test_release_review_slices_do_not_claim_unrecorded_" + "remote_success",
        "def test_release_review_slices_reflect_current_oom_signoff_" + "gap",
        "def test_backend_test_audit_reflects_current_local_" + "baselines",
        "def test_architecture_reflects_github_provider_webhook_" + "implementation",
        "def test_architecture_reflects_audit_retention_cleanup_" + "implementation",
        "def test_doc_conflict_audit_does_not_keep_resolved_audit_cleanup_as_"
        + "decision",
        "def test_docs_reflect_audit_events_query_api_" + "completion",
        "def test_task_archives_reflect_webhook_and_result_filter_" + "completion",
        "def test_todo_maintainer_decisions_separate_pending_from_" + "resolved",
        "def test_backlog_docs_distinguish_current_status_from_remaining_" + "gaps",
        "def test_backlog_docs_reflect_project_search_sorting_" + "completion",
        "def test_backlog_docs_reflect_silent_windows_" + "completion",
        "def test_backlog_docs_reflect_single_test_history_" + "completion",
        "def test_backlog_docs_reflect_worker_logging_" + "completion",
        "def test_backlog_docs_reflect_arch_layer_first_stage_" + "completion",
        "def test_test_quality_docs_reflect_soft_deleted_run_state_write_" + "guard",
        "def test_test_quality_docs_reflect_soft_deleted_schedule_due_query_" + "guard",
        "def test_backlog_docs_reflect_opentelemetry_partial_" + "implementation",
        "def test_doc_conflict_audit_reflects_manual_trigger_" + "completion",
        "def test_backlog_docs_reflect_notification_template_partial_" + "completion",
        "def test_backlog_docs_reflect_notification_channels_" + "completion",
        "def test_testing_docs_capture_notification_api_worker_" + "contract",
        "def test_testing_docs_capture_sse_missing_ticket_" + "contract",
        "def test_repeated_http_cancel_assertion_is_exact_terminal_" + "conflict",
        "def test_testing_docs_capture_run_priority_validation_" + "contract",
        "def test_testing_docs_do_not_overclaim_generic_html_artifact_preview_" + "e2e",
        "def test_testing_docs_do_not_treat_printed_worker_secrets_as_"
        + "unimplemented",
    ]:
        assert docs_status_contract not in contract_source
        assert docs_status_contract in docs_status_contract_source
    for docs_current_gate_contract in [
        "def test_testing_strategy_records_current_gate_contract_" + "splits",
    ]:
        assert docs_current_gate_contract not in contract_source
        assert docs_current_gate_contract in docs_current_gate_contract_source
    for executor_engine_contract in [
        "def test_quality_ops_capture_auto_retry_real_db_failure_exact_error_"
        + "contract",
        "def test_quality_ops_capture_executor_skipped_transition_exact_log_"
        + "contract",
        "def test_quality_ops_capture_executor_failed_tests_cap_direct_projection_"
        + "contract",
        "def test_quality_ops_capture_executor_state_transition_commit_sequence_"
        + "contracts",
        "def test_quality_ops_capture_executor_timeout_artifact_log_exact_"
        + "contract",
        "def test_quality_ops_capture_executor_artifact_limit_exact_storage_"
        + "contract",
        "def test_quality_ops_capture_executor_artifact_upload_storage_exact_"
        + "contract",
        "def test_quality_ops_capture_executor_artifact_repo_missing_s3_exact_upload_"
        + "contract",
        "def test_quality_ops_capture_executor_mark_collecting_race_exact_publish_"
        + "contract",
        "def test_quality_ops_capture_run_executor_setup_success_backend_lifecycle_"
        + "contract",
        "def test_quality_ops_capture_run_executor_setup_failure_spec_exact_"
        + "contract",
        "def test_quality_ops_capture_lifespan_worker_startup_exact_init_sequence_"
        + "contract",
        "def test_quality_ops_capture_lifespan_shutdown_close_no_cancel_exact_"
        + "contract",
        "def test_quality_ops_capture_docker_backend_create_execution_exact_config_"
        + "contract",
        "def test_quality_ops_capture_docker_backend_oom_retry_backoff_exact_"
        + "contract",
        "def test_quality_ops_capture_worker_resource_termination_exact_log_fields_"
        + "contract",
        "def test_quality_ops_capture_oom_e2e_exact_resource_termination_log_"
        + "contract",
        "def test_quality_ops_capture_cancel_e2e_create_execution_spec_exact_"
        + "contract",
        "def test_quality_ops_capture_executor_container_log_redaction_exact_"
        + "contract",
        "def test_quality_ops_capture_auto_retry_setup_log_exact_once_" + "contract",
    ]:
        assert executor_engine_contract not in contract_source
        assert executor_engine_contract in executor_engine_contract_source
    for plugin_runner_contract in [
        "def test_quality_ops_capture_plugin_registry_builtins_exact_" + "contract",
        "def test_quality_ops_capture_junit_upload_report_exact_artifact_s3_"
        + "contract",
        "def test_quality_ops_capture_js_runner_subprocess_kwargs_direct_helper_"
        + "contract",
        "def test_quality_ops_capture_js_runner_junit_parent_subprocess_exact_"
        + "contract",
        "def test_quality_ops_capture_js_runner_missing_junit_still_executes_"
        + "contract",
        "def test_quality_ops_capture_js_runner_failure_subprocess_exact_" + "contract",
        "def test_quality_ops_capture_js_runner_env_subprocess_exact_" + "contract",
        "def test_quality_ops_capture_js_runner_success_subprocess_exact_" + "contract",
        "def test_quality_ops_capture_pytest_go_runner_subprocess_kwargs_direct_helper_"
        + "contract",
        "def test_quality_ops_capture_pytest_run_tests_subprocess_env_cwd_exact_"
        + "contract",
        "def test_quality_ops_capture_go_run_tests_env_subprocess_exact_" + "contract",
        "def test_quality_ops_capture_js_runner_command_prefix_exact_helper_"
        + "contract",
        "def test_quality_ops_capture_pytest_runner_shell_command_exact_helper_"
        + "contract",
        "def test_quality_ops_capture_go_runner_junit_failure_skip_exact_subtree_"
        + "contract",
        "def test_quality_ops_capture_plugin_registry_discover_failure_exact_"
        + "contract",
    ]:
        assert plugin_runner_contract not in contract_source
        assert plugin_runner_contract in plugin_runner_contract_source
    for release_gate_contract in [
        "def test_quality_ops_capture_performance_slo_workflow_env_exact_" + "contract",
        "def test_quality_ops_capture_release_candidate_e2e_exact_spec_list_"
        + "contract",
        "def test_quality_ops_capture_ci_workflow_job_topology_exact_" + "contract",
        "def test_quality_ops_capture_release_candidate_gate_profile_structured_"
        + "contract",
        "def test_quality_ops_capture_release_gate_compose_worker_permission_"
        + "contract",
        "def test_quality_ops_capture_performance_slo_manifest_exact_name_"
        + "contract",
    ]:
        assert release_gate_contract not in contract_source
        assert release_gate_contract in release_gate_contract_source
    for resource_api_contract in [
        "def test_quality_ops_capture_credentials_list_exact_response_" + "contract",
        "def test_quality_ops_capture_credential_create_audit_complete_payload_"
        + "contract",
        "def test_quality_ops_capture_environment_list_exact_response_" + "contract",
        "def test_quality_ops_capture_environment_disk_limit_update_exact_"
        + "contract",
        "def test_quality_ops_capture_environment_disk_limit_update_exact_response_body_"
        + "contract",
        "def test_quality_ops_capture_environment_create_disk_defaults_exact_"
        + "contract",
        "def test_quality_ops_capture_environment_env_vars_update_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_notification_rule_list_exact_response_"
        + "contract",
        "def test_quality_ops_capture_notification_rule_crud_exact_response_audit_"
        + "contract",
        "def test_quality_ops_capture_notification_legacy_invalid_list_exact_"
        + "contract",
        "def test_quality_ops_capture_schedule_list_exact_response_" + "contract",
        "def test_quality_ops_capture_schedule_crud_exact_response_audit_" + "contract",
        "def test_quality_ops_capture_schedule_missing_project_lookup_exact_"
        + "contract",
        "def test_quality_ops_capture_schedule_silent_window_integration_exact_no_fire_audit_"
        + "contract",
        "def test_quality_ops_capture_environment_env_vars_aad_mismatch_exact_audit_"
        + "contract",
        "def test_quality_ops_capture_environment_env_vars_encrypted_at_rest_exact_response_"
        + "contract",
        "def test_quality_ops_capture_schedule_validation_detail_exact_" + "contract",
        "def test_quality_ops_capture_silent_window_bypass_exact_run_response_"
        + "contract",
        "def test_quality_ops_capture_credential_encrypt_rotate_exact_aad_response_"
        + "contract",
        "def test_quality_ops_capture_credential_delete_audit_complete_payload_"
        + "contract",
        "def test_quality_ops_capture_notification_template_update_response_audit_exact_"
        + "contract",
    ]:
        assert resource_api_contract not in contract_source
        assert resource_api_contract in resource_api_contract_source
    for audit_contract in [
        "def test_quality_ops_capture_audit_events_owner_admin_exact_list_"
        + "contract",
        "def test_quality_ops_capture_audit_events_empty_list_exact_response_"
        + "contract",
        "def test_quality_ops_capture_audit_events_list_access_exact_response_self_audit_"
        + "contract",
        "def test_quality_ops_capture_audit_events_cross_tenant_exact_envelope_"
        + "contract",
        "def test_quality_ops_capture_audit_events_cross_tenant_exact_list_no_leak_"
        + "contract",
        "def test_quality_ops_capture_audit_events_list_exact_response_" + "contract",
        "def test_quality_ops_capture_audit_events_unit_exact_envelope_" + "contract",
        "def test_quality_ops_capture_write_audit_helper_complete_kwargs_" + "contract",
        "def test_quality_ops_capture_write_audit_failure_exact_warning_" + "contract",
        "def test_quality_ops_capture_project_create_audit_route_exact_wiring_"
        + "contract",
        "def test_quality_ops_capture_audit_events_direct_duplicate_cleanup_"
        + "contract",
    ]:
        assert audit_contract not in contract_source
        assert audit_contract in audit_contract_source
    for pipeline_repository_contract in [
        "def test_quality_ops_capture_audit_retention_exact_delete_count_" + "contract",
        "def test_quality_ops_capture_run_retention_exact_delete_count_" + "contract",
        "def test_quality_ops_capture_project_repository_exact_tenant_list_"
        + "contract",
        "def test_quality_ops_capture_schedule_due_query_exact_result_" + "contract",
        "def test_quality_ops_capture_pipeline_list_exact_response_" + "contract",
        "def test_quality_ops_capture_artifact_repository_pagination_exact_"
        + "contract",
        "def test_quality_ops_capture_pipeline_soft_delete_exact_visible_list_"
        + "contract",
        "def test_quality_ops_capture_repository_matrix_exact_total_" + "contracts",
        "def test_quality_ops_capture_pipeline_missing_project_error_response_"
        + "contract",
        "def test_quality_ops_capture_pipeline_nested_payload_exact_persistence_"
        + "contract",
        "def test_quality_ops_capture_pipeline_core_schema_validation_detail_exact_"
        + "contract",
        "def test_quality_ops_capture_pipeline_nested_validation_detail_exact_"
        + "contract",
        "def test_quality_ops_capture_run_repository_scheduler_sql_column_bound_params_"
        + "contract",
        "def test_quality_ops_capture_schedule_repository_due_sql_column_bound_params_"
        + "contract",
    ]:
        assert pipeline_repository_contract not in contract_source
        assert pipeline_repository_contract in pipeline_repository_contract_source
    for frontend_contract in [
        "def test_quality_ops_capture_frontend_openapi_exact_field_" + "contract",
        "def test_quality_ops_capture_trigger_run_payload_exact_field_" + "contract",
        "def test_quality_ops_capture_notification_rule_create_required_exact_"
        + "contract",
        "def test_quality_ops_capture_frontend_run_terminal_polling_archive_"
        + "contract",
        "def test_quality_ops_capture_frontend_create_payload_optionality_exact_"
        + "contract",
    ]:
        assert frontend_contract not in contract_source
        assert frontend_contract in frontend_contract_source
    for api_guardrails_contract in [
        "def test_quality_ops_capture_admin_status_exact_response_body_" + "contract",
        "def test_quality_ops_capture_cross_tenant_isolation_response_" + "contracts",
        "def test_quality_ops_capture_webhook_signature_empty_secret_" + "contract",
        "def test_quality_ops_capture_webhook_signature_compare_digest_runtime_"
        + "contract",
        "def test_quality_ops_capture_unit_all_assertion_direct_contract_" + "sweep",
        "def test_quality_ops_capture_error_subfield_static_gate_" + "contract",
        "def test_quality_ops_capture_rbac_project_lookup_sequence_exact_" + "contract",
        "def test_quality_ops_capture_soft_delete_infra_exact_empty_list_" + "contract",
        "def test_quality_ops_capture_global_204_empty_body_guard_" + "contract",
        "def test_quality_ops_capture_global_201_response_body_guard_" + "contract",
        "def test_quality_ops_capture_health_uptime_numeric_seconds_" + "contract",
        "def test_quality_ops_capture_health_liveness_exact_response_body_"
        + "contract",
        "def test_quality_ops_capture_security_headers_exact_map_hsts_" + "contract",
        "def test_quality_ops_capture_rbac_dependency_sql_column_bound_params_"
        + "contract",
    ]:
        assert api_guardrails_contract not in contract_source
        assert api_guardrails_contract in api_guardrails_contract_source
    for observability_contract in [
        "def test_quality_ops_capture_logging_renderer_output_shape_" + "contract",
        "def test_quality_ops_capture_opentelemetry_fastapi_exact_instrumentation_"
        + "contract",
    ]:
        assert observability_contract not in contract_source
        assert observability_contract in observability_contract_source
    for analytics_contract in [
        "def test_quality_ops_capture_analytics_success_exact_kwargs_cutoff_window_"
        + "contract",
    ]:
        assert analytics_contract not in contract_source
        assert analytics_contract in analytics_contract_source
    for migration_contract in [
        "def test_quality_ops_capture_migration_007_env_vars_exact_envelope_"
        + "contract",
    ]:
        assert migration_contract not in contract_source
        assert migration_contract in migration_contract_source

    assert (
        "def test_quality_ops_capture_rbac_dependency_sql_column_bound_params_"
        + "contract"
    ) not in contract_source
    assert (
        "def test_quality_ops_capture_frontend_create_payload_optionality_exact_"
        + "contract"
    ) not in contract_source
    assert (
        "def test_quality_ops_capture_run_repository_scheduler_sql_column_bound_params_"
        + "contract"
    ) not in contract_source
    assert (
        "def test_quality_ops_capture_opentelemetry_fastapi_exact_instrumentation_"
        + "contract"
    ) not in contract_source
