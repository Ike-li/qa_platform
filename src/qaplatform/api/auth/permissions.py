from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    """Tenant-level role.

    Permissions form an intersection with :class:`ProjectRole` for project-scoped
    actions. Tenant Owner/Admin implicitly has project Admin rights inside the
    same tenant; tenant Viewer is read-only regardless of project role.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectRole(str, Enum):
    """Project-level role, stored in ``project_member.role``."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


_TENANT_ROLE_ALIASES: dict[str, Role] = {
    # Legacy strings persisted in app_user.role before the dual-layer RBAC migration.
    "platform_admin": Role.ADMIN,
    "developer": Role.MEMBER,
    "user": Role.MEMBER,
}


def normalize_tenant_role(raw: str) -> Role | None:
    """Resolve a stored role string (legacy or canonical) to a :class:`Role`."""
    if raw in _TENANT_ROLE_ALIASES:
        return _TENANT_ROLE_ALIASES[raw]
    try:
        return Role(raw)
    except ValueError:
        return None


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


# Actions whose authorisation requires both tenant-level and project-level role
# (intersection semantics). Project-level enforcement is wired in a later
# commit; this set documents intent and is consumed by the dependency layer.
PROJECT_SCOPED_ACTIONS: frozenset[Action] = frozenset({
    Action.PROJECT_EDIT,
    Action.PROJECT_DELETE,
    Action.RUN_TRIGGER,
    Action.RUN_CANCEL,
    Action.RUN_CANCEL_OWN,
    Action.PIPELINE_READ,
    Action.PIPELINE_EDIT,
    Action.CONFIG_READ,
    Action.CONFIG_EDIT,
    Action.CREDENTIAL_READ,
    Action.CREDENTIAL_EDIT,
    Action.SCHEDULE_READ,
    Action.SCHEDULE_EDIT,
    Action.MEMBER_READ,
    Action.MEMBER_EDIT,
    Action.RUN_READ,
})

TENANT_SCOPED_ACTIONS: frozenset[Action] = frozenset({
    Action.PROJECT_CREATE,
    Action.PROJECT_READ,
    Action.TOKEN_MANAGE,
})

# ``RUN_READ`` and ``MEMBER_READ`` apply at project scope when a project_id is
# in the request (e.g. /projects/{id}/runs); list endpoints further filter by
# tenant_id and ProjectMember rows server-side.


# Tenant-level permission matrix
TENANT_ROLE_PERMISSIONS: dict[Role, set[Action]] = {
    Role.OWNER: set(Action),
    Role.ADMIN: set(Action),
    Role.MEMBER: {
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

# Project-level permission matrix (used by Commit 4 enforcement).
PROJECT_ROLE_PERMISSIONS: dict[ProjectRole, set[Action]] = {
    ProjectRole.ADMIN: {
        a for a in PROJECT_SCOPED_ACTIONS
    },
    ProjectRole.DEVELOPER: {
        Action.PROJECT_EDIT,
        Action.RUN_READ,
        Action.RUN_TRIGGER,
        Action.RUN_CANCEL_OWN,
        Action.PIPELINE_READ,
        Action.PIPELINE_EDIT,
        Action.CONFIG_READ,
        Action.CONFIG_EDIT,
        Action.CREDENTIAL_READ,
        Action.SCHEDULE_READ,
        Action.SCHEDULE_EDIT,
        Action.MEMBER_READ,
    },
    ProjectRole.VIEWER: {
        Action.RUN_READ,
        Action.PIPELINE_READ,
        Action.CONFIG_READ,
        Action.CREDENTIAL_READ,
        Action.SCHEDULE_READ,
        Action.MEMBER_READ,
    },
}


# Backwards-compatible alias used by existing tests / debug pages.
ROLE_PERMISSIONS = TENANT_ROLE_PERMISSIONS


@dataclass(frozen=True)
class PermissionContext:
    user_id: str
    role: str
    tenant_id: str
    is_own_resource: bool = False
    project_id: str | None = None
    project_role: ProjectRole | None = None
    is_platform_admin: bool = False


def check_permission(
    ctx: PermissionContext,
    action: Action,
) -> bool:
    """Check whether a user is allowed to perform ``action``.

    Tenant-only check by default. When ``ctx.project_role`` is provided and
    ``action`` is in :data:`PROJECT_SCOPED_ACTIONS`, both the tenant-level
    and project-level matrices must allow the action (intersection).
    Tenant Owner/Admin keep their cross-project authority and bypass the
    project-level check inside their own tenant.

    A user with ``is_platform_admin=True`` bypasses both layers (still scoped
    to their resolved ``tenant_id`` — cross-tenant access is enforced at the
    request boundary, not here).
    """
    if ctx.is_platform_admin:
        return True

    role = normalize_tenant_role(ctx.role)
    if role is None:
        return False

    tenant_allowed = TENANT_ROLE_PERMISSIONS.get(role, set())
    tenant_ok = action in tenant_allowed
    if not tenant_ok and action == Action.RUN_CANCEL and Action.RUN_CANCEL_OWN in tenant_allowed:
        tenant_ok = ctx.is_own_resource
    if not tenant_ok:
        return False

    if action not in PROJECT_SCOPED_ACTIONS:
        return True

    if role in (Role.OWNER, Role.ADMIN):
        return True

    if ctx.project_role is None:
        return False

    project_allowed = PROJECT_ROLE_PERMISSIONS.get(ctx.project_role, set())
    if action in project_allowed:
        return True
    if action == Action.RUN_CANCEL and Action.RUN_CANCEL_OWN in project_allowed:
        return ctx.is_own_resource
    return False
