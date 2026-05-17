from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    require_project_permission,
)
from qaplatform.api.schemas import (
    ErrorResponse,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectMemberUpdate,
)
from qaplatform.infra.database.models import (
    AppUser as AppUserORM,
    ProjectMember,
)

from fastapi import Depends

router = APIRouter(
    prefix="/projects/{project_id}/members",
    tags=["project-members"],
)


def _to_response(member: ProjectMember, user: AppUserORM) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        project_id=member.project_id,
        user_id=member.user_id,
        username=user.username,
        email=user.email,
        role=member.role,
        created_at=member.created_at,
    )


async def _verify_project_access(project_id: UUID, repos: Repos, user: CurrentUser):
    project = await repos.project.get_by_id(project_id)
    if project is None or project.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get(
    "",
    response_model=list[ProjectMemberResponse],
    summary="项目成员列表",
)
async def list_project_members(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.MEMBER_READ),
):
    await _verify_project_access(project_id, repos, user)

    stmt = (
        select(ProjectMember)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.tenant_id == user.tenant_id,
        )
        .options(selectinload(ProjectMember.user))
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_response(m, m.user) for m in rows]


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
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.MEMBER_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    candidate = (
        await session.execute(
            select(AppUserORM).where(AppUserORM.id == body.user_id)
        )
    ).scalar_one_or_none()
    if candidate is None or candidate.tenant_id != user.tenant_id:
        raise HTTPException(status_code=422, detail="User not in this tenant")

    existing = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == body.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already a project member")

    member = ProjectMember(
        tenant_id=user.tenant_id,
        project_id=project_id,
        user_id=body.user_id,
        role=body.role,
    )
    session.add(member)
    await session.flush()
    await session.refresh(member, ["created_at"])

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
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.MEMBER_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    member = (
        await session.execute(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.tenant_id == user.tenant_id,
            )
            .options(selectinload(ProjectMember.user))
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    before_role = member.role
    member.role = body.role
    await session.flush()

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
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.MEMBER_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    member = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    await session.delete(member)
    await write_audit(
        repos, user,
        action="project_member.remove",
        resource_type="project_member",
        resource_id=project_id,
        before={"user_id": str(user_id), "role": member.role},
    )
