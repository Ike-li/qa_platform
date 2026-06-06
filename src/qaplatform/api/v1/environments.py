from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import CurrentUser, Repos, require_project_permission
from qaplatform.api.schemas import (
    EnvironmentCreate,
    EnvironmentResponse,
    EnvironmentUpdate,
    ErrorResponse,
    PaginatedResponse,
)
from qaplatform.dependencies import CryptoService
from qaplatform.domain.services.env_vars_crypto import decrypt_env_vars, encrypt_env_vars

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/environments",
    tags=["environments"],
)

class _EnvironmentAuditState(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    base_image: str
    setup_script: str | None = None
    memory_mb: int
    cpu_cores: float
    disk_mb: int | None = None
    max_artifact_size_mb: int
    max_artifacts_count: int
    network_policy: str
    env_vars: dict[str, int | bool] = Field(default_factory=dict)
    cache_key: str | None = None
    created_at: datetime


class _EnvVarsCryptoFailure(BaseModel):
    operation: str
    project_id: UUID
    environment_id: UUID | None = None
    error_type: str


def _get_crypto(request: Request) -> CryptoService:
    crypto = request.app.state.container.crypto_service
    if crypto is None:
        raise HTTPException(status_code=503, detail="Crypto service not initialised")
    return crypto


def _to_response(orm, crypto: CryptoService) -> EnvironmentResponse:
    rl = orm.resource_limits or {}
    env_vars = decrypt_env_vars(orm.env_vars, environment_id=orm.id, crypto=crypto)
    return EnvironmentResponse(
        id=orm.id,
        project_id=orm.project_id,
        name=orm.name,
        base_image=orm.base_image,
        setup_script=orm.setup_script,
        memory_mb=orm.memory_mb,
        cpu_cores=orm.cpu_cores,
        disk_mb=rl.get("disk_mb"),
        max_artifact_size_mb=rl.get("max_artifact_size_mb", 100),
        max_artifacts_count=rl.get("max_artifacts_count", 50),
        network_policy=orm.network_policy,
        env_vars=env_vars,
        cache_key=orm.cache_key,
        created_at=orm.created_at,
    )


def _to_audit_state(response: EnvironmentResponse) -> _EnvironmentAuditState:
    data = response.model_dump()
    data["env_vars"] = {"redacted": True, "count": len(response.env_vars)}
    return _EnvironmentAuditState.model_validate(data)


async def _write_crypto_failure_audit(
    repos: Repos,
    user: CurrentUser,
    *,
    operation: str,
    project_id: UUID,
    environment_id: UUID | None,
    error: Exception,
) -> None:
    await write_audit(
        repos,
        user,
        action=f"environment.env_vars_{operation}_failed",
        resource_type="environment",
        resource_id=environment_id,
        after=_EnvVarsCryptoFailure(
            operation=operation,
            project_id=project_id,
            environment_id=environment_id,
            error_type=type(error).__name__,
        ),
    )
    commit = getattr(repos.audit, "commit", None)
    if commit is None:
        return
    try:
        await commit()
    except Exception:
        log.warning(
            "audit commit failed after env_vars crypto failure",
            extra={"operation": operation, "environment_id": str(environment_id)},
            exc_info=True,
        )


async def _safe_to_response(
    orm,
    *,
    crypto: CryptoService,
    repos: Repos,
    user: CurrentUser,
    project_id: UUID,
) -> EnvironmentResponse:
    try:
        return _to_response(orm, crypto)
    except Exception as exc:
        await _write_crypto_failure_audit(
            repos,
            user,
            operation="decrypt",
            project_id=project_id,
            environment_id=orm.id,
            error=exc,
        )
        raise HTTPException(status_code=500, detail="Environment env vars decrypt failed") from exc


async def _encrypt_or_500(
    env_vars: dict[str, str],
    *,
    environment_id: UUID,
    crypto: CryptoService,
    repos: Repos,
    user: CurrentUser,
    project_id: UUID,
) -> dict[str, str]:
    try:
        return encrypt_env_vars(env_vars, environment_id=environment_id, crypto=crypto)
    except Exception as exc:
        await _write_crypto_failure_audit(
            repos,
            user,
            operation="encrypt",
            project_id=project_id,
            environment_id=environment_id,
            error=exc,
        )
        raise HTTPException(status_code=500, detail="Environment env vars encrypt failed") from exc


async def _verify_project_access(project_id: UUID, repos: Repos, user):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get(
    "",
    response_model=PaginatedResponse[EnvironmentResponse],
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="环境列表",
)
async def list_environments(
    project_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _perm=require_project_permission(Action.CONFIG_READ),
):
    await _verify_project_access(project_id, repos, user)
    crypto = _get_crypto(request)

    items, total = await repos.environment.list_by_project(
        project_id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[
            await _safe_to_response(
                i,
                crypto=crypto,
                repos=repos,
                user=user,
                project_id=project_id,
            )
            for i in items
        ],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=EnvironmentResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="创建环境",
)
async def create_environment(
    project_id: UUID,
    body: EnvironmentCreate,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CONFIG_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    resource_limits = {
        "max_artifact_size_mb": body.max_artifact_size_mb,
        "max_artifacts_count": body.max_artifacts_count,
    }
    if body.disk_mb is not None:
        resource_limits["disk_mb"] = body.disk_mb
    crypto = _get_crypto(request)
    env_id = uuid4()
    encrypted_env_vars = await _encrypt_or_500(
        body.env_vars,
        environment_id=env_id,
        crypto=crypto,
        repos=repos,
        user=user,
        project_id=project_id,
    )
    orm = await repos.environment.create(
        id=env_id,
        project_id=project_id,
        name=body.name,
        base_image=body.base_image,
        setup_script=body.setup_script,
        memory_mb=body.memory_mb,
        cpu_cores=body.cpu_cores,
        resource_limits=resource_limits,
        network_policy=body.network_policy,
        env_vars=encrypted_env_vars,
        cache_key=body.cache_key,
    )
    response = await _safe_to_response(
        orm,
        crypto=crypto,
        repos=repos,
        user=user,
        project_id=project_id,
    )
    await write_audit(
        repos, user,
        action="environment.create",
        resource_type="environment",
        resource_id=orm.id,
        after=_to_audit_state(response),
    )
    return response


@router.get(
    "/{env_id}",
    response_model=EnvironmentResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="环境详情",
)
async def get_environment(
    project_id: UUID,
    env_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CONFIG_READ),
):
    await _verify_project_access(project_id, repos, user)

    env = await repos.environment.get_for_project(env_id, project_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")
    return await _safe_to_response(
        env,
        crypto=_get_crypto(request),
        repos=repos,
        user=user,
        project_id=project_id,
    )


@router.put(
    "/{env_id}",
    response_model=EnvironmentResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="更新环境",
)
async def update_environment(
    project_id: UUID,
    env_id: UUID,
    body: EnvironmentUpdate,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CONFIG_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    env = await repos.environment.get_for_project(env_id, project_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    crypto = _get_crypto(request)
    before = await _safe_to_response(
        env,
        crypto=crypto,
        repos=repos,
        user=user,
        project_id=project_id,
    )
    update_data = body.model_dump(exclude_unset=True)
    if "env_vars" in update_data:
        update_data["env_vars"] = await _encrypt_or_500(
            update_data["env_vars"],
            environment_id=env.id,
            crypto=crypto,
            repos=repos,
            user=user,
            project_id=project_id,
        )
    limits_fields = {"disk_mb", "max_artifact_size_mb", "max_artifacts_count"}
    limits_update = {k: update_data.pop(k) for k in list(update_data) if k in limits_fields}
    if limits_update:
        current_rl = dict(env.resource_limits or {})
        for key, value in limits_update.items():
            if key == "disk_mb" and value is None:
                current_rl.pop(key, None)
            else:
                current_rl[key] = value
        update_data["resource_limits"] = current_rl

    updated = await repos.environment.update(env, **update_data)
    after = await _safe_to_response(
        updated,
        crypto=crypto,
        repos=repos,
        user=user,
        project_id=project_id,
    )
    await write_audit(
        repos, user,
        action="environment.update",
        resource_type="environment",
        resource_id=updated.id,
        before=_to_audit_state(before),
        after=_to_audit_state(after),
    )
    return after


@router.delete(
    "/{env_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="删除环境",
)
async def delete_environment(
    project_id: UUID,
    env_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CONFIG_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    env = await repos.environment.get_for_project(env_id, project_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    before = await _safe_to_response(
        env,
        crypto=_get_crypto(request),
        repos=repos,
        user=user,
        project_id=project_id,
    )
    await repos.environment.delete(env)
    await write_audit(
        repos, user,
        action="environment.delete",
        resource_type="environment",
        resource_id=env_id,
        before=_to_audit_state(before),
    )
