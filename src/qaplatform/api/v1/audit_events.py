from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import CurrentUser, Repos, require_permission
from qaplatform.api.schemas import ErrorResponse, PaginatedResponse
from qaplatform.infra.database.models import AuditEvent as AuditEventORM

router = APIRouter(prefix="/audit-events", tags=["audit-events"])
_AUDIT_TEXT_FILTER_MAX_LENGTH = 200


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID | None
    user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    before_state: dict | None
    after_state: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


class AuditEventQueryAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor_id: UUID | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    page: int
    per_page: int
    total: int


def _to_response(orm: AuditEventORM) -> AuditEventResponse:
    return AuditEventResponse(
        id=orm.id,
        tenant_id=orm.tenant_id,
        user_id=orm.user_id,
        action=orm.action,
        resource_type=orm.resource_type,
        resource_id=orm.resource_id,
        before_state=orm.before_state,
        after_state=orm.after_state,
        ip_address=str(orm.ip_address) if orm.ip_address is not None else None,
        user_agent=orm.user_agent,
        created_at=orm.created_at,
    )


def _validate_text_filter(name: str, value: str | None) -> None:
    if value is None:
        return
    if value.strip() == "":
        raise HTTPException(status_code=422, detail=f"Invalid audit {name}: empty")
    if len(value) > _AUDIT_TEXT_FILTER_MAX_LENGTH:
        raise HTTPException(status_code=422, detail=f"Invalid audit {name}: too long")


@router.get(
    "",
    response_model=PaginatedResponse[AuditEventResponse],
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="审计日志列表",
)
async def list_audit_events(
    repos: Repos,
    user: CurrentUser,
    actor_id: UUID | None = Query(None, description="按操作人筛选"),
    action: str | None = Query(None, description="按动作筛选"),
    resource_type: str | None = Query(None, description="按目标资源类型筛选"),
    resource_id: UUID | None = Query(None, description="按目标资源 ID 筛选"),
    start_at: datetime | None = Query(None, description="起始时间（含）"),
    end_at: datetime | None = Query(None, description="结束时间（含）"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _perm=require_permission(Action.AUDIT_READ),
):
    _validate_text_filter("action", action)
    _validate_text_filter("resource_type", resource_type)
    if start_at is not None and end_at is not None and start_at > end_at:
        raise HTTPException(
            status_code=422,
            detail="Invalid audit time range: start_at must be before end_at",
        )

    items, total = await repos.audit.list(
        tenant_id=user.tenant_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        start_at=start_at,
        end_at=end_at,
        offset=(page - 1) * per_page,
        limit=per_page,
    )

    if total == 0 and await repos.audit.has_cross_tenant_match(
        tenant_id=user.tenant_id,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
    ):
        raise HTTPException(status_code=404, detail="Audit event not found")

    response = PaginatedResponse(
        data=[_to_response(item) for item in items],
        page=page,
        per_page=per_page,
        total=total,
    )
    await write_audit(
        repos,
        user,
        action="audit_events.list",
        resource_type="audit_event",
        after=AuditEventQueryAudit(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            start_at=start_at,
            end_at=end_at,
            page=page,
            per_page=per_page,
            total=total,
        ),
    )
    return response
