"""Unit tests for rate_limit middleware — P1-K.

Covers:
- _resolve_client_ip: no trusted proxies, single trusted proxy, multi-hop
- _resolve_bucket_key: unauthenticated (IP bucket) vs Bearer token (hash bucket)
- RateLimitMiddleware.dispatch: per-token isolation (different tokens don't
  exhaust each other's quota)
"""
from __future__ import annotations

import hashlib
import ipaddress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qaplatform.api.middleware.rate_limit import (
    _parse_trusted_nets,
    _resolve_bucket_key,
    _resolve_client_ip,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(
    client_host: str = "1.2.3.4",
    xff: str | None = None,
    authorization: str | None = None,
    path: str = "/api/v1/runs",
) -> SimpleNamespace:
    """Build a minimal fake Request object."""
    headers: dict[str, str] = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    if authorization is not None:
        headers["authorization"] = authorization

    return SimpleNamespace(
        client=SimpleNamespace(host=client_host),
        headers=headers,
        url=SimpleNamespace(path=path),
        app=SimpleNamespace(state=SimpleNamespace(container=None)),
    )


def _nets(cidrs: list[str]):
    return _parse_trusted_nets(cidrs)


# ---------------------------------------------------------------------------
# _resolve_client_ip
# ---------------------------------------------------------------------------

class TestResolveClientIp:
    def test_no_trusted_proxies_ignores_xff(self):
        """Without trusted_proxies, X-Forwarded-For must be ignored."""
        req = _make_request(client_host="203.0.113.1", xff="1.2.3.4")
        ip = _resolve_client_ip(req, trusted_nets=[])
        assert ip == "203.0.113.1"

    def test_no_trusted_proxies_no_xff(self):
        req = _make_request(client_host="203.0.113.1")
        ip = _resolve_client_ip(req, trusted_nets=[])
        assert ip == "203.0.113.1"

    def test_untrusted_peer_ignores_xff(self):
        """Even with trusted_proxies configured, an untrusted direct peer
        means we use client.host directly."""
        nets = _nets(["10.0.0.0/8"])
        req = _make_request(client_host="203.0.113.1", xff="1.2.3.4")
        ip = _resolve_client_ip(req, trusted_nets=nets)
        assert ip == "203.0.113.1"

    def test_trusted_peer_single_hop(self):
        """Trusted peer + XFF with one real client IP → return that IP."""
        nets = _nets(["10.0.0.0/8"])
        req = _make_request(client_host="10.0.0.5", xff="1.2.3.4, 10.0.0.5")
        ip = _resolve_client_ip(req, trusted_nets=nets)
        assert ip == "1.2.3.4"

    def test_trusted_peer_multi_hop(self):
        """Multiple trusted hops in XFF — walk right-to-left, skip all
        trusted addresses, return the first non-trusted one."""
        nets = _nets(["10.0.0.0/8"])
        req = _make_request(
            client_host="10.0.0.6",
            xff="1.2.3.4, 10.0.0.5, 10.0.0.6",
        )
        ip = _resolve_client_ip(req, trusted_nets=nets)
        assert ip == "1.2.3.4"

    def test_all_hops_trusted_falls_back_to_client_host(self):
        """If every XFF entry is trusted, fall back to client.host."""
        nets = _nets(["10.0.0.0/8"])
        req = _make_request(
            client_host="10.0.0.1",
            xff="10.0.0.2, 10.0.0.3",
        )
        ip = _resolve_client_ip(req, trusted_nets=nets)
        assert ip == "10.0.0.1"

    def test_malformed_xff_segment_skipped(self):
        """A non-IP segment in XFF is skipped; the next valid non-trusted
        address is returned."""
        nets = _nets(["10.0.0.0/8"])
        req = _make_request(
            client_host="10.0.0.1",
            xff="1.2.3.4, not-an-ip, 10.0.0.1",
        )
        ip = _resolve_client_ip(req, trusted_nets=nets)
        assert ip == "1.2.3.4"

    def test_no_client_returns_unknown(self):
        """request.client is None → 'unknown'."""
        nets = _nets(["10.0.0.0/8"])
        req = _make_request(client_host="10.0.0.1")
        req.client = None
        ip = _resolve_client_ip(req, trusted_nets=nets)
        assert ip == "unknown"

    def test_ipv6_trusted_proxy(self):
        """IPv6 addresses in trusted_proxies and XFF are handled correctly."""
        nets = _nets(["fc00::/7"])
        req = _make_request(
            client_host="fc00::1",
            xff="2001:db8::1, fc00::1",
        )
        ip = _resolve_client_ip(req, trusted_nets=nets)
        assert ip == "2001:db8::1"


# ---------------------------------------------------------------------------
# _resolve_bucket_key
# ---------------------------------------------------------------------------

class TestResolveBucketKey:
    def test_no_auth_uses_ip_bucket(self):
        req = _make_request(client_host="1.2.3.4")
        bucket = _resolve_bucket_key(req, ip="1.2.3.4")
        assert bucket == "ip:1.2.3.4"

    def test_bearer_token_uses_hash_bucket(self):
        token = "mytoken123"
        req = _make_request(authorization=f"Bearer {token}")
        bucket = _resolve_bucket_key(req, ip="1.2.3.4")

        expected_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        assert bucket == f"token:{expected_hash}"

    def test_bearer_token_bucket_does_not_contain_raw_token(self):
        token = "supersecrettoken"
        req = _make_request(authorization=f"Bearer {token}")
        bucket = _resolve_bucket_key(req, ip="1.2.3.4")
        assert token not in bucket

    def test_bearer_case_insensitive(self):
        token = "mytoken"
        req_lower = _make_request(authorization=f"bearer {token}")
        req_upper = _make_request(authorization=f"BEARER {token}")
        assert _resolve_bucket_key(req_lower, ip="x") == _resolve_bucket_key(req_upper, ip="x")

    def test_different_tokens_produce_different_buckets(self):
        req_a = _make_request(authorization="Bearer tokenA")
        req_b = _make_request(authorization="Bearer tokenB")
        assert _resolve_bucket_key(req_a, ip="1.2.3.4") != _resolve_bucket_key(req_b, ip="1.2.3.4")

    def test_same_token_same_bucket_regardless_of_ip(self):
        token = "sharedtoken"
        req_a = _make_request(client_host="1.1.1.1", authorization=f"Bearer {token}")
        req_b = _make_request(client_host="2.2.2.2", authorization=f"Bearer {token}")
        assert _resolve_bucket_key(req_a, ip="1.1.1.1") == _resolve_bucket_key(req_b, ip="2.2.2.2")


# ---------------------------------------------------------------------------
# RateLimitMiddleware.dispatch — per-token isolation
# ---------------------------------------------------------------------------

class TestRateLimitMiddlewareDispatch:
    """Verify that two different tokens don't exhaust each other's quota,
    and that a third distinct token can still pass when the first two are
    at their limit."""

    def _make_redis_mock(self, counts: dict[str, int]):
        """Return an async Redis mock whose pipeline returns a configurable
        request count per key.  counts maps key-substring → count."""

        async def fake_execute(pipe_self=None):
            # The key is set via zadd; we stored it on the pipe mock
            key = getattr(fake_pipe, "_last_key", "")
            for substr, count in counts.items():
                if substr in key:
                    return [None, None, count, None]
            return [None, None, 0, None]

        fake_pipe = MagicMock()
        fake_pipe.zremrangebyscore = MagicMock(return_value=fake_pipe)
        fake_pipe.zadd = MagicMock(side_effect=lambda k, v: setattr(fake_pipe, "_last_key", k) or fake_pipe)
        fake_pipe.zcard = MagicMock(return_value=fake_pipe)
        fake_pipe.expire = MagicMock(return_value=fake_pipe)
        fake_pipe.execute = AsyncMock(side_effect=fake_execute)

        redis = MagicMock()
        redis.pipeline = MagicMock(return_value=fake_pipe)
        return redis

    def _make_middleware(self, redis_mock, trusted_proxies=None):
        from qaplatform.api.middleware.rate_limit import RateLimitMiddleware
        from qaplatform.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://u:p@localhost/db",
            redis_url="redis://localhost:6379/0",
            s3_endpoint="http://localhost:9000",
            s3_access_key="key",
            s3_secret_key="secret",
            jwt_secret="a" * 32,
            encryption_key="0" * 64,
            rate_limit_per_minute=5,
            rate_limit_window_seconds=60,
            trusted_proxies=trusted_proxies or [],
        )
        app = MagicMock()
        mw = RateLimitMiddleware.__new__(RateLimitMiddleware)
        mw.settings = settings
        mw.redis = redis_mock
        from qaplatform.api.middleware.rate_limit import _parse_trusted_nets
        mw._trusted_nets = _parse_trusted_nets(settings.trusted_proxies)
        return mw

    @pytest.mark.asyncio
    async def test_different_tokens_independent_quotas(self):
        """Token A at limit (count=6 > 5) must be blocked; Token B (count=1)
        must still pass through."""
        token_a = "aaaa"
        token_b = "bbbb"
        hash_a = hashlib.sha256(token_a.encode()).hexdigest()[:16]
        hash_b = hashlib.sha256(token_b.encode()).hexdigest()[:16]

        redis = self._make_redis_mock({hash_a: 6, hash_b: 1})
        mw = self._make_middleware(redis)

        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        req_a = _make_request(authorization=f"Bearer {token_a}")
        req_b = _make_request(authorization=f"Bearer {token_b}")

        resp_a = await mw.dispatch(req_a, call_next)
        resp_b = await mw.dispatch(req_b, call_next)

        assert resp_a.status_code == 429
        assert resp_b.status_code == 200

    @pytest.mark.asyncio
    async def test_third_token_passes_when_others_exhausted(self):
        """Two tokens at limit; a third distinct token (count=0) still passes."""
        token_c = "cccc"
        hash_c = hashlib.sha256(token_c.encode()).hexdigest()[:16]

        # hash_c has count 0 → should pass
        redis = self._make_redis_mock({hash_c: 0})
        mw = self._make_middleware(redis)

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        req_c = _make_request(authorization=f"Bearer {token_c}")
        resp_c = await mw.dispatch(req_c, call_next)
        assert resp_c.status_code == 200

    @pytest.mark.asyncio
    async def test_no_trusted_proxy_xff_ignored_in_key(self):
        """Without trusted_proxies, XFF is ignored; bucket key uses client.host."""
        redis = self._make_redis_mock({"ip:203.0.113.1": 0})
        mw = self._make_middleware(redis, trusted_proxies=[])

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        req = _make_request(client_host="203.0.113.1", xff="1.2.3.4")
        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 200
        # Verify call_next was called (not rate-limited)
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_endpoint_uses_strict_limit(self):
        """P1-3: /auth/register must walk the same strict bucket as login/token,
        otherwise self-service tenant creation can be flooded."""
        # Simulate a request to /auth/register with count=6 (exceeds strict limit of 5)
        redis = self._make_redis_mock({"/auth/register": 6})
        mw = self._make_middleware(redis)

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        req = _make_request(path="/auth/register")
        resp = await mw.dispatch(req, call_next)

        # Should be rate-limited (429) because count=6 > rate_limit_auth_failure=5
        assert resp.status_code == 429
        # Verify call_next was NOT called (request was blocked)
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_endpoint_uses_strict_limit(self):
        """P1-7: /auth/refresh is a token rotation entry point and must use
        strict rate limiting to prevent abuse."""
        # Simulate a request to /auth/refresh with count=6 (exceeds strict limit of 5)
        redis = self._make_redis_mock({"/auth/refresh": 6})
        mw = self._make_middleware(redis)

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        req = _make_request(path="/auth/refresh")
        resp = await mw.dispatch(req, call_next)

        # Should be rate-limited (429) because count=6 > rate_limit_auth_failure=5
        assert resp.status_code == 429
        # Verify call_next was NOT called (request was blocked)
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_sse_ticket_endpoint_uses_strict_limit(self):
        """P1-7: /auth/sse-ticket is an SSE authentication entry point and must
        use strict rate limiting to prevent abuse."""
        # Simulate a request to /auth/sse-ticket with count=6 (exceeds strict limit of 5)
        redis = self._make_redis_mock({"/auth/sse-ticket": 6})
        mw = self._make_middleware(redis)

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        req = _make_request(path="/auth/sse-ticket")
        resp = await mw.dispatch(req, call_next)

        # Should be rate-limited (429) because count=6 > rate_limit_auth_failure=5
        assert resp.status_code == 429
        # Verify call_next was NOT called (request was blocked)
        call_next.assert_not_called()
