"""API endpoints for report share token management."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import CurrentUser, Repos, _get_db_session
from qaplatform.api.run_access import get_run_for_action
from qaplatform.api.schemas import ErrorResponse
from qaplatform.services.report_share_service import (
    generate_share_token,
    list_share_tokens,
    revoke_share_token,
)

router = APIRouter(prefix="/runs", tags=["report-shares"])


# Request/Response schemas
class CreateShareTokenRequest(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=90, description="Token有效期（天）")
    max_access_count: int | None = Field(default=None, ge=1, description="最大访问次数限制")


class ShareTokenResponse(BaseModel):
    id: UUID
    share_url: str
    token: str
    expires_at: str
    max_access_count: int | None


class ShareTokenListItem(BaseModel):
    id: UUID
    token: str
    created_by: UUID
    expires_at: str
    is_expired: bool
    access_count: int
    max_access_count: int | None
    last_accessed_at: str | None
    created_at: str


@router.post(
    "/{run_id}/share",
    response_model=ShareTokenResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="生成报告分享链接",
    description="为指定的测试运行生成临时分享链接，可设置有效期和访问次数限制",
)
async def create_share_token(
    run_id: UUID,
    body: CreateShareTokenRequest,
    request: Request,
    user: CurrentUser,
    repos: Repos,
    session: AsyncSession = Depends(_get_db_session),
):
    """Generate a share token for a report."""
    # Check if user has access to this run
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
    )

    # Generate share token
    result = await generate_share_token(
        session=session,
        run_id=run_id,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        expires_in_days=body.expires_in_days,
        max_access_count=body.max_access_count,
    )

    await session.commit()

    # Construct share URL
    # For now, use a relative path - frontend will handle the full URL
    share_url = f"/public/reports/{run_id}?token={result['token']}"

    # Audit log
    await write_audit(
        repos,
        user,
        action="report_share.create",
        resource_type="run",
        resource_id=run_id,
        after={"token_id": str(result["id"]), "expires_in_days": body.expires_in_days},
    )

    return ShareTokenResponse(
        id=result["id"],
        share_url=share_url,
        token=result["token"],
        expires_at=result["expires_at"].isoformat(),
        max_access_count=result["max_access_count"],
    )


@router.get(
    "/{run_id}/shares",
    response_model=list[ShareTokenListItem],
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="列出报告分享链接",
    description="获取指定测试运行的所有分享链接",
)
async def get_share_tokens(
    run_id: UUID,
    user: CurrentUser,
    repos: Repos,
    session: AsyncSession = Depends(_get_db_session),
):
    """List all share tokens for a run."""
    # Check if user has access to this run
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
    )

    # Get share tokens
    tokens = await list_share_tokens(session=session, run_id=run_id)

    return [
        ShareTokenListItem(
            id=token["id"],
            token=token["token"],
            created_by=token["created_by"],
            expires_at=token["expires_at"].isoformat(),
            is_expired=token["is_expired"],
            access_count=token["access_count"],
            max_access_count=token["max_access_count"],
            last_accessed_at=token["last_accessed_at"].isoformat() if token["last_accessed_at"] else None,
            created_at=token["created_at"].isoformat(),
        )
        for token in tokens
    ]


@router.delete(
    "/{run_id}/shares/{token_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="撤销报告分享链接",
    description="撤销指定的分享链接，使其立即失效",
)
async def delete_share_token(
    run_id: UUID,
    token_id: UUID,
    request: Request,
    user: CurrentUser,
    repos: Repos,
    session: AsyncSession = Depends(_get_db_session),
):
    """Revoke a share token."""
    # Check if user has access to this run
    await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run_id,
        action=Action.RUN_READ,
    )

    # Revoke token
    success = await revoke_share_token(session=session, token_id=token_id)

    if not success:
        raise HTTPException(status_code=404, detail="Share token not found")

    # Audit log
    await write_audit(
        repos,
        user,
        action="report_share.revoke",
        resource_type="run",
        resource_id=run_id,
        after={"token_id": str(token_id)},
    )

    return None
