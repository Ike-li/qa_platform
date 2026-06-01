"""Real PostgreSQL integration coverage for repository and API persistence.

These tests intentionally avoid mocking repositories or database sessions.
They verify behaviors that unit tests with mocks cannot prove: tenant-scoped
queries, real uniqueness constraints, transaction rollback, persisted project
membership, and conditional run state updates.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


def _assert_integrity_constraint(error: IntegrityError, constraint: str) -> None:
    haystack = " ".join(
        str(part)
        for part in (
            error,
            getattr(error, "orig", ""),
            repr(getattr(error, "orig", "")),
        )
    )
    assert constraint in haystack


def _project_payload(slug: str) -> dict:
    return {
        "name": f"project-{slug}",
        "slug": slug,
        "git_url": "https://example.com/repo.git",
        "default_branch": "main",
    }


def _pipeline_payload(name: str) -> dict:
    return {
        "name": name,
        "stages": [
            {
                "name": "run-tests",
                "plugin": "pytest",
                "phase": "execute",
                "config": {},
            }
        ],
        "trigger_config": {"type": "manual"},
        "timeout_seconds": 600,
    }


async def _project_count_by_slug(session, tenant_id, slug: str) -> int:
    from qaplatform.infra.database.models import Project

    result = await session.execute(
        select(func.count()).select_from(Project).where(
            Project.tenant_id == tenant_id,
            Project.slug == slug,
            Project.deleted_at.is_(None),
        )
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_project_repository_filters_tenant_paginates_and_excludes_soft_deleted(
    integration_db_session,
    seed_run,
    seed_second_tenant,
):
    from qaplatform.infra.database.repositories.project_repo import ProjectRepository

    repo = ProjectRepository(integration_db_session)
    tenant_a = seed_run["tenant"].id
    tenant_b = seed_second_tenant["tenant"].id
    user_a = seed_run["user"].id

    keep = await repo.create(
        tenant_id=tenant_a,
        created_by=user_a,
        **_project_payload(f"keep-{uuid4().hex[:8]}"),
    )
    soft_deleted = await repo.create(
        tenant_id=tenant_a,
        created_by=user_a,
        **_project_payload(f"deleted-{uuid4().hex[:8]}"),
    )
    await repo.delete(soft_deleted)
    await integration_db_session.commit()

    items, total = await repo.list_by_tenant(tenant_a, offset=0, limit=50)

    ids = {item.id for item in items}
    tenant_ids = {item.tenant_id for item in items}
    assert total == 2
    assert ids == {keep.id, seed_run["project"].id}
    assert seed_second_tenant["project"].id not in ids
    assert soft_deleted.id not in ids
    assert tenant_ids == {tenant_a}

    tenant_b_items, tenant_b_total = await repo.list_by_tenant(
        tenant_b, offset=0, limit=50
    )
    assert tenant_b_total == 1
    assert {item.id for item in tenant_b_items} == {seed_second_tenant["project"].id}
    assert {item.tenant_id for item in tenant_b_items} == {tenant_b}


@pytest.mark.asyncio
async def test_project_slug_unique_constraint_rolls_back_without_dirty_data(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Project
    from qaplatform.infra.database.repositories.project_repo import ProjectRepository

    tenant_id = seed_run["tenant"].id
    user_id = seed_run["user"].id
    existing_slug = seed_run["project"].slug

    integration_db_session.add(
        Project(
            tenant_id=tenant_id,
            created_by=user_id,
            **_project_payload(existing_slug),
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        await integration_db_session.commit()
    _assert_integrity_constraint(exc_info.value, "uq_project_tenant_slug")

    await integration_db_session.rollback()

    repo = ProjectRepository(integration_db_session)
    original = await repo.get_by_slug(tenant_id, existing_slug)
    assert original is not None
    assert original.id == seed_run["project"].id
    assert await _project_count_by_slug(integration_db_session, tenant_id, existing_slug) == 1

    recovered_slug = f"after-rollback-{uuid4().hex[:8]}"
    recovered = await repo.create(
        tenant_id=tenant_id,
        created_by=user_id,
        **_project_payload(recovered_slug),
    )
    await integration_db_session.commit()
    assert recovered.id is not None


@pytest.mark.asyncio
async def test_project_create_api_persists_project_member_admin_row(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Project, ProjectMember

    slug = f"api-project-{uuid4().hex[:8]}"
    resp = await integration_client.post("/api/v1/projects", json=_project_payload(slug))
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    project = await integration_db_session.get(Project, project_id)
    assert project is not None
    assert project.slug == slug
    assert project.tenant_id == seed_run["tenant"].id

    member = await integration_db_session.get(
        ProjectMember,
        {"project_id": project.id, "user_id": seed_run["user"].id},
    )
    assert member is not None
    assert member.tenant_id == seed_run["tenant"].id
    assert member.role == "admin"


@pytest.mark.asyncio
async def test_pipeline_api_persists_rows_and_soft_delete_hides_from_repository(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Pipeline
    from qaplatform.infra.database.repositories.project_repo import PipelineRepository

    project_id = seed_run["project"].id
    name = f"api-pipeline-{uuid4().hex[:8]}"

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/pipelines",
        json=_pipeline_payload(name),
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    pipeline = await integration_db_session.get(Pipeline, pipeline_id)
    assert pipeline is not None
    assert pipeline.project_id == project_id
    assert pipeline.name == name
    assert pipeline.stages[0]["plugin"] == "pytest"

    delete_resp = await integration_client.delete(
        f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text
    assert delete_resp.content == b""

    await integration_db_session.refresh(pipeline)
    assert pipeline.deleted_at is not None

    repo = PipelineRepository(integration_db_session)
    visible, total = await repo.list_by_project(project_id, limit=100)
    assert total == 1
    assert [item.id for item in visible] == [seed_run["pipeline"].id]


@pytest.mark.asyncio
async def test_run_repository_conditional_updates_are_persisted_and_idempotent(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    repo = RunRepository(integration_db_session)
    run_id = seed_run["run"].id

    claimed = await repo.claim_for_worker(run_id, "worker-a")
    await integration_db_session.commit()
    assert claimed is not None

    second_claim = await repo.claim_for_worker(run_id, "worker-b")
    await integration_db_session.commit()
    assert second_claim is None

    run = await integration_db_session.get(Run, run_id)
    assert run is not None
    await integration_db_session.refresh(run)
    assert run.status == RunStatusEnum.PREPARING
    assert run.worker_id == "worker-a"

    assert await repo.mark_running(run_id) is True
    assert await repo.mark_running(run_id) is False
    assert await repo.cancel_if_current(run_id) is True
    assert await repo.finish_if_current(run_id, status=RunStatusEnum.DONE) is False
    await integration_db_session.commit()

    await integration_db_session.refresh(run)
    assert run.status == RunStatusEnum.CANCELLED
    assert run.cancel_requested_at is not None
