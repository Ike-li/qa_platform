from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_access_control_evidence():
    project_cross_tenant_integration_row = _quality_ops_row(
        "| 2026-05-30 | `RUN_INTEGRATION_TESTS=1 "
        "tests/integration/test_api_endpoints.py::"
        "TestCrossTenantIsolation::test_cross_tenant_project_access`"
    )
    audit_events_query_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Audit events query 参数短路契约）"
    )
    audit_events_integration_row = _quality_ops_row(
        "| 2026-05-30 | `RUN_INTEGRATION_TESTS=1 "
        "tests/integration/test_audit_events_api.py::"
        "test_audit_events_owner_admin_can_list_member_viewer_forbidden "
        "tests/integration/test_audit_events_api.py::"
        "test_audit_events_tenant_isolation_and_cross_tenant_ids_return_404`"
    )
    notification_rule_cross_project_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Notification rule item 跨项目 404 等价性契约）"
    )
    rbac_project_lookup_row = _quality_ops_row(
        "| 2026-05-30 | N/A（RBAC project membership lookup scope 契约）"
    )
    permission_context_frozen_row = _quality_ops_row(
        "| 2026-05-30 | N/A（PermissionContext frozen 字段保持契约）"
    )
    rbac_viewer_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（RBAC viewer 权限矩阵精确契约）"
    )
    rbac_non_project_action_row = _quality_ops_row(
        "| 2026-05-30 | N/A（RBAC non-project action 工厂边界契约）"
    )
    assert "1 passed" in project_cross_tenant_integration_row
    assert "同一 `NOT_FOUND` envelope" in project_cross_tenant_integration_row
    assert "不回显外部 project/tenant/user ID" in (project_cross_tenant_integration_row)
    assert "不回显随机探测 ID" in project_cross_tenant_integration_row
    assert "existence oracle 不能泄露标识" in project_cross_tenant_integration_row
    assert "`tests/unit/test_api/test_audit.py` 13 passed" in audit_events_query_row
    assert "coverage unit 1164 passed" in audit_events_query_row
    assert "`/audit-events?action=`、`resource_type=`" in audit_events_query_row
    assert "`start_at > end_at`" in audit_events_query_row
    assert "不查 audit list、不查跨租户 match、不写 `audit_events.list` 自审计" in (
        audit_events_query_row
    )
    assert "空 action/resource_type 会扩大成更宽查询" in audit_events_query_row
    assert "2 passed" in audit_events_integration_row
    assert "403/404 响应体" in audit_events_integration_row
    assert "跨租户 tenant/user/project/event id 不泄漏" in (
        audit_events_integration_row
    )
    assert "拒绝查询不写 `audit_events.list` 自审计" in (audit_events_integration_row)
    assert "成功空列表仍写自审计" in audit_events_integration_row
    assert "安全集成测试只证明状态码" in audit_events_integration_row
    assert (
        "test_notification_rule_item_routes_hide_other_project_rule_without_side_effects"
        in (notification_rule_cross_project_row)
    )
    assert "1 passed" in notification_rule_cross_project_row
    assert (
        "notification rule get/update/delete 对跨项目 rule 与缺失 rule 返回同一 `NOT_FOUND` envelope"
        in (notification_rule_cross_project_row)
    )
    assert "不 update/delete/audit" in notification_rule_cross_project_row
    assert "响应不回显外部 project_id" in notification_rule_cross_project_row
    assert "只覆盖 rule 不存在与 project 不存在" in (
        notification_rule_cross_project_row
    )
    assert "漏掉父项目校验" in notification_rule_cross_project_row
    assert "`tests/unit/test_api/test_rbac_deps.py` 15 passed" in (
        rbac_project_lookup_row
    )
    assert "project_id+tenant_id 收敛" in rbac_project_lookup_row
    assert "project_id+user_id+tenant_id 收敛" in rbac_project_lookup_row
    assert "固定 404" in rbac_project_lookup_row
    assert "不回显 project/user/tenant id" in rbac_project_lookup_row
    assert "固定 403" in rbac_project_lookup_row
    assert "状态码和查询次数" in rbac_project_lookup_row
    assert "没锁住 user/tenant 过滤" in rbac_project_lookup_row
    assert "用别人的 ProjectMember 放行" in rbac_project_lookup_row
    assert "SQL params 和响应脱敏" in rbac_project_lookup_row
    assert "只证明“查过一次并返回 403/404”" in rbac_project_lookup_row
    assert (
        "`tests/unit/test_auth/test_permissions.py::TestPermissionContext::test_frozen` 1 passed"
        in (permission_context_frozen_row)
    )
    assert (
        "PermissionContext frozen 用例从 raises-only 补成 FrozenInstanceError 与字段保持契约"
        in (permission_context_frozen_row)
    )
    assert "只匹配 `user_id`" in permission_context_frozen_row
    assert "frozen dataclass 退化成普通 AttributeError" in (
        permission_context_frozen_row
    )
    assert "赋值失败后原权限上下文字段被污染" in permission_context_frozen_row
    assert "异常类型为 `FrozenInstanceError`" in permission_context_frozen_row
    assert "`cannot assign to field 'user_id'`" in permission_context_frozen_row
    assert "`user_id/role/tenant_id` 原值保持" in permission_context_frozen_row
    assert "权限上下文不可变测试只为异常覆盖率服务" in (permission_context_frozen_row)
    assert (
        "`tests/unit/test_auth/test_permissions.py::TestTenantRolePermissions::test_viewer_has_read_only_actions tests/unit/test_auth/test_permissions.py::TestProjectRolePermissions::test_viewer_is_read_only` 2 passed"
        in (rbac_viewer_exact_row)
    )
    assert "targeted ruff passed" in rbac_viewer_exact_row
    assert "targeted docs contract passed" in rbac_viewer_exact_row
    assert "固定为精确 Action 集合" in rbac_viewer_exact_row
    assert "只检查现有 action 名称里包含 `read`" in rbac_viewer_exact_row
    assert "如果删掉 `RUN_READ`、`MEMBER_READ`" in rbac_viewer_exact_row
    assert "避免权限矩阵测试只证明“剩下的权限看起来只读”" in (rbac_viewer_exact_row)
    assert (
        "`tests/unit/test_api/test_rbac_deps.py::TestEnforceProjectAction::test_non_project_scoped_action_raises_value_error tests/unit/test_api/test_rbac_deps.py::TestRequireProjectPermission::test_factory_rejects_non_project_scoped_action` 2 passed"
        in (rbac_non_project_action_row)
    )
    assert (
        "RBAC 非 project-scoped action 用例从 raises-only 补成 exact ValueError 与数据库零触达契约"
        in (rbac_non_project_action_row)
    )
    assert "只匹配 `non-project-scoped`" in rbac_non_project_action_row
    assert "错误来源被混淆" in rbac_non_project_action_row
    assert "action 名丢失" in rbac_non_project_action_row
    assert (
        "`enforce_project_action` / `require_project_permission` 与 `Action.PROJECT_CREATE`"
        in (rbac_non_project_action_row)
    )
    assert "不 await `session.execute`" in rbac_non_project_action_row
    assert "RBAC 工厂边界测试只为异常覆盖率服务" in (rbac_non_project_action_row)
