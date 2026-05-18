from __future__ import annotations

import pytest

from qaplatform.api.auth.permissions import (
    PROJECT_ROLE_PERMISSIONS,
    PROJECT_SCOPED_ACTIONS,
    ROLE_PERMISSIONS,
    TENANT_ROLE_PERMISSIONS,
    Action,
    PermissionContext,
    ProjectRole,
    Role,
    check_permission,
    normalize_tenant_role,
)


class TestTenantRolePermissions:
    def test_owner_has_all_actions(self):
        assert TENANT_ROLE_PERMISSIONS[Role.OWNER] == set(Action)

    def test_admin_has_all_actions(self):
        assert TENANT_ROLE_PERMISSIONS[Role.ADMIN] == set(Action)

    def test_legacy_role_permissions_alias_matches_tenant(self):
        assert ROLE_PERMISSIONS is TENANT_ROLE_PERMISSIONS

    def test_viewer_has_read_only_actions(self):
        viewer_perms = TENANT_ROLE_PERMISSIONS[Role.VIEWER]
        for action in viewer_perms:
            assert "read" in action.value or action == Action.CREDENTIAL_READ

    def test_viewer_cannot_trigger_runs(self):
        assert Action.RUN_TRIGGER not in TENANT_ROLE_PERMISSIONS[Role.VIEWER]

    def test_member_can_trigger_runs(self):
        assert Action.RUN_TRIGGER in TENANT_ROLE_PERMISSIONS[Role.MEMBER]

    def test_member_cannot_cancel_arbitrary_run(self):
        assert Action.RUN_CANCEL not in TENANT_ROLE_PERMISSIONS[Role.MEMBER]
        assert Action.RUN_CANCEL_OWN in TENANT_ROLE_PERMISSIONS[Role.MEMBER]

    def test_member_covers_expected_actions(self):
        expected = {
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
            Action.NOTIFICATION_READ,
            Action.NOTIFICATION_EDIT,
        }
        assert TENANT_ROLE_PERMISSIONS[Role.MEMBER] == expected


class TestProjectRolePermissions:
    def test_admin_covers_all_project_scoped_actions(self):
        assert PROJECT_ROLE_PERMISSIONS[ProjectRole.ADMIN] == set(PROJECT_SCOPED_ACTIONS)

    def test_developer_can_trigger_runs_but_not_delete_project(self):
        dev = PROJECT_ROLE_PERMISSIONS[ProjectRole.DEVELOPER]
        assert Action.RUN_TRIGGER in dev
        assert Action.PROJECT_DELETE not in dev

    def test_developer_can_only_cancel_own(self):
        dev = PROJECT_ROLE_PERMISSIONS[ProjectRole.DEVELOPER]
        assert Action.RUN_CANCEL not in dev
        assert Action.RUN_CANCEL_OWN in dev

    def test_viewer_is_read_only(self):
        viewer = PROJECT_ROLE_PERMISSIONS[ProjectRole.VIEWER]
        assert all("read" in a.value for a in viewer)


class TestNormalizeTenantRole:
    def test_legacy_platform_admin_maps_to_admin(self):
        assert normalize_tenant_role("platform_admin") is Role.ADMIN

    def test_legacy_developer_maps_to_member(self):
        assert normalize_tenant_role("developer") is Role.MEMBER

    def test_legacy_user_maps_to_member(self):
        assert normalize_tenant_role("user") is Role.MEMBER

    def test_canonical_owner(self):
        assert normalize_tenant_role("owner") is Role.OWNER

    def test_unknown_returns_none(self):
        assert normalize_tenant_role("nonexistent") is None


