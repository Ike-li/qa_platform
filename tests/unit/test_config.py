"""Tests for QAP_ prefixed environment variable parsing in Settings."""

from __future__ import annotations

import os

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

ENV_FIELD_NAMES = {
    "QAP_DATABASE_URL": "database_url",
    "QAP_REDIS_URL": "redis_url",
    "QAP_S3_ENDPOINT": "s3_endpoint",
    "QAP_S3_ACCESS_KEY": "s3_access_key",
    "QAP_S3_SECRET_KEY": "s3_secret_key",
    "QAP_JWT_SECRET": "jwt_secret",
    "QAP_ENCRYPTION_KEY": "encryption_key",
}


@pytest.fixture(autouse=True)
def _isolate_qap_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("QAP_"):
            monkeypatch.delenv(key, raising=False)


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)


def _required_settings_input_without(missing_key: str) -> dict[str, str]:
    return {
        ENV_FIELD_NAMES[env_key]: value
        for env_key, value in REQUIRED_ENV.items()
        if env_key != missing_key
    }


def _validation_error_projection(errors) -> list[dict]:
    return [
        {
            "type": error["type"],
            "loc": error["loc"],
            "msg": error["msg"],
            "input": error.get("input"),
        }
        for error in errors
    ]


# --- QAP_ prefix env var parsing ---


def test_env_prefix_parsing(monkeypatch: pytest.MonkeyPatch):
    """QAP_ prefixed env vars are correctly mapped to fields."""
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_APP_NAME", "CustomApp")
    monkeypatch.setenv("QAP_DEBUG", "true")
    monkeypatch.setenv("QAP_ENVIRONMENT", "production")

    s = Settings(_env_file=None)
    assert s.app_name == "CustomApp"
    assert s.debug is True
    assert s.environment == "production"


def test_database_url_from_env(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_DATABASE_URL", "postgresql+asyncpg://db-host/prod")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://db-host/prod"


def test_integer_fields_from_env(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_DATABASE_POOL_SIZE", "25")
    monkeypatch.setenv("QAP_JWT_ACCESS_TOKEN_TTL", "7200")
    s = Settings(_env_file=None)
    assert s.database_pool_size == 25
    assert s.jwt_access_token_ttl == 7200


@pytest.mark.parametrize(
    ("env_key", "raw_value", "expected_field", "expected_msg"),
    [
        (
            "QAP_DATABASE_POOL_SIZE",
            "0",
            "database_pool_size",
            "greater than or equal to 1",
        ),
        (
            "QAP_DATABASE_MAX_OVERFLOW",
            "-1",
            "database_max_overflow",
            "greater than or equal to 0",
        ),
        (
            "QAP_REDIS_MAX_CONNECTIONS",
            "0",
            "redis_max_connections",
            "greater than or equal to 1",
        ),
        (
            "QAP_S3_PRESIGNED_URL_TTL",
            "0",
            "s3_presigned_url_ttl",
            "greater than or equal to 1",
        ),
        (
            "QAP_JWT_ACCESS_TOKEN_TTL",
            "0",
            "jwt_access_token_ttl",
            "greater than or equal to 1",
        ),
        (
            "QAP_JWT_REFRESH_TOKEN_TTL",
            "0",
            "jwt_refresh_token_ttl",
            "greater than or equal to 1",
        ),
        (
            "QAP_MAX_CONCURRENT_RUNS",
            "0",
            "max_concurrent_runs",
            "greater than or equal to 1",
        ),
        (
            "QAP_MAX_CONCURRENT_PER_PROJECT",
            "0",
            "max_concurrent_per_project",
            "greater than or equal to 1",
        ),
        (
            "QAP_DEFAULT_TIMEOUT_SECONDS",
            "0",
            "default_timeout_seconds",
            "greater than or equal to 1",
        ),
        (
            "QAP_PREPARING_TIMEOUT_SECONDS",
            "0",
            "preparing_timeout_seconds",
            "greater than or equal to 1",
        ),
        (
            "QAP_COLLECTING_TIMEOUT_SECONDS",
            "0",
            "collecting_timeout_seconds",
            "greater than or equal to 1",
        ),
        (
            "QAP_MAX_EVENT_CHAIN_DEPTH",
            "0",
            "max_event_chain_depth",
            "greater than or equal to 1",
        ),
        (
            "QAP_RATE_LIMIT_PER_MINUTE",
            "0",
            "rate_limit_per_minute",
            "greater than or equal to 1",
        ),
        (
            "QAP_RATE_LIMIT_WINDOW_SECONDS",
            "0",
            "rate_limit_window_seconds",
            "greater than or equal to 1",
        ),
        (
            "QAP_RATE_LIMIT_AUTH_FAILURE",
            "0",
            "rate_limit_auth_failure",
            "greater than or equal to 1",
        ),
        (
            "QAP_RATE_LIMIT_AUTH_FAILURE_WINDOW",
            "0",
            "rate_limit_auth_failure_window",
            "greater than or equal to 1",
        ),
        (
            "QAP_RETENTION_RUNS_DAYS",
            "0",
            "retention_runs_days",
            "greater than or equal to 1",
        ),
        (
            "QAP_RETENTION_REPORTS_DAYS",
            "0",
            "retention_reports_days",
            "greater than or equal to 1",
        ),
        (
            "QAP_RETENTION_AUDIT_DAYS",
            "0",
            "retention_audit_days",
            "greater than or equal to 1",
        ),
    ],
)
def test_numeric_settings_reject_invalid_bounds(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    raw_value: str,
    expected_field: str,
    expected_msg: str,
):
    _set_required(monkeypatch)
    monkeypatch.setenv(env_key, raw_value)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "greater_than_equal",
            "loc": (expected_field,),
            "msg": f"Input should be {expected_msg}",
            "input": raw_value,
        }
    ]


