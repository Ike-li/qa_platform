from __future__ import annotations

from collections import Counter
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from argon2 import Type, extract_parameters

from qaplatform.api.auth.token_service import TokenService


VALID_TOKEN_ID = "a" * 32
VALID_SECRET = "b" * 64
VALID_API_TOKEN = f"qap_{VALID_TOKEN_ID}_{VALID_SECRET}"


def _duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


class TestGenerateToken:
    def test_token_has_exact_public_format_and_entropy_lengths(self):
        token_id, full_token = TokenService.generate_token()
        match = re.fullmatch(
            r"qap_(?P<token_id>[0-9a-f]{32})_(?P<secret>[0-9a-f]{64})",
            full_token,
        )

        assert match is not None
        secret = match.group("secret")
        assert match.group("token_id") == token_id
        assert full_token == f"qap_{token_id}_{secret}"
        assert TokenService.parse_bearer_token(full_token) == (token_id, secret)

    def test_unique_tokens(self):
        generated = [TokenService.generate_token() for _ in range(100)]
        token_ids = [token_id for token_id, _ in generated]
        full_tokens = [full_token for _, full_token in generated]
        secrets = []
        for token_id, full_token in generated:
            parsed = TokenService.parse_bearer_token(full_token)
            assert parsed is not None
            parsed_token_id, secret = parsed
            assert parsed_token_id == token_id
            secrets.append(secret)

        assert _duplicate_values(token_ids) == []
        assert _duplicate_values(full_tokens) == []
        assert _duplicate_values(secrets) == []


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
        result = TokenService.parse_bearer_token(VALID_API_TOKEN)
        assert result == (VALID_TOKEN_ID, VALID_SECRET)

    def test_rejects_non_qap_prefix(self):
        assert TokenService.parse_bearer_token("bearer_abc123") is None

    def test_rejects_too_few_parts(self):
        assert TokenService.parse_bearer_token("qap_abc") is None

    @pytest.mark.parametrize(
        "raw",
        [
            "qap__secret",
            "qap_tokenid_",
            "qap_abc123_secret456",
            "qap_tokid_my_secret_with_underscores",
            f"qap_{'a' * 31}_{VALID_SECRET}",
            f"qap_{VALID_TOKEN_ID}_{'b' * 63}",
            f"qap_{'g' * 32}_{VALID_SECRET}",
            f"qap_{VALID_TOKEN_ID}_{'g' * 64}",
            f"qap_{VALID_TOKEN_ID.upper()}_{VALID_SECRET}",
        ],
    )
    def test_rejects_non_generated_token_shapes(self, raw):
        assert TokenService.parse_bearer_token(raw) is None

    def test_rejects_empty_string(self):
        assert TokenService.parse_bearer_token("") is None


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
        with patch.object(
            TokenService,
            "generate_token",
            return_value=("token-id", "qap_token-id_secret-value"),
        ), patch.object(
            TokenService,
            "hash_token",
            return_value="hashed-secret",
        ) as hash_token:
            result = await svc.create_api_token(
                user_id=user_id,
                name="ci-token",
                scopes=["*"],
                expires_at=expires,
            )

        assert result["token"] == "qap_token-id_secret-value"
        assert result["record"] is fake_record
        hash_token.assert_called_once_with("secret-value")
        mock_repo.create.assert_awaited_once_with(
            user_id=user_id,
            name="ci-token",
            token_id="token-id",
            secret_hash="hashed-secret",
            scopes=["*"],
            expires_at=expires,
        )

    @pytest.mark.asyncio
    async def test_hash_is_argon2id(self):
        mock_repo = AsyncMock()
        user_id = uuid4()
        expires = datetime.now(timezone.utc) + timedelta(days=90)
        fake_record = MagicMock()
        mock_repo.create.return_value = fake_record

        svc = TokenService(mock_repo)
        result = await svc.create_api_token(user_id, "t", [], expires)

        assert result["record"] is fake_record
        parsed = TokenService.parse_bearer_token(result["token"])
        assert parsed is not None
        token_id, secret = parsed
        create_kwargs = mock_repo.create.await_args.kwargs
        hash_value = create_kwargs["secret_hash"]
        assert create_kwargs == {
            "user_id": user_id,
            "name": "t",
            "token_id": token_id,
            "secret_hash": hash_value,
            "scopes": [],
            "expires_at": expires,
        }
        parameters = extract_parameters(hash_value)
        assert {
            "type": parameters.type,
            "version": parameters.version,
            "salt_len": parameters.salt_len,
            "hash_len": parameters.hash_len,
            "time_cost": parameters.time_cost,
            "memory_cost": parameters.memory_cost,
            "parallelism": parameters.parallelism,
        } == {
            "type": Type.ID,
            "version": 19,
            "salt_len": 16,
            "hash_len": 32,
            "time_cost": 3,
            "memory_cost": 65536,
            "parallelism": 1,
        }
        assert TokenService.verify_token(secret, hash_value) is True
        assert TokenService.verify_token(result["token"], hash_value) is False
        assert TokenService.verify_token(user_id.hex, hash_value) is False
