from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select, update


async def _save_project_settings(session, project, settings: dict) -> None:
    project.settings = settings
    await session.commit()
    await session.refresh(project)


async def _webhook_run_count(
    session, project_id, *, dedup_key: str | None = None
) -> int:
    from qaplatform.infra.database.models import Run

    stmt = (
        select(func.count())
        .select_from(Run)
        .where(
            Run.project_id == project_id,
            Run.trigger_type == "webhook",
        )
    )
    if dedup_key is not None:
        stmt = stmt.where(Run.dedup_key == dedup_key)

    result = await session.execute(stmt)
    return int(result.scalar_one())


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _expected_run_response(run, *, pipeline_name: str) -> dict:
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "project_id": str(run.project_id),
        "pipeline_id": str(run.pipeline_id),
        "pipeline_name": pipeline_name,
        "environment_id": str(run.environment_id),
        "status": run.status.value if hasattr(run.status, "value") else run.status,
        "trigger_type": run.trigger_type,
        "priority": run.priority,
        "triggered_by": str(run.triggered_by) if run.triggered_by else None,
        "git_ref": run.git_ref,
        "git_sha": run.git_sha,
        "attempt": run.attempt,
        "started_at": _json_datetime(run.started_at) if run.started_at else None,
        "finished_at": _json_datetime(run.finished_at) if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "summary": run.summary,
        "error_message": run.error_message,
        "created_at": _json_datetime(run.created_at),
        "updated_at": _json_datetime(run.updated_at),
    }


def _run_dedup_projection(run) -> dict:
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "project_id": run.project_id,
        "pipeline_id": run.pipeline_id,
        "environment_id": run.environment_id,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "git_ref": run.git_ref,
        "git_sha": run.git_sha,
        "triggered_by": run.triggered_by,
        "attempt": run.attempt,
        "dedup_key": run.dedup_key,
        "retry_group_id": run.retry_group_id,
    }


def _github_push_payload(repo_url: str, *, git_ref: str, git_sha: str) -> dict:
    full_name = "/".join(repo_url.removesuffix(".git").split("/")[-2:])
    return {
        "ref": git_ref,
        "after": git_sha,
        "repository": {
            "full_name": full_name,
            "clone_url": repo_url,
            "html_url": repo_url.removesuffix(".git"),
            "ssh_url": f"git@github.com:{full_name}.git",
        },
    }


class _ConflictArq:
    async def enqueue_job(self, *_args, _job_id: str, **_kwargs):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_provider_github_push_matches_repo_url_without_user_and_audits_system_identity(
    seed_run,
    integration_app,
    integration_client,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, Run
    from qaplatform.infra.webhook_signature import generate_webhook_signature

    project = seed_run["project"]
    integration_app.state.container.arq_pool = None
    project.git_url = f"https://github.com/acme/qa-platform-{project.id}.git"
    secret = "github-provider-secret"
    await _save_project_settings(
        integration_db_session,
        project,
        {"webhook_secret": secret, "allowed_branches": ["main"]},
    )
    payload = _github_push_payload(
        project.git_url,
        git_ref="refs/heads/main",
        git_sha="a" * 40,
    )
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = generate_webhook_signature(secret, raw_body)

    resp = await integration_client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": f"delivery-{project.id}",
            "X-Hub-Signature-256": signature,
        },
    )

    assert resp.status_code == 201, resp.text
    response_body = resp.json()
    run_id = UUID(response_body["id"])
    run = await integration_db_session.get(Run, run_id)
    assert run is not None
    assert run.tenant_id == project.tenant_id
    assert run.project_id == project.id
    assert run.triggered_by is None
    assert run.git_ref == "refs/heads/main"
    assert run.git_sha == "a" * 40
    assert run.metadata_["provider"] == "github"
    assert run.metadata_["event"] == "push"
    assert run.metadata_["delivery_id"] == f"delivery-{project.id}"
    assert run.metadata_["git_url"] == project.git_url
    assert run.dedup_key == f"github:{project.git_url}:{'a' * 40}:main"

    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "run.trigger",
                    AuditEvent.resource_id == run.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.tenant_id == project.tenant_id
    assert audit.user_id is None
    assert audit.after_state == response_body


