"""API write-path integration tests with real database state assertions."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


async def _audit_actions(integration_db_session, *, user_id, resource_id) -> set[str]:
    from qaplatform.infra.database.models import AuditEvent

    return set(
        (
            await integration_db_session.execute(
                select(AuditEvent.action).where(
                    AuditEvent.user_id == user_id,
                    AuditEvent.resource_id == resource_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def _audit_event(integration_db_session, *, action: str, resource_id):
    from qaplatform.infra.database.models import AuditEvent

    return (
        await integration_db_session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.action == action,
                AuditEvent.resource_id == resource_id,
            )
            .order_by(AuditEvent.created_at.desc())
        )
    ).scalars().first()


async def _row_count(integration_db_session, model, *filters) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in filters:
        stmt = stmt.where(clause)
    result = await integration_db_session.execute(stmt)
    return int(result.scalar_one())


def _error_detail(body: dict) -> str | None:
    error = body.get("error")
    return body.get("detail") or (error or {}).get("message")


@pytest.mark.asyncio
async def test_credentials_api_persists_encrypted_value_rotates_and_soft_deletes(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Credential
    from qaplatform.infra.database.repositories.project_repo import CredentialRepository

    project_id = seed_run["project"].id
    name = f"token-{uuid4().hex[:8]}"

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/credentials",
        json={"name": name, "type": "token", "value": "secret-v1"},
    )
    assert create_resp.status_code == 201, create_resp.text
    credential_id = create_resp.json()["id"]
    assert "value" not in create_resp.json()

    credential = await integration_db_session.get(Credential, credential_id)
    assert credential is not None
    assert credential.tenant_id == seed_run["tenant"].id
    assert credential.project_id == project_id
    assert credential.created_by == seed_run["user"].id
    assert b"secret-v1" not in credential.encrypted_value

    crypto = integration_app.state.container.crypto_service
    assert crypto is not None
    assert (
        crypto.decrypt(
            credential.encrypted_value,
            context_id=f"credential:{project_id}:{name}",
        )
        == "secret-v1"
    )

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/credentials/{credential_id}",
        json={"value": "secret-v2"},
    )
    assert update_resp.status_code == 200, update_resp.text
    await integration_db_session.refresh(credential)
    assert (
        crypto.decrypt(
            credential.encrypted_value,
            context_id=f"credential:{project_id}:{name}",
        )
        == "secret-v2"
    )

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/credentials/{credential_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    await integration_db_session.refresh(credential)
    assert credential.deleted_at is not None

    repo = CredentialRepository(integration_db_session)
    assert (
        await repo.get_by_project_tenant(
            credential.id,
            project_id,
            seed_run["tenant"].id,
        )
        is None
    )
    assert {"credential.create", "credential.rotate", "credential.delete"}.issubset(
        await _audit_actions(
            integration_db_session,
            user_id=seed_run["user"].id,
            resource_id=credential.id,
        )
    )
    create_audit = await _audit_event(
        integration_db_session,
        action="credential.create",
        resource_id=credential.id,
    )
    rotate_audit = await _audit_event(
        integration_db_session,
        action="credential.rotate",
        resource_id=credential.id,
    )
    delete_audit = await _audit_event(
        integration_db_session,
        action="credential.delete",
        resource_id=credential.id,
    )
    assert create_audit is not None
    assert rotate_audit is not None
    assert delete_audit is not None
    serialized_audit = repr(
        [
            create_audit.before_state,
            create_audit.after_state,
            rotate_audit.before_state,
            rotate_audit.after_state,
            delete_audit.before_state,
            delete_audit.after_state,
        ]
    )
    assert "secret-v1" not in serialized_audit
    assert "secret-v2" not in serialized_audit
    assert "encrypted_value" not in serialized_audit
    assert create_audit.after_state["name"] == name
    assert rotate_audit.after_state["name"] == name
    assert delete_audit.before_state["name"] == name


@pytest.mark.asyncio
async def test_environment_api_persists_encrypted_env_vars_limits_and_soft_delete(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Environment
    from qaplatform.infra.database.repositories.project_repo import (
        EnvironmentRepository,
    )

    project_id = seed_run["project"].id
    name = f"env-{uuid4().hex[:8]}"

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/environments",
        json={
            "name": name,
            "base_image": "python:3.12-alpine",
            "memory_mb": 384,
            "cpu_cores": 0.75,
            "max_artifact_size_mb": 42,
            "max_artifacts_count": 9,
            "network_policy": "restricted",
            "env_vars": {"API_TOKEN": "secret-token"},
            "cache_key": "deps-v1",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    env_id = body["id"]
    assert body["env_vars"] == {"API_TOKEN": "secret-token"}

    env = await integration_db_session.get(Environment, env_id)
    assert env is not None
    assert env.project_id == project_id
    assert env.resource_limits == {
        "max_artifact_size_mb": 42,
        "max_artifacts_count": 9,
    }
    assert env.env_vars != {"API_TOKEN": "secret-token"}
    assert "secret-token" not in str(env.env_vars)

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/environments/{env_id}",
        json={
            "memory_mb": 512,
            "max_artifact_size_mb": 64,
            "env_vars": {"API_TOKEN": "rotated-token"},
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["env_vars"] == {"API_TOKEN": "rotated-token"}

    await integration_db_session.refresh(env)
    assert env.memory_mb == 512
    assert env.resource_limits["max_artifact_size_mb"] == 64
    assert "rotated-token" not in str(env.env_vars)

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/environments/{env_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    await integration_db_session.refresh(env)
    assert env.deleted_at is not None

    repo = EnvironmentRepository(integration_db_session)
    assert await repo.get_by_name(project_id, name) is None
    assert {
        "environment.create",
        "environment.update",
        "environment.delete",
    }.issubset(
        await _audit_actions(
            integration_db_session,
            user_id=seed_run["user"].id,
            resource_id=env.id,
        )
    )
    create_audit = await _audit_event(
        integration_db_session,
        action="environment.create",
        resource_id=env.id,
    )
    update_audit = await _audit_event(
        integration_db_session,
        action="environment.update",
        resource_id=env.id,
    )
    delete_audit = await _audit_event(
        integration_db_session,
        action="environment.delete",
        resource_id=env.id,
    )
    assert create_audit is not None
    assert update_audit is not None
    assert delete_audit is not None
    serialized_audit = repr(
        [
            create_audit.before_state,
            create_audit.after_state,
            update_audit.before_state,
            update_audit.after_state,
            delete_audit.before_state,
            delete_audit.after_state,
        ]
    )
    assert "secret-token" not in serialized_audit
    assert "rotated-token" not in serialized_audit
    assert create_audit.after_state["env_vars"] == {"redacted": True, "count": 1}
    assert update_audit.before_state["env_vars"] == {"redacted": True, "count": 1}
    assert update_audit.after_state["env_vars"] == {"redacted": True, "count": 1}
    assert delete_audit.before_state["env_vars"] == {"redacted": True, "count": 1}


@pytest.mark.asyncio
async def test_notification_rule_api_persists_updates_and_hides_soft_deleted_rule(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import NotificationRule
    from qaplatform.infra.database.repositories.project_repo import (
        NotificationRuleRepository,
    )

    project_id = seed_run["project"].id
    name = f"notify-{uuid4().hex[:8]}"
    webhook_url = f"https://hooks.example.com/{uuid4().hex}/secret-webhook-token"
    email_address = f"qa-{uuid4().hex[:8]}@example.com"

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/notification-rules",
        json={
            "name": name,
            "enabled": True,
            "conditions": [{"field": "status", "operator": "eq", "value": "failed"}],
            "channels": [{"type": "email", "address": email_address}],
            "template": "Run {{run_id}} failed secret-template-marker",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    rule_id = create_resp.json()["id"]

    rule = await integration_db_session.get(NotificationRule, rule_id)
    assert rule is not None
    assert rule.project_id == project_id
    assert rule.conditions[0]["value"] == "failed"
    assert rule.channels[0]["address"] == email_address

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
        json={
            "enabled": False,
            "channels": [{"type": "webhook", "webhook_url": webhook_url}],
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    await integration_db_session.refresh(rule)
    assert rule.enabled is False
    assert rule.channels[0]["type"] == "webhook"

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    await integration_db_session.refresh(rule)
    assert rule.deleted_at is not None

    repo = NotificationRuleRepository(integration_db_session)
    visible, total = await repo.list_by_project(project_id, limit=100)
    assert rule.id not in {item.id for item in visible}
    assert total == 0
    assert {
        "notification_rule.create",
        "notification_rule.update",
        "notification_rule.delete",
    }.issubset(
        await _audit_actions(
            integration_db_session,
            user_id=seed_run["user"].id,
            resource_id=rule.id,
        )
    )
    create_audit = await _audit_event(
        integration_db_session,
        action="notification_rule.create",
        resource_id=rule.id,
    )
    update_audit = await _audit_event(
        integration_db_session,
        action="notification_rule.update",
        resource_id=rule.id,
    )
    delete_audit = await _audit_event(
        integration_db_session,
        action="notification_rule.delete",
        resource_id=rule.id,
    )
    assert create_audit is not None
    assert update_audit is not None
    assert delete_audit is not None
    serialized_audit = repr(
        [
            create_audit.before_state,
            create_audit.after_state,
            update_audit.before_state,
            update_audit.after_state,
            delete_audit.before_state,
            delete_audit.after_state,
        ]
    )
    assert webhook_url not in serialized_audit
    assert email_address not in serialized_audit
    assert "secret-template-marker" not in serialized_audit
    assert create_audit.after_state["channels"] == {
        "redacted": True,
        "count": 1,
        "types": ["email"],
    }
    assert update_audit.after_state["channels"] == {
        "redacted": True,
        "count": 1,
        "types": ["webhook"],
    }
    assert delete_audit.before_state["channels"] == {
        "redacted": True,
        "count": 1,
        "types": ["webhook"],
    }
    assert delete_audit.before_state["template"]["redacted"] is True


@pytest.mark.asyncio
async def test_schedule_and_run_apis_persist_next_run_metadata_and_audit_rows(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run, Schedule

    project_id = seed_run["project"].id
    pipeline_id = seed_run["pipeline"].id

    schedule_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/schedules",
        json={
            "pipeline_id": str(pipeline_id),
            "cron_expr": "*/15 * * * *",
            "timezone": "Asia/Shanghai",
            "missed_fire_policy": "run_once",
            "quiet_windows": [{"start": "00:00", "end": "01:00"}],
            "enabled": True,
        },
    )
    assert schedule_resp.status_code == 201, schedule_resp.text
    schedule_id = schedule_resp.json()["id"]

    schedule = await integration_db_session.get(Schedule, schedule_id)
    assert schedule is not None
    assert schedule.project_id == project_id
    assert schedule.pipeline_id == pipeline_id
    assert schedule.next_run_at is not None
    assert schedule.missed_fire_policy == "run_once"

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/schedules/{schedule_id}",
        json={"enabled": False, "cron_expr": "*/30 * * * *"},
    )
    assert update_resp.status_code == 200, update_resp.text
    await integration_db_session.refresh(schedule)
    assert schedule.enabled is False
    assert schedule.cron_expr == "*/30 * * * *"

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/schedules/{schedule_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    await integration_db_session.refresh(schedule)
    assert schedule.deleted_at is not None

    run_resp = await integration_client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id), "git_ref": "feature/p0", "priority": 0},
    )
    assert run_resp.status_code == 201, run_resp.text
    run_id = run_resp.json()["id"]

    run = await integration_db_session.get(Run, run_id)
    assert run is not None
    assert run.tenant_id == seed_run["tenant"].id
    assert run.project_id == project_id
    assert run.pipeline_id == pipeline_id
    assert run.environment_id == seed_run["environment"].id
    assert run.git_ref == "feature/p0"
    assert run.priority == 0
    assert run.retry_group_id == run.id
    assert run.metadata_["git_url"] == seed_run["project"].git_url
    assert run.metadata_["default_branch"] == seed_run["project"].default_branch

    assert {"schedule.create", "schedule.update", "schedule.delete"}.issubset(
        await _audit_actions(
            integration_db_session,
            user_id=seed_run["user"].id,
            resource_id=schedule.id,
        )
    )
    delete_audit = await _audit_event(
        integration_db_session,
        action="schedule.delete",
        resource_id=schedule.id,
    )
    assert delete_audit is not None
    assert delete_audit.before_state["cron_expr"] == "*/30 * * * *"
    assert delete_audit.before_state["enabled"] is False
    assert delete_audit.after_state is None
    assert "run.trigger" in await _audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=run.id,
    )


@pytest.mark.asyncio
async def test_batch_run_apis_persist_state_and_audit_rows(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run, RunStatusEnum

    run = seed_run["run"]
    run.status = RunStatusEnum.RUNNING
    await integration_db_session.commit()

    cancel_resp = await integration_client.post(
        "/api/v1/runs/batch/cancel",
        json={"run_ids": [str(run.id)]},
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    assert cancel_resp.json() == {"processed": 1, "failed": 0, "errors": []}
    await integration_db_session.refresh(run)
    assert run.status == RunStatusEnum.CANCELLED

    integration_app.state.container.arq_pool = None
    retry_resp = await integration_client.post(
        "/api/v1/runs/batch/retry",
        json={"run_ids": [str(run.id)]},
    )
    assert retry_resp.status_code == 200, retry_resp.text
    assert retry_resp.json() == {"processed": 1, "failed": 0, "errors": []}

    retry_run = (
        await integration_db_session.execute(
            select(Run).where(Run.source_run_id == run.id)
        )
    ).scalar_one()
    assert retry_run.status == RunStatusEnum.QUEUED
    assert retry_run.tenant_id == seed_run["tenant"].id
    assert retry_run.project_id == seed_run["project"].id
    assert retry_run.pipeline_id == seed_run["pipeline"].id
    assert retry_run.environment_id == seed_run["environment"].id
    assert retry_run.chain_depth == 1

    actions = await _audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=run.id,
    )
    assert {"run.batch_cancel", "run.batch_retry"}.issubset(actions)


@pytest.mark.asyncio
async def test_schedule_api_rejects_cross_project_pipeline_without_persisting(
    integration_client_as,
    integration_db_session,
    seed_run,
    seed_second_tenant,
):
    from qaplatform.infra.database.models import Schedule

    user = seed_run["user"]
    tenant = seed_run["tenant"]
    project_id = seed_run["project"].id
    before = await _row_count(
        integration_db_session,
        Schedule,
        Schedule.project_id == project_id,
    )

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/schedules",
            json={
                "pipeline_id": str(seed_second_tenant["pipeline"].id),
                "cron_expr": "*/10 * * * *",
                "timezone": "UTC",
                "missed_fire_policy": "skip",
                "quiet_windows": [],
                "enabled": True,
            },
        )

    assert resp.status_code == 404, resp.text
    assert _error_detail(resp.json()) == "Pipeline not found"
    assert (
        await _row_count(
            integration_db_session,
            Schedule,
            Schedule.project_id == project_id,
        )
        == before
    )


@pytest.mark.asyncio
async def test_manual_run_archived_project_returns_409_without_persisting(
    integration_client_as,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run

    user = seed_run["user"]
    tenant = seed_run["tenant"]
    project = seed_run["project"]
    project.status = "archived"
    await integration_db_session.commit()
    await integration_db_session.refresh(project)
    before = await _row_count(
        integration_db_session,
        Run,
        Run.project_id == project.id,
        Run.trigger_type == "manual",
    )

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={
                "pipeline_id": str(seed_run["pipeline"].id),
                "git_ref": "main",
            },
        )

    assert resp.status_code == 409, resp.text
    assert "archived" in resp.json()["detail"].lower()
    assert (
        await _row_count(
            integration_db_session,
            Run,
            Run.project_id == project.id,
            Run.trigger_type == "manual",
        )
        == before
    )
