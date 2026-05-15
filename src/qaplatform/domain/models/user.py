from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    username: str
    email: str
    password_hash: str
    role: Literal["platform_admin", "user"] = "user"
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Credential(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    name: str
    type: Literal["token", "ssh_key", "password"]
    encrypted_value: bytes
    created_by: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApiToken(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    name: str
    token_id: str
    secret_hash: str
    scopes: list[str] = Field(default_factory=lambda: ["*"])
    expires_at: datetime
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    is_revoked: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
