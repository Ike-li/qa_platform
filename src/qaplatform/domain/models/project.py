from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


def _validate_non_blank_text(field_name: str, value: str | None) -> str | None:
    if value is not None and value.strip() == "":
        raise ValueError(f"{field_name} must not be blank")
    return value


def _validate_non_blank_text_list(field_name: str, values: list[str]) -> list[str]:
    for index, value in enumerate(values):
        if value.strip() == "":
            raise ValueError(f"{field_name}[{index}] must not be blank")
    return values


class SilentWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_at: datetime
    end_at: datetime
    reason: str = Field(..., min_length=1, max_length=200)

    @field_validator("start_at", "end_at")
    @classmethod
    def _require_tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _require_positive_window(self) -> "SilentWindow":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be greater than start_at")
        return self


class Project(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Environment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    name: str
    base_image: str
    setup_script: str | None = None
    resource_limits: ResourceLimits
    network_policy: Literal["allow", "deny", "restricted"] = "deny"
    env_vars: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StageDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    plugin: str
    config: dict = Field(default_factory=dict)
    continue_on_error: bool = False
    phase: Literal["prepare", "execute", "collect", "notify"] | None = None

    @field_validator("name", "plugin")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        return _validate_non_blank_text(f"stage {info.field_name}", value)


SelectorPathValue = Annotated[str, Field(min_length=1, max_length=1000)]
SelectorTagValue = Annotated[str, Field(min_length=1, max_length=100)]
RetryReasonValue = Annotated[str, Field(min_length=1, max_length=100)]


class TestSelector(BaseModel):
    model_config = ConfigDict(frozen=True)
    __test__ = False

    include_paths: list[SelectorPathValue] = Field(default_factory=list, max_length=100)
    exclude_paths: list[SelectorPathValue] = Field(default_factory=list, max_length=100)
    tags: list[SelectorTagValue] = Field(default_factory=list, max_length=100)
    expression: str | None = None
    regex: str | None = None
    on_empty: Literal["fail", "skip", "warn"] = "fail"

    @field_validator("include_paths", "exclude_paths", "tags")
    @classmethod
    def _validate_text_list(cls, values: list[str], info: ValidationInfo) -> list[str]:
        return _validate_non_blank_text_list(info.field_name, values)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = 1
    retry_on: list[RetryReasonValue] = Field(default_factory=list, max_length=20)
    backoff_seconds: int = 0
    scope: Literal["pipeline", "stage"] = "pipeline"

    @field_validator("retry_on")
    @classmethod
    def _validate_retry_on(cls, values: list[str]) -> list[str]:
        return _validate_non_blank_text_list("retry_on", values)


class TriggerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str = Field("manual", min_length=1, max_length=50)
    dedup_window_seconds: int | None = Field(None, ge=0)
    source: dict = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    target: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        return _validate_non_blank_text("trigger_config type", value)


class CollectorDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    plugin: str = "junit"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("plugin")
    @classmethod
    def _validate_plugin(cls, value: str) -> str:
        return _validate_non_blank_text("collector plugin", value)


class Pipeline(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    name: str
    stages: list[StageDefinition] = Field(default_factory=list)
    selector: TestSelector = Field(default_factory=TestSelector)
    trigger_config: TriggerConfig = Field(default_factory=TriggerConfig)
    collectors: list[CollectorDefinition] = Field(
        default_factory=lambda: [CollectorDefinition()]
    )
    timeout_seconds: int = 1800
    retry_policy: RetryPolicy | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_non_blank_text("pipeline name", value)


# Re-export for convenience (avoids circular imports downstream)
from qaplatform.domain.models.common import ResourceLimits  # noqa: E402
