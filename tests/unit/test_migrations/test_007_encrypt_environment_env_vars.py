from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

from qaplatform.dependencies import CryptoService
from qaplatform.domain.services.env_vars_crypto import (
    decrypt_env_vars,
    encrypt_env_vars,
    is_encrypted_env_vars,
)


def _load_migration():
    path = Path(__file__).parents[3] / "alembic/versions/007_encrypt_environment_env_vars.py"
    spec = importlib.util.spec_from_file_location("migration_007_encrypt_env_vars", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


class _Connection:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []

    def execute(self, _stmt, params=None):
        if params is None:
            return _Result(self._rows)
        self.updates.append(params)
        return None


def test_upgrade_encrypts_plain_env_vars_and_skips_existing_envelopes(monkeypatch):
    migration = _load_migration()
    crypto = CryptoService({0: b"\x00" * 32})
    plain_id = uuid4()
    encrypted_id = uuid4()
    already_encrypted = encrypt_env_vars(
        {"ALREADY": "secret"},
        environment_id=encrypted_id,
        crypto=crypto,
    )
    conn = _Connection(
        [
            {"id": plain_id, "env_vars": {"TOKEN": "secret-value"}},
            {"id": encrypted_id, "env_vars": already_encrypted},
        ]
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: conn)
    monkeypatch.setattr(migration, "_crypto_from_settings", lambda: crypto)

    migration.upgrade()

    assert [update["id"] for update in conn.updates] == [plain_id]
    updated = conn.updates[0]
    updated_env_vars = updated["env_vars"]
    assert set(updated_env_vars) == {"__encrypted__", "ciphertext"}
    assert updated_env_vars["__encrypted__"] == "qaplatform.env_vars.v1"
    assert isinstance(updated_env_vars["ciphertext"], str)
    assert updated_env_vars["ciphertext"]
    assert is_encrypted_env_vars(updated_env_vars)
    assert "TOKEN" not in repr(updated_env_vars)
    assert "secret-value" not in repr(updated_env_vars)
    assert decrypt_env_vars(updated_env_vars, environment_id=plain_id, crypto=crypto) == {
        "TOKEN": "secret-value",
    }


def test_downgrade_decrypts_envelopes_and_skips_plain_env_vars(monkeypatch):
    migration = _load_migration()
    crypto = CryptoService({0: b"\x00" * 32})
    encrypted_id = uuid4()
    plain_id = uuid4()
    encrypted = encrypt_env_vars(
        {"TOKEN": "secret-value"},
        environment_id=encrypted_id,
        crypto=crypto,
    )
    conn = _Connection(
        [
            {"id": encrypted_id, "env_vars": encrypted},
            {"id": plain_id, "env_vars": {"PLAIN": "value"}},
        ]
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: conn)
    monkeypatch.setattr(migration, "_crypto_from_settings", lambda: crypto)

    migration.downgrade()

    assert conn.updates == [
        {"id": encrypted_id, "env_vars": {"TOKEN": "secret-value"}},
    ]
