from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.run_commands import (
    RESERVED_RUN_METADATA_KEYS,
    build_project_run_metadata,
    resolve_project_run_environment_id,
)
from qaplatform.api.run_presenters import to_run_response
from qaplatform.api.schemas import (
    ErrorResponse,
    RunResponse,
    WebhookTriggerRequest,
)
from qaplatform.api.webhook_helpers import (
    _allowed_branch_patterns as _allowed_branch_patterns,
)
from qaplatform.api.webhook_helpers import (
    _branch_allowed as _branch_allowed,
)
from qaplatform.api.webhook_helpers import (
    _branch_name_from_ref as _branch_name_from_ref,
)
from qaplatform.api.webhook_helpers import (
    _dedup_key as _dedup_key,
)
from qaplatform.api.webhook_helpers import (
    _github_payload_to_trigger_request as _github_payload_to_trigger_request,
)
from qaplatform.api.webhook_helpers import (
    _github_repo_url_candidates as _github_repo_url_candidates,
)
from qaplatform.api.webhook_helpers import (
    _is_integrity_error as _is_integrity_error,
)
from qaplatform.api.webhook_helpers import (
    _webhook_decision_audit_state as _webhook_decision_audit_state,
)
from qaplatform.infra.webhook_signature import verify_webhook_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
provider_router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)


def _detail_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                    "required": ["detail"],
                }
            }
        },
    }


def _webhook_decision_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["status"],
                }
            }
        },
    }


async def _duplicate_webhook_response(
    *,
    repos: Repos,
    audit_user,
    project_id: UUID,
    body: WebhookTriggerRequest,
    branch_name: str,
):
    log.info("webhook duplicate run for project %s branch %s", project_id, branch_name)
    await write_audit(
        repos,
        audit_user,
        action="webhook.duplicate",
        resource_type="project",
        resource_id=project_id,
        after=_webhook_decision_audit_state(
            body,
            project_id=project_id,
            branch_name=branch_name,
            status="duplicate",
            reason="dedup_key_conflict",
        ),
    )
    return JSONResponse(status_code=200, content={"status": "duplicate"})


def _signature_header(request: Request) -> str:
    return (
        request.headers.get("X-Webhook-Signature")
        or request.headers.get("X-Hub-Signature-256")
        or ""
    )


async def _create_webhook_run(
    *,
    project,
    body: WebhookTriggerRequest,
    request: Request,
    repos: Repos,
    audit_user,
    session: AsyncSession,
):
    project_resource_id = project.id

    if project.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Project is archived; new runs cannot be triggered",
        )

    branch_name = _branch_name_from_ref(body.git_ref)
    allowed_branches = _allowed_branch_patterns(project.settings)
    if not _branch_allowed(branch_name, allowed_branches):
        log.info("webhook branch filtered for project %s branch %s", project_resource_id, branch_name)
        await write_audit(
            repos,
            audit_user,
            action="webhook.filtered",
            resource_type="project",
            resource_id=project_resource_id,
            after=_webhook_decision_audit_state(
                body,
                project_id=project_resource_id,
                branch_name=branch_name,
                status="filtered",
                reason="branch_not_allowed",
            ),
        )
        return JSONResponse(
            status_code=200,
            content={"status": "filtered", "reason": "branch_not_allowed"},
        )

    pipeline = await repos.pipeline.get_latest_enabled(project.id)
    if pipeline is None:
        raise HTTPException(status_code=409, detail="No pipeline configured for project")

    environment_id = await resolve_project_run_environment_id(
        repos=repos,
        project=project,
    )
    metadata = build_project_run_metadata(
        project,
        extra_metadata=body.metadata,
        reserved_extra_keys=RESERVED_RUN_METADATA_KEYS,
    )

    dedup_key = _dedup_key(body.metadata, project.git_url, body.git_sha, branch_name)
    if dedup_key is not None and await repos.run.get_active_by_dedup(
        project_id=project.id,
        pipeline_id=pipeline.id,
        dedup_key=dedup_key,
    ):
        return await _duplicate_webhook_response(
            repos=repos,
            audit_user=audit_user,
            project_id=project_resource_id,
            body=body,
            branch_name=branch_name,
        )

    try:
        run = await repos.run.create(
            tenant_id=project.tenant_id,
            project_id=project.id,
            pipeline_id=pipeline.id,
            environment_id=environment_id,
            git_ref=body.git_ref,
            git_sha=body.git_sha,
            triggered_by=getattr(audit_user, "user_id", None),
            trigger_type="webhook",
            metadata_=metadata,
            dedup_key=dedup_key,
        )
    except Exception as exc:
        if dedup_key is None or not _is_integrity_error(exc):
            raise
        await session.rollback()
        return await _duplicate_webhook_response(
            repos=repos,
            audit_user=audit_user,
            project_id=project_resource_id,
            body=body,
            branch_name=branch_name,
        )
    await repos.run.set_retry_group_id(run.id, run.id)

    container = request.app.state.container
    arq_pool = getattr(container, "arq_pool", None)
    if arq_pool is not None:
        from qaplatform.infra.queue.scheduler import enqueue_run

        await enqueue_run(arq_pool, repos.run, run, "webhook", container.settings)

    response = to_run_response(run)
    await write_audit(
        repos,
        audit_user,
        action="run.trigger",
        resource_type="run",
        resource_id=run.id,
        after=response,
    )
    return response


