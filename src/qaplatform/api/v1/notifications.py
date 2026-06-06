from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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


class _NotificationRuleAuditState(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    enabled: bool
    conditions: list[dict]
    channels: dict[str, object] = Field(default_factory=dict)
    template: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


def _condition_payload(conditions) -> list[dict]:
    return [
        condition.model_dump(exclude_none=True)
        if isinstance(condition, BaseModel)
        else condition
        for condition in conditions
    ]


def _to_rule_response(orm) -> NotificationRuleResponse:
    return NotificationRuleResponse.model_validate(orm)


def _rule_channel_type(channel) -> str:
    if isinstance(channel, dict):
        return str(channel.get("type", "unknown"))
    return str(getattr(channel, "type", "unknown"))


def _to_rule_audit_state(response: NotificationRuleResponse) -> _NotificationRuleAuditState:
    channel_types = [_rule_channel_type(channel) for channel in response.channels]
    return _NotificationRuleAuditState(
        id=response.id,
        project_id=response.project_id,
        name=response.name,
        enabled=response.enabled,
        conditions=_condition_payload(response.conditions),
        channels={
            "redacted": True,
            "count": len(response.channels),
            "types": channel_types,
        },
        template={
            "redacted": True,
            "present": response.template is not None,
            "length": len(response.template or ""),
        },
        created_at=response.created_at,
    )


def _to_log_response(orm) -> NotificationLogResponse:
    return NotificationLogResponse.model_validate(orm)


def _channel_payload(channels) -> list[dict]:
    return [channel.model_dump(exclude_none=True) for channel in channels]


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
        conditions=_condition_payload(body.conditions),
        channels=_channel_payload(body.channels),
        template=body.template,
    )

    response = _to_rule_response(rule)
    await write_audit(
        repos, user,
        action="notification_rule.create",
        resource_type="notification_rule",
        resource_id=rule.id,
        after=_to_rule_audit_state(response),
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

    rule = await repos.notification_rule.get_for_project(rule_id, project.id)
    if rule is None:
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

    rule = await repos.notification_rule.get_for_project(rule_id, project.id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Notification rule not found")

    before = _to_rule_response(rule)

    update_data = {}
    if body.name is not None:
        update_data["name"] = body.name
    if body.enabled is not None:
        update_data["enabled"] = body.enabled
    if body.conditions is not None:
        update_data["conditions"] = _condition_payload(body.conditions)
    if body.channels is not None:
        update_data["channels"] = _channel_payload(body.channels)
    if "template" in body.model_fields_set:
        update_data["template"] = body.template

    updated_rule = await repos.notification_rule.update(rule, **update_data)

    response = _to_rule_response(updated_rule)
    await write_audit(
        repos, user,
        action="notification_rule.update",
        resource_type="notification_rule",
        resource_id=updated_rule.id,
        before=_to_rule_audit_state(before),
        after=_to_rule_audit_state(response),
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

    rule = await repos.notification_rule.get_for_project(rule_id, project.id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Notification rule not found")

    before = _to_rule_response(rule)
    await repos.notification_rule.delete(rule)
    await write_audit(
        repos, user,
        action="notification_rule.delete",
        resource_type="notification_rule",
        resource_id=rule_id,
        before=_to_rule_audit_state(before),
    )
