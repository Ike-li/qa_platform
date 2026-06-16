from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from qaplatform.api.schemas.common import (
    validate_run_git_ref,
    validate_webhook_git_ref,
    validate_webhook_git_sha,
)

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
TestResultStatusValue = Literal["passed", "failed", "error", "skipped", "xfail"]


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


TriageCategoryValue = Literal["new", "known_flaky", "persistent"]
TriageConfidenceValue = Literal["observing", "established"]


class TriageObservation(BaseModel):
    """履历迷你条的一格：该用例在某次 run 中的观测。"""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    run_id: UUID
    run_created_at: datetime
    status: TestResultStatusValue


class TriageItem(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    suite: str
    name: str
    status: TestResultStatusValue
    duration_ms: int = 0
    error_message: str | None = None
    stack_trace: str | None = None
    category: TriageCategoryValue
    confidence: TriageConfidenceValue
    observation_count: int
    quarantined: bool = False
    # 最近最多 10 次观测（含本次），按时间升序（旧 → 新）。
    recent_history: list[TriageObservation] = Field(default_factory=list)


class TriageCluster(BaseModel):
    """同错误签名折叠的一组失败。"""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    signature: str
    count: int
    items: list[TriageItem]


class RunTriageResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    run_id: UUID
    total_failed: int
    new: list[TriageCluster] = Field(default_factory=list)
    known_flaky: list[TriageCluster] = Field(default_factory=list)
    persistent: list[TriageCluster] = Field(default_factory=list)


__all__ = [
    "ArtifactResponse",
    "BatchRunRequest",
    "BatchRunResponse",
    "RunCancel",
    "RunListFilter",
    "RunLogEntryResponse",
    "RunResponse",
    "RunStatusValue",
    "RunTriageResponse",
    "RunTrigger",
    "TestResultResponse",
    "TestResultStatusValue",
    "TriageCategoryValue",
    "TriageCluster",
    "TriageConfidenceValue",
    "TriageItem",
    "TriageObservation",
    "WebhookTriggerRequest",
]
