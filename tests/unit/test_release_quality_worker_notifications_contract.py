from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
WORKER_NOTIFICATIONS_TEST = (
    ROOT / "tests" / "unit" / "test_worker" / "test_notifications.py"
)


def test_quality_ops_capture_notification_matching_rule_log_create_exact_kwargs_contract():
    row = _quality_ops_row_containing(
        "Notification matching rule log create exact kwargs 契约"
    )
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)

    assert "Notification matching rule log create exact kwargs 契约" in row
    assert (
        "`tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_matching_rule_sends_notification` 1 passed"
        in row
    )
    assert "worker notifications full 35 passed" in row
    assert "最基础的 matching-rule 成功路径现在通过 `_assert_delivery_log`" in row
    assert "{project_id,run_id,rule_id,channel_type,status,error_message}" in (
        row
    )
    assert "`get_by_delivery`、`_send_channel` 消息与 commit" in row
    assert "此前逐字段抽查 `log_repo.create`" in row
    assert "日志写入额外字段" in row
    assert "基础通知发送测试只证明“发了消息并写过一条日志”" in (
        row
    )

    matching_block = _marked_block(
        worker_notifications,
        "async def test_matching_rule_sends_notification",
        "async def test_template_rendering",
    )
    helper_block = _marked_block(
        worker_notifications,
        "def _assert_delivery_log",
        "@pytest.mark.asyncio",
    )

    assert "log_repo.create.assert_awaited_once()" in helper_block
    assert 'status = call_kwargs["status"]' in helper_block
    assert 'assert call_kwargs == {**expected, "status": status}' in helper_block
    assert 'assert status.value == expected["status"]' in helper_block
    assert "return call_kwargs" in helper_block
    assert "assert set(call_kwargs)" not in helper_block

    assert "log_repo.get_by_delivery.assert_awaited_once_with(" in matching_block
    assert "mock_send.assert_awaited_once_with(" in matching_block
    assert "self._assert_delivery_log(" in matching_block
    assert '"project_id": project_id' in matching_block
    assert '"run_id": run_id' in matching_block
    assert '"rule_id": rule.id' in matching_block
    assert '"channel_type": "webhook"' in matching_block
    assert '"status": "sent"' in matching_block
    assert '"error_message": None' in matching_block
    assert "session.commit.assert_awaited_once()" in matching_block
    assert "log_repo.create.assert_awaited_once()" not in matching_block
    assert "assert set(call_kwargs)" not in matching_block
    assert "**call_kwargs" not in matching_block

    assert 'assert call_kwargs["project_id"] == project_id' not in matching_block
    assert 'assert call_kwargs["run_id"] == run_id' not in matching_block
    assert 'assert call_kwargs["rule_id"] == rule.id' not in matching_block
    assert 'assert call_kwargs["channel_type"] == "webhook"' not in matching_block
    assert 'assert call_kwargs["status"].value == "sent"' not in matching_block
    assert 'assert call_kwargs["error_message"] is None' not in matching_block


def test_quality_ops_capture_notification_template_rendering_exact_send_log_contract():
    row = _quality_ops_row_containing(
        "Notification template rendering exact send/log 契约"
    )
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)

    assert "Notification template rendering exact send/log 契约" in row
    assert (
        "`tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_template_rendering` 1 passed"
        in row
    )
    assert "worker notifications full 35 passed" in row
    assert "release quality docs contract full 163 passed" in row
    assert "固定 rule-level 模板渲染后的完整 `_send_channel` 参数" in (
        row
    )
    assert "`get_by_delivery` delivery key、`_assert_delivery_log` direct helper 与 commit" in (
        row
    )
    assert "只看消息里有 run_id/status/passed/failed 片段" in row
    assert "模板渲染测试只证明“几个变量被替换进字符串”" in row

    template_block = _marked_block(
        worker_notifications,
        "async def test_template_rendering",
        "async def test_channel_template_overrides_rule_template_and_loads_project_name",
    )

    assert "project_id = uuid4()" in template_block
    assert 'expected_message = f"Run {run_id} status=failed passed=5 failed=3"' in (
        template_block
    )
    assert "rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)" in (
        template_block
    )
    assert "log_repo.get_by_delivery.assert_awaited_once_with(" in template_block
    assert "run_id=run_id" in template_block
    assert "rule_id=rule.id" in template_block
    assert 'channel_type="webhook"' in template_block
    assert "mock_send.assert_awaited_once_with(" in template_block
    assert '"webhook"' in template_block
    assert '{"url": "https://example.com"}' in template_block
    assert "expected_message" in template_block
    assert "self._assert_delivery_log(" in template_block
    assert '"project_id": project_id' in template_block
    assert '"run_id": run_id' in template_block
    assert '"rule_id": rule.id' in template_block
    assert '"channel_type": "webhook"' in template_block
    assert '"status": "sent"' in template_block
    assert '"error_message": None' in template_block
    assert "session.commit.assert_awaited_once()" in template_block
    assert "log_repo.create.assert_awaited_once()" not in template_block
    assert "assert set(call_kwargs)" not in template_block
    assert "**call_kwargs" not in template_block

    assert "mock_send.assert_awaited_once()" not in template_block
    assert "sent_message = mock_send.await_args.args[2]" not in template_block
    assert 'assert "status=failed" in sent_message' not in template_block
    assert 'assert "passed=5" in sent_message' not in template_block
    assert 'assert "failed=3" in sent_message' not in template_block


