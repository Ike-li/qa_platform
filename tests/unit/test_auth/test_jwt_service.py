from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt
import pytest

from qaplatform.api.auth.jwt_service import JWTService


def _make_settings(**overrides):
    settings = MagicMock()
    settings.jwt_secret = overrides.get("jwt_secret", "test-secret-key-for-jwt-32bytes!")
    settings.jwt_access_token_ttl = overrides.get("jwt_access_token_ttl", 1800)
    settings.jwt_refresh_token_ttl = overrides.get("jwt_refresh_token_ttl", 604800)
    return settings


class TestCreateAccessToken:
    def test_returns_valid_jwt(self):
        svc = JWTService(_make_settings())
        token = svc.create_access_token("user-1", "developer", "tenant-1")
        payload = jwt.decode(token, "test-secret-key-for-jwt-32bytes!", algorithms=["HS256"])
        assert payload["sub"] == "user-1"
        assert payload["role"] == "developer"
        assert payload["tenant_id"] == "tenant-1"
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_different_tokens_have_different_jti(self):
        svc = JWTService(_make_settings())
        t1 = svc.create_access_token("u1", "viewer", "t1")
        t2 = svc.create_access_token("u1", "viewer", "t1")
        p1 = jwt.decode(t1, "test-secret-key-for-jwt-32bytes!", algorithms=["HS256"])
        p2 = jwt.decode(t2, "test-secret-key-for-jwt-32bytes!", algorithms=["HS256"])
        assert p1["jti"] != p2["jti"]


class TestCreateRefreshToken:
    def test_returns_valid_jwt(self):
        svc = JWTService(_make_settings())
        token = svc.create_refresh_token("user-2")
        payload = jwt.decode(token, "test-secret-key-for-jwt-32bytes!", algorithms=["HS256"])
        assert payload["sub"] == "user-2"
        assert payload["type"] == "refresh"
        assert "exp" in payload
        assert "jti" in payload

    def test_no_role_or_tenant_in_refresh(self):
        svc = JWTService(_make_settings())
        token = svc.create_refresh_token("user-3")
        payload = jwt.decode(token, "test-secret-key-for-jwt-32bytes!", algorithms=["HS256"])
        assert "role" not in payload
        assert "tenant_id" not in payload


class TestDecodeToken:
    def test_decodes_valid_token(self):
        svc = JWTService(_make_settings())
        token = svc.create_access_token("u1", "platform_admin", "t1")
        payload = svc.decode_token(token)
        assert payload["sub"] == "u1"
        assert payload["role"] == "platform_admin"

    def test_raises_on_expired_token(self):
        settings = _make_settings(jwt_access_token_ttl=0)
        svc = JWTService(settings)
        token = svc.create_access_token("u1", "viewer", "t1")
        # token is already expired (ttl=0), sleep a tick to ensure clock advances
        time.sleep(0.01)
        with pytest.raises(jwt.ExpiredSignatureError):
            svc.decode_token(token)

    def test_raises_on_wrong_secret(self):
        svc = JWTService(_make_settings())
        token = svc.create_access_token("u1", "viewer", "t1")
        other_svc = JWTService(_make_settings(jwt_secret="different-secret-key-32bytes!!!"))
        with pytest.raises(jwt.InvalidSignatureError):
            other_svc.decode_token(token)

    def test_raises_on_malformed_token(self):
        svc = JWTService(_make_settings())
        with pytest.raises(jwt.DecodeError):
            svc.decode_token("not-a-jwt")

    def test_raises_on_tampered_payload(self):
        svc = JWTService(_make_settings())
        token = svc.create_access_token("u1", "viewer", "t1")
        # Tamper with the token by flipping a character in the payload
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1][::-1] + "." + parts[2]
        with pytest.raises(jwt.DecodeError):
            svc.decode_token(tampered)


class TestBlacklist:
    @pytest.mark.asyncio
    async def test_revoke_marks_jti_as_revoked(self):
        from unittest.mock import AsyncMock

        redis = AsyncMock()
        store: dict[str, str] = {}

        async def _set(key, value, ex=None):
            store[key] = value

        async def _exists(key):
            return 1 if key in store else 0

        redis.set = AsyncMock(side_effect=_set)
        redis.exists = AsyncMock(side_effect=_exists)

        svc = JWTService(_make_settings(), redis=redis)
        await svc.revoke("abc123", 3600)
        assert await svc.is_revoked("abc123") is True

    @pytest.mark.asyncio
    async def test_unknown_jti_not_revoked(self):
        from unittest.mock import AsyncMock

        redis = AsyncMock()
        redis.exists = AsyncMock(return_value=0)

        svc = JWTService(_make_settings(), redis=redis)
        assert await svc.is_revoked("unknown-jti") is False

    @pytest.mark.asyncio
    async def test_revoke_without_redis_is_noop(self):
        """When no redis is injected, revoke/is_revoked must not raise."""
        svc = JWTService(_make_settings(), redis=None)
        await svc.revoke("jti-x", 3600)  # must not raise
        assert await svc.is_revoked("jti-x") is False

    @pytest.mark.asyncio
    async def test_revoke_ttl_floored_at_one(self):
        """ttl_seconds=0 must be stored with ex=1 (Redis rejects ex=0)."""
        from unittest.mock import AsyncMock, call

        redis = AsyncMock()
        redis.set = AsyncMock()

        svc = JWTService(_make_settings(), redis=redis)
        await svc.revoke("jti-y", 0)
        redis.set.assert_called_once_with("jwt:revoked:jti-y", "1", ex=1)
