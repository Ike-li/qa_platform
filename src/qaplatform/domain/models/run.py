from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    COLLECTING = "collecting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


TERMINAL_STATUSES: set[RunStatus] = {
    RunStatus.DONE,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.TIMEOUT,
}


class RunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: int = 0
    pass_rate: float = 0.0


class TestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    suite: str
    name: str
    status: Literal["passed", "failed", "error", "skipped", "xfail"]
    duration_ms: int = 0
    error_message: str | None = None
    stack_trace: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    type: Literal["report", "log", "screenshot", "video", "coverage", "custom"]
    name: str
    storage_path: str
    size_bytes: int
    mime_type: str
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    pipeline_id: UUID
    environment_id: UUID
    status: RunStatus = RunStatus.QUEUED
    trigger_type: Literal["manual", "schedule", "webhook", "api", "event"] = "manual"
    priority: int = 1
    triggered_by: UUID | None = None
    git_ref: str
    git_sha: str | None = None
    # Retry tracking
    retry_group_id: UUID | None = None
    attempt: int = 1
    # Event chain
    source_run_id: UUID | None = None
    chain_depth: int = 0
    # Control plane
    dedup_key: str | None = None
    dedup_expires_at: datetime | None = None
    queue_name: str | None = None
    arq_job_id: str | None = None
    execution_id: str | None = None
    worker_id: str | None = None
    enqueued_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    summary: RunSummary | None = None
    metadata: dict = Field(default_factory=dict)
    error_message: str | None = None
    status_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