@pytest.mark.parametrize(
    ("trusted_proxies", "expected_msg"),
    [
        (["not-a-cidr"], "trusted_proxies[0] must be a valid CIDR"),
        ([""], "trusted_proxies[0] must not be blank"),
        (
            ["10.0.0.0/8", "999.999.999.999/32"],
            "trusted_proxies[1] must be a valid CIDR",
        ),
    ],
)
def test_trusted_proxies_reject_invalid_cidrs(
    monkeypatch: pytest.MonkeyPatch,
    trusted_proxies: list[str],
    expected_msg: str,
):
    _set_required(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            trusted_proxies=trusted_proxies,
            _env_file=None,
        )

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "value_error",
            "loc": ("trusted_proxies",),
            "msg": f"Value error, {expected_msg}",
            "input": trusted_proxies,
        }
    ]


def test_trusted_proxies_accept_valid_cidrs_and_strip_whitespace(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_required(monkeypatch)

    settings = Settings(
        trusted_proxies=[" 10.0.0.0/8 ", "2001:db8::/32"],
        _env_file=None,
    )

    assert settings.trusted_proxies == ["10.0.0.0/8", "2001:db8::/32"]


def test_git_allowed_private_hosts_parse_comma_separated_env(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_GIT_ALLOWED_PRIVATE_HOSTS", " GitHub.com,gitlab.example ")

    settings = Settings(_env_file=None)

    assert settings.git_allowed_private_hosts == ["github.com", "gitlab.example"]


@pytest.mark.parametrize(
    ("hosts", "expected_msg"),
    [
        ([""], "git_allowed_private_hosts[0] must not be blank"),
        (
            ["https://github.com"],
            "git_allowed_private_hosts[0] must be a hostname, not a URL",
        ),
        (
            ["github.com:443"],
            "git_allowed_private_hosts[0] must be a hostname, not a URL",
        ),
    ],
)
def test_git_allowed_private_hosts_reject_invalid_hostnames(
    monkeypatch: pytest.MonkeyPatch,
    hosts: list[str],
    expected_msg: str,
):
    _set_required(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            git_allowed_private_hosts=hosts,
            _env_file=None,
        )

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "value_error",
            "loc": ("git_allowed_private_hosts",),
            "msg": f"Value error, {expected_msg}",
            "input": hosts,
        }
    ]


