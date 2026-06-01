from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _block_between,
    _marked_block,
    _marked_block_or_tail,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_credentials.py"
ENVIRONMENT_ENV_VARS_ENCRYPTION = (
    ROOT / "tests" / "integration" / "test_environment_env_vars_encryption.py"
)
ENVIRONMENTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_environments.py"
NOTIFICATIONS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_notifications.py"
SCHEDULES_TEST = ROOT / "tests" / "unit" / "test_api" / "test_schedules.py"
SILENT_WINDOWS_INTEGRATION = ROOT / "tests" / "integration" / "test_silent_windows.py"


def test_quality_ops_capture_credentials_list_exact_response_contract():
    ops_row = _quality_ops_row_containing("Credential list 精确响应契约")
    credentials_test = _read(CREDENTIALS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Credential list exact pagination body 契约）"
    )

    assert "Credential list exact pagination body 契约" in row
    assert (
        "`tests/unit/test_api/test_credentials.py::test_list_credentials_returns_response_without_plaintext` 1 passed"
        in row
    )
    assert "release quality docs contract full 333 passed" in row
    assert "完整分页 body" in row
    assert "`page=2`、`per_page=1`、`total=2`" in row
    assert "两个完整 CredentialResponse item 必须整体等值" in row
    assert "字段集合精确排除 value/encrypted_value" in row
    assert 'body["page"]` / `body["per_page"]` / `body["total"]' in row
    assert "`frozenset(entry)`" in row
    assert "credential list exact pagination body 契约" in row
    assert "data 和几个分页数字分别看起来对且没看到明文" in row

    assert "Credential list 精确响应契约" in ops_row
    assert "固定完整 data 响应，包含 id/project_id/name/type/created_by/created_at" in ops_row
    assert "字段集合精确排除 value/encrypted_value" in ops_row
    assert 'assert body == {' in credentials_test
    assert '"created_by": str(c1.created_by)' in credentials_test
    assert '"created_at": c2.created_at.isoformat().replace("+00:00", "Z")' in (
        credentials_test
    )
    assert '"page": 2' in credentials_test
    assert '"per_page": 1' in credentials_test
    assert '"total": 2' in credentials_test
    for rejected in [
        'assert body["page"] == 2',
        'assert body["per_page"] == 1',
        'assert body["total"] == 2',
        'assert body["data"] == [',
        "frozenset(entry)",
    ]:
        assert rejected not in credentials_test
    assert 'assert len(body["data"]) == 2' not in credentials_test
    assert 'assert "value" not in entry' not in credentials_test
    assert 'assert "encrypted_value" not in entry' not in credentials_test


def test_quality_ops_capture_credential_create_audit_complete_payload_contract():
    row = _quality_ops_row_containing("Credential create audit complete payload 契约")
    credentials_test = _read(CREDENTIALS_TEST)

    assert "Credential create audit complete payload 契约" in row
    assert (
        "`tests/unit/test_api/test_credentials.py::test_create_credential_audit_does_not_leak_plaintext` 1 passed"
        in row
    )
    assert "credentials full 14 passed" in row
    assert "固定完整 `repos.audit.create` kwargs" in row
    assert "tenant/user/action/resource/before_state" in row
    assert "id/project_id/name/type/created_by/created_at" in row
    assert "ciphertext bytes 不进入 audit" in row
    assert "只抽查 after_state 的 name/type" in row
    assert "tenant/user/resource_id 漂移" in row
    assert "created_by/created_at 漏掉" in row
    assert "没看到明文且两个字段对" in row

    audit_block = _marked_block(
        credentials_test,
        "async def test_create_credential_audit_does_not_leak_plaintext",
        "async def test_create_credential_duplicate_name_returns_409",
    )

    assert "created.created_by = mock_user.user_id" in audit_block
    assert "created.created_at = datetime(2026, 5, 31, 10, 11, 12, tzinfo=timezone.utc)" in (
        audit_block
    )
    assert "assert audit_kwargs == {" in audit_block
    for expected in [
        '"tenant_id": tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "credential.create"',
        '"resource_type": "credential"',
        '"resource_id": created.id',
        '"before_state": None',
        '"id": str(created.id)',
        '"project_id": str(project.id)',
        '"name": "k"',
        '"type": "password"',
        '"created_by": str(mock_user.user_id)',
        '"created_at": "2026-05-31T10:11:12Z"',
    ]:
        assert expected in audit_block
    assert "assert secret_value not in serialised" in audit_block
    assert 'assert "encrypted_value" not in serialised' in audit_block
    assert "assert repr(mock_crypto.encrypt.return_value) not in serialised" in (
        audit_block
    )
    assert 'after_state.get("name")' not in audit_block
    assert 'after_state.get("type")' not in audit_block


def test_quality_ops_capture_environment_list_exact_response_contract():
    ops_row = _quality_ops_row_containing("Environment list 精确响应契约")
    environments_test = _read(ENVIRONMENTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Environment list exact pagination body 契约）"
    )

    assert "Environment list exact pagination body 契约" in row
    assert (
        "`tests/unit/test_api/test_environments.py::test_list_environments_uses_pagination_and_decrypts_items` 1 passed"
        in row
    )
    assert "release quality docs contract full 332 passed" in row
    assert "完整分页 body" in row
    assert "`page=3`、`per_page=5`、`total=11`" in row
    assert "完整 EnvironmentResponse item 必须整体等值" in row
    assert "env_vars 解密后返回且 audit 无副作用" in row
    assert 'body["page"]` / `body["per_page"]` / `body["total"]' in row
    assert "environment list exact pagination body 契约" in row
    assert "data 和几个分页数字分别看起来对" in row

    assert "Environment list 精确响应契约" in ops_row
    assert 'assert body == {' in environments_test
    assert '"setup_script": None' in environments_test
    assert '"created_at": env.created_at.isoformat().replace("+00:00", "Z")' in (
        environments_test
    )
    assert '"page": 3' in environments_test
    assert '"per_page": 5' in environments_test
    assert '"total": 11' in environments_test
    for rejected in [
        'assert body["page"] == 3',
        'assert body["per_page"] == 5',
        'assert body["total"] == 11',
        'assert body["data"] == [',
        'assert set(body["data"][0]) == {',
    ]:
        assert rejected not in environments_test
    assert 'assert len(body["data"]) == 1' not in environments_test
    assert 'item = body["data"][0]' not in environments_test


