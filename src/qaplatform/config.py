from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    app_name: str = "QA Platform"
    debug: bool = False
    environment: str = "development"  # development / staging / production

    # Database
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str
    redis_max_connections: int = 50

    # Object storage
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "qa-platform"
    s3_region: str = "us-east-1"
    s3_presigned_url_ttl: int = 3600  # seconds; how long artifact download URLs stay valid

    # Security
    jwt_secret: str
    jwt_access_token_ttl: int = 3600  # 1h
    jwt_refresh_token_ttl: int = 604800  # 7d
    encryption_key: str  # 32 bytes hex

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_long_enough(cls, v: str) -> str:
        if len(v.encode()) < 32:
            raise ValueError("jwt_secret must be >= 32 bytes (RFC 7518 Section 3.2)")
        return v

    @field_validator("encryption_key")
    @classmethod
    def _enc_key_is_64_hex(cls, v: str) -> str:
        if len(v) != 64 or not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("encryption_key must be 64 hex chars (32 bytes)")
        return v
    encryption_keys: dict[int, str] | None = None  # {version: key_hex}, overrides encryption_key
    enable_hsts: bool = True

    # Execution engine
    max_concurrent_runs: int = 5
    max_concurrent_per_project: int = 3
    worker_max_jobs: int = Field(default=10, ge=1)
    default_timeout_seconds: int = 1800
    preparing_timeout_seconds: int = 300
    collecting_timeout_seconds: int = 180
    max_event_chain_depth: int = 5
    docker_host: str = "unix:///var/run/docker.sock"

    # Rate limiting
    rate_limit_per_minute: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_auth_failure: int = 5
    rate_limit_auth_failure_window: int = 60
    # CIDR blocks of trusted reverse proxies (e.g. ["10.0.0.0/8", "172.16.0.0/12"]).
    # Empty list (default) means no proxy is trusted; client.host is always used directly.
    trusted_proxies: list[str] = []

    # Data retention
    retention_runs_days: int = 90
    retention_reports_days: int = 30
    retention_audit_days: int = 1095  # 3 years

    # Observability
    otel_enabled: bool = False
    otel_exporter_endpoint: str | None = None
    otel_service_name: str = "qa-platform"
    otel_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    log_level: str = "INFO"
    log_format: str = "json"  # json / console

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_prefix": "QAP_", "extra": "ignore"}
