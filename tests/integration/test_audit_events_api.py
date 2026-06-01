from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select


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


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _count_audit_list_events(session, *, tenant_id, user_id) -> int:
    from qaplatform.infra.database.models import AuditEvent

    result = await session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.user_id == user_id,
            AuditEvent.action == "audit_events.list",
            AuditEvent.resource_type == "audit_event",
        )
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_audit_events_owner_admin_can_list_member_viewer_forbidden(
    seed_run,
    integration_client_as,
    integration_db_session,
):
    tenant = seed_run["tenant"]
    user = seed_run["user"]
    event = await _create_audit_event(
        integration_db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        action="project.create",
        resource_type="project",
        resource_id=seed_run["project"].id,
    )
    query = {
        "action": "project.create",
        "resource_type": "project",
        "resource_id": str(seed_run["project"].id),
        "per_page": 10,
    }

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        owner_resp = await client.get("/api/v1/audit-events", params=query)
    assert owner_resp.status_code == 200, owner_resp.text
    owner_body = owner_resp.json()
    expected_event = {
        "id": str(event.id),
        "tenant_id": str(tenant.id),
        "user_id": str(user.id),
        "action": "project.create",
        "resource_type": "project",
        "resource_id": str(seed_run["project"].id),
        "before_state": None,
        "after_state": {"ok": True},
        "ip_address": None,
        "user_agent": None,
        "created_at": _json_datetime(event.created_at),
    }
    assert owner_body == {
        "data": [expected_event],
        "page": 1,
        "per_page": 10,
        "total": 1,
    }

    async with integration_client_as(user.id, tenant.id, role="admin") as client:
        admin_resp = await client.get("/api/v1/audit-events", params=query)
    assert admin_resp.status_code == 200, admin_resp.text
    admin_body = admin_resp.json()
    assert admin_body == {
        "data": [expected_event],
        "page": 1,
        "per_page": 10,
        "total": 1,
    }

    before_denied_count = await _count_audit_list_events(
        integration_db_session,
        tenant_id=tenant.id,
        user_id=user.id,
    )
    assert before_denied_count == 2

    async with integration_client_as(user.id, tenant.id, role="member") as client:
        member_resp = await client.get("/api/v1/audit-events")
    assert member_resp.status_code == 403, member_resp.text
    assert member_resp.json() == {"detail": "Insufficient permissions"}

    async with integration_client_as(user.id, tenant.id, role="viewer") as client:
        viewer_resp = await client.get("/api/v1/audit-events")
    assert viewer_resp.status_code == 403, viewer_resp.text
    assert viewer_resp.json() == {"detail": "Insufficient permissions"}
    assert (
        await _count_audit_list_events(
            integration_db_session,
            tenant_id=tenant.id,
            user_id=user.id,
        )
        == before_denied_count
    )