def test_quality_ops_capture_environment_disk_limit_update_exact_contract():
    row = _quality_ops_row_containing("Environment disk limit update/audit 精确契约")
    environments_test = _read(ENVIRONMENTS_TEST)

    assert "Environment disk limit update/audit 精确契约" in row
    assert (
        "`tests/unit/test_api/test_environments.py::test_update_environment_updates_and_clears_disk_limit` 1 passed"
        in row
    )
    assert "两次 tenant-scoped project lookup" in row
    assert "两次 `environment.update(env, resource_limits=...)` 完整参数" in (
        row
    )
    assert "仍保留 `max_artifact_size_mb/max_artifacts_count`" in row
    assert "1024→2048、2048→None 的 before/after disk 变化" in row
    assert "`environment.update.await_count == 2`" in row
    assert "update 传错 env、漏 tenant scope" in row
    assert "环境资源限制测试只证明“更新接口调用了两次”" in row
    assert "mock_user," in environments_test
    assert "mock_repos.project.get_for_tenant.await_args_list" in environments_test
    assert "mock_repos.environment.get_by_id.await_args_list" in environments_test
    assert "mock_repos.environment.update.await_args_list" in environments_test
    assert '"resource_limits": {' in environments_test
    assert '"disk_mb": 2048' in environments_test
    assert '"max_artifact_size_mb": 100' in environments_test
    assert '"max_artifacts_count": 50' in environments_test
    assert 'call["before_state"]["disk_mb"]' in environments_test
    assert 'call["after_state"]["disk_mb"]' in environments_test
    assert "1024" in environments_test
    assert "2048" in environments_test
    assert "None" in environments_test
    assert "assert mock_repos.environment.update.await_count == 2" not in (
        environments_test
    )


def test_quality_ops_capture_environment_disk_limit_update_exact_response_body_contract():
    environments_test = _read(ENVIRONMENTS_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Environment disk limit update exact response body 契约）"
    )
    test_block = _block_between(environments_test, "async def test_update_environment_updates_and_clears_disk_limit", "async def test_update_environment_reencrypts_env_vars_and_redacts_audit")

    assert "`tests/unit/test_api/test_environments.py::test_update_environment_updates_and_clears_disk_limit` 1 passed" in row
    assert "release quality docs contract full 300 passed" in row
    assert "两次完整 EnvironmentResponse" in row
    assert "id/project/name/base_image/setup/memory/cpu/disk/artifact/network/env_vars/cache/created_at" in row
    assert '`resp.json()["disk_mb"]`' in row
    assert "Environment disk limit update exact response body 契约" in row
    assert "只证明“disk_mb 局部字段对了”" in row

    assert "env.created_at = datetime(2026, 5, 31, 21, 22, 23" in test_block
    assert test_block.count("assert update_resp.json() == {") == 1
    assert test_block.count("assert clear_resp.json() == {") == 1
    assert '"disk_mb": 2048' in test_block
    assert '"disk_mb": None' in test_block
    for expected in [
        '"id": str(env.id)',
        '"project_id": str(project.id)',
        '"name": "default"',
        '"base_image": "python:3.12.1"',
        '"setup_script": None',
        '"memory_mb": 512',
        '"cpu_cores": 1.0',
        '"max_artifact_size_mb": 100',
        '"max_artifacts_count": 50',
        '"network_policy": "deny"',
        '"env_vars": {}',
        '"cache_key": None',
        '"created_at": "2026-05-31T21:22:23Z"',
    ]:
        assert expected in test_block
    assert 'update_resp.json()["disk_mb"]' not in test_block
    assert 'clear_resp.json()["disk_mb"]' not in test_block