@pytest.mark.parametrize(
    ("env_key", "expected_field"),
    [
        ("QAP_S3_BUCKET", "s3_bucket"),
        ("QAP_S3_REGION", "s3_region"),
        ("QAP_DOCKER_HOST", "docker_host"),
        ("QAP_OTEL_SERVICE_NAME", "otel_service_name"),
    ],
)
def test_default_string_settings_reject_blank_values(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    expected_field: str,
):
    _set_required(monkeypatch)
    monkeypatch.setenv(env_key, "   ")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "value_error",
            "loc": (expected_field,),
            "msg": f"Value error, {expected_field} must not be blank",
            "input": "   ",
        }
    ]


def test_otel_exporter_endpoint_blank_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_OTEL_EXPORTER_ENDPOINT", "   ")

    settings = Settings(_env_file=None)

    assert settings.otel_exporter_endpoint is None


def test_cors_origins_reject_blank_entries(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            cors_origins=["http://localhost:5173", " "],
            _env_file=None,
        )

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "value_error",
            "loc": ("cors_origins",),
            "msg": "Value error, cors_origins[1] must not be blank",
            "input": ["http://localhost:5173", " "],
        }
    ]


def test_cors_origins_strip_whitespace(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)

    settings = Settings(
        cors_origins=[" http://localhost:5173 ", "https://app.example.com"],
        _env_file=None,
    )

    assert settings.cors_origins == [
        "http://localhost:5173",
        "https://app.example.com",
    ]


# --- Default values ---


