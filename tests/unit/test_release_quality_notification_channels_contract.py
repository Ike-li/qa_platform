from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _marked_block_or_tail,
    _notification_channel_http_case_blocks,
    _notification_channel_sections,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
WORKER_CHANNELS_TEST = ROOT / "tests" / "unit" / "test_worker" / "test_channels.py"
WORKER_CHANNELS_SOURCE = (
    ROOT / "src" / "qaplatform" / "worker" / "notifications" / "channels.py"
)


def test_quality_ops_capture_notification_channel_text_success_exact_timeout_call_contract():
    quality_ops = _quality_ops_row_containing(
        "Notification channel text success exact timeout/call 契约"
    )
    channels_test = _read(WORKER_CHANNELS_TEST)

    assert "Notification channel text success exact timeout/call 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_channels.py::TestWebhookChannel::test_success tests/unit/test_worker/test_channels.py::TestDingtalkChannel::test_success_text_message tests/unit/test_worker/test_channels.py::TestWecomChannel::test_success_text_message` 3 passed"
        in quality_ops
    )
    assert "channels full 38 passed" in quality_ops
    assert "固定 `ChannelResult(success=True)`、`AsyncClient(timeout=...)`" in (
        quality_ops
    )
    assert "endpoint、params/headers 与完整 json payload" in quality_ops
    assert "此前只看局部 `params/json/headers`" in quality_ops
    assert "timeout 被删、DingTalk/WeCom endpoint 常量被绕开" in quality_ops
    assert "基础通知渠道测试只证明“发过一个看起来像 text 的 payload”" in (
        quality_ops
    )

    sections = _notification_channel_sections(channels_test)
    webhook_success_block = _marked_block(
        sections["webhook"],
        "async def test_success(self):",
        "async def test_error_response",
    )
    dingtalk_text_block = _marked_block(
        sections["dingtalk"],
        "async def test_success_text_message",
        "async def test_signs_request_when_secret_configured",
    )
    wecom_text_block = _marked_block(
        sections["wecom"],
        "async def test_success_text_message",
        "async def test_timeout_returns_failure_without_webhook_key",
    )

    assert "assert result == ChannelResult(success=True)" in webhook_success_block
    assert "client_cls.assert_called_once_with(timeout=WebhookChannel.TIMEOUT)" in (
        webhook_success_block
    )
    assert 'assert call_args.args == ("POST", "https://hooks.example.com/notify")' in (
        webhook_success_block
    )
    assert 'assert call_args.kwargs == {' in webhook_success_block
    assert '"json": {"message": "test message"},' in webhook_success_block
    assert '"headers": {},' in webhook_success_block

    assert "assert result == ChannelResult(success=True)" in dingtalk_text_block
    assert "client_cls.assert_called_once_with(timeout=DingtalkChannel.TIMEOUT)" in (
        dingtalk_text_block
    )
    assert "assert call_args.args == (DingtalkChannel.ENDPOINT,)" in (
        dingtalk_text_block
    )
    assert '"params": {"access_token": "token-123"},' in dingtalk_text_block
    assert '"msgtype": "text"' in dingtalk_text_block
    assert '"text": {"content": "构建完成"}' in dingtalk_text_block

    assert "assert result == ChannelResult(success=True)" in wecom_text_block
    assert "client_cls.assert_called_once_with(timeout=WecomChannel.TIMEOUT)" in (
        wecom_text_block
    )
    assert "assert call_args.args == (WecomChannel.ENDPOINT,)" in wecom_text_block
    assert '"params": {"key": "key-123"},' in wecom_text_block
    assert '"msgtype": "text"' in wecom_text_block
    assert '"text": {"content": "构建完成"}' in wecom_text_block

    combined = webhook_success_block + dingtalk_text_block + wecom_text_block
    assert "assert result.success is True" not in combined
    assert "call_args.args[0]" not in combined
    assert 'call_args.kwargs["params"]' not in combined
    assert 'call_args.kwargs["json"]' not in combined
    assert 'call_args.kwargs["headers"]' not in combined


