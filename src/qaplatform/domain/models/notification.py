from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NOTIFICATION_CHANNEL_TYPES = frozenset({"email", "webhook", "dingtalk", "wecom"})
NOTIFICATION_CANONICAL_CONDITION_FIELDS = frozenset(
    {"status", "pass_rate", "failed", "consecutive_failures"}
)
NOTIFICATION_CONDITION_FIELDS = frozenset(
    {*NOTIFICATION_CANONICAL_CONDITION_FIELDS, "consecutive_failed_runs"}
)
NOTIFICATION_CONDITION_OPERATORS = frozenset({"eq", "ne", "lt", "gt", "lte", "gte"})

_CHANNEL_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "email": (
        "address",
        "to",
        "to_addresses",
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_password",
        "from_address",
        "subject",
    ),
    "webhook": ("webhook_url", "url", "headers", "method"),
    "dingtalk": ("access_token", "secret", "msgtype", "title"),
    "wecom": ("webhook_key", "msgtype"),
}
_CHANNEL_CONFIG_ALIASES: dict[str, dict[str, str]] = {
    "email": {"address": "to_addresses", "to": "to_addresses"},
    "webhook": {"webhook_url": "url"},
}


def _normalize_config_entry(channel_type: str, key: str, value: Any) -> tuple[str, Any]:
    normalized_key = _CHANNEL_CONFIG_ALIASES.get(channel_type, {}).get(key, key)
    if normalized_key == "to_addresses" and isinstance(value, str):
        return normalized_key, [value]
    return normalized_key, value


def normalize_notification_channel(channel: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical channel shape consumed by notification delivery."""
    if not isinstance(channel, dict):
        return {"type": "unknown", "config": {}}

    channel_type = channel.get("type", "unknown")
    if not isinstance(channel_type, str) or not channel_type:
        channel_type = "unknown"

    config: dict[str, Any] = {}
    for key in _CHANNEL_CONFIG_KEYS.get(channel_type, ()):
        if key in channel:
            normalized_key, value = _normalize_config_entry(channel_type, key, channel[key])
            config[normalized_key] = value

    raw_config = channel.get("config", {})
    if isinstance(raw_config, dict):
        for key, value in raw_config.items():
            normalized_key, value = _normalize_config_entry(channel_type, key, value)
            config[normalized_key] = value

    normalized: dict[str, Any] = {"type": channel_type, "config": config}
    if "template" in channel:
        normalized["template"] = channel["template"]
    return normalized


def normalize_notification_conditions(conditions: list[Any] | None) -> list[dict] | None:
    if conditions is None:
        return None
    return [
        _normalize_notification_condition(condition, f"conditions[{index}]")
        for index, condition in enumerate(conditions)
    ]


def _invalid_notification_condition(
    reason: str,
    *,
    field: Any = None,
    operator: Any = None,
) -> dict:
    invalid = {"invalid": True, "reason": reason}
    if isinstance(field, str):
        invalid["raw_field"] = field
    if isinstance(operator, str):
        invalid["raw_operator"] = operator
    return invalid


def _normalize_notification_condition(condition: Any, path: str) -> dict:
    if not isinstance(condition, dict):
        return _invalid_notification_condition(f"{path} must be an object")

    group_keys = [key for key in ("all", "any") if key in condition]
    if group_keys:
        if len(group_keys) > 1:
            return _invalid_notification_condition(
                f"{path} must contain only one of all or any",
                field=condition.get("field"),
                operator=condition.get("operator"),
            )
        if any(key not in group_keys for key in condition):
            return _invalid_notification_condition(
                f"{path} group cannot mix field/operator/value with all/any",
                field=condition.get("field"),
                operator=condition.get("operator"),
            )
        group_key = group_keys[0]
        children = condition.get(group_key)
        if not isinstance(children, list) or not children:
            return _invalid_notification_condition(
                f"{path}.{group_key} must be a non-empty list"
            )
        return {
            group_key: [
                _normalize_notification_condition(child, f"{path}.{group_key}[{index}]")
                for index, child in enumerate(children)
            ]
        }

    normalized = dict(condition)
    if normalized.get("field") == "consecutive_failed_runs":
        normalized["field"] = "consecutive_failures"

    field = normalized.get("field")
    operator = normalized.get("operator", "eq")
    if not isinstance(field, str) or field not in NOTIFICATION_CANONICAL_CONDITION_FIELDS:
        allowed = ", ".join(sorted(NOTIFICATION_CANONICAL_CONDITION_FIELDS))
        return _invalid_notification_condition(
            f"{path}.field must be one of: {allowed}",
            field=field,
            operator=operator,
        )
    if not isinstance(operator, str) or operator not in NOTIFICATION_CONDITION_OPERATORS:
        allowed = ", ".join(sorted(NOTIFICATION_CONDITION_OPERATORS))
        return _invalid_notification_condition(
            f"{path}.operator must be one of: {allowed}",
            field=field,
            operator=operator,
        )
    if "value" not in normalized:
        return _invalid_notification_condition(
            f"{path}.value is required",
            field=field,
            operator=operator,
        )

    value = normalized["value"]
    if not isinstance(value, str | int | float | bool):
        return _invalid_notification_condition(
            f"{path}.value must be a string, number, or boolean",
            field=field,
            operator=operator,
        )

    return {"field": field, "operator": operator, "value": value}


def validate_notification_conditions(conditions: list[dict] | None) -> list[dict] | None:
    if conditions is None:
        return None
    return [
        _validate_notification_condition(condition, f"conditions[{index}]")
        for index, condition in enumerate(conditions)
    ]


def _validate_notification_condition(condition: Any, path: str) -> dict:
    if not isinstance(condition, dict):
        raise ValueError(f"{path} must be an object")

    group_keys = [key for key in ("all", "any") if key in condition]
    if group_keys:
        if len(group_keys) > 1:
            raise ValueError(f"{path} must contain only one of all or any")
        if any(key not in group_keys for key in condition):
            raise ValueError(f"{path} group cannot mix field/operator/value with all/any")
        group_key = group_keys[0]
        children = condition[group_key]
        if not isinstance(children, list) or not children:
            raise ValueError(f"{path}.{group_key} must be a non-empty list")
        return {
            group_key: [
                _validate_notification_condition(child, f"{path}.{group_key}[{index}]")
                for index, child in enumerate(children)
            ]
        }

    field = condition.get("field")
    if not isinstance(field, str) or field not in NOTIFICATION_CANONICAL_CONDITION_FIELDS:
        allowed = ", ".join(sorted(NOTIFICATION_CANONICAL_CONDITION_FIELDS))
        raise ValueError(f"{path}.field must be one of: {allowed}")

    operator = condition.get("operator", "eq")
    if not isinstance(operator, str) or operator not in NOTIFICATION_CONDITION_OPERATORS:
        allowed = ", ".join(sorted(NOTIFICATION_CONDITION_OPERATORS))
        raise ValueError(f"{path}.operator must be one of: {allowed}")
    if "value" not in condition:
        raise ValueError(f"{path}.value is required")

    return {"field": field, "operator": operator, "value": condition["value"]}


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
