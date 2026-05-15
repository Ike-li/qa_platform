from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    operator: str  # eq, ne, lt, gt, lte, gte, in, contains
    value: str | int | float | bool | list


class ChannelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str  # email, dingtalk, wecom, slack, webhook
    config: dict = Field(default_factory=dict)


class NotificationRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    name: str
    enabled: bool = True
    conditions: list[Condition] = Field(default_factory=list)
    channels: list[ChannelConfig] = Field(default_factory=list)
    template: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Notification(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    run_id: UUID
    rule_id: UUID
    channel_type: str
    status: str  # sent / failed / skipped
    error_message: str | None = None
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