def test_quality_ops_capture_environment_create_disk_defaults_exact_contract():
    environments_test = _read(ENVIRONMENTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Environment create disk defaults exact 契约）"
    )

    assert "Environment create disk defaults exact 契约" in row
    assert (
        "`tests/unit/test_api/test_environments.py::test_create_environment_stores_disk_limit` 1 passed"
        in row
    )
    assert "environments full 27 passed" in row
    assert "release quality docs contract full 175 passed" in row
    assert "固定完整 EnvironmentResponse" in row
    assert "tenant-scoped project lookup" in row
    assert "`environment.create` 完整默认 kwargs" in row
    assert "空 env_vars 加密 envelope 可解密为空" in row
    assert "完整 `environment.create` audit kwargs" in row
    assert "此前只断言响应 `disk_mb == 2048`" in row
    assert "环境磁盘配额测试只证明“disk_mb 字段写进去了”" in row

    block = _marked_block(
        environments_test,
        "async def test_create_environment_stores_disk_limit",
        "async def test_update_environment_updates_and_clears_disk_limit",
    )
    for expected in [
        "crypto,",
        "env.created_at = datetime(2026, 5, 31, 19, 20, 21, tzinfo=timezone.utc)",
        "assert body == {",
        '"memory_mb": 512',
        '"cpu_cores": 1.0',
        '"disk_mb": 2048',
        '"max_artifact_size_mb": 100',
        '"max_artifacts_count": 50',
        '"network_policy": "deny"',
        '"env_vars": {}',
        '"created_at": "2026-05-31T19:20:21Z"',
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(",
        'stored_env_vars = create_kwargs["env_vars"]',
        "decrypt_env_vars(stored_env_vars, environment_id=env_id, crypto=crypto) == {}",
        "assert create_kwargs == {",
        '"env_vars": stored_env_vars',
        "assert mock_repos.audit.create.await_args.kwargs == {",
        '"action": "environment.create"',
        '"before_state": None',
        '"env_vars": {"redacted": True, "count": 0}',
    ]:
        assert expected in block
    assert 'resp.json()["disk_mb"]' not in block
    assert 'await_args.kwargs["resource_limits"]' not in block


def test_quality_ops_capture_environment_env_vars_update_exact_response_audit_contract():
    environments_test = _read(ENVIRONMENTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Environment env_vars update exact response/audit 契约）"
    )

    assert "Environment env_vars update exact response/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_environments.py::test_update_environment_reencrypts_env_vars_and_redacts_audit` 1 passed"
        in row
    )
    assert "environments full 27 passed" in row
    assert "release quality docs contract full 289 passed" in row
    assert "targeted ruff passed" in row
    assert "固定完整 EnvironmentResponse" in row
    assert "tenant-scoped project lookup" in row
    assert "`environment.update(env, env_vars=...)` 且无额外 kwargs" in row
    assert "密文 envelope 不含新旧 key/secret" in row
    assert "`environment.update` audit before/after 完整等值" in row
    assert "该用例虽已证明重加密和 audit 不含明文" in row
    assert "repo update 夹带额外字段" in row
    assert "密文看起来不泄密" in row

    block = _marked_block(
        environments_test,
        "async def test_update_environment_reencrypts_env_vars_and_redacts_audit",
        "async def test_delete_environment_removes_existing_environment_and_audits",
    )
    for expected in [
        "mock_user",
        "env.created_at = datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc)",
        "expected_body = {",
        '"name": "default"',
        '"base_image": "python:3.12.1"',
        '"memory_mb": 512',
        '"cpu_cores": 1.0',
        '"disk_mb": 1024',
        '"max_artifact_size_mb": 100',
        '"max_artifacts_count": 50',
        '"network_policy": "deny"',
        '"env_vars": {"NEW_TOKEN": "new-secret"}',
        '"created_at": "2026-05-31T20:21:22Z"',
        "assert body == expected_body",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(",
        "mock_repos.environment.get_by_id.assert_awaited_once_with(env.id)",
        "mock_repos.environment.update.assert_awaited_once()",
        "assert mock_repos.environment.update.await_args.args == (env,)",
        "update_kwargs = mock_repos.environment.update.await_args.kwargs",
        'stored_env_vars = update_kwargs["env_vars"]',
        'assert update_kwargs == {"env_vars": stored_env_vars}',
        "decrypt_env_vars(stored_env_vars, environment_id=env.id, crypto=crypto) == {",
        "expected_before = {",
        "expected_after = {",
        '"env_vars": {"redacted": True, "count": 1}',
        "assert audit_kwargs == {",
        '"action": "environment.update"',
        '"before_state": expected_before',
        '"after_state": expected_after',
        'assert "OLD_TOKEN" not in serialized_audit',
        'assert "NEW_TOKEN" not in serialized_audit',
    ]:
        assert expected in block
    assert 'assert body["env_vars"] == {"NEW_TOKEN": "new-secret"}' not in block
    assert "assert set(mock_repos.environment.update.await_args.kwargs)" not in block
    assert 'assert audit_kwargs["tenant_id"] == mock_user.tenant_id' not in block
    assert 'assert audit_kwargs["after_state"]["env_vars"]' not in block


def test_quality_ops_capture_notification_rule_list_exact_response_contract():
    notifications_test = _read(NOTIFICATIONS_TEST)
    row = _quality_ops_row("| 2026-05-31 | N/A（Notification rule list exact pagination body 契约）")

    assert (
        "`tests/unit/test_api/test_notifications.py::"
        "test_list_rules_uses_project_access_pagination_and_returns_rules` 1 passed"
        in row
    )
    assert "release quality docs contract full 330 passed" in row
    assert "targeted ruff passed" in row
    assert "完整分页 body" in row
    assert "完整 NotificationRuleResponse item 必须整体等值" in row
    assert "`body[\"page\"]` / `body[\"per_page\"]` / `body[\"total\"]`" in row
    assert "只证明“data 和几个分页数字分别看起来对”" in row
    assert "assert body == {" in notifications_test
    assert '"page": 2' in notifications_test
    assert '"per_page": 1' in notifications_test
    assert '"total": 3' in notifications_test
    assert '"enabled": True' in notifications_test
    assert '"template": "Run {{run_id}} token"' in notifications_test
    assert '"created_at": rule.created_at.isoformat().replace("+00:00", "Z")' in (
        notifications_test
    )
    assert 'assert body["page"] == 2' not in notifications_test
    assert 'assert body["per_page"] == 1' not in notifications_test
    assert 'assert body["total"] == 3' not in notifications_test
    assert 'assert body["data"] == [' not in notifications_test
    assert 'assert set(body["data"][0]) == {' not in notifications_test
    assert 'body["data"][0]["channels"] == [' not in notifications_test


def test_quality_ops_capture_notification_rule_crud_exact_response_audit_contract():
    notifications_test = _read(NOTIFICATIONS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification rule CRUD exact response/audit 契约）"
    )

    assert "Notification rule CRUD exact response/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_notifications.py::test_create_rule "
        "tests/unit/test_api/test_notifications.py::test_update_rule "
        "tests/unit/test_api/test_notifications.py::test_delete_rule` 3 passed"
        in row
    )
    assert "notifications API full 21 passed" in row
    assert "release quality docs contract full 177 passed" in row
    assert "`NOTIFICATION_EDIT` 权限调用" in row
    assert "tenant-scoped project lookup" in row
    assert "get/create/update/delete 仓储 exact 参数" in row
    assert "完整 NotificationRuleResponse" in row
    assert "tenant/user/action/resource/before_state/after_state" in row
    assert "不泄露 webhook URL 或模板内容" in row
    assert "此前只抽查响应 name、delete 调用和 audit action/resource/name/channel redacted" in row
    assert "通知规则正向测试只证明“接口成功且几个字段像是对的”" in row

    assert "def _expected_rule_response(rule) -> dict:" in notifications_test
    assert "def _expected_rule_audit_state(rule) -> dict:" in notifications_test

    create_block = _marked_block(
        notifications_test,
        "async def test_create_rule(",
        "async def test_create_rule_rejects_duplicate_channel_types",
    )
    for expected in [
        "mock_user, project_id",
        "rule.created_at = datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc)",
        "assert resp.json() == _expected_rule_response(rule)",
        "Action.NOTIFICATION_EDIT",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(",
        "mock_repos.notification_rule.create.assert_awaited_once_with(",
        '"https://hooks.example.com/secret-token"',
        "assert audit_kwargs == {",
        '"action": "notification_rule.create"',
        '"before_state": None',
        '"after_state": _expected_rule_audit_state(rule)',
        'assert "secret-token" not in repr(audit_kwargs)',
        'assert "Run {{run_id}} token" not in repr(audit_kwargs)',
    ]:
        assert expected in create_block
    assert 'data["name"]' not in create_block
    assert 'audit_kwargs["after_state"]["channels"]' not in create_block

    delete_block = _marked_block(
        notifications_test,
        "async def test_delete_rule(",
        "async def test_update_rule(",
    )
    for expected in [
        "before_state = _expected_rule_audit_state(rule)",
        "Action.NOTIFICATION_EDIT",
        "mock_repos.notification_rule.get_by_id.assert_awaited_once_with(rule.id)",
        "mock_repos.notification_rule.delete.assert_awaited_once_with(rule)",
        "assert audit_kwargs == {",
        '"action": "notification_rule.delete"',
        '"before_state": before_state',
        '"after_state": None',
        'assert "Run {{run_id}} token" not in repr(audit_kwargs)',
    ]:
        assert expected in delete_block
    assert 'audit_kwargs["action"]' not in delete_block
    assert 'audit_kwargs["before_state"]["channels"]' not in delete_block

    update_block = _marked_block(
        notifications_test,
        "async def test_update_rule(",
        "async def test_update_rule_normalizes_conditions_channels_and_redacts_audit",
    )
    for expected in [
        "before_state = _expected_rule_audit_state(rule)",
        "assert resp.json() == _expected_rule_response(rule)",
        "Action.NOTIFICATION_EDIT",
        "mock_repos.notification_rule.get_by_id.assert_awaited_once_with(rule.id)",
        'mock_repos.notification_rule.update.assert_awaited_once_with(',
        'name="Updated Rule"',
        "assert audit_kwargs == {",
        '"action": "notification_rule.update"',
        '"before_state": before_state',
        '"after_state": _expected_rule_audit_state(rule)',
        'assert "secret-token" not in repr(audit_kwargs)',
        'assert "Run {{run_id}} token" not in repr(audit_kwargs)',
    ]:
        assert expected in update_block
    assert 'resp.json()["name"]' not in update_block
    assert 'audit_kwargs["before_state"]["name"]' not in update_block


def test_quality_ops_capture_notification_legacy_invalid_list_exact_contract():
    row = _quality_ops_row_containing(
        "Notification legacy/invalid list exact response 契约"
    )
    notifications_test = _read(NOTIFICATIONS_TEST)

    assert "Notification legacy/invalid list exact response 契约" in row
    assert (
        "`tests/unit/test_api/test_notifications.py::test_list_rules_normalizes_legacy_channel_response_shape tests/unit/test_api/test_notifications.py::test_list_rules_marks_historical_invalid_conditions_without_500` 2 passed"
        in row
    )
    assert "完整分页响应体" in row
    assert "canonical `config.url`" in row
    assert "`consecutive_failed_runs -> consecutive_failures` alias" in row
    assert "invalid condition 的 `reason/raw_field/raw_operator`" in row
    assert "project access、list pagination 与 no audit" in row
    assert 'resp.json()["data"][0]["channels"]' in row
    assert "分页壳漂移" in row
    assert "历史兼容列表测试只证明“嵌套片段被归一化了”" in row

    legacy_block = _marked_block(
        notifications_test,
        "async def test_list_rules_normalizes_legacy_channel_response_shape",
        "async def test_list_rules_marks_historical_invalid_conditions_without_500",
    )
    invalid_block = _marked_block(
        notifications_test,
        "async def test_list_rules_marks_historical_invalid_conditions_without_500",
        "async def test_create_rule",
    )

    for block in (legacy_block, invalid_block):
        assert "assert resp.json() == {" in block
        assert '"data": [' in block
        assert '"page": 1' in block
        assert '"per_page": 20' in block
        assert '"total": 1' in block
        assert "project.get_for_tenant.assert_awaited_once_with" in block
        assert "notification_rule.list_by_project.assert_awaited_once_with" in block
        assert "mock_repos.audit.create.assert_not_awaited()" in block
        assert 'resp.json()["data"][0]["channels"]' not in block
        assert 'resp.json()["data"][0]["conditions"]' not in block

    assert '"config": {"url": "https://hooks.example.com/legacy"}' in legacy_block
    assert '"field": "consecutive_failures"' in legacy_block
    assert '"raw_field": "statuz"' in invalid_block
    assert '"raw_operator": "between"' in invalid_block
    assert "conditions[1].any[0].operator must be one of:" in invalid_block


def test_quality_ops_capture_schedule_list_exact_response_contract():
    ops_row = _quality_ops_row_containing("Schedule list 精确响应契约")
    schedules_test = _read(SCHEDULES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Schedule list exact pagination body 契约）"
    )
    list_block = _marked_block(
        schedules_test,
        "async def test_list_schedules_uses_project_access_and_pagination",
        "\n\n@pytest.mark.asyncio",
    )

    assert "Schedule list exact pagination body 契约" in row
    assert (
        "`tests/unit/test_api/test_schedules.py::test_list_schedules_uses_project_access_and_pagination` 1 passed"
        in row
    )
    assert "release quality docs contract full 335 passed" in row
    assert "完整分页 body" in row
    assert "`page=2`、`per_page=1`、`total=1`" in row
    assert "完整 ScheduleResponse item 必须整体等值" in row
    assert "tenant-scoped project lookup" in row
    assert "`schedule.list_by_project` offset/limit" in row
    assert 'data["page"]` / `data["per_page"]` / `data["total"]' in row
    assert "schedule list exact pagination body 契约" in row
    assert "data 和几个分页数字分别看起来对" in row

    assert "Schedule list 精确响应契约" in ops_row
    assert "包含 timezone/missed_fire_policy/quiet_windows/last_run_at/next_run_at" in (
        ops_row
    )
    assert "字段集合精确匹配 ScheduleResponse" in ops_row
    assert "assert data == {" in list_block
    assert '"timezone": "Asia/Shanghai"' in list_block
    assert '"next_run_at": schedule.next_run_at.isoformat().replace(' in list_block
    assert '"page": 2' in list_block
    assert '"per_page": 1' in list_block
    assert '"total": 1' in list_block
    for rejected in [
        'assert data["page"] == 2',
        'assert data["per_page"] == 1',
        'assert data["total"] == 1',
        'assert data["data"] == [',
        'assert set(data["data"][0]) == {',
        'data["data"][0]["cron_expr"] == "0 * * * *"',
    ]:
        assert rejected not in list_block


def test_quality_ops_capture_schedule_crud_exact_response_audit_contract():
    schedules_test = _read(SCHEDULES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Schedule CRUD exact response/audit 契约）"
    )

    assert "Schedule CRUD exact response/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_schedules.py::test_create_schedule "
        "tests/unit/test_api/test_schedules.py::test_update_schedule_recomputes_next_run "
        "tests/unit/test_api/test_schedules.py::test_delete_schedule` 3 passed"
        in row
    )
    assert "schedules full 11 passed" in row
    assert "release quality docs contract full 179 passed" in row
    assert "`SCHEDULE_EDIT` 权限调用" in row
    assert "tenant-scoped project lookup" in row
    assert "pipeline/schedule lookup" in row
    assert "create/update/delete 仓储 exact 参数" in row
    assert "完整 ScheduleResponse" in row
    assert "tenant/user/action/resource/before_state/after_state" in row
    assert "`compute_next_run_at` 输入与 next_run_at JSON 口径" in row
    assert "此前只抽查 cron/pipeline/timezone/next_run 或 audit action/resource" in row
    assert "Schedule 正向测试只证明“调度接口成功且几个字段看起来对”" in row

    assert "def _expected_schedule_response(schedule) -> dict:" in schedules_test

    create_block = _marked_block(
        schedules_test,
        "async def test_create_schedule(",
        "async def test_create_schedule_rejects_pipeline_outside_project_without_side_effects",
    )
    for expected in [
        "mock_user, project_id, pipeline_id",
        "schedule.created_at = datetime(2026, 5, 31, 20, 21, 22, tzinfo=timezone.utc)",
        "assert data == {",
        '"quiet_windows": [',
        '"last_run_at": None',
        '"next_run_at": "2026-05-29T03:15:00Z"',
        '"created_at": "2026-05-31T20:21:22Z"',
        "Action.SCHEDULE_EDIT",
        'compute_next.assert_called_once_with("15 3 * * *", "UTC")',
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(",
        "mock_repos.pipeline.get_by_id.assert_awaited_once_with(pipeline_id)",
        "mock_repos.schedule.create.assert_awaited_once_with(",
        "assert audit_kwargs == {",
        '"action": "schedule.create"',
        '"before_state": None',
        '"after_state": data',
    ]:
        assert expected in create_block
    assert 'data["cron_expr"]' not in create_block
    assert 'audit_kwargs["after_state"]["cron_expr"]' not in create_block

    delete_block = _marked_block(
        schedules_test,
        "async def test_delete_schedule(",
        "async def test_update_schedule_recomputes_next_run",
    )
    for expected in [
        "mock_user, project_id, pipeline_id",
        "before_state = _expected_schedule_response(schedule)",
        "Action.SCHEDULE_EDIT",
        "mock_repos.schedule.get_by_id.assert_awaited_once_with(schedule.id)",
        "mock_repos.schedule.delete.assert_awaited_once_with(schedule)",
        "assert audit_kwargs == {",
        '"action": "schedule.delete"',
        '"before_state": before_state',
        '"after_state": None',
    ]:
        assert expected in delete_block
    assert 'audit_kwargs["before_state"]["cron_expr"]' not in delete_block

    update_block = _marked_block_or_tail(
        schedules_test,
        "async def test_update_schedule_recomputes_next_run",
        "\n\n@pytest.mark.asyncio",
    )
    for expected in [
        "mock_user,",
        "before_state = _expected_schedule_response(schedule)",
        "new_next = datetime(2026, 6, 1, 2, 30, tzinfo=timezone.utc)",
        "assert data == _expected_schedule_response(schedule)",
        "Action.SCHEDULE_EDIT",
        'compute_next.assert_called_once_with("30 2 * * *", "Asia/Shanghai")',
        "mock_repos.schedule.update.assert_awaited_once_with(",
        "assert audit_kwargs == {",
        '"action": "schedule.update"',
        '"before_state": before_state',
        '"after_state": _expected_schedule_response(schedule)',
    ]:
        assert expected in update_block
    assert 'data["next_run_at"]' not in update_block
    assert 'audit_kwargs["after_state"]["next_run_at"]' not in update_block


def test_quality_ops_capture_schedule_missing_project_lookup_exact_contract():
    row = _quality_ops_row_containing(
        "Schedule missing project tenant lookup 精确契约"
    )
    schedules_test = _read(SCHEDULES_TEST)

    assert "Schedule missing project tenant lookup 精确契约" in row
    assert (
        "`tests/unit/test_api/test_schedules.py::test_schedule_routes_hide_missing_project_without_side_effects` 1 passed"
        in row
    )
    assert "五个父项目缺失入口现在固定每次都以同一个 `project_id` 和 `mock_user.tenant_id`" in (
        row
    )
    assert "不回显 project_id/schedule_id" in row
    assert "`project.get_for_tenant.await_count == 5`" in row
    assert "查错 project_id、漏掉 tenant scope" in row
    assert "五个入口都查过项目" in row
    assert "mock_user," in schedules_test
    assert "mock_repos.project.get_for_tenant.await_args_list == [" in (
        schedules_test
    )
    assert "call(project_id, mock_user.tenant_id)" in schedules_test
    assert "assert str(project_id) not in resp.text" in schedules_test
    assert "assert str(schedule_id) not in resp.text" in schedules_test
    assert "assert mock_repos.project.get_for_tenant.await_count == 5" not in (
        schedules_test
    )


def test_quality_ops_capture_schedule_silent_window_integration_exact_no_fire_audit_contract():
    silent_windows = _read(SILENT_WINDOWS_INTEGRATION)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_silent_windows.py::"
            "test_cron_tick_in_silent_window_skips_run_writes_audit_and_preserves_last_run_at")

    assert "` 1 passed" in row
    assert "release quality docs contract full 233 passed" in row
    assert "targeted ruff passed" in row
    assert "不创建 schedule run" in row
    assert "Schedule.last_run_at/last_error 不变" in row
    assert "next_run_at 不被推进" in row
    assert "`schedule_skipped_silent_window` AuditEvent" in row
    assert "tenant/user/resource/before_state/after_state 完整等值" in row
    assert "window start/end 必须以 JSON `Z` 时间精确序列化" in row
    assert "此前只抽查 run count、last_run_at、audit schedule_id 和 window reason" in row
    assert "误推进 next_run_at" in row
    assert "写错 tenant/resource" in row
    assert "before_state 被误填" in row
    assert "窗口 start/end 序列化漂移" in row
    assert "没新建 run 且审计里有 reason" in row

    block = _marked_block(
        silent_windows,
        "async def test_cron_tick_in_silent_window_skips_run_writes_audit_and_preserves_last_run_at",
        "async def test_cron_tick_outside_silent_window_creates_run",
    )

    for expected in [
        "due_at = now - timedelta(minutes=1)",
        "window_start = now - timedelta(minutes=5)",
        "window_end = now + timedelta(minutes=5)",
        "assert await _schedule_runs(integration_db_session, project.id, schedule.id) == []",
        "assert refreshed.last_run_at is None",
        "assert refreshed.last_error is None",
        "assert _json_datetime(refreshed.next_run_at) == _json_datetime(due_at)",
        'AuditEvent.action == "schedule_skipped_silent_window"',
        "assert event.tenant_id == project.tenant_id",
        "assert event.user_id is None",
        'assert event.resource_type == "schedule"',
        "assert event.resource_id == schedule.id",
        "assert event.before_state is None",
        "assert event.after_state == {",
        '"schedule_id": str(schedule.id)',
        '"window": {',
        '"start_at": _json_datetime(window_start)',
        '"end_at": _json_datetime(window_end)',
        '"reason": "Release freeze"',
    ]:
        assert expected in block
    assert 'event.after_state["schedule_id"]' not in block
    assert 'event.after_state["window"]["reason"]' not in block


