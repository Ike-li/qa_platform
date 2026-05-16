from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_

from qaplatform.api.deps import CurrentUser, Repos
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
    return ProjectResponse(
        id=orm.id,
        tenant_id=orm.tenant_id,
        name=orm.name,
        slug=orm.slug,
        description=orm.description,
        git_url=orm.git_url,
        git_auth_method=orm.git_auth_method,
        credential_id=orm.credential_id,
        default_branch=orm.default_branch,
        root_path=orm.root_path,
        shallow_clone=orm.shallow_clone,
        default_env_id=orm.default_env_id,
        settings=orm.settings or {},
        status=orm.status,
        created_by=orm.created_by,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


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
        pattern = f"%{q}%"
        filters.append(
            or_(ProjectORM.name.ilike(pattern), ProjectORM.description.ilike(pattern))
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
):
    existing = await repos.project.get_by_slug(user.tenant_id, body.slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Slug already exists")

    orm = await repos.project.create(
        tenant_id=user.tenant_id,
        created_by=user.user_id,
        **body.model_dump(),
    )
    return _to_response(orm)


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
    project = await repos.project.get_by_id(project_id)
    if project is None or project.tenant_id != user.tenant_id:
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
):
    project = await repos.project.get_by_id(project_id)
    if project is None or project.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = body.model_dump(exclude_unset=True)
    updated = await repos.project.update(project, **update_data)
    return _to_response(updated)


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
):
    project = await repos.project.get_by_id(project_id)
    if project is None or project.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    await repos.project.delete(project)