@router.post(
    "/{project_id}/trigger",
    response_model=RunResponse,
    status_code=201,
    responses={
        200: _webhook_decision_response("Webhook was filtered or marked duplicate"),
        401: _detail_response("Missing or invalid webhook signature"),
        404: {"model": ErrorResponse},
        409: _detail_response("Webhook cannot trigger a run for the project state"),
    },
    summary="Webhook 触发执行",
)
async def webhook_trigger(
    project_id: UUID,
    body: WebhookTriggerRequest,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # --- Webhook HMAC-SHA256 signature verification ---
    webhook_secret: str | None = (project.settings or {}).get("webhook_secret")
    if webhook_secret:
        signature_header = _signature_header(request)
        if not signature_header:
            raise HTTPException(
                status_code=401,
                detail="Missing X-Webhook-Signature header",
            )
        raw_body = await request.body()
        if not verify_webhook_signature(webhook_secret, raw_body, signature_header):
            raise HTTPException(
                status_code=401,
                detail="Invalid webhook signature",
            )

    await enforce_project_action(session, user, project.id, Action.RUN_TRIGGER)
    return await _create_webhook_run(
        project=project,
        body=body,
        request=request,
        repos=repos,
        audit_user=user,
        session=session,
    )


@provider_router.post(
    "/{provider}",
    response_model=RunResponse,
    status_code=201,
    responses={
        200: _webhook_decision_response("Webhook was filtered or marked duplicate"),
        202: _detail_response("Provider event was accepted but ignored"),
        400: _detail_response("Provider webhook payload is invalid"),
        401: _detail_response("Missing or invalid webhook signature"),
        404: {"model": ErrorResponse},
        409: _detail_response("Webhook repository match is ambiguous or not runnable"),
    },
    summary="Git provider webhook 触发执行",
)
async def provider_webhook_trigger(
    provider: str,
    request: Request,
    repos: Repos,
    session: AsyncSession = Depends(_get_db_session, scope="function"),
):
    provider_key = provider.lower()
    if provider_key != "github":
        raise HTTPException(status_code=404, detail="Unsupported webhook provider")

    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook JSON")

    event = request.headers.get("X-GitHub-Event", "push")
    delivery_id = request.headers.get("X-GitHub-Delivery")
    body, repo_urls = _github_payload_to_trigger_request(
        payload,
        event=event,
        delivery_id=delivery_id,
    )
    if not repo_urls:
        raise HTTPException(status_code=400, detail="Missing repository URL")

    projects = await repos.project.list_by_git_urls(repo_urls)
    if not projects:
        raise HTTPException(status_code=404, detail="No project matches webhook repository")

    signature_header = _signature_header(request)
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing webhook signature header")

    signed_projects = []
    for project in projects:
        secret = (project.settings or {}).get("webhook_secret")
        if isinstance(secret, str) and secret:
            if verify_webhook_signature(secret, raw_body, signature_header):
                signed_projects.append(project)

    if not signed_projects:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    if len(signed_projects) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous webhook repository match")

    project = signed_projects[0]
    audit_user = SimpleNamespace(tenant_id=project.tenant_id, user_id=None)
    return await _create_webhook_run(
        project=project,
        body=body,
        request=request,
        repos=repos,
        audit_user=audit_user,
        session=session,
    )
