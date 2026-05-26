from __future__ import annotations

import base64
import uuid

import pytest

from qaplatform.dependencies import CryptoService
from qaplatform.domain.services.env_vars_crypto import (
    decrypt_env_vars,
    encrypt_env_vars,
    is_encrypted_env_vars,
)


def _crypto(keys: dict[int, bytes] | None = None) -> CryptoService:
    return CryptoService(keys or {0: b"\x00" * 32})


def test_env_vars_encrypt_decrypt_roundtrip_hides_plaintext() -> None:
    env_id = uuid.uuid4()
    secret_env = {"API_TOKEN": "secret-value", "REGION": "ap-east-1"}

    encrypted = encrypt_env_vars(secret_env, environment_id=env_id, crypto=_crypto())

    assert is_encrypted_env_vars(encrypted)
    assert decrypt_env_vars(encrypted, environment_id=env_id, crypto=_crypto()) == secret_env
    serialized = repr(encrypted)
    assert "API_TOKEN" not in serialized
    assert "secret-value" not in serialized


def test_env_vars_aad_mismatch_fails() -> None:
    encrypted = encrypt_env_vars(
        {"TOKEN": "secret"},
        environment_id=uuid.uuid4(),
        crypto=_crypto(),
    )

    with pytest.raises(Exception):
        decrypt_env_vars(encrypted, environment_id=uuid.uuid4(), crypto=_crypto())


def test_env_vars_key_version_rotation_decrypts_old_and_encrypts_new() -> None:
    env_id = uuid.uuid4()
    old_crypto = _crypto({0: b"\x00" * 32})
    rotated_crypto = _crypto({0: b"\x00" * 32, 1: b"\x01" * 32})

    old_encrypted = encrypt_env_vars({"OLD": "value"}, environment_id=env_id, crypto=old_crypto)
    new_encrypted = encrypt_env_vars({"NEW": "value"}, environment_id=env_id, crypto=rotated_crypto)

    assert decrypt_env_vars(old_encrypted, environment_id=env_id, crypto=rotated_crypto) == {
        "OLD": "value",
    }
    new_ciphertext = base64.b64decode(new_encrypted["ciphertext"])
    assert new_ciphertext[0] & 0x0F == 1