def test_quality_ops_capture_environment_env_vars_aad_mismatch_exact_audit_contract():
    env_vars_test = _read(ENVIRONMENT_ENV_VARS_ENCRYPTION)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_environment_env_vars_encryption.py::"
            "test_environment_env_vars_aad_mismatch_returns_500_and_audits")

    assert "` 1 passed" in row
    assert "release quality docs contract full 231 passed" in row
    assert "targeted ruff passed" in row
    assert '500 body `{"detail": "Environment env vars decrypt failed"}`' in row
    assert "响应不回显 secret" in row
    assert "`environment.env_vars_decrypt_failed` audit.event" in row
    assert "tenant/user/resource/action 精确匹配" in row
    assert "before_state 为 None" in row
    assert "after_state 精确为 decrypt/project_id/environment_id/error_type=ValueError" in row
    assert "failure payload 不含 `TOKEN`、`bound-to-source`" in row
    assert "source environment id" in row
    assert "此前只抽查 500、audit action、operation 和明文 value 不出现" in row
    assert "environment_id 错写 source id" in row
    assert "变量名 `TOKEN` 进审计" in row
    assert "坏 AAD 会 500 且审计大概写了 decrypt" in row

    block = _marked_block_or_tail(
        env_vars_test,
        "async def test_environment_env_vars_aad_mismatch_returns_500_and_audits",
        "\n\n@pytest.mark.asyncio",
    )

    assert (
        'assert mismatch_resp.json() == {"detail": '
        '"Environment env vars decrypt failed"}'
    ) in block
    assert 'assert "TOKEN" not in mismatch_resp.text' in block
    assert 'assert "bound-to-source" not in mismatch_resp.text' in block
    for expected in [
        "tenant_id::text AS tenant_id",
        "user_id::text AS user_id",
        "resource_type",
        "resource_id::text AS resource_id",
        "before_state",
        'assert audit["tenant_id"] == str(seed_run["tenant"].id)',
        'assert audit["user_id"] == str(seed_run["user"].id)',
        'assert audit["action"] == "environment.env_vars_decrypt_failed"',
        'assert audit["resource_type"] == "environment"',
        'assert audit["resource_id"] == target_id',
        'assert audit["before_state"] is None',
        'assert audit["after_state"] == {',
        '"operation": "decrypt"',
        '"project_id": project_id',
        '"environment_id": target_id',
        '"error_type": "ValueError"',
        "serialized_failure = repr(",
        'for forbidden in ["TOKEN", "bound-to-source", source_id]:',
    ]:
        assert expected in block
    assert 'audit["after_state"]["operation"]' not in block
    assert '"bound-to-source" not in repr(audit["after_state"])' not in block


