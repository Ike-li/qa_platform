from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class TestSelector(BaseModel):
    model_config = ConfigDict(frozen=True)

    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    expression: str | None = None
    regex: str | None = None
    on_empty: Literal["fail", "skip", "warn"] = "fail"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = 1
    retry_on: list[str] = Field(default_factory=list)
    backoff_seconds: int = 0
    scope: Literal["pipeline", "stage"] = "pipeline"


class TriggerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str = "manual"
    dedup_window_seconds: int | None = None
    source: dict = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    target: dict = Field(default_factory=dict)


class Pipeline(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    name: str
    stages: list[StageDefinition] = Field(default_factory=list)
    selector: TestSelector = Field(default_factory=TestSelector)
    trigger_config: TriggerConfig = Field(default_factory=TriggerConfig)
    timeout_seconds: int = 1800
    retry_policy: RetryPolicy | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Re-export for convenience (avoids circular imports downstream)
from qaplatform.domain.models.common import ResourceLimits  # noqa: E402
