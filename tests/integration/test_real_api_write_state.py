"""API write-path integration tests with real database state assertions."""

from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


async def _audit_actions(integration_db_session, *, user_id, resource_id) -> list[str]:
    from qaplatform.infra.database.models import AuditEvent

    result = await integration_db_session.execute(
        select(AuditEvent.action).where(
            AuditEvent.user_id == user_id,
            AuditEvent.resource_id == resource_id,
        )
    )
    return sorted(result.scalars().all())


async def _assert_audit_actions(
    integration_db_session,
    *,
    user_id,
    resource_id,
    expected: set[str],
) -> None:
    assert await _audit_actions(
        integration_db_session,
        user_id=user_id,
        resource_id=resource_id,
    ) == sorted(expected)


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


def _assert_not_found_response(body: dict, message: str) -> None:
    assert body == {
        "error": {
            "code": "NOT_FOUND",
            "message": message,
            "details": [],
        }
    }


def _decode_redis_mapping(mapping: dict) -> dict[str, str]:
    return {
        key.decode() if isinstance(key, bytes) else key: (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in mapping.items()
    }


def _json_datetime(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _json_datetime_or_none(value) -> str | None:
    return _json_datetime(value) if value is not None else None


def _expected_run_response(run, *, pipeline_name: str) -> dict:
    status = run.status.value if hasattr(run.status, "value") else run.status
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "project_id": str(run.project_id),
        "pipeline_id": str(run.pipeline_id),
        "pipeline_name": pipeline_name,
        "environment_id": str(run.environment_id),
        "status": status,
        "trigger_type": run.trigger_type,
        "priority": run.priority,
        "triggered_by": str(run.triggered_by) if run.triggered_by is not None else None,
        "git_ref": run.git_ref,
        "git_sha": run.git_sha,
        "attempt": run.attempt,
        "started_at": _json_datetime_or_none(run.started_at),
        "finished_at": _json_datetime_or_none(run.finished_at),
        "duration_ms": run.duration_ms,
        "summary": run.summary,
        "error_message": run.error_message,
        "created_at": _json_datetime(run.created_at),
        "updated_at": _json_datetime(run.updated_at),
    }


def _assert_run_cancel_redis_event(
    decoded_event: dict,
    decoded_status: dict,
    run_id,
) -> None:
    datetime.fromisoformat(decoded_event["timestamp"].replace("Z", "+00:00"))
    assert decoded_event == {
        "run_id": str(run_id),
        "status": "cancelled",
        "timestamp": decoded_event["timestamp"],
        "previous": "running",
    }
    assert decoded_status == {
        "status": "cancelled",
        "timestamp": decoded_event["timestamp"],
    }


def _assert_credential_payload_does_not_leak(payload, *secrets: str) -> None:
    def _walk(node) -> None:
        if isinstance(node, dict):
            assert not ({"value", "encrypted_value"} & set(node))
            for nested in node.values():
                _walk(nested)
            return
        if isinstance(node, list):
            for nested in node:
                _walk(nested)
            return
        if isinstance(node, str):
            for secret in secrets:
                assert secret not in node

    _walk(payload)


def _expected_environment_audit_state(body: dict) -> dict:
    return {
        **body,
        "env_vars": {"redacted": True, "count": len(body["env_vars"])},
    }


def _expected_notification_rule_audit_state(body: dict) -> dict:
    return {
        "id": body["id"],
        "project_id": body["project_id"],
        "name": body["name"],
        "enabled": body["enabled"],
        "conditions": body["conditions"],
        "channels": {
            "redacted": True,
            "count": len(body["channels"]),
            "types": [channel["type"] for channel in body["channels"]],
        },
        "template": {
            "redacted": True,
            "present": body["template"] is not None,
            "length": len(body["template"] or ""),
        },
        "created_at": body["created_at"],
    }


class _RecordingArq:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})

        class _Job:
            def __init__(self, job_id: str) -> None:
                self.job_id = job_id

        return _Job(kwargs["_job_id"])


