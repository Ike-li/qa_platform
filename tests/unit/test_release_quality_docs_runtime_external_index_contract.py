from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import _read


ROOT = Path(__file__).resolve().parents[2]
DOCS_CONTRACT = ROOT / "tests" / "unit" / "test_release_quality_docs_contract.py"
RUNTIME_EXTERNAL_CONTRACTS = (
    (
        Path("tests/unit/test_release_quality_notification_channels_contract.py"),
        (
            "Notification channel text success exact timeout/call " + "契约",
            "Email SMTP error redaction " + "契约",
            "Email SMTP success wait_for/thread exact " + "契约",
            "ChannelRouter exact result propagation " + "契约",
            "Email SMTP timeout wait_for exact " + "契约",
            "Notification channel HTTP request exact args/kwargs " + "契约",
            "Notification HTTP success exact ChannelResult " + "契约",
            "Notification channel failure exact ChannelResult " + "契约",
        ),
    ),
    (
        Path("tests/unit/test_release_quality_performance_contract.py"),
        (
            "def test_quality_ops_capture_artifact_list_p99_exact_page_"
            + "contract",
            "def test_quality_ops_capture_performance_artifact_and_audit_full_dto_"
            + "contract",
            "def test_quality_ops_capture_performance_audit_large_self_audit_exact_list_"
            + "contract",
            "def test_quality_ops_capture_performance_direct_projection_" + "contract",
            "def test_quality_ops_capture_performance_enqueue_exact_arq_call_sequence_"
            + "contract",
            "def test_quality_ops_capture_residual_len_direct_projection_"
            + "contract",
            "def test_quality_ops_capture_performance_write_trigger_direct_projection_"
            + "contract",
            "def test_quality_ops_capture_performance_enqueue_dequeue_full_projection_"
            + "contract",
            "def test_quality_ops_capture_performance_dequeue_audit_direct_projection_"
            + "contract",
            "def test_quality_ops_capture_performance_smoke_exact_response_windows_"
            + "contract",
            "def test_quality_ops_capture_performance_denied_exact_error_body_"
            + "contract",
            "def test_quality_ops_capture_performance_log_artifact_denial_exact_body_"
            + "contract",
            "def test_quality_ops_capture_performance_priority_backlog_order_followup_"
            + "contract",
        ),
    ),
    (
        Path("tests/unit/test_release_quality_worker_external_stack_contract.py"),
        (
            "def test_worker_external_stack_creation_assertions_" + "are_exact",
            "def test_quality_ops_capture_worker_external_stack_artifact_names_exact_"
            + "contract",
            "def test_quality_ops_capture_worker_artifact_page_projection_followup_"
            + "contract",
            "def test_quality_ops_capture_worker_archive_exact_line_read_scope_"
            + "contract",
            "def test_quality_ops_capture_worker_archive_page_projection_followup_"
            + "contract",
            "def test_quality_ops_capture_worker_retry_priority_archive_exact_line_"
            + "contract",
            "def test_quality_ops_capture_worker_10_container_exact_final_statuses_"
            + "contract",
            "def test_quality_ops_capture_worker_10_container_run_id_running_direct_"
            + "contract",
            "def test_quality_ops_capture_worker_external_stack_poll_predicates_are_"
            + "targeted",
            "def test_quality_ops_capture_worker_pytest_package_archive_exact_line_"
            + "contract",
            "def test_quality_ops_capture_worker_live_sse_exact_marker_sequence_"
            + "contract",
            "def test_quality_ops_capture_worker_slo_exact_marker_archive_sequence_"
            + "contract",
            "def test_quality_ops_capture_worker_failure_empty_artifact_exact_response_"
            + "contract",
            "def test_quality_ops_capture_worker_failure_no_retry_direct_attempt_list_"
            + "contract",
            "def test_quality_ops_capture_worker_setup_failure_run_detail_exact_error_"
            + "contract",
            "def test_quality_ops_capture_worker_setup_failure_archive_exact_line_read_scope_"
            + "contract",
            "def test_quality_ops_capture_worker_lost_original_error_exact_heartbeat_"
            + "contract",
            "def test_quality_ops_capture_worker_external_stack_denied_exact_body_"
            + "contract",
            "def test_quality_ops_capture_external_stack_performance_artifact_exact_"
            + "contract",
        ),
    ),
    (
        Path("tests/unit/test_release_quality_real_auth_results_contract.py"),
        (
            "def test_quality_ops_capture_storage_unavailable_exact_body_"
            + "contract",
            "def test_quality_ops_capture_real_auth_artifact_list_exact_response_"
            + "contract",
            "def test_quality_ops_capture_artifact_download_real_404_exact_envelope_"
            + "contract",
            "def test_quality_ops_capture_artifact_upload_limit_exact_log_sequence_"
            + "contract",
            "def test_quality_ops_capture_real_auth_artifact_projection_exact_"
            + "contract",
            "def test_quality_ops_capture_api_token_project_read_exact_list_"
            + "contract",
            "def test_quality_ops_capture_real_auth_token_pagination_exact_response_"
            + "contract",
            "def test_quality_ops_capture_real_auth_token_empty_pagination_exact_response_"
            + "contract",
            "def test_quality_ops_capture_real_auth_audit_events_exact_response_"
            + "contract",
            "def test_quality_ops_capture_real_auth_scope_denial_exact_body_"
            + "contract",
            "def test_quality_ops_capture_api_token_scope_matrix_exact_denial_body_"
            + "contract",
            "def test_quality_ops_capture_real_api_token_revoke_exact_rejection_"
            + "contract",
            "def test_quality_ops_capture_real_auth_results_and_artifacts_exact_response_"
            + "contract",
            "def test_quality_ops_capture_real_auth_field_set_direct_projection_"
            + "contract",
            "def test_quality_ops_capture_real_auth_artifact_list_pagination_exact_response_"
            + "contract",
            "def test_quality_ops_capture_real_auth_archived_log_large_page_exact_window_"
            + "contract",
            "def test_quality_ops_capture_refresh_token_revoke_outage_exact_warning_"
            + "contract",
            "def test_quality_ops_capture_auth_refresh_audit_new_jti_trace_"
            + "contract",
            "def test_quality_ops_capture_auth_token_missing_authorization_integration_exact_response_"
            + "contract",
            "def test_quality_ops_capture_sse_events_real_resume_exact_frame_"
            + "contract",
            "def test_quality_ops_capture_sse_logs_real_resume_exact_frame_"
            + "contract",
            "def test_quality_ops_capture_real_auth_sse_resume_projection_followup_"
            + "contract",
            "def test_quality_ops_capture_real_sse_logs_missing_ticket_exact_body_"
            + "contract",
            "def test_quality_ops_capture_archived_logs_missing_object_exact_envelope_alias_"
            + "gate",
            "def test_quality_ops_capture_integration_field_set_residual_cleanup_"
            + "contract",
            "def test_quality_ops_capture_artifact_response_body_followup_"
            + "contract",
            "def test_quality_ops_capture_real_auth_artifact_list_body_order_followup_"
            + "contract",
        ),
    ),
)


def test_runtime_external_contract_indexes_stay_out_of_docs_main_contract():
    docs_contract_source = _read(DOCS_CONTRACT)

    for relative_path, markers in RUNTIME_EXTERNAL_CONTRACTS:
        contract_source = _read(ROOT / relative_path)
        for marker in markers:
            assert marker not in docs_contract_source
            assert marker in contract_source
