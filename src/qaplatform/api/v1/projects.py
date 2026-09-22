from __future__ import annotations

import re
from typing import Any, get_args
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    require_permission,
    require_project_permission,
)
from qaplatform.api.schemas import (
    ErrorResponse,
    GitBranchDiscoveryRequest,
    GitBranchDiscoveryResponse,
    PaginatedResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectStatusValue,
    ProjectUpdate,
)
from qaplatform.domain.models.project import SilentWindow
from qaplatform.engine.redact import redact_url_userinfo
from qaplatform.infra.database.models import Project as ProjectORM

router = APIRouter(prefix="/projects", tags=["projects"])
_SSH_GIT_URL_RE = re.compile(r"^[^@]+@[^:]+:.+")
_SENSITIVE_PROJECT_SETTINGS_RE = re.compile(
    r"(secret|token|password|passwd|pwd|credential|api[_-]?key|private[_-]?key|auth)",
    re.IGNORECASE,
)
_REDACTED = {"redacted": True}
_PROJECT_STATUS_VALUES = set(get_args(ProjectStatusValue))
_PROJECT_SEARCH_MAX_LENGTH = 500


def _to_response(orm: ProjectORM) -> ProjectResponse:
    settings = orm.settings or {}
    return ProjectResponse.model_validate(orm).model_copy(
        update={
            "silent_windows": [
                SilentWindow.model_validate(window)
                for window in settings.get("silent_windows", [])
            ]
        }
    )


def _to_audit_state(response: ProjectResponse) -> dict:
    data = response.model_dump(mode="json")
    data["git_url"] = redact_url_userinfo(data["git_url"])
    data["settings"] = _redact_project_settings_audit_value(data.get("settings", {}))
    return data


def _redact_project_settings_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: dict(_REDACTED)
            if _is_sensitive_project_settings_key(key)
            else _redact_project_settings_audit_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_project_settings_audit_value(item) for item in value]
    if isinstance(value, str):
        return redact_url_userinfo(value)
    return value


def _is_sensitive_project_settings_key(key: Any) -> bool:
    return isinstance(key, str) and _SENSITIVE_PROJECT_SETTINGS_RE.search(key) is not None


def _public(response: ProjectResponse) -> ProjectResponse:
    """对外响应：省略 settings 中的敏感键。

    刻意用省略而不是替换成哨兵对象——settings 是自由 dict，缺键是它本来就
    合法的状态，而把字符串位置换成 {"redacted": true} 会让按 schema 生成的
    客户端拿到意外类型。

    只作用于 HTTP 响应。审计走 _to_audit_state 自己的脱敏，那里需要保留
    「这个键曾经存在」的信号，两者不能共用同一个函数。
    """
    settings = response.settings or {}
    if not any(_is_sensitive_project_settings_key(key) for key in settings):
        return response
    return response.model_copy(
        update={
            "settings": {
                key: value
                for key, value in settings.items()
                if not _is_sensitive_project_settings_key(key)
            }
        }
    )


def _carry_over_sensitive_settings(incoming: Any, existing: Any) -> Any:
    """把存量 settings 里未被本次请求提及的敏感键带到新 settings。

    PUT 的 settings 是整体替换，而响应里又看不到敏感键，于是「GET 改一处
    再 PUT」的客户端必然不会带上它们。没有这层携带，一次无关的设置修改
    就会静默清掉 webhook_secret。

    请求里显式出现该键（包括传 null）仍以请求为准，这是清除的唯一方式。
    """
    if not isinstance(incoming, dict):
        return incoming
    if not isinstance(existing, dict):
        return incoming
    merged = dict(incoming)
    for key, value in existing.items():
        if _is_sensitive_project_settings_key(key) and key not in merged:
            merged[key] = value
    return merged


def _serialize_silent_windows(windows: list[SilentWindow]) -> list[dict]:
    return [window.model_dump(mode="json") for window in windows]


def _is_https_git_url(value: str) -> bool:
    return urlparse(value).scheme == "https"


def _is_ssh_git_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "ssh" or _SSH_GIT_URL_RE.match(value) is not None


