from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import CurrentUser, Repos, require_permission
from qaplatform.api.schemas import (
    ErrorResponse,
    PaginatedResponse,
    PipelineCreate,
    PipelineResponse,
    PipelineUpdate,
    RetryPolicyInput,
    StageDefinitionInput,
    TestSelectorInput,
    TriggerConfigInput,
)

router = APIRouter(
    prefix="/projects/{project_id}/pipelines",
    tags=["pipelines"],
)


def _to_response(orm) -> PipelineResponse:
    stages = [StageDefinitionInput(**s) for s in (orm.stages or [])]
    selector = TestSelectorInput(**(orm.selector or {}))
    trigger = TriggerConfigInput(**(orm.trigger_config or {}))
    retry = RetryPolicyInput(**orm.retry_policy) if orm.retry_policy else None
    return PipelineResponse(
        id=orm.id,
        project_id=orm.project_id,
        name=orm.name,
        stages=stages,
        selector=selector,
        trigger_config=trigger,
        timeout_seconds=orm.timeout_seconds,
        retry_policy=retry,
        enabled=orm.enabled,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


async def _verify_project_access(project_id: UUID, repos: Repos, user):
    project = await repos.project.get_by_id(project_id)
    if project is None or project.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get(
    "",
    response_model=PaginatedResponse[PipelineResponse],
    summary="Pipeline 列表",
)
async def list_pipelines(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    await _verify_project_access(project_id, repos, user)

    items, total = await repos.pipeline.list_by_project(
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
    response_model=PipelineResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}},
    summary="创建 Pipeline",
)
async def create_pipeline(
    project_id: UUID,
    body: PipelineCreate,
    repos: Repos,
    user: CurrentUser,
    _perm=require_permission(Action.PIPELINE_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    orm = await repos.pipeline.create(
        project_id=project_id,
        name=body.name,
        stages=[s.model_dump() for s in body.stages],
        selector=body.selector.model_dump(),
        trigger_config=body.trigger_config.model_dump(),
        timeout_seconds=body.timeout_seconds,
        retry_policy=body.retry_policy.model_dump() if body.retry_policy else None,
        enabled=body.enabled,
    )
    response = _to_response(orm)
    await write_audit(
        repos, user,
        action="pipeline.create",
        resource_type="pipeline",
        resource_id=orm.id,
        after=response,
    )
    return response


@router.get(
    "/{pipeline_id}",
    response_model=PipelineResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Pipeline 详情",
)
async def get_pipeline(
    project_id: UUID,
    pipeline_id: UUID,
    repos: Repos,
    user: CurrentUser,
):
    await _verify_project_access(project_id, repos, user)

    pipeline = await repos.pipeline.get_by_id(pipeline_id)
    if pipeline is None or pipeline.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return _to_response(pipeline)


@router.put(
    "/{pipeline_id}",
    response_model=PipelineResponse,
    responses={404: {"model": ErrorResponse}},
    summary="更新 Pipeline",
)
async def update_pipeline(
    project_id: UUID,
    pipeline_id: UUID,
    body: PipelineUpdate,
    repos: Repos,
    user: CurrentUser,
    _perm=require_permission(Action.PIPELINE_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    pipeline = await repos.pipeline.get_by_id(pipeline_id)
    if pipeline is None or pipeline.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    before = _to_response(pipeline)
    update_data = body.model_dump(exclude_unset=True)
    if "stages" in update_data and update_data["stages"] is not None:
        update_data["stages"] = [s.model_dump() for s in body.stages]
    if "selector" in update_data and update_data["selector"] is not None:
        update_data["selector"] = body.selector.model_dump()
    if "trigger_config" in update_data and update_data["trigger_config"] is not None:
        update_data["trigger_config"] = body.trigger_config.model_dump()
    if "retry_policy" in update_data and update_data["retry_policy"] is not None:
        update_data["retry_policy"] = body.retry_policy.model_dump()

    updated = await repos.pipeline.update(pipeline, **update_data)
    after = _to_response(updated)
    await write_audit(
        repos, user,
        action="pipeline.update",
        resource_type="pipeline",
        resource_id=updated.id,
        before=before,
        after=after,
    )
    return after


@router.delete(
    "/{pipeline_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
    summary="删除 Pipeline",
)
async def delete_pipeline(
    project_id: UUID,
    pipeline_id: UUID,
    repos: Repos,
    user: CurrentUser,
    _perm=require_permission(Action.PIPELINE_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    pipeline = await repos.pipeline.get_by_id(pipeline_id)
    if pipeline is None or pipeline.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    before = _to_response(pipeline)
    await repos.pipeline.delete(pipeline)
    await write_audit(
        repos, user,
        action="pipeline.delete",
        resource_type="pipeline",
        resource_id=pipeline_id,
        before=before,
    )
