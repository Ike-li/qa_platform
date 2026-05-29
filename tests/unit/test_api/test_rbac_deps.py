"""Unit tests for the RBAC dependency layer (require_project_permission /
enforce_project_action) — covers tenant∩project intersection edge cases that
unit-level check_permission tests can't exercise (path-param parsing, ORM
lookup short-circuits, platform-admin bypass).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import enforce_project_action


def _user(role: str = "member", is_platform_admin: bool = False):
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        role=role,
        tenant_id=uuid.uuid4(),
        is_platform_admin=is_platform_admin,
    )


def _session_returning_role(raw_role_value):
    """Return an AsyncMock session whose execute(...).scalar_one_or_none()
    yields the given ProjectMember.role string (or None for no row)."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=raw_role_value)
    session.execute = AsyncMock(return_value=result)
    return session


def _session_returning_project_then_role(project_id, raw_role_value):
    """Return a session for require_project_permission's project + role queries."""
    session = AsyncMock()

    project_result = MagicMock()
    project_result.scalar_one_or_none = MagicMock(return_value=project_id)
    role_result = MagicMock()
    role_result.scalar_one_or_none = MagicMock(return_value=raw_role_value)

    session.execute = AsyncMock(side_effect=[project_result, role_result])
    return session


class TestEnforceProjectAction:
    """The intersection should:
    - allow tenant Owner/Admin without consulting ProjectMember (bypass)
    - allow platform_admin unconditionally
    - require a ProjectMember row for tenant Member/Viewer
    - within ProjectMember, gate by ProjectRole permission matrix
    """

    @pytest.mark.asyncio
    async def test_member_with_no_project_membership_is_denied(self):
        user = _user(role="member")
        session = _session_returning_role(None)

        with pytest.raises(HTTPException) as exc:
            await enforce_project_action(
                session, user, uuid.uuid4(), Action.PIPELINE_EDIT
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_member_with_project_admin_role_is_allowed(self):
        user = _user(role="member")
        session = _session_returning_role("admin")

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_EDIT
        )

    @pytest.mark.asyncio
    async def test_member_with_project_viewer_cannot_edit(self):
        user = _user(role="member")
        session = _session_returning_role("viewer")

        with pytest.raises(HTTPException) as exc:
            await enforce_project_action(
                session, user, uuid.uuid4(), Action.PIPELINE_EDIT
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_member_with_project_viewer_can_read(self):
        user = _user(role="member")
        session = _session_returning_role("viewer")

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_READ
        )

    @pytest.mark.asyncio
    async def test_tenant_owner_bypasses_project_lookup(self):
        """Tenant Owner has cross-project authority: ProjectMember is never queried."""
        user = _user(role="owner")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_EDIT
        )
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_tenant_admin_bypasses_project_lookup(self):
        user = _user(role="admin")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_EDIT
        )
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_platform_admin_bypasses_everything(self):
        user = _user(role="member", is_platform_admin=True)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_EDIT
        )
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_cancel_own_resource_for_member(self):
        """RUN_CANCEL with is_own_resource=True should be allowed for a
        ProjectMember(developer) even when full RUN_CANCEL is not granted."""
        user = _user(role="member")
        session = _session_returning_role("developer")

        # Developer can cancel own runs
        await enforce_project_action(
            session, user, uuid.uuid4(), Action.RUN_CANCEL,
            is_own_resource=True,
        )

    @pytest.mark.asyncio
    async def test_non_project_scoped_action_raises_value_error(self):
        user = _user(role="owner")
        session = AsyncMock()

        with pytest.raises(ValueError, match="non-project-scoped"):
            await enforce_project_action(
                session, user, uuid.uuid4(), Action.PROJECT_CREATE,
            )


class TestRequireProjectPermission:
    """The Depends factory layer adds:
    - path-param extraction (UUID parse)
    - 500 if path-param name doesn't exist
    - 422 on malformed UUID
    Beyond that, the same intersection logic applies — covered above.
    """

    @pytest.mark.asyncio
    async def test_invalid_uuid_raises_422(self):
        from qaplatform.api.deps import require_project_permission

        dep = require_project_permission(Action.PIPELINE_READ)
        # Depends wraps the inner function — pull it back out for direct call.
        inner = dep.dependency

        request = MagicMock()
        request.path_params = {"project_id": "not-a-uuid"}
        user = _user(role="owner")
        session = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await inner(request, user, session)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_project_id_param_raises_500(self):
        from qaplatform.api.deps import require_project_permission

        dep = require_project_permission(
            Action.PIPELINE_READ, project_id_param="other_id"
        )
        inner = dep.dependency

        request = MagicMock()
        request.path_params = {"project_id": str(uuid.uuid4())}
        user = _user(role="owner")
        session = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await inner(request, user, session)
        assert exc.value.status_code == 500

    def test_factory_rejects_non_project_scoped_action(self):
        from qaplatform.api.deps import require_project_permission

        with pytest.raises(ValueError, match="non-project-scoped"):
            require_project_permission(Action.PROJECT_CREATE)

    @pytest.mark.asyncio
    async def test_missing_or_cross_tenant_project_raises_404_before_rbac(self):
        from qaplatform.api.deps import require_project_permission

        dep = require_project_permission(Action.PIPELINE_READ)
        inner = dep.dependency
        project_id = uuid.uuid4()

        request = MagicMock()
        request.path_params = {"project_id": str(project_id)}
        user = _user(role="member")

        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=None)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=project_result)

        with pytest.raises(HTTPException) as exc:
            await inner(request, user, session)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Project not found"
        assert session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_visible_project_member_without_membership_is_403(self):
        from qaplatform.api.deps import require_project_permission

        dep = require_project_permission(Action.PIPELINE_READ)
        inner = dep.dependency
        project_id = uuid.uuid4()

        request = MagicMock()
        request.path_params = {"project_id": str(project_id)}
        user = _user(role="member")
        session = _session_returning_project_then_role(project_id, None)

        with pytest.raises(HTTPException) as exc:
            await inner(request, user, session)
        assert exc.value.status_code == 403
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_tenant_owner_bypasses_project_visibility_lookup(self):
        from qaplatform.api.deps import require_project_permission

        dep = require_project_permission(Action.PIPELINE_EDIT)
        inner = dep.dependency
        project_id = uuid.uuid4()

        request = MagicMock()
        request.path_params = {"project_id": str(project_id)}
        user = _user(role="owner")

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        await inner(request, user, session)
        session.execute.assert_not_called()
