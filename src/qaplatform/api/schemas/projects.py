from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from qaplatform.api.schemas.common import (
    validate_credential_name,
    validate_project_text,
)
from qaplatform.domain.models.project import SilentWindow

_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

ProjectStatusValue = Literal["active", "archived"]


def validate_timezone_name(timezone_name: str | None) -> str | None:
    if timezone_name is None:
        return None
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid timezone: {timezone_name}") from exc
    return timezone_name


def validate_schedule_quiet_windows(windows: list[dict] | None) -> list[dict] | None:
    if windows is None:
        return None

    normalized: list[dict] = []
    for index, window in enumerate(windows):
        if not isinstance(window, dict):
            raise ValueError(f"quiet_windows[{index}] must be an object")

        start = window.get("start")
        end = window.get("end")
        if not isinstance(start, str) or not _HH_MM_RE.match(start):
            raise ValueError(f"quiet_windows[{index}].start must use HH:MM")
        if not isinstance(end, str) or not _HH_MM_RE.match(end):
            raise ValueError(f"quiet_windows[{index}].end must use HH:MM")

        timezone_name = window.get("timezone", "Asia/Shanghai")
        if not isinstance(timezone_name, str):
            raise ValueError(f"quiet_windows[{index}].timezone must be a string")
        validate_timezone_name(timezone_name)

        normalized.append(
            {
                "start": start,
                "end": end,
                "timezone": timezone_name,
            }
        )
    return normalized


def validate_schedule_cron_expr(cron_expr: str) -> str:
    from croniter import croniter

    if not croniter.is_valid(cron_expr):
        raise ValueError(f"invalid cron expression: {cron_expr}")
    return cron_expr


def validate_optional_schedule_cron_expr(cron_expr: str | None) -> str | None:
    if cron_expr is None:
        return None
    return validate_schedule_cron_expr(cron_expr)


def _validate_project_settings(settings: dict | None) -> dict | None:
    if settings is None:
        return None

    allowed = settings.get("allowed_branches")
    if allowed is not None:
        if not isinstance(allowed, list):
            raise ValueError("settings.allowed_branches must be a list of strings")
        if len(allowed) > 50:
            raise ValueError("settings.allowed_branches must contain at most 50 entries")
        for pattern in allowed:
            if not isinstance(pattern, str):
                raise ValueError("settings.allowed_branches entries must be strings")
            if not pattern.strip():
                raise ValueError("settings.allowed_branches entries must be non-empty")
            if len(pattern) > 200:
                raise ValueError("settings.allowed_branches entries must be at most 200 characters")

    silent_windows = settings.get("silent_windows")
    if silent_windows is None:
        return settings
    if not isinstance(silent_windows, list):
        raise ValueError("settings.silent_windows must be a list")
    if len(silent_windows) > 20:
        raise ValueError("settings.silent_windows must contain at most 20 entries")
    return {
        **settings,
        "silent_windows": [
            SilentWindow.model_validate(window).model_dump(mode="json")
            for window in silent_windows
        ],
    }


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(None, max_length=500)
    git_url: str = Field(..., min_length=1, max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] = "none"
    credential_id: UUID | None = None
    default_branch: str = Field("main", min_length=1, max_length=100)
    root_path: str = Field(".", min_length=1, max_length=255)
    shallow_clone: bool = True
    default_env_id: UUID | None = None
    settings: dict = Field(default_factory=dict)

    @field_validator("settings")
    @classmethod
    def _check_settings(cls, v: dict) -> dict:
        return _validate_project_settings(v) or {}

    @field_validator("name", "git_url", "default_branch", "root_path")
    @classmethod
    def _validate_text_fields(cls, v: str | None, info: ValidationInfo) -> str | None:
        return validate_project_text(info.field_name, v)


class GitBranchDiscoveryRequest(BaseModel):
    git_url: str = Field(..., min_length=1, max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] = "none"

    @field_validator("git_url")
    @classmethod
    def _validate_git_url(cls, v: str) -> str:
        return validate_project_text("git_url", v)


