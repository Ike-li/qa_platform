"""Public API endpoints for viewing shared reports without authentication."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.deps import Repos, _get_db_session
from qaplatform.api.run_presenters import is_allure_report_index
from qaplatform.api.schemas import ErrorResponse
from qaplatform.services.report_share_service import verify_share_token

router = APIRouter(prefix="/public/reports", tags=["public-reports"])


@router.get(
    "/{run_id}",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="公开查看分享的报告",
    description="通过临时token访问Allure报告，无需登录",
)
async def view_shared_report(
    run_id: UUID,
    request: Request,
    repos: Repos,
    token: str = Query(..., description="分享token"),
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    """View a shared report using a temporary token.

    This endpoint is publicly accessible (no authentication required).
    It verifies the token, increments the access count, and redirects
    to the Allure report artifact preview if valid.

    Args:
        run_id: The run ID to access
        request: FastAPI request object
        token: Share token string
        repos: Repository bundle
        session: Database session

    Returns:
        RedirectResponse to the artifact preview URL

    Raises:
        HTTPException: 403 if token is invalid, expired, or max access reached
        HTTPException: 404 if run or Allure report not found
        HTTPException: 503 if S3 storage is not available
    """
    container = request.app.state.container
    if container.s3_client is None:
        raise HTTPException(
            status_code=503,
            detail="Report sharing is not available",
        )

    # Verify token and increment access count
    is_valid, share_token_obj = await verify_share_token(
        session=session,
        token=token,
        run_id=run_id,
    )

    if not is_valid:
        if share_token_obj is None:
            # Token not found or run_id mismatch
            raise HTTPException(
                status_code=403,
                detail="Invalid share token",
            )
        # Token exists but is expired or max access reached
        from datetime import datetime, timezone
        if share_token_obj.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=403,
                detail="Share link has expired",
            )
        if (
            share_token_obj.max_access_count is not None
            and share_token_obj.access_count >= share_token_obj.max_access_count
        ):
            raise HTTPException(
                status_code=403,
                detail="Share link access limit reached",
            )
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired share token",
        )

    # Find the Allure report artifact for this run
    offset = 0
    page_size = 100
    artifact = None

    while True:
        items, total = await repos.artifact.list_by_run(
            run_id,
            offset=offset,
            limit=page_size,
        )
        for art in items:
            if is_allure_report_index(art):
                artifact = art
                break
        if artifact is not None:
            break
        offset += len(items)
        if offset >= total or not items:
            break

    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail="Allure report not found for this run",
        )

    # Generate preview URL for the artifact using the same pattern as artifacts.py
    from qaplatform.api.v1.artifacts import (
        _allows_relative_preview_assets,
        _artifact_storage_prefix,
        _create_preview_token,
        _preview_entry_name,
    )

    ttl = container.settings.s3_presigned_url_ttl
    preview_token = _create_preview_token(
        container.settings.jwt_secret,
        artifact.id,
        share_token_obj.tenant_id,
        ttl,
        storage_prefix=_artifact_storage_prefix(artifact.storage_path),
        allow_relative_assets=_allows_relative_preview_assets(artifact),
    )

    preview_url = request.url_for(
        "preview_artifact_file",
        artifact_id=str(artifact.id),
        token=preview_token,
        artifact_path=_preview_entry_name(artifact.name),
    )

    # Redirect to the preview URL
    return RedirectResponse(url=str(preview_url), status_code=302)
