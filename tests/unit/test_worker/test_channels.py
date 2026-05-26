"""Tests for notification channels (email, webhook) and the router."""

from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qaplatform.worker.notifications.channels import (
    ChannelResult,
    ChannelRouter,
    DingtalkChannel,
    EmailChannel,
    WebhookChannel,
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

        with patch.object(EmailChannel, "_send_sync") as mock_send:
            result = await channel.send(config, "hello")

        assert result.success is True
        assert result.error is None
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args.args[0] == "smtp.example.com"
        assert call_args.args[1] == 587
        assert call_args.args[3] == "pass"
        assert call_args.args[4] == "from@example.com"
        assert call_args.args[5] == ["to@example.com"]

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Mock connection failure and verify error is surfaced."""
        channel = EmailChannel()
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from_address": "from@example.com",
            "to_addresses": ["to@example.com"],
        }

        with patch.object(
            EmailChannel, "_send_sync", side_effect=OSError("Connection refused"),
        ):
            result = await channel.send(config, "hello")

        assert result.success is False
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_missing_config_returns_error(self):
        channel = EmailChannel()
        result = await channel.send({}, "hello")
        assert result.success is False
        assert "missing" in result.error.lower()

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

        with patch.object(EmailChannel, "_send_sync") as mock_send:
            await channel.send(config, "hello")

        assert mock_send.call_args.args[1] == 465


# --------------------------------------------------------------------------- #
# WebhookChannel
# --------------------------------------------------------------------------- #


class TestWebhookChannel:
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
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "test message")

        assert result.success is True
        mock_client.request.assert_awaited_once()
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.args[0] == "POST"
        assert call_kwargs.args[1] == "https://hooks.example.com/notify"
        assert call_kwargs.kwargs["json"] == {"message": "test message"}

    @pytest.mark.asyncio
    async def test_error_response(self):
        """Mock 500 response and verify error is surfaced."""
        channel = WebhookChannel()
        config = {"url": "https://hooks.example.com/notify"}

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(WebhookChannel, "_validate_webhook_url", return_value=None),
            patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await channel.send(config, "test message")

        assert result.success is False
        assert "500" in result.error

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

        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_url_returns_error(self):
        channel = WebhookChannel()
        result = await channel.send({}, "hello")
        assert result.success is False
        assert "missing webhook url" in result.error.lower()

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

        assert result.success is True
        call_args = mock_client.request.call_args
        assert call_args.args[0] == "PUT"

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

        assert result.success is True
        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["headers"] == {"Authorization": "Bearer token123"}


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

        with patch("qaplatform.worker.notifications.channels.httpx.AsyncClient", return_value=mock_client):
            result = await channel.send(config, "构建完成")

        assert result.success is True
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://oapi.dingtalk.com/robot/send"
        assert call_args.kwargs["params"] == {"access_token": "token-123"}
        assert call_args.kwargs["json"] == {
            "msgtype": "text",
            "text": {"content": "构建完成"},
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

        assert result.success is True
        params = mock_client.post.call_args.kwargs["params"]
        assert params["access_token"] == "token-123"
        assert params["timestamp"] == timestamp
        assert params["sign"] == expected_sign

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

        assert result.success is False
        assert "timeout" in result.error
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

        assert result.success is False
        assert "310000" in result.error
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

        assert result.success is True
        assert mock_client.post.call_args.kwargs["json"] == {
            "msgtype": "markdown",
            "markdown": {"title": "流水线通知", "text": "### 构建完成"},
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

        assert result.success is False
        assert "500" in result.error
        assert "token-123" not in result.error
        assert "SECabc" not in result.error
        assert "upstream" not in result.error


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

        result = await router.route_channel("email", {"smtp_host": "x"}, "msg")
        assert result.success is True
        email_channel.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_webhook(self):
        """Verify routing to webhook channel."""
        router = ChannelRouter()
        wh_channel = MagicMock()
        wh_channel.send = AsyncMock(return_value=ChannelResult(success=True))
        router._channels = {"webhook": wh_channel}

        result = await router.route_channel("webhook", {"url": "https://x"}, "msg")
        assert result.success is True
        wh_channel.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_dingtalk(self):
        """Verify routing to dingtalk channel."""
        router = ChannelRouter()
        dt_channel = MagicMock()
        dt_channel.send = AsyncMock(return_value=ChannelResult(success=True))
        router._channels = {"dingtalk": dt_channel}

        result = await router.route_channel("dingtalk", {"access_token": "x"}, "msg")
        assert result.success is True
        dt_channel.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_unknown(self):
        """Unknown channel type returns error, does not raise."""
        router = ChannelRouter()
        result = await router.route_channel("sms", {}, "msg")
        assert result.success is False
        assert "unknown channel type" in result.error.lower()


# --------------------------------------------------------------------------- #
# Module-level convenience function
# --------------------------------------------------------------------------- #


class TestRouteChannelFunction:
    @pytest.mark.asyncio
    async def test_delegates_to_router(self):
        """Module-level route_channel delegates to the singleton router."""
        mock_result = ChannelResult(success=True)
        with patch(
            "qaplatform.worker.notifications.channels._router.route_channel",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_route:
            result = await route_channel("email", {}, "msg")

        assert result.success is True
        mock_route.assert_awaited_once_with("email", {}, "msg")
