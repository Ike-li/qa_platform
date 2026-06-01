from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _block_between,
    _marked_block,
    _marked_block_or_tail,
    _quality_ops_row,
    _quality_ops_row_containing,
    _quality_ops_rows_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
API_ENDPOINTS = ROOT / "tests" / "integration" / "test_api_endpoints.py"
ENVIRONMENTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_environments.py"
REAL_API_WRITE_STATE = ROOT / "tests" / "integration" / "test_real_api_write_state.py"
INTEGRATION_SCHEMA_BOOTSTRAP_CONTRACT = (
    ROOT / "tests" / "unit" / "test_integration_schema_bootstrap_contract.py"
)


def test_quality_ops_capture_environment_and_schedule_404_envelope_contracts():
    row = _quality_ops_row_containing(
        "Environment 缺失/跨项目 env",
        "Schedule 跨项目 pipeline 拒绝路径固定 exact `NOT_FOUND` envelope",
    )
    environment_tests = _read(ENVIRONMENTS_TEST)
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    assert "Environment 缺失/跨项目 env、缺失 project" in row
    assert "Schedule 跨项目 pipeline 拒绝路径固定 exact `NOT_FOUND` envelope" in (
        row
    )
    assert "不再兼容 legacy `detail or error.message`" in row
    assert "tests/unit/test_api/test_environments.py::test_get_environment_returns_same_404_for_missing_or_other_project" in (
        row
    )
    assert "test_schedule_api_rejects_cross_project_pipeline_without_persisting" in (
        row
    )
    assert "_assert_not_found_response" in environment_tests
    assert '_assert_not_found_response(wrong_project_body, "Environment not found")' in (
        environment_tests
    )
    assert 'assert bodies == [expected_body] * 5' in environment_tests
    assert 'get("detail") or' not in environment_tests
    assert "_assert_not_found_response" in real_api_write_state
    assert '_assert_not_found_response(resp.json(), "Pipeline not found")' in (
        real_api_write_state
    )
    assert 'get("detail") or' not in real_api_write_state


def test_quality_ops_capture_real_api_archived_project_run_exact_rejection_contract():
    row = _quality_ops_row_containing(
        "archived project manual run integration exact rejection 契约"
    )
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    assert "archived project manual run integration exact rejection 契约" in (
        row
    )
    assert (
        '固定 409 body `{"detail": "Project is archived; new runs cannot be triggered"}`'
        in row
    )
    assert "manual Run 数量和 `run.create` 审计数量不变" in row
    assert "只断言 `409` 和 detail 含 `archived`" in row
    assert "拒绝路径误写 `run.create` 审计" in row
    assert "含 archived 的 409" in row

    block = _marked_block_or_tail(
        real_api_write_state,
        "async def test_manual_run_archived_project_returns_409_without_persisting",
        "\n\n@pytest.mark.asyncio",
    )

    assert "from qaplatform.infra.database.models import AuditEvent, Run" in block
    assert "before_run_create_audits = await _row_count(" in block
    assert 'AuditEvent.action == "run.create"' in block
    assert "assert resp.json() == {" in block
    assert '"detail": "Project is archived; new runs cannot be triggered"' in block
    assert "== before_run_create_audits" in block
    assert 'assert "archived" in resp.json()["detail"].lower()' not in block


def test_quality_ops_capture_real_api_write_state_exact_audit_actions():
    row = _quality_ops_row_containing("真实写路径 lifecycle 审计 action")
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    assert "真实写路径 lifecycle 审计 action" in row
    assert "从 `issubset` 提升为精确列表" in row
    assert "不允许额外 action 或重复 action 混入" in row
    assert "_assert_audit_actions" in real_api_write_state
    assert ".issubset(" not in real_api_write_state
    assert 'expected={"project.create", "project.update", "project.delete"}' in (
        real_api_write_state
    )
    assert 'expected={"pipeline.create", "pipeline.update", "pipeline.delete"}' in (
        real_api_write_state
    )
    assert '"project_member.add"' in real_api_write_state
    assert '"credential.rotate"' in real_api_write_state
    assert '"environment.delete"' in real_api_write_state
    assert '"notification_rule.update"' in real_api_write_state
    assert 'expected={"schedule.create", "schedule.update", "schedule.delete"}' in (
        real_api_write_state
    )
    assert 'actions == ["run.batch_cancel", "run.batch_retry"]' in real_api_write_state


def test_quality_ops_capture_project_real_api_lifecycle_exact_response_audit_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_project_api_audits_lifecycle_without_git_url_userinfo_leak")

    assert "` 1 passed" in row
    assert "release quality docs contract full 236 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 ProjectResponse 字段集合与默认值" in row
    assert "update 响应只允许 description/git_url/status/updated_at 变化" in row
    assert "三条 `project.*` AuditEvent 均要求 tenant/user/resource 完整匹配" in row
    assert "before/after_state 分别精确等于脱敏 git_url 后的响应投影" in row
    assert "userinfo token 不进入任何审计 payload" in row
    assert "此前只抽查 API git_url、DB status、审计 action 集合" in row
    assert "审计 git_url/status 片段" in row
    assert "响应漏字段" in row
    assert "update 改坏不相关字段" in row
    assert "审计归属写错" in row
    assert "before/after_state 漏字段" in row
    assert "项目真实写路径测试只证明“项目能改删且审计里有脱敏 URL”" in row

    block = _marked_block(
        real_api_write_state,
        "async def test_project_api_audits_lifecycle_without_git_url_userinfo_leak",
        "async def test_pipeline_api_persists_audit_states_for_lifecycle",
    )

    for expected in [
        "create_body = create_resp.json()",
        "assert create_body == {",
        '"tenant_id": str(seed_run["tenant"].id)',
        '"name": f"Audit Project {slug}"',
        '"git_auth_method": "none"',
        '"credential_id": None',
        '"root_path": "."',
        '"shallow_clone": True',
        '"default_env_id": None',
        '"settings": {}',
        '"silent_windows": []',
        '"status": "active"',
        '"created_by": str(seed_run["user"].id)',
        "update_body = update_resp.json()",
        "assert update_body == {",
        "**create_body",
        '"description": "archived for audit evidence"',
        '"git_url": update_git_url',
        '"status": "archived"',
        '"updated_at": update_body["updated_at"]',
        "for event in [create_audit, update_audit, delete_audit]:",
        'assert event.resource_type == "project"',
        "assert event.resource_id == project.id",
        "expected_create_audit_after = {",
        '"git_url": "https://***@example.com/org/repo.git"',
        "expected_update_audit_after = {",
        '"git_url": "https://***@git.example.com/new/repo.git"',
        "assert create_audit.after_state == expected_create_audit_after",
        "assert update_audit.before_state == expected_create_audit_after",
        "assert update_audit.after_state == expected_update_audit_after",
        "assert delete_audit.before_state == expected_update_audit_after",
        "assert delete_audit.after_state is None",
        "assert create_secret not in serialized_audit",
        "assert update_secret not in serialized_audit",
    ]:
        assert expected in block

    assert 'create_resp.json()["git_url"]' not in block
    assert 'update_resp.json()["git_url"]' not in block
    assert 'create_audit.after_state["git_url"]' not in block
    assert 'update_audit.after_state["status"]' not in block


