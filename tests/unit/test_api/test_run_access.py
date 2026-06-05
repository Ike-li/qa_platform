from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from qaplatform.api.auth.permissions import Action
from qaplatform.api.run_access import get_run_for_action


@pytest.mark.asyncio
async def test_get_run_for_action_fetches_by_tenant_and_enforces_project_action():
    user = SimpleNamespace(user_id=uuid4(), tenant_id=uuid4())
    run = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        triggered_by=user.user_id,
    )
    repos = MagicMock()
    repos.run.get_for_tenant = AsyncMock(return_value=run)
    session = AsyncMock()
    enforce_action = AsyncMock()

    result = await get_run_for_action(
        repos=repos,
        session=session,
        user=user,
        run_id=run.id,
        action=Action.RUN_CANCEL,
        allow_own_resource=True,
        enforce_action=enforce_action,
    )

    assert result is run
    repos.run.get_for_tenant.assert_awaited_once_with(run.id, user.tenant_id)
    enforce_action.assert_awaited_once_with(
        session,
        user,
        run.project_id,
        Action.RUN_CANCEL,
        is_own_resource=True,
    )


@pytest.mark.asyncio
async def test_get_run_for_action_hides_missing_run_without_authorizing():
    user = SimpleNamespace(user_id=uuid4(), tenant_id=uuid4())
    repos = MagicMock()
    repos.run.get_for_tenant = AsyncMock(return_value=None)
    enforce_action = AsyncMock()
    run_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await get_run_for_action(
            repos=repos,
            session=AsyncMock(),
            user=user,
            run_id=run_id,
            action=Action.RUN_READ,
            enforce_action=enforce_action,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Run not found"
    repos.run.get_for_tenant.assert_awaited_once_with(run_id, user.tenant_id)
    enforce_action.assert_not_awaited()
