from __future__ import annotations

from datetime import datetime, timezone
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


class _ConflictArq:
    async def enqueue_job(self, *_args, _job_id: str, **_kwargs):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_webhook_same_commit_second_trigger_returns_duplicate(
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
    assert "archived" in resp.json()["detail"].lower()
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
    assert resp.json()["detail"] == "No pipeline configured for project"
    assert await _webhook_run_count(integration_db_session, project.id) == before


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
    assert resp.json()["detail"] == "No environment configured for project"
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
    run_id = UUID(resp.json()["id"])
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


@pytest.mark.asyncio
async def test_webhook_filtered_branch_returns_200_and_creates_no_run(
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
        {"allowed_branches": ["main", "release/*"]},
    )
    before = await _webhook_run_count(integration_db_session, project.id)

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={"git_ref": "refs/heads/feature/nope", "git_sha": "def456"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "filtered"
    assert await _webhook_run_count(integration_db_session, project.id) == before


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

    first_run_id = UUID(first.json()["id"])
    await integration_db_session.execute(
        update(Run).where(Run.id == first_run_id).values(status=RunStatusEnum.DONE)
    )
    await integration_db_session.commit()

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        second = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger", json=payload
        )

    assert second.status_code == 201, second.text
    dedup_key = f"github:{project.git_url}:done-sha:release/2026.05"
    assert (
        await _webhook_run_count(
            integration_db_session, project.id, dedup_key=dedup_key
        )
        == 2
    )


@pytest.mark.asyncio
async def test_webhook_cross_tenant_project_returns_404(
    seed_run,
    seed_second_tenant,
    integration_app,
    integration_client_as,
):
    user_a = seed_run["user"]
    tenant_a = seed_run["tenant"]
    project_b = seed_second_tenant["project"]
    integration_app.state.container.arq_pool = None

    async with integration_client_as(user_a.id, tenant_a.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project_b.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
        )

    assert resp.status_code == 404
