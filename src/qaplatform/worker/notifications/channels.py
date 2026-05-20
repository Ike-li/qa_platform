"""Real notification channels: email (SMTP) and webhook (HTTP)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.text import MIMEText

import httpx

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
            return ChannelResult(success=False, error=f"SMTP error: {exc}")

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
        from urllib.parse import urlparse
        import ipaddress, socket

        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            return f"webhook URL must use http/https protocol, got: {parsed.scheme}://"
        if not parsed.hostname:
            return "webhook URL has no hostname"

        private_cidrs = [
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("169.254.0.0/16"),
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("::1/128"),
        ]
        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
            for family, _, _, _, sockaddr in infos:
                ip = ipaddress.ip_address(sockaddr[0])
                for cidr in private_cidrs:
                    if ip in cidr:
                        return f"webhook URL resolves to private IP: {ip}"
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
                        error=f"webhook returned {response.status_code}: {response.text[:200]}",
                    )
        except httpx.TimeoutException:
            return ChannelResult(success=False, error=f"webhook timeout after {self.TIMEOUT}s")
        except httpx.HTTPError as exc:
            return ChannelResult(success=False, error=f"webhook network error: {exc}")

        return ChannelResult(success=True)


# -- Router ------------------------------------------------------------------ #


class ChannelRouter:
    """Route a notification to the appropriate channel implementation."""

    _channels = {
        "email": EmailChannel(),
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