class TestCheckPermission:
    def test_owner_always_allowed(self):
        ctx = PermissionContext(user_id="u1", role="owner", tenant_id="t1")
        for action in Action:
            assert check_permission(ctx, action) is True

    def test_legacy_platform_admin_string_still_allowed(self):
        ctx = PermissionContext(user_id="u1", role="platform_admin", tenant_id="t1")
        for action in Action:
            assert check_permission(ctx, action) is True

    def test_viewer_allowed_for_read(self):
        # PROJECT_READ is tenant-scoped (project list); RUN_READ is project-scoped
        # so it requires a project_role for non-Owner/Admin tenants.
        ctx_tenant = PermissionContext(user_id="u1", role="viewer", tenant_id="t1")
        assert check_permission(ctx_tenant, Action.PROJECT_READ) is True

        ctx_project = PermissionContext(
            user_id="u1", role="viewer", tenant_id="t1",
            project_id="p1", project_role=ProjectRole.VIEWER,
        )
        assert check_permission(ctx_project, Action.RUN_READ) is True

    def test_viewer_denied_for_trigger(self):
        ctx = PermissionContext(
            user_id="u1", role="viewer", tenant_id="t1",
            project_id="p1", project_role=ProjectRole.ADMIN,  # intersection: still no
        )
        assert check_permission(ctx, Action.RUN_TRIGGER) is False

    def test_member_allowed_for_trigger_with_developer_project_role(self):
        ctx = PermissionContext(
            user_id="u1", role="member", tenant_id="t1",
            project_id="p1", project_role=ProjectRole.DEVELOPER,
        )
        assert check_permission(ctx, Action.RUN_TRIGGER) is True

    def test_member_denied_for_trigger_without_project_role(self):
        ctx = PermissionContext(user_id="u1", role="member", tenant_id="t1")
        assert check_permission(ctx, Action.RUN_TRIGGER) is False

    def test_legacy_developer_string_allowed_for_trigger_with_project_role(self):
        ctx = PermissionContext(
            user_id="u1", role="developer", tenant_id="t1",
            project_id="p1", project_role=ProjectRole.DEVELOPER,
        )
        assert check_permission(ctx, Action.RUN_TRIGGER) is True

    def test_member_cancel_own_allowed(self):
        ctx = PermissionContext(
            user_id="u1", role="member", tenant_id="t1", is_own_resource=True,
            project_id="p1", project_role=ProjectRole.DEVELOPER,
        )
        assert check_permission(ctx, Action.RUN_CANCEL) is True

    def test_member_cancel_others_denied(self):
        ctx = PermissionContext(
            user_id="u1", role="member", tenant_id="t1", is_own_resource=False,
            project_id="p1", project_role=ProjectRole.DEVELOPER,
        )
        assert check_permission(ctx, Action.RUN_CANCEL) is False

    def test_owner_bypasses_missing_project_role(self):
        ctx = PermissionContext(user_id="u1", role="owner", tenant_id="t1")
        assert check_permission(ctx, Action.RUN_TRIGGER) is True
        assert check_permission(ctx, Action.PIPELINE_EDIT) is True

    def test_admin_bypasses_missing_project_role(self):
        ctx = PermissionContext(user_id="u1", role="admin", tenant_id="t1")
        assert check_permission(ctx, Action.RUN_TRIGGER) is True

    def test_intersection_tenant_viewer_blocks_project_admin_writes(self):
        # PRD intersection: tenant Viewer + project Admin still cannot write.
        ctx = PermissionContext(
            user_id="u1", role="viewer", tenant_id="t1",
            project_id="p1", project_role=ProjectRole.ADMIN,
        )
        assert check_permission(ctx, Action.RUN_TRIGGER) is False
        assert check_permission(ctx, Action.PIPELINE_EDIT) is False

    def test_intersection_project_viewer_blocks_tenant_member_writes(self):
        # tenant Member can trigger runs in general, but if their project_role
        # is Viewer the intersection allows only reads.
        ctx = PermissionContext(
            user_id="u1", role="member", tenant_id="t1",
            project_id="p1", project_role=ProjectRole.VIEWER,
        )
        assert check_permission(ctx, Action.RUN_TRIGGER) is False
        assert check_permission(ctx, Action.RUN_READ) is True

    def test_viewer_cancel_any_denied(self):
        ctx = PermissionContext(user_id="u1", role="viewer", tenant_id="t1")
        assert check_permission(ctx, Action.RUN_CANCEL) is False
        assert check_permission(ctx, Action.RUN_CANCEL_OWN) is False

    def test_unknown_role_denied(self):
        ctx = PermissionContext(user_id="u1", role="nonexistent", tenant_id="t1")
        assert check_permission(ctx, Action.PROJECT_READ) is False

    def test_empty_role_denied(self):
        ctx = PermissionContext(user_id="u1", role="", tenant_id="t1")
        assert check_permission(ctx, Action.PROJECT_READ) is False


class TestPermissionContext:
    def test_frozen(self):
        ctx = PermissionContext(user_id="u1", role="viewer", tenant_id="t1")
        with pytest.raises(AttributeError):
            ctx.user_id = "u2"  # type: ignore[misc]

    def test_optional_project_fields_default_none(self):
        ctx = PermissionContext(user_id="u1", role="member", tenant_id="t1")
        assert ctx.project_id is None
        assert ctx.project_role is None
