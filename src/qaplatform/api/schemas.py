from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from qaplatform.domain.models.common import (
    PaginatedResponse as PaginatedResponse,
    PaginationParams as PaginationParams,
)
from qaplatform.domain.models.notification import (
    NOTIFICATION_CHANNEL_TYPES,
    normalize_notification_channel,
    normalize_notification_conditions,
    validate_notification_conditions,
)
from qaplatform.domain.models.project import SilentWindow

_IMAGE_TAG_RE = re.compile(r"^[a-zA-Z0-9._/\-]+:[a-zA-Z0-9._\-]+$")
_BLOCKED_IMAGE_TAGS = {"latest", "stable", "edge"}
_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

RunStatusValue = Literal[
    "queued",
    "preparing",
    "running",
    "collecting",
    "done",
    "failed",
    "cancelled",
    "timeout",
]
ProjectStatusValue = Literal["active", "archived"]
TestResultStatusValue = Literal["passed", "failed", "error", "skipped", "xfail"]
SelectorPathValue = Annotated[str, Field(min_length=1, max_length=1000)]
SelectorTagValue = Annotated[str, Field(min_length=1, max_length=100)]
RetryReasonValue = Annotated[str, Field(min_length=1, max_length=100)]


def validate_pinned_base_image(image: str) -> str:
    if not _IMAGE_TAG_RE.match(image):
        raise ValueError("Image must use format 'registry/name:tag'")
    tag = image.rsplit(":", 1)[-1]
    if tag.lower() in _BLOCKED_IMAGE_TAGS:
        raise ValueError(f"Tag ':{tag}' is not allowed; pin a specific version")
    return image


def validate_timezone_name(timezone_name: str | None) -> str | None:
    if timezone_name is None:
        return None
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid timezone: {timezone_name}") from exc
    return timezone_name


def validate_schedule_quiet_windows(windows: list[dict] | None) -> list[dict] | None:
    if windows is None:
        return None

    normalized: list[dict] = []
    for index, window in enumerate(windows):
        if not isinstance(window, dict):
            raise ValueError(f"quiet_windows[{index}] must be an object")

        start = window.get("start")
        end = window.get("end")
        if not isinstance(start, str) or not _HH_MM_RE.match(start):
            raise ValueError(f"quiet_windows[{index}].start must use HH:MM")
        if not isinstance(end, str) or not _HH_MM_RE.match(end):
            raise ValueError(f"quiet_windows[{index}].end must use HH:MM")

        timezone_name = window.get("timezone", "Asia/Shanghai")
        if not isinstance(timezone_name, str):
            raise ValueError(f"quiet_windows[{index}].timezone must be a string")
        validate_timezone_name(timezone_name)

        normalized.append(
            {
                "start": start,
                "end": end,
                "timezone": timezone_name,
            }
        )
    return normalized


def validate_schedule_cron_expr(cron_expr: str) -> str:
    from croniter import croniter

    if not croniter.is_valid(cron_expr):
        raise ValueError(f"invalid cron expression: {cron_expr}")
    return cron_expr


def validate_optional_schedule_cron_expr(cron_expr: str | None) -> str | None:
    if cron_expr is None:
        return None
    return validate_schedule_cron_expr(cron_expr)


def validate_notification_channels(channels: list[dict] | None) -> list[dict] | None:
    if channels is None:
        return None

    seen: set[str] = set()
    normalized_channels: list[dict] = []
    for index, channel in enumerate(channels):
        channel_type = channel.get("type") if isinstance(channel, dict) else None
        if not isinstance(channel_type, str) or not channel_type:
            raise ValueError(f"channels[{index}].type is required")
        if channel_type not in NOTIFICATION_CHANNEL_TYPES:
            allowed = ", ".join(sorted(NOTIFICATION_CHANNEL_TYPES))
            raise ValueError(
                f"unsupported notification channel type: {channel_type}; allowed: {allowed}"
            )
        if channel_type in seen:
            raise ValueError(f"duplicate notification channel type: {channel_type}")
        if "config" in channel and channel["config"] is not None and not isinstance(channel["config"], dict):
            raise ValueError(f"channels[{index}].config must be an object")
        seen.add(channel_type)
        normalized_channels.append(normalize_notification_channel(channel))
    return normalized_channels


