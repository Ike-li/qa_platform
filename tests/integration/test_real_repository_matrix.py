"""Repository-level integration matrix against real PostgreSQL.

These tests cover behavior that unit-level mocks cannot prove: tenant filters,
pagination totals, uniqueness constraints, rollback recovery, cross-tenant audit
detection, soft-delete visibility, and hard-delete cascade behavior.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


async def _count_rows(session, model, *filters) -> int:
    stmt = select(func.count()).select_from(model)
    for filter_ in filters:
        stmt = stmt.where(filter_)
    return int((await session.execute(stmt)).scalar_one())


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


async def _create_run_for_state(session, seed_run, *, status, git_ref: str):
    from qaplatform.infra.database.models import Run

    run = Run(
        tenant_id=seed_run["tenant"].id,
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        environment_id=seed_run["environment"].id,
        status=status,
        trigger_type="manual",
        priority=1,
        triggered_by=seed_run["user"].id,
        git_ref=git_ref,
        metadata_={},
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_run_repository_find_waiting_orders_by_priority_then_fifo(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    now = datetime.now(timezone.utc)
    seed_run["run"].enqueued_at = now

    low_old = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref=f"low-{uuid4().hex}",
    )
    low_old.priority = 2
    low_old.created_at = now - timedelta(minutes=4)

    high_old = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref=f"high-old-{uuid4().hex}",
    )
    high_old.priority = 0
    high_old.created_at = now - timedelta(minutes=3)

    high_new = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref=f"high-new-{uuid4().hex}",
    )
    high_new.priority = 0
    high_new.created_at = now - timedelta(minutes=2)

    medium = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref=f"medium-{uuid4().hex}",
    )
    medium.priority = 1
    medium.created_at = now - timedelta(minutes=1)
    await integration_db_session.commit()

    waiting = await RunRepository(integration_db_session).find_waiting(limit=1000)
    expected_ids = {high_old.id, high_new.id, medium.id, low_old.id}
    observed = [run.id for run in waiting if run.id in expected_ids]

    assert observed == [
        high_old.id,
        high_new.id,
        medium.id,
        low_old.id,
    ]


@pytest.mark.asyncio
async def test_audit_repository_filters_paginates_and_detects_cross_tenant_matches(
    integration_db_session,
    seed_run,
    seed_second_tenant,
):
    from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository

    repo = AuditEventRepository(integration_db_session)
    tenant_a = seed_run["tenant"].id
    user_a = seed_run["user"].id
    project_a = seed_run["project"].id
    tenant_b = seed_second_tenant["tenant"].id
    user_b = seed_second_tenant["user"].id
    project_b = seed_second_tenant["project"].id

    older = await repo.create(
        tenant_id=tenant_a,
        user_id=user_a,
        action="project.update",
        resource_type="project",
        resource_id=project_a,
        after_state={"seq": "older"},
    )
    older.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    newer = await repo.create(
        tenant_id=tenant_a,
        user_id=user_a,
        action="project.update",
        resource_type="project",
        resource_id=project_a,
        after_state={"seq": "newer"},
    )
    newer.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await repo.create(
        tenant_id=tenant_b,
        user_id=user_b,
        action="project.update",
        resource_type="project",
        resource_id=project_b,
        after_state={"seq": "other-tenant"},
    )
    await integration_db_session.commit()

    items, total = await repo.list(
        tenant_id=tenant_a,
        actor_id=user_a,
        action="project.update",
        resource_type="project",
        resource_id=project_a,
        offset=0,
        limit=1,
    )
    assert total == 2
    assert [item.id for item in items] == [newer.id]

    resource_items, resource_total = await repo.list_by_resource(
        "project",
        project_a,
        offset=0,
        limit=10,
    )
    assert resource_total == 2
    assert {item.id for item in resource_items} == {older.id, newer.id}

    assert await repo.has_cross_tenant_match(
        tenant_id=tenant_a,
        actor_id=user_b,
        resource_type="project",
        resource_id=project_b,
    )
    assert not await repo.has_cross_tenant_match(tenant_id=tenant_a)


@pytest.mark.asyncio
async def test_audit_retention_hard_deletes_only_events_older_than_cutoff(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import AuditEvent
    from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository

    repo = AuditEventRepository(integration_db_session)
    tenant_id = seed_run["tenant"].id
    user_id = seed_run["user"].id
    project_id = seed_run["project"].id
    cutoff = datetime.now(timezone.utc) - timedelta(days=365)

    old_event = await repo.create(
        tenant_id=tenant_id,
        user_id=user_id,
        action="retention.old",
        resource_type="project",
        resource_id=project_id,
        after_state={"age": "old"},
    )
    old_event.created_at = cutoff - timedelta(days=35)
    old_system_event = await repo.create(
        tenant_id=None,
        user_id=None,
        action="retention.old_system",
        resource_type="system",
        after_state={"age": "old"},
    )
    old_system_event.created_at = cutoff - timedelta(days=35)
    recent_event = await repo.create(
        tenant_id=tenant_id,
        user_id=user_id,
        action="retention.recent",
        resource_type="project",
        resource_id=project_id,
        after_state={"age": "recent"},
    )
    recent_event.created_at = cutoff + timedelta(days=364)
    await integration_db_session.commit()

    eligible_before = await _count_rows(
        integration_db_session,
        AuditEvent,
        AuditEvent.created_at < cutoff,
    )
    deleted = await repo.delete_older_than(cutoff=cutoff)
    await integration_db_session.commit()

    assert eligible_before == 2
    assert deleted == eligible_before
    assert (
        await _count_rows(
            integration_db_session,
            AuditEvent,
            AuditEvent.id == old_event.id,
        )
        == 0
    )
    assert (
        await _count_rows(
            integration_db_session,
            AuditEvent,
            AuditEvent.id == old_system_event.id,
        )
        == 0
    )
    assert (
        await _count_rows(
            integration_db_session,
            AuditEvent,
            AuditEvent.id == recent_event.id,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_user_repository_scopes_soft_delete_and_recovers_from_unique_violation(
    integration_db_session,
    seed_run,
    seed_second_tenant,
):
    from qaplatform.infra.database.models import AppUser
    from qaplatform.infra.database.repositories.user_repo import UserRepository

    repo = UserRepository(integration_db_session)
    suffix = uuid4().hex[:8]
    tenant_a = seed_run["tenant"].id
    tenant_b = seed_second_tenant["tenant"].id
    shared_username = f"shared_{suffix}"
    email_a = f"shared-{suffix}@example.com"
    email_b = f"shared-b-{suffix}@example.com"

    user_a = await repo.create(
        tenant_id=tenant_a,
        username=shared_username,
        email=email_a,
        password_hash="argon2:placeholder",
        role="member",
        is_platform_admin=False,
        is_active=True,
    )
    user_b = await repo.create(
        tenant_id=tenant_b,
        username=shared_username,
        email=email_b,
        password_hash="argon2:placeholder",
        role="member",
        is_platform_admin=False,
        is_active=True,
    )
    await integration_db_session.commit()

    assert (await repo.get_by_username(tenant_a, shared_username)).id == user_a.id
    assert (await repo.get_by_username(tenant_b, shared_username)).id == user_b.id
    assert (await repo.get_by_email(tenant_a, email_a)).id == user_a.id

    users, total = await repo.list_by_tenant(tenant_a, offset=0, limit=1)
    assert total == 2
    assert [
        {
            "id": user.id,
            "tenant_id": user.tenant_id,
            "username": user.username,
            "email": user.email,
        }
        for user in users
    ] == [
        {
            "id": user_a.id,
            "tenant_id": tenant_a,
            "username": shared_username,
            "email": email_a,
        }
    ]

    await repo.delete(user_a)
    await integration_db_session.commit()
    assert await repo.get_by_username(tenant_a, shared_username) is None
    assert (await repo.get_by_username(tenant_b, shared_username)).id == user_b.id

    integration_db_session.add(
        AppUser(
            tenant_id=tenant_b,
            username=shared_username,
            email=f"dupe-{suffix}@example.com",
            password_hash="argon2:placeholder",
            role="member",
            is_platform_admin=False,
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        await integration_db_session.commit()
    _assert_integrity_constraint(exc_info.value, "uq_app_user_tenant_username")

    await integration_db_session.rollback()
    assert (
        await _count_rows(
            integration_db_session,
            AppUser,
            AppUser.tenant_id == tenant_b,
            AppUser.username == shared_username,
        )
        == 1
    )
    recovered = await repo.create(
        tenant_id=tenant_a,
        username=f"recovered_{suffix}",
        email=f"recovered-{suffix}@example.com",
        password_hash="argon2:placeholder",
        role="viewer",
        is_platform_admin=False,
        is_active=True,
    )
    await integration_db_session.commit()
    assert recovered.id is not None


@pytest.mark.asyncio
async def test_run_retention_hard_delete_cascades_results_artifacts_and_events(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import (
        Artifact,
        Run,
        RunEvent,
        RunStatusEnum,
        TestResult,
        TestResultStatusEnum,
    )
    from qaplatform.infra.database.repositories.run_repo import (
        ArtifactRepository,
        RunRepository,
        TestResultRepository,
    )

    run = seed_run["run"]
    run_repo = RunRepository(integration_db_session)
    result_repo = TestResultRepository(integration_db_session)
    artifact_repo = ArtifactRepository(integration_db_session)

    project_runs, project_total = await run_repo.list_by_project(
        run.project_id,
        offset=0,
        limit=1,
    )
    assert project_total == 1
    assert [
        {
            "id": item.id,
            "tenant_id": item.tenant_id,
            "project_id": item.project_id,
            "pipeline_id": item.pipeline_id,
        }
        for item in project_runs
    ] == [
        {
            "id": run.id,
            "tenant_id": run.tenant_id,
            "project_id": run.project_id,
            "pipeline_id": run.pipeline_id,
        }
    ]
    pipeline_runs, pipeline_total = await run_repo.list_by_pipeline(
        run.pipeline_id,
        offset=0,
        limit=10,
    )
    assert pipeline_total == 1
    assert [item.id for item in pipeline_runs] == [run.id]

    await result_repo.bulk_create(
        [
            {
                "run_id": run.id,
                "suite": "retention",
                "name": "test_old_result",
                "status": TestResultStatusEnum.PASSED,
                "duration_ms": 7,
                "tags": [],
                "metadata_": {},
            }
        ]
    )
    artifact = await artifact_repo.create(
        run_id=run.id,
        type="log",
        name="stdout.txt",
        storage_path=f"runs/{run.id}/stdout.txt",
        size_bytes=32,
        mime_type="text/plain",
    )
    event = RunEvent(run_id=run.id, type="log", payload={"message": "done"})
    integration_db_session.add(event)

    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    old_finished_at = cutoff - timedelta(days=29)
    await run_repo.update(run, status=RunStatusEnum.DONE, finished_at=old_finished_at)
    await run_repo.delete(run)

    old_failed = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.FAILED,
        git_ref=f"old-failed-{uuid4().hex}",
    )
    old_failed.finished_at = old_finished_at
    old_cancelled = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.CANCELLED,
        git_ref=f"old-cancelled-{uuid4().hex}",
    )
    old_cancelled.finished_at = old_finished_at
    old_timeout = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.TIMEOUT,
        git_ref=f"old-timeout-{uuid4().hex}",
    )
    old_timeout.finished_at = old_finished_at
    recent_done = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.DONE,
        git_ref=f"recent-done-{uuid4().hex}",
    )
    recent_done.finished_at = cutoff + timedelta(hours=12)
    active_queued = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref=f"active-queued-{uuid4().hex}",
    )
    await integration_db_session.commit()

    eligible_run_ids = {run.id, old_failed.id, old_cancelled.id, old_timeout.id}
    retained_run_ids = {recent_done.id, active_queued.id}
    terminal_statuses = [
        RunStatusEnum.DONE,
        RunStatusEnum.FAILED,
        RunStatusEnum.CANCELLED,
        RunStatusEnum.TIMEOUT,
    ]
    eligible_before = await _count_rows(
        integration_db_session,
        Run,
        Run.status.in_(terminal_statuses),
        Run.finished_at < cutoff,
    )
    assert eligible_before == len(eligible_run_ids)

    assert await _count_rows(integration_db_session, Run, Run.id == run.id) == 1
    assert await _count_rows(
        integration_db_session,
        TestResult,
        TestResult.run_id == run.id,
    ) == 1
    assert await _count_rows(
        integration_db_session,
        Artifact,
        Artifact.id == artifact.id,
    ) == 1
    assert await _count_rows(
        integration_db_session,
        RunEvent,
        RunEvent.run_id == run.id,
    ) == 1

    deleted = await run_repo.delete_terminal_older_than(cutoff=cutoff)
    await integration_db_session.commit()

    assert deleted == eligible_before
    for deleted_run_id in eligible_run_ids:
        assert await _count_rows(integration_db_session, Run, Run.id == deleted_run_id) == 0
    for retained_run_id in retained_run_ids:
        assert await _count_rows(integration_db_session, Run, Run.id == retained_run_id) == 1
    assert await _count_rows(
        integration_db_session,
        TestResult,
        TestResult.run_id == run.id,
    ) == 0
    assert await _count_rows(
        integration_db_session,
        Artifact,
        Artifact.id == artifact.id,
    ) == 0
    assert await _count_rows(
        integration_db_session,
        RunEvent,
        RunEvent.run_id == run.id,
    ) == 0


@pytest.mark.asyncio
async def test_run_repository_state_machine_persists_all_terminal_paths(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    repo = RunRepository(integration_db_session)

    happy = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref="state-happy",
    )
    await integration_db_session.commit()

    claimed = await repo.claim_for_worker(happy.id, worker_id="worker-state")
    assert claimed is not None
    assert claimed.status == RunStatusEnum.PREPARING
    assert claimed.worker_id == "worker-state"

    assert await repo.mark_running(happy.id) is True
    await integration_db_session.refresh(claimed)
    assert claimed.status == RunStatusEnum.RUNNING
    assert claimed.started_at is not None

    assert await repo.mark_collecting(happy.id) is True
    await integration_db_session.refresh(claimed)
    assert claimed.status == RunStatusEnum.COLLECTING

    assert await repo.finish_if_current(happy.id, status=RunStatusEnum.DONE) is True
    await integration_db_session.refresh(claimed)
    assert claimed.status == RunStatusEnum.DONE
    assert claimed.finished_at is not None

    failed = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref="state-failed",
    )
    cancelled = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref="state-cancelled",
    )
    timed_out = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.RUNNING,
        git_ref="state-timeout",
    )
    await integration_db_session.commit()

    assert await repo.fail_if_current(failed.id, message="container failed") is True
    await integration_db_session.refresh(failed)
    assert failed.status == RunStatusEnum.FAILED
    assert failed.error_message == "container failed"
    assert failed.finished_at is not None

    assert await repo.cancel_if_current(cancelled.id) is True
    await integration_db_session.refresh(cancelled)
    assert cancelled.status == RunStatusEnum.CANCELLED
    assert cancelled.cancel_requested_at is not None
    assert cancelled.finished_at is not None

    assert await repo.timeout_if_current(
        timed_out.id,
        expected_in={RunStatusEnum.RUNNING},
    ) is True
    await integration_db_session.refresh(timed_out)
    assert timed_out.status == RunStatusEnum.TIMEOUT
    assert timed_out.finished_at is not None


@pytest.mark.asyncio
async def test_run_repository_state_writes_ignore_soft_deleted_runs(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    repo = RunRepository(integration_db_session)
    now = datetime.now(timezone.utc)

    queued = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref="soft-deleted-queued",
    )
    preparing = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.PREPARING,
        git_ref="soft-deleted-preparing",
    )
    running = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.RUNNING,
        git_ref="soft-deleted-running",
    )
    collecting = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.COLLECTING,
        git_ref="soft-deleted-collecting",
    )
    failed_candidate = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref="soft-deleted-fail",
    )
    cancelled_candidate = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref="soft-deleted-cancel",
    )
    timeout_candidate = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.RUNNING,
        git_ref="soft-deleted-timeout",
    )
    worker_lost = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.RUNNING,
        git_ref="soft-deleted-worker-lost",
    )
    worker_lost.worker_id = "worker-lost"
    metadata_candidate = await _create_run_for_state(
        integration_db_session,
        seed_run,
        status=RunStatusEnum.QUEUED,
        git_ref="soft-deleted-metadata",
    )
    metadata_candidate.worker_id = "worker-release"

    for run in [
        queued,
        preparing,
        running,
        collecting,
        failed_candidate,
        cancelled_candidate,
        timeout_candidate,
        worker_lost,
        metadata_candidate,
    ]:
        run.deleted_at = now
    await integration_db_session.commit()
    await integration_db_session.refresh(metadata_candidate)
    original_metadata_updated_at = metadata_candidate.updated_at

    assert await repo.claim_for_worker(queued.id, worker_id="worker-claim") is None
    assert await repo.mark_running(preparing.id) is False
    assert await repo.mark_collecting(running.id) is False
    assert await repo.finish_if_current(collecting.id, status=RunStatusEnum.DONE) is False
    assert await repo.fail_if_current(failed_candidate.id, message="should not persist") is False
    assert await repo.cancel_if_current(cancelled_candidate.id) is False
    assert await repo.timeout_if_current(
        timeout_candidate.id,
        expected_in={RunStatusEnum.RUNNING},
    ) is False
    assert await repo.mark_worker_lost(
        worker_lost.id,
        worker_id="worker-lost",
        message="lost heartbeat",
    ) is False

    await repo.set_retry_group_id(metadata_candidate.id, queued.id)
    await repo.mark_enqueued(
        metadata_candidate.id,
        queue_name="queue:high",
        arq_job_id="job-soft-deleted",
        enqueued_at=now,
    )
    await repo.mark_waiting(metadata_candidate.id)
    await repo.update_git_sha(metadata_candidate.id, "f" * 40)
    await repo.update_execution_id(metadata_candidate.id, "exec-soft-deleted")
    await repo.release_worker(metadata_candidate.id, worker_id="worker-release")

    for run, expected_status in [
        (queued, RunStatusEnum.QUEUED),
        (preparing, RunStatusEnum.PREPARING),
        (running, RunStatusEnum.RUNNING),
        (collecting, RunStatusEnum.COLLECTING),
        (failed_candidate, RunStatusEnum.QUEUED),
        (cancelled_candidate, RunStatusEnum.QUEUED),
        (timeout_candidate, RunStatusEnum.RUNNING),
        (worker_lost, RunStatusEnum.RUNNING),
    ]:
        await integration_db_session.refresh(run)
        assert run.status == expected_status
        assert run.finished_at is None

    await integration_db_session.refresh(metadata_candidate)
    assert metadata_candidate.retry_group_id is None
    assert metadata_candidate.queue_name is None
    assert metadata_candidate.arq_job_id is None
    assert metadata_candidate.enqueued_at is None
    assert metadata_candidate.git_sha is None
    assert metadata_candidate.execution_id is None
    assert metadata_candidate.worker_id == "worker-release"
    assert metadata_candidate.updated_at == original_metadata_updated_at


@pytest.mark.asyncio
async def test_schedule_repository_due_query_ignores_soft_deleted_schedules(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Schedule
    from qaplatform.infra.database.repositories.project_repo import ScheduleRepository

    now = datetime.now(timezone.utc)

    visible_due = Schedule(
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        cron_expr="*/5 * * * *",
        timezone="UTC",
        missed_fire_policy="run_once",
        quiet_windows=[],
        enabled=True,
        next_run_at=now - timedelta(minutes=1),
    )
    deleted_due = Schedule(
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        cron_expr="*/5 * * * *",
        timezone="UTC",
        missed_fire_policy="run_once",
        quiet_windows=[],
        enabled=True,
        next_run_at=now - timedelta(minutes=2),
        deleted_at=now,
    )
    future = Schedule(
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        cron_expr="*/5 * * * *",
        timezone="UTC",
        missed_fire_policy="run_once",
        quiet_windows=[],
        enabled=True,
        next_run_at=now + timedelta(minutes=5),
    )
    integration_db_session.add_all([visible_due, deleted_due, future])
    await integration_db_session.commit()

    due = await ScheduleRepository(integration_db_session).find_due_schedules(now, limit=50)

    assert [schedule.id for schedule in due] == [visible_due.id]


@pytest.mark.asyncio
async def test_result_and_artifact_repositories_query_paginate_and_recover(
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import TestResultStatusEnum
    from qaplatform.infra.database.repositories.run_repo import (
        ArtifactRepository,
        TestResultRepository,
    )

    run_id = seed_run["run"].id
    result_repo = TestResultRepository(integration_db_session)
    artifact_repo = ArtifactRepository(integration_db_session)

    results = await result_repo.bulk_create(
        [
            {
                "run_id": run_id,
                "suite": "repo",
                "name": "test_alpha",
                "status": TestResultStatusEnum.PASSED,
                "duration_ms": 10,
                "tags": ["fast"],
                "metadata_": {"shard": 1},
            },
            {
                "run_id": run_id,
                "suite": "repo",
                "name": "test_beta",
                "status": TestResultStatusEnum.FAILED,
                "duration_ms": 20,
                "tags": ["slow"],
                "metadata_": {"shard": 2},
            },
            {
                "run_id": run_id,
                "suite": "repo",
                "name": "test_gamma",
                "status": TestResultStatusEnum.ERROR,
                "duration_ms": 30,
                "tags": [],
                "metadata_": {},
            },
        ]
    )
    now = datetime.now(timezone.utc)
    for index, result in enumerate(results):
        result.created_at = now - timedelta(minutes=index)
    await integration_db_session.commit()

    page, result_total = await result_repo.list_by_run(run_id, offset=0, limit=2)
    assert result_total == 3
    assert [item.name for item in page] == ["test_alpha", "test_beta"]

    failed = await result_repo.list_by_run_and_status(
        run_id,
        TestResultStatusEnum.FAILED.value,
    )
    assert [item.name for item in failed] == ["test_beta"]

    with pytest.raises(IntegrityError) as exc_info:
        await result_repo.bulk_create(
            [
                {
                    "run_id": run_id,
                    "suite": "repo",
                    "name": "test_beta",
                    "status": TestResultStatusEnum.PASSED,
                    "duration_ms": 1,
                    "tags": [],
                    "metadata_": {},
                }
            ]
        )
        await integration_db_session.commit()
    _assert_integrity_constraint(exc_info.value, "uq_test_result_run_suite_name")
    await integration_db_session.rollback()
    all_results, all_total = await result_repo.list_by_run(run_id, offset=0, limit=10)
    assert all_total == 3
    assert [item.name for item in all_results].count("test_beta") == 1

    first_artifact = await artifact_repo.create(
        run_id=run_id,
        type="log",
        name="first.log",
        storage_path=f"runs/{run_id}/first.log",
        size_bytes=10,
        mime_type="text/plain",
    )
    visible_artifact = await artifact_repo.create(
        run_id=run_id,
        type="report",
        name="report.html",
        storage_path=f"runs/{run_id}/report.html",
        size_bytes=20,
        mime_type="text/html",
    )
    trace_artifact = await artifact_repo.create(
        run_id=run_id,
        type="trace",
        name="trace.zip",
        storage_path=f"runs/{run_id}/trace.zip",
        size_bytes=30,
        mime_type="application/zip",
    )
    artifact_order_base = datetime.now(timezone.utc)
    first_artifact.created_at = artifact_order_base - timedelta(seconds=2)
    visible_artifact.created_at = artifact_order_base - timedelta(seconds=1)
    trace_artifact.created_at = artifact_order_base
    await artifact_repo.delete(first_artifact)
    await integration_db_session.commit()

    artifact_page, artifact_total = await artifact_repo.list_by_run(
        run_id,
        offset=0,
        limit=1,
    )
    assert artifact_total == 2
    assert [item.id for item in artifact_page] == [trace_artifact.id]
    assert (
        await artifact_repo.get_by_id(visible_artifact.id)
    ).name == "report.html"
