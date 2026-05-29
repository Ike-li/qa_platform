from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from qaplatform.api.v1.audit_events import list_audit_events


def _repos():
    audit = MagicMock()
    audit.list = AsyncMock()
    audit.has_cross_tenant_match = AsyncMock(return_value=False)
    audit.create = AsyncMock()

    repos = MagicMock()
    repos.audit = audit
    return repos


def _user():
    user = MagicMock()
    user.tenant_id = uuid4()
    user.user_id = uuid4()
    return user


@pytest.mark.asyncio
async def test_list_audit_events_returns_page_and_writes_query_audit():
    repos = _repos()
    user = _user()
    actor_id = uuid4()
    resource_id = uuid4()
    event = SimpleNamespace(
        id=uuid4(),
        tenant_id=user.tenant_id,
        user_id=actor_id,
        action="run.trigger",
        resource_type="run",
        resource_id=resource_id,
        before_state=None,
        after_state={"status": "queued"},
        ip_address=None,
        user_agent="pytest",
        created_at=datetime.now(timezone.utc),
    )
    repos.audit.list.return_value = ([event], 1)

    response = await list_audit_events(
        repos=repos,
        user=user,
        actor_id=actor_id,
        action="run.trigger",
        resource_type="run",
        resource_id=resource_id,
        start_at=None,
        end_at=None,
        page=2,
        per_page=5,
        _perm=None,
    )

    repos.audit.list.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        actor_id=actor_id,
        action="run.trigger",
        resource_type="run",
        resource_id=resource_id,
        start_at=None,
        end_at=None,
        offset=5,
        limit=5,
    )
    assert response.total == 1
    assert response.page == 2
    assert response.per_page == 5
    assert response.data[0].id == event.id
    assert response.data[0].after_state == {"status": "queued"}

    repos.audit.create.assert_awaited_once()
    audit_kwargs = repos.audit.create.await_args.kwargs
    assert audit_kwargs["action"] == "audit_events.list"
    assert audit_kwargs["resource_type"] == "audit_event"
    assert audit_kwargs["after_state"] == {
        "actor_id": str(actor_id),
        "action": "run.trigger",
        "resource_type": "run",
        "resource_id": str(resource_id),
        "start_at": None,
        "end_at": None,
        "page": 2,
        "per_page": 5,
        "total": 1,
    }


@pytest.mark.asyncio
async def test_list_audit_events_cross_tenant_match_returns_404_without_audit():
    repos = _repos()
    user = _user()
    resource_id = uuid4()
    repos.audit.list.return_value = ([], 0)
    repos.audit.has_cross_tenant_match.return_value = True

    with pytest.raises(HTTPException) as exc_info:
        await list_audit_events(
            repos=repos,
            user=user,
            actor_id=None,
            action=None,
            resource_type="run",
            resource_id=resource_id,
            start_at=None,
            end_at=None,
            page=1,
            per_page=20,
            _perm=None,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Audit event not found"
    repos.audit.has_cross_tenant_match.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        actor_id=None,
        resource_type="run",
        resource_id=resource_id,
    )
    repos.audit.create.assert_not_awaited()
