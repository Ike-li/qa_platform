from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    require_project_permission,
)
from qaplatform.api.schemas import (
    CredentialCreate,
    CredentialResponse,
    CredentialUpdate,
    ErrorResponse,
    PaginatedResponse,
)

router = APIRouter(
    prefix="/projects/{project_id}/credentials",
    tags=["credentials"],
)


def _aad(project_id: UUID, name: str) -> str:
    """Additional authenticated data binding ciphertext to (project, name)."""
    return f"credential:{project_id}:{name}"


def _to_response(orm) -> CredentialResponse:
    return CredentialResponse.model_validate(orm)


async def _verify_project_access(project_id: UUID, repos: Repos, user: CurrentUser):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get(
    "",
    response_model=PaginatedResponse[CredentialResponse],
    summary="项目凭证列表",
)
async def list_credentials(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _perm=require_project_permission(Action.CREDENTIAL_READ),
):
    await _verify_project_access(project_id, repos, user)
    rows, total = await repos.credential.list_by_project_tenant(
        project_id,
        user.tenant_id,
        offset=(page - 1) * per_page,
        limit=per_page,
    )
    return PaginatedResponse(
        data=[_to_response(c) for c in rows],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=CredentialResponse,
    status_code=201,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="创建凭证",
)
async def create_credential(
    project_id: UUID,
    body: CredentialCreate,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CREDENTIAL_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    if await repos.credential.get_name_exists(project_id, body.name):
        raise HTTPException(status_code=409, detail="Credential name already exists")

    crypto = request.app.state.container.crypto_service
    if crypto is None:
        raise HTTPException(status_code=503, detail="Crypto service not initialised")
    encrypted = crypto.encrypt(body.value, context_id=_aad(project_id, body.name))

    cred = await repos.credential.create(
        tenant_id=user.tenant_id,
        project_id=project_id,
        name=body.name,
        type=body.type,
        encrypted_value=encrypted,
        created_by=user.user_id,
    )

    response = _to_response(cred)
    await write_audit(
        repos, user,
        action="credential.create",
        resource_type="credential",
        resource_id=cred.id,
        after=response,
    )
    return response


@router.get(
    "/{credential_id}",
    response_model=CredentialResponse,
    responses={404: {"model": ErrorResponse}},
    summary="凭证详情",
)
async def get_credential(
    project_id: UUID,
    credential_id: UUID,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CREDENTIAL_READ),
):
    await _verify_project_access(project_id, repos, user)
    cred = await repos.credential.get_by_project_tenant(credential_id, project_id, user.tenant_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return _to_response(cred)


@router.put(
    "/{credential_id}",
    response_model=CredentialResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="轮换凭证 value",
)
async def update_credential(
    project_id: UUID,
    credential_id: UUID,
    body: CredentialUpdate,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CREDENTIAL_EDIT),
):
    await _verify_project_access(project_id, repos, user)
    cred = await repos.credential.get_by_project_tenant(credential_id, project_id, user.tenant_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    crypto = request.app.state.container.crypto_service
    if crypto is None:
        raise HTTPException(status_code=503, detail="Crypto service not initialised")
    encrypted = crypto.encrypt(body.value, context_id=_aad(project_id, cred.name))
    await repos.credential.update(cred, encrypted_value=encrypted)

    response = _to_response(cred)
    await write_audit(
        repos, user,
        action="credential.rotate",
        resource_type="credential",
        resource_id=cred.id,
        after=response,
    )
    return response


@router.delete(
    "/{credential_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="删除凭证",
)
async def delete_credential(
    project_id: UUID,
    credential_id: UUID,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.CREDENTIAL_EDIT),
):
    project = await _verify_project_access(project_id, repos, user)
    cred = await repos.credential.get_by_project_tenant(credential_id, project_id, user.tenant_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    if project.credential_id == cred.id:
        raise HTTPException(
            status_code=409,
            detail="Credential is in use by this project (project.credential_id)",
        )

    before = _to_response(cred)
    await repos.credential.delete(cred)
    await write_audit(
        repos, user,
        action="credential.delete",
        resource_type="credential",
        resource_id=credential_id,
        before=before,
    )
