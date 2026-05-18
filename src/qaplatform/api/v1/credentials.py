from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    require_project_permission,
)
from qaplatform.api.schemas import (
    CredentialCreate,
    CredentialResponse,
    CredentialUpdate,
    ErrorResponse,
)
from qaplatform.infra.database.models import Credential as CredentialORM

router = APIRouter(
    prefix="/projects/{project_id}/credentials",
    tags=["credentials"],
)


def _aad(project_id: UUID, name: str) -> str:
    """Additional authenticated data binding ciphertext to (project, name)."""
    return f"credential:{project_id}:{name}"


def _to_response(orm: CredentialORM) -> CredentialResponse:
    return CredentialResponse(
        id=orm.id,
        project_id=orm.project_id,
        name=orm.name,
        type=orm.type,
        created_by=orm.created_by,
        created_at=orm.created_at,
    )


async def _verify_project_access(project_id: UUID, repos: Repos, user: CurrentUser):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get(
    "",
    response_model=list[CredentialResponse],
    summary="项目凭证列表",
)
async def list_credentials(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.CREDENTIAL_READ),
):
    await _verify_project_access(project_id, repos, user)
    rows = (
        await session.execute(
            select(CredentialORM).where(
                CredentialORM.project_id == project_id,
                CredentialORM.tenant_id == user.tenant_id,
            )
        )
    ).scalars().all()
    return [_to_response(c) for c in rows]


@router.post(
    "",
    response_model=CredentialResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="创建凭证",
)
async def create_credential(
    project_id: UUID,
    body: CredentialCreate,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.CREDENTIAL_EDIT),
):
    await _verify_project_access(project_id, repos, user)

    duplicate = (
        await session.execute(
            select(CredentialORM.id).where(
                CredentialORM.project_id == project_id,
                CredentialORM.name == body.name,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Credential name already exists")

    crypto = request.app.state.container.crypto_service
    if crypto is None:
        raise HTTPException(status_code=503, detail="Crypto service not initialised")
    encrypted = crypto.encrypt(body.value, context_id=_aad(project_id, body.name))

    cred = CredentialORM(
        tenant_id=user.tenant_id,
        project_id=project_id,
        name=body.name,
        type=body.type,
        encrypted_value=encrypted,
        created_by=user.user_id,
    )
    session.add(cred)
    await session.flush()
    await session.refresh(cred, ["created_at"])

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
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.CREDENTIAL_READ),
):
    await _verify_project_access(project_id, repos, user)
    cred = (
        await session.execute(
            select(CredentialORM).where(
                CredentialORM.id == credential_id,
                CredentialORM.project_id == project_id,
                CredentialORM.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return _to_response(cred)


@router.put(
    "/{credential_id}",
    response_model=CredentialResponse,
    responses={404: {"model": ErrorResponse}},
    summary="轮换凭证 value",
)
async def update_credential(
    project_id: UUID,
    credential_id: UUID,
    body: CredentialUpdate,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.CREDENTIAL_EDIT),
):
    await _verify_project_access(project_id, repos, user)
    cred = (
        await session.execute(
            select(CredentialORM).where(
                CredentialORM.id == credential_id,
                CredentialORM.project_id == project_id,
                CredentialORM.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    crypto = request.app.state.container.crypto_service
    if crypto is None:
        raise HTTPException(status_code=503, detail="Crypto service not initialised")
    cred.encrypted_value = crypto.encrypt(body.value, context_id=_aad(project_id, cred.name))
    await session.flush()

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
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_project_permission(Action.CREDENTIAL_EDIT),
):
    project = await _verify_project_access(project_id, repos, user)
    cred = (
        await session.execute(
            select(CredentialORM).where(
                CredentialORM.id == credential_id,
                CredentialORM.project_id == project_id,
                CredentialORM.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    if project.credential_id == cred.id:
        raise HTTPException(
            status_code=409,
            detail="Credential is in use by this project (project.credential_id)",
        )

    before = _to_response(cred)
    await session.delete(cred)
    await write_audit(
        repos, user,
        action="credential.delete",
        resource_type="credential",
        resource_id=credential_id,
        before=before,
    )