def test_defaults_debug_false(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("QAP_DEBUG", raising=False)
    monkeypatch.setenv("QAP_DEBUG", "false")
    s = Settings(_env_file=None)
    assert s.debug is False


def test_defaults_enable_hsts_true(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.enable_hsts is True


def test_defaults_app_name(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.app_name == "QA Platform"


def test_defaults_environment_development(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.environment == "development"


def test_defaults_pool_and_overflow(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.database_pool_size == 10
    assert s.database_max_overflow == 20


def test_defaults_jwt_ttl(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.jwt_access_token_ttl == 3600
    assert s.jwt_refresh_token_ttl == 604800


def test_defaults_s3_bucket_and_region(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.s3_bucket == "qa-platform"
    assert s.s3_region == "us-east-1"


def test_defaults_retention(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.retention_runs_days == 90
    assert s.retention_reports_days == 30
    assert s.retention_audit_days == 1095


def test_worker_max_jobs_from_env(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_WORKER_MAX_JOBS", "12")

    s = Settings(_env_file=None)

    assert s.worker_max_jobs == 12


def test_defaults_otel_disabled(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    s = Settings(_env_file=None)
    assert s.otel_enabled is False
    assert s.otel_exporter_endpoint is None
    assert s.otel_service_name == "qa-platform"
    assert s.otel_sample_rate == 1.0


def test_otel_fields_from_env(monkeypatch: pytest.MonkeyPatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_OTEL_ENABLED", "true")
    monkeypatch.setenv("QAP_OTEL_EXPORTER_ENDPOINT", "http://tempo:4318/v1/traces")
    monkeypatch.setenv("QAP_OTEL_SERVICE_NAME", "qa-platform-api")
    monkeypatch.setenv("QAP_OTEL_SAMPLE_RATE", "0.5")

    s = Settings(_env_file=None)

    assert s.otel_enabled is True
    assert s.otel_exporter_endpoint == "http://tempo:4318/v1/traces"
    assert s.otel_service_name == "qa-platform-api"
    assert s.otel_sample_rate == 0.5


@pytest.mark.parametrize(
    ("sample_rate", "expected_type", "expected_msg"),
    [
        ("-0.1", "greater_than_equal", "Input should be greater than or equal to 0"),
        ("1.1", "less_than_equal", "Input should be less than or equal to 1"),
    ],
)
def test_otel_sample_rate_bounds(
    monkeypatch: pytest.MonkeyPatch,
    sample_rate: str,
    expected_type: str,
    expected_msg: str,
):
    _set_required(monkeypatch)
    monkeypatch.setenv("QAP_OTEL_SAMPLE_RATE", sample_rate)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": expected_type,
            "loc": ("otel_sample_rate",),
            "msg": expected_msg,
            "input": sample_rate,
        }
    ]


@pytest.mark.parametrize(
    ("encryption_keys", "expected_msg"),
    [
        ({0: "0" * 63}, "encryption_keys[0] must be 64 hex chars (32 bytes)"),
        ({1: "z" * 64}, "encryption_keys[1] must be 64 hex chars (32 bytes)"),
        ({16: "0" * 64}, "encryption key version must be 0-15"),
    ],
)
def test_encryption_keys_rotation_values_are_validated(
    monkeypatch: pytest.MonkeyPatch,
    encryption_keys: dict[int, str],
    expected_msg: str,
):
    _set_required(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            encryption_keys=encryption_keys,
            _env_file=None,
        )

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "value_error",
            "loc": ("encryption_keys",),
            "msg": f"Value error, {expected_msg}",
            "input": encryption_keys,
        }
    ]


# --- Required fields missing ---


def _env_without(key: str) -> dict[str, str]:
    return {k: v for k, v in REQUIRED_ENV.items() if k != key}


@pytest.mark.parametrize(
    ("missing_key", "expected_field"),
    [
        ("QAP_DATABASE_URL", "database_url"),
        ("QAP_REDIS_URL", "redis_url"),
        ("QAP_S3_ENDPOINT", "s3_endpoint"),
        ("QAP_S3_ACCESS_KEY", "s3_access_key"),
        ("QAP_S3_SECRET_KEY", "s3_secret_key"),
        ("QAP_JWT_SECRET", "jwt_secret"),
        ("QAP_ENCRYPTION_KEY", "encryption_key"),
    ],
)
def test_required_field_missing_raises(
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
    expected_field: str,
):
    for k, v in _env_without(missing_key).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(missing_key, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "missing",
            "loc": (expected_field,),
            "msg": "Field required",
            "input": _required_settings_input_without(missing_key),
        }
    ]


@pytest.mark.parametrize(
    ("env_key", "expected_field", "blank_value"),
    [
        ("QAP_DATABASE_URL", "database_url", ""),
        ("QAP_REDIS_URL", "redis_url", "   "),
        ("QAP_S3_ENDPOINT", "s3_endpoint", ""),
        ("QAP_S3_ACCESS_KEY", "s3_access_key", "   "),
        ("QAP_S3_SECRET_KEY", "s3_secret_key", ""),
        ("QAP_JWT_SECRET", "jwt_secret", " " * 32),
    ],
)
def test_required_string_fields_reject_blank_values(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    expected_field: str,
    blank_value: str,
):
    _set_required(monkeypatch)
    monkeypatch.setenv(env_key, blank_value)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "value_error",
            "loc": (expected_field,),
            "msg": f"Value error, {expected_field} must not be blank",
            "input": blank_value,
        }
    ]


@pytest.mark.parametrize(
    ("env_key", "raw_value", "expected_field", "expected_msg"),
    [
        (
            "QAP_LOG_LEVEL",
            "verbose",
            "log_level",
            "log_level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL",
        ),
        (
            "QAP_LOG_LEVEL",
            "   ",
            "log_level",
            "log_level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL",
        ),
        ("QAP_LOG_FORMAT", "yaml", "log_format", "log_format must be json or console"),
        ("QAP_LOG_FORMAT", "   ", "log_format", "log_format must be json or console"),
    ],
)
def test_log_configuration_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    raw_value: str,
    expected_field: str,
    expected_msg: str,
):
    _set_required(monkeypatch)
    monkeypatch.setenv(env_key, raw_value)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert _validation_error_projection(exc_info.value.errors()) == [
        {
            "type": "value_error",
            "loc": (expected_field,),
            "msg": f"Value error, {expected_msg}",
            "input": raw_value,
        }
    ]