@pytest.mark.asyncio
async def test_project_api_audits_lifecycle_without_git_url_userinfo_leak(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Project

    slug = f"audit-project-{uuid4().hex[:8]}"
    create_secret = f"create-token-{uuid4().hex}"
    update_secret = f"update-token-{uuid4().hex}"
    create_git_url = (
        f"https://x-access-token:{create_secret}@example.com/org/repo.git"
    )
    update_git_url = f"https://oauth2:{update_secret}@git.example.com/new/repo.git"

    create_resp = await integration_client.post(
        "/api/v1/projects",
        json={
            "name": f"Audit Project {slug}",
            "slug": slug,
            "description": "initial",
            "git_url": create_git_url,
            "default_branch": "main",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    create_body = create_resp.json()
    project_id = create_body["id"]
    assert create_body == {
        "id": project_id,
        "tenant_id": str(seed_run["tenant"].id),
        "name": f"Audit Project {slug}",
        "slug": slug,
        "description": "initial",
        "git_url": create_git_url,
        "git_auth_method": "none",
        "credential_id": None,
        "default_branch": "main",
        "root_path": ".",
        "shallow_clone": True,
        "default_env_id": None,
        "settings": {},
        "silent_windows": [],
        "status": "active",
        "created_by": str(seed_run["user"].id),
        "created_at": create_body["created_at"],
        "updated_at": create_body["updated_at"],
    }

    project = await integration_db_session.get(Project, project_id)
    assert project is not None
    assert project.tenant_id == seed_run["tenant"].id
    assert project.created_by == seed_run["user"].id

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}",
        json={
            "description": "archived for audit evidence",
            "git_url": update_git_url,
            "status": "archived",
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    update_body = update_resp.json()
    assert update_body == {
        **create_body,
        "description": "archived for audit evidence",
        "git_url": update_git_url,
        "status": "archived",
        "updated_at": update_body["updated_at"],
    }
    await integration_db_session.refresh(project)
    assert project.status == "archived"
    assert project.git_url == update_git_url

    delete_resp = await integration_client.delete(f"/api/v1/projects/{project_id}")
    assert delete_resp.status_code == 204, delete_resp.text
    assert delete_resp.content == b""
    await integration_db_session.refresh(project)
    assert project.deleted_at is not None

    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=project.id,
        expected={"project.create", "project.update", "project.delete"},
    )
    create_audit = await _audit_event(
        integration_db_session,
        action="project.create",
        resource_id=project.id,
    )
    update_audit = await _audit_event(
        integration_db_session,
        action="project.update",
        resource_id=project.id,
    )
    delete_audit = await _audit_event(
        integration_db_session,
        action="project.delete",
        resource_id=project.id,
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
    assert create_secret not in serialized_audit
    assert update_secret not in serialized_audit
    assert "x-access-token" not in serialized_audit
    assert "oauth2" not in serialized_audit
    for event in [create_audit, update_audit, delete_audit]:
        assert event.tenant_id == seed_run["tenant"].id
        assert event.user_id == seed_run["user"].id
        assert event.resource_type == "project"
        assert event.resource_id == project.id

    expected_create_audit_after = {
        **create_body,
        "git_url": "https://***@example.com/org/repo.git",
    }
    expected_update_audit_after = {
        **update_body,
        "git_url": "https://***@git.example.com/new/repo.git",
    }
    assert create_audit.before_state is None
    assert create_audit.after_state == expected_create_audit_after
    assert update_audit.before_state == expected_create_audit_after
    assert update_audit.after_state == expected_update_audit_after
    assert delete_audit.before_state == expected_update_audit_after
    assert delete_audit.after_state is None


@pytest.mark.asyncio
async def test_pipeline_api_persists_audit_states_for_lifecycle(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Pipeline

    project_id = seed_run["project"].id
    name = f"audit-pipeline-{uuid4().hex[:8]}"
    create_secret = f"create-pipeline-secret-{uuid4().hex}"
    update_secret = f"update-pipeline-secret-{uuid4().hex}"

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/pipelines",
        json={
            "name": name,
            "stages": [
                {
                    "name": "unit",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {
                        "command": (
                            "pytest tests/unit -q --index-url "
                            f"https://user:{create_secret}@packages.example/simple"
                        ),
                        "env": {"API_TOKEN": create_secret, "REGION": "ap-east-1"},
                        "headers": {"Authorization": f"Bearer {create_secret}"},
                    },
                }
            ],
            "selector": {"include_paths": ["tests/unit"], "on_empty": "warn"},
            "trigger_config": {
                "type": "manual",
                "source": {
                    "webhook_secret": create_secret,
                    "credential_id": f"credential-{create_secret}",
                    "clone_url": f"https://x-access-token:{create_secret}@git.example/repo.git",
                },
            },
            "retry_policy": {"max_attempts": 2, "retry_on": ["infra"]},
            "timeout_seconds": 900,
            "enabled": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    create_body = create_resp.json()
    pipeline_id = create_body["id"]

    pipeline = await integration_db_session.get(Pipeline, pipeline_id)
    assert pipeline is not None
    assert pipeline.project_id == project_id
    assert pipeline.stages[0]["config"]["env"]["API_TOKEN"] == create_secret

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
        json={
            "name": f"{name}-disabled",
            "stages": [
                {
                    "name": "integration",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {
                        "command": (
                            "pytest tests/integration -q --repo "
                            f"https://user:{update_secret}@git.example/org/repo.git"
                        ),
                        "env": {"PASSWORD": update_secret, "REGION": "ap-east-1"},
                        "tokens": [update_secret],
                    },
                }
            ],
            "selector": {"exclude_paths": ["tests/e2e"]},
            "trigger_config": {
                "type": "schedule",
                "conditions": {"secret_header": update_secret},
                "target": {
                    "url": f"https://deploy:{update_secret}@deploy.example/hook",
                    "access_token": update_secret,
                },
            },
            "retry_policy": {"max_attempts": 3, "retry_on": ["infra", "timeout"]},
            "enabled": False,
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    update_body = update_resp.json()
    await integration_db_session.refresh(pipeline)
    assert pipeline.enabled is False
    assert pipeline.retry_policy["max_attempts"] == 3
    assert pipeline.stages[0]["config"]["env"]["PASSWORD"] == update_secret
    assert pipeline.trigger_config["target"]["access_token"] == update_secret

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    assert delete_resp.content == b""
    await integration_db_session.refresh(pipeline)
    assert pipeline.deleted_at is not None

    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=pipeline.id,
        expected={"pipeline.create", "pipeline.update", "pipeline.delete"},
    )
    create_audit = await _audit_event(
        integration_db_session,
        action="pipeline.create",
        resource_id=pipeline.id,
    )
    update_audit = await _audit_event(
        integration_db_session,
        action="pipeline.update",
        resource_id=pipeline.id,
    )
    delete_audit = await _audit_event(
        integration_db_session,
        action="pipeline.delete",
        resource_id=pipeline.id,
    )
    assert create_audit is not None
    assert update_audit is not None
    assert delete_audit is not None
    for event in [create_audit, update_audit, delete_audit]:
        assert event.tenant_id == seed_run["tenant"].id
        assert event.user_id == seed_run["user"].id
        assert event.resource_type == "pipeline"
        assert event.resource_id == pipeline.id

    expected_create_audit_after = {
        **create_body,
        "stages": [
            {
                **create_body["stages"][0],
                "config": {
                    "command": (
                        "pytest tests/unit -q --index-url "
                        "https://***@packages.example/simple"
                    ),
                    "env": {
                        "API_TOKEN": {"redacted": True},
                        "REGION": "ap-east-1",
                    },
                    "headers": {"Authorization": {"redacted": True}},
                },
            }
        ],
        "trigger_config": {
            **create_body["trigger_config"],
            "source": {
                "webhook_secret": {"redacted": True},
                "credential_id": {"redacted": True},
                "clone_url": "https://***@git.example/repo.git",
            },
        },
    }
    expected_update_audit_after = {
        **update_body,
        "stages": [
            {
                **update_body["stages"][0],
                "config": {
                    "command": (
                        "pytest tests/integration -q --repo "
                        "https://***@git.example/org/repo.git"
                    ),
                    "env": {
                        "PASSWORD": {"redacted": True},
                        "REGION": "ap-east-1",
                    },
                    "tokens": {"redacted": True},
                },
            }
        ],
        "trigger_config": {
            **update_body["trigger_config"],
            "conditions": {"secret_header": {"redacted": True}},
            "target": {
                "url": "https://***@deploy.example/hook",
                "access_token": {"redacted": True},
            },
        },
    }
    assert create_audit.before_state is None
    assert create_audit.after_state == expected_create_audit_after
    assert update_audit.before_state == expected_create_audit_after
    assert update_audit.after_state == expected_update_audit_after
    assert delete_audit.before_state == expected_update_audit_after
    assert delete_audit.after_state is None
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
    assert create_secret not in serialized_audit
    assert update_secret not in serialized_audit
    assert "x-access-token" not in serialized_audit


@pytest.mark.asyncio
async def test_project_member_api_persists_audit_states_for_role_changes(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import AppUser, ProjectMember
    from qaplatform.infra.database.repositories.project_repo import (
        ProjectMemberRepository,
    )

    tenant_id = seed_run["tenant"].id
    project_id = seed_run["project"].id
    suffix = uuid4().hex[:8]
    member_user = AppUser(
        tenant_id=tenant_id,
        username=f"member-{suffix}",
        email=f"member-{suffix}@test.local",
        password_hash="argon2:placeholder",
        role="member",
        is_platform_admin=False,
        is_active=True,
    )
    integration_db_session.add(member_user)
    await integration_db_session.commit()
    await integration_db_session.refresh(member_user)

    add_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": str(member_user.id), "role": "developer"},
    )
    assert add_resp.status_code == 201, add_resp.text
    add_body = add_resp.json()

    member = await integration_db_session.get(
        ProjectMember,
        {"project_id": project_id, "user_id": member_user.id},
    )
    assert member is not None
    assert member.tenant_id == tenant_id
    assert member.role == "developer"
    assert add_body == {
        "project_id": str(project_id),
        "user_id": str(member_user.id),
        "username": member_user.username,
        "email": member_user.email,
        "role": "developer",
        "created_at": _json_datetime(member.created_at),
    }

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/members/{member_user.id}",
        json={"role": "viewer"},
    )
    assert update_resp.status_code == 200, update_resp.text
    update_body = update_resp.json()
    await integration_db_session.refresh(member)
    assert member.role == "viewer"
    assert update_body == {**add_body, "role": "viewer"}

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/members/{member_user.id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    assert delete_resp.content == b""
    await integration_db_session.refresh(member)
    assert member.deleted_at is not None

    repo = ProjectMemberRepository(integration_db_session)
    assert await repo.get_by_project_user(project_id, member_user.id, tenant_id) is None

    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=project_id,
        expected={
            "project_member.add",
            "project_member.update",
            "project_member.remove",
        },
    )
    add_audit = await _audit_event(
        integration_db_session,
        action="project_member.add",
        resource_id=project_id,
    )
    update_audit = await _audit_event(
        integration_db_session,
        action="project_member.update",
        resource_id=project_id,
    )
    remove_audit = await _audit_event(
        integration_db_session,
        action="project_member.remove",
        resource_id=project_id,
    )
    assert add_audit is not None
    assert update_audit is not None
    assert remove_audit is not None
    for event in [add_audit, update_audit, remove_audit]:
        assert event.tenant_id == tenant_id
        assert event.user_id == seed_run["user"].id
        assert event.resource_type == "project_member"
        assert event.resource_id == project_id

    assert add_audit.before_state is None
    assert add_audit.after_state == add_body
    assert update_audit.before_state == {
        "user_id": str(member_user.id),
        "role": "developer",
    }
    assert update_audit.after_state == update_body
    assert remove_audit.before_state == {
        "user_id": str(member_user.id),
        "role": "viewer",
    }
    assert remove_audit.after_state is None


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
    create_body = create_resp.json()
    credential_id = UUID(create_body["id"])

    credential = await integration_db_session.get(Credential, credential_id)
    assert credential is not None
    assert create_body == {
        "id": str(credential.id),
        "project_id": str(project_id),
        "name": name,
        "type": "token",
        "created_by": str(seed_run["user"].id),
        "created_at": _json_datetime(credential.created_at),
    }
    _assert_credential_payload_does_not_leak(create_body, "secret-v1", "secret-v2")
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
    update_body = update_resp.json()
    await integration_db_session.refresh(credential)
    assert update_body == {
        "id": str(credential.id),
        "project_id": str(project_id),
        "name": name,
        "type": "token",
        "created_by": str(seed_run["user"].id),
        "created_at": _json_datetime(credential.created_at),
    }
    _assert_credential_payload_does_not_leak(update_body, "secret-v1", "secret-v2")
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
    assert delete_resp.content == b""
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
    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=credential.id,
        expected={
            "credential.create",
            "credential.rotate",
            "credential.delete",
        },
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
    audit_payloads = [
        create_audit.before_state,
        create_audit.after_state,
        rotate_audit.before_state,
        rotate_audit.after_state,
        delete_audit.before_state,
        delete_audit.after_state,
    ]
    _assert_credential_payload_does_not_leak(
        audit_payloads,
        "secret-v1",
        "secret-v2",
        repr(credential.encrypted_value),
    )
    assert create_audit.before_state is None
    assert create_audit.after_state == create_body
    assert rotate_audit.before_state is None
    assert rotate_audit.after_state == update_body
    assert delete_audit.before_state == update_body
    assert delete_audit.after_state is None


@pytest.mark.asyncio
async def test_project_git_token_binding_reaches_trigger_metadata_without_secret(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import AuditEvent, Run

    project = seed_run["project"]
    project_id = project.id
    token = f"git-token-{uuid4().hex}"
    cred_name = f"git-token-{uuid4().hex[:8]}"

    create_cred = await integration_client.post(
        f"/api/v1/projects/{project_id}/credentials",
        json={"name": cred_name, "type": "token", "value": token},
    )
    assert create_cred.status_code == 201, create_cred.text
    credential_id = create_cred.json()["id"]

    update_project = await integration_client.put(
        f"/api/v1/projects/{project_id}",
        json={
            "git_url": "https://github.com/example/private.git",
            "git_auth_method": "token",
            "credential_id": credential_id,
        },
    )
    assert update_project.status_code == 200, update_project.text

    trigger = await integration_client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(seed_run["pipeline"].id)},
    )
    assert trigger.status_code == 201, trigger.text
    run_id = trigger.json()["id"]

    run = await integration_db_session.get(Run, run_id)
    assert run is not None
    assert run.metadata_["git_url"] == "https://github.com/example/private.git"
    assert run.metadata_["git_auth_method"] == "token"
    assert run.metadata_["credential_id"] == credential_id
    assert token not in repr(run.metadata_)

    audit_rows = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.resource_id.in_([project_id, run.id])
                )
            )
        )
        .scalars()
        .all()
    )
    serialized_audit = repr(
        [row.before_state for row in audit_rows]
        + [row.after_state for row in audit_rows]
    )
    assert token not in serialized_audit


