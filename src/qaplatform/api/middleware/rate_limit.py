import time
from typing import Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from qaplatform.config import Settings

logger = structlog.get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-based sliding window rate limiter.
    """

    def __init__(self, app, settings: Settings, redis_client=None):
        super().__init__(app)
        self.settings = settings
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for some paths if needed, e.g., docs, health
        if request.url.path in ["/health", "/ready", "/docs", "/openapi.json"]:
            return await call_next(request)

        # Lazy load redis from app state if not provided
        redis = self.redis
        if redis is None:
            container = getattr(request.app.state, "container", None)
            if container:
                redis = getattr(container, "redis_client", None)
        
        if redis is None:
            # If Redis is still not available, we can't rate limit, so we just proceed
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        path = request.url.path
        
        # Determine limits
        # Default: 100 req/min
        # Login: 5 req/min
        limit = self.settings.rate_limit_per_minute
        window = self.settings.rate_limit_window_seconds
        
        if "/auth/login" in path or "/auth/token" in path:
            limit = self.settings.rate_limit_auth_failure
            window = self.settings.rate_limit_auth_failure_window

        key = f"rate_limit:{ip}:{path}"
        now = time.time()
        
        try:
            # Sliding window using Redis sorted set
            pipe = redis.pipeline()
            # Remove old entries
            pipe.zremrangebyscore(key, 0, now - window)
            # Add current entry
            pipe.zadd(key, {str(now): now})
            # Count entries
            pipe.zcard(key)
            # Set expiry to clean up
            pipe.expire(key, window)
            
            results = await pipe.execute()
            request_count = results[2]
            
            if request_count > limit:
                logger.warning("rate_limit_exceeded", ip=ip, path=path, count=request_count, limit=limit)
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
            # If Redis is down, we allow the request but log the error
            logger.error("rate_limit_error", error=str(e))
            return await call_next(request)

        return await call_next(request)
