from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Re-export domain common schemas for convenience
from qaplatform.domain.models.common import PaginatedResponse, PaginationParams


# ── Unified error ────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    details: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: ErrorDetail


# ── Project schemas ──────────────────────────────────────────────────────────

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
    status: Literal["active", "archived"] | None = None


class ProjectResponse(BaseModel):
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
    created_at: datetime
    updated_at: datetime


# ── Environment schemas ─────────────────────────────────────────────────────

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


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    max_attempts: int = 1
    retry_on: list[str] = Field(default_factory=list)
    backoff_seconds: int = 0
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
    model_config = ConfigDict(frozen=True)

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


class RunCancel(BaseModel):
    reason: str | None = None


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    model_config = ConfigDict(frozen=True)

    status: str | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    sort: str = "-created_at"


class TestResultResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    model_config = ConfigDict(frozen=True)

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
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    user_id: UUID
    username: str
    email: str
    role: str
    created_at: datetime