@pytest.mark.asyncio
async def test_audit_events_refused_queries_do_not_write_self_audit(
    seed_run,
    seed_second_tenant,
    integration_client_as,
    integration_db_session,
):
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    tenant_b = seed_second_tenant["tenant"]
    user_b = seed_second_tenant["user"]
    project_b = seed_second_tenant["project"]

    await _create_audit_event(
        integration_db_session,
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        action="project.update",
        resource_type="project",
        resource_id=project_b.id,
    )
    before_count = await _count_audit_list_events(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
    )

    async with integration_client_as(user_a.id, tenant_a.id, role="member") as client:
        member_resp = await client.get("/api/v1/audit-events")

    async with integration_client_as(user_a.id, tenant_a.id, role="viewer") as client:
        viewer_resp = await client.get("/api/v1/audit-events")

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        cross_tenant_resp = await client.get(
            "/api/v1/audit-events",
            params={"resource_type": "project", "resource_id": str(project_b.id)},
        )

    assert member_resp.status_code == 403, member_resp.text
    assert viewer_resp.status_code == 403, viewer_resp.text
    assert cross_tenant_resp.status_code == 404, cross_tenant_resp.text
    assert member_resp.json() == {"detail": "Insufficient permissions"}
    assert viewer_resp.json() == {"detail": "Insufficient permissions"}
    assert cross_tenant_resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Audit event not found",
            "details": [],
        }
    }
    assert str(project_b.id) not in cross_tenant_resp.text
    assert str(user_b.id) not in cross_tenant_resp.text
    assert (
        await _count_audit_list_events(
            integration_db_session,
            tenant_id=tenant_a.id,
            user_id=user_a.id,
        )
        == before_count
    )


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
    assert body == {
        "data": [
            {
                "id": str(newer.id),
                "tenant_id": str(tenant.id),
                "user_id": str(user.id),
                "action": "project.update",
                "resource_type": "project",
                "resource_id": str(project.id),
                "before_state": None,
                "after_state": {"ok": True},
                "ip_address": None,
                "user_agent": None,
                "created_at": _json_datetime(newer.created_at),
            },
            {
                "id": str(older.id),
                "tenant_id": str(tenant.id),
                "user_id": str(user.id),
                "action": "project.update",
                "resource_type": "project",
                "resource_id": str(project.id),
                "before_state": None,
                "after_state": {"ok": True},
                "ip_address": None,
                "user_agent": None,
                "created_at": _json_datetime(older.created_at),
            },
        ],
        "page": 1,
        "per_page": 10,
        "total": 2,
    }


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
    cross_tenant_action = f"project.update.{tenant_a.id.hex}"

    event_a = await _create_audit_event(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
        action=cross_tenant_action,
        resource_type="project",
        resource_id=project_a.id,
    )
    event_b = await _create_audit_event(
        integration_db_session,
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        action=cross_tenant_action,
        resource_type="project",
        resource_id=project_b.id,
    )

    before_count = await _count_audit_list_events(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
    )

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        list_resp = await client.get(
            "/api/v1/audit-events",
            params={"action": cross_tenant_action, "per_page": 100},
        )
    after_list_count = await _count_audit_list_events(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
    )

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        actor_resp = await client.get(
            "/api/v1/audit-events",
            params={"actor_id": str(user_b.id)},
        )
    after_actor_count = await _count_audit_list_events(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
    )

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        target_resp = await client.get(
            "/api/v1/audit-events",
            params={"resource_type": "project", "resource_id": str(project_b.id)},
        )
    after_target_count = await _count_audit_list_events(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
    )

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        resource_type_resp = await client.get(
            "/api/v1/audit-events",
            params={"resource_type": "credential", "page": 99, "per_page": 7},
        )
    after_empty_success_count = await _count_audit_list_events(
        integration_db_session,
        tenant_id=tenant_a.id,
        user_id=user_a.id,
    )

    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json() == {
        "data": [
            {
                "id": str(event_a.id),
                "tenant_id": str(tenant_a.id),
                "user_id": str(user_a.id),
                "action": cross_tenant_action,
                "resource_type": "project",
                "resource_id": str(project_a.id),
                "before_state": None,
                "after_state": {"ok": True},
                "ip_address": None,
                "user_agent": None,
                "created_at": _json_datetime(event_a.created_at),
            }
        ],
        "page": 1,
        "per_page": 100,
        "total": 1,
    }
    not_found_body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Audit event not found",
            "details": [],
        }
    }
    assert actor_resp.status_code == 404, actor_resp.text
    assert actor_resp.json() == not_found_body
    assert target_resp.status_code == 404, target_resp.text
    assert target_resp.json() == not_found_body
    leaked_cross_tenant_ids = {
        str(tenant_b.id),
        str(user_b.id),
        str(project_b.id),
        str(event_b.id),
    }
    denied_response_text = f"{actor_resp.text}\n{target_resp.text}"
    leaked_cross_tenant_values = [
        value
        for value in sorted(leaked_cross_tenant_ids)
        if value in denied_response_text
    ]
    assert leaked_cross_tenant_values == []
    assert after_list_count == before_count + 1
    assert after_actor_count == after_list_count
    assert after_target_count == after_actor_count
    assert after_empty_success_count == after_target_count + 1
    assert resource_type_resp.status_code == 200
    assert resource_type_resp.json() == {
        "data": [],
        "page": 99,
        "per_page": 7,
        "total": 0,
    }


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
    assert resp.json() == {
        "data": [],
        "page": 1,
        "per_page": 20,
        "total": 0,
    }

    result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.user_id == user.id,
            AuditEvent.action == "audit_events.list",
            AuditEvent.resource_type == "audit_event",
        )
    )
    (event,) = [
        {
            "resource_id": event.resource_id,
            "before_state": event.before_state,
            "after_state": event.after_state,
        }
        for event in result.scalars().all()
    ]
    assert event == {
        "resource_id": None,
        "before_state": None,
        "after_state": {
            "actor_id": None,
            "action": None,
            "resource_type": None,
            "resource_id": None,
            "start_at": None,
            "end_at": None,
            "page": 1,
            "per_page": 20,
            "total": 0,
        },
    }
    assert "data" not in event["after_state"]