def test_quality_ops_capture_email_smtp_error_redaction_contract():
    quality_ops = _quality_ops_row_containing("Email SMTP error redaction 契约")
    channels_test = _read(WORKER_CHANNELS_TEST)
    channels_source = _read(WORKER_CHANNELS_SOURCE)

    assert "Email SMTP error redaction 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_channels.py::TestEmailChannel::test_connection_error_redacts_config_values` 1 passed"
        in quality_ops
    )
    assert "channels full 38 passed" in quality_ops
    assert "SMTP/OSError 分支现在使用 `redact_sensitive_text` 只脱敏 `smtp_password`" in (
        quality_ops
    )
    assert "保留 host 诊断信息" in quality_ops
    assert "smtp://***@smtp.example.com refused; password=[REDACTED]" in (
        quality_ops
    )
    assert "此前直接返回 `SMTP error: {exc}`" in quality_ops
    assert "把密钥写入通知日志" in quality_ops
    assert "邮件渠道失败测试只证明“错误文本里有连接失败”" in quality_ops

    assert "from qaplatform.engine.redact import redact_sensitive_text" in (
        channels_source
    )
    assert "safe_error = redact_sensitive_text(" in channels_source
    assert '{"smtp_password": password}' in channels_source
    assert 'f"SMTP error: {exc}"' not in channels_source

    test_block = _marked_block(
        channels_test,
        "async def test_connection_error_redacts_config_values",
        "async def test_missing_config_returns_error",
    )
    assert '"smtp_password": "super-secret-password"' in test_block
    assert "smtp://mailer:super-secret-password@smtp.example.com refused" in (
        test_block
    )
    assert "assert result == ChannelResult(" in test_block
    assert (
        '"SMTP error: smtp://***@smtp.example.com refused; password=[REDACTED]"'
        in test_block
    )
    assert 'assert "super-secret-password" not in result.error' in test_block
    assert 'assert "mailer:" not in result.error' in test_block
    assert "assert \"Connection refused\" in result.error" not in test_block


def test_quality_ops_capture_email_smtp_success_wait_for_thread_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "Email SMTP success wait_for/thread exact 契约"
    )
    channels_test = _read(WORKER_CHANNELS_TEST)

    assert "Email SMTP success wait_for/thread exact 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_channels.py::TestEmailChannel::test_success tests/unit/test_worker/test_channels.py::TestEmailChannel::test_ssl_port_465` 2 passed"
        in quality_ops
    )
    assert "channels full 38 passed" in quality_ops
    assert "release quality docs contract full 159 passed" in quality_ops
    assert "`wait_for(thread_result, timeout=EmailChannel.TIMEOUT)`" in quality_ops
    assert "锁住 `to_thread` 包裹同一个 `_send_sync` 调用" in quality_ops
    assert "此前仍用 `wait_for.assert_awaited_once()` / `to_thread.assert_awaited_once()` 无参断言" in (
        quality_ops
    )
    assert "SSL 465 用例也只抽查 port" in quality_ops
    assert "避免 Email SMTP 成功测试只证明“成功返回且线程 helper 被碰过”" in (
        quality_ops
    )

    success_block = _marked_block(
        channels_test,
        "async def test_success",
        "async def test_connection_error_redacts_config_values",
    )
    ssl_block = _marked_block(
        channels_test,
        "async def test_ssl_port_465",
        "async def test_smtp_timeout_is_reported",
    )
    combined = success_block + ssl_block

    assert combined.count("thread_result = asyncio.get_running_loop().create_future()") == 2
    assert combined.count("to_thread_mock = MagicMock(return_value=thread_result)") == 2
    assert combined.count("new=to_thread_mock") == 2
    assert combined.count("assert result == ChannelResult(success=True)") == 2
    assert combined.count("to_thread.assert_called_once()") == 2
    assert combined.count(
        "wait_for.assert_awaited_once_with(thread_result, timeout=EmailChannel.TIMEOUT)"
    ) == 2
    assert "assert call_args.args[0] == channel._send_sync" in success_block
    assert "assert call_args.args[1:7] == (" in success_block
    assert '"smtp.example.com",' in success_block
    assert "587," in success_block
    assert '"user",' in success_block
    assert '"pass",' in success_block
    assert "assert to_thread.call_args.args[0] == channel._send_sync" in ssl_block
    assert "assert to_thread.call_args.args[1:7] == (" in ssl_block
    assert "465," in ssl_block
    assert "None," in ssl_block
    assert '"",' in ssl_block
    assert "wait_for.assert_awaited_once()" not in combined
    assert "to_thread.assert_awaited_once()" not in combined
    assert "assert result.success is True" not in combined
    assert "assert to_thread.await_args.args[2] == 465" not in ssl_block


