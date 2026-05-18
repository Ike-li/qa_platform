from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    CurrentUser,
    Repos,
    _get_db_session,
    enforce_project_action,
)
from qaplatform.api.schemas import (
    ErrorResponse,
    NotificationLogResponse,
    NotificationRuleCreate,
    NotificationRuleResponse,
    NotificationRuleUpdate,
    PaginatedResponse,
)

router = APIRouter(
    prefix="/projects/{project_id}/notification-rules",
    tags=["notifications"],
)


def _to_rule_response(orm) -> NotificationRuleResponse:
    return NotificationRuleResponse(
        id=orm.id,
        project_id=orm.project_id,
        name=orm.name,
        enabled=orm.enabled,
        conditions=orm.conditions or [],
        channels=orm.channels or [],
        template=orm.template,
        created_at=orm.created_at,
    )


def _to_log_response(orm) -> NotificationLogResponse:
    return NotificationLogResponse(
        id=orm.id,
        project_id=orm.project_id,
        run_id=orm.run_id,
        rule_id=orm.rule_id,
        channel_type=orm.channel_type,
        status=orm.status.value if hasattr(orm.status, "value") else orm.status,
        error_message=orm.error_message,
        sent_at=orm.sent_at,
    )


@router.get(
    "",
    response_model=PaginatedResponse[NotificationRuleResponse],
    summary="通知规则列表",
)
async def list_notification_rules(
    project_id: UUID,
    repos: Repos,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.NOTIFICATION_READ)

    items, total = await repos.notification_rule.list_by_project(
        project.id, offset=(page - 1) * per_page, limit=per_page,
    )
    return PaginatedResponse(
        data=[_to_rule_response(i) for i in items],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post(
    "",
    response_model=NotificationRuleResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}},
    summary="创建通知规则",
)
async def create_notification_rule(
    project_id: UUID,
    body: NotificationRuleCreate,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.NOTIFICATION_EDIT)

    rule = await repos.notification_rule.create(
        project_id=project.id,
        name=body.name,
        enabled=body.enabled,
        conditions=body.conditions,
        channels=body.channels,
        template=body.template,
    )

    response = _to_rule_response(rule)
    await write_audit(
        repos, user,
        action="notification_rule.create",
        resource_type="notification_rule",
        resource_id=rule.id,
        after=response,
    )
    return response


@router.get(
    "/{rule_id}",
    response_model=NotificationRuleResponse,
    responses={404: {"model": ErrorResponse}},
    summary="通知规则详情",
)
async def get_notification_rule(
    project_id: UUID,
    rule_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.NOTIFICATION_READ)

    rule = await repos.notification_rule.get_by_id(rule_id)
    if rule is None or rule.project_id != project.id:
        raise HTTPException(status_code=404, detail="Notification rule not found")
    return _to_rule_response(rule)


@router.put(
    "/{rule_id}",
    response_model=NotificationRuleResponse,
    responses={404: {"model": ErrorResponse}},
    summary="更新通知规则",
)
async def update_notification_rule(
    project_id: UUID,
    rule_id: UUID,
    body: NotificationRuleUpdate,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.NOTIFICATION_EDIT)

    rule = await repos.notification_rule.get_by_id(rule_id)
    if rule is None or rule.project_id != project.id:
        raise HTTPException(status_code=404, detail="Notification rule not found")

    before = _to_rule_response(rule)

    if body.name is not None:
        rule.name = body.name
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.conditions is not None:
        rule.conditions = body.conditions
    if body.channels is not None:
        rule.channels = body.channels
    if body.template is not None:
        rule.template = body.template

    response = _to_rule_response(rule)
    await write_audit(
        repos, user,
        action="notification_rule.update",
        resource_type="notification_rule",
        resource_id=rule.id,
        before=before,
        after=response,
    )
    return response


@router.delete(
    "/{rule_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
    summary="删除通知规则",
)
async def delete_notification_rule(
    project_id: UUID,
    rule_id: UUID,
    repos: Repos,
    user: CurrentUser,
    session: AsyncSession = Depends(_get_db_session),
):
    project = await repos.project.get_for_tenant(project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await enforce_project_action(session, user, project.id, Action.NOTIFICATION_EDIT)

    rule = await repos.notification_rule.get_by_id(rule_id)
    if rule is None or rule.project_id != project.id:
        raise HTTPException(status_code=404, detail="Notification rule not found")

    await repos.notification_rule.delete(rule)
    await write_audit(
        repos, user,
        action="notification_rule.delete",
        resource_type="notification_rule",
        resource_id=rule_id,
    )
