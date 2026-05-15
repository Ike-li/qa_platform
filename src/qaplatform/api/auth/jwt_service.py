from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from qaplatform.config import Settings


class JWTService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret
        self._algorithm = "HS256"
        self._access_ttl = timedelta(seconds=settings.jwt_access_token_ttl)
        self._refresh_ttl = timedelta(seconds=settings.jwt_refresh_token_ttl)

    def create_access_token(
        self,
        user_id: str,
        role: str,
        tenant_id: str,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "role": role,
            "tenant_id": tenant_id,
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
