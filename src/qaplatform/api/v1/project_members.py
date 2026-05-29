from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    require_project_permission,
)
from qaplatform.api.schemas import (
    ErrorResponse,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectMemberUpdate,
    PaginatedResponse,
)

router = APIRouter(
    prefix="/projects/{project_id}/members",
    tags=["project-members"],
)


def _to_response(member, user) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        project_id=member.project_id,
        user_id=member.user_id,
        username=user.username,
        email=user.email,
        role=member.role,
        created_at=member.created_at,
    )


async def _verify_project_access(project_id: UUID, repos: Repos, user: CurrentUser):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get(
    "",
    response_model=PaginatedResponse[ProjectMemberResponse],
    summary="项目成员列表",
)
async def list_project_members(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _perm=require_project_permission(Action.MEMBER_READ),
):
    await _verify_project_access(project_id, repos, user)
    rows, total = await repos.project_member.list_by_project_tenant(
        project_id,
        user.tenant_id,
        offset=(page - 1) * per_page,
        limit=per_page,
    )
    return PaginatedResponse(
        data=[_to_response(m, m.user) for m in rows],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=ProjectMemberResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="添加项目成员",
)
async def add_project_member(
    project_id: UUID,
    body: ProjectMemberCreate,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.MEMBER_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    candidate = await repos.user.get_by_id(body.user_id)
    if candidate is None or candidate.tenant_id != user.tenant_id:
        raise HTTPException(status_code=422, detail="User not in this tenant")

    existing = await repos.project_member.get_existing(project_id, body.user_id, user.tenant_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already a project member")

    member = await repos.project_member.create(
        tenant_id=user.tenant_id,
        project_id=project_id,
        user_id=body.user_id,
        role=body.role,
    )

    response = _to_response(member, candidate)
    await write_audit(
        repos, user,
        action="project_member.add",
        resource_type="project_member",
        resource_id=project_id,
        after=response,
    )
    return response


@router.put(
    "/{user_id}",
    response_model=ProjectMemberResponse,
    responses={404: {"model": ErrorResponse}},
    summary="更新项目成员角色",
)
async def update_project_member(
    project_id: UUID,
    user_id: UUID,
    body: ProjectMemberUpdate,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.MEMBER_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    member = await repos.project_member.get_by_project_user(project_id, user_id, user.tenant_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    before_role = member.role
    await repos.project_member.update(member, role=body.role)

    response = _to_response(member, member.user)
    await write_audit(
        repos, user,
        action="project_member.update",
        resource_type="project_member",
        resource_id=project_id,
        before={"user_id": str(user_id), "role": before_role},
        after=response,
    )
    return response


@router.delete(
    "/{user_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="移除项目成员",
)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.MEMBER_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    member = await repos.project_member.get_existing(project_id, user_id, user.tenant_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    before_role = member.role
    await repos.project_member.delete(member)
    await write_audit(
        repos, user,
        action="project_member.remove",
        resource_type="project_member",
        resource_id=project_id,
        before={"user_id": str(user_id), "role": before_role},
    )
