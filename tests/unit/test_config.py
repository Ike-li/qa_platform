"""Tests for QAP_ prefixed environment variable parsing in Settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qaplatform.config import Settings


# Minimal env vars to satisfy all required fields
REQUIRED_ENV = {
    "QAP_DATABASE_URL": "postgresql+asyncpg://localhost/test",
    "QAP_REDIS_URL": "redis://localhost:6379/0",
    "QAP_S3_ENDPOINT": "http://localhost:9000",
    "QAP_S3_ACCESS_KEY": "minioadmin",
    "QAP_S3_SECRET_KEY": "minioadmin",
    "QAP_JWT_SECRET": "test-jwt-secret-at-least-32bytes!",
    "QAP_ENCRYPTION_KEY": "0" * 64,
}


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)


# --- QAP_ prefix env var parsing ---


def test_env_prefix_parsing(monkeypatch: pytest.MonkeyPatch):
    """QAP_ prefixed env vars are correctly mapped to fields."""
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_APP_NAME", "CustomApp")
    monkeypatch.setenv("QAP_DEBUG", "true")
    monkeypatch.setenv("QAP_ENVIRONMENT", "production")

    s = Settings()
    assert s.app_name == "CustomApp"
    assert s.debug is True
    assert s.environment == "production"


def test_database_url_from_env(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_DATABASE_URL", "postgresql+asyncpg://db-host/prod")
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://db-host/prod"


def test_integer_fields_from_env(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_DATABASE_POOL_SIZE", "25")
    monkeypatch.setenv("QAP_JWT_ACCESS_TOKEN_TTL", "7200")
    s = Settings()
    assert s.database_pool_size == 25
    assert s.jwt_access_token_ttl == 7200


# --- Default values ---


def test_defaults_debug_false(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("QAP_DEBUG", raising=False)
    monkeypatch.setenv("QAP_DEBUG", "false")
    s = Settings()
    assert s.debug is False


def test_defaults_enable_hsts_true(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings()
    assert s.enable_hsts is True


def test_defaults_app_name(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings()
    assert s.app_name == "QA Platform"


def test_defaults_environment_development(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings()
    assert s.environment == "development"


def test_defaults_pool_and_overflow(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings()
    assert s.database_pool_size == 10
    assert s.database_max_overflow == 20


def test_defaults_jwt_ttl(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings()
    assert s.jwt_access_token_ttl == 3600
    assert s.jwt_refresh_token_ttl == 604800


def test_defaults_s3_bucket_and_region(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings()
    assert s.s3_bucket == "qa-platform"
    assert s.s3_region == "us-east-1"


def test_defaults_retention(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings()
    assert s.retention_runs_days == 90
    assert s.retention_reports_days == 30
    assert s.retention_audit_days == 1095


# --- Required fields missing ---


def _env_without(key: str) -> dict[str, str]:
    return {k: v for k, v in REQUIRED_ENV.items() if k != key}


@pytest.mark.parametrize(
    "missing_key",
    [
        "QAP_DATABASE_URL",
        "QAP_REDIS_URL",
        "QAP_S3_ENDPOINT",
        "QAP_S3_ACCESS_KEY",
        "QAP_S3_SECRET_KEY",
        "QAP_JWT_SECRET",
        "QAP_ENCRYPTION_KEY",
    ],
)
def test_required_field_missing_raises(
    monkeypatch: pytest.MonkeyPatch, missing_key: str
):
    for k, v in _env_without(missing_key).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(missing_key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