def test_quality_ops_capture_environment_env_vars_encrypted_at_rest_exact_response_contract():
    env_vars_test = _read(ENVIRONMENT_ENV_VARS_ENCRYPTION)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
            "tests/integration/test_environment_env_vars_encryption.py::"
            "test_environment_env_vars_create_fetch_update_are_encrypted_at_rest -q`")
    block = _block_between(env_vars_test, "async def test_environment_env_vars_create_fetch_update_are_encrypted_at_rest", "async def test_environment_env_vars_aad_mismatch_returns_500_and_audits")

    assert "` 1 passed" in row
    assert "release quality docs contract full 302 passed" in row
    assert "targeted ruff passed" in row
    assert "create/get/update 三次完整 EnvironmentResponse" in row
    assert "id/project/name/base_image/setup/memory/cpu/disk/artifact/network/env_vars/cache/created_at" in row
    assert "DB 侧继续证明 API_TOKEN/secret 与 NEW_TOKEN/rotated-secret 不落明文" in row
    assert "此前只断言响应 `env_vars` 与 DB 不含明文" in row
    assert "Environment env_vars encrypted at rest exact response 契约" in row
    assert "只证明“密文存储且 env_vars 字段能读回”" in row

    assert "expected_response = {" in block
    for expected in [
        '"id": env_id',
        '"project_id": project_id',
        '"name": "encrypted-env"',
        '"base_image": "python:3.12.1"',
        '"setup_script": None',
        '"memory_mb": 512',
        '"cpu_cores": 1.0',
        '"disk_mb": None',
        '"max_artifact_size_mb": 100',
        '"max_artifacts_count": 50',
        '"network_policy": "deny"',
        '"env_vars": first_env',
        '"cache_key": None',
        '"created_at": body["created_at"]',
        "assert body == expected_response",
        "assert get_resp.json() == expected_response",
        "assert update_resp.json() == {",
        "**expected_response",
        '"env_vars": next_env',
        '"API_TOKEN" not in repr(stored)',
        '"secret-value" not in repr(stored)',
        '"NEW_TOKEN" not in repr(stored_after_update)',
        '"rotated-secret" not in repr(stored_after_update)',
    ]:
        assert expected in block
    assert 'get_resp.json()["env_vars"]' not in block
    assert 'update_resp.json()["env_vars"]' not in block


