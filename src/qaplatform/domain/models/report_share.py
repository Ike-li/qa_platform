"""Report share token models for temporary report sharing."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportShareToken(BaseModel):
    """Report share token for temporary public access to Allure reports."""
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    run_id: UUID
    token: str
    created_by: UUID
    expires_at: datetime
    access_count: int = 0
    max_access_count: int | None = None
    last_accessed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CreateReportShareTokenRequest(BaseModel):
    """Request to create a report share token."""
    expires_in_days: int = Field(default=7, ge=1, le=90)
    max_access_count: int | None = Field(default=None, ge=1)


class ReportShareTokenResponse(BaseModel):
    """Response containing the share token and URL."""
    model_config = ConfigDict(frozen=True)

    id: UUID
    share_url: str
    token: str
    expires_at: datetime
    max_access_count: int | None = None
