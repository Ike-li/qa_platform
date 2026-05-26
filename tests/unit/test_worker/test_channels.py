"""Tests for notification channels (email, webhook) and the router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qaplatform.worker.notifications.channels import (
    ChannelResult,
    ChannelRouter,
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
