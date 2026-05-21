import hashlib
import ipaddress
import re

from typing import Callable, Union

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from qaplatform.config import Settings

logger = structlog.get_logger(__name__)

_IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# P1-3: Strict rate limit paths (auth endpoints with elevated abuse risk)
# P1-7: Added /auth/refresh and /auth/sse-ticket (token rotation and SSE auth)
_STRICT_PATHS = (
    "/auth/login",
    "/auth/token",
    "/auth/register",
    "/auth/refresh",
    "/auth/sse-ticket",
)


def _parse_trusted_nets(cidr_list: list[str]) -> list[_IPNetwork]:
    """Convert a list of CIDR strings to network objects, skipping invalid entries."""
    nets: list[_IPNetwork] = []
    for cidr in cidr_list:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("rate_limit_invalid_cidr", cidr=cidr)
    return nets


def _in_trusted(addr: str, trusted_nets: list[_IPNetwork]) -> bool:
    """Return True if *addr* falls within any of the trusted networks."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in trusted_nets)


def _resolve_client_ip(
    request: Request,
    trusted_nets: list[_IPNetwork],
) -> str:
    """Determine the real client IP, honouring X-Forwarded-For only when the
    direct peer (request.client.host) is a trusted proxy.

    Algorithm:
    1. If client.host is NOT in trusted_nets → return client.host directly.
    2. Otherwise parse X-Forwarded-For right-to-left, skipping trusted hops,
       and return the first non-trusted address found.
    3. If every address in the header is trusted (or the header is absent/
       malformed), fall back to client.host.
    """
    direct_peer = request.client.host if request.client else "unknown"

    if not trusted_nets or not _in_trusted(direct_peer, trusted_nets):
        return direct_peer

    xff = request.headers.get("x-forwarded-for", "")
    # Split, strip whitespace, drop empty segments
    parts = [p.strip() for p in xff.split(",") if p.strip()]

    # Walk right-to-left; return the first address that is NOT trusted
    for addr in reversed(parts):
        try:
            ipaddress.ip_address(addr)  # validate it's a parseable IP
        except ValueError:
            # Malformed segment — skip it, don't trust it
            continue
        if not _in_trusted(addr, trusted_nets):
            return addr

    # All hops were trusted or header was absent — fall back to direct peer
    return direct_peer


def _resolve_bucket_key(request: Request, ip: str) -> str:
    """Return a bucket identifier string.

    If the request carries a Bearer token, the bucket is derived from a
    truncated SHA-256 of the token (first 16 hex chars).  This keeps
    per-token isolation without storing or logging the raw credential.

    Otherwise the bucket is the resolved client IP.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        short_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"token:{short_hash}"
    return f"ip:{ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-based sliding window rate limiter.

    Improvements over the original implementation:
    - Trusted-proxy-aware client IP resolution (X-Forwarded-For only when the
      direct peer is a configured trusted proxy).
    - Per-token bucketing for authenticated requests so that users behind a
      shared egress IP cannot exhaust each other's quota.
    """

    def __init__(self, app, settings: Settings, redis_client=None):
        super().__init__(app)
        self.settings = settings
        self.redis = redis_client
        # Pre-parse CIDR strings once at startup
        self._trusted_nets: list[_IPNetwork] = _parse_trusted_nets(
            settings.trusted_proxies
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health/docs paths
        if request.url.path in ["/health", "/ready", "/docs", "/openapi.json"]:
            return await call_next(request)

        # Lazy-load Redis from app state if not injected directly
        redis = self.redis
        if redis is None:
            container = getattr(request.app.state, "container", None)
            if container:
                redis = getattr(container, "redis_client", None)

        if redis is None:
            # Redis unavailable — allow the request but skip rate limiting
            return await call_next(request)

        ip = _resolve_client_ip(request, self._trusted_nets)
        bucket = _resolve_bucket_key(request, ip)
        path = request.url.path

        # Determine limits (fixed-window, product decision — do not change)
        limit = self.settings.rate_limit_per_minute
        window = self.settings.rate_limit_window_seconds

        if any(p in path for p in _STRICT_PATHS):
            limit = self.settings.rate_limit_auth_failure
            window = self.settings.rate_limit_auth_failure_window

        # Normalize UUIDs in path to prevent per-resource rate limit bypass
        normalized_path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{id}",
            path,
        )
        key = f"rate_limit:{bucket}:{normalized_path}"

        try:
            # Use Redis TIME to avoid clock skew between app servers and Redis
            redis_time = await redis.time()
            now = redis_time[0] + redis_time[1] / 1_000_000

            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window)

            results = await pipe.execute()
            request_count = results[2]

            if request_count > limit:
                logger.warning(
                    "rate_limit_exceeded",
                    bucket=bucket,
                    path=path,
                    count=request_count,
                    limit=limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "TOO_MANY_REQUESTS",
                            "message": "Rate limit exceeded. Please try again later.",
                        }
                    },
                    headers={"Retry-After": str(window)},
                )
        except Exception as e:
            logger.error("rate_limit_error", error=str(e))
            # Fail-closed for auth endpoints during Redis outage
            if any(p in path for p in _STRICT_PATHS):
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": {
                            "code": "SERVICE_UNAVAILABLE",
                            "message": "Service temporarily unavailable",
                        }
                    },
                    headers={"Retry-After": "5"},
                )
            return await call_next(request)

        return await call_next(request)