def test_quality_ops_capture_channel_router_exact_result_propagation_contract():
    quality_ops = _quality_ops_row_containing(
        "ChannelRouter exact result propagation 契约"
    )
    channels_test = _read(WORKER_CHANNELS_TEST)

    assert "ChannelRouter exact result propagation 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_channels.py::TestChannelRouter::test_route_email tests/unit/test_worker/test_channels.py::TestChannelRouter::test_route_webhook tests/unit/test_worker/test_channels.py::TestChannelRouter::test_route_dingtalk tests/unit/test_worker/test_channels.py::TestChannelRouter::test_route_wecom tests/unit/test_worker/test_channels.py::TestChannelRouter::test_route_known_channel_propagates_failure_result tests/unit/test_worker/test_channels.py::TestRouteChannelFunction::test_delegates_to_router` 6 passed"
        in quality_ops
    )
    assert "channels full 39 passed" in quality_ops
    assert "release quality docs contract full 161 passed" in quality_ops
    assert "下游失败 `ChannelResult(success=False, error=...)` 原样透传" in (
        quality_ops
    )
    assert "module-level wrapper 忽略 router 返回值" in quality_ops
    assert "避免通知路由测试只证明“调到了某个 channel 且成功布尔值为真”" in (
        quality_ops
    )

    router_block = _marked_block(
        channels_test,
        "class TestChannelRouter:",
        "class TestRouteChannelFunction:",
    )
    wrapper_block = _marked_block_or_tail(
        channels_test,
        "class TestRouteChannelFunction:",
        "# WorkerChannelFactory",
    )

    for channel_name in ("email", "webhook", "dingtalk", "wecom"):
        assert f'router._channels = {{"{channel_name}":' in router_block
    assert router_block.count("assert result == ChannelResult(success=True)") == 4
    assert "async def test_route_known_channel_propagates_failure_result" in router_block
    assert 'channel_result = ChannelResult(success=False, error="downstream failed")' in (
        router_block
    )
    assert "assert result == channel_result" in router_block
    assert "channel.send.assert_awaited_once_with(config, \"msg\")" in router_block
    assert 'mock_result = ChannelResult(success=False, error="router failed")' in (
        wrapper_block
    )
    assert "assert result == mock_result" in wrapper_block
    assert "mock_route.assert_awaited_once_with(\"email\", {}, \"msg\")" in (
        wrapper_block
    )
    assert "assert result.success is True" not in router_block
    assert "assert result.success is True" not in wrapper_block


def test_quality_ops_capture_email_smtp_timeout_wait_for_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "Email SMTP timeout wait_for exact 契约"
    )
    channels_test = _read(WORKER_CHANNELS_TEST)

    assert "Email SMTP timeout wait_for exact 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_channels.py::TestEmailChannel::test_smtp_timeout_is_reported` 1 passed"
        in quality_ops
    )
    assert "channels full 38 passed" in quality_ops
    assert "让 `asyncio.wait_for` 抛 `TimeoutError`" in quality_ops
    assert "`wait_for(thread_result, timeout=EmailChannel.TIMEOUT)`" in quality_ops
    assert "此前让 `asyncio.to_thread` 自己抛 `TimeoutError`" in quality_ops
    assert "实现移除 `wait_for`、timeout 参数漂移" in quality_ops
    assert "邮件 timeout 测试只证明“某处抛了 TimeoutError”" in quality_ops

    test_block = _marked_block(
        channels_test,
        "async def test_smtp_timeout_is_reported",
        "# --------------------------------------------------------------------------- #",
    )

    assert "thread_result = asyncio.get_running_loop().create_future()" in test_block
    assert "to_thread_mock = MagicMock(return_value=thread_result)" in test_block
    assert (
        'patch(\n                "qaplatform.worker.notifications.channels.asyncio.wait_for",'
        in test_block
    )
    assert "side_effect=asyncio.TimeoutError" in test_block
    assert "assert result == ChannelResult(" in test_block
    assert "to_thread.assert_called_once()" in test_block
    assert "assert to_thread.call_args.args[0] == channel._send_sync" in test_block
    assert "assert to_thread.call_args.args[1:7] == (" in test_block
    assert "wait_for.assert_awaited_once_with(thread_result, timeout=EmailChannel.TIMEOUT)" in (
        test_block
    )
    assert "to_thread.side_effect = asyncio.TimeoutError" not in test_block
    assert "to_thread.assert_awaited_once()" not in test_block