def test_quality_ops_capture_project_member_real_api_exact_response_audit_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_project_member_api_persists_audit_states_for_role_changes")

    assert "` 1 passed" in row
    assert "release quality docs contract full 237 passed" in row
    assert "targeted ruff passed" in row
    assert "add/update 完整 ProjectMemberResponse" in row
    assert "remove 204 空响应" in row
    assert "软删除后 repository 不可见" in row
    assert "三条 `project_member.*` AuditEvent 的 tenant/user/resource 完整匹配" in row
    assert "add/update after_state 精确等于 API 响应" in row
    assert "update/remove before_state 固定 user_id+role" in row
    assert "remove after_state 为 None" in row
    assert "此前只看 add 响应 role" in row
    assert "少量 audit role 字段" in row
    assert "username/email/created_at 响应串错" in row
    assert "update 返回旧 role" in row
    assert "204 响应夹带 body" in row
    assert "审计 resource_type/resource_id 写错" in row
    assert "after_state 只写子集" in row
    assert "成员真实写路径测试只证明“角色变了且审计里有 role”" in row

    block = _marked_block(
        real_api_write_state,
        "async def test_project_member_api_persists_audit_states_for_role_changes",
        "async def test_credentials_api_persists_encrypted_value_rotates_and_soft_deletes",
    )

    for expected in [
        "add_body = add_resp.json()",
        "assert add_body == {",
        '"project_id": str(project_id)',
        '"user_id": str(member_user.id)',
        '"username": member_user.username',
        '"email": member_user.email',
        '"role": "developer"',
        '"created_at": _json_datetime(member.created_at)',
        "update_body = update_resp.json()",
        'assert update_body == {**add_body, "role": "viewer"}',
        'assert delete_resp.content == b""',
        "assert await repo.get_by_project_user(project_id, member_user.id, tenant_id) is None",
        "for event in [add_audit, update_audit, remove_audit]:",
        "assert event.tenant_id == tenant_id",
        'assert event.resource_type == "project_member"',
        "assert event.resource_id == project_id",
        "assert add_audit.before_state is None",
        "assert add_audit.after_state == add_body",
        'assert update_audit.before_state == {',
        '"role": "developer"',
        "assert update_audit.after_state == update_body",
        'assert remove_audit.before_state == {',
        '"role": "viewer"',
        "assert remove_audit.after_state is None",
    ]:
        assert expected in block

    assert 'add_resp.json()["role"]' not in block
    assert 'add_audit.after_state["role"]' not in block
    assert 'update_audit.after_state["role"]' not in block


def test_quality_ops_capture_pipeline_real_api_lifecycle_exact_audit_projection_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_pipeline_api_persists_audit_states_for_lifecycle")

    assert "` 1 passed" in row
    assert "release quality docs contract full 238 passed" in row
    assert "targeted ruff passed" in row
    assert "三条 `pipeline.*` AuditEvent 的 tenant/user/resource 完整匹配" in row
    assert "delete 204 空响应" in row
    assert "before/after_state 精确等于 API 响应的递归脱敏投影" in row
    assert "URL userinfo 保留 host/path 后脱敏" in row
    assert "secret/token/credential/Authorization 等 key" in row
    assert "`{\"redacted\": true}`" in row
    assert "此前虽然覆盖多类敏感字段，但仍是一串字段抽查" in row
    assert "audit before_state 漏字段" in row
    assert "after_state 夹带额外字段" in row
    assert "update/delete 使用错版本响应" in row
    assert "tokens 列表/trigger_config 某个分支未脱敏" in row
    assert "pipeline 审计测试只证明“几个敏感字段被处理过”" in row

    block = _marked_block(
        real_api_write_state,
        "async def test_pipeline_api_persists_audit_states_for_lifecycle",
        "async def test_project_member_api_persists_audit_states_for_role_changes",
    )

    for expected in [
        "create_body = create_resp.json()",
        "update_body = update_resp.json()",
        'assert delete_resp.content == b""',
        "for event in [create_audit, update_audit, delete_audit]:",
        'assert event.resource_type == "pipeline"',
        "assert event.resource_id == pipeline.id",
        "expected_create_audit_after = {",
        "**create_body",
        '"https://***@packages.example/simple"',
        '"API_TOKEN": {"redacted": True}',
        '"Authorization": {"redacted": True}',
        '"webhook_secret": {"redacted": True}',
        '"credential_id": {"redacted": True}',
        '"clone_url": "https://***@git.example/repo.git"',
        "expected_update_audit_after = {",
        "**update_body",
        '"https://***@git.example/org/repo.git"',
        '"PASSWORD": {"redacted": True}',
        '"tokens": {"redacted": True}',
        '"secret_header": {"redacted": True}',
        '"url": "https://***@deploy.example/hook"',
        '"access_token": {"redacted": True}',
        "assert create_audit.before_state is None",
        "assert create_audit.after_state == expected_create_audit_after",
        "assert update_audit.before_state == expected_create_audit_after",
        "assert update_audit.after_state == expected_update_audit_after",
        "assert delete_audit.before_state == expected_update_audit_after",
        "assert delete_audit.after_state is None",
    ]:
        assert expected in block

    for weak_fragment in [
        'create_audit.after_state["name"]',
        'create_audit.after_state["retry_policy"]',
        'update_audit.before_state["enabled"]',
        'update_audit.after_state["enabled"]',
        'update_audit.after_state["trigger_config"]',
        'delete_audit.before_state["enabled"]',
    ]:
        assert weak_fragment not in block


