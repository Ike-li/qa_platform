from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.schemas import ErrorResponse

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


async def _get_artifact_or_404(repos, artifact_id: UUID, tenant_id: UUID):
    artifact = await repos.artifact.get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    run = await repos.run.get_for_tenant(artifact.run_id, tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact, run


async def _generate_download_url(s3_client, bucket: str, storage_path: str, expires_in: int) -> str:
    url = await s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": storage_path},
        ExpiresIn=expires_in,
    )
    return url


@router.get(
    "/{artifact_id}/download",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="获取产物下载链接",
)
async def download_artifact(
    artifact_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    artifact, run = await _get_artifact_or_404(repos, artifact_id, user.tenant_id)
    await enforce_project_action(session, user, run.project_id, Action.RUN_READ)

    container = request.app.state.container
    if container.s3_client is None:
        raise HTTPException(
            status_code=503,
            detail="Artifact download is not available",
        )
    ttl = container.settings.s3_presigned_url_ttl
    url = await _generate_download_url(
        container.s3_client,
        container.settings.s3_bucket,
        artifact.storage_path,
        ttl,
    )
    return {"download_url": url, "expires_in": ttl}