async def _validate_git_credential_binding(
    *,
    repos: Repos,
    tenant_id: UUID,
    project_id: UUID | None,
    git_url: str,
    git_auth_method: str,
    credential_id: UUID | None,
) -> None:
    if git_auth_method == "none":
        if credential_id is not None:
            raise HTTPException(
                status_code=422,
                detail="credential_id requires git_auth_method token or ssh_key",
            )
        return

    if git_auth_method == "token" and not _is_https_git_url(git_url):
        raise HTTPException(
            status_code=422,
            detail="Token Git credentials require an https:// git_url",
        )
    if git_auth_method == "ssh_key" and not _is_ssh_git_url(git_url):
        raise HTTPException(
            status_code=422,
            detail="SSH key Git credentials require an SSH git_url",
        )

    if credential_id is None:
        return
    if project_id is None:
        raise HTTPException(
            status_code=422,
            detail="Create the project before binding a project credential",
        )

    credential = await repos.credential.get_by_project_tenant(
        credential_id,
        project_id,
        tenant_id,
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    expected_type = "token" if git_auth_method == "token" else "ssh_key"
    if credential.type != expected_type:
        raise HTTPException(
            status_code=422,
            detail=f"Credential type must be {expected_type} for git_auth_method={git_auth_method}",
        )


@router.get(
    "",
    response_model=PaginatedResponse[ProjectResponse],
    responses={422: {"model": ErrorResponse}},
    summary="项目列表",
)
async def list_projects(
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, description="按名称/描述/Slug/Git 仓库搜索"),
    status: str | None = Query(
        None,
        description="active / archived",
        json_schema_extra={"enum": sorted(_PROJECT_STATUS_VALUES)},
    ),
    _perm=require_permission(Action.PROJECT_READ),
):
    if status is not None:
        if status == "":
            raise HTTPException(status_code=422, detail="Invalid project status: empty")
        if status not in _PROJECT_STATUS_VALUES:
            raise HTTPException(status_code=422, detail=f"Invalid project status: {status}")
    if q is not None:
        if q.strip() == "":
            raise HTTPException(status_code=422, detail="Invalid project search query: empty")
        if len(q) > _PROJECT_SEARCH_MAX_LENGTH:
            raise HTTPException(status_code=422, detail="Invalid project search query: too long")

    items, total = await repos.project.list_filtered_by_tenant(
        tenant_id=user.tenant_id,
        offset=(page - 1) * per_page,
        limit=per_page,
        status=status,
        query=q,
    )
    return PaginatedResponse(
        data=[_public(_to_response(i)) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="创建项目",
)
async def create_project(
    body: ProjectCreate,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
    _perm=require_permission(Action.PROJECT_CREATE),
):
    existing = await repos.project.get_by_slug(user.tenant_id, body.slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Slug already exists")

    await _validate_git_credential_binding(
        repos=repos,
        tenant_id=user.tenant_id,
        project_id=None,
        git_url=body.git_url,
        git_auth_method=body.git_auth_method,
        credential_id=body.credential_id,
    )

    orm = await repos.project.create(
        tenant_id=user.tenant_id,
        created_by=user.user_id,
        **body.model_dump(),
    )

    # Auto-add the creator as a project admin so a tenant Member who creates
    # a project can immediately operate on it without needing a tenant
    # Owner/Admin to grant them access.
    from qaplatform.infra.database.models import ProjectMember as ProjectMemberORM

    session.add(
        ProjectMemberORM(
            tenant_id=user.tenant_id,
            project_id=orm.id,
            user_id=user.user_id,
            role="admin",
        )
    )
    await session.flush()

    response = _to_response(orm)
    await write_audit(
        repos, user,
        action="project.create",
        resource_type="project",
        resource_id=orm.id,
        after=_to_audit_state(response),
    )
    return _public(response)


@router.post(
    "/branches",
    response_model=GitBranchDiscoveryResponse,
    responses={422: {"model": ErrorResponse}},
    summary="发现 Git 仓库分支",
)
async def discover_git_branches(
    body: GitBranchDiscoveryRequest,
    request: Request,
    repos: Repos,
    user: CurrentUser,
    _perm=require_permission(Action.PROJECT_CREATE),
):
    if body.git_auth_method != "none":
        raise HTTPException(
            status_code=422,
            detail="Branch discovery currently supports public repositories only",
        )
    settings = request.app.state.container.settings
    from qaplatform.plugins.builtin.git_source import GitSource

    source = GitSource(allowed_private_hosts=settings.git_allowed_private_hosts)
    try:
        branches, default_branch = await source.list_branches(body.git_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = GitBranchDiscoveryResponse(
        branches=branches,
        default_branch=default_branch,
    )
    await write_audit(
        repos,
        user,
        action="project.branches_discover",
        resource_type="project",
        after={
            "git_url": redact_url_userinfo(body.git_url),
            "branch_count": len(branches),
            "default_branch": default_branch,
        },
    )
    return response


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorResponse}},
    summary="项目详情",
)
async def get_project(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    _perm=require_permission(Action.PROJECT_READ),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _public(_to_response(project))


@router.put(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="更新项目",
)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.PROJECT_EDIT),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    before = _to_response(project)
    update_data = body.model_dump(exclude_unset=True)
    if body.silent_windows is not None:
        update_data.pop("silent_windows", None)
        settings = dict(update_data.pop("settings", None) or project.settings or {})
        settings["silent_windows"] = _serialize_silent_windows(body.silent_windows)
        update_data["settings"] = settings
    if "settings" in update_data:
        update_data["settings"] = _carry_over_sensitive_settings(
            update_data["settings"], project.settings
        )
    effective_git_url = update_data.get("git_url", project.git_url)
    effective_auth_method = update_data.get("git_auth_method", project.git_auth_method)
    effective_credential_id = (
        update_data["credential_id"]
        if "credential_id" in update_data
        else project.credential_id
    )
    await _validate_git_credential_binding(
        repos=repos,
        tenant_id=user.tenant_id,
        project_id=project.id,
        git_url=effective_git_url,
        git_auth_method=effective_auth_method,
        credential_id=effective_credential_id,
    )
    updated = await repos.project.update(project, **update_data)
    after = _to_response(updated)
    await write_audit(
        repos, user,
        action="project.update",
        resource_type="project",
        resource_id=updated.id,
        before=_to_audit_state(before),
        after=_to_audit_state(after),
    )
    return _public(after)


@router.delete(
    "/{project_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
    summary="删除项目",
)
async def delete_project(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    _perm=require_project_permission(Action.PROJECT_DELETE),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    before = _to_response(project)
    await repos.project.delete(project)
    await write_audit(
        repos, user,
        action="project.delete",
        resource_type="project",
        resource_id=project_id,
        before=_to_audit_state(before),
    )