@pytest.mark.asyncio
async def test_provider_github_push_rejects_invalid_signature_without_run(
    seed_run,
    integration_app,
    integration_client,
    integration_db_session,
):
    project = seed_run["project"]
    integration_app.state.container.arq_pool = None
    project.git_url = f"https://github.com/acme/qa-platform-{project.id}.git"
    await _save_project_settings(
        integration_db_session,
        project,
        {"webhook_secret": "github-provider-secret"},
    )
    before = await _webhook_run_count(integration_db_session, project.id)
    payload = _github_push_payload(
        project.git_url,
        git_ref="refs/heads/main",
        git_sha="b" * 40,
    )
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    resp = await integration_client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": "sha256=bad",
        },
    )

    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "Invalid webhook signature"}
    assert "github-provider-secret" not in resp.text
    assert str(project.id) not in resp.text
    assert project.git_url not in resp.text
    assert await _webhook_run_count(integration_db_session, project.id) == before


@pytest.mark.asyncio
async def test_provider_github_push_filtered_branch_uses_api_v1_alias_and_system_audit(
    seed_run,
    integration_app,
    integration_client,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent
    from qaplatform.infra.webhook_signature import generate_webhook_signature

    project = seed_run["project"]
    integration_app.state.container.arq_pool = None
    project.git_url = f"https://github.com/acme/qa-platform-{project.id}.git"
    secret = "github-provider-secret"
    await _save_project_settings(
        integration_db_session,
        project,
        {"webhook_secret": secret, "allowed_branches": ["main"]},
    )
    before = await _webhook_run_count(integration_db_session, project.id)
    payload = _github_push_payload(
        project.git_url,
        git_ref="refs/heads/feature/nope",
        git_sha="c" * 40,
    )
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = generate_webhook_signature(secret, raw_body)

    resp = await integration_client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": f"provider-filtered-{project.id}",
            "X-Hub-Signature-256": signature,
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "filtered", "reason": "branch_not_allowed"}
    assert await _webhook_run_count(integration_db_session, project.id) == before

    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "webhook.filtered",
                    AuditEvent.resource_id == project.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.user_id is None
    assert audit.tenant_id == project.tenant_id
    assert audit.resource_type == "project"
    assert audit.resource_id == project.id
    assert audit.before_state is None
    assert audit.after_state == {
        "project_id": str(project.id),
        "status": "filtered",
        "reason": "branch_not_allowed",
        "git_ref": "refs/heads/feature/nope",
        "git_sha": "c" * 40,
        "branch_name": "feature/nope",
        "provider": "github",
        "delivery_id": f"provider-filtered-{project.id}",
    }
    assert project.git_url not in repr(audit.after_state)
    assert secret not in repr(audit.after_state)


@pytest.mark.asyncio
async def test_webhook_same_commit_second_trigger_returns_duplicate(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent

    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    await _save_project_settings(
        integration_db_session,
        project,
        {"allowed_branches": ["main"]},
    )

    payload = {
        "git_ref": "refs/heads/main",
        "git_sha": "abc123",
        "metadata": {"provider": "github"},
    }

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        first = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger", json=payload
        )
        second = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger", json=payload
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json() == {"status": "duplicate"}

    dedup_key = f"github:{project.git_url}:abc123:main"
    assert (
        await _webhook_run_count(
            integration_db_session, project.id, dedup_key=dedup_key
        )
        == 1
    )
    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "webhook.duplicate",
                    AuditEvent.resource_id == project.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.user_id == user.id
    assert audit.tenant_id == tenant.id
    assert audit.resource_type == "project"
    assert audit.resource_id == project.id
    assert audit.before_state is None
    assert audit.after_state == {
        "project_id": str(project.id),
        "status": "duplicate",
        "reason": "dedup_key_conflict",
        "git_ref": "refs/heads/main",
        "git_sha": "abc123",
        "branch_name": "main",
        "provider": "github",
    }
    assert project.git_url not in repr(audit.after_state)
    assert dedup_key not in repr(audit.after_state)


