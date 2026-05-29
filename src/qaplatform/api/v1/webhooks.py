from __future__ import annotations

import logging
from fnmatch import fnmatch
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
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
provider_router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)
_INTEGRITY_ERRORS = (
    SQLAlchemyIntegrityError,
)
_RESERVED_METADATA_KEYS = {
    "git_url",
    "git_auth_method",
    "credential_id",
    "shallow_clone",
    "default_branch",
}
_RESERVED_METADATA_KEYS_LOWER = {key.lower() for key in _RESERVED_METADATA_KEYS}


def _branch_name_from_ref(git_ref: str) -> str:
    heads_prefix = "refs/heads/"
    if git_ref.startswith(heads_prefix):
        return git_ref[len(heads_prefix):]
    return git_ref


def _allowed_branch_patterns(settings: dict | None) -> list[str]:
    allowed = (settings or {}).get("allowed_branches", [])
    if not isinstance(allowed, list):
        return []
    return [pattern for pattern in allowed if isinstance(pattern, str) and pattern]


def _branch_allowed(branch_name: str, allowed_patterns: list[str]) -> bool:
    if not allowed_patterns:
        return True
    return any(fnmatch(branch_name, pattern) for pattern in allowed_patterns)


def _dedup_key(metadata: dict, repo_url: str, commit_sha: str | None, branch_name: str) -> str | None:
    if not commit_sha:
        return None
    provider = str(metadata.get("provider") or "webhook")
    return f"{provider}:{repo_url}:{commit_sha}:{branch_name}"


def _webhook_decision_audit_state(
    body: WebhookTriggerRequest,
    *,
    project_id: UUID,
    branch_name: str,
    status: str,
    reason: str,
) -> dict:
    metadata = body.metadata or {}
    state = {
        "project_id": str(project_id),
        "status": status,
        "reason": reason,
        "git_ref": body.git_ref,
        "git_sha": body.git_sha,
        "branch_name": branch_name,
        "provider": str(metadata.get("provider") or "webhook"),
    }
    delivery_id = metadata.get("delivery_id")
    if delivery_id is not None:
        state["delivery_id"] = str(delivery_id)
    return state


def _exception_chain(exc: Exception):
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend(
            (
                getattr(current, "orig", None),
                current.__cause__,
                current.__context__,
            )
        )


def _is_integrity_error(exc: Exception) -> bool:
    if any(
        isinstance(candidate, _INTEGRITY_ERRORS)
        or candidate.__class__.__name__ in {"IntegrityError", "UniqueViolationError"}
        for candidate in _exception_chain(exc)
    ):
        return True
    message = repr(exc)
    return "UniqueViolationError" in message or "duplicate key value" in message


def _to_run_response(orm) -> RunResponse:
    from qaplatform.api.v1.runs import _to_run_response as _to_resp
    return _to_resp(orm)


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


def _github_repo_url_candidates(repo: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for key in ("clone_url", "ssh_url", "git_url", "html_url"):
        value = repo.get(key)
        if isinstance(value, str) and value:
            candidates.add(value)
            if key == "html_url" and not value.endswith(".git"):
                candidates.add(f"{value}.git")

    full_name = repo.get("full_name")
    if isinstance(full_name, str) and "/" in full_name:
        candidates.update(
            {
                f"https://github.com/{full_name}",
                f"https://github.com/{full_name}.git",
                f"git@github.com:{full_name}.git",
            }
        )
    return candidates


def _github_payload_to_trigger_request(
    payload: dict[str, Any],
    *,
    event: str,
    delivery_id: str | None,
) -> tuple[WebhookTriggerRequest, set[str]]:
    metadata = {"provider": "github", "event": event}
    if delivery_id:
        metadata["delivery_id"] = delivery_id

    if event == "push":
        repo = payload.get("repository")
        if not isinstance(repo, dict):
            raise HTTPException(status_code=400, detail="Missing GitHub repository payload")
        git_ref = payload.get("ref")
        git_sha = payload.get("after")
        if not isinstance(git_ref, str) or not git_ref:
            raise HTTPException(status_code=400, detail="Missing GitHub ref")
        if not isinstance(git_sha, str) or not git_sha:
            raise HTTPException(status_code=400, detail="Missing GitHub commit SHA")
        full_name = repo.get("full_name")
        if isinstance(full_name, str):
            metadata["repository"] = full_name
        return WebhookTriggerRequest(
            git_ref=git_ref,
            git_sha=git_sha,
            metadata=metadata,
        ), _github_repo_url_candidates(repo)

    if event == "pull_request":
        pull_request = payload.get("pull_request")
        if not isinstance(pull_request, dict):
            raise HTTPException(status_code=400, detail="Missing GitHub pull_request payload")
        base = pull_request.get("base")
        head = pull_request.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise HTTPException(status_code=400, detail="Missing GitHub pull_request refs")
        base_repo = base.get("repo")
        head_repo = head.get("repo")
        if not isinstance(base_repo, dict) or not isinstance(head_repo, dict):
            raise HTTPException(status_code=400, detail="Missing GitHub pull_request repo")
        if head_repo.get("full_name") != base_repo.get("full_name"):
            raise HTTPException(status_code=202, detail="Fork pull requests are ignored")
        number = pull_request.get("number")
        sha = head.get("sha")
        if not isinstance(number, int) or not isinstance(sha, str) or not sha:
            raise HTTPException(status_code=400, detail="Missing GitHub pull_request number or SHA")
        full_name = base_repo.get("full_name")
        if isinstance(full_name, str):
            metadata["repository"] = full_name
        return WebhookTriggerRequest(
            git_ref=f"refs/pull/{number}/head",
            git_sha=sha,
            metadata=metadata,
        ), _github_repo_url_candidates(base_repo)

    raise HTTPException(status_code=202, detail=f"Unsupported GitHub event: {event}")


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

    pipelines, _ = await repos.pipeline.list_by_project(project.id, limit=1)
    if not pipelines:
        raise HTTPException(status_code=409, detail="No pipeline configured for project")
    pipeline = pipelines[0]

    environment_id = project.default_env_id
    if environment_id is None:
        envs, _ = await repos.environment.list_by_project(project.id, limit=1)
        if envs:
            environment_id = envs[0].id
        else:
            raise HTTPException(status_code=409, detail="No environment configured for project")

    metadata = {"git_url": project.git_url}
    if project.git_auth_method != "none" and project.credential_id:
        metadata["git_auth_method"] = project.git_auth_method
        metadata["credential_id"] = str(project.credential_id)
    if project.shallow_clone:
        metadata["shallow_clone"] = True
    if project.default_branch:
        metadata["default_branch"] = project.default_branch
    metadata.update(
        {
            key: value
            for key, value in body.metadata.items()
            if key.lower() not in _RESERVED_METADATA_KEYS_LOWER
        }
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
    run.retry_group_id = run.id

    container = request.app.state.container
    arq_pool = getattr(container, "arq_pool", None)
    if arq_pool is not None:
        from qaplatform.worker.scheduler import enqueue_run

        await enqueue_run(arq_pool, repos.run, run, "webhook", container.settings)

    response = _to_run_response(run)
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
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Git provider webhook 触发执行",
)
async def provider_webhook_trigger(
    provider: str,
    request: Request,
    repos: Repos,
    session: AsyncSession = Depends(_get_db_session),
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
