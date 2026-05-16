from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from qaplatform.api.deps import CurrentUser, Repos
from qaplatform.api.schemas import ErrorResponse

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


async def _get_artifact_or_404(repos, artifact_id: UUID, tenant_id: UUID):
    artifact = await repos.artifact.get_by_id(artifact_id)
    if artifact is None or artifact.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


async def _generate_download_url(s3_client, bucket: str, storage_path: str) -> str:
    url = await s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": storage_path},
        ExpiresIn=3600,
    )
    return url


@router.get(
    "/{artifact_id}/download",
    responses={404: {"model": ErrorResponse}},
    summary="获取产物下载链接",
)
async def download_artifact(
    artifact_id: UUID,
    request: Request,
    repos: Repos,
    user: CurrentUser,
):
    artifact = await _get_artifact_or_404(repos, artifact_id, user.tenant_id)

    container = request.app.state.container
    url = await _generate_download_url(
        container.s3_client,
        container.settings.s3_bucket,
        artifact.storage_path,
    )
    return {"download_url": url, "expires_in": 3600}
