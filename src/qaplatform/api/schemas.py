from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from qaplatform.domain.models.common import (
    PaginatedResponse as PaginatedResponse,
    PaginationParams as PaginationParams,
)
from qaplatform.domain.models.project import SilentWindow

_IMAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-/:]*(:[a-zA-Z0-9._\-]+)?(@sha256:[a-f0-9]+)?$")


# ── Unified error ────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    code: str
    message: str
    details: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    error: ErrorDetail


# ── Project schemas ──────────────────────────────────────────────────────────

def _validate_project_settings(settings: dict | None) -> dict | None:
    if settings is None:
        return None

    allowed = settings.get("allowed_branches")
    if allowed is not None:
        if not isinstance(allowed, list):
            raise ValueError("settings.allowed_branches must be a list of strings")
        if len(allowed) > 50:
            raise ValueError("settings.allowed_branches must contain at most 50 entries")
        for pattern in allowed:
            if not isinstance(pattern, str):
                raise ValueError("settings.allowed_branches entries must be strings")
            if not pattern.strip():
                raise ValueError("settings.allowed_branches entries must be non-empty")
            if len(pattern) > 200:
                raise ValueError("settings.allowed_branches entries must be at most 200 characters")

    silent_windows = settings.get("silent_windows")
    if silent_windows is None:
        return settings
    if not isinstance(silent_windows, list):
        raise ValueError("settings.silent_windows must be a list")
    if len(silent_windows) > 20:
        raise ValueError("settings.silent_windows must contain at most 20 entries")
    return {
        **settings,
        "silent_windows": [
            SilentWindow.model_validate(window).model_dump(mode="json")
            for window in silent_windows
        ],
    }


class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=100)
    slug: str = Field(..., max_length=50)
    description: str | None = Field(None, max_length=500)
    git_url: str = Field(..., max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] = "none"
    credential_id: UUID | None = None
    default_branch: str = Field("main", max_length=100)
    root_path: str = Field(".", max_length=255)
    shallow_clone: bool = True
    default_env_id: UUID | None = None
    settings: dict = Field(default_factory=dict)

    @field_validator("settings")
    @classmethod
    def _check_settings(cls, v: dict) -> dict:
        return _validate_project_settings(v) or {}


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=500)
    git_url: str | None = Field(None, max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] | None = None
    credential_id: UUID | None = None
    default_branch: str | None = Field(None, max_length=100)
    root_path: str | None = Field(None, max_length=255)
    shallow_clone: bool | None = None
    default_env_id: UUID | None = None
    settings: dict | None = None
    silent_windows: list[SilentWindow] | None = Field(None, max_length=20)
    status: Literal["active", "archived"] | None = None

    @field_validator("settings")
    @classmethod
    def _check_settings(cls, v: dict | None) -> dict | None:
        return _validate_project_settings(v)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    description: str | None = None
    git_url: str
    git_auth_method: Literal["none", "token", "ssh_key"] = "none"
    credential_id: UUID | None = None
    default_branch: str = "main"
    root_path: str = "."
    shallow_clone: bool = True
    default_env_id: UUID | None = None
    settings: dict = Field(default_factory=dict)
    silent_windows: list[SilentWindow] = Field(default_factory=list, max_length=20)
    status: Literal["active", "archived"] = "active"
    created_by: UUID
    created_at: datetime
    updated_at: datetime


# ── Environment schemas ─────────────────────────────────────────────────────

_BLOCKED_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "SHELL", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "PYTHONPATH",
    "NODE_PATH", "GOPATH", "GOROOT", "CLASSPATH",
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "no_proxy", "NO_PROXY",
})


def _validate_blocked_env_keys(v: dict[str, str]) -> dict[str, str]:
    blocked = _BLOCKED_ENV_KEYS & v.keys()
    if blocked:
        raise ValueError(f"Blocked env var keys: {', '.join(sorted(blocked))}")
    return v


