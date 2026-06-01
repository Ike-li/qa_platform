from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _quality_ops_row,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_007_ENV_VARS_TEST = (
    ROOT
    / "tests"
    / "unit"
    / "test_migrations"
    / "test_007_encrypt_environment_env_vars.py"
)


def test_quality_ops_capture_migration_007_env_vars_exact_envelope_contract():
    migration_test = _read(MIGRATION_007_ENV_VARS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Migration 007 env_vars upgrade exact envelope 契约）"
    )

    assert "Migration 007 env_vars upgrade exact envelope 契约" in row
    assert (
        "`tests/unit/test_migrations/test_007_encrypt_environment_env_vars.py::test_upgrade_encrypts_plain_env_vars_and_skips_existing_envelopes` 1 passed"
        in row
    )
    assert "migration 007 full 2 passed" in row
    assert "release quality docs contract full 201 passed" in row
    assert "只更新 plain row 的 id 序列" in row
    assert "`__encrypted__` + `ciphertext`" in row
    assert "marker 必须是 `qaplatform.env_vars.v1`" in row
    assert "ciphertext 必须是非空字符串" in row
    assert "不回显明文 key/value" in row
    assert "`len(conn.updates) == 1`" in row
    assert "迁移额外更新已加密行" in row
    assert "marker 漂移" in row
    assert "有一条环境变量能 roundtrip" in row

    test_block = _marked_block(
        migration_test,
        "def test_upgrade_encrypts_plain_env_vars_and_skips_existing_envelopes",
        "def test_downgrade_decrypts_envelopes_and_skips_plain_env_vars",
    )

    for expected in [
        'assert [update["id"] for update in conn.updates] == [plain_id]',
        'updated_env_vars = updated["env_vars"]',
        'assert set(updated_env_vars) == {"__encrypted__", "ciphertext"}',
        'assert updated_env_vars["__encrypted__"] == "qaplatform.env_vars.v1"',
        'assert isinstance(updated_env_vars["ciphertext"], str)',
        'assert updated_env_vars["ciphertext"]',
        "assert is_encrypted_env_vars(updated_env_vars)",
        'assert "TOKEN" not in repr(updated_env_vars)',
        'assert "secret-value" not in repr(updated_env_vars)',
        "assert decrypt_env_vars(updated_env_vars, environment_id=plain_id, crypto=crypto) == {",
    ]:
        assert expected in test_block
    assert "assert len(conn.updates) == 1" not in test_block
