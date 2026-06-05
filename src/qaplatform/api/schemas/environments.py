from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from qaplatform.api.schemas.common import (
    validate_environment_text,
    validate_pinned_base_image,
)

_BLOCKED_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "SHELL", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "PYTHONPATH",
    "NODE_PATH", "GOPATH", "GOROOT", "CLASSPATH",
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "no_proxy", "NO_PROXY",
})


def _validate_blocked_env_keys(v: dict[str, str]) -> dict[str, str]:
    blocked = _BLOCKED_ENV_KEYS & v.keys()
    if blocked:
        raise ValueError(f"Blocked env var keys: {', '.join(sorted(blocked))}")
    return v


class EnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    base_image: str = Field(..., max_length=255)
    setup_script: str | None = Field(None, max_length=10000)
    memory_mb: int = Field(512, ge=1)
    cpu_cores: float = Field(1.0, gt=0)
    disk_mb: int | None = Field(None, ge=1)
    max_artifact_size_mb: int = Field(100, ge=1)
    max_artifacts_count: int = Field(50, ge=1)
    network_policy: Literal["allow", "deny", "restricted"] = "deny"
    env_vars: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = Field(None, min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return validate_environment_text("name", v)

    @field_validator("cache_key")
    @classmethod
    def _validate_cache_key(cls, v: str | None) -> str | None:
        return validate_environment_text("cache_key", v)

    @field_validator("base_image")
    @classmethod
    def _validate_base_image(cls, v: str) -> str:
        return validate_pinned_base_image(v)

    @field_validator("env_vars")
    @classmethod
    def _check_env_keys(cls, v: dict[str, str]) -> dict[str, str]:
        return _validate_blocked_env_keys(v)


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    base_image: str | None = Field(None, max_length=255)
    setup_script: str | None = Field(None, max_length=10000)
    memory_mb: int | None = Field(None, ge=1)
    cpu_cores: float | None = Field(None, gt=0)
    disk_mb: int | None = Field(None, ge=1)
    max_artifact_size_mb: int | None = Field(None, ge=1)
    max_artifacts_count: int | None = Field(None, ge=1)
    network_policy: Literal["allow", "deny", "restricted"] | None = None
    env_vars: dict[str, str] | None = None
    cache_key: str | None = Field(None, min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        return validate_environment_text("name", v)

    @field_validator("cache_key")
    @classmethod
    def _validate_cache_key(cls, v: str | None) -> str | None:
        return validate_environment_text("cache_key", v)

    @field_validator("base_image")
    @classmethod
    def _validate_base_image(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_pinned_base_image(v)

    @field_validator("env_vars")
    @classmethod
    def _check_env_keys(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        return _validate_blocked_env_keys(v)


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    base_image: str
    setup_script: str | None = None
    memory_mb: int = 512
    cpu_cores: float = 1.0
    disk_mb: int | None = None
    max_artifact_size_mb: int = 100
    max_artifacts_count: int = 50
    network_policy: Literal["allow", "deny", "restricted"] = "deny"
    env_vars: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = None
    created_at: datetime


__all__ = [
    "EnvironmentCreate",
    "EnvironmentResponse",
    "EnvironmentUpdate",
]
