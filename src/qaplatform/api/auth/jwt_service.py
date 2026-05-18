from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from qaplatform.config import Settings


class JWTService:
    def __init__(self, settings: Settings, redis=None) -> None:
        self._secret = settings.jwt_secret
        self._algorithm = "HS256"
        self._access_ttl = timedelta(seconds=settings.jwt_access_token_ttl)
        self._refresh_ttl = timedelta(seconds=settings.jwt_refresh_token_ttl)
        self._redis = redis

    def create_access_token(
        self,
        user_id: str,
        role: str,
        tenant_id: str,
        is_platform_admin: bool = False,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "is_platform_admin": is_platform_admin,
            "exp": now + self._access_ttl,
            "iat": now,
            "jti": uuid4().hex,
            "type": "access",
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_refresh_token(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "exp": now + self._refresh_ttl,
            "iat": now,
            "jti": uuid4().hex,
            "type": "refresh",
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict:
        return jwt.decode(token, self._secret, algorithms=[self._algorithm])

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Add jti to the revocation blacklist with TTL matching token lifetime.

        The key auto-expires so the blacklist never grows unboundedly.
        """
        if self._redis is None:
            return
        await self._redis.set(f"jwt:revoked:{jti}", "1", ex=max(1, ttl_seconds))

    async def is_revoked(self, jti: str) -> bool:
        """Return True if the jti is on the revocation blacklist."""
        if self._redis is None:
            return False
        return bool(await self._redis.exists(f"jwt:revoked:{jti}"))