def test_quality_ops_capture_environment_real_api_lifecycle_exact_response_audit_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_environment_api_persists_encrypted_env_vars_limits_and_soft_delete")

    assert "` 1 passed" in row
    assert "release quality docs contract full 239 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 EnvironmentResponse" in row
    assert "delete 204 空响应" in row
    assert "DB env_vars 非明文" in row
    assert "resource_limits 持久化" in row
    assert "repository 软删除不可见" in row
    assert "三条 `environment.*` AuditEvent 的 tenant/user/resource 完整匹配" in row
    assert 'env_vars 替换为 `{"redacted": true, "count": 1}` 的投影' in row
    assert "原始/轮换 token 不进入任何审计 payload" in row
    assert "此前只抽查 env_vars 响应、disk_mb、DB 加密" in row
    assert "audit env_vars 红action 片段" in row
    assert "resource_limits 响应/DB 不一致" in row
    assert "before/after_state 串错" in row
    assert "环境真实写路径测试只证明“变量加密了且审计里 env_vars 被打码”" in row

    helper_block = _marked_block(
        real_api_write_state,
        "def _expected_environment_audit_state",
        "class _RecordingArq",
    )
    assert '"env_vars": {"redacted": True, "count": len(body["env_vars"])}' in (
        helper_block
    )

    block = _marked_block(
        real_api_write_state,
        "async def test_environment_api_persists_encrypted_env_vars_limits_and_soft_delete",
        "async def test_environment_api_reads_resource_limits_without_audit_secret_leak",
    )

    for expected in [
        "create_body = create_resp.json()",
        "assert create_body == {",
        '"project_id": str(project_id)',
        '"name": name',
        '"base_image": "python:3.12-alpine"',
        '"setup_script": None',
        '"memory_mb": 384',
        '"cpu_cores": 0.75',
        '"disk_mb": 2048',
        '"max_artifact_size_mb": 42',
        '"max_artifacts_count": 9',
        '"network_policy": "restricted"',
        '"env_vars": {"API_TOKEN": "secret-token"}',
        '"cache_key": "deps-v1"',
        "update_body = update_resp.json()",
        "assert update_body == {",
        "**create_body",
        '"memory_mb": 512',
        '"disk_mb": 4096',
        '"max_artifact_size_mb": 64',
        '"env_vars": {"API_TOKEN": "rotated-token"}',
        'assert delete_resp.content == b""',
        "for event in [create_audit, update_audit, delete_audit]:",
        'assert event.resource_type == "environment"',
        "assert event.resource_id == env.id",
        "expected_create_audit_after = _expected_environment_audit_state(create_body)",
        "expected_update_audit_after = _expected_environment_audit_state(update_body)",
        "assert create_audit.before_state is None",
        "assert create_audit.after_state == expected_create_audit_after",
        "assert update_audit.before_state == expected_create_audit_after",
        "assert update_audit.after_state == expected_update_audit_after",
        "assert delete_audit.before_state == expected_update_audit_after",
        "assert delete_audit.after_state is None",
        'assert "secret-token" not in serialized_audit',
        'assert "rotated-token" not in serialized_audit',
    ]:
        assert expected in block

    for weak_fragment in [
        'body["env_vars"]',
        'body["disk_mb"]',
        'update_resp.json()["env_vars"]',
        'create_audit.after_state["env_vars"]',
        'update_audit.before_state["env_vars"]',
        'delete_audit.before_state["env_vars"]',
    ]:
        assert weak_fragment not in block


def test_quality_ops_capture_notification_rule_real_api_exact_response_audit_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_notification_rule_api_persists_updates_and_hides_soft_deleted_rule")

    assert "` 1 passed" in row
    assert "release quality docs contract full 240 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 NotificationRuleResponse" in row
    assert "email/webhook channel canonical config" in row
    assert "delete 204 空响应" in row
    assert "repository 软删除不可见" in row
    assert "三条 `notification_rule.*` AuditEvent 的 tenant/user/resource 完整匹配" in row
    assert "before/after_state 精确等于 API 响应投影" in row
    assert "conditions 保留" in row
    assert "channels 只留 redacted/count/types" in row
    assert "template 只留 redacted/present/length" in row
    assert "webhook URL 和模板 secret 不进审计" in row
    assert "此前只抽查 DB channel config" in row
    assert "audit channels/template 少量字段" in row
    assert "template 明文进入审计" in row
    assert "audit before_state 用错版本" in row
    assert "通知规则真实写路径测试只证明“channel 被归一化且审计里 channels 被打码”" in row

    helper_block = _marked_block(
        real_api_write_state,
        "def _expected_notification_rule_audit_state",
        "class _RecordingArq",
    )
    for expected in [
        '"conditions": body["conditions"]',
        '"types": [channel["type"] for channel in body["channels"]]',
        '"present": body["template"] is not None',
        '"length": len(body["template"] or "")',
    ]:
        assert expected in helper_block

    block = _marked_block(
        real_api_write_state,
        "async def test_notification_rule_api_persists_updates_and_hides_soft_deleted_rule",
        "async def test_schedule_and_run_apis_persist_next_run_metadata_and_audit_rows",
    )

    for expected in [
        "create_body = create_resp.json()",
        "assert create_body == {",
        '"project_id": str(project_id)',
        '"enabled": True',
        '"conditions": [{"field": "status", "operator": "eq", "value": "failed"}]',
        '"type": "email"',
        '"config": {"to_addresses": [email_address]}',
        '"template": "Run {{run_id}} failed secret-template-marker"',
        "update_body = update_resp.json()",
        "assert update_body == {",
        "**create_body",
        '"enabled": False',
        '"type": "webhook"',
        '"config": {"url": webhook_url}',
        'assert delete_resp.content == b""',
        "assert total == 0",
        "assert visible == []",
        "for event in [create_audit, update_audit, delete_audit]:",
        'assert event.resource_type == "notification_rule"',
        "assert event.resource_id == rule.id",
        "expected_create_audit_after = _expected_notification_rule_audit_state(create_body)",
        "expected_update_audit_after = _expected_notification_rule_audit_state(update_body)",
        "assert create_audit.before_state is None",
        "assert create_audit.after_state == expected_create_audit_after",
        "assert update_audit.before_state == expected_create_audit_after",
        "assert update_audit.after_state == expected_update_audit_after",
        "assert delete_audit.before_state == expected_update_audit_after",
        "assert delete_audit.after_state is None",
        "assert webhook_url not in serialized_audit",
        'assert "secret-template-marker" not in serialized_audit',
    ]:
        assert expected in block

    for weak_fragment in [
        'create_resp.json()["id"]',
        'create_audit.after_state["channels"]',
        'update_audit.after_state["channels"]',
        'delete_audit.before_state["channels"]',
        'delete_audit.before_state["template"]',
    ]:
        assert weak_fragment not in block


def test_quality_ops_capture_notification_rule_integration_exact_response_audit_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
            "tests/integration/test_api_endpoints.py::TestNotificationRules::"
            "test_create_notification_rule tests/integration/test_api_endpoints.py::"
            "TestNotificationRules::test_update_notification_rule -q` 2 passed")
    create_block = _block_between(api_endpoints, "async def test_create_notification_rule", "@pytest.mark.parametrize")
    update_block = _block_between(api_endpoints, "async def test_update_notification_rule", "async def test_delete_notification_rule")

    assert "release quality docs contract full 314 passed" in row
    assert "targeted ruff passed" in row
    assert "固定完整 NotificationRuleResponse" in row
    assert "`_notification_rule_audit_state`" in row
    assert "before_state/after_state 完整脱敏" in row
    assert "DB 行的 project/name/enabled/conditions/channels/template 与响应一致" in row
    assert "Notification rule integration exact response/audit 契约" in row
    assert "只证明“规则名和启用状态看起来对”" in row

    for expected in [
        "def _notification_rule_audit_state(body: dict) -> dict:",
        '"conditions": body["conditions"]',
        '"types": [channel["type"] for channel in body["channels"]]',
        '"present": body["template"] is not None',
        '"length": len(body["template"] or "")',
    ]:
        assert expected in api_endpoints
    for expected in [
        "expected_body = {",
        '"project_id": project_id',
        '"conditions": payload["conditions"]',
        '"template": None',
        "assert body == expected_body",
        "assert rule.conditions == payload[\"conditions\"]",
        "assert audit.before_state is None",
        "assert audit.after_state == _notification_rule_audit_state(expected_body)",
    ]:
        assert expected in create_block
    for expected in [
        "assert created == {",
        '"name": "before-update"',
        '"conditions": []',
        "before_audit_state = _notification_rule_audit_state(created)",
        'expected_body = {**created, "name": "after-update", "enabled": False}',
        "assert body == expected_body",
        "assert rule.conditions == created[\"conditions\"]",
        "assert audit.before_state == before_audit_state",
        "assert audit.after_state == _notification_rule_audit_state(expected_body)",
    ]:
        assert expected in update_block
    combined = create_block + update_block
    assert 'assert body["name"] == "slack-alert"' not in create_block
    assert 'assert body["channels"] == [' not in create_block
    assert 'assert created["channels"] == [' not in update_block
    assert 'assert body["name"] == "after-update"' not in update_block
    assert 'assert body["enabled"] is False' not in update_block
    assert 'audit.after_state["channels"]' not in combined


