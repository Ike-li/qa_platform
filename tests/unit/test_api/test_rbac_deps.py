"""Unit tests for the RBAC dependency layer (require_project_permission /
enforce_project_action) — covers tenant∩project intersection edge cases that
unit-level check_permission tests can't exercise (path-param parsing, ORM
lookup short-circuits, platform-admin bypass).
"""
from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

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
    member = None
    if raw_role_value is not None:
        member = SimpleNamespace(role=raw_role_value)
    result.scalar_one_or_none = MagicMock(return_value=member)
    session.execute = AsyncMock(return_value=result)
    return session


def _session_returning_project_then_role(project_id, raw_role_value):
    """Return a session for require_project_permission's project + role queries."""
    session = AsyncMock()

    project_result = MagicMock()
    project_result.scalar_one_or_none = MagicMock(return_value=SimpleNamespace(id=project_id))
    role_result = MagicMock()
    member = None
    if raw_role_value is not None:
        member = SimpleNamespace(role=raw_role_value)
    role_result.scalar_one_or_none = MagicMock(return_value=member)

    session.execute = AsyncMock(side_effect=[project_result, role_result])
    return session


def _executed_statement_column_params(
    session,
    index: int,
    column_names: list[str],
) -> dict[str, object]:
    statement = session.execute.await_args_list[index].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    bound_params: dict[str, object] = {}
    param_names: set[str] = set()
    for column_name in column_names:
        match = re.search(rf"{re.escape(column_name)} = %\(([^)]+)\)s", sql)
        assert match is not None, sql
        param_name = match.group(1)
        param_names.add(param_name)
        bound_params[column_name] = compiled.params[param_name]
    assert set(compiled.params) == param_names
    return bound_params


def _assert_execute_param_sequence(
    session,
    expected_param_maps: list[dict[str, object]],
) -> None:
    assert len(session.execute.await_args_list) == len(expected_param_maps)
    assert [
        _executed_statement_column_params(session, index, list(expected_params))
        for index, expected_params in enumerate(expected_param_maps)
    ] == expected_param_maps


def _assert_project_visibility_lookup_used(session, project_id, user) -> None:
    assert _executed_statement_column_params(
        session,
        0,
        ["project.id", "project.tenant_id"],
    ) == {
        "project.id": project_id,
        "project.tenant_id": user.tenant_id,
    }