def validate_notification_rule_name(name: str | None) -> str | None:
    if name is not None and name.strip() == "":
        raise ValueError("notification rule name must not be blank")
    return name


def validate_credential_name(name: str) -> str:
    if name.strip() == "":
        raise ValueError("credential name must not be blank")
    return name


def validate_environment_text(field_name: str, value: str | None) -> str | None:
    if value is not None and value.strip() == "":
        raise ValueError(f"environment {field_name} must not be blank")
    return value


def validate_project_text(field_name: str, value: str | None) -> str | None:
    if value is not None and value.strip() == "":
        raise ValueError(f"project {field_name} must not be blank")
    return value


def validate_run_git_ref(git_ref: str | None) -> str | None:
    if git_ref is not None and git_ref.strip() == "":
        raise ValueError("run git_ref must not be blank")
    return git_ref


def validate_webhook_git_ref(git_ref: str) -> str:
    if git_ref.strip() == "":
        raise ValueError("webhook git_ref must not be blank")
    return git_ref


def validate_webhook_git_sha(git_sha: str | None) -> str | None:
    if git_sha is not None and git_sha.strip() == "":
        raise ValueError("webhook git_sha must not be blank")
    return git_sha


def validate_pipeline_text(field_name: str, value: str | None) -> str | None:
    if value is not None and value.strip() == "":
        raise ValueError(f"pipeline {field_name} must not be blank")
    return value


def validate_pipeline_text_list(field_name: str, values: list[str]) -> list[str]:
    for index, value in enumerate(values):
        if value.strip() == "":
            raise ValueError(f"pipeline {field_name}[{index}] must not be blank")
    return values


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
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(None, max_length=500)
    git_url: str = Field(..., min_length=1, max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] = "none"
    credential_id: UUID | None = None
    default_branch: str = Field("main", min_length=1, max_length=100)
    root_path: str = Field(".", min_length=1, max_length=255)
    shallow_clone: bool = True
    default_env_id: UUID | None = None
    settings: dict = Field(default_factory=dict)

    @field_validator("settings")
    @classmethod
    def _check_settings(cls, v: dict) -> dict:
        return _validate_project_settings(v) or {}

    @field_validator("name", "git_url", "default_branch", "root_path")
    @classmethod
    def _validate_text_fields(cls, v: str | None, info: ValidationInfo) -> str | None:
        return validate_project_text(info.field_name, v)


class GitBranchDiscoveryRequest(BaseModel):
    git_url: str = Field(..., min_length=1, max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] = "none"

    @field_validator("git_url")
    @classmethod
    def _validate_git_url(cls, v: str) -> str:
        return validate_project_text("git_url", v)