def test_quality_ops_capture_schedule_run_real_api_exact_response_audit_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_schedule_and_run_apis_persist_next_run_metadata_and_audit_rows")

    assert "` 1 passed" in row
    assert "release quality docs contract full 241 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 ScheduleResponse" in row
    assert "delete 204 空响应" in row
    assert "真实 Schedule 行 next_run/missed_fire_policy 更新" in row
    assert "Run metadata/retry_group 入库" in row
    assert "三条 `schedule.*` AuditEvent 与 `run.trigger` AuditEvent" in row
    assert "tenant/user/resource/before_state/after_state 完整匹配" in row
    assert "schedule delete before_state 精确等于更新后的响应" in row
    assert "schedule 响应本身未精确固定" in row
    assert "delete audit 只抽 cron/enabled" in row
    assert "run.trigger audit 也未验证 tenant/resource 归属" in row
    assert "update next_run_at 串错" in row
    assert "run audit 写错 resource_type/resource_id" in row
    assert "调度真实写路径测试只证明“schedule 审计大概写了，run 也触发了”" in row

    block = _marked_block(
        real_api_write_state,
        "async def test_schedule_and_run_apis_persist_next_run_metadata_and_audit_rows",
        "async def test_manual_run_priority_persists_worker_queue_metadata_with_real_db",
    )

    for expected in [
        "created_schedule = schedule_resp.json()",
        "assert created_schedule == {",
        '"project_id": str(project_id)',
        '"pipeline_id": str(pipeline_id)',
        '"cron_expr": "*/15 * * * *"',
        '"timezone": "Asia/Shanghai"',
        '"missed_fire_policy": "run_once"',
        '"quiet_windows": [',
        '{"start": "00:00", "end": "01:00", "timezone": "Asia/Shanghai"}',
        '"last_run_at": None',
        '"next_run_at": created_schedule["next_run_at"]',
        '"last_error": None',
        "updated_schedule = update_resp.json()",
        "assert updated_schedule == {",
        "**created_schedule",
        '"cron_expr": "*/30 * * * *"',
        '"enabled": False',
        '"next_run_at": updated_schedule["next_run_at"]',
        'assert delete_resp.content == b""',
        "for event in [create_audit, update_audit, delete_audit]:",
        'assert event.resource_type == "schedule"',
        "assert event.resource_id == schedule.id",
        "assert create_audit.after_state == created_schedule",
        "assert update_audit.before_state == created_schedule",
        "assert update_audit.after_state == updated_schedule",
        "assert delete_audit.before_state == updated_schedule",
        "assert delete_audit.after_state is None",
        "assert run_audit.tenant_id == seed_run[\"tenant\"].id",
        "assert run_audit.user_id == seed_run[\"user\"].id",
        'assert run_audit.resource_type == "run"',
        "assert run_audit.resource_id == run.id",
        "assert run_audit.before_state is None",
        "assert run_audit.after_state == created_run",
    ]:
        assert expected in block

    for weak_fragment in [
        'delete_audit.before_state["cron_expr"]',
        'delete_audit.before_state["enabled"]',
    ]:
        assert weak_fragment not in block


def test_quality_ops_capture_real_api_write_pagination_exact_response_contract():
    row = _quality_ops_row_containing(
        "真实 DB credentials 与 project members 分页测试"
    )
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    assert "真实 DB credentials 与 project members 分页测试" in row
    assert "第二页完整 data 响应必须精确等于最早创建的记录" in row
    assert "完整 body 等值后不再重复字段集合守门" in row
    assert "避免 credentials/members 分页测试只证明“第二页有一条”" in row
    assert "assert credentials_body == {" in real_api_write_state
    assert '"data": [created_credentials[0]]' in real_api_write_state
    assert 'assert set(credentials_body["data"][0]) == {' not in real_api_write_state
    assert "assert members_body == {" in real_api_write_state
    assert '"data": [created_members[0]]' in real_api_write_state
    assert 'assert set(members_body["data"][0]) == {' not in real_api_write_state
    assert 'assert len(credentials_body["data"]) == 1' not in real_api_write_state
    assert 'assert "value" not in credentials_body["data"][0]' not in (
        real_api_write_state
    )
    assert 'assert len(members_body["data"]) == 1' not in real_api_write_state
    assert 'members_body["data"][0]["role"] == "developer"' not in (
        real_api_write_state
    )


def test_quality_ops_capture_real_api_write_empty_pagination_exact_response_contract():
    row = _quality_ops_row_containing(
        "真实 DB credentials 与 project members 空分页现在固定完整"
    )
    real_api_write_state = _read(REAL_API_WRITE_STATE)
    test_block = _block_between(real_api_write_state, "async def test_project_member_and_credential_lists_are_paginated", "async def test_environment_api_persists_encrypted_env_vars_limits_and_soft_delete")

    assert "真实 DB credentials 与 project members 空分页现在固定完整" in row
    assert "release quality docs contract full 245 passed" in row
    assert "避免 credentials/members 空分页测试只证明“空列表且总数对”" in (
        row
    )
    assert "credentials_empty_body = credentials_empty_page.json()" in test_block
    assert "assert credentials_empty_body == {" in test_block
    assert '"data": []' in test_block
    assert '"page": 99' in test_block
    assert '"per_page": 2' in test_block
    assert '"total": 3' in test_block
    assert "members_empty_body = members_empty_page.json()" in test_block
    assert "assert members_empty_body == {" in test_block
    assert 'credentials_empty_page.json()["data"]' not in test_block
    assert 'credentials_empty_page.json()["total"]' not in test_block
    assert 'members_empty_page.json()["data"]' not in test_block
    assert 'members_empty_page.json()["total"]' not in test_block


def test_quality_ops_capture_integration_analytics_history_exact_response_contract():
    row = _quality_ops_row_containing("analytics test-history 真实 API integration")
    api_endpoints = _read(API_ENDPOINTS)

    assert "analytics test-history 真实 API integration" in row
    assert "包含两个历史点的 run_id/run_created_at/run_status/status" in row
    assert "避免 analytics 历史测试只证明“两个 run 大致按顺序返回”" in (
        row
    )
    assert "assert body == {" in api_endpoints
    assert '"run_created_at": base_time.isoformat().replace("+00:00", "Z")' in (
        api_endpoints
    )
    assert '"duration_ms": 10' in api_endpoints
    assert '"error_message": None' in api_endpoints
    assert '"run_created_at": (base_time + timedelta(minutes=5))' in api_endpoints
    assert '"error_message": "expected checkout to pass"' in api_endpoints
    assert '"pagination": {"offset": 0, "limit": 50, "total": 2}' in api_endpoints
    assert 'assert set(body["data"][0]) == {' not in api_endpoints
    assert (
        'assert body["pagination"] == {"offset": 0, "limit": 50, "total": 2}\n'
        '        assert [point["run_id"] for point in body["data"]] == ['
    ) not in api_endpoints
    assert 'assert body["data"][0]["git_ref"] == "analytics-history-a"' not in (
        api_endpoints
    )