class EnvironmentCreate(BaseModel):
    name: str = Field(..., max_length=100)
    base_image: str = Field(..., max_length=255)
    setup_script: str | None = Field(None, max_length=10000)
    memory_mb: int = 512
    cpu_cores: float = 1.0
    max_artifact_size_mb: int = 100
    max_artifacts_count: int = 50
    network_policy: Literal["allow", "deny", "restricted"] = "deny"
    env_vars: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = Field(None, max_length=100)

    @field_validator("base_image")
    @classmethod
    def _validate_base_image(cls, v: str) -> str:
        if not _IMAGE_RE.match(v):
            raise ValueError(f"Invalid Docker image name: {v!r}")
        return v

    @field_validator("env_vars")
    @classmethod
    def _check_env_keys(cls, v: dict[str, str]) -> dict[str, str]:
        return _validate_blocked_env_keys(v)


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    base_image: str | None = Field(None, max_length=255)
    setup_script: str | None = Field(None, max_length=10000)
    memory_mb: int | None = None
    cpu_cores: float | None = None
    max_artifact_size_mb: int | None = None
    max_artifacts_count: int | None = None
    network_policy: Literal["allow", "deny", "restricted"] | None = None
    env_vars: dict[str, str] | None = None
    cache_key: str | None = Field(None, max_length=100)

    @field_validator("base_image")
    @classmethod
    def _validate_base_image(cls, v: str | None) -> str | None:
        if v is not None and not _IMAGE_RE.match(v):
            raise ValueError(f"Invalid Docker image name: {v!r}")
        return v

    @field_validator("env_vars")
    @classmethod
    def _check_env_keys(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        return _validate_blocked_env_keys(v)


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    base_image: str
    setup_script: str | None = None
    memory_mb: int = 512
    cpu_cores: float = 1.0
    max_artifact_size_mb: int = 100
    max_artifacts_count: int = 50
    network_policy: Literal["allow", "deny", "restricted"] = "deny"
    env_vars: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = None
    created_at: datetime


# ── Pipeline schemas ─────────────────────────────────────────────────────────

class StageDefinitionInput(BaseModel):
    name: str = Field(..., max_length=100)
    plugin: str = Field(..., max_length=50)
    config: dict = Field(default_factory=dict)
    continue_on_error: bool = False
    phase: Literal["prepare", "execute", "collect", "notify"] | None = None


class TestSelectorInput(BaseModel):
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    expression: str | None = Field(None, max_length=1000)
    regex: str | None = Field(None, max_length=1000)
    on_empty: Literal["fail", "skip", "warn"] = "fail"


class RetryPolicyInput(BaseModel):
    max_attempts: int = Field(1, ge=1, le=5)
    retry_on: list[str] = Field(default_factory=list)
    backoff_seconds: int = Field(0, ge=0)
    scope: Literal["pipeline", "stage"] = "pipeline"


class TriggerConfigInput(BaseModel):
    type: str = "manual"
    dedup_window_seconds: int | None = None
    source: dict = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    target: dict = Field(default_factory=dict)


class PipelineCreate(BaseModel):
    name: str = Field(..., max_length=100)
    stages: list[StageDefinitionInput] = Field(default_factory=list)
    selector: TestSelectorInput = Field(default_factory=TestSelectorInput)
    trigger_config: TriggerConfigInput = Field(default_factory=TriggerConfigInput)
    timeout_seconds: int = Field(default=1800, le=86400)
    retry_policy: RetryPolicyInput | None = None
    enabled: bool = True


class PipelineUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    stages: list[StageDefinitionInput] | None = None
    selector: TestSelectorInput | None = None
    trigger_config: TriggerConfigInput | None = None
    timeout_seconds: int | None = Field(None, le=86400)
    retry_policy: RetryPolicyInput | None = None
    enabled: bool | None = None


class PipelineResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    stages: list[StageDefinitionInput] = Field(default_factory=list)
    selector: TestSelectorInput = Field(default_factory=TestSelectorInput)
    trigger_config: TriggerConfigInput = Field(default_factory=TriggerConfigInput)
    timeout_seconds: int = 1800
    retry_policy: RetryPolicyInput | None = None
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


# ── Run schemas ──────────────────────────────────────────────────────────────

class RunTrigger(BaseModel):
    pipeline_id: UUID
    git_ref: str | None = None
    priority: int = Field(default=1, ge=0, le=2, description="0=HIGH, 1=MEDIUM, 2=LOW")


class RunCancel(BaseModel):
    reason: str | None = None


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    pipeline_id: UUID
    pipeline_name: str
    environment_id: UUID
    status: str
    trigger_type: str
    priority: int = 1
    triggered_by: UUID | None = None
    git_ref: str
    git_sha: str | None = None
    attempt: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    summary: dict | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RunListFilter(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    status: str | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    sort: str = "-created_at"


class TestResultResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    run_id: UUID
    suite: str
    name: str
    status: str
    duration_ms: int = 0
    error_message: str | None = None
    stack_trace: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    run_id: UUID
    type: str
    name: str
    storage_path: str
    size_bytes: int
    mime_type: str
    expires_at: datetime | None = None
    created_at: datetime


# ── Project member schemas ───────────────────────────────────────────────────


class ProjectMemberCreate(BaseModel):
    user_id: UUID
    role: Literal["admin", "developer", "viewer"]


class ProjectMemberUpdate(BaseModel):
    role: Literal["admin", "developer", "viewer"]


class ProjectMemberResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    project_id: UUID
    user_id: UUID
    username: str
    email: str
    role: str
    created_at: datetime


# ── Credential schemas ──────────────────────────────────────────────────────


class CredentialCreate(BaseModel):
    name: str = Field(..., max_length=100)
    type: Literal["token", "ssh_key", "password"]
    value: str = Field(..., min_length=1, max_length=65536)


class CredentialUpdate(BaseModel):
    value: str = Field(..., min_length=1, max_length=65536)


class CredentialResponse(BaseModel):
    """Credential metadata. The plaintext ``value`` is never returned by the API."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    type: str
    created_by: UUID
    created_at: datetime


# ── Schedule schemas ────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    pipeline_id: UUID
    cron_expr: str = Field(..., min_length=1, max_length=100)
    timezone: str = Field("Asia/Shanghai", max_length=50)
    missed_fire_policy: Literal["skip", "run_once", "run_all"] = "skip"
    quiet_windows: list[dict] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("cron_expr")
    @classmethod
    def validate_cron_expr(cls, v: str) -> str:
        from croniter import croniter
        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron expression: {v}")
        return v


class ScheduleUpdate(BaseModel):
    cron_expr: str | None = Field(None, min_length=1, max_length=100)
    timezone: str | None = Field(None, max_length=50)
    missed_fire_policy: Literal["skip", "run_once", "run_all"] | None = None
    quiet_windows: list[dict] | None = None
    enabled: bool | None = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    pipeline_id: UUID
    cron_expr: str
    timezone: str
    missed_fire_policy: str
    quiet_windows: list[dict]
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_error: str | None
    created_at: datetime


# ── Notification schemas ───────────────────────────────────────────────────

class NotificationRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    enabled: bool = True
    conditions: list[dict] = Field(default_factory=list)
    channels: list[dict] = Field(..., min_length=1)
    template: str | None = None


class NotificationRuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    enabled: bool | None = None
    conditions: list[dict] | None = None
    channels: list[dict] | None = None
    template: str | None = None


class NotificationRuleResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    enabled: bool
    conditions: list[dict]
    channels: list[dict]
    template: str | None
    created_at: datetime


class NotificationLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    run_id: UUID
    rule_id: UUID
    channel_type: str
    status: str
    error_message: str | None
    sent_at: datetime


# ── Webhook schemas ─────────────────────────────────────────────────────────

class WebhookTriggerRequest(BaseModel):
    git_ref: str = Field(..., min_length=1, max_length=200)
    git_sha: str | None = None
    metadata: dict = Field(default_factory=dict)


# ── Batch schemas ───────────────────────────────────────────────────────────

class BatchRunRequest(BaseModel):
    run_ids: list[UUID] = Field(..., min_length=1, max_length=50)


class BatchRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    processed: int
    failed: int
    errors: list[str] = Field(default_factory=list)


# ── Analytics schemas ───────────────────────────────────────────────────────

class TrendDataPoint(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    date: str
    total_runs: int
    passed_runs: int
    failed_runs: int
    pass_rate: float


class FlakyTest(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    suite: str
    name: str
    total_runs: int
    failed_count: int
    passed_count: int
    flaky_rate: float


# ── Analytics paginated wrappers ─────────────────────────────────────────────

class AnalyticsPaginationMeta(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    offset: int
    limit: int
    total: int


class TrendsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    data: list[TrendDataPoint]
    pagination: AnalyticsPaginationMeta


class FlakyResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    data: list[FlakyTest]
    pagination: AnalyticsPaginationMeta
