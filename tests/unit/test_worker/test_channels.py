"""Tests for notification channels (email, webhook) and the router."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from email import message_from_string
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qaplatform.worker.notifications.channels import (
    ChannelResult,
    ChannelRouter,
    DingtalkChannel,
    EmailChannel,
    WebhookChannel,
    WecomChannel,
    route_channel,
)

# --------------------------------------------------------------------------- #
# EmailChannel
# --------------------------------------------------------------------------- #


class TestEmailChannel:
    @pytest.mark.asyncio
    async def test_success(self):
        """Mock aiosmtplib / smtplib and verify send parameters."""
        channel = EmailChannel()
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "smtp_password": "pass",
            "from_address": "from@example.com",
            "to_addresses": ["to@example.com"],
            "subject": "Test Subject",
        }

        thread_result = asyncio.get_running_loop().create_future()
        thread_result.set_result(None)
        to_thread_mock = MagicMock(return_value=thread_result)

        with (
            patch(
                "qaplatform.worker.notifications.channels.asyncio.to_thread",
                new=to_thread_mock,
            ) as to_thread,
            patch(
                "qaplatform.worker.notifications.channels.asyncio.wait_for",
                new_callable=AsyncMock,
            ) as wait_for,
        ):
            result = await channel.send(config, "hello")

        assert result == ChannelResult(success=True)
        to_thread.assert_called_once()
        call_args = to_thread.call_args
        assert call_args.args[0] == channel._send_sync
        assert call_args.args[1:7] == (
            "smtp.example.com",
            587,
            "user",
            "pass",
            "from@example.com",
            ["to@example.com"],
        )
        raw_message = message_from_string(call_args.args[7])
        assert raw_message["Subject"] == "Test Subject"
        assert raw_message["From"] == "from@example.com"
        assert raw_message["To"] == "to@example.com"
        assert raw_message.get_payload(decode=True).decode("utf-8") == "hello"
        wait_for.assert_awaited_once_with(thread_result, timeout=EmailChannel.TIMEOUT)

    @pytest.mark.asyncio
    async def test_connection_error_redacts_config_values(self):
        """Mock connection failure and verify useful but safe error text."""
        channel = EmailChannel()
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "mailer",
            "smtp_password": "super-secret-password",
            "from_address": "from@example.com",
            "to_addresses": ["to@example.com"],
        }

        with patch.object(
            EmailChannel,
            "_send_sync",
            side_effect=OSError(
                "smtp://mailer:super-secret-password@smtp.example.com refused; "
                "password=super-secret-password"
            ),
        ):
            result = await channel.send(config, "hello")

        assert result == ChannelResult(
            success=False,
            error="SMTP error: smtp://***@smtp.example.com refused; password=[REDACTED]",
        )
        assert "super-secret-password" not in result.error
        assert "mailer:" not in result.error

    @pytest.mark.asyncio
    async def test_missing_config_returns_error(self):
        channel = EmailChannel()
        result = await channel.send({}, "hello")
        assert result == ChannelResult(
            success=False,
            error="missing required email config fields",
        )

    @pytest.mark.asyncio
    async def test_ssl_port_465(self):
        """Verify SSL path is taken for port 465."""
        channel = EmailChannel()
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "from_address": "from@example.com",
            "to_addresses": ["to@example.com"],
        }

        thread_result = asyncio.get_running_loop().create_future()
        thread_result.set_result(None)
        to_thread_mock = MagicMock(return_value=thread_result)

        with (
            patch(
                "qaplatform.worker.notifications.channels.asyncio.to_thread",
                new=to_thread_mock,
            ) as to_thread,
            patch(
                "qaplatform.worker.notifications.channels.asyncio.wait_for",
                new_callable=AsyncMock,
            ) as wait_for,
        ):
            result = await channel.send(config, "hello")

        assert result == ChannelResult(success=True)
        to_thread.assert_called_once()
        assert to_thread.call_args.args[0] == channel._send_sync
        assert to_thread.call_args.args[1:7] == (
            "smtp.example.com",
            465,
            None,
            "",
            "from@example.com",
            ["to@example.com"],
        )
        wait_for.assert_awaited_once_with(thread_result, timeout=EmailChannel.TIMEOUT)

    @pytest.mark.asyncio
    async def test_smtp_timeout_is_reported(self):
        channel = EmailChannel()
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from_address": "from@example.com",
            "to_addresses": ["to@example.com"],
        }
        thread_result = asyncio.get_running_loop().create_future()
        thread_result.set_result(None)
        to_thread_mock = MagicMock(return_value=thread_result)

        with (
            patch(
                "qaplatform.worker.notifications.channels.asyncio.to_thread",
                new=to_thread_mock,
            ) as to_thread,
            patch(
                "qaplatform.worker.notifications.channels.asyncio.wait_for",
                new_callable=AsyncMock,
                side_effect=asyncio.TimeoutError,
            ) as wait_for,
        ):
            result = await channel.send(config, "hello")

        assert result == ChannelResult(
            success=False,
            error=f"SMTP timeout after {EmailChannel.TIMEOUT}s",
        )
        to_thread.assert_called_once()
        assert to_thread.call_args.args[0] == channel._send_sync
        assert to_thread.call_args.args[1:7] == (
            "smtp.example.com",
            587,
            None,
            "",
            "from@example.com",
            ["to@example.com"],
        )
        wait_for.assert_awaited_once_with(thread_result, timeout=EmailChannel.TIMEOUT)


# --------------------------------------------------------------------------- #
# WebhookChannel
# --------------------------------------------------------------------------- #


class TestWebhookChannel:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "resolved_ip",
        [
            "127.0.0.1",
            "0.0.0.0",
            "fc00::1",
            "fe80::1",
        ],
    )
    async def test_rejects_non_public_resolved_ip_before_http_client(self, resolved_ip):
        channel = WebhookChannel()
        config = {"url": "https://hooks.example.com/notify"}

        with (
            patch(
                "socket.getaddrinfo",
                return_value=[(None, None, None, None, (resolved_ip, 443))],
            ),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient") as client_cls,
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(
            success=False,
            error=f"webhook URL resolves to non-public IP: {resolved_ip}",
        )
        client_cls.assert_not_called()

    @pytest.mark.parametrize(
        ("url", "expected_error"),
        [
            (
                "ftp://hooks.example.com/notify",
                "webhook URL must use http/https protocol, got: ftp://",
            ),
            ("https:///notify", "webhook URL has no hostname"),
        ],
    )
    def test_validate_webhook_url_rejects_unsafe_url_shapes(
        self,
        url,
        expected_error,
    ):
        assert WebhookChannel._validate_webhook_url(url) == expected_error

    @pytest.mark.asyncio
    async def test_rejects_url_credentials_before_dns_or_http_client(self):
        channel = WebhookChannel()
        config = {"url": "https://user:token-123@hooks.example.com/notify"}

        with (
            patch("socket.getaddrinfo") as getaddrinfo,
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient") as client_cls,
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(
            success=False,
            error="webhook URL must not include credentials",
        )
        assert "token-123" not in result.error
        getaddrinfo.assert_not_called()
        client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_success(self):
        """Mock httpx and verify POST request."""
        channel = WebhookChannel()
        config = {"url": "https://hooks.example.com/notify"}

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(WebhookChannel, "_validate_webhook_url", return_value=None),
            patch(
                "qaplatform.worker.notifications.channels.httpx.AsyncClient",
                return_value=mock_client,
            ) as client_cls,
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(success=True)
        client_cls.assert_called_once_with(timeout=WebhookChannel.TIMEOUT)
        mock_client.request.assert_awaited_once()
        call_args = mock_client.request.await_args
        assert call_args.args == ("POST", "https://hooks.example.com/notify")
        assert call_args.kwargs == {
            "json": {"message": "test message"},
            "headers": {},
        }

    @pytest.mark.asyncio
    async def test_error_response(self):
        """Mock 500 response and verify body text is not persisted as error."""
        channel = WebhookChannel()
        config = {"url": "https://hooks.example.com/notify"}

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error token-123 SECabc"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(WebhookChannel, "_validate_webhook_url", return_value=None),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(success=False, error="webhook returned HTTP 500")
        assert "Internal Server Error" not in result.error
        assert "token-123" not in result.error
        assert "SECabc" not in result.error

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Mock timeout and verify error is surfaced."""
        channel = WebhookChannel()
        config = {"url": "https://hooks.example.com/notify"}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(WebhookChannel, "_validate_webhook_url", return_value=None),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(
            success=False,
            error=f"webhook timeout after {WebhookChannel.TIMEOUT}s",
        )

    @pytest.mark.asyncio
    async def test_network_error_does_not_echo_exception_text(self):
        channel = WebhookChannel()
        config = {"url": "https://hooks.example.com/notify"}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(
            side_effect=httpx.ConnectError(
                "connect failed for https://user:token-123@hooks.example.com"
            )
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(WebhookChannel, "_validate_webhook_url", return_value=None),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(
            success=False,
            error="webhook network error: ConnectError",
        )
        assert "token-123" not in result.error
        assert "hooks.example.com" not in result.error

    @pytest.mark.asyncio
    async def test_missing_url_returns_error(self):
        channel = WebhookChannel()
        result = await channel.send({}, "hello")
        assert result == ChannelResult(success=False, error="missing webhook url")

    @pytest.mark.asyncio
    async def test_custom_method(self):
        """Verify custom HTTP method is passed through."""
        channel = WebhookChannel()
        config = {"url": "https://hooks.example.com/notify", "method": "PUT"}

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(WebhookChannel, "_validate_webhook_url", return_value=None),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(success=True)
        mock_client.request.assert_awaited_once()
        call_args = mock_client.request.await_args
        assert call_args.args == ("PUT", "https://hooks.example.com/notify")
        assert call_args.kwargs == {
            "json": {"message": "test message"},
            "headers": {},
        }

    @pytest.mark.asyncio
    async def test_custom_headers(self):
        """Verify custom headers are passed through."""
        channel = WebhookChannel()
        config = {
            "url": "https://hooks.example.com/notify",
            "headers": {"Authorization": "Bearer token123"},
        }

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(WebhookChannel, "_validate_webhook_url", return_value=None),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "test message")

        assert result == ChannelResult(success=True)
        mock_client.request.assert_awaited_once()
        call_args = mock_client.request.await_args
        assert call_args.args == ("POST", "https://hooks.example.com/notify")
        assert call_args.kwargs == {
            "json": {"message": "test message"},
            "headers": {"Authorization": "Bearer token123"},
        }


