from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from qaplatform.domain.models.notification import (
    NOTIFICATION_CHANNEL_TYPES,
    normalize_notification_channel,
    normalize_notification_conditions,
    validate_notification_conditions,
)

NotificationChannelType = Literal["email", "webhook", "dingtalk", "wecom"]


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


__all__ = [
    "NotificationChannelPayload",
    "NotificationChannelType",
    "NotificationConditionAllGroup",
    "NotificationConditionAnyGroup",
    "NotificationConditionExpression",
    "NotificationConditionField",
    "NotificationConditionLeaf",
    "NotificationConditionOperator",
    "NotificationConditionResponseAllGroup",
    "NotificationConditionResponseAnyGroup",
    "NotificationConditionResponseExpression",
    "NotificationInvalidCondition",
    "NotificationLogResponse",
    "NotificationRuleCreate",
    "NotificationRuleResponse",
    "NotificationRuleUpdate",
    "validate_notification_channels",
    "validate_notification_rule_name",
]