def test_quality_ops_capture_schedule_validation_detail_exact_contract():
    row = _quality_ops_row_containing("Schedule validation detail 精确契约")
    schedules_test = _read(SCHEDULES_TEST)

    assert "Schedule validation detail 精确契约" in row
    assert (
        "`tests/unit/test_api/test_schedules.py::test_schedule_routes_reject_invalid_cron_before_side_effects tests/unit/test_api/test_schedules.py::test_schedule_routes_reject_invalid_timezone_before_side_effects tests/unit/test_api/test_schedules.py::test_schedule_routes_reject_invalid_quiet_windows_before_side_effects` 3 passed"
        in row
    )
    assert "schedule cron_expr、timezone、quiet_windows" in row
    assert "固定 `_validation_detail_lines(response)` 的单条 detail" in row
    assert "不查 project/pipeline/schedule" in row
    assert "不调用 `compute_next_run_at`" in row
    assert "`response.text` 包含式断言错误片段" in row
    assert "同一次请求夹带额外 validation detail" in row
    assert "loc/type 文案漂移" in row
    assert "只证明“某段错误文本出现过”" in row

    validation_block = _marked_block(
        schedules_test,
        "async def test_schedule_routes_reject_invalid_cron_before_side_effects",
        "async def test_get_schedule_not_found_has_no_write_side_effects"
    )

    assert "def _validation_detail_lines(response) -> list[str]:" in schedules_test
    assert "assert _validation_detail_lines(create_resp) == [expected_detail]" in (
        validation_block
    )
    assert "assert _validation_detail_lines(update_resp) == [expected_detail]" in (
        validation_block
    )
    assert (
        "body -> quiet_windows: Value error, quiet_windows[0].start must use HH:MM"
        in validation_block
    )
    assert (
        "body -> quiet_windows: Value error, invalid timezone: Mars/Base"
        in validation_block
    )
    assert '"invalid cron expression: not cron" in create_resp.text' not in (
        validation_block
    )
    assert '"invalid timezone: Mars/Base" in update_resp.text' not in validation_block
    assert '"quiet_windows[0].start must use HH:MM" in create_resp.text' not in (
        validation_block
    )


