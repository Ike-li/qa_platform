from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag

_ENVELOPE_MARKER = "qaplatform.env_vars.v1"
_MARKER_KEY = "__encrypted__"
_CIPHERTEXT_KEY = "ciphertext"


class EnvVarsCrypto(Protocol):
    def encrypt(self, plaintext: str, context_id: str = "") -> bytes: ...
    def decrypt(self, data: bytes, context_id: str = "") -> str: ...


def env_vars_aad(environment_id: UUID | str) -> str:
    return f"env:{environment_id}"


def is_encrypted_env_vars(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get(_MARKER_KEY) == _ENVELOPE_MARKER
        and isinstance(value.get(_CIPHERTEXT_KEY), str)
    )


def encrypt_env_vars(
    env_vars: dict[str, str],
    *,
    environment_id: UUID | str,
    crypto: EnvVarsCrypto,
) -> dict[str, str]:
    plaintext = json.dumps(env_vars, sort_keys=True, separators=(",", ":"))
    ciphertext = crypto.encrypt(plaintext, context_id=env_vars_aad(environment_id))
    return {
        _MARKER_KEY: _ENVELOPE_MARKER,
        _CIPHERTEXT_KEY: base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_env_vars(
    stored: Any,
    *,
    environment_id: UUID | str,
    crypto: EnvVarsCrypto,
) -> dict[str, str]:
    if stored in (None, {}):
        return {}
    if not is_encrypted_env_vars(stored):
        return _validate_env_vars(stored)

    encoded = stored[_CIPHERTEXT_KEY]
    try:
        ciphertext = base64.b64decode(encoded.encode("ascii"), validate=True)
        plaintext = crypto.decrypt(ciphertext, context_id=env_vars_aad(environment_id))
        decoded = json.loads(plaintext)
    except (
        binascii.Error,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        InvalidTag,
    ) as exc:
        raise ValueError("Invalid encrypted env_vars payload") from exc

    return _validate_env_vars(decoded)


def _validate_env_vars(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("env_vars payload must be a JSON object")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError("env_vars keys and values must be strings")
    return dict(value)