@pytest.mark.asyncio
async def test_webhook_archived_project_returns_409_and_creates_no_run(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    project.status = "archived"
    await integration_db_session.commit()
    await integration_db_session.refresh(project)
    before = await _webhook_run_count(integration_db_session, project.id)

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "archived-sha"},
        )

    assert resp.status_code == 409, resp.text
    assert resp.json() == {
        "detail": "Project is archived; new runs cannot be triggered",
    }
    assert await _webhook_run_count(integration_db_session, project.id) == before


@pytest.mark.asyncio
async def test_webhook_without_pipeline_returns_409_and_creates_no_run(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    seed_run["pipeline"].deleted_at = datetime.now(timezone.utc)
    await integration_db_session.commit()
    before = await _webhook_run_count(integration_db_session, project.id)

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "missing-pipeline-sha"},
        )

    assert resp.status_code == 409, resp.text
    assert resp.json() == {"detail": "No pipeline configured for project"}
    assert await _webhook_run_count(integration_db_session, project.id) == before


@pytest.mark.asyncio
async def test_webhook_skips_disabled_pipeline_and_picks_the_enabled_one(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    """webhook 选 pipeline 时必须跳过 enabled=False 的。

    选择逻辑取 created_at 最新的一个且不看 enabled，而外部结果导入会建一个
    名为 external-import 的占位 pipeline 并显式置为 enabled=False。只要用过
    一次导入，占位 pipeline 就成了最新的那个，此后所有 webhook 都会挂到它
    身上——那条 pipeline 没有真正的执行阶段。
    """
    from qaplatform.infra.database.models import Pipeline

    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    enabled_pipeline = seed_run["pipeline"]

    disabled = Pipeline(
        project_id=project.id,
        name="external-import",
        stages=[{"name": "pytest", "plugin": "pytest", "phase": "execute", "config": {}}],
        selector={},
        trigger_config={"type": "manual"},
        collectors=[],
        timeout_seconds=600,
        enabled=False,
        created_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    integration_db_session.add(disabled)
    await integration_db_session.commit()

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={
                "git_ref": "refs/heads/main",
                "git_sha": "a" * 40,
            },
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["pipeline_id"] == str(enabled_pipeline.id)


@pytest.mark.asyncio
async def test_webhook_without_environment_returns_409_and_creates_no_run(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    seed_run["environment"].deleted_at = datetime.now(timezone.utc)
    await integration_db_session.commit()
    before = await _webhook_run_count(integration_db_session, project.id)

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "missing-env-sha"},
        )

    assert resp.status_code == 409, resp.text
    assert resp.json() == {"detail": "No environment configured for project"}
    assert await _webhook_run_count(integration_db_session, project.id) == before


@pytest.mark.asyncio
async def test_webhook_enqueue_conflict_keeps_run_waiting_and_audited(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, Run, RunStatusEnum

    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = _ConflictArq()
    payload = {
        "git_ref": "refs/heads/main",
        "git_sha": "enqueue-conflict-sha",
        "metadata": {"provider": "github"},
    }

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(f"/api/v1/webhooks/{project.id}/trigger", json=payload)

    assert resp.status_code == 201, resp.text
    response_body = resp.json()
    run_id = UUID(response_body["id"])
    run = await integration_db_session.get(Run, run_id)
    assert run is not None
    assert run.trigger_type == "webhook"
    assert run.status == RunStatusEnum.QUEUED
    assert run.enqueued_at is None
    assert run.arq_job_id is None
    assert run.retry_group_id == run.id
    assert run.dedup_key == f"github:{project.git_url}:enqueue-conflict-sha:main"

    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "run.trigger",
                    AuditEvent.resource_id == run.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.user_id == user.id
    assert audit.after_state == response_body


@pytest.mark.asyncio
async def test_signed_webhook_rejects_missing_signature_without_creating_run(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    await _save_project_settings(
        integration_db_session,
        project,
        {"webhook_secret": "signed-webhook-secret"},
    )
    before = await _webhook_run_count(integration_db_session, project.id)

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "missing-signature"},
        )

    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "Missing X-Webhook-Signature header"}
    assert "signed-webhook-secret" not in resp.text
    assert str(project.id) not in resp.text
    assert await _webhook_run_count(integration_db_session, project.id) == before