def test_quality_ops_capture_notification_channel_http_request_exact_args_kwargs_contract():
    quality_ops = _quality_ops_row_containing(
        "Notification channel HTTP request exact args/kwargs 契约"
    )
    channels_test = _read(WORKER_CHANNELS_TEST)

    assert "Notification channel HTTP request exact args/kwargs 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_channels.py::TestWebhookChannel::test_custom_method tests/unit/test_worker/test_channels.py::TestWebhookChannel::test_custom_headers tests/unit/test_worker/test_channels.py::TestDingtalkChannel::test_signs_request_when_secret_configured tests/unit/test_worker/test_channels.py::TestDingtalkChannel::test_markdown_message tests/unit/test_worker/test_channels.py::TestWecomChannel::test_markdown_message` 5 passed"
        in quality_ops
    )
    assert "channels full 38 passed" in quality_ops
    assert "固定 HTTP call 的完整 args 与 kwargs" in quality_ops
    assert "覆盖 endpoint、method、params、headers 和 json payload" in quality_ops
    assert "此前多只看 `kwargs[\"json\"]` 或 params 子字段" in quality_ops
    assert "发错 URL、漏 access_token/key、headers 丢失" in quality_ops
    assert "渠道测试只证明“某个 json/params 片段被传过”" in quality_ops

    blocks = _notification_channel_http_case_blocks(channels_test)
    webhook_method_block = blocks["webhook_method"]
    webhook_headers_block = blocks["webhook_headers"]
    dingtalk_sign_block = blocks["dingtalk_sign"]
    dingtalk_markdown_block = blocks["dingtalk_markdown"]
    wecom_markdown_block = blocks["wecom_markdown"]

    assert 'assert call_args.args == ("PUT", "https://hooks.example.com/notify")' in (
        webhook_method_block
    )
    assert '"headers": {},' in webhook_method_block
    assert '"json": {"message": "test message"},' in webhook_method_block
    assert 'assert call_args.args == ("POST", "https://hooks.example.com/notify")' in (
        webhook_headers_block
    )
    assert '"headers": {"Authorization": "Bearer token123"},' in (
        webhook_headers_block
    )
    assert '"json": {"message": "test message"},' in webhook_headers_block

    assert "assert call_args.args == (DingtalkChannel.ENDPOINT,)" in (
        dingtalk_sign_block
    )
    assert '"timestamp": timestamp' in dingtalk_sign_block
    assert '"sign": expected_sign' in dingtalk_sign_block
    assert '"msgtype": "text"' in dingtalk_sign_block
    assert '"text": {"content": "构建完成"}' in dingtalk_sign_block
    assert "assert call_args.args == (DingtalkChannel.ENDPOINT,)" in (
        dingtalk_markdown_block
    )
    assert '"params": {"access_token": "token-123"}' in dingtalk_markdown_block
    assert '"markdown": {"title": "流水线通知", "text": "### 构建完成"}' in (
        dingtalk_markdown_block
    )

    assert "assert call_args.args == (WecomChannel.ENDPOINT,)" in (
        wecom_markdown_block
    )
    assert '"params": {"key": "key-123"}' in wecom_markdown_block
    assert '"markdown": {"content": "### 构建完成"}' in wecom_markdown_block

    assert 'call_kwargs = mock_client.request.await_args.kwargs' not in (
        webhook_method_block + webhook_headers_block
    )
    assert 'params = mock_client.post.await_args.kwargs["params"]' not in (
        dingtalk_sign_block
    )
    assert 'mock_client.post.await_args.kwargs["json"]' not in (
        dingtalk_markdown_block + wecom_markdown_block
    )


