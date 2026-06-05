"""Pure helper functions for webhook request parsing and decisions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from fnmatch import fnmatch
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from qaplatform.api.schemas import WebhookTriggerRequest


_INTEGRITY_ERRORS = (SQLAlchemyIntegrityError,)
_FULL_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _branch_name_from_ref(git_ref: str) -> str:
    heads_prefix = "refs/heads/"
    if git_ref.startswith(heads_prefix):
        return git_ref[len(heads_prefix) :]
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


def _dedup_key(
    metadata: dict | None,
    repo_url: str,
    commit_sha: str | None,
    branch_name: str,
) -> str | None:
    if not commit_sha:
        return None
    metadata = metadata or {}
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


def _exception_chain(exc: Exception) -> Iterable[Exception]:
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


def _validate_github_commit_sha(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=400, detail=f"Missing GitHub {context} SHA")
    if not _FULL_GIT_SHA_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid GitHub {context} SHA")
    return value


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
            raise HTTPException(
                status_code=400,
                detail="Missing GitHub repository payload",
            )
        git_ref = payload.get("ref")
        if not isinstance(git_ref, str) or not git_ref.strip():
            raise HTTPException(status_code=400, detail="Missing GitHub ref")
        git_sha = _validate_github_commit_sha(
            payload.get("after"),
            context="commit",
        )
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
            raise HTTPException(
                status_code=400,
                detail="Missing GitHub pull_request payload",
            )
        base = pull_request.get("base")
        head = pull_request.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise HTTPException(
                status_code=400,
                detail="Missing GitHub pull_request refs",
            )
        base_repo = base.get("repo")
        head_repo = head.get("repo")
        if not isinstance(base_repo, dict) or not isinstance(head_repo, dict):
            raise HTTPException(
                status_code=400,
                detail="Missing GitHub pull_request repo",
            )
        if head_repo.get("full_name") != base_repo.get("full_name"):
            raise HTTPException(status_code=202, detail="Fork pull requests are ignored")
        number = pull_request.get("number")
        if not isinstance(number, int):
            raise HTTPException(
                status_code=400,
                detail="Missing GitHub pull_request number or SHA",
            )
        sha = _validate_github_commit_sha(head.get("sha"), context="pull_request")
        full_name = base_repo.get("full_name")
        if isinstance(full_name, str):
            metadata["repository"] = full_name
        return WebhookTriggerRequest(
            git_ref=f"refs/pull/{number}/head",
            git_sha=sha,
            metadata=metadata,
        ), _github_repo_url_candidates(base_repo)

    raise HTTPException(status_code=202, detail=f"Unsupported GitHub event: {event}")