@pytest.mark.asyncio
async def test_signed_webhook_success_audits_and_protects_reserved_metadata(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, Run
    from qaplatform.infra.webhook_signature import generate_webhook_signature

    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    secret = "signed-webhook-secret"
    await _save_project_settings(
        integration_db_session,
        project,
        {"webhook_secret": secret, "allowed_branches": ["release/*"]},
    )
    attacker_url = "https://attacker.example/evil.git"
    attacker_credential = str(UUID("00000000-0000-0000-0000-000000000123"))
    payload = {
        "git_ref": "refs/heads/release/2026.05",
        "git_sha": "signed-webhook-sha",
        "metadata": {
            "provider": "github",
            "delivery_id": f"delivery-{project.id}",
            "git_url": attacker_url,
            "credential_id": attacker_credential,
            "shallow_clone": False,
            "default_branch": "evil",
        },
    }
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = generate_webhook_signature(secret, raw_body)

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
            },
        )

    assert resp.status_code == 201, resp.text
    response_body = resp.json()
    run_id = UUID(response_body["id"])
    run = await integration_db_session.get(Run, run_id)
    assert run is not None
    assert run.tenant_id == tenant.id
    assert run.project_id == project.id
    assert run.pipeline_id == seed_run["pipeline"].id
    assert run.environment_id == seed_run["environment"].id
    assert run.triggered_by == user.id
    assert run.trigger_type == "webhook"
    assert run.git_ref == "refs/heads/release/2026.05"
    assert run.git_sha == "signed-webhook-sha"
    assert run.dedup_key == f"github:{project.git_url}:signed-webhook-sha:release/2026.05"
    assert run.metadata_["git_url"] == project.git_url
    assert run.metadata_["shallow_clone"] is True
    assert run.metadata_["default_branch"] == project.default_branch
    assert run.metadata_["delivery_id"] == f"delivery-{project.id}"
    serialized_metadata = repr(run.metadata_)
    assert attacker_url not in serialized_metadata
    assert attacker_credential not in serialized_metadata
    assert "evil" not in serialized_metadata

    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "run.trigger",
                    AuditEvent.resource_id == run.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.tenant_id == tenant.id
    assert audit.user_id == user.id
    assert audit.resource_type == "run"
    assert audit.resource_id == run.id
    assert audit.before_state is None
    assert audit.after_state == response_body
    assert audit.after_state["trigger_type"] == "webhook"
    assert attacker_url not in repr(audit.after_state)
    assert attacker_credential not in repr(audit.after_state)
    assert "evil" not in repr(audit.after_state)


@pytest.mark.asyncio
async def test_webhook_filtered_branch_returns_200_and_creates_no_run(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent

    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    await _save_project_settings(
        integration_db_session,
        project,
        {"allowed_branches": ["main", "release/*"]},
    )
    before = await _webhook_run_count(integration_db_session, project.id)

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={
                "git_ref": "refs/heads/feature/nope",
                "git_sha": "def456",
                "metadata": {
                    "provider": "github",
                    "delivery_id": f"filtered-{project.id}",
                    "git_url": "https://attacker.example/leak.git",
                    "credential_id": "should-not-be-audited",
                },
            },
        )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "filtered", "reason": "branch_not_allowed"}
    assert await _webhook_run_count(integration_db_session, project.id) == before
    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "webhook.filtered",
                    AuditEvent.resource_id == project.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.tenant_id == tenant.id
    assert audit.user_id == user.id
    assert audit.resource_type == "project"
    assert audit.resource_id == project.id
    assert audit.before_state is None
    assert audit.after_state == {
        "project_id": str(project.id),
        "status": "filtered",
        "reason": "branch_not_allowed",
        "git_ref": "refs/heads/feature/nope",
        "git_sha": "def456",
        "branch_name": "feature/nope",
        "provider": "github",
        "delivery_id": f"filtered-{project.id}",
    }
    serialized_audit = repr(audit.after_state)
    assert project.git_url not in serialized_audit
    assert "attacker.example" not in serialized_audit
    assert "should-not-be-audited" not in serialized_audit