class GitBranchDiscoveryResponse(BaseModel):
    branches: list[str]
    default_branch: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    git_url: str | None = Field(None, min_length=1, max_length=255)
    git_auth_method: Literal["none", "token", "ssh_key"] | None = None
    credential_id: UUID | None = None
    default_branch: str | None = Field(None, min_length=1, max_length=100)
    root_path: str | None = Field(None, min_length=1, max_length=255)
    shallow_clone: bool | None = None
    default_env_id: UUID | None = None
    settings: dict | None = None
    silent_windows: list[SilentWindow] | None = Field(None, max_length=20)
    status: ProjectStatusValue | None = None

    @field_validator("settings")
    @classmethod
    def _check_settings(cls, v: dict | None) -> dict | None:
        return _validate_project_settings(v)

    @field_validator("name", "git_url", "default_branch", "root_path")
    @classmethod
    def _validate_text_fields(cls, v: str | None, info: ValidationInfo) -> str | None:
        return validate_project_text(info.field_name, v)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

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
    status: ProjectStatusValue = "active"
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class ProjectMemberCreate(BaseModel):
    user_id: UUID
    role: Literal["admin", "developer", "viewer"]


class ProjectMemberUpdate(BaseModel):
    role: Literal["admin", "developer", "viewer"]


class ProjectMemberResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    project_id: UUID
    user_id: UUID
    username: str
    email: str
    role: str
    created_at: datetime


class CredentialCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: Literal["token", "ssh_key", "password"]
    value: str = Field(..., min_length=1, max_length=65536)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return validate_credential_name(name)


class CredentialUpdate(BaseModel):
    value: str = Field(..., min_length=1, max_length=65536)


class CredentialResponse(BaseModel):
    """Credential metadata. The plaintext ``value`` is never returned by the API."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    type: str
    created_by: UUID
    created_at: datetime


class ScheduleCreate(BaseModel):
    pipeline_id: UUID
    cron_expr: str = Field(..., min_length=1, max_length=100)
    timezone: str = Field("Asia/Shanghai", min_length=1, max_length=50)
    missed_fire_policy: Literal["skip", "run_once", "run_all"] = "skip"
    quiet_windows: list[dict] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("cron_expr")
    @classmethod
    def validate_cron_expr(cls, v: str) -> str:
        return validate_schedule_cron_expr(v)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        return validate_timezone_name(v)

    @field_validator("quiet_windows")
    @classmethod
    def validate_quiet_windows(cls, v: list[dict]) -> list[dict]:
        return validate_schedule_quiet_windows(v) or []


class ScheduleUpdate(BaseModel):
    cron_expr: str | None = Field(None, min_length=1, max_length=100)
    timezone: str | None = Field(None, min_length=1, max_length=50)
    missed_fire_policy: Literal["skip", "run_once", "run_all"] | None = None
    quiet_windows: list[dict] | None = None
    enabled: bool | None = None

    @field_validator("cron_expr")
    @classmethod
    def validate_cron_expr(cls, v: str | None) -> str | None:
        return validate_optional_schedule_cron_expr(v)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        return validate_timezone_name(v)

    @field_validator("quiet_windows")
    @classmethod
    def validate_quiet_windows(cls, v: list[dict] | None) -> list[dict] | None:
        return validate_schedule_quiet_windows(v)


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    pipeline_id: UUID
    cron_expr: str
    timezone: str
    missed_fire_policy: str
    quiet_windows: list[dict]
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_error: str | None
    created_at: datetime


__all__ = [
    "CredentialCreate",
    "CredentialResponse",
    "CredentialUpdate",
    "GitBranchDiscoveryRequest",
    "GitBranchDiscoveryResponse",
    "ProjectCreate",
    "ProjectMemberCreate",
    "ProjectMemberResponse",
    "ProjectMemberUpdate",
    "ProjectResponse",
    "ProjectStatusValue",
    "ProjectUpdate",
    "ScheduleCreate",
    "ScheduleResponse",
    "ScheduleUpdate",
    "validate_optional_schedule_cron_expr",
    "validate_schedule_cron_expr",
    "validate_schedule_quiet_windows",
    "validate_timezone_name",
]