def test_quality_ops_capture_notification_failure_log_exact_kwargs_error_contract():
    row = _quality_ops_row_containing(
        "Notification failure log exact kwargs/error 契约"
    )
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)

    assert "Notification failure log exact kwargs/error 契约" in row
    assert (
        "`tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_send_failure_logged tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_template_render_failure_logged_without_sending` 2 passed"
        in row
    )
    assert "worker notifications full 35 passed" in row
    assert "send failure 与 template render failure 现在通过 `_assert_delivery_log`" in (
        row
    )
    assert "完整 `{project_id,run_id,rule_id,channel_type,status,error_message}`" in (
        row
    )
    assert "`send failed for [REDACTED] with [REDACTED]`" in row
    assert "`unknown template variable: unknown`" in row
    assert "send failure 还只用包含式检查 `send failed` 与脱敏片段" in (
        row
    )
    assert "错误文本退化或泄露信息仍带着相似片段" in row
    assert "通知失败日志测试只证明“失败被记录且大概脱敏”" in row

    send_failure_block = _marked_block(
        worker_notifications,
        "async def test_send_failure_logged",
        "async def test_template_render_failure_logged_without_sending",
    )
    template_failure_block = _marked_block(
        worker_notifications,
        "async def test_template_render_failure_logged_without_sending",
        "async def test_existing_delivery_log_skips_duplicate_send",
    )

    for block in (send_failure_block, template_failure_block):
        assert "self._assert_delivery_log(" in block
        assert '"project_id": project_id' in block
        assert '"run_id": run_id' in block
        assert '"rule_id": rule.id' in block
        assert '"channel_type": "webhook"' in block
        assert '"status": "failed"' in block
        assert "session.commit.assert_awaited_once()" in block
        assert "log_repo.create.assert_awaited_once()" not in block
        assert "assert set(call_kwargs)" not in block
        assert "**call_kwargs" not in block
        assert 'assert call_kwargs["project_id"] == project_id' not in block
        assert 'assert call_kwargs["run_id"] == run_id' not in block
        assert 'assert call_kwargs["rule_id"] == rule.id' not in block
        assert 'assert call_kwargs["channel_type"] == "webhook"' not in block
        assert 'assert call_kwargs["status"].value == "failed"' not in block

    assert (
        '"error_message": "send failed for [REDACTED] with [REDACTED]"'
        in send_failure_block
    )
    assert 'assert "send failed" in call_kwargs["error_message"]' not in (
        send_failure_block
    )
    assert 'assert "[REDACTED]" in call_kwargs["error_message"]' in (
        send_failure_block
    )
    assert 'assert secret_url not in call_kwargs["error_message"]' in (
        send_failure_block
    )
    assert 'assert header_token not in call_kwargs["error_message"]' in (
        send_failure_block
    )

    assert "mock_send.assert_not_awaited()" in template_failure_block
    assert (
        '"error_message": "unknown template variable: unknown"'
        in template_failure_block
    )
    assert (
        'assert "unknown template variable" in call_kwargs["error_message"]'
        not in template_failure_block
    )


