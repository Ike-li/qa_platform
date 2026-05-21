from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import CurrentUser, Repos, _get_db_session, require_permission, require_project_permission
from qaplatform.api.schemas import (
    ErrorResponse,
    PaginatedResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from qaplatform.infra.database.models import Project as ProjectORM

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_response(orm: ProjectORM) -> ProjectResponse:
    return ProjectResponse.model_validate(orm)


@router.get(
    "",
    response_model=PaginatedResponse[ProjectResponse],
    summary="项目列表",
)
async def list_projects(
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, description="按名称/描述搜索"),
    status: str | None = Query(None, description="active / archived"),
):
    filters = [ProjectORM.tenant_id == user.tenant_id]
    if status:
        filters.append(ProjectORM.status == status)
    if q:
        def _escape_like(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        pattern = f"%{_escape_like(q)}%"
        filters.append(
            or_(
                ProjectORM.name.ilike(pattern, escape="\\"),
                ProjectORM.description.ilike(pattern, escape="\\"),
            )
        )

    items, total = await repos.project.list(
        offset=(page - 1) * per_page,
        limit=per_page,
        filters=filters,
    )
    return PaginatedResponse(
        data=[_to_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}},
    summary="创建项目",
)
async def create_project(
    body: ProjectCreate,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_permission(Action.PROJECT_CREATE),
):
    existing = await repos.project.get_by_slug(user.tenant_id, body.slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Slug already exists")

    orm = await repos.project.create(
        tenant_id=user.tenant_id,
        created_by=user.user_id,
        **body.model_dump(),
    )

    # Auto-add the creator as a project admin so a tenant Member who creates
    # a project can immediately operate on it without needing a tenant
    # Owner/Admin to grant them access.
    from qaplatform.infra.database.models import ProjectMember as ProjectMemberORM

    session.add(
        ProjectMemberORM(
            tenant_id=user.tenant_id,
            project_id=orm.id,
            user_id=user.user_id,
            role="admin",
        )
    )
    await session.flush()

    response = _to_response(orm)
    await write_audit(
        repos, user,
        action="project.create",
        resource_type="project",
        resource_id=orm.id,
        after=response,
    )
    return response


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorResponse}},
    summary="项目详情",
)
async def get_project(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_response(project)


@router.put(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorResponse}},
    summary="更新项目",
)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.PROJECT_EDIT),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    before = _to_response(project)
    update_data = body.model_dump(exclude_unset=True)
    updated = await repos.project.update(project, **update_data)
    after = _to_response(updated)
    await write_audit(
        repos, user,
        action="project.update",
        resource_type="project",
        resource_id=updated.id,
        before=before,
        after=after,
    )
    return after


@router.delete(
    "/{project_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
    summary="删除项目",
)
async def delete_project(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.PROJECT_DELETE),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    before = _to_response(project)
    await repos.project.delete(project)
    await write_audit(
        repos, user,
        action="project.delete",
        resource_type="project",
        resource_id=project_id,
        before=before,
    )
