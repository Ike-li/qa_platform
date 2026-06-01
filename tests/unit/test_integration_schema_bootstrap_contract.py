from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_INTEGRATION_CONFTEST_PATH = (
    Path(__file__).resolve().parents[1] / "integration" / "conftest.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "_integration_conftest_contract", _INTEGRATION_CONFTEST_PATH
)
assert _SPEC is not None
assert _SPEC.loader is not None
_integration_conftest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _integration_conftest
_SPEC.loader.exec_module(_integration_conftest)
integration_db_schema = _integration_conftest.integration_db_schema


def _pg_container() -> MagicMock:
    container = MagicMock()
    container.get_connection_url.return_value = (
        "postgresql+psycopg2://qaplatform:qaplatform@localhost:5432/qaplatform"
    )
    return container


def test_integration_db_schema_reports_alembic_mode_when_migration_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(_integration_conftest.subprocess, "run", run)

    result = integration_db_schema.__wrapped__(_pg_container(), object())

    assert result == {"mode": "alembic"}
    env = run.call_args.kwargs["env"]
    assert env["QAP_DATABASE_URL"] == (
        "postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform"
    )
    assert env["QAP_S3_REGION"] == "us-east-1"


def test_integration_db_schema_strips_external_qap_env_before_migration(
    monkeypatch: pytest.MonkeyPatch,
):
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setenv("QAP_DATABASE_URL", "postgresql+asyncpg://dev/dev")
    monkeypatch.setenv("QAP_S3_REGION", "")
    monkeypatch.setenv("QAP_UNRELATED", "leak")
    monkeypatch.setattr(_integration_conftest.subprocess, "run", run)

    result = integration_db_schema.__wrapped__(_pg_container(), object())

    assert result == {"mode": "alembic"}
    env = run.call_args.kwargs["env"]
    assert env["QAP_DATABASE_URL"] == (
        "postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform"
    )
    assert env["QAP_S3_REGION"] == "us-east-1"
    assert "QAP_UNRELATED" not in env


def test_integration_db_schema_fails_instead_of_metadata_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    run = MagicMock(
        return_value=SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="broken migration",
        )
    )
    create_engine = MagicMock(side_effect=AssertionError("metadata fallback used"))
    monkeypatch.setattr(_integration_conftest.subprocess, "run", run)
    monkeypatch.setattr(_integration_conftest, "create_async_engine", create_engine)

    with pytest.raises(pytest.fail.Exception) as exc_info:
        integration_db_schema.__wrapped__(_pg_container(), object())

    assert str(exc_info.value) == (
        "alembic upgrade head failed for integration schema bootstrap "
        "(exit=1):\nbroken migration"
    )
    create_engine.assert_not_called()
