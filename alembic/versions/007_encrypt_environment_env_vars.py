"""encrypt environment env_vars

Revision ID: 007
Revises: 006
Create Date: 2026-05-26
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from qaplatform.config import Settings
from qaplatform.dependencies import CryptoService
from qaplatform.domain.services.env_vars_crypto import (
    decrypt_env_vars,
    encrypt_env_vars,
    is_encrypted_env_vars,
)

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SELECT_ENVIRONMENTS = sa.text("SELECT id, env_vars FROM environment")
_UPDATE_ENV_VARS = sa.text(
    "UPDATE environment SET env_vars = :env_vars WHERE id = :id"
).bindparams(sa.bindparam("env_vars", type_=JSONB))


def _crypto_from_settings() -> CryptoService:
    settings = Settings()
    keys: dict[int, bytes] = {}
    if settings.encryption_keys:
        for version, key_hex in settings.encryption_keys.items():
            keys[version] = bytes.fromhex(key_hex)
    else:
        keys[0] = bytes.fromhex(settings.encryption_key)
    return CryptoService(keys)


def upgrade() -> None:
    conn = op.get_bind()
    crypto = _crypto_from_settings()
    for row in conn.execute(_SELECT_ENVIRONMENTS).mappings():
        env_vars = row["env_vars"] or {}
        if is_encrypted_env_vars(env_vars):
            continue
        encrypted = encrypt_env_vars(env_vars, environment_id=row["id"], crypto=crypto)
        conn.execute(_UPDATE_ENV_VARS, {"id": row["id"], "env_vars": encrypted})


def downgrade() -> None:
    conn = op.get_bind()
    crypto = _crypto_from_settings()
    for row in conn.execute(_SELECT_ENVIRONMENTS).mappings():
        env_vars = row["env_vars"] or {}
        if not is_encrypted_env_vars(env_vars):
            continue
        decrypted = decrypt_env_vars(env_vars, environment_id=row["id"], crypto=crypto)
        conn.execute(_UPDATE_ENV_VARS, {"id": row["id"], "env_vars": decrypted})
