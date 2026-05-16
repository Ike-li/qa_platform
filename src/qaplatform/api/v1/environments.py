from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from qaplatform.api.deps import CurrentUser, Repos
from qaplatform.api.schemas import (
    EnvironmentCreate,
    EnvironmentResponse,
    EnvironmentUpdate,
    ErrorResponse,
    PaginatedResponse,
)

router = APIRouter(
    prefix="/projects/{project_id}/environments",
    tags=["environments"],
)


def _to_response(orm) -> EnvironmentResponse:
    rl = orm.resource_limits or {}
    return EnvironmentResponse(
        id=orm.id,
        project_id=orm.project_id,
        name=orm.name,
        base_image=orm.base_image,
        setup_script=orm.setup_script,
        memory_mb=orm.memory_mb,
        cpu_cores=orm.cpu_cores,
        max_artifact_size_mb=rl.get("max_artifact_size_mb", 100),
        max_artifacts_count=rl.get("max_artifacts_count", 50),
        network_policy=orm.network_policy,
        env_vars=orm.env_vars or {},
        cache_key=orm.cache_key,
        created_at=orm.created_at,
    )


async def _verify_project_access(project_id: UUID, repos: Repos, user):
    project = await repos.project.get_by_id(project_id)
    if project is None or project.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get(
    "",
    response_model=PaginatedResponse[EnvironmentResponse],
    summary="环境列表",
)
async def list_environments(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    await _verify_project_access(project_id, repos, user)

    items, total = await repos.environment.list_by_project(
        project_id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[_to_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=EnvironmentResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}},
    summary="创建环境",
)
async def create_environment(
    project_id: UUID,
    body: EnvironmentCreate,
    repos: Repos,
    user: CurrentUser,
):
    await _verify_project_access(project_id, repos, user)

    resource_limits = {
        "max_artifact_size_mb": body.max_artifact_size_mb,
        "max_artifacts_count": body.max_artifacts_count,
    }
    orm = await repos.environment.create(
        project_id=project_id,
        name=body.name,
        base_image=body.base_image,
        setup_script=body.setup_script,
        memory_mb=body.memory_mb,
        cpu_cores=body.cpu_cores,
        resource_limits=resource_limits,
        network_policy=body.network_policy,
        env_vars=body.env_vars,
        cache_key=body.cache_key,
    )
    return _to_response(orm)


@router.get(
    "/{env_id}",
    response_model=EnvironmentResponse,
    responses={404: {"model": ErrorResponse}},
    summary="环境详情",
)
async def get_environment(
    project_id: UUID,
    env_id: UUID,
    repos: Repos,
    user: CurrentUser,
):
    await _verify_project_access(project_id, repos, user)

    env = await repos.environment.get_by_id(env_id)
    if env is None or env.project_id != project_id:
        raise HTTPException(status_code=404, detail="Environment not found")
    return _to_response(env)


@router.put(
    "/{env_id}",
    response_model=EnvironmentResponse,
    responses={404: {"model": ErrorResponse}},
    summary="更新环境",
)
async def update_environment(
    project_id: UUID,
    env_id: UUID,
    body: EnvironmentUpdate,
    repos: Repos,
    user: CurrentUser,
):
    await _verify_project_access(project_id, repos, user)

    env = await repos.environment.get_by_id(env_id)
    if env is None or env.project_id != project_id:
        raise HTTPException(status_code=404, detail="Environment not found")

    update_data = body.model_dump(exclude_unset=True)
    limits_fields = {"max_artifact_size_mb", "max_artifacts_count"}
    limits_update = {k: update_data.pop(k) for k in list(update_data) if k in limits_fields}
    if limits_update:
        current_rl = dict(env.resource_limits or {})
        current_rl.update(limits_update)
        update_data["resource_limits"] = current_rl

    updated = await repos.environment.update(env, **update_data)
    return _to_response(updated)


@router.delete(
    "/{env_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
    summary="删除环境",
)
async def delete_environment(
    project_id: UUID,
    env_id: UUID,
    repos: Repos,
    user: CurrentUser,
):
    await _verify_project_access(project_id, repos, user)

    env = await repos.environment.get_by_id(env_id)
    if env is None or env.project_id != project_id:
        raise HTTPException(status_code=404, detail="Environment not found")

    await repos.environment.delete(env)
