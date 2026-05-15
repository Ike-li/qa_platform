from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Action(str, Enum):
    # Project
    PROJECT_READ = "project.read"
    PROJECT_CREATE = "project.create"
    PROJECT_EDIT = "project.edit"
    PROJECT_DELETE = "project.delete"

    # Run
    RUN_READ = "run.read"
    RUN_TRIGGER = "run.trigger"
    RUN_CANCEL = "run.cancel"
    RUN_CANCEL_OWN = "run.cancel.own"

    # Pipeline
    PIPELINE_READ = "pipeline.read"
    PIPELINE_EDIT = "pipeline.edit"

    # Config
    CONFIG_READ = "config.read"
    CONFIG_EDIT = "config.edit"

    # Credential
    CREDENTIAL_READ = "credential.read"
    CREDENTIAL_EDIT = "credential.edit"

    # Member
    MEMBER_READ = "member.read"
    MEMBER_EDIT = "member.edit"

    # Token
    TOKEN_MANAGE = "token.manage"

    # Schedule
    SCHEDULE_READ = "schedule.read"
    SCHEDULE_EDIT = "schedule.edit"


# Permission matrix: role -> set of allowed actions
ROLE_PERMISSIONS: dict[Role, set[Action]] = {
    Role.PLATFORM_ADMIN: set(Action),  # all actions
    Role.DEVELOPER: {
        Action.PROJECT_READ,
        Action.PROJECT_CREATE,
        Action.PROJECT_EDIT,
        Action.RUN_READ,
        Action.RUN_TRIGGER,
        Action.RUN_CANCEL_OWN,
        Action.PIPELINE_READ,
        Action.PIPELINE_EDIT,
        Action.CONFIG_READ,
        Action.CONFIG_EDIT,
        Action.CREDENTIAL_READ,
        Action.CREDENTIAL_EDIT,
        Action.MEMBER_READ,
        Action.TOKEN_MANAGE,
        Action.SCHEDULE_READ,
        Action.SCHEDULE_EDIT,
    },
    Role.VIEWER: {
        Action.PROJECT_READ,
        Action.RUN_READ,
        Action.PIPELINE_READ,
        Action.CONFIG_READ,
        Action.MEMBER_READ,
        Action.CREDENTIAL_READ,
        Action.SCHEDULE_READ,
    },
}


@dataclass(frozen=True)
class PermissionContext:
    user_id: str
    role: str
    tenant_id: str
    is_own_resource: bool = False


def check_permission(
    ctx: PermissionContext,
    action: Action,
) -> bool:
    """Check whether a user is allowed to perform an action.

    platform_admin bypasses all checks.
    For run.cancel.own, the caller must set is_own_resource=True.
    """
    try:
        role = Role(ctx.role)
    except ValueError:
        return False

    allowed = ROLE_PERMISSIONS.get(role, set())
    if action in allowed:
        return True

    # run.cancel falls back to run.cancel.own when the resource is owned
    if action == Action.RUN_CANCEL and Action.RUN_CANCEL_OWN in allowed:
        return ctx.is_own_resource

    return False