def test_quality_ops_capture_integration_analytics_trends_flaky_exact_response_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
        "tests/integration/test_api_endpoints.py::TestAnalytics::test_get_trends "
        "tests/integration/test_api_endpoints.py::TestAnalytics::test_get_flaky -q` 2 passed"
    )
    analytics_block = _block_between(api_endpoints, "class TestAnalytics:", "# --------------------------------------------------------------------------- #\n# Cross-tenant isolation")
    trends_block = _block_between(analytics_block, "async def test_get_trends", "async def test_get_flaky")
    flaky_block = _block_between(analytics_block, "async def test_get_flaky", "async def test_get_test_history")

    assert "release quality docs contract full 318 passed" in row
    assert "targeted ruff passed" in row
    assert "Analytics trends/flaky 真实 API 集成用例" in row
    assert "完整 response body" in row
    assert "flaky 的 data 与默认 `limit=50` 全部等值" in row
    assert "analytics trends/flaky integration exact response 契约" in row
    assert "聚合 data 看起来对" in row

    for expected in [
        "assert body == {",
        '"date": str(created_at.date())',
        '"total_runs": 2',
        '"passed_runs": 1',
        '"failed_runs": 1',
        '"pass_rate": 0.5',
        '"pagination": {"offset": 0, "limit": 365, "total": 1}',
    ]:
        assert expected in trends_block
    for rejected in [
        'assert body["pagination"]["total"] == 1',
        'assert body["pagination"]["offset"] == 0',
        'assert body["pagination"]["limit"] == 365',
        'assert body["data"] == [',
    ]:
        assert rejected not in trends_block

    for expected in [
        "assert body == {",
        '"suite": "analytics"',
        '"name": "test_flaky_checkout"',
        '"total_runs": 2',
        '"passed_count": 1',
        '"failed_count": 1',
        '"flaky_rate": 0.5',
        '"pagination": {"offset": 0, "limit": 50, "total": 1}',
    ]:
        assert expected in flaky_block
    for rejected in [
        'assert body["pagination"]["total"] == 1',
        'assert body["data"] == [',
    ]:
        assert rejected not in flaky_block


def test_quality_ops_capture_core_api_list_exact_response_contracts():
    row = _quality_ops_row_containing("core API list integration")
    api_endpoints = _read(API_ENDPOINTS)
    projects_block = _marked_block(
        api_endpoints,
        "async def test_list_projects(self,",
        "async def test_list_projects_search_orders_results_by_name",
    )
    runs_block = _marked_block(
        api_endpoints,
        "async def test_list_runs(self,",
        "async def test_list_runs_filters_pipeline_git_ref_and_created_range",
    )
    pipelines_block = _marked_block(
        api_endpoints,
        "async def test_list_pipelines(self,",
        "# --------------------------------------------------------------------------- #\n# Notification Rules",
    )
    notification_rules_block = _marked_block(
        api_endpoints,
        "async def test_list_notification_rules(self,",
        "async def test_list_notification_rules_normalizes_legacy_channel_shape",
    )

    assert "core API list integration" in row
    assert "projects/runs/pipelines/notification-rules 完整 response body" in (
        row
    )
    assert "删除完整 body 等值后的冗余 `set(body[\"data\"][0])` 字段集合守门" in (
        row
    )
    assert "避免 core list integration 只证明“条数和几个字段看起来对”" in (
        row
    )
    assert "def _json_datetime(value: datetime) -> str:" in api_endpoints
    assert '"git_auth_method": "none"' in api_endpoints
    assert '"git_sha": None' in api_endpoints
    assert '"started_at": None' in api_endpoints
    assert '"selector": {' in api_endpoints
    assert '"dedup_window_seconds": None' in api_endpoints
    assert '"data": [created]' in api_endpoints
    for block in [
        projects_block,
        runs_block,
        pipelines_block,
        notification_rules_block,
    ]:
        assert 'assert set(body["data"][0]) == {' not in block
    assert 'assert len(body["data"]) == 2' not in api_endpoints
    assert 'assert len(body["data"]) == 1' not in api_endpoints
    assert 'seeded = items_by_id[str(seed_run["project"].id)]' not in api_endpoints
    assert 'listed = items_by_id[str(seed_run["run"].id)]' not in api_endpoints
    assert 'seeded = items_by_id[str(seed_run["pipeline"].id)]' not in api_endpoints
    assert 'assert created["id"] in items_by_id' not in api_endpoints
    assert 'assert "id" in item' not in api_endpoints
    assert 'assert "name" in item' not in api_endpoints


def test_quality_ops_capture_project_delete_exact_audit_redacted_url_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_api_endpoints.py::TestProjectsCRUD::"
            "test_delete_project")

    assert "` 1 passed" in row
    assert "release quality docs contract full 229 passed" in row
    assert "targeted ruff passed" in row
    assert "204 空响应" in row
    assert "软删除行存在" in row
    assert "`project.delete` AuditEvent 的 tenant/user/resource 完整匹配" in row
    assert "before_state 精确等于删除前 ProjectResponse" in row
    assert "`https://***@example.com/r.git`" in row
    assert "after_state 为 None" in row
    assert "不含 git-user、git-pass 或原始 URL" in row
    assert "此前只抽查 audit before_state 的 id/slug" in row
    assert "含 userinfo 的 git_url 进入审计" in row
    assert "项目被软删且审计里有 id/slug" in row

    block = _marked_block(
        api_endpoints,
        "async def test_delete_project(",
        "# --------------------------------------------------------------------------- #\n# Runs",
    )

    assert '"git_url": "https://git-user:git-pass@example.com/r.git"' in block
    assert "created = create_resp.json()" in block
    assert 'assert created["git_url"] == payload["git_url"]' in block
    assert "pid = created[\"id\"]" in block
    assert 'assert del_resp.content == b""' in block
    assert "assert deleted_project.deleted_at is not None" in block
    assert 'AuditEvent.action == "project.delete"' in block
    assert 'assert audit.tenant_id == seed_run["tenant"].id' in block
    assert 'assert audit.user_id == seed_run["user"].id' in block
    assert 'assert audit.resource_type == "project"' in block
    assert "assert audit.resource_id == deleted_project.id" in block
    assert (
        'expected_before_state = {**created, "git_url": '
        '"https://***@example.com/r.git"}'
    ) in block
    assert "assert audit.before_state == expected_before_state" in block
    assert "assert audit.after_state is None" in block
    assert "serialized_audit = repr([audit.before_state, audit.after_state])" in block
    for forbidden in ['"git-user"', '"git-pass"', 'payload["git_url"]']:
        assert forbidden in block
    assert 'assert audit.before_state["id"] == pid' not in block
    assert 'assert audit.before_state["slug"] == slug' not in block