def _assert_project_role_lookup_used(session, project_id, user) -> None:
    assert _executed_statement_column_params(
        session,
        -1,
        [
            "project_member.project_id",
            "project_member.user_id",
            "project_member.tenant_id",
        ],
    ) == {
        "project_member.project_id": project_id,
        "project_member.user_id": user.user_id,
        "project_member.tenant_id": user.tenant_id,
    }


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
                session, user, project_id := uuid.uuid4(), Action.PIPELINE_EDIT
            )
        assert exc.value.status_code == 403
        assert exc.value.detail == "Insufficient permissions"
        session.execute.assert_awaited_once()
        _assert_project_role_lookup_used(session, project_id, user)

    @pytest.mark.asyncio
    async def test_member_with_project_admin_role_is_allowed(self):
        user = _user(role="member")
        project_id = uuid.uuid4()
        session = _session_returning_role("admin")

        await enforce_project_action(
            session, user, project_id, Action.PIPELINE_EDIT
        )

        session.execute.assert_awaited_once()
        _assert_project_role_lookup_used(session, project_id, user)

    @pytest.mark.asyncio
    async def test_member_with_project_viewer_cannot_edit(self):
        user = _user(role="member")
        session = _session_returning_role("viewer")

        with pytest.raises(HTTPException) as exc:
            await enforce_project_action(
                session, user, project_id := uuid.uuid4(), Action.PIPELINE_EDIT
            )
        assert exc.value.status_code == 403
        assert exc.value.detail == "Insufficient permissions"
        session.execute.assert_awaited_once()
        _assert_project_role_lookup_used(session, project_id, user)

    @pytest.mark.asyncio
    async def test_member_with_project_viewer_can_read(self):
        user = _user(role="member")
        project_id = uuid.uuid4()
        session = _session_returning_role("viewer")

        await enforce_project_action(
            session, user, project_id, Action.PIPELINE_READ
        )

        session.execute.assert_awaited_once()
        _assert_project_role_lookup_used(session, project_id, user)

    @pytest.mark.asyncio
    async def test_tenant_owner_bypasses_project_lookup(self):
        """Tenant Owner has cross-project authority: ProjectMember is never queried."""
        user = _user(role="owner")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_EDIT
        )
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tenant_admin_bypasses_project_lookup(self):
        user = _user(role="admin")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_EDIT
        )
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_platform_admin_bypasses_everything(self):
        user = _user(role="member", is_platform_admin=True)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        await enforce_project_action(
            session, user, uuid.uuid4(), Action.PIPELINE_EDIT
        )
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_cancel_own_resource_for_member(self):
        """RUN_CANCEL with is_own_resource=True should be allowed for a
        ProjectMember(developer) even when full RUN_CANCEL is not granted."""
        user = _user(role="member")
        project_id = uuid.uuid4()
        session = _session_returning_role("developer")

        # Developer can cancel own runs
        await enforce_project_action(
            session, user, project_id, Action.RUN_CANCEL,
            is_own_resource=True,
        )

        session.execute.assert_awaited_once()
        _assert_project_role_lookup_used(session, project_id, user)

    @pytest.mark.asyncio
    async def test_non_project_scoped_action_raises_value_error(self):
        user = _user(role="owner")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=AssertionError("should not query"))

        with pytest.raises(ValueError) as exc_info:
            await enforce_project_action(
                session, user, uuid.uuid4(), Action.PROJECT_CREATE,
            )

        assert exc_info.value.args == (
            f"enforce_project_action used for non-project-scoped action: {Action.PROJECT_CREATE}",
        )
        session.execute.assert_not_awaited()


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
        session.execute = AsyncMock(side_effect=AssertionError("invalid UUID must not query"))

        with pytest.raises(HTTPException) as exc:
            await inner(request, user, session)
        assert exc.value.status_code == 422
        assert exc.value.detail == "Invalid project_id"
        session.execute.assert_not_awaited()

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
        session.execute = AsyncMock(
            side_effect=AssertionError("missing path param must not query")
        )

        with pytest.raises(HTTPException) as exc:
            await inner(request, user, session)
        assert exc.value.status_code == 500
        assert exc.value.detail == "project_id missing from path; expected 'other_id'"
        session.execute.assert_not_awaited()

    def test_factory_rejects_non_project_scoped_action(self):
        from qaplatform.api.deps import require_project_permission

        with pytest.raises(ValueError) as exc_info:
            require_project_permission(Action.PROJECT_CREATE)

        assert exc_info.value.args == (
            f"require_project_permission used for non-project-scoped action: {Action.PROJECT_CREATE}",
        )

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
        _assert_execute_param_sequence(
            session,
            [{"project.id": project_id, "project.tenant_id": user.tenant_id}],
        )
        error_payload = repr(exc.value.detail) + repr(exc.value.args)
        assert str(project_id) not in error_payload
        assert str(user.tenant_id) not in error_payload
        assert str(user.user_id) not in error_payload

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
        assert exc.value.detail == "Insufficient permissions"
        _assert_execute_param_sequence(
            session,
            [
                {
                    "project.id": project_id,
                    "project.tenant_id": user.tenant_id,
                },
                {
                    "project_member.project_id": project_id,
                    "project_member.user_id": user.user_id,
                    "project_member.tenant_id": user.tenant_id,
                },
            ],
        )
        error_payload = repr(exc.value.detail) + repr(exc.value.args)
        assert str(project_id) not in error_payload
        assert str(user.tenant_id) not in error_payload
        assert str(user.user_id) not in error_payload

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
        session.execute.assert_not_awaited()
