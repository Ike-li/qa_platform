"""Real notification channels: email (SMTP) and webhook (HTTP)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.mime.text import MIMEText

import httpx

from qaplatform.engine.redact import redact_sensitive_text

log = logging.getLogger(__name__)

# -- Channel result ---------------------------------------------------------- #


@dataclass(slots=True)
class ChannelResult:
    """Outcome of a single channel send attempt."""

    success: bool
    error: str | None = None


# -- Email channel ----------------------------------------------------------- #


class EmailChannel:
    """Send notification emails via SMTP (TLS on 587 or SSL on 465).

    Config keys:
        smtp_host, smtp_port, smtp_user, smtp_password,
        from_address, to_addresses (list[str])
    """

    TIMEOUT = 30  # seconds

    async def send(self, config: dict, message: str) -> ChannelResult:
        host = config.get("smtp_host")
        port = int(config.get("smtp_port", 587))
        user = config.get("smtp_user")
        password = config.get("smtp_password", "")
        from_addr = config.get("from_address")
        to_addrs = config.get("to_addresses", [])

        if not all([host, from_addr, to_addrs]):
            return ChannelResult(success=False, error="missing required email config fields")

        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = config.get("subject", "QA Platform Notification")
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)

        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._send_sync, host, port, user, password, from_addr, to_addrs, msg.as_string(),
                ),
                timeout=self.TIMEOUT,
            )
        except asyncio.TimeoutError:
            return ChannelResult(success=False, error=f"SMTP timeout after {self.TIMEOUT}s")
        except smtplib.SMTPAuthenticationError:
            return ChannelResult(success=False, error="SMTP authentication failed")
        except (smtplib.SMTPException, OSError) as exc:
            safe_error = redact_sensitive_text(
                str(exc),
                {"smtp_password": password},
            )
            return ChannelResult(success=False, error=f"SMTP error: {safe_error}")

        return ChannelResult(success=True)

    # -- synchronous helper (runs in thread) ---------------------------------- #

    @staticmethod
    def _send_sync(
        host: str,
        port: int,
        user: str | None,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        raw_message: str,
    ) -> None:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=EmailChannel.TIMEOUT) as server:
                if user:
                    server.login(user, password)
                server.sendmail(from_addr, to_addrs, raw_message)
        else:
            with smtplib.SMTP(host, port, timeout=EmailChannel.TIMEOUT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if user:
                    server.login(user, password)
                server.sendmail(from_addr, to_addrs, raw_message)


# -- Webhook channel --------------------------------------------------------- #


class WebhookChannel:
    """Send notification payloads via HTTP POST (or custom method).

    Config keys:
        url, headers (optional dict), method (default POST)
    """

    TIMEOUT = 30  # seconds

    @staticmethod
    def _validate_webhook_url(url: str) -> str | None:
        """Validate webhook URL to prevent SSRF. Returns error message or None."""
        import ipaddress
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            return f"webhook URL must use http/https protocol, got: {parsed.scheme}://"
        if not parsed.hostname:
            return "webhook URL has no hostname"
        if parsed.username is not None or parsed.password is not None:
            return "webhook URL must not include credentials"

        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
            for _, _, _, _, sockaddr in infos:
                ip = ipaddress.ip_address(sockaddr[0])
                if not ip.is_global:
                    return f"webhook URL resolves to non-public IP: {ip}"
        except socket.gaierror:
            return f"cannot resolve webhook hostname: {parsed.hostname}"
        return None

    async def send(self, config: dict, message: str) -> ChannelResult:
        url = config.get("url")
        if not url:
            return ChannelResult(success=False, error="missing webhook url")

        ssrf_error = self._validate_webhook_url(url)
        if ssrf_error:
            return ChannelResult(success=False, error=ssrf_error)

        headers = config.get("headers", {})
        method = config.get("method", "POST").upper()
        payload = {"message": message}

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.request(method, url, json=payload, headers=headers)
                if response.status_code >= 400:
                    return ChannelResult(
                        success=False,
                        error=f"webhook returned HTTP {response.status_code}",
                    )
        except httpx.TimeoutException:
            return ChannelResult(success=False, error=f"webhook timeout after {self.TIMEOUT}s")
        except httpx.HTTPError as exc:
            return ChannelResult(
                success=False,
                error=f"webhook network error: {exc.__class__.__name__}",
            )

        return ChannelResult(success=True)


# -- DingTalk channel ------------------------------------------------------- #


class DingtalkChannel:
    """Send messages through DingTalk custom robot webhooks.

    Config keys:
        access_token, secret (optional), msgtype (text/markdown)
    """

    ENDPOINT = "https://oapi.dingtalk.com/robot/send"
    TIMEOUT = 10  # seconds

    @staticmethod
    def _sign(secret: str, timestamp: int) -> str:
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    @classmethod
    def _build_params(cls, access_token: str, secret: str | None) -> dict[str, str | int]:
        params: dict[str, str | int] = {"access_token": access_token}
        if secret:
            timestamp = int(time.time() * 1000)
            params["timestamp"] = timestamp
            params["sign"] = cls._sign(secret, timestamp)
        return params

    @staticmethod
    def _build_payload(msgtype: str, message: str, config: dict) -> dict:
        if msgtype == "text":
            return {"msgtype": "text", "text": {"content": message}}
        if msgtype == "markdown":
            return {
                "msgtype": "markdown",
                "markdown": {
                    "title": config.get("title", "QA Platform Notification"),
                    "text": message,
                },
            }
        raise ValueError(f"unsupported dingtalk msgtype: {msgtype}")

    async def send(self, config: dict, message: str) -> ChannelResult:
        access_token = config.get("access_token")
        if not access_token:
            return ChannelResult(success=False, error="missing dingtalk access_token")

        secret = config.get("secret")
        msgtype = config.get("msgtype", "text")
        try:
            payload = self._build_payload(msgtype, message, config)
        except ValueError as exc:
            return ChannelResult(success=False, error=str(exc))

        params = self._build_params(access_token, secret)
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.post(self.ENDPOINT, params=params, json=payload)
        except httpx.TimeoutException:
            return ChannelResult(success=False, error=f"dingtalk timeout after {self.TIMEOUT}s")
        except httpx.HTTPError as exc:
            return ChannelResult(
                success=False,
                error=f"dingtalk network error: {exc.__class__.__name__}",
            )

        if response.status_code >= 400:
            return ChannelResult(success=False, error=f"dingtalk returned HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError:
            return ChannelResult(success=False, error="dingtalk returned invalid JSON")
        if not isinstance(body, dict):
            return ChannelResult(success=False, error="dingtalk returned invalid JSON object")

        errcode = body.get("errcode")
        if errcode != 0:
            return ChannelResult(success=False, error=f"dingtalk API error {errcode}")

        return ChannelResult(success=True)


# -- WeCom channel ---------------------------------------------------------- #


class WecomChannel:
    """Send messages through WeCom group robot webhooks.

    Config keys:
        webhook_key, msgtype (text/markdown)
    """

    ENDPOINT = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    TIMEOUT = 10  # seconds

    @staticmethod
    def _build_payload(msgtype: str, message: str) -> dict:
        if msgtype == "text":
            return {"msgtype": "text", "text": {"content": message}}
        if msgtype == "markdown":
            return {"msgtype": "markdown", "markdown": {"content": message}}
        raise ValueError(f"unsupported wecom msgtype: {msgtype}")

    async def send(self, config: dict, message: str) -> ChannelResult:
        webhook_key = config.get("webhook_key")
        if not webhook_key:
            return ChannelResult(success=False, error="missing wecom webhook_key")

        msgtype = config.get("msgtype", "text")
        try:
            payload = self._build_payload(msgtype, message)
        except ValueError as exc:
            return ChannelResult(success=False, error=str(exc))

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.post(self.ENDPOINT, params={"key": webhook_key}, json=payload)
        except httpx.TimeoutException:
            return ChannelResult(success=False, error=f"wecom timeout after {self.TIMEOUT}s")
        except httpx.HTTPError as exc:
            return ChannelResult(
                success=False,
                error=f"wecom network error: {exc.__class__.__name__}",
            )

        if response.status_code >= 400:
            return ChannelResult(success=False, error=f"wecom returned HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError:
            return ChannelResult(success=False, error="wecom returned invalid JSON")
        if not isinstance(body, dict):
            return ChannelResult(success=False, error="wecom returned invalid JSON object")

        errcode = body.get("errcode")
        if errcode != 0:
            return ChannelResult(success=False, error=f"wecom API error {errcode}")

        return ChannelResult(success=True)


# -- Router ------------------------------------------------------------------ #


class ChannelRouter:
    """Route a notification to the appropriate channel implementation."""

    _channels = {
        "dingtalk": DingtalkChannel(),
        "email": EmailChannel(),
        "wecom": WecomChannel(),
        "webhook": WebhookChannel(),
    }

    async def route_channel(
        self, channel_type: str, channel_config: dict, message: str,
    ) -> ChannelResult:
        channel = self._channels.get(channel_type)
        if channel is None:
            return ChannelResult(success=False, error=f"unknown channel type: {channel_type}")
        return await channel.send(channel_config, message)


# Module-level singleton for convenience
_router = ChannelRouter()


async def route_channel(channel_type: str, channel_config: dict, message: str) -> ChannelResult:
    """Module-level convenience wrapper around the default router."""
    return await _router.route_channel(channel_type, channel_config, message)
