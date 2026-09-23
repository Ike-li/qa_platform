"""Unit tests for SecurityHeadersMiddleware."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qaplatform.api.middleware.security_headers import SecurityHeadersMiddleware

EXPECTED_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}

EXPECTED_HSTS = "max-age=31536000; includeSubDomains"


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


class TestSecurityHeaders:
    """Security headers must be exact, not substring smoke checks."""

    @pytest.mark.asyncio
    async def test_exact_headers_when_hsts_disabled(self):
        headers = await _dispatch(_make_middleware(enable_hsts=False))

        assert headers == EXPECTED_SECURITY_HEADERS

    @pytest.mark.asyncio
    async def test_exact_headers_when_hsts_enabled(self):
        headers = await _dispatch(_make_middleware(enable_hsts=True))

        assert headers == {
            **EXPECTED_SECURITY_HEADERS,
            "Strict-Transport-Security": EXPECTED_HSTS,
        }

    @pytest.mark.asyncio
    async def test_responses_tell_search_engines_not_to_index(self):
        """自托管实例不应被搜索引擎收录。

        报告分享链接无需登录即可访问，一旦被贴到公开页面，爬虫就能顺着链接
        把测试结果收进索引。前端页面由 index.html 的 robots meta 覆盖，
        API 响应（含 JSON）只能靠响应头。
        """
        headers = await _dispatch(_make_middleware())

        assert headers["X-Robots-Tag"] == "noindex, nofollow"