def test_quality_ops_capture_notification_rule_delete_exact_audit_no_channel_leak_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_api_endpoints.py::TestNotificationRules::"
            "test_delete_notification_rule")

    assert "` 1 passed" in row
    assert "release quality docs contract full 228 passed" in row
    assert "targeted ruff passed" in row
    assert "204 空响应" in row
    assert "软删除行存在" in row
    assert (
        "`notification_rule.delete` AuditEvent 的 tenant/user/resource 完整匹配"
        in row
    )
    assert "before_state 精确等于完整删除前审计状态" in row
    assert "id/project_id/name/enabled/conditions/channels/template/created_at" in row
    assert "after_state 为 None" in row
    assert "不含 webhook URL" in row
    assert "`webhook_url`" in row
    assert "`config`" in row
    assert '`"url"`' in row
    assert "此前只抽查 audit before_state 的 id/channel redacted" in row
    assert "channel config 以别的字段名泄露" in row
    assert "规则被软删且审计里 URL 字符串没出现" in row

    block = _marked_block(
        api_endpoints,
        "async def test_delete_notification_rule(",
        "# --------------------------------------------------------------------------- #\n# Analytics",
    )

    assert "created = create_resp.json()" in block
    assert 'rule_id = created["id"]' in block
    assert 'assert del_resp.content == b""' in block
    assert "assert deleted_rule.deleted_at is not None" in block
    assert 'AuditEvent.action == "notification_rule.delete"' in block
    assert 'assert audit.tenant_id == seed_run["tenant"].id' in block
    assert 'assert audit.user_id == seed_run["user"].id' in block
    assert 'assert audit.resource_type == "notification_rule"' in block
    assert "assert audit.resource_id == deleted_rule.id" in block
    assert "assert audit.before_state == {" in block
    for expected in [
        '"id": rule_id',
        '"project_id": project_id',
        '"name": "to-delete"',
        '"enabled": True',
        '"conditions": []',
        '"channels": {',
        '"redacted": True',
        '"count": 1',
        '"types": ["webhook"]',
        '"template": {',
        '"present": False',
        '"length": 0',
        '"created_at": created["created_at"]',
    ]:
        assert expected in block
    assert "assert audit.after_state is None" in block
    assert "serialized_audit = repr([audit.before_state, audit.after_state])" in block
    for forbidden in [
        '"https://h.example.com"',
        '"webhook_url"',
        '"config"',
        "'\"url\"'",
    ]:
        assert forbidden in block
    assert 'assert "https://h.example.com" not in str(audit.before_state)' not in block
    assert 'assert audit.before_state["id"] == rule_id' not in block
    assert 'assert audit.before_state["channels"]' not in block


def test_quality_ops_capture_credential_real_api_exact_response_no_secret_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_credentials_api_persists_encrypted_value_rotates_and_soft_deletes")

    assert "` 1 passed" in row
    assert "release quality docs contract full 226 passed" in row
    assert "targeted ruff passed" in row
    assert "响应完整等于 CredentialResponse 元数据" in row
    assert "id/project_id/name/type/created_by/created_at" in row
    assert "递归证明响应与三条 audit payload 都不含 `value`" in row
    assert "`encrypted_value`" in row
    assert "`secret-v1`" in row
    assert "`secret-v2`" in row
    assert "当前 ciphertext repr" in row
    assert "before/after_state 也分别精确等于 None/响应体/响应体/None" in row
    assert "此前只断言 create 响应顶层没有 `\"value\"`" in row
    assert "明文藏到嵌套字段" in row
    assert "凭据集成测试只证明“数据库加密成功且顶层没看到 value”" in row

    helper_block = _marked_block(
        real_api_write_state,
        "def _assert_credential_payload_does_not_leak",
        "class _RecordingArq",
    )

    assert '{"value", "encrypted_value"} & set(node)' in helper_block
    assert "for secret in secrets:" in helper_block
    assert "assert secret not in node" in helper_block

    block = _marked_block(
        real_api_write_state,
        "async def test_credentials_api_persists_encrypted_value_rotates_and_soft_deletes",
        "async def test_project_git_token_binding_reaches_trigger_metadata_without_secret",
    )

    assert "create_body = create_resp.json()" in block
    assert 'credential_id = UUID(create_body["id"])' in block
    assert "assert create_body == {" in block
    assert '"created_by": str(seed_run["user"].id)' in block
    assert '"created_at": _json_datetime(credential.created_at)' in block
    assert '_assert_credential_payload_does_not_leak(create_body, "secret-v1", "secret-v2")' in (
        block
    )
    assert "update_body = update_resp.json()" in block
    assert "assert update_body == {" in block
    assert '_assert_credential_payload_does_not_leak(update_body, "secret-v1", "secret-v2")' in (
        block
    )
    assert "audit_payloads = [" in block
    assert "repr(credential.encrypted_value)" in block
    assert "assert create_audit.before_state is None" in block
    assert "assert create_audit.after_state == create_body" in block
    assert "assert rotate_audit.before_state is None" in block
    assert "assert rotate_audit.after_state == update_body" in block
    assert "assert delete_audit.before_state == update_body" in block
    assert "assert delete_audit.after_state is None" in block
    assert 'assert "value" not in create_resp.json()' not in block
    assert "serialized_audit = repr(" not in block


def test_quality_ops_capture_notification_rule_soft_delete_exact_empty_list_contract():
    row = _quality_ops_row_containing(
        "notification rule 真实 API/DB 用例现在断言 soft-delete 后"
    )
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    assert "notification rule 真实 API/DB 用例现在断言 soft-delete 后" in (
        row
    )
    assert "且 `visible == []`" in row
    assert "assert total == 0" in real_api_write_state
    assert "assert visible == []" in real_api_write_state
    assert "assert rule.id not in {item.id for item in visible}" not in (
        real_api_write_state
    )


def test_quality_ops_capture_project_create_exact_response_contract():
    row = _quality_ops_row_containing("project create 真实 API 用例现在验证响应 UUID")
    api_endpoints = _read(API_ENDPOINTS)

    assert "project create 真实 API 用例现在验证响应 UUID" in row
    assert "精确固定 tenant_id、created_by、默认 clone/config 字段与状态" in (
        row
    )
    assert 'created_id = uuid.UUID(body["id"])' in api_endpoints
    assert 'datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))' in (
        api_endpoints
    )
    assert '"tenant_id": str(seed_run["tenant"].id)' in api_endpoints
    assert '"created_by": str(seed_run["user"].id)' in api_endpoints
    assert '"settings": {}' in api_endpoints
    assert '"silent_windows": []' in api_endpoints
    assert 'assert "id" in body' not in api_endpoints
    assert 'assert "created_at" in body' not in api_endpoints