class GitBranchDiscoveryResponse(BaseModel):
    branches: list[str]
    default_branch: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    git_url: str | None = Field(None, min_length=1, max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] | None = None
    credential_id: UUID | None = None
    default_branch: str | None = Field(None, min_length=1, max_length=100)
    root_path: str | None = Field(None, min_length=1, max_length=255)
    shallow_clone: bool | None = None
    default_env_id: UUID | None = None
    settings: dict | None = None
    silent_windows: list[SilentWindow] | None = Field(None, max_length=20)
    status: ProjectStatusValue | None = None

    @field_validator("settings")
    @classmethod
    def _check_settings(cls, v: dict | None) -> dict | None:
        return _validate_project_settings(v)

    @field_validator("name", "git_url", "default_branch", "root_path")
    @classmethod
    def _validate_text_fields(cls, v: str | None, info: ValidationInfo) -> str | None:
        return validate_project_text(info.field_name, v)


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
    status: ProjectStatusValue = "active"
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
    name: str = Field(..., min_length=1, max_length=100)
    base_image: str = Field(..., max_length=255)
    setup_script: str | None = Field(None, max_length=10000)
    memory_mb: int = Field(512, ge=1)
    cpu_cores: float = Field(1.0, gt=0)
    disk_mb: int | None = Field(None, ge=1)
    max_artifact_size_mb: int = Field(100, ge=1)
    max_artifacts_count: int = Field(50, ge=1)
    network_policy: Literal["allow", "deny", "restricted"] = "deny"
    env_vars: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = Field(None, min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return validate_environment_text("name", v)

    @field_validator("cache_key")
    @classmethod
    def _validate_cache_key(cls, v: str | None) -> str | None:
        return validate_environment_text("cache_key", v)

    @field_validator("base_image")
    @classmethod
    def _validate_base_image(cls, v: str) -> str:
        return validate_pinned_base_image(v)

    @field_validator("env_vars")
    @classmethod
    def _check_env_keys(cls, v: dict[str, str]) -> dict[str, str]:
        return _validate_blocked_env_keys(v)


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    base_image: str | None = Field(None, max_length=255)
    setup_script: str | None = Field(None, max_length=10000)
    memory_mb: int | None = Field(None, ge=1)
    cpu_cores: float | None = Field(None, gt=0)
    disk_mb: int | None = Field(None, ge=1)
    max_artifact_size_mb: int | None = Field(None, ge=1)
    max_artifacts_count: int | None = Field(None, ge=1)
    network_policy: Literal["allow", "deny", "restricted"] | None = None
    env_vars: dict[str, str] | None = None
    cache_key: str | None = Field(None, min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        return validate_environment_text("name", v)

    @field_validator("cache_key")
    @classmethod
    def _validate_cache_key(cls, v: str | None) -> str | None:
        return validate_environment_text("cache_key", v)

    @field_validator("base_image")
    @classmethod
    def _validate_base_image(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_pinned_base_image(v)

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
    disk_mb: int | None = None
    max_artifact_size_mb: int = 100
    max_artifacts_count: int = 50
    network_policy: Literal["allow", "deny", "restricted"] = "deny"
    env_vars: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = None
    created_at: datetime


# ── Pipeline schemas ─────────────────────────────────────────────────────────

class StageDefinitionInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    plugin: str = Field(..., min_length=1, max_length=50)
    config: dict = Field(default_factory=dict)
    continue_on_error: bool = False
    phase: Literal["prepare", "execute", "collect", "notify"] | None = None

    @field_validator("name", "plugin")
    @classmethod
    def validate_text(cls, value: str, info: ValidationInfo) -> str:
        return validate_pipeline_text(f"stage {info.field_name}", value)


class TestSelectorInput(BaseModel):
    include_paths: list[SelectorPathValue] = Field(default_factory=list, max_length=100)
    exclude_paths: list[SelectorPathValue] = Field(default_factory=list, max_length=100)
    tags: list[SelectorTagValue] = Field(default_factory=list, max_length=100)
    expression: str | None = Field(None, max_length=1000)
    regex: str | None = Field(None, max_length=1000)
    on_empty: Literal["fail", "skip", "warn"] = "fail"

    @field_validator("include_paths", "exclude_paths", "tags")
    @classmethod
    def validate_text_list(cls, values: list[str], info: ValidationInfo) -> list[str]:
        return validate_pipeline_text_list(f"selector {info.field_name}", values)


class RetryPolicyInput(BaseModel):
    max_attempts: int = Field(1, ge=1, le=5)
    retry_on: list[RetryReasonValue] = Field(default_factory=list, max_length=20)
    backoff_seconds: int = Field(0, ge=0)
    scope: Literal["pipeline", "stage"] = "pipeline"

    @field_validator("retry_on")
    @classmethod
    def validate_retry_on(cls, values: list[str]) -> list[str]:
        return validate_pipeline_text_list("retry_policy retry_on", values)


class TriggerConfigInput(BaseModel):
    type: str = Field("manual", min_length=1, max_length=50)
    dedup_window_seconds: int | None = Field(None, ge=0)
    source: dict = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    target: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        return validate_pipeline_text("trigger_config type", value)


class CollectorDefinitionInput(BaseModel):
    plugin: str = Field("junit", min_length=1, max_length=50)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("plugin")
    @classmethod
    def validate_plugin(cls, value: str) -> str:
        return validate_pipeline_text("collector plugin", value)


class PipelineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    stages: list[StageDefinitionInput] = Field(default_factory=list)
    selector: TestSelectorInput = Field(default_factory=TestSelectorInput)
    trigger_config: TriggerConfigInput = Field(default_factory=TriggerConfigInput)
    collectors: list[CollectorDefinitionInput] = Field(
        default_factory=lambda: [CollectorDefinitionInput()],
        min_length=1,
        max_length=10,
    )
    timeout_seconds: int = Field(default=1800, ge=1, le=86400)
    retry_policy: RetryPolicyInput | None = None
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_pipeline_text("name", value)


class PipelineUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    stages: list[StageDefinitionInput] | None = None
    selector: TestSelectorInput | None = None
    trigger_config: TriggerConfigInput | None = None
    collectors: list[CollectorDefinitionInput] | None = Field(
        None,
        min_length=1,
        max_length=10,
    )
    timeout_seconds: int | None = Field(None, ge=1, le=86400)
    retry_policy: RetryPolicyInput | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return validate_pipeline_text("name", value)


class PipelineResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    stages: list[StageDefinitionInput] = Field(default_factory=list)
    selector: TestSelectorInput = Field(default_factory=TestSelectorInput)
    trigger_config: TriggerConfigInput = Field(default_factory=TriggerConfigInput)
    collectors: list[CollectorDefinitionInput] = Field(
        default_factory=lambda: [CollectorDefinitionInput()],
    )
    timeout_seconds: int = 1800
    retry_policy: RetryPolicyInput | None = None
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


# ── Run schemas ──────────────────────────────────────────────────────────────

class RunTrigger(BaseModel):
    pipeline_id: UUID
    git_ref: str | None = Field(None, min_length=1, max_length=200)
    git_sha: str | None = Field(
        None,
        pattern=r"^[0-9a-fA-F]{40}$",
        description="Optional full Git commit SHA to execute",
    )
    environment_id: UUID | None = None
    priority: int = Field(default=1, ge=0, le=2, description="0=HIGH, 1=MEDIUM, 2=LOW")

    @field_validator("git_ref")
    @classmethod
    def validate_git_ref(cls, git_ref: str | None) -> str | None:
        return validate_run_git_ref(git_ref)


class RunCancel(BaseModel):
    reason: str | None = Field(None, max_length=500)


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    pipeline_id: UUID
    pipeline_name: str
    environment_id: UUID
    status: RunStatusValue
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
    status: TestResultStatusValue
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


class RunLogEntryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    stream: str
    line: str


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
    name: str = Field(..., min_length=1, max_length=100)
    type: Literal["token", "ssh_key", "password"]
    value: str = Field(..., min_length=1, max_length=65536)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return validate_credential_name(name)


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
    timezone: str = Field("Asia/Shanghai", min_length=1, max_length=50)
    missed_fire_policy: Literal["skip", "run_once", "run_all"] = "skip"
    quiet_windows: list[dict] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("cron_expr")
    @classmethod
    def validate_cron_expr(cls, v: str) -> str:
        return validate_schedule_cron_expr(v)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        return validate_timezone_name(v)

    @field_validator("quiet_windows")
    @classmethod
    def validate_quiet_windows(cls, v: list[dict]) -> list[dict]:
        return validate_schedule_quiet_windows(v) or []


class ScheduleUpdate(BaseModel):
    cron_expr: str | None = Field(None, min_length=1, max_length=100)
    timezone: str | None = Field(None, min_length=1, max_length=50)
    missed_fire_policy: Literal["skip", "run_once", "run_all"] | None = None
    quiet_windows: list[dict] | None = None
    enabled: bool | None = None

    @field_validator("cron_expr")
    @classmethod
    def validate_cron_expr(cls, v: str | None) -> str | None:
        return validate_optional_schedule_cron_expr(v)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        return validate_timezone_name(v)

    @field_validator("quiet_windows")
    @classmethod
    def validate_quiet_windows(cls, v: list[dict] | None) -> list[dict] | None:
        return validate_schedule_quiet_windows(v)


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

NotificationChannelType = Literal["email", "webhook", "dingtalk", "wecom"]


class NotificationChannelPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: NotificationChannelType
    config: dict[str, Any] = Field(default_factory=dict)
    template: str | None = None


NotificationConditionField = Literal[
    "status",
    "pass_rate",
    "failed",
    "consecutive_failures",
]
NotificationConditionOperator = Literal["eq", "ne", "lt", "gt", "lte", "gte"]


class NotificationConditionLeaf(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: NotificationConditionField
    operator: NotificationConditionOperator = "eq"
    value: str | int | float | bool


class NotificationConditionAllGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    all: list[NotificationConditionExpression] = Field(..., min_length=1)


class NotificationConditionAnyGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    any: list[NotificationConditionExpression] = Field(..., min_length=1)


NotificationConditionExpression: TypeAlias = (
    NotificationConditionLeaf | NotificationConditionAllGroup | NotificationConditionAnyGroup
)


class NotificationInvalidCondition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    invalid: Literal[True] = True
    reason: str
    raw_field: str | None = None
    raw_operator: str | None = None


class NotificationConditionResponseAllGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    all: list[NotificationConditionResponseExpression] = Field(..., min_length=1)


class NotificationConditionResponseAnyGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    any: list[NotificationConditionResponseExpression] = Field(..., min_length=1)


NotificationConditionResponseExpression: TypeAlias = (
    NotificationConditionLeaf
    | NotificationConditionResponseAllGroup
    | NotificationConditionResponseAnyGroup
    | NotificationInvalidCondition
)


class NotificationRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    enabled: bool = True
    conditions: list[NotificationConditionExpression] = Field(default_factory=list)
    channels: list[NotificationChannelPayload] = Field(..., min_length=1)
    template: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return validate_notification_rule_name(name)

    @field_validator("channels", mode="before")
    @classmethod
    def validate_channels(cls, channels: list[dict]) -> list[dict]:
        return validate_notification_channels(channels) or []

    @field_validator("conditions", mode="before")
    @classmethod
    def validate_conditions(cls, conditions: list[dict]) -> list[dict]:
        return validate_notification_conditions(conditions) or []


class NotificationRuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    enabled: bool | None = None
    conditions: list[NotificationConditionExpression] | None = None
    channels: list[NotificationChannelPayload] | None = Field(None, min_length=1)
    template: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str | None) -> str | None:
        return validate_notification_rule_name(name)

    @field_validator("channels", mode="before")
    @classmethod
    def validate_channels(cls, channels: list[dict] | None) -> list[dict] | None:
        return validate_notification_channels(channels)

    @field_validator("conditions", mode="before")
    @classmethod
    def validate_conditions(cls, conditions: list[dict] | None) -> list[dict] | None:
        return validate_notification_conditions(conditions)


class NotificationRuleResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    enabled: bool
    conditions: list[NotificationConditionResponseExpression]
    channels: list[NotificationChannelPayload]
    template: str | None
    created_at: datetime

    @field_validator("conditions", mode="before")
    @classmethod
    def normalize_conditions(cls, conditions: list[dict]) -> list[dict]:
        return normalize_notification_conditions(conditions) or []

    @field_validator("channels", mode="before")
    @classmethod
    def normalize_channels(cls, channels: list[dict]) -> list[dict]:
        return [normalize_notification_channel(channel) for channel in channels]


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
    git_sha: str | None = Field(None, min_length=1, max_length=100)
    metadata: dict = Field(default_factory=dict)

    @field_validator("git_ref")
    @classmethod
    def validate_git_ref(cls, git_ref: str) -> str:
        return validate_webhook_git_ref(git_ref)

    @field_validator("git_sha")
    @classmethod
    def validate_git_sha(cls, git_sha: str | None) -> str | None:
        return validate_webhook_git_sha(git_sha)


# ── Batch schemas ───────────────────────────────────────────────────────────

class BatchRunRequest(BaseModel):
    run_ids: list[UUID] = Field(..., min_length=1, max_length=50)

    @field_validator("run_ids")
    @classmethod
    def validate_unique_run_ids(cls, v: list[UUID]) -> list[UUID]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate run_ids are not allowed")
        return v


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


class TestHistoryPoint(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    run_id: UUID
    run_created_at: datetime
    run_status: RunStatusValue
    status: TestResultStatusValue
    duration_ms: int | None = None
    error_message: str | None = None
    git_ref: str | None = None


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


class TestHistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    data: list[TestHistoryPoint]
    pagination: AnalyticsPaginationMeta