def test_quality_ops_capture_notification_existing_delivery_short_circuit_contract():
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification existing delivery idempotent short-circuit 契约）"
    )

    assert "Notification existing delivery idempotent short-circuit 契约" in row
    assert (
        "`tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_existing_delivery_log_skips_duplicate_send` 1 passed"
        in row
    )
    assert "worker notifications full 35 passed" in row
    assert "release quality docs contract full 202 passed" in row
    assert "先查 delivery key" in row
    assert "不加载 project_name" in row
    assert "不发送 channel" in row
    assert "不创建新 NotificationLog" in row
    assert "此前只证明不 send、不 create" in row
    assert "delivery 去重放到模板渲染或 project lookup 之后" in row
    assert "未知模板变量噪声" in row
    assert "只证明“最后没有再次发送”" in row

    test_block = _marked_block(
        worker_notifications,
        "async def test_existing_delivery_log_skips_duplicate_send",
        "async def test_duplicate_log_integrity_error_after_send_is_treated_as_existing_delivery",
    )

    for expected in [
        'rule.template = "Run {{project_name}} status={{status}}"',
        "project_repo = AsyncMock()",
        "project_repo.get_by_id = AsyncMock(",
        '"duplicate delivery must short-circuit before project lookup"',
        "ProjectRepository\", return_value=project_repo",
        "rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)",
        "log_repo.get_by_delivery.assert_awaited_once_with(",
        "run_id=run_id",
        "rule_id=rule.id",
        'channel_type="webhook"',
        "project_repo.get_by_id.assert_not_awaited()",
        "mock_send.assert_not_awaited()",
        "log_repo.create.assert_not_awaited()",
        "session.commit.assert_awaited_once_with()",
    ]:
        assert expected in test_block
    assert "rule.template = None" not in test_block


def test_quality_ops_capture_notification_log_write_exception_attempted_log_contract():
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)
    row = _quality_ops_row("|", contains="Notification log write exception attempted log direct kwargs follow-up")

    assert (
        "`tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_duplicate_log_integrity_error_after_send_is_treated_as_existing_delivery "
        "tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_non_duplicate_log_integrity_error_propagates_after_send "
        "tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_unexpected_log_write_failure_propagates_after_send` "
        "3 passed"
    ) in row
    assert "worker notifications full 35 passed" in row
    assert "release quality docs contract full 344 passed" in row
    assert "targeted ruff passed" in row
    assert 'get_by_delivery(run_id, rule_id, channel_type="webhook")' in row
    assert "完整 `{project_id,run_id,rule_id,channel_type,status,error_message}`" in row
    assert "duplicate 唯一约束分支 commit" in row
    assert "FK/RuntimeError 分支不 commit" in row
    assert "`log_repo.create.assert_awaited_once()`" in row
    assert "send 后碰过日志仓储" in row

    duplicate_block = _marked_block(
        worker_notifications,
        "async def test_duplicate_log_integrity_error_after_send_is_treated_as_existing_delivery",
        "async def test_non_duplicate_log_integrity_error_propagates_after_send",
    )
    non_duplicate_block = _marked_block(
        worker_notifications,
        "async def test_non_duplicate_log_integrity_error_propagates_after_send",
        "async def test_unexpected_log_write_failure_propagates_after_send",
    )
    unexpected_block = _marked_block(
        worker_notifications,
        "async def test_unexpected_log_write_failure_propagates_after_send",
        "async def test_multiple_channels_per_rule",
    )

    for block in (duplicate_block, non_duplicate_block, unexpected_block):
        assert "log_repo.get_by_delivery.assert_awaited_once_with(" in block
        assert "run_id=run_id" in block
        assert "rule_id=rule.id" in block
        assert 'channel_type="webhook"' in block
        assert "self._assert_delivery_log(" in block
        assert '"project_id": project_id' in block
        assert '"run_id": run_id' in block
        assert '"rule_id": rule.id' in block
        assert '"channel_type": "webhook"' in block
        assert '"status": "sent"' in block
        assert '"error_message": None' in block
        assert "log_repo.create.assert_awaited_once()" not in block
        assert "assert set(call_kwargs)" not in block
        assert 'assert call_kwargs["project_id"] == project_id' not in block
        assert 'assert call_kwargs["status"].value == "sent"' not in block

    assert "session.commit.assert_awaited_once()" in duplicate_block
    assert "session.commit.assert_not_awaited()" in non_duplicate_block
    assert "session.commit.assert_not_awaited()" in unexpected_block
    assert "assert exc_info.value is error" in unexpected_block


def test_quality_ops_capture_notification_multi_channel_log_create_exact_contract():
    row = _quality_ops_row_containing(
        "Notification multi-channel log create 精确契约"
    )
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)

    assert "Notification multi-channel log create 精确契约" in row
    assert "`log_repo.create` 的完整" in row
    assert "{project_id, run_id, rule_id, channel_type, status, error_message}" in (
        row
    )
    assert "`await_count == 2`、channel_type 列表和 `all(...)` 字段子集" in (
        row
    )
    assert "project/run/rule 串错" in row
    assert "发送了两个渠道且字段大概一致" in row
    assert '"project_id": create_call.kwargs["project_id"]' in worker_notifications
    assert '"channel_type": create_call.kwargs["channel_type"]' in (
        worker_notifications
    )
    assert '"status": create_call.kwargs["status"].value' in worker_notifications
    assert '"channel_type": "email"' in worker_notifications
    assert '"channel_type": "webhook"' in worker_notifications
    assert "and create_call.kwargs[\"run_id\"] == run_id" not in worker_notifications
    assert "for create_call in log_repo.create.await_args_list\n        )" not in (
        worker_notifications
    )
    assert "assert log_repo.create.await_count == 2" not in worker_notifications