@pytest.mark.asyncio
async def test_project_member_and_credential_lists_are_paginated(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import AppUser

    tenant_id = seed_run["tenant"].id
    project_id = seed_run["project"].id
    suffix = uuid4().hex[:8]

    credential_names = [f"page-token-{suffix}-{idx}" for idx in range(3)]
    created_credentials = []
    for name in credential_names:
        create_resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/credentials",
            json={"name": name, "type": "token", "value": f"secret-{name}"},
        )
        assert create_resp.status_code == 201, create_resp.text
        created_credentials.append(create_resp.json())

    credentials_page = await integration_client.get(
        f"/api/v1/projects/{project_id}/credentials",
        params={"page": 2, "per_page": 2},
    )
    assert credentials_page.status_code == 200, credentials_page.text
    credentials_body = credentials_page.json()
    assert credentials_body == {
        "data": [created_credentials[0]],
        "page": 2,
        "per_page": 2,
        "total": 3,
    }

    credentials_empty_page = await integration_client.get(
        f"/api/v1/projects/{project_id}/credentials",
        params={"page": 99, "per_page": 2},
    )
    assert credentials_empty_page.status_code == 200, credentials_empty_page.text
    credentials_empty_body = credentials_empty_page.json()
    assert credentials_empty_body == {
        "data": [],
        "page": 99,
        "per_page": 2,
        "total": 3,
    }

    member_users = []
    for idx in range(3):
        member_user = AppUser(
            tenant_id=tenant_id,
            username=f"page-member-{suffix}-{idx}",
            email=f"page-member-{suffix}-{idx}@test.local",
            password_hash="argon2:placeholder",
            role="member",
            is_platform_admin=False,
            is_active=True,
        )
        integration_db_session.add(member_user)
        member_users.append(member_user)
    await integration_db_session.commit()
    created_members = []
    for member_user in member_users:
        await integration_db_session.refresh(member_user)
        add_resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/members",
            json={"user_id": str(member_user.id), "role": "developer"},
        )
        assert add_resp.status_code == 201, add_resp.text
        created_members.append(add_resp.json())

    members_page = await integration_client.get(
        f"/api/v1/projects/{project_id}/members",
        params={"page": 2, "per_page": 2},
    )
    assert members_page.status_code == 200, members_page.text
    members_body = members_page.json()
    assert members_body == {
        "data": [created_members[0]],
        "page": 2,
        "per_page": 2,
        "total": 3,
    }

    members_empty_page = await integration_client.get(
        f"/api/v1/projects/{project_id}/members",
        params={"page": 99, "per_page": 2},
    )
    assert members_empty_page.status_code == 200, members_empty_page.text
    members_empty_body = members_empty_page.json()
    assert members_empty_body == {
        "data": [],
        "page": 99,
        "per_page": 2,
        "total": 3,
    }


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
            "disk_mb": 2048,
            "max_artifact_size_mb": 42,
            "max_artifacts_count": 9,
            "network_policy": "restricted",
            "env_vars": {"API_TOKEN": "secret-token"},
            "cache_key": "deps-v1",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    create_body = create_resp.json()
    env_id = create_body["id"]
    assert create_body == {
        "id": env_id,
        "project_id": str(project_id),
        "name": name,
        "base_image": "python:3.12-alpine",
        "setup_script": None,
        "memory_mb": 384,
        "cpu_cores": 0.75,
        "disk_mb": 2048,
        "max_artifact_size_mb": 42,
        "max_artifacts_count": 9,
        "network_policy": "restricted",
        "env_vars": {"API_TOKEN": "secret-token"},
        "cache_key": "deps-v1",
        "created_at": create_body["created_at"],
    }

    env = await integration_db_session.get(Environment, env_id)
    assert env is not None
    assert env.project_id == project_id
    assert env.resource_limits == {
        "disk_mb": 2048,
        "max_artifact_size_mb": 42,
        "max_artifacts_count": 9,
    }
    assert env.env_vars != {"API_TOKEN": "secret-token"}
    assert "secret-token" not in str(env.env_vars)

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/environments/{env_id}",
        json={
            "memory_mb": 512,
            "disk_mb": 4096,
            "max_artifact_size_mb": 64,
            "env_vars": {"API_TOKEN": "rotated-token"},
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    update_body = update_resp.json()
    assert update_body == {
        **create_body,
        "memory_mb": 512,
        "disk_mb": 4096,
        "max_artifact_size_mb": 64,
        "env_vars": {"API_TOKEN": "rotated-token"},
    }

    await integration_db_session.refresh(env)
    assert env.memory_mb == 512
    assert env.resource_limits["disk_mb"] == 4096
    assert env.resource_limits["max_artifact_size_mb"] == 64
    assert "rotated-token" not in str(env.env_vars)

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/environments/{env_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    assert delete_resp.content == b""
    await integration_db_session.refresh(env)
    assert env.deleted_at is not None

    repo = EnvironmentRepository(integration_db_session)
    assert await repo.get_by_name(project_id, name) is None
    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=env.id,
        expected={
            "environment.create",
            "environment.update",
            "environment.delete",
        },
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
    for event in [create_audit, update_audit, delete_audit]:
        assert event.tenant_id == seed_run["tenant"].id
        assert event.user_id == seed_run["user"].id
        assert event.resource_type == "environment"
        assert event.resource_id == env.id

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
    expected_create_audit_after = _expected_environment_audit_state(create_body)
    expected_update_audit_after = _expected_environment_audit_state(update_body)
    assert create_audit.before_state is None
    assert create_audit.after_state == expected_create_audit_after
    assert update_audit.before_state == expected_create_audit_after
    assert update_audit.after_state == expected_update_audit_after
    assert delete_audit.before_state == expected_update_audit_after
    assert delete_audit.after_state is None


@pytest.mark.asyncio
async def test_environment_api_reads_resource_limits_without_audit_secret_leak(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Environment

    project_id = seed_run["project"].id
    name = f"env-resource-read-{uuid4().hex[:8]}"
    secret = f"resource-secret-{uuid4().hex}"

    def assert_resource_fields(body: dict, *, max_count: int, disk_mb: int) -> None:
        assert body["name"] == name
        assert body["memory_mb"] == 768
        assert body["cpu_cores"] == 1.25
        assert body["disk_mb"] == disk_mb
        assert body["max_artifact_size_mb"] == 77
        assert body["max_artifacts_count"] == max_count
        assert body["network_policy"] == "restricted"
        assert body["env_vars"] == {"RESOURCE_TOKEN": secret}
        assert body["cache_key"] == "resource-cache-v1"

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/environments",
        json={
            "name": name,
            "base_image": "python:3.12-alpine",
            "setup_script": "python -V",
            "memory_mb": 768,
            "cpu_cores": 1.25,
            "disk_mb": 2048,
            "max_artifact_size_mb": 77,
            "max_artifacts_count": 11,
            "network_policy": "restricted",
            "env_vars": {"RESOURCE_TOKEN": secret},
            "cache_key": "resource-cache-v1",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    create_body = create_resp.json()
    assert_resource_fields(create_body, max_count=11, disk_mb=2048)
    env_id = UUID(create_body["id"])

    get_resp = await integration_client.get(
        f"/api/v1/projects/{project_id}/environments/{env_id}"
    )
    assert get_resp.status_code == 200, get_resp.text
    assert_resource_fields(get_resp.json(), max_count=11, disk_mb=2048)

    list_resp = await integration_client.get(
        f"/api/v1/projects/{project_id}/environments",
        params={"page": 1, "per_page": 100},
    )
    assert list_resp.status_code == 200, list_resp.text
    list_body = list_resp.json()
    listed = next(
        item for item in list_body["data"] if item["id"] == str(env_id)
    )
    assert_resource_fields(listed, max_count=11, disk_mb=2048)

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/environments/{env_id}",
        json={"disk_mb": 4096, "max_artifacts_count": 13},
    )
    assert update_resp.status_code == 200, update_resp.text
    update_body = update_resp.json()
    assert_resource_fields(update_body, max_count=13, disk_mb=4096)

    env = await integration_db_session.get(Environment, env_id)
    assert env is not None
    assert env.memory_mb == 768
    assert env.cpu_cores == 1.25
    assert env.resource_limits == {
        "disk_mb": 4096,
        "max_artifact_size_mb": 77,
        "max_artifacts_count": 13,
    }
    assert secret not in repr(env.env_vars)

    create_audit = await _audit_event(
        integration_db_session,
        action="environment.create",
        resource_id=env_id,
    )
    update_audit = await _audit_event(
        integration_db_session,
        action="environment.update",
        resource_id=env_id,
    )
    assert create_audit is not None
    assert update_audit is not None
    serialized_audit = repr(
        [
            create_audit.before_state,
            create_audit.after_state,
            update_audit.before_state,
            update_audit.after_state,
        ]
    )
    assert secret not in serialized_audit
    assert create_audit.before_state is None
    assert create_audit.after_state["env_vars"] == {"redacted": True, "count": 1}
    assert create_audit.after_state["memory_mb"] == 768
    assert create_audit.after_state["cpu_cores"] == 1.25
    assert create_audit.after_state["disk_mb"] == 2048
    assert create_audit.after_state["max_artifact_size_mb"] == 77
    assert create_audit.after_state["max_artifacts_count"] == 11
    assert update_audit.before_state["disk_mb"] == 2048
    assert update_audit.after_state["disk_mb"] == 4096
    assert update_audit.before_state["max_artifact_size_mb"] == 77
    assert update_audit.before_state["max_artifacts_count"] == 11
    assert update_audit.after_state["max_artifact_size_mb"] == 77
    assert update_audit.after_state["max_artifacts_count"] == 13
    assert update_audit.before_state["env_vars"] == {"redacted": True, "count": 1}
    assert update_audit.after_state["env_vars"] == {"redacted": True, "count": 1}


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
    create_body = create_resp.json()
    rule_id = create_body["id"]
    assert create_body == {
        "id": rule_id,
        "project_id": str(project_id),
        "name": name,
        "enabled": True,
        "conditions": [{"field": "status", "operator": "eq", "value": "failed"}],
        "channels": [
            {
                "type": "email",
                "config": {"to_addresses": [email_address]},
                "template": None,
            }
        ],
        "template": "Run {{run_id}} failed secret-template-marker",
        "created_at": create_body["created_at"],
    }

    rule = await integration_db_session.get(NotificationRule, rule_id)
    assert rule is not None
    assert rule.project_id == project_id
    assert rule.conditions[0]["value"] == "failed"
    assert rule.channels[0]["config"]["to_addresses"] == [email_address]

    update_resp = await integration_client.put(
        f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
        json={
            "enabled": False,
            "channels": [{"type": "webhook", "webhook_url": webhook_url}],
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    update_body = update_resp.json()
    assert update_body == {
        **create_body,
        "enabled": False,
        "channels": [
            {
                "type": "webhook",
                "config": {"url": webhook_url},
                "template": None,
            }
        ],
    }
    await integration_db_session.refresh(rule)
    assert rule.enabled is False
    assert rule.channels[0]["type"] == "webhook"
    assert rule.channels[0]["config"]["url"] == webhook_url

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    assert delete_resp.content == b""
    await integration_db_session.refresh(rule)
    assert rule.deleted_at is not None

    repo = NotificationRuleRepository(integration_db_session)
    visible, total = await repo.list_by_project(project_id, limit=100)
    assert total == 0
    assert visible == []
    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=rule.id,
        expected={
            "notification_rule.create",
            "notification_rule.update",
            "notification_rule.delete",
        },
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
    for event in [create_audit, update_audit, delete_audit]:
        assert event.tenant_id == seed_run["tenant"].id
        assert event.user_id == seed_run["user"].id
        assert event.resource_type == "notification_rule"
        assert event.resource_id == rule.id

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
    expected_create_audit_after = _expected_notification_rule_audit_state(create_body)
    expected_update_audit_after = _expected_notification_rule_audit_state(update_body)
    assert create_audit.before_state is None
    assert create_audit.after_state == expected_create_audit_after
    assert update_audit.before_state == expected_create_audit_after
    assert update_audit.after_state == expected_update_audit_after
    assert delete_audit.before_state == expected_update_audit_after
    assert delete_audit.after_state is None


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
    created_schedule = schedule_resp.json()
    schedule_id = created_schedule["id"]
    assert created_schedule == {
        "id": schedule_id,
        "project_id": str(project_id),
        "pipeline_id": str(pipeline_id),
        "cron_expr": "*/15 * * * *",
        "timezone": "Asia/Shanghai",
        "missed_fire_policy": "run_once",
        "quiet_windows": [
            {"start": "00:00", "end": "01:00", "timezone": "Asia/Shanghai"}
        ],
        "enabled": True,
        "last_run_at": None,
        "next_run_at": created_schedule["next_run_at"],
        "last_error": None,
        "created_at": created_schedule["created_at"],
    }

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
    updated_schedule = update_resp.json()
    assert updated_schedule == {
        **created_schedule,
        "cron_expr": "*/30 * * * *",
        "enabled": False,
        "next_run_at": updated_schedule["next_run_at"],
    }
    await integration_db_session.refresh(schedule)
    assert schedule.enabled is False
    assert schedule.cron_expr == "*/30 * * * *"

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/schedules/{schedule_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    assert delete_resp.content == b""
    await integration_db_session.refresh(schedule)
    assert schedule.deleted_at is not None

    run_resp = await integration_client.post(
        "/api/v1/runs",
        json={"pipeline_id": str(pipeline_id), "git_ref": "feature/p0", "priority": 0},
    )
    assert run_resp.status_code == 201, run_resp.text
    created_run = run_resp.json()
    run_id = created_run["id"]

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

    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=schedule.id,
        expected={"schedule.create", "schedule.update", "schedule.delete"},
    )
    create_audit = await _audit_event(
        integration_db_session,
        action="schedule.create",
        resource_id=schedule.id,
    )
    update_audit = await _audit_event(
        integration_db_session,
        action="schedule.update",
        resource_id=schedule.id,
    )
    delete_audit = await _audit_event(
        integration_db_session,
        action="schedule.delete",
        resource_id=schedule.id,
    )
    assert create_audit is not None
    assert update_audit is not None
    assert delete_audit is not None
    for event in [create_audit, update_audit, delete_audit]:
        assert event.tenant_id == seed_run["tenant"].id
        assert event.user_id == seed_run["user"].id
        assert event.resource_type == "schedule"
        assert event.resource_id == schedule.id

    assert create_audit.before_state is None
    assert create_audit.after_state == created_schedule
    assert update_audit.before_state == created_schedule
    assert update_audit.after_state == updated_schedule
    assert delete_audit.before_state == updated_schedule
    assert delete_audit.after_state is None
    assert "run.trigger" in await _audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=run.id,
    )
    run_audit = await _audit_event(
        integration_db_session,
        action="run.trigger",
        resource_id=run.id,
    )
    assert run_audit is not None
    assert run_audit.tenant_id == seed_run["tenant"].id
    assert run_audit.user_id == seed_run["user"].id
    assert run_audit.resource_type == "run"
    assert run_audit.resource_id == run.id
    assert run_audit.before_state is None
    assert run_audit.after_state == created_run


@pytest.mark.asyncio
async def test_manual_run_priority_persists_worker_queue_metadata_with_real_db(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run

    pipeline_id = str(seed_run["pipeline"].id)
    tenant_id = seed_run["tenant"].id
    user_id = seed_run["user"].id
    arq = _RecordingArq()
    original_arq_pool = integration_app.state.container.arq_pool
    settings = integration_app.state.container.settings
    original_max_total = settings.max_concurrent_runs
    original_max_per_project = settings.max_concurrent_per_project
    integration_app.state.container.arq_pool = arq
    settings.max_concurrent_runs = 1000
    settings.max_concurrent_per_project = 1000

    try:
        cases = [
            (0, "queue:high"),
            (1, "queue:medium"),
            (2, "queue:low"),
        ]
        run_ids: list[UUID] = []

        for priority, expected_queue in cases:
            response = await integration_client.post(
                "/api/v1/runs",
                json={
                    "pipeline_id": pipeline_id,
                    "git_ref": f"queue-priority-{priority}-{uuid4().hex}",
                    "priority": priority,
                },
            )
            assert response.status_code == 201, response.text
            body = response.json()
            run_id = UUID(body["id"])
            run_ids.append(run_id)

            integration_db_session.expire_all()
            run = await integration_db_session.get(Run, run_id)
            assert run is not None
            assert body["priority"] == priority
            assert body["git_ref"] == run.git_ref
            assert body["status"] == "queued"
            assert run.priority == priority
            assert run.queue_name == expected_queue
            assert run.arq_job_id == f"run:{run_id}"
            assert run.enqueued_at is not None

            audit = await _audit_event(
                integration_db_session,
                action="run.trigger",
                resource_id=run_id,
            )
            assert audit is not None
            assert audit.tenant_id == tenant_id
            assert audit.user_id == user_id
            assert audit.resource_type == "run"
            assert audit.before_state is None
            assert audit.after_state == body
            serialized_audit = repr(audit.after_state)
            assert "queue_name" not in serialized_audit
            assert "arq_job_id" not in serialized_audit
            assert "git_url" not in serialized_audit
            assert "credential_id" not in serialized_audit

        assert [call["args"] for call in arq.calls] == [
            ("execute_run", str(run_id)) for run_id in run_ids
        ]
        assert [call["kwargs"]["_queue_name"] for call in arq.calls] == [
            "queue:high",
            "queue:medium",
            "queue:low",
        ]
        assert [call["kwargs"]["_job_id"] for call in arq.calls] == [
            f"run:{run_id}" for run_id in run_ids
        ]
    finally:
        integration_app.state.container.arq_pool = original_arq_pool
        settings.max_concurrent_runs = original_max_total
        settings.max_concurrent_per_project = original_max_per_project


@pytest.mark.asyncio
async def test_single_run_cancel_persists_state_redis_event_and_audit_row(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import EVENT_STREAM_KEY, STATUS_HASH_KEY
    from qaplatform.infra.database.models import RunStatusEnum

    run = seed_run["run"]
    run.status = RunStatusEnum.RUNNING
    await integration_db_session.commit()
    await integration_db_session.refresh(run)
    expected_before = _expected_run_response(
        run,
        pipeline_name=seed_run["pipeline"].name,
    )

    response = await integration_client.post(f"/api/v1/runs/{run.id}/cancel")

    assert response.status_code == 200, response.text
    body = response.json()

    await integration_db_session.refresh(run)
    expected_after = _expected_run_response(
        run,
        pipeline_name=seed_run["pipeline"].name,
    )
    assert body == expected_after
    assert run.status == RunStatusEnum.CANCELLED
    assert run.cancel_requested_at is not None
    assert run.finished_at is not None

    redis = integration_app.state.container.redis_client
    status_hash = await redis.hgetall(STATUS_HASH_KEY.format(run_id=str(run.id)))
    decoded_status = _decode_redis_mapping(status_hash)

    events = await redis.xrange(EVENT_STREAM_KEY.format(run_id=str(run.id)))
    assert events, "cancel API did not publish a Redis status event"
    _event_id, latest_event = events[-1]
    decoded_event = _decode_redis_mapping(latest_event)
    _assert_run_cancel_redis_event(decoded_event, decoded_status, run.id)

    await _assert_audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=run.id,
        expected={"run.cancel"},
    )

    audit = await _audit_event(
        integration_db_session,
        action="run.cancel",
        resource_id=run.id,
    )
    assert audit is not None
    assert audit.tenant_id == seed_run["tenant"].id
    assert audit.user_id == seed_run["user"].id
    assert audit.resource_type == "run"
    assert audit.resource_id == run.id
    assert audit.before_state == expected_before
    assert audit.after_state == expected_after


@pytest.mark.asyncio
async def test_batch_run_apis_persist_state_and_audit_rows(
    integration_app,
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import EVENT_STREAM_KEY, STATUS_HASH_KEY
    from qaplatform.infra.database.models import Run, RunStatusEnum

    run = seed_run["run"]
    run.status = RunStatusEnum.RUNNING
    await integration_db_session.commit()
    await integration_db_session.refresh(run)
    expected_before = _expected_run_response(
        run,
        pipeline_name=seed_run["pipeline"].name,
    )

    cancel_resp = await integration_client.post(
        "/api/v1/runs/batch/cancel",
        json={"run_ids": [str(run.id)]},
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    assert cancel_resp.json() == {"processed": 1, "failed": 0, "errors": []}
    await integration_db_session.refresh(run)
    expected_cancelled = _expected_run_response(
        run,
        pipeline_name=seed_run["pipeline"].name,
    )
    assert run.status == RunStatusEnum.CANCELLED

    redis = integration_app.state.container.redis_client
    status_hash = await redis.hgetall(STATUS_HASH_KEY.format(run_id=str(run.id)))
    decoded_status = _decode_redis_mapping(status_hash)
    events = await redis.xrange(EVENT_STREAM_KEY.format(run_id=str(run.id)))
    assert events, "batch cancel API did not publish a Redis status event"
    _event_id, latest_event = events[-1]
    decoded_event = _decode_redis_mapping(latest_event)
    _assert_run_cancel_redis_event(decoded_event, decoded_status, run.id)

    batch_cancel_audit = await _audit_event(
        integration_db_session,
        action="run.batch_cancel",
        resource_id=run.id,
    )
    assert batch_cancel_audit is not None
    assert batch_cancel_audit.tenant_id == seed_run["tenant"].id
    assert batch_cancel_audit.user_id == seed_run["user"].id
    assert batch_cancel_audit.resource_type == "run"
    assert batch_cancel_audit.resource_id == run.id
    assert batch_cancel_audit.before_state == expected_before
    assert batch_cancel_audit.after_state == expected_cancelled

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

    batch_retry_audit = await _audit_event(
        integration_db_session,
        action="run.batch_retry",
        resource_id=run.id,
    )
    assert batch_retry_audit is not None
    assert batch_retry_audit.tenant_id == seed_run["tenant"].id
    assert batch_retry_audit.user_id == seed_run["user"].id
    assert batch_retry_audit.resource_type == "run"
    assert batch_retry_audit.resource_id == run.id
    assert batch_retry_audit.before_state == expected_cancelled
    assert batch_retry_audit.after_state == {
        "retry_run_id": str(retry_run.id),
        "source_run_id": str(run.id),
        "status": "queued",
        "attempt": retry_run.attempt,
    }

    actions = await _audit_actions(
        integration_db_session,
        user_id=seed_run["user"].id,
        resource_id=run.id,
    )
    assert actions == ["run.batch_cancel", "run.batch_retry"]


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
    _assert_not_found_response(resp.json(), "Pipeline not found")
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
    from qaplatform.infra.database.models import AuditEvent, Run

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
    before_run_create_audits = await _row_count(
        integration_db_session,
        AuditEvent,
        AuditEvent.user_id == user.id,
        AuditEvent.action == "run.create",
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
    assert resp.json() == {
        "detail": "Project is archived; new runs cannot be triggered"
    }
    assert (
        await _row_count(
            integration_db_session,
            Run,
            Run.project_id == project.id,
            Run.trigger_type == "manual",
        )
        == before
    )
    assert (
        await _row_count(
            integration_db_session,
            AuditEvent,
            AuditEvent.user_id == user.id,
            AuditEvent.action == "run.create",
        )
        == before_run_create_audits
    )