@pytest.mark.asyncio
async def test_webhook_terminal_same_commit_can_trigger_again(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import Run, RunStatusEnum

    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    await _save_project_settings(
        integration_db_session,
        project,
        {"allowed_branches": ["release/*"]},
    )

    payload = {
        "git_ref": "refs/heads/release/2026.05",
        "git_sha": "done-sha",
        "metadata": {"provider": "github"},
    }

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        first = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger", json=payload
        )

    assert first.status_code == 201, first.text

    first_body = first.json()
    first_run_id = UUID(first_body["id"])
    first_run = await integration_db_session.get(Run, first_run_id)
    assert first_run is not None
    assert first_body == _expected_run_response(
        first_run,
        pipeline_name=seed_run["pipeline"].name,
    )
    await integration_db_session.execute(
        update(Run).where(Run.id == first_run_id).values(status=RunStatusEnum.DONE)
    )
    await integration_db_session.commit()

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        second = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger", json=payload
        )

    assert second.status_code == 201, second.text
    second_body = second.json()
    second_run_id = UUID(second_body["id"])
    assert second_run_id != first_run_id
    second_run = await integration_db_session.get(Run, second_run_id)
    assert second_run is not None
    assert second_body == _expected_run_response(
        second_run,
        pipeline_name=seed_run["pipeline"].name,
    )
    dedup_key = f"github:{project.git_url}:done-sha:release/2026.05"
    runs = (
        await integration_db_session.execute(
            select(Run)
            .where(
                Run.project_id == project.id,
                Run.trigger_type == "webhook",
                Run.dedup_key == dedup_key,
            )
            .order_by(Run.created_at)
        )
    ).scalars().all()
    assert [run.id for run in runs] == [first_run_id, second_run_id]
    assert [_run_dedup_projection(run) for run in runs] == [
        {
            "id": first_run_id,
            "tenant_id": tenant.id,
            "project_id": project.id,
            "pipeline_id": seed_run["pipeline"].id,
            "environment_id": seed_run["environment"].id,
            "status": RunStatusEnum.DONE,
            "trigger_type": "webhook",
            "git_ref": "refs/heads/release/2026.05",
            "git_sha": "done-sha",
            "triggered_by": user.id,
            "attempt": 1,
            "dedup_key": dedup_key,
            "retry_group_id": first_run_id,
        },
        {
            "id": second_run_id,
            "tenant_id": tenant.id,
            "project_id": project.id,
            "pipeline_id": seed_run["pipeline"].id,
            "environment_id": seed_run["environment"].id,
            "status": RunStatusEnum.QUEUED,
            "trigger_type": "webhook",
            "git_ref": "refs/heads/release/2026.05",
            "git_sha": "done-sha",
            "triggered_by": user.id,
            "attempt": 1,
            "dedup_key": dedup_key,
            "retry_group_id": second_run_id,
        },
    ]


@pytest.mark.asyncio
async def test_webhook_cross_tenant_project_returns_404(
    seed_run,
    seed_second_tenant,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent

    user_a = seed_run["user"]
    tenant_a = seed_run["tenant"]
    project_b = seed_second_tenant["project"]
    integration_app.state.container.arq_pool = None
    before = await _webhook_run_count(integration_db_session, project_b.id)

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project_b.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
        )

    assert resp.status_code == 404, resp.text
    assert resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Project not found",
            "details": [],
        },
    }
    assert str(project_b.id) not in resp.text
    assert str(project_b.tenant_id) not in resp.text
    assert str(user_a.id) not in resp.text
    assert str(tenant_a.id) not in resp.text
    assert await _webhook_run_count(integration_db_session, project_b.id) == before
    audit_count = (
        await integration_db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.resource_id == project_b.id,
                AuditEvent.action.in_(["webhook.filtered", "webhook.duplicate"]),
            )
        )
    ).scalar_one()
    assert audit_count == 0
