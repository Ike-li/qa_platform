from __future__ import annotations

import mimetypes
from datetime import datetime, timedelta, timezone
from inspect import isawaitable
from pathlib import PurePosixPath
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
_PREVIEW_TOKEN_AUDIENCE = "artifact-preview"


def _preview_asset_origin_source(request: Request) -> str:
    url = getattr(request, "url", None)
    scheme = getattr(url, "scheme", None)
    netloc = getattr(url, "netloc", None)
    if scheme in {"http", "https"} and isinstance(netloc, str) and netloc:
        return f"{scheme}://{netloc}"
    return "'self'"


def _preview_response_headers(request: Request) -> dict[str, str]:
    asset_origin = _preview_asset_origin_source(request)
    csp = (
        "sandbox allow-scripts allow-downloads; "
        "default-src 'none'; "
        f"script-src {asset_origin} 'unsafe-inline' 'unsafe-eval' blob:; "
        f"style-src {asset_origin} 'unsafe-inline'; "
        f"img-src {asset_origin} data: blob:; "
        f"font-src {asset_origin} data:; "
        f"connect-src {asset_origin}; "
        f"worker-src {asset_origin} blob:; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "object-src 'none'"
    )
    return {
        "Cache-Control": "private, max-age=60",
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Access-Control-Allow-Origin": "*",
    }


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


def _artifact_storage_prefix(storage_path: str) -> str:
    return storage_path.rsplit("/", 1)[0] if "/" in storage_path else ""


def _is_html_preview_artifact(artifact) -> bool:
    name = str(getattr(artifact, "name", "")).lower()
    mime_type = str(getattr(artifact, "mime_type", "")).split(";", 1)[0].strip().lower()
    if getattr(artifact, "type", "") == "allure-report":
        return name.endswith(".html") or name.endswith(".htm")
    return (
        getattr(artifact, "type", "") == "html"
        or mime_type == "text/html"
        or name.endswith(".html")
        or name.endswith(".htm")
    )


def _allows_relative_preview_assets(artifact) -> bool:
    name = str(getattr(artifact, "name", "")).lower()
    return (
        getattr(artifact, "type", "") == "allure-report"
        and name.endswith("allure-report/index.html")
    )


def _create_preview_token(
    secret: str,
    artifact_id: UUID,
    expires_in: int,
    *,
    storage_prefix: str,
    allow_relative_assets: bool,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "aud": _PREVIEW_TOKEN_AUDIENCE,
            "sub": str(artifact_id),
            "prefix": storage_prefix,
            "assets": allow_relative_assets,
            "exp": now + timedelta(seconds=expires_in),
            "iat": now,
        },
        secret,
        algorithm="HS256",
    )


def _verify_preview_token(secret: str, token: str, artifact_id: UUID) -> dict:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_PREVIEW_TOKEN_AUDIENCE,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=403, detail="Artifact preview link is invalid") from exc
    if payload.get("sub") != str(artifact_id):
        raise HTTPException(status_code=403, detail="Artifact preview link is invalid")
    return payload


def _preview_entry_name(artifact_name: str) -> str:
    entry = PurePosixPath(artifact_name).name
    return entry or "index.html"


def _storage_key_for_preview_path(
    storage_path: str,
    artifact_path: str,
    *,
    allow_relative_assets: bool,
) -> str:
    rel = PurePosixPath(artifact_path)
    if rel.is_absolute() or any(part in {"", ".."} for part in rel.parts):
        raise HTTPException(status_code=404, detail="Artifact preview file not found")
    if not allow_relative_assets and rel.as_posix() != PurePosixPath(storage_path).name:
        raise HTTPException(status_code=404, detail="Artifact preview file not found")

    base = _artifact_storage_prefix(storage_path)
    target = rel.as_posix()
    return f"{base}/{target}" if base else target


async def _read_s3_body(body) -> bytes:
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    if hasattr(body, "read"):
        value = body.read()
        if isawaitable(value):
            value = await value
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
    return bytes(body)


def _is_missing_object_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return True
    return exc.__class__.__name__ in {"NoSuchKey", "NoSuchKeyError"}


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


@router.get(
    "/{artifact_id}/preview-url",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="获取产物预览链接",
)
async def get_artifact_preview_url(
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
            detail="Artifact preview is not available",
        )
    if not _is_html_preview_artifact(artifact):
        raise HTTPException(status_code=404, detail="Artifact preview is not available")

    ttl = container.settings.s3_presigned_url_ttl
    token = _create_preview_token(
        container.settings.jwt_secret,
        artifact_id,
        ttl,
        storage_prefix=_artifact_storage_prefix(artifact.storage_path),
        allow_relative_assets=_allows_relative_preview_assets(artifact),
    )
    preview_url = request.url_for(
        "preview_artifact_file",
        artifact_id=str(artifact_id),
        token=token,
        artifact_path=_preview_entry_name(artifact.name),
    )
    return {"preview_url": str(preview_url), "expires_in": ttl}


@router.get(
    "/{artifact_id}/preview/{token}/{artifact_path:path}",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="预览产物文件",
)
async def preview_artifact_file(
    artifact_id: UUID,
    token: str,
    artifact_path: str,
    request: Request,
    repos: Repos,
):
    container = request.app.state.container
    if container.s3_client is None:
        raise HTTPException(
            status_code=503,
            detail="Artifact preview is not available",
        )

    payload = _verify_preview_token(container.settings.jwt_secret, token, artifact_id)
    artifact = await repos.artifact.get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact preview file not found")
    if payload.get("prefix") != _artifact_storage_prefix(artifact.storage_path):
        raise HTTPException(status_code=403, detail="Artifact preview link is invalid")

    key = _storage_key_for_preview_path(
        artifact.storage_path,
        artifact_path,
        allow_relative_assets=payload.get("assets") is True,
    )
    try:
        response = await container.s3_client.get_object(
            Bucket=container.settings.s3_bucket,
            Key=key,
        )
    except Exception as exc:
        if _is_missing_object_error(exc):
            raise HTTPException(
                status_code=404,
                detail="Artifact preview file not found",
            ) from exc
        raise

    content = await _read_s3_body(response.get("Body", b""))
    media_type, _ = mimetypes.guess_type(artifact_path)
    return Response(
        content=content,
        media_type=media_type or "application/octet-stream",
        headers=_preview_response_headers(request),
    )