def test_quality_ops_capture_notification_invalid_condition_integration_exact_detail_contract():
    row = _quality_ops_row_containing(
        "Notification invalid condition integration exact detail 契约"
    )
    api_endpoints = _read(API_ENDPOINTS)

    assert "Notification invalid condition integration exact detail 契约" in row
    assert (
        "`RUN_INTEGRATION_TESTS=1 tests/integration/test_api_endpoints.py::TestNotificationRules::test_create_notification_rule_rejects_invalid_condition` 2 passed"
        in row
    )
    assert "真实 notification rule invalid condition 集成用例" in row
    assert "422 detail 的 `{type, loc, msg, input}` 单条投影" in row
    assert "对应 rule name 没有写入 PostgreSQL" in row
    assert "真实 FastAPI+DB 集成仍只用 `resp.text` 包含" in row
    assert "错误响应里有相似文字" in row

    assert (
        "def _validation_error_projection(errors: list[dict]) -> list[dict]:"
        in api_endpoints
    )

    test_block = _marked_block(
        api_endpoints,
        "async def test_create_notification_rule_rejects_invalid_condition",
        "async def test_list_notification_rules",
    )

    assert 'assert resp.status_code == 422, resp.text' in test_block
    assert (
        'assert _validation_error_projection(resp.json()["detail"]) == ['
        in test_block
    )
    assert '"type": "value_error"' in test_block
    assert '"loc": ["body", "conditions"]' in test_block
    assert (
        '"Value error, conditions[0].field must be one of: "'
        in test_block
    )
    assert (
        '"consecutive_failures, failed, pass_rate, status"'
        in test_block
    )
    assert '"input": [condition]' in test_block
    assert "result.scalar_one_or_none() is None" in test_block
    assert '"conditions[0].field must be one of" in resp.text' not in test_block


def test_quality_ops_capture_legacy_notification_channel_exact_response_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 uv run pytest "
        "tests/integration/test_api_endpoints.py::TestNotificationRules::"
        "test_list_notification_rules_normalizes_legacy_channel_shape -q` 1 passed"
    )
    test_block = _block_between(api_endpoints, "async def test_list_notification_rules_normalizes_legacy_channel_shape", "async def test_list_notification_rules_marks_historical_invalid_conditions")

    assert "targeted docs contract passed" in row
    assert "targeted ruff passed" in row
    assert "完整分页 body" in row
    assert "`webhook_url` key" in row
    assert "legacy notification channel exact response 契约" in row
    assert "channels 大致归一化了" in row

    for expected in [
        "await integration_db_session.refresh(legacy_rule)",
        "expected_item = {",
        '"enabled": True',
        '"conditions": []',
        '"created_at": _json_datetime(legacy_rule.created_at)',
        "assert body == {",
        '"data": [expected_item],',
        '"per_page": 20,',
        '"total": 1,',
        'assert "webhook_url" not in body["data"][0]["channels"][0]',
    ]:
        assert expected in test_block
    assert "items_by_id = {item[\"id\"]: item for item in body[\"data\"]}" not in (
        test_block
    )


def test_quality_ops_capture_notification_invalid_condition_integration_exact_response_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
        "tests/integration/test_api_endpoints.py::TestNotificationRules::"
        "test_list_notification_rules_marks_historical_invalid_conditions -q` 1 passed"
    )
    test_block = _block_between(api_endpoints, "async def test_list_notification_rules_marks_historical_invalid_conditions", "async def test_update_notification_rule")

    assert "release quality docs contract full 315 passed" in row
    assert "targeted ruff passed" in row
    assert "完整分页响应" in row
    assert "完整 reason、raw_field、raw_operator" in row
    assert "canonical webhook `config.url`" in row
    assert "notification invalid condition integration exact response 契约" in row
    assert "某条规则里有 invalid 标记" in row

    for expected in [
        "await integration_db_session.refresh(dirty_rule)",
        "assert resp.json() == {",
        '"page": 1',
        '"per_page": 20',
        '"total": 1',
        '"enabled": True',
        '"template": None',
        '"created_at": _json_datetime(dirty_rule.created_at)',
        '"conditions[0].field must be one of: "',
        '"consecutive_failures, failed, pass_rate, status"',
        '"raw_field": "statuz"',
        '"raw_operator": "eq"',
        '"conditions[1].all[0].operator must be one of: "',
        '"eq, gt, gte, lt, lte, ne"',
        '"raw_field": "failed"',
        '"raw_operator": "around"',
        '"config": {"url": "https://hooks.example.com/historical-invalid"}',
    ]:
        assert expected in test_block
    assert "items_by_id =" not in test_block
    assert 'conditions[0]["invalid"]' not in test_block
    assert '"conditions[0].field must be one of" in conditions[0]["reason"]' not in (
        test_block
    )
    assert 'conditions[1]["all"][0]["raw_operator"]' not in test_block


def test_quality_ops_capture_core_list_exact_pagination_contracts():
    quality_ops = _quality_ops_rows_containing(
        "Core list exact pagination 集成契约",
        "core API list integration",
    )
    api_endpoints = _read(API_ENDPOINTS)

    assert "Core list exact pagination 集成契约" in quality_ops
    assert "projects/pipelines/notification-rules 列表 smoke" in quality_ops
    assert "core API list integration" in quality_ops
    assert "完整 response body、排序和时间字段" in quality_ops
    assert "重复字段集合断言" in quality_ops
    assert "tenant/project scope" in quality_ops
    assert '"git_auth_method": "none"' in api_endpoints
    assert '"updated_at": _json_datetime(seed_run["project"].updated_at)' in (
        api_endpoints
    )
    assert '"selector": {' in api_endpoints
    assert '"trigger_config": {' in api_endpoints
    assert '"data": [created]' in api_endpoints
    assert 'assert len(body["data"]) == 2' not in api_endpoints
    assert 'assert len(body["data"]) == 1' not in api_endpoints
    assert "assert \"data\" in body" not in api_endpoints
    assert "assert body[\"total\"] >= 1" not in api_endpoints
    assert "assert body[\"total\"] >= 2" not in api_endpoints


def test_quality_ops_capture_pipeline_integration_full_response_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 uv run pytest "
        "tests/integration/test_api_endpoints.py::TestPipelines::test_create_pipeline "
        "tests/integration/test_api_endpoints.py::TestPipelines::"
        "test_update_pipeline_accepts_current_contract -q` 2 passed"
    )
    create_block = _block_between(api_endpoints, "async def test_create_pipeline", "async def test_update_pipeline_accepts_current_contract")
    update_block = _block_between(api_endpoints, "async def test_update_pipeline_accepts_current_contract", "async def test_list_pipelines")

    assert "targeted docs contract passed" in row
    assert "targeted ruff passed" in row
    assert "完整 PipelineResponse body" in row
    assert "selector/trigger 默认壳" in row
    assert "Pipeline integration full response 契约" in row
    assert "几个嵌套字段看起来对" in row

    for block in [create_block, update_block]:
        assert "expected_body = {" in block
        assert '"project_id": project_id' in block
        assert '"stages": [' in block
        assert '{**stage, "continue_on_error": False}' in block
        assert 'for stage in payload["stages"]' in block
        assert '"selector": {' in block
        assert '"exclude_paths": []' in block
        assert '"tags": []' in block
        assert '"expression": None' in block
        assert '"regex": None' in block
        assert '"trigger_config": {' in block
        assert '"dedup_window_seconds": None' in block
        assert '"collectors": payload["collectors"]' in block
        assert '"timeout_seconds": payload["timeout_seconds"]' in block
        assert '"retry_policy": payload["retry_policy"]' in block
        assert '"updated_at": body["updated_at"]' in block
        assert "assert body == expected_body" in block
    assert 'body["stages"][0]["config"]["command"].startswith' not in (
        create_block + update_block
    )
    assert 'assert body["stages"] == [' not in (create_block + update_block)
    assert 'body["stages"][0]["plugin"]' not in create_block
    assert 'body["stages"][0]["config"]["url"]' not in update_block
    assert 'body["stages"][1]["phase"]' not in create_block