def test_quality_ops_capture_notification_template_lazy_log_create_exact_contract():
    row = _quality_ops_row_containing(
        "Notification template/lazy log create 精确契约"
    )
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)

    assert "Notification template/lazy log create 精确契约" in row
    assert (
        "`tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_channel_template_overrides_rule_template_and_loads_project_name tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_project_name_is_not_loaded_when_templates_do_not_reference_it` 2 passed"
        in row
    )
    assert "channel template override 与 lazy project-name 用例" in row
    assert "`_send_channel` 消息" in row
    assert "两条 `log_repo.create` 的完整" in row
    assert "{project_id, run_id, rule_id, channel_type, status, error_message}" in (
        row
    )
    assert "`log_repo.create.await_count == 2`" in row
    assert "日志落错 project/run/rule、status/error 漂移" in row
    assert "通知模板测试只证明“消息发出且写了两条日志”" in row
    assert "test_channel_template_overrides_rule_template_and_loads_project_name" in (
        worker_notifications
    )
    assert "test_project_name_is_not_loaded_when_templates_do_not_reference_it" in (
        worker_notifications
    )
    assert "project_repo.get_by_id.assert_not_awaited()" in worker_notifications
    assert '"status": create_call.kwargs["status"].value' in worker_notifications
    assert '"error_message": create_call.kwargs["error_message"]' in (
        worker_notifications
    )
    assert '"channel_type": "webhook"' in worker_notifications
    assert '"channel_type": "email"' in worker_notifications
    assert "assert log_repo.create.await_count == 2" not in worker_notifications


def test_quality_ops_capture_notification_consecutive_failures_exact_log_contract():
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification consecutive failures exact log 契约）"
    )

    assert "Notification consecutive failures exact log 契约" in row
    assert (
        "`tests/unit/test_worker/test_notifications.py::TestEvaluateAndNotify::test_or_group_with_consecutive_failures_sends_notification` 1 passed"
        in row
    )
    assert "worker notifications full 35 passed" in row
    assert "release quality docs contract full 182 passed" in row
    assert "`_load_consecutive_failures(run_repo, project_id, run_id)`" in row
    assert "delivery 去重 key" in row
    assert "`_send_channel` 完整参数" in row
    assert "`_assert_delivery_log` direct helper 与 sent log 投影" in row
    assert "此前只证明连续失败数被加载、消息发过、日志写过一次" in row
    assert "delivery key 漂移" in row
    assert "log 的 project/run/rule/channel 串错" in row
    assert "只证明“OR 条件触发后发了消息”" in row

    test_block = _marked_block(
        worker_notifications,
        "async def test_or_group_with_consecutive_failures_sends_notification",
        "async def test_non_matching_rule_skipped",
    )
    helper_block = _marked_block(
        worker_notifications,
        "def _assert_delivery_log",
        "\n\n    @pytest.mark.asyncio",
    )
    for expected in [
        "log_repo.create.assert_awaited_once()",
        "call_kwargs = log_repo.create.await_args.kwargs",
        "status = call_kwargs[\"status\"]",
        'assert call_kwargs == {**expected, "status": status}',
        'assert status.value == expected["status"]',
        "return call_kwargs",
    ]:
        assert expected in helper_block
    assert "assert set(call_kwargs)" not in helper_block

    for expected in [
        "load_consecutive.assert_awaited_once_with(run_repo, project_id, run_id)",
        "log_repo.get_by_delivery.assert_awaited_once_with(",
        "run_id=run_id",
        "rule_id=rule.id",
        'channel_type="webhook"',
        "mock_send.assert_awaited_once_with(",
        "self._assert_delivery_log(",
        '"project_id"',
        '"run_id"',
        '"rule_id"',
        '"channel_type"',
        '"status"',
        '"error_message"',
        '"status": "sent"',
        '"error_message": None',
        "session.commit.assert_awaited_once()",
    ]:
        assert expected in test_block
    assert "assert set(call_kwargs)" not in test_block
    assert "log_repo.create.assert_awaited_once()\n        session.commit.assert_awaited_once()" not in (
        test_block
    )
