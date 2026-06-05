from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from qaplatform.api.schemas.common import (
    validate_pipeline_text,
    validate_pipeline_text_list,
)

SelectorPathValue = Annotated[str, Field(min_length=1, max_length=1000)]
SelectorTagValue = Annotated[str, Field(min_length=1, max_length=100)]
RetryReasonValue = Annotated[str, Field(min_length=1, max_length=100)]


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


__all__ = [
    "CollectorDefinitionInput",
    "PipelineCreate",
    "PipelineResponse",
    "PipelineUpdate",
    "RetryPolicyInput",
    "RetryReasonValue",
    "SelectorPathValue",
    "SelectorTagValue",
    "StageDefinitionInput",
    "TestSelectorInput",
    "TriggerConfigInput",
]
