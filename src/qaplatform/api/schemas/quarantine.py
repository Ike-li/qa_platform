from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuarantineAddRequest(BaseModel):
    suite: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    reason: str = Field(..., min_length=1, max_length=1000)
    expires_at: datetime | None = None


class QuarantineResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    suite: str
    name: str
    reason: str
    created_by: UUID | None
    created_at: datetime
    expires_at: datetime | None = None