def test_quality_ops_capture_silent_window_bypass_exact_run_response_contract():
    silent_windows = _read(SILENT_WINDOWS_INTEGRATION)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
        "tests/integration/test_silent_windows.py::"
        "test_manual_trigger_ignores_silent_windows "
        "tests/integration/test_silent_windows.py::"
        "test_webhook_trigger_ignores_silent_windows -q` 2 passed"
    )
    manual_block = _block_between(silent_windows, "async def test_manual_trigger_ignores_silent_windows", "async def test_webhook_trigger_ignores_silent_windows")
    webhook_block = _after(
        silent_windows,
        "async def test_webhook_trigger_ignores_silent_windows",
    )

    assert "release quality docs contract full 305 passed" in row
    assert "targeted ruff passed" in row
    assert "`_expected_trigger_run_response` 固定完整 RunResponse" in row
    assert "pipeline_name" in row
    assert "priority" in row
    assert "attempt" in row
    assert "timestamps/summary/error" in row
    assert "silent-window bypass exact RunResponse 契约" in row
    assert "只证明“创建了某个 queued run 且审计等于这个局部响应”" in row

    for expected in [
        "def _expected_trigger_run_response(",
        '"pipeline_name": seed_run["pipeline"].name',
        '"priority": 1',
        '"attempt": 1',
        '"started_at": None',
        '"finished_at": None',
        '"duration_ms": None',
        '"summary": None',
        '"error_message": None',
        '"created_at": body["created_at"]',
        '"updated_at": body["updated_at"]',
    ]:
        assert expected in silent_windows
    for block in [manual_block, webhook_block]:
        assert "assert body == _expected_trigger_run_response(" in block
        assert "assert audit.after_state == body" in block
    combined = manual_block + webhook_block
    assert 'assert body["status"] == "queued"' not in combined
    assert 'assert body["trigger_type"] == "manual"' not in manual_block
    assert 'assert body["trigger_type"] == "webhook"' not in webhook_block
    assert 'assert body["git_sha"]' not in combined


