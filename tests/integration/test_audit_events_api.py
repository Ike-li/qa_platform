from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select


async def _create_audit_event(
    session,
    *,
    tenant_id,
    user_id,
    action: str,
    resource_type: str,
    resource_id=None,
    created_at: datetime | None = None,
):
    from qaplatform.infra.database.models import AuditEvent

    event = AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_state=None,
        after_state={"ok": True},
        created_at=created_at,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


@pytest.mark.asyncio
async def test_audit_events_owner_admin_can_list_member_viewer_forbidden(
    seed_run,
    integration_client_as,
    integration_db_session,
):
    tenant = seed_run["tenant"]
    user = seed_run["user"]
    await _create_audit_event(
        integration_db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        action="project.create",
        resource_type="project",
        resource_id=seed_run["project"].id,
    )

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        owner_resp = await client.get("/api/v1/audit-events")
    assert owner_resp.status_code == 200

    async with integration_client_as(user.id, tenant.id, role="admin") as client:
        admin_resp = await client.get("/api/v1/audit-events")
    assert admin_resp.status_code == 200

    async with integration_client_as(user.id, tenant.id, role="member") as client:
        member_resp = await client.get("/api/v1/audit-events")
    assert member_resp.status_code == 403

    async with integration_client_as(user.id, tenant.id, role="viewer") as client:
        viewer_resp = await client.get("/api/v1/audit-events")
    assert viewer_resp.status_code == 403


@pytest.mark.asyncio
async def test_audit_events_filters_combine_and_sort_desc(
    seed_run,
    integration_client_as,
    integration_db_session,
):
    tenant = seed_run["tenant"]
    user = seed_run["user"]
    project = seed_run["project"]
    now = datetime.now(timezone.utc)

    older = await _create_audit_event(
        integration_db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        action="project.update",
        resource_type="project",
        resource_id=project.id,
        created_at=now - timedelta(minutes=10),
    )
    newer = await _create_audit_event(
        integration_db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        action="project.update",
        resource_type="project",
        resource_id=project.id,
        created_at=now - timedelta(minutes=5),
    )
    await _create_audit_event(
        integration_db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        action="run.cancel",
        resource_type="run",
        resource_id=seed_run["run"].id,
        created_at=now - timedelta(minutes=1),
    )

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.get(
            "/api/v1/audit-events",
            params={
                "actor_id": str(user.id),
                "action": "project.update",
                "resource_type": "project",
                "resource_id": str(project.id),
                "start_at": (now - timedelta(minutes=15)).isoformat(),
                "end_at": now.isoformat(),
                "page": 1,
                "per_page": 10,
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == 1
    assert body["per_page"] == 10
    assert body["total"] == 2
    assert [item["id"] for item in body["data"]] == [str(newer.id), str(older.id)]
    assert all(item["resource_type"] == "project" for item in body["data"])


@pytest.mark.asyncio
async def test_audit_events_tenant_isolation_and_cross_tenant_ids_return_404(
    seed_run,
    seed_second_tenant,
    integration_client_as,
    integration_db_session,
):
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    tenant_b = seed_second_tenant["tenant"]
    user_b = seed_second_tenant["user"]
    project_a = seed_run["project"]
    project_b = seed_second_tenant["project"]

    event_a = await _create_audit_event(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
        action="project.update",
        resource_type="project",
        resource_id=project_a.id,
    )
    event_b = await _create_audit_event(
        integration_db_session,
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        action="project.update",
        resource_type="project",
        resource_id=project_b.id,
    )

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        list_resp = await client.get(
            "/api/v1/audit-events",
            params={"action": "project.update", "per_page": 100},
        )
        actor_resp = await client.get(
            "/api/v1/audit-events",
            params={"actor_id": str(user_b.id)},
        )
        target_resp = await client.get(
            "/api/v1/audit-events",
            params={"resource_type": "project", "resource_id": str(project_b.id)},
        )
        resource_type_resp = await client.get(
            "/api/v1/audit-events",
            params={"resource_type": "credential"},
        )

    assert list_resp.status_code == 200, list_resp.text
    ids = {item["id"] for item in list_resp.json()["data"]}
    assert str(event_a.id) in ids
    assert str(event_b.id) not in ids
    assert actor_resp.status_code == 404
    assert target_resp.status_code == 404
    assert resource_type_resp.status_code == 200
    assert resource_type_resp.json()["data"] == []


@pytest.mark.asyncio
async def test_audit_events_list_access_writes_audit_event(
    seed_run,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent

    tenant = seed_run["tenant"]
    user = seed_run["user"]

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.get("/api/v1/audit-events")

    assert resp.status_code == 200, resp.text

    result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.user_id == user.id,
            AuditEvent.action == "audit_events.list",
            AuditEvent.resource_type == "audit_event",
        )
    )
    event = result.scalars().first()
    assert event is not None
    assert event.after_state["page"] == 1
    assert event.after_state["per_page"] == 20
    assert "data" not in event.after_state
