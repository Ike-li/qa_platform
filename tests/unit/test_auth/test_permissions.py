from __future__ import annotations

import pytest

from qaplatform.api.auth.permissions import (
    ROLE_PERMISSIONS,
    Action,
    PermissionContext,
    Role,
    check_permission,
)


class TestRolePermissions:
    def test_platform_admin_has_all_actions(self):
        admin_perms = ROLE_PERMISSIONS[Role.PLATFORM_ADMIN]
        assert admin_perms == set(Action)

    def test_viewer_has_read_only_actions(self):
        viewer_perms = ROLE_PERMISSIONS[Role.VIEWER]
        for action in viewer_perms:
            assert "read" in action.value or action == Action.CREDENTIAL_READ

    def test_viewer_cannot_trigger_runs(self):
        assert Action.RUN_TRIGGER not in ROLE_PERMISSIONS[Role.VIEWER]

    def test_developer_can_trigger_runs(self):
        assert Action.RUN_TRIGGER in ROLE_PERMISSIONS[Role.DEVELOPER]

    def test_developer_cannot_cancel_any_run(self):
        # developer has run.cancel.own but not run.cancel
        assert Action.RUN_CANCEL not in ROLE_PERMISSIONS[Role.DEVELOPER]
        assert Action.RUN_CANCEL_OWN in ROLE_PERMISSIONS[Role.DEVELOPER]

    def test_roles_cover_expected_actions(self):
        expected_dev = {
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
        }
        assert ROLE_PERMISSIONS[Role.DEVELOPER] == expected_dev


class TestCheckPermission:
    def test_platform_admin_always_allowed(self):
        ctx = PermissionContext(user_id="u1", role="platform_admin", tenant_id="t1")
        for action in Action:
            assert check_permission(ctx, action) is True

    def test_viewer_allowed_for_read(self):
        ctx = PermissionContext(user_id="u1", role="viewer", tenant_id="t1")
        assert check_permission(ctx, Action.PROJECT_READ) is True
        assert check_permission(ctx, Action.RUN_READ) is True

    def test_viewer_denied_for_trigger(self):
        ctx = PermissionContext(user_id="u1", role="viewer", tenant_id="t1")
        assert check_permission(ctx, Action.RUN_TRIGGER) is False

    def test_developer_allowed_for_trigger(self):
        ctx = PermissionContext(user_id="u1", role="developer", tenant_id="t1")
        assert check_permission(ctx, Action.RUN_TRIGGER) is True

    def test_developer_cancel_own_allowed(self):
        ctx = PermissionContext(
            user_id="u1", role="developer", tenant_id="t1", is_own_resource=True
        )
        assert check_permission(ctx, Action.RUN_CANCEL) is True

    def test_developer_cancel_others_denied(self):
        ctx = PermissionContext(
            user_id="u1", role="developer", tenant_id="t1", is_own_resource=False
        )
        assert check_permission(ctx, Action.RUN_CANCEL) is False

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