# --------------------------------------------------------------------------- #
# DingtalkChannel
# --------------------------------------------------------------------------- #


class TestDingtalkChannel:
    @pytest.mark.asyncio
    async def test_success_text_message(self):
        channel = DingtalkChannel()
        config = {"access_token": "token-123"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "qaplatform.worker.notifications.channels.httpx.AsyncClient",
            return_value=mock_client,
        ) as client_cls:
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(success=True)
        client_cls.assert_called_once_with(timeout=DingtalkChannel.TIMEOUT)
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.await_args
        assert call_args.args == (DingtalkChannel.ENDPOINT,)
        assert call_args.kwargs == {
            "params": {"access_token": "token-123"},
            "json": {
                "msgtype": "text",
                "text": {"content": "构建完成"},
            },
        }

    @pytest.mark.asyncio
    async def test_signs_request_when_secret_configured(self):
        channel = DingtalkChannel()
        config = {"access_token": "token-123", "secret": "SECabc"}
        timestamp = 1_700_000_000_123
        string_to_sign = f"{timestamp}\nSECabc".encode("utf-8")
        expected_sign = base64.b64encode(
            hmac.new(b"SECabc", string_to_sign, hashlib.sha256).digest()
        ).decode("utf-8")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("qaplatform.worker.notifications.channels.time.time", return_value=timestamp / 1000),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(success=True)
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.await_args
        assert call_args.args == (DingtalkChannel.ENDPOINT,)
        assert call_args.kwargs == {
            "params": {
                "access_token": "token-123",
                "timestamp": timestamp,
                "sign": expected_sign,
            },
            "json": {
                "msgtype": "text",
                "text": {"content": "构建完成"},
            },
        }

    @pytest.mark.asyncio
    async def test_timeout_returns_failure_without_secret_values(self):
        channel = DingtalkChannel()
        config = {"access_token": "token-123", "secret": "SECabc"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(
            success=False,
            error=f"dingtalk timeout after {DingtalkChannel.TIMEOUT}s",
        )
        assert "token-123" not in result.error
        assert "SECabc" not in result.error

    @pytest.mark.asyncio
    async def test_api_errcode_returns_failure_without_secret_values(self):
        channel = DingtalkChannel()
        config = {"access_token": "token-123", "secret": "SECabc"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errcode": 310000,
            "errmsg": "token-123 keyword missing SECabc",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(
            success=False,
            error="dingtalk API error 310000",
        )
        assert "token-123" not in result.error
        assert "SECabc" not in result.error
        assert "keyword missing" not in result.error

    @pytest.mark.asyncio
    async def test_markdown_message(self):
        channel = DingtalkChannel()
        config = {
            "access_token": "token-123",
            "msgtype": "markdown",
            "title": "流水线通知",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "### 构建完成")

        assert result == ChannelResult(success=True)
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.await_args
        assert call_args.args == (DingtalkChannel.ENDPOINT,)
        assert call_args.kwargs == {
            "params": {"access_token": "token-123"},
            "json": {
                "msgtype": "markdown",
                "markdown": {"title": "流水线通知", "text": "### 构建完成"},
            },
        }

    @pytest.mark.asyncio
    async def test_http_error_status_returns_failure(self):
        channel = DingtalkChannel()
        config = {"access_token": "token-123", "secret": "SECabc"}

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "upstream token-123 failed SECabc"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(success=False, error="dingtalk returned HTTP 500")
        assert "token-123" not in result.error
        assert "SECabc" not in result.error
        assert "upstream" not in result.error

    @pytest.mark.asyncio
    async def test_non_object_json_returns_failure_without_secret_values(self):
        channel = DingtalkChannel()
        config = {"access_token": "token-123", "secret": "SECabc"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["token-123", "SECabc"]

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(
            success=False,
            error="dingtalk returned invalid JSON object",
        )
        assert "token-123" not in result.error
        assert "SECabc" not in result.error


# --------------------------------------------------------------------------- #
# WecomChannel
# --------------------------------------------------------------------------- #


class TestWecomChannel:
    @pytest.mark.asyncio
    async def test_success_text_message(self):
        channel = WecomChannel()
        config = {"webhook_key": "key-123"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "qaplatform.worker.notifications.channels.httpx.AsyncClient",
            return_value=mock_client,
        ) as client_cls:
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(success=True)
        client_cls.assert_called_once_with(timeout=WecomChannel.TIMEOUT)
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.await_args
        assert call_args.args == (WecomChannel.ENDPOINT,)
        assert call_args.kwargs == {
            "params": {"key": "key-123"},
            "json": {
                "msgtype": "text",
                "text": {"content": "构建完成"},
            },
        }

    @pytest.mark.asyncio
    async def test_timeout_returns_failure_without_webhook_key(self):
        channel = WecomChannel()
        config = {"webhook_key": "key-123"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(
            success=False,
            error=f"wecom timeout after {WecomChannel.TIMEOUT}s",
        )
        assert "key-123" not in result.error

    @pytest.mark.asyncio
    async def test_api_errcode_returns_failure_without_webhook_key(self):
        channel = WecomChannel()
        config = {"webhook_key": "key-123"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errcode": 93000,
            "errmsg": "invalid key-123",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(success=False, error="wecom API error 93000")
        assert "key-123" not in result.error
        assert "invalid" not in result.error

    @pytest.mark.asyncio
    async def test_markdown_message(self):
        channel = WecomChannel()
        config = {
            "webhook_key": "key-123",
            "msgtype": "markdown",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "### 构建完成")

        assert result == ChannelResult(success=True)
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.await_args
        assert call_args.args == (WecomChannel.ENDPOINT,)
        assert call_args.kwargs == {
            "params": {"key": "key-123"},
            "json": {
                "msgtype": "markdown",
                "markdown": {"content": "### 构建完成"},
            },
        }

    @pytest.mark.asyncio
    async def test_http_error_status_returns_failure_without_webhook_key(self):
        channel = WecomChannel()
        config = {"webhook_key": "key-123"}

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "upstream key-123 failed"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(success=False, error="wecom returned HTTP 500")
        assert "key-123" not in result.error
        assert "upstream" not in result.error

    @pytest.mark.asyncio
    async def test_non_object_json_returns_failure_without_webhook_key(self):
        channel = WecomChannel()
        config = {"webhook_key": "key-123"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["key-123"]

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result == ChannelResult(
            success=False,
            error="wecom returned invalid JSON object",
        )
        assert "key-123" not in result.error


# --------------------------------------------------------------------------- #
# ChannelRouter
# --------------------------------------------------------------------------- #


class TestChannelRouter:
    @pytest.mark.asyncio
    async def test_route_email(self):
        """Verify routing to email channel."""
        router = ChannelRouter()
        email_channel = MagicMock()
        email_channel.send = AsyncMock(return_value=ChannelResult(success=True))
        router._channels = {"email": email_channel}

        config = {"smtp_host": "x"}
        result = await router.route_channel("email", config, "msg")
        assert result == ChannelResult(success=True)
        email_channel.send.assert_awaited_once_with(config, "msg")

    @pytest.mark.asyncio
    async def test_route_webhook(self):
        """Verify routing to webhook channel."""
        router = ChannelRouter()
        wh_channel = MagicMock()
        wh_channel.send = AsyncMock(return_value=ChannelResult(success=True))
        router._channels = {"webhook": wh_channel}

        config = {"url": "https://x"}
        result = await router.route_channel("webhook", config, "msg")
        assert result == ChannelResult(success=True)
        wh_channel.send.assert_awaited_once_with(config, "msg")

    @pytest.mark.asyncio
    async def test_route_dingtalk(self):
        """Verify routing to dingtalk channel."""
        router = ChannelRouter()
        dt_channel = MagicMock()
        dt_channel.send = AsyncMock(return_value=ChannelResult(success=True))
        router._channels = {"dingtalk": dt_channel}

        config = {"access_token": "x"}
        result = await router.route_channel("dingtalk", config, "msg")
        assert result == ChannelResult(success=True)
        dt_channel.send.assert_awaited_once_with(config, "msg")

    @pytest.mark.asyncio
    async def test_route_wecom(self):
        """Verify routing to wecom channel."""
        router = ChannelRouter()
        wecom_channel = MagicMock()
        wecom_channel.send = AsyncMock(return_value=ChannelResult(success=True))
        router._channels = {"wecom": wecom_channel}

        config = {"webhook_key": "x"}
        result = await router.route_channel("wecom", config, "msg")
        assert result == ChannelResult(success=True)
        wecom_channel.send.assert_awaited_once_with(config, "msg")

    @pytest.mark.asyncio
    async def test_route_known_channel_propagates_failure_result(self):
        router = ChannelRouter()
        channel = MagicMock()
        channel_result = ChannelResult(success=False, error="downstream failed")
        channel.send = AsyncMock(return_value=channel_result)
        router._channels = {"webhook": channel}

        config = {"url": "https://x"}
        result = await router.route_channel("webhook", config, "msg")

        assert result == channel_result
        channel.send.assert_awaited_once_with(config, "msg")

    @pytest.mark.asyncio
    async def test_route_unknown(self):
        """Unknown channel type returns error, does not raise."""
        router = ChannelRouter()
        result = await router.route_channel("sms", {}, "msg")
        assert result == ChannelResult(success=False, error="unknown channel type: sms")


# --------------------------------------------------------------------------- #
# Module-level convenience function
# --------------------------------------------------------------------------- #


class TestRouteChannelFunction:
    @pytest.mark.asyncio
    async def test_delegates_to_router(self):
        """Module-level route_channel delegates to the singleton router."""
        mock_result = ChannelResult(success=False, error="router failed")
        with patch(
            "qaplatform.worker.notifications.channels._router.route_channel",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_route:
            result = await route_channel("email", {}, "msg")

        assert result == mock_result
        mock_route.assert_awaited_once_with("email", {}, "msg")
