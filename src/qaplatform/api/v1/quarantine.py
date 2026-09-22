from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    require_project_permission,
)
from qaplatform.api.schemas import (
    ErrorResponse,
    PaginatedResponse,
    QuarantineAddRequest,
    QuarantineResponse,
)

router = APIRouter(
    prefix="/projects/{project_id}/quarantine",
    tags=["quarantine"],
)


@router.get(
    "",
    response_model=PaginatedResponse[QuarantineResponse],
    responses={404: {"model": ErrorResponse}},
    summary="列出已隔离的测试",
)
async def list_quarantine(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _perm=require_project_permission(Action.RUN_READ),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows, total = await repos.quarantine.list_by_project(
        project_id,
        offset=(page - 1) * per_page,
        limit=per_page,
    )

    return PaginatedResponse(
        data=[QuarantineResponse.model_validate(r) for r in rows],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=QuarantineResponse,
    status_code=201,
    responses={
        200: {"model": QuarantineResponse, "description": "已存在，更新隔离理由"},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="隔离测试",
)
async def add_to_quarantine(
    project_id: UUID,
    body: QuarantineAddRequest,
    response: Response,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.PROJECT_EDIT),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Project is archived; cannot modify quarantine",
        )

    existing = await repos.quarantine.get_quarantine(project_id, body.suite, body.name)
    before = QuarantineResponse.model_validate(existing) if existing else None

    record = await repos.quarantine.add_to_quarantine(
        project_id=project_id,
        suite=body.suite,
        name=body.name,
        reason=body.reason,
        created_by=user.user_id,
        expires_at=body.expires_at,
    )

    # upsert：命中既有行时是更新而非新建，按 T17 §2.2 返回 200
    if existing is not None:
        response.status_code = 200

    after = QuarantineResponse.model_validate(record)
    await write_audit(
        repos,
        user,
        action="quarantine.add",
        resource_type="quarantine",
        resource_id=record.id,
        before=before,
        after=after,
    )
    return after


@router.delete(
    "",
    status_code=204,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="取消隔离测试",
)
async def remove_from_quarantine(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    suite: str = Query(..., min_length=1, max_length=255),
    name: str = Query(..., min_length=1, max_length=255),
    _perm=require_project_permission(Action.PROJECT_EDIT),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Project is archived; cannot modify quarantine",
        )

    record = await repos.quarantine.get_quarantine(project_id, suite, name)
    if record is None:
        raise HTTPException(status_code=404, detail="Quarantine record not found")

    before = QuarantineResponse.model_validate(record)
    await repos.quarantine.remove_from_quarantine(project_id, suite, name)

    await write_audit(
        repos,
        user,
        action="quarantine.remove",
        resource_type="quarantine",
        resource_id=record.id,
        before=before,
    )
