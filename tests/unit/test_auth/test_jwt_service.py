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
