from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from qaplatform.api.schemas.runs import RunStatusValue, TestResultStatusValue


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
    observation_count: int
    window_days: int


class TestHistoryPoint(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    run_id: UUID
    run_created_at: datetime
    run_status: RunStatusValue
    status: TestResultStatusValue
    duration_ms: int | None = None
    error_message: str | None = None
    git_ref: str | None = None
    observation_count: int | None = None


class ReleaseTestDelta(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    suite: str
    name: str
    failed_count: int


class ReleaseSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    git_ref: str
    baseline_git_ref: str
    total_runs: int
    passed_runs: int
    failed_runs: int
    raw_pass_rate: float
    flaky_adjusted_pass_rate: float | None = None
    new_failing_tests: list[ReleaseTestDelta] = Field(default_factory=list)
    recovered_tests: list[ReleaseTestDelta] = Field(default_factory=list)
    observation_count: int
    window_days: int


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


__all__ = [
    "AnalyticsPaginationMeta",
    "FlakyResponse",
    "FlakyTest",
    "ReleaseSummaryResponse",
    "ReleaseTestDelta",
    "TestHistoryPoint",
    "TestHistoryResponse",
    "TrendDataPoint",
    "TrendsResponse",
]