def test_quality_ops_capture_notification_http_success_exact_channel_result_contract():
    channels_test = _read(WORKER_CHANNELS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification HTTP success exact ChannelResult 契约）"
    )

    assert "Notification HTTP success exact ChannelResult 契约" in row
    assert (
        "`tests/unit/test_worker/test_channels.py::TestWebhookChannel::test_custom_method tests/unit/test_worker/test_channels.py::TestWebhookChannel::test_custom_headers tests/unit/test_worker/test_channels.py::TestDingtalkChannel::test_signs_request_when_secret_configured tests/unit/test_worker/test_channels.py::TestDingtalkChannel::test_markdown_message tests/unit/test_worker/test_channels.py::TestWecomChannel::test_markdown_message` 5 passed"
        in row
    )
    assert "channels full 39 passed" in row
    assert "release quality docs contract full 282 passed" in row
    assert "targeted ruff passed" in row
    assert "固定完整 `ChannelResult(success=True)`" in row
    assert "成功分支没有夹带 error" in row
    assert "返回值仍只断言 `result.success is True`" in row
    assert 'ChannelResult(success=True, error="...")' in row
    assert "请求打对了且 success 布尔值为真" in row

    blocks = _notification_channel_http_case_blocks(channels_test)
    webhook_method_block = blocks["webhook_method"]
    webhook_headers_block = blocks["webhook_headers"]
    dingtalk_sign_block = blocks["dingtalk_sign"]
    dingtalk_markdown_block = blocks["dingtalk_markdown"]
    wecom_markdown_block = blocks["wecom_markdown"]

    combined = (
        webhook_method_block
        + webhook_headers_block
        + dingtalk_sign_block
        + dingtalk_markdown_block
        + wecom_markdown_block
    )
    assert combined.count("assert result == ChannelResult(success=True)") == 5
    assert "assert result.success is True" not in combined


def test_quality_ops_capture_notification_channel_failure_exact_result_contract():
    channels_test = _read(WORKER_CHANNELS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Notification channel failure exact ChannelResult 契约）"
    )

    assert "Notification channel failure exact ChannelResult 契约" in row
    assert "notification channel failure selectors 21 passed" in row
    assert "channels full 39 passed" in row
    assert "release quality docs contract full 283 passed" in row
    assert "targeted ruff passed" in row
    assert "Email missing config" in row
    assert "Webhook 非公网解析/URL shape/credentials/HTTP 500/timeout/network/missing URL" in (
        row
    )
    assert "DingTalk timeout/API errcode/HTTP 500/invalid JSON object" in row
    assert "WeCom timeout/API errcode/HTTP 500/invalid JSON object" in row
    assert "exact `ChannelResult`" in row
    assert "错误文案夹带 upstream body、secret、debug hint" in row
    assert "missing/credentials/timeout/API/HTTP 串线" in row
    assert "失败了且错误里有关键词" in row

    for expected in [
        'error="missing required email config fields",',
        'error=f"webhook URL resolves to non-public IP: {resolved_ip}",',
        '"webhook URL must use http/https protocol, got: ftp://",',
        '("https:///notify", "webhook URL has no hostname"),',
        "assert WebhookChannel._validate_webhook_url(url) == expected_error",
        'error="webhook URL must not include credentials",',
        'assert result == ChannelResult(success=False, error="webhook returned HTTP 500")',
        'error=f"webhook timeout after {WebhookChannel.TIMEOUT}s",',
        'error="webhook network error: ConnectError",',
        'assert result == ChannelResult(success=False, error="missing webhook url")',
        'error=f"dingtalk timeout after {DingtalkChannel.TIMEOUT}s",',
        'error="dingtalk API error 310000",',
        'assert result == ChannelResult(success=False, error="dingtalk returned HTTP 500")',
        'error="dingtalk returned invalid JSON object",',
        'error=f"wecom timeout after {WecomChannel.TIMEOUT}s",',
        'assert result == ChannelResult(success=False, error="wecom API error 93000")',
        'assert result == ChannelResult(success=False, error="wecom returned HTTP 500")',
        'error="wecom returned invalid JSON object",',
        'assert result == ChannelResult(success=False, error="unknown channel type: sms")',
    ]:
        assert expected in channels_test

    for old_weak_assertion in [
        "assert expected_error in WebhookChannel._validate_webhook_url(url)",
        'assert "500" in result.error',
        'assert "timeout" in result.error',
        'assert "timeout" in result.error.lower()',
        'assert "310000" in result.error',
        'assert "93000" in result.error',
        'assert "unknown channel type" in result.error.lower()',
        'assert "missing webhook url" in result.error.lower()',
        'assert "missing" in result.error.lower()',
    ]:
        assert old_weak_assertion not in channels_test
