from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.api.auth.token_service import TokenService


class TestGenerateToken:
    def test_format_starts_with_qap(self):
        token_id, full_token = TokenService.generate_token()
        assert full_token.startswith("qap_")

    def test_token_has_three_parts(self):
        token_id, full_token = TokenService.generate_token()
        parts = full_token.split("_")
        assert len(parts) == 3

    def test_token_id_matches(self):
        token_id, full_token = TokenService.generate_token()
        parts = full_token.split("_", maxsplit=2)
        assert parts[1] == token_id

    def test_token_id_is_32_hex_chars(self):
        token_id, _ = TokenService.generate_token()
        assert len(token_id) == 32
        int(token_id, 16)

    def test_unique_tokens(self):
        ids = {TokenService.generate_token()[0] for _ in range(100)}
        assert len(ids) == 100


class TestHashAndVerify:
    def test_hash_then_verify_succeeds(self):
        secret = "abcdef1234567890"
        h = TokenService.hash_token(secret)
        assert TokenService.verify_token(secret, h) is True

    def test_wrong_secret_fails(self):
        secret = "correct-secret"
        h = TokenService.hash_token(secret)
        assert TokenService.verify_token("wrong-secret", h) is False

    def test_empty_secret_fails(self):
        h = TokenService.hash_token("real-secret")
        assert TokenService.verify_token("", h) is False

    def test_garbage_hash_fails(self):
        assert TokenService.verify_token("secret", "not-a-hash") is False


class TestParseBearerToken:
    def test_valid_format(self):
        result = TokenService.parse_bearer_token("qap_abc123_secret456")
        assert result == ("abc123", "secret456")

    def test_rejects_non_qap_prefix(self):
        assert TokenService.parse_bearer_token("bearer_abc123") is None

    def test_rejects_too_few_parts(self):
        assert TokenService.parse_bearer_token("qap_abc") is None

    def test_rejects_empty_string(self):
        assert TokenService.parse_bearer_token("") is None

    def test_secret_can_contain_underscores(self):
        result = TokenService.parse_bearer_token("qap_tokid_my_secret_with_underscores")
        assert result is not None
        token_id, secret = result
        assert token_id == "tokid"
        assert secret == "my_secret_with_underscores"


class TestCreateApiToken:
    @pytest.mark.asyncio
    async def test_creates_token_with_repo(self):
        mock_repo = AsyncMock()
        user_id = uuid4()
        expires = datetime.now(timezone.utc) + timedelta(days=90)

        # Simulate ORM model instance
        fake_record = MagicMock()
        fake_record.token_id = "abc123"
        fake_record.name = "ci-token"
        fake_record.scopes = ["*"]
        fake_record.expires_at = expires
        fake_record.created_at = datetime.now(timezone.utc)
        mock_repo.create.return_value = fake_record

        svc = TokenService(mock_repo)
        result = await svc.create_api_token(
            user_id=user_id,
            name="ci-token",
            scopes=["*"],
            expires_at=expires,
        )

        assert result["token"].startswith("qap_")
        assert result["record"] is fake_record
        mock_repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hash_is_argon2id(self):
        mock_repo = AsyncMock()
        user_id = uuid4()
        expires = datetime.now(timezone.utc) + timedelta(days=90)
        mock_repo.create.return_value = MagicMock()

        svc = TokenService(mock_repo)
        await svc.create_api_token(user_id, "t", [], expires)

        call_args = mock_repo.create.call_args
        hash_value = call_args.kwargs.get("secret_hash", "")
        assert hash_value.startswith("$argon2")