def test_quality_ops_capture_credential_encrypt_rotate_exact_aad_response_contract():
    credentials_test = _read(CREDENTIALS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Credential encrypt/rotate exact AAD response 契约）"
    )

    assert "Credential encrypt/rotate exact AAD response 契约" in row
    assert (
        "`tests/unit/test_api/test_credentials.py::test_create_credential_encrypts_with_aad tests/unit/test_api/test_credentials.py::test_rotate_credential_re_encrypts_with_aad` 2 passed"
        in row
    )
    assert "credentials full 14 passed" in row
    assert "release quality docs contract full 171 passed" in row
    assert "crypto.encrypt(value, context_id=f\"credential:{project.id}:db_password\")" in (
        row
    )
    assert "project/credential tenant-scoped lookup" in row
    assert "完整 CredentialResponse" in row
    assert "rotate audit 也固定 tenant/user/action/resource/before/after_state" in (
        row
    )
    assert "明文、`encrypted_value` 或 ciphertext bytes" in row
    assert "此前只用 `encrypt.assert_called_once()` 后抽查 `call_args`" in row
    assert "响应只负向检查没有明文" in row
    assert "credential 加密测试只证明“加密函数大概被调用且响应没看到 secret”" in (
        row
    )

    assert "def _expected_credential_response(credential) -> dict:" in (
        credentials_test
    )

    create_block = _marked_block(
        credentials_test,
        "async def test_create_credential_encrypts_with_aad",
        "async def test_create_credential_audit_does_not_leak_plaintext",
    )
    for expected in [
        "created.created_by = mock_user.user_id",
        "created.created_at = datetime(2026, 5, 31, 16, 17, 18, tzinfo=timezone.utc)",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)",
        "mock_crypto.encrypt.assert_called_once_with(",
        '"s3cret"',
        'context_id=f"credential:{project.id}:db_password"',
        "mock_repos.credential.create.assert_awaited_once_with(",
        "assert body == _expected_credential_response(created)",
    ]:
        assert expected in create_block
    assert "mock_crypto.encrypt.call_args" not in create_block

    rotate_block = _marked_block(
        credentials_test,
        "async def test_rotate_credential_re_encrypts_with_aad",
        "async def test_delete_credential_404_when_missing",
    )
    for expected in [
        "cred.created_by = mock_user.user_id",
        "cred.created_at = datetime(2026, 5, 31, 17, 18, 19, tzinfo=timezone.utc)",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)",
        "mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(",
        "mock_crypto.encrypt.assert_called_once_with(",
        '"new-secret"',
        'context_id=f"credential:{project.id}:db_password"',
        "assert body == _expected_credential_response(cred)",
        "assert audit_kwargs == {",
        '"action": "credential.rotate"',
        '"before_state": None',
        '"after_state": _expected_credential_response(cred)',
        "assert repr(mock_crypto.encrypt.return_value) not in serialised",
    ]:
        assert expected in rotate_block
    assert "mock_crypto.encrypt.call_args" not in rotate_block
    assert 'audit_kwargs["action"]' not in rotate_block


def test_quality_ops_capture_credential_delete_audit_complete_payload_contract():
    credentials_test = _read(CREDENTIALS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Credential delete audit complete payload 契约）"
    )

    assert "Credential delete audit complete payload 契约" in row
    assert (
        "`tests/unit/test_api/test_credentials.py::test_delete_credential_happy_path` 1 passed"
        in row
    )
    assert "credentials full 14 passed" in row
    assert "release quality docs contract full 172 passed" in row
    assert "project/credential tenant-scoped lookup" in row
    assert "`credential.delete(cred)`" in row
    assert "完整 `credential.delete` audit kwargs" in row
    assert "before_state 完整 CredentialResponse" in row
    assert "after_state None" in row
    assert "`value`、`encrypted_value` 或 ciphertext bytes" in row
    assert "此前只证明 delete 被 await" in row
    assert "局部抽查 audit action/resource/name/type" in row
    assert "credential delete 审计测试只证明“删了对象且几个字段看起来对”" in (
        row
    )

    delete_block = _marked_block(
        credentials_test,
        "async def test_delete_credential_happy_path",
        "async def test_credential_routes_hide_missing_project_without_side_effects",
    )

    for expected in [
        "cred.created_by = mock_user.user_id",
        "cred.created_at = datetime(2026, 5, 31, 18, 19, 20, tzinfo=timezone.utc)",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)",
        "mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(",
        "mock_repos.credential.delete.assert_awaited_once_with(cred)",
        "assert audit_kwargs == {",
        '"tenant_id": tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "credential.delete"',
        '"resource_type": "credential"',
        '"resource_id": cred.id',
        '"before_state": _expected_credential_response(cred)',
        '"after_state": None',
        'assert "value" not in serialised',
        'assert "encrypted_value" not in serialised',
        "assert repr(cred.encrypted_value) not in serialised",
    ]:
        assert expected in delete_block
    assert 'audit_kwargs["action"]' not in delete_block
    assert 'before_state["name"]' not in delete_block


def test_quality_ops_capture_notification_template_update_response_audit_exact_contract():
    notifications_test = _read(NOTIFICATIONS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification template update response/audit exact 契约）"
    )

    assert "Notification template update response/audit exact 契约" in row
    assert (
        "`tests/unit/test_api/test_notifications.py::test_update_rule_clears_template_when_null_submitted tests/unit/test_api/test_notifications.py::test_update_rule_keeps_template_when_omitted` 2 passed"
        in row
    )
    assert "完整 NotificationRuleResponse" in row
    assert "`NOTIFICATION_EDIT` 权限" in row
    assert "update audit before/after 的 redacted template" in row
    assert "只断言 status 200、内存 rule.template 和局部 response template" in row
    assert "模板字段看起来被清空或保留" in row

    for expected in [
        "async def test_update_rule_clears_template_when_null_submitted(",
        "async def test_update_rule_keeps_template_when_omitted(",
        "before_state = _expected_rule_audit_state(rule)",
        "assert resp.json() == _expected_rule_response(rule)",
        "assert enforce_args[3] == Action.NOTIFICATION_EDIT",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(",
        "mock_repos.notification_rule.get_by_id.assert_awaited_once_with(rule.id)",
        "mock_repos.audit.create.assert_awaited_once()",
        '"before_state": before_state,',
        '"after_state": _expected_rule_audit_state(rule),',
        '"present": False,',
        '"length": 0,',
        '"present": True,',
        "assert \"secret-token\" not in repr(audit_kwargs)",
        "assert original_template not in repr(audit_kwargs)",
    ]:
        assert expected in notifications_test
    assert 'assert resp.json()["template"] is None' not in notifications_test
    assert 'assert resp.json()["template"] == original_template' not in notifications_test
