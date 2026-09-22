from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


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

    @computed_field
    @property
    def expired(self) -> bool:
        """该隔离是否已过期而不再生效。

        过期的行不从列表里隐藏——运维需要看见「这条失效了」才能决定要不要
        续期，直接消失反而让人以为从没设过。
        """
        if self.expires_at is None:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)