def test_quality_ops_capture_project_get_update_integration_exact_response_audit_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
        "tests/integration/test_api_endpoints.py::TestProjectsCRUD::test_get_project "
        "tests/integration/test_api_endpoints.py::TestProjectsCRUD::"
        "test_update_project -q` 2 passed"
    )
    get_block = _block_between(api_endpoints, "async def test_get_project", "async def test_update_project")
    update_block = _block_between(api_endpoints, "async def test_update_project", "async def test_delete_project")

    assert "release quality docs contract full 306 passed" in row
    assert "targeted ruff passed" in row
    assert "`_expected_seed_project_response` 固定完整 ProjectResponse" in row
    assert "settings/silent_windows/status/timestamps 全部等值" in row
    assert "DB name 已更新" in row
    assert "`project.update` AuditEvent" in row
    assert "before_state/after_state 完整匹配响应契约" in row
    assert "Project get/update integration exact response/audit 契约" in row
    assert "只证明“能按 id 返回或改掉一个名字”" in row

    for expected in [
        "def _expected_seed_project_response(",
        '"git_auth_method": "none"',
        '"default_branch": "main"',
        '"settings": {}',
        '"silent_windows": []',
        '"status": "active"',
        '"created_at": _json_datetime(project.created_at)',
        '"updated_at": updated_at or _json_datetime(project.updated_at)',
    ]:
        assert expected in api_endpoints
    assert "assert body == _expected_seed_project_response(seed_run)" in get_block
    assert "before_body = _expected_seed_project_response(seed_run)" in update_block
    assert "assert body == expected_body" in update_block
    assert 'await integration_db_session.refresh(seed_run["project"])' in update_block
    assert 'AuditEvent.action == "project.update"' in update_block
    assert "assert audit.before_state == before_body" in update_block
    assert "assert audit.after_state == expected_body" in update_block
    combined = get_block + update_block
    assert 'assert body["id"] == project_id' not in combined
    assert 'assert body["name"] == "integration-project"' not in get_block
    assert 'assert body["name"] == "renamed-project"' not in update_block


def test_quality_ops_capture_project_search_integration_exact_pagination_sort_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
        "tests/integration/test_api_endpoints.py::TestProjectsCRUD::"
        "test_list_projects_search_orders_results_by_name -q` 1 passed"
    )
    block = _block_between(api_endpoints, "async def test_list_projects_search_orders_results_by_name", "async def test_get_project")

    assert "release quality docs contract full 308 passed" in row
    assert "targeted ruff passed" in row
    assert "保存三次 create 的完整 ProjectResponse" in row
    assert "`{\"data\": sorted(created_projects, key=name), \"page\": 1, \"per_page\": 10, \"total\": 3}`" in row
    assert "Project search exact pagination/sort 契约" in row
    assert "只证明“几个名字按字母排了”" in row

    assert "created_projects = []" in block
    assert "created_projects.append(create_resp.json())" in block
    assert 'assert resp.json() == {' in block
    assert '"data": sorted(created_projects, key=lambda item: item["name"])' in block
    assert '"page": 1' in block
    assert '"per_page": 10' in block
    assert '"total": 3' in block
    assert "returned_names =" not in block
    assert "assert returned_names == sorted(names)" not in block


def test_quality_ops_capture_project_cross_tenant_direct_no_leak_list_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 uv run pytest "
        "tests/integration/test_api_endpoints.py::TestCrossTenantIsolation::"
        "test_cross_tenant_project_access -q` 1 passed"
    )
    block = _after(
        api_endpoints,
        "async def test_cross_tenant_project_access",
    )

    assert "targeted docs contract passed" in row
    assert "targeted ruff passed" in row
    assert "同一 `NOT_FOUND` envelope" in row
    assert "显式泄露列表" in row
    assert "cross-tenant 404 direct no-leak list 契约" in row
    assert "只证明“404 body 大致一致”" in row

    for expected in [
        "leaked_cross_tenant_values = [",
        "if value in resp.text or value in random_resp.text",
        "leaked_random_values = [",
        "assert leaked_cross_tenant_values == []",
        "assert leaked_random_values == []",
    ]:
        assert expected in block
    assert "assert all(value not in resp.text for value in leaked_cross_tenant_ids)" not in (
        block
    )


def test_quality_ops_capture_crud_delete_followup_404_exact_envelope_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_api_endpoints.py::TestProjectsCRUD::test_delete_project tests/integration/test_api_endpoints.py::TestNotificationRules::test_delete_notification_rule -q` 2 passed")
    assert "release quality docs contract full 275 passed" in row
    assert "targeted ruff passed" in row
    assert "CRUD delete follow-up 404 exact envelope/no-leak 契约" in row
    assert "project_id、rule_id、原始 git URL、git userinfo 或 webhook URL" in row
    assert "只断言 `get_resp.status_code == 404`" in row

    assert (
        'def _not_found_body(message: str) -> dict:\n'
        '    return {"error": {"code": "NOT_FOUND", "message": message, "details": []}}'
    ) in api_endpoints

    project_block = _block_between(api_endpoints, "async def test_delete_project", "\n\n    async def")
    rule_block = _block_between(api_endpoints, "async def test_delete_notification_rule", "\n\n        audit =")

    for expected in [
        "assert get_resp.status_code == 404, get_resp.text",
        'assert get_resp.json() == _not_found_body("Project not found")',
        'for forbidden in [pid, payload["git_url"], "git-user", "git-pass"]:',
        "assert forbidden not in get_resp.text",
    ]:
        assert expected in project_block

    for expected in [
        "assert get_resp.status_code == 404, get_resp.text",
        'assert get_resp.json() == _not_found_body("Notification rule not found")',
        'for forbidden in [project_id, rule_id, "https://h.example.com"]:',
        "assert forbidden not in get_resp.text",
    ]:
        assert expected in rule_block


def test_quality_ops_capture_integration_schema_bootstrap_fail_message_contract():
    quality_ops = _quality_ops_row_containing(
        "Integration schema bootstrap fail message 精确契约"
    )
    schema_bootstrap_contract = _read(INTEGRATION_SCHEMA_BOOTSTRAP_CONTRACT)

    assert "Integration schema bootstrap fail message 精确契约" in quality_ops
    assert "pytest fail message 完整等于" in quality_ops
    assert "不会调用 metadata fallback engine" in quality_ops
    assert '`pytest.raises(..., match="alembic upgrade head failed")`' in (
        quality_ops
    )
    assert "exit code/stderr 被丢弃" in quality_ops
    assert "迁移失败时抛了相似错误" in quality_ops
    assert "assert str(exc_info.value) == (" in schema_bootstrap_contract
    assert "alembic upgrade head failed for integration schema bootstrap" in (
        schema_bootstrap_contract
    )
    assert "(exit=1):\\nbroken migration" in schema_bootstrap_contract
    assert "create_engine.assert_not_called()" in schema_bootstrap_contract
    assert 'match="alembic upgrade head failed"' not in schema_bootstrap_contract
