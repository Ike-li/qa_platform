from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_api_boundary_evidence():
    artifact_download_404_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Artifact download 404 短路与 no-storage 契约）"
    )
    ready_degraded_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Ready degraded 双失败防泄漏契约）"
    )
    sse_malformed_ticket_row = _quality_ops_row(
        "| 2026-05-30 | N/A（SSE ticket malformed payload 防泄漏契约）"
    )
    credential_rotate_missing_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Credential rotate 缺失资源无副作用契约）"
    )
    project_member_update_missing_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Project member update 缺失成员无副作用契约）"
    )
    schedule_item_cross_project_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Schedule item 跨项目 404 等价性契约）"
    )
    run_trigger_environment_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Run trigger environment 跨项目 404 等价性契约）"
    )
    batch_internal_failure_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Batch internal failure 防泄漏契约）"
    )
    assert "test_download_artifact_404_short_circuits_before_rbac_or_storage" in (
        artifact_download_404_row
    )
    assert "`tests/unit/test_api/test_artifacts.py` 12 passed" in (
        artifact_download_404_row
    )
    assert "download route 固定返回同一 `Artifact not found` 404" in (
        artifact_download_404_row
    )
    assert "在 RBAC 与 S3 presign 前短路" in artifact_download_404_row
    assert "不回显外部 artifact/run/storage path" in artifact_download_404_row
    assert "`_get_artifact_or_404` helper 已覆盖 missing 与 cross-tenant run" in (
        artifact_download_404_row
    )
    assert "路由绕过 helper、404 后仍触发 RBAC 或预签名" in artifact_download_404_row
    assert "只证明 helper 和 happy path" in artifact_download_404_row
    assert (
        "test_ready_checks_all_dependencies_and_redacts_probe_errors_when_degraded"
        in ready_degraded_row
    )
    assert "`tests/unit/test_api/test_health.py` 6 passed" in ready_degraded_row
    assert "`/ready` 在 DB 与 Redis probe 同时失败时固定返回 degraded" in (
        ready_degraded_row
    )
    assert "两个 probe 都会执行" in ready_degraded_row
    assert "只暴露 `{db: error, redis: error}`" in ready_degraded_row
    assert "不回显底层异常文案" in ready_degraded_row
    assert "第一个 probe 失败后仍会检查第二个依赖" in ready_degraded_row
    assert "`database probe failed` / `redis probe failed`" in ready_degraded_row
    assert "只证明单点失败状态码" in ready_degraded_row
    assert "test_authenticate_sse_ticket_rejects_malformed_payload_without_leaking" in (
        sse_malformed_ticket_row
    )
    assert "`tests/unit/test_api/test_sse.py` 23 passed" in sse_malformed_ticket_row
    assert "非 JSON、非 object、缺字段、非法 UUID、role/scopes 类型错误" in (
        sse_malformed_ticket_row
    )
    assert "固定返回同一 401" in sse_malformed_ticket_row
    assert "不回显 payload、ticket 或 secret marker" in sse_malformed_ticket_row
    assert "只使用原子 `getdel`" in sse_malformed_ticket_row
    assert "不回退 `get`/`delete`" in sse_malformed_ticket_row
    assert "scope 保留和 getdel 原子消费" in sse_malformed_ticket_row
    assert "回显 payload、ticket、secret" in sse_malformed_ticket_row
    assert "racy get/delete" in sse_malformed_ticket_row
    assert "只证明一种 legacy 格式会失败" in sse_malformed_ticket_row
    assert "test_rotate_credential_404_when_missing_without_side_effects" in (
        credential_rotate_missing_row
    )
    assert "`tests/unit/test_api/test_credentials.py` 14 passed" in (
        credential_rotate_missing_row
    )
    assert "项目存在但 credential 缺失时固定返回 `NOT_FOUND` envelope" in (
        credential_rotate_missing_row
    )
    assert "不调用 crypto、不 update、不写 audit" in credential_rotate_missing_row
    assert "rotate 成功、crypto 503 和明文不泄露" in credential_rotate_missing_row
    assert "先加密再查资源" in credential_rotate_missing_row
    assert "对 `None` 执行 update" in credential_rotate_missing_row
    assert "只证明 AAD happy path 与 crypto unavailable" in (
        credential_rotate_missing_row
    )
    assert "test_update_nonexistent_member_returns_404_without_side_effects" in (
        project_member_update_missing_row
    )
    assert "`tests/unit/test_api/test_project_members.py` 10 passed" in (
        project_member_update_missing_row
    )
    assert "项目存在但成员缺失时固定返回 `NOT_FOUND` envelope" in (
        project_member_update_missing_row
    )
    assert "不 update、不写 audit" in project_member_update_missing_row
    assert "delete 缺失成员、缺失项目、非法 role、跨租户 user 和 duplicate add" in (
        project_member_update_missing_row
    )
    assert "对不存在成员执行 update" in project_member_update_missing_row
    assert "404 前误写 audit" in project_member_update_missing_row
    assert "只证明 happy path role 变更" in project_member_update_missing_row
    assert (
        "test_schedule_item_routes_hide_other_project_schedule_without_side_effects"
        in schedule_item_cross_project_row
    )
    assert "1 passed" in schedule_item_cross_project_row
    assert (
        "schedule get/update/delete 对跨项目 schedule 与缺失 schedule 返回同一 `NOT_FOUND` envelope"
        in schedule_item_cross_project_row
    )
    assert "不 update/delete/audit" in schedule_item_cross_project_row
    assert "不调用 `compute_next_run_at`" in schedule_item_cross_project_row
    assert "响应不回显外部 project_id" in schedule_item_cross_project_row
    assert "只覆盖 schedule 不存在" in schedule_item_cross_project_row
    assert "漏掉父项目校验" in schedule_item_cross_project_row
    assert (
        "test_trigger_run_hides_missing_or_other_project_environment_without_side_effects"
        in run_trigger_environment_row
    )
    assert "1 passed" in run_trigger_environment_row
    assert "缺失 environment 或跨项目 environment 都返回同一 `NOT_FOUND` envelope" in (
        run_trigger_environment_row
    )
    assert "不创建 run、不设置 retry group、不入队、不写 audit" in (
        run_trigger_environment_row
    )
    assert "响应不回显外部 project_id" in run_trigger_environment_row
    assert "`environment.project_id != project.id` 防护" in (
        run_trigger_environment_row
    )
    assert "漏掉 environment 父项目校验" in run_trigger_environment_row
    assert "只证明 pipeline 边界能隐藏" in run_trigger_environment_row
    assert (
        "test_batch_cancel_internal_failure_redacts_exception_without_side_effects"
        in batch_internal_failure_row
    )
    assert (
        "test_batch_retry_internal_failure_redacts_exception_without_side_effects"
        in batch_internal_failure_row
    )
    assert "batch cancel/retry slice 8 passed" in batch_internal_failure_row
    assert "`tests/unit/test_api/test_p3.py` 55 passed" in batch_internal_failure_row
    assert "`<run_id>: operation failed`" in batch_internal_failure_row
    assert "不回显 SQL/secret/底层异常文本" in batch_internal_failure_row
    assert (
        "不 cancel、不 publish Redis cancel/status、不 create retry run、不 enqueue、不写 audit"
        in batch_internal_failure_row
    )
    assert "`SQLAlchemyError` / `ValueError` 分支直接把异常文本拼进 `errors`" in (
        batch_internal_failure_row
    )
    assert "带 SQL、token、内部字段的异常" in batch_internal_failure_row
    assert "客户端可见" in batch_internal_failure_row
    assert "两条失败注入锁住通用错误和零副作用" in batch_internal_failure_row
    assert "只证明业务失败会列入 errors" in batch_internal_failure_row
