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
from qaplatform.api.audit import write_audit
from qaplatform.api.schemas import (
    ErrorResponse,
    RunResponse,
    WebhookTriggerRequest,
)
from qaplatform.infra.webhook_signature import verify_webhook_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _to_run_response(orm) -> RunResponse:
    from qaplatform.api.v1.runs import _to_run_response as _to_resp
    return _to_resp(orm)


@router.post(
    "/{project_id}/trigger",
    response_model=RunResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Webhook 触发执行",
)
async def webhook_trigger(
    project_id: UUID,
    body: WebhookTriggerRequest,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Project is archived; new runs cannot be triggered",
        )

    # --- Webhook HMAC-SHA256 signature verification ---
    webhook_secret: str | None = (project.settings or {}).get("webhook_secret")
    if webhook_secret:
        signature_header = request.headers.get("X-Webhook-Signature", "")
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

    # Resolve pipeline — use the first active pipeline for the project
    pipelines, _ = await repos.pipeline.list_by_project(project.id, limit=1)
    if not pipelines:
        raise HTTPException(status_code=409, detail="No pipeline configured for project")
    pipeline = pipelines[0]

    # Resolve environment
    environment_id = project.default_env_id
    if environment_id is None:
        envs, _ = await repos.environment.list_by_project(project.id, limit=1)
        if envs:
            environment_id = envs[0].id
        else:
            raise HTTPException(status_code=409, detail="No environment configured for project")

    RESERVED_KEYS = {"git_url", "credential_id", "shallow_clone", "default_branch"}
    _RESERVED_LOWER = {k.lower() for k in RESERVED_KEYS}
    metadata = {"git_url": project.git_url}
    if project.git_auth_method != "none" and project.credential_id:
        metadata["credential_id"] = str(project.credential_id)
    if project.shallow_clone:
        metadata["shallow_clone"] = True
    if project.default_branch:
        metadata["default_branch"] = project.default_branch
    metadata.update({k: v for k, v in body.metadata.items() if k.lower() not in _RESERVED_LOWER})

    run = await repos.run.create(
        tenant_id=user.tenant_id,
        project_id=project.id,
        pipeline_id=pipeline.id,
        environment_id=environment_id,
        git_ref=body.git_ref,
        git_sha=body.git_sha,
        triggered_by=user.user_id,
        trigger_type="webhook",
        metadata_=metadata,
    )
    run.retry_group_id = run.id

    container = request.app.state.container
    arq_pool = getattr(container, "arq_pool", None)
    if arq_pool is not None:
        from qaplatform.worker.scheduler import enqueue_run

        await enqueue_run(arq_pool, repos.run, run, "webhook", container.settings)

    response = _to_run_response(run)
    await write_audit(
        repos, user,
        action="run.trigger",
        resource_type="run",
        resource_id=run.id,
        after=response,
    )
    return response
