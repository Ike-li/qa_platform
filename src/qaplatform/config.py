import ipaddress
from typing import Annotated

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode


_HEX_CHARS = set("0123456789abcdefABCDEF")
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_LOG_FORMATS = {"json", "console"}


def _is_64_hex(value: str) -> bool:
    return len(value) == 64 and all(c in _HEX_CHARS for c in value)


class Settings(BaseSettings):
    # Core
    app_name: str = "QA Platform"
    debug: bool = False
    environment: str = "development"  # development / staging / production

    # Database
    database_url: str
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)

    # Redis
    redis_url: str
    redis_max_connections: int = Field(default=50, ge=1)

    # Object storage
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "qa-platform"
    s3_region: str = "us-east-1"
    s3_presigned_url_ttl: int = Field(
        default=3600,
        ge=1,
    )  # seconds; how long artifact download URLs stay valid

    # Security
    jwt_secret: str
    jwt_access_token_ttl: int = Field(default=3600, ge=1)  # 1h
    jwt_refresh_token_ttl: int = Field(default=604800, ge=1)  # 7d
    refresh_cookie_secure: bool | None = None
    encryption_key: str  # 32 bytes hex

    @field_validator(
        "database_url",
        "redis_url",
        "s3_endpoint",
        "s3_access_key",
        "s3_secret_key",
        "s3_bucket",
        "s3_region",
        "docker_host",
        "otel_service_name",
    )
    @classmethod
    def _required_string_not_blank(cls, v: str, info: ValidationInfo) -> str:
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return v

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_long_enough(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("jwt_secret must not be blank")
        if len(v.encode()) < 32:
            raise ValueError("jwt_secret must be >= 32 bytes (RFC 7518 Section 3.2)")
        return v

    @field_validator("encryption_key")
    @classmethod
    def _enc_key_is_64_hex(cls, v: str) -> str:
        if not _is_64_hex(v):
            raise ValueError("encryption_key must be 64 hex chars (32 bytes)")
        return v

    encryption_keys: dict[int, str] | None = (
        None  # {version: key_hex}, overrides encryption_key
    )

    @field_validator("encryption_keys")
    @classmethod
    def _enc_keys_are_64_hex(cls, v: dict[int, str] | None) -> dict[int, str] | None:
        if v is None:
            return v
        for version, key_hex in v.items():
            if version < 0 or version > 15:
                raise ValueError("encryption key version must be 0-15")
            if not _is_64_hex(key_hex):
                raise ValueError(
                    f"encryption_keys[{version}] must be 64 hex chars (32 bytes)"
                )
        return v

    enable_hsts: bool = True

    # Execution engine
    max_concurrent_runs: int = Field(default=5, ge=1)
    max_concurrent_per_project: int = Field(default=3, ge=1)
    worker_max_jobs: int = Field(default=10, ge=1)
    default_timeout_seconds: int = Field(default=1800, ge=1)
    preparing_timeout_seconds: int = Field(default=300, ge=1)
    collecting_timeout_seconds: int = Field(default=180, ge=1)
    max_event_chain_depth: int = Field(default=5, ge=1)
    docker_host: str = "unix:///var/run/docker.sock"
    git_allowed_private_hosts: Annotated[list[str], NoDecode] = []

    @field_validator("git_allowed_private_hosts", mode="before")
    @classmethod
    def _parse_git_allowed_private_hosts(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            if not v.strip():
                return []
            return [host.strip() for host in v.split(",")]
        return v

    @field_validator("git_allowed_private_hosts")
    @classmethod
    def _git_allowed_private_hosts_are_hostnames(cls, v: list[str]) -> list[str]:
        normalized: list[str] = []
        for index, hostname in enumerate(v):
            stripped = hostname.strip().lower()
            if not stripped:
                raise ValueError(
                    f"git_allowed_private_hosts[{index}] must not be blank"
                )
            if "/" in stripped or ":" in stripped:
                raise ValueError(
                    f"git_allowed_private_hosts[{index}] must be a hostname, not a URL"
                )
            normalized.append(stripped)
        return normalized

    # Rate limiting
    rate_limit_per_minute: int = Field(default=100, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_auth_failure: int = Field(default=5, ge=1)
    rate_limit_auth_failure_window: int = Field(default=60, ge=1)
    # CIDR blocks of trusted reverse proxies (e.g. ["10.0.0.0/8", "172.16.0.0/12"]).
    # Empty list (default) means no proxy is trusted; client.host is always used directly.
    trusted_proxies: list[str] = []

    @field_validator("trusted_proxies")
    @classmethod
    def _trusted_proxies_are_valid_cidrs(cls, v: list[str]) -> list[str]:
        normalized: list[str] = []
        for index, cidr in enumerate(v):
            stripped = cidr.strip()
            if not stripped:
                raise ValueError(f"trusted_proxies[{index}] must not be blank")
            try:
                ipaddress.ip_network(stripped, strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"trusted_proxies[{index}] must be a valid CIDR"
                ) from exc
            normalized.append(stripped)
        return normalized

    # Data retention
    retention_runs_days: int = Field(default=90, ge=1)
    retention_reports_days: int = Field(default=30, ge=1)
    retention_audit_days: int = Field(default=1095, ge=1)  # 3 years

    # Observability
    otel_enabled: bool = False
    otel_exporter_endpoint: str | None = None
    otel_service_name: str = "qa-platform"
    otel_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    log_level: str = "INFO"
    log_format: str = "json"  # json / console

    @field_validator("log_level")
    @classmethod
    def _log_level_is_supported(cls, v: str) -> str:
        normalized = v.strip().upper()
        if normalized not in _LOG_LEVELS:
            raise ValueError(
                "log_level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )
        return normalized

    @field_validator("log_format")
    @classmethod
    def _log_format_is_supported(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in _LOG_FORMATS:
            raise ValueError("log_format must be json or console")
        return normalized

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("otel_exporter_endpoint")
    @classmethod
    def _blank_otel_exporter_endpoint_is_unset(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            return None
        return v

    @field_validator("cors_origins")
    @classmethod
    def _cors_origins_not_blank(cls, v: list[str]) -> list[str]:
        normalized: list[str] = []
        for index, origin in enumerate(v):
            stripped = origin.strip()
            if not stripped:
                raise ValueError(f"cors_origins[{index}] must not be blank")
            normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def _production_security_hardening(self):
        """Reject insecure defaults in production (P1-1 mitigation)."""
        if self.environment.lower() != "production":
            return self

        # Reject debug=True in production
        if self.debug:
            raise ValueError(
                "Production environment must not run with debug=True "
                "(exposes /docs and /redoc API documentation)"
            )

        # Reject known placeholder JWT secrets
        _PLACEHOLDER_JWT_SECRETS = {
            "dev-jwt-secret-change-me-32-bytes-minimum",
            "change-me-in-production-at-least-32bytes",
            "test-jwt-secret-at-least-32bytes!",
            "placeholder-secret-change-me-in-production",
        }
        if self.jwt_secret in _PLACEHOLDER_JWT_SECRETS:
            raise ValueError(
                "Production environment must not use placeholder jwt_secret. "
                "Generate a strong secret with: openssl rand -hex 32"
            )

        # Reject all-zero encryption key
        if self.encryption_key == "0" * 64:
            raise ValueError(
                "Production environment must not use all-zero encryption_key. "
                "Generate a strong key with: openssl rand -hex 32"
            )

        return self

    model_config = {"env_file": ".env", "env_prefix": "QAP_", "extra": "ignore"}
