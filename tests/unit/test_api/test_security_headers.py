"""Unit tests for SecurityHeadersMiddleware."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qaplatform.api.middleware.security_headers import SecurityHeadersMiddleware


def _make_settings(enable_hsts: bool = False) -> SimpleNamespace:
    return SimpleNamespace(enable_hsts=enable_hsts)


def _make_middleware(enable_hsts: bool = False) -> SecurityHeadersMiddleware:
    app = MagicMock()
    settings = _make_settings(enable_hsts)
    mw = SecurityHeadersMiddleware.__new__(SecurityHeadersMiddleware)
    mw.settings = settings
    mw.app = app
    return mw


async def _dispatch(mw: SecurityHeadersMiddleware, path: str = "/") -> dict[str, str]:
    """Run dispatch and return the response headers as a plain dict."""
    mock_response = MagicMock()
    mock_response.headers = {}

    async def call_next(request):
        return mock_response

    req = SimpleNamespace()
    resp = await mw.dispatch(req, call_next)
    return dict(resp.headers)


class TestSecurityHeadersPresent:
    """All required security headers must be set on every response."""

    @pytest.mark.asyncio
    async def test_x_content_type_options(self):
        headers = await _dispatch(_make_middleware())
        assert headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self):
        headers = await _dispatch(_make_middleware())
        assert headers["X-Frame-Options"] == "DENY"

    @pytest.mark.asyncio
    async def test_x_xss_protection(self):
        headers = await _dispatch(_make_middleware())
        assert headers["X-XSS-Protection"] == "0"

    @pytest.mark.asyncio
    async def test_referrer_policy(self):
        headers = await _dispatch(_make_middleware())
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy(self):
        headers = await _dispatch(_make_middleware())
        assert headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"

    @pytest.mark.asyncio
    async def test_content_security_policy(self):
        headers = await _dispatch(_make_middleware())
        expected = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        assert headers["Content-Security-Policy"] == expected


class TestCSPDirectives:
    """Verify individual CSP directives are present in the header value."""

    @pytest.mark.asyncio
    async def test_default_src_self(self):
        headers = await _dispatch(_make_middleware())
        assert "default-src 'self'" in headers["Content-Security-Policy"]

    @pytest.mark.asyncio
    async def test_script_src_self(self):
        headers = await _dispatch(_make_middleware())
        assert "script-src 'self'" in headers["Content-Security-Policy"]

    @pytest.mark.asyncio
    async def test_style_src_self_unsafe_inline(self):
        headers = await _dispatch(_make_middleware())
        assert "style-src 'self' 'unsafe-inline'" in headers["Content-Security-Policy"]

    @pytest.mark.asyncio
    async def test_img_src_self_data(self):
        headers = await _dispatch(_make_middleware())
        assert "img-src 'self' data:" in headers["Content-Security-Policy"]

    @pytest.mark.asyncio
    async def test_connect_src_self(self):
        headers = await _dispatch(_make_middleware())
        assert "connect-src 'self'" in headers["Content-Security-Policy"]

    @pytest.mark.asyncio
    async def test_frame_ancestors_none(self):
        headers = await _dispatch(_make_middleware())
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


class TestHSTS:
    """HSTS header controlled by enable_hsts setting."""

    @pytest.mark.asyncio
    async def test_hsts_present_when_enabled(self):
        headers = await _dispatch(_make_middleware(enable_hsts=True))
        assert "Strict-Transport-Security" in headers
        assert headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"

    @pytest.mark.asyncio
    async def test_hsts_absent_when_disabled(self):
        headers = await _dispatch(_make_middleware(enable_hsts=False))
        assert "Strict-Transport-Security" not in headers
