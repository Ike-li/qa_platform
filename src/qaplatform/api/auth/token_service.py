from __future__ import annotations

import os
import re
from datetime import datetime
from typing import TYPE_CHECKING

import argon2.low_level
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

if TYPE_CHECKING:
    from uuid import UUID

    from qaplatform.infra.database.repositories.user_repo import (
        ApiTokenRepository,
    )

_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    type=argon2.low_level.Type.ID,
)
_API_TOKEN_PATTERN = re.compile(r"^qap_([0-9a-f]{32})_([0-9a-f]{64})$")


class TokenService:
    def __init__(self, api_token_repo: ApiTokenRepository) -> None:
        self._repo = api_token_repo

    @staticmethod
    def generate_token() -> tuple[str, str]:
        """Return (token_id, full_token)."""
        token_id = os.urandom(16).hex()
        secret = os.urandom(32).hex()
        full_token = f"qap_{token_id}_{secret}"
        return token_id, full_token

    @staticmethod
    def hash_token(secret: str) -> str:
        return _ph.hash(secret)

    @staticmethod
    def verify_token(secret: str, hash_value: str) -> bool:
        try:
            return _ph.verify(hash_value, secret)
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    @staticmethod
    def parse_bearer_token(raw: str) -> tuple[str, str] | None:
        """Parse a qap_ bearer token. Return (token_id, secret) or None."""
        match = _API_TOKEN_PATTERN.fullmatch(raw)
        if match is None:
            return None
        return match.group(1), match.group(2)

    async def create_api_token(
        self,
        user_id: UUID,
        name: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> dict:
        """Create an API token and return the full token string plus the ORM record."""
        token_id, full_token = self.generate_token()
        secret = full_token.split("_", maxsplit=2)[2]
        secret_hash = self.hash_token(secret)

        record = await self._repo.create(
            user_id=user_id,
            name=name,
            token_id=token_id,
            secret_hash=secret_hash,
            scopes=scopes,
            expires_at=expires_at,
        )
        return {"record": record, "token": full_token}
