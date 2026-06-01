from __future__ import annotations

import base64
import uuid

import pytest
from cryptography.exceptions import InvalidTag

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
    wrong_env_id = uuid.uuid4()
    encrypted = encrypt_env_vars(
        {"TOKEN": "secret"},
        environment_id=uuid.uuid4(),
        crypto=_crypto(),
    )

    with pytest.raises(ValueError) as exc_info:
        decrypt_env_vars(encrypted, environment_id=wrong_env_id, crypto=_crypto())

    assert str(exc_info.value) == "Invalid encrypted env_vars payload"
    assert isinstance(exc_info.value.__cause__, InvalidTag)
    serialized_error = repr(exc_info.value)
    assert "TOKEN" not in serialized_error
    assert "secret" not in serialized_error
    assert encrypted["ciphertext"] not in serialized_error
    assert str(wrong_env_id) not in serialized_error


@pytest.mark.parametrize("raw_ciphertext", [b"", b"\x10", b"\x10" + b"\x00" * 12])
def test_env_vars_truncated_ciphertext_fails_with_sanitized_error(
    raw_ciphertext: bytes,
) -> None:
    encrypted = {
        "__encrypted__": "qaplatform.env_vars.v1",
        "ciphertext": base64.b64encode(raw_ciphertext).decode("ascii"),
    }
    env_id = uuid.uuid4()

    with pytest.raises(ValueError) as exc_info:
        decrypt_env_vars(encrypted, environment_id=env_id, crypto=_crypto())

    assert str(exc_info.value) == "Invalid encrypted env_vars payload"
    assert isinstance(exc_info.value.__cause__, ValueError)
    serialized_error = repr(exc_info.value)
    if encrypted["ciphertext"]:
        assert encrypted["ciphertext"] not in serialized_error
    assert str(env_id) not in serialized_error


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
