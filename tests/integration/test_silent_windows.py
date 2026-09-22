from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from qaplatform.worker.settings import check_schedules


class _FakeArq:
    async def enqueue_job(self, *_args, _job_id: str, **_kwargs):
        return SimpleNamespace(job_id=_job_id)


class _ConflictArq:
    async def enqueue_job(self, *_args, _job_id: str, **_kwargs):
        return None

    async def close(self):
        return None


async def _save_silent_window(
    session, project, *, start_at: datetime, end_at: datetime
) -> None:
    project.settings = {
        "silent_windows": [
            {
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "reason": "Release freeze",
            }
        ]
    }
    await session.commit()
    await session.refresh(project)


async def _create_due_schedule(
    session,
    seed_run,
    *,
    next_run_at: datetime,
    cron_expr: str = "* * * * *",
    missed_fire_policy: str = "skip",
):
    from qaplatform.infra.database.models import Schedule

    schedule = Schedule(
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        cron_expr=cron_expr,
        timezone="UTC",
        missed_fire_policy=missed_fire_policy,
        quiet_windows=[],
        enabled=True,
        next_run_at=next_run_at,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


def _ctx(integration_db_engine, *, arq_pool=None):
    return {
        "db_session_factory": async_sessionmaker(
            integration_db_engine, expire_on_commit=False
        ),
        "arq_pool": arq_pool or _FakeArq(),
        "settings": SimpleNamespace(
            max_concurrent_runs=100, max_concurrent_per_project=100
        ),
    }


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _expected_trigger_run_response(
    body: dict,
    seed_run: dict,
    *,
    run_id: UUID,
    trigger_type: str,
    git_ref: str,
    git_sha: str | None,
) -> dict:
    return {
        "id": str(run_id),
        "tenant_id": str(seed_run["tenant"].id),
        "project_id": str(seed_run["project"].id),
        "pipeline_id": str(seed_run["pipeline"].id),
        "pipeline_name": seed_run["pipeline"].name,
        "environment_id": str(seed_run["environment"].id),
        "status": "queued",
        "trigger_type": trigger_type,
        "priority": 1,
        "triggered_by": str(seed_run["user"].id),
        "git_ref": git_ref,
        "git_sha": git_sha,
        "attempt": 1,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "summary": None,
        "error_message": None,
        "created_at": body["created_at"],
        "updated_at": body["updated_at"],
    }


async def _run_count(session, project_id, *, trigger_type: str) -> int:
    from qaplatform.infra.database.models import Run

    result = await session.execute(
        select(func.count())
        .select_from(Run)
        .where(
            Run.project_id == project_id,
            Run.trigger_type == trigger_type,
        )
    )
    return int(result.scalar_one())


async def _schedule_runs(session, project_id, schedule_id):
    from qaplatform.infra.database.models import Run

    runs = (
        (
            await session.execute(
                select(Run).where(
                    Run.project_id == project_id,
                    Run.trigger_type == "schedule",
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        run for run in runs if (run.metadata_ or {}).get("schedule_id") == str(schedule_id)
    ]


def _expected_schedule_metadata(project, schedule, *, scheduled_for=None) -> dict:
    """构造 schedule 触发出的 Run 应有的 metadata。

    ``scheduled_for`` 记录这个 Run 对应哪个 cron 槽——补跑多个槽时，它是区分
    各个 Run 的唯一线索。调用方通常不预先知道具体值（取决于宽限窗口内实际
    落在哪一格），传 ANY 之外的值时才做精确比较。
    """
    metadata = {
        "schedule_id": str(schedule.id),
        "git_url": project.git_url,
    }
    if scheduled_for is not None:
        metadata["scheduled_for"] = scheduled_for
    if project.git_auth_method != "none" and project.credential_id:
        metadata["git_auth_method"] = project.git_auth_method
        metadata["credential_id"] = str(project.credential_id)
    if project.shallow_clone:
        metadata["shallow_clone"] = True
    if project.default_branch:
        metadata["default_branch"] = project.default_branch
    return metadata


async def _run_by_id(session, run_id: UUID):
    from qaplatform.infra.database.models import Run

    return await session.get(Run, run_id)


async def _audit_event(session, *, action: str, resource_id: UUID):
    from qaplatform.infra.database.models import AuditEvent

    return (
        (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == action,
                    AuditEvent.resource_id == resource_id,
                )
            )
        )
        .scalars()
        .one_or_none()
    )


@pytest.mark.asyncio
async def test_project_update_api_persists_silent_windows_in_settings(
    seed_run,
    integration_client_as,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent

    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    project.settings = {
        "allowed_branches": ["main"],
        "webhook_secret": "existing-webhook-secret",
    }
    await integration_db_session.commit()
    await integration_db_session.refresh(project)
    before_updated_at = _json_datetime(project.updated_at)

    window = {
        "start_at": "2026-06-01T09:00:00+08:00",
        "end_at": "2026-06-01T11:00:00+08:00",
        "reason": "Release freeze",
    }
    # 库里应保留 webhook_secret（携带前移），但对外响应必须省略它
    expected_stored_settings = {
        "allowed_branches": ["main"],
        "webhook_secret": "existing-webhook-secret",
        "silent_windows": [window],
    }
    expected_response_settings = {
        "allowed_branches": ["main"],
        "silent_windows": [window],
    }

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.put(
            f"/api/v1/projects/{project.id}",
            json={"silent_windows": [window]},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "id": str(project.id),
        "tenant_id": str(tenant.id),
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "git_url": project.git_url,
        "git_auth_method": project.git_auth_method,
        "credential_id": None,
        "default_branch": project.default_branch,
        "root_path": project.root_path,
        "shallow_clone": project.shallow_clone,
        "default_env_id": None,
        "settings": expected_response_settings,
        "silent_windows": [window],
        "status": project.status,
        "created_by": str(user.id),
        "created_at": _json_datetime(project.created_at),
        "updated_at": body["updated_at"],
    }
    start_at = datetime.fromisoformat(body["silent_windows"][0]["start_at"])
    end_at = datetime.fromisoformat(body["silent_windows"][0]["end_at"])
    assert start_at == datetime(2026, 6, 1, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    assert end_at == datetime(2026, 6, 1, 11, 0, tzinfo=timezone(timedelta(hours=8)))

    await integration_db_session.refresh(project)
    assert project.settings == expected_stored_settings
    assert _json_datetime(project.updated_at) == body["updated_at"]

    result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "project.update",
            AuditEvent.resource_id == project.id,
        )
    )
    event = result.scalars().one()
    assert event.tenant_id == tenant.id
    assert event.user_id == user.id
    assert event.resource_type == "project"
    assert event.before_state == {
        **body,
        "settings": {
            "allowed_branches": ["main"],
            "webhook_secret": {"redacted": True},
        },
        "silent_windows": [],
        "updated_at": before_updated_at,
    }
    assert event.after_state == {
        **body,
        "settings": {
            "allowed_branches": ["main"],
            "webhook_secret": {"redacted": True},
            "silent_windows": [window],
        },
    }
    assert "existing-webhook-secret" not in repr(
        [event.before_state, event.after_state]
    )


@pytest.mark.asyncio
async def test_cron_tick_in_silent_window_skips_run_writes_audit_and_preserves_last_run_at(
    seed_run,
    integration_db_engine,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, Schedule

    now = datetime.now(timezone.utc)
    project = seed_run["project"]
    due_at = now - timedelta(minutes=1)
    schedule = await _create_due_schedule(
        integration_db_session,
        seed_run,
        next_run_at=due_at,
    )
    window_start = now - timedelta(minutes=5)
    window_end = now + timedelta(minutes=5)
    await _save_silent_window(
        integration_db_session,
        project,
        start_at=window_start,
        end_at=window_end,
    )
    before_runs = await _run_count(
        integration_db_session, project.id, trigger_type="schedule"
    )

    await check_schedules(_ctx(integration_db_engine))

    assert (
        await _run_count(integration_db_session, project.id, trigger_type="schedule")
        == before_runs
    )
    assert await _schedule_runs(integration_db_session, project.id, schedule.id) == []

    refreshed = await integration_db_session.get(Schedule, schedule.id)
    assert refreshed is not None
    await integration_db_session.refresh(refreshed)
    assert refreshed.last_run_at is None
    assert refreshed.last_error is None
    assert _json_datetime(refreshed.next_run_at) == _json_datetime(due_at)

    result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "schedule_skipped_silent_window",
            AuditEvent.resource_id == schedule.id,
        )
    )
    event = result.scalars().one()
    assert event.tenant_id == project.tenant_id
    assert event.user_id is None
    assert event.resource_type == "schedule"
    assert event.resource_id == schedule.id
    assert event.before_state is None
    assert event.after_state == {
        "schedule_id": str(schedule.id),
        "window": {
            "start_at": _json_datetime(window_start),
            "end_at": _json_datetime(window_end),
            "reason": "Release freeze",
        },
    }


@pytest.mark.asyncio
async def test_cron_tick_outside_silent_window_creates_run(
    seed_run,
    integration_db_engine,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, RunStatusEnum, Schedule

    now = datetime.now(timezone.utc)
    project = seed_run["project"]
    schedule = await _create_due_schedule(
        integration_db_session,
        seed_run,
        next_run_at=now - timedelta(minutes=1),
    )
    await _save_silent_window(
        integration_db_session,
        project,
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(hours=2),
    )
    before_runs = await _run_count(
        integration_db_session, project.id, trigger_type="schedule"
    )

    await check_schedules(_ctx(integration_db_engine))

    assert (
        await _run_count(integration_db_session, project.id, trigger_type="schedule")
        == before_runs + 1
    )
    refreshed = await integration_db_session.get(Schedule, schedule.id)
    assert refreshed is not None
    await integration_db_session.refresh(refreshed)
    assert refreshed.last_run_at is not None

    runs = await _schedule_runs(integration_db_session, project.id, schedule.id)
    assert len(runs) == 1
    # scheduled_for 取决于宽限窗口内实际落在哪个 cron 槽，只断言存在且可解析
    actual_metadata = dict(runs[0].metadata_)
    scheduled_for = actual_metadata.pop("scheduled_for", None)
    assert scheduled_for is not None
    assert datetime.fromisoformat(scheduled_for).tzinfo is not None
    assert "missed_fire" not in actual_metadata  # 宽限内的抖动不算补跑
    assert actual_metadata == _expected_schedule_metadata(project, schedule)
    # 审计记录的是 Run 的完整 metadata，含 scheduled_for
    expected_metadata = dict(runs[0].metadata_)
    run = runs[0]
    assert run.tenant_id == project.tenant_id
    assert run.project_id == project.id
    assert run.pipeline_id == seed_run["pipeline"].id
    assert run.environment_id == seed_run["environment"].id
    assert run.status == RunStatusEnum.QUEUED
    assert run.trigger_type == "schedule"
    assert run.triggered_by is None
    assert run.git_ref == project.default_branch
    assert run.git_sha is None
    assert run.retry_group_id == run.id
    assert run.attempt == 1
    assert run.queue_name == "queue:low"
    assert run.arq_job_id == f"run:{run.id}"
    assert run.enqueued_at is not None

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
    assert audit.resource_type == "run"
    assert audit.after_state == {
        "id": str(run.id),
        "tenant_id": str(project.tenant_id),
        "project_id": str(project.id),
        "pipeline_id": str(seed_run["pipeline"].id),
        "environment_id": str(seed_run["environment"].id),
        "status": "queued",
        "trigger_type": "schedule",
        "triggered_by": None,
        "git_ref": project.default_branch,
        "git_sha": None,
        "priority": run.priority,
        "attempt": 1,
        "metadata": expected_metadata,
        "schedule_id": str(schedule.id),
        "enqueued": True,
    }


@pytest.mark.asyncio
async def test_cron_tick_enqueue_conflict_records_last_error_and_waiting_run(
    seed_run,
    integration_db_engine,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, RunStatusEnum, Schedule

    now = datetime.now(timezone.utc)
    project = seed_run["project"]
    schedule = await _create_due_schedule(
        integration_db_session,
        seed_run,
        next_run_at=now - timedelta(minutes=1),
    )
    before_runs = await _run_count(
        integration_db_session, project.id, trigger_type="schedule"
    )

    await check_schedules(_ctx(integration_db_engine, arq_pool=_ConflictArq()))

    assert (
        await _run_count(integration_db_session, project.id, trigger_type="schedule")
        == before_runs + 1
    )
    refreshed = await integration_db_session.get(Schedule, schedule.id)
    assert refreshed is not None
    await integration_db_session.refresh(refreshed)
    assert refreshed.last_run_at is not None
    assert refreshed.last_error == "enqueue failed"

    created = await _schedule_runs(integration_db_session, project.id, schedule.id)
    assert len(created) == 1
    actual_metadata = dict(created[0].metadata_)
    scheduled_for = actual_metadata.pop("scheduled_for", None)
    assert scheduled_for is not None
    assert "missed_fire" not in actual_metadata
    assert actual_metadata == _expected_schedule_metadata(project, schedule)
    expected_metadata = dict(created[0].metadata_)
    waiting_run = created[0]
    assert waiting_run.tenant_id == project.tenant_id
    assert waiting_run.project_id == project.id
    assert waiting_run.pipeline_id == seed_run["pipeline"].id
    assert waiting_run.environment_id == seed_run["environment"].id
    assert waiting_run.status == RunStatusEnum.QUEUED
    assert waiting_run.trigger_type == "schedule"
    assert waiting_run.triggered_by is None
    assert waiting_run.git_ref == project.default_branch
    assert waiting_run.git_sha is None
    assert waiting_run.retry_group_id == waiting_run.id
    assert waiting_run.attempt == 1
    assert waiting_run.enqueued_at is None
    assert waiting_run.queue_name is None
    assert waiting_run.arq_job_id is None

    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "run.trigger",
                    AuditEvent.resource_id == waiting_run.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.user_id is None
    assert audit.after_state == {
        "id": str(waiting_run.id),
        "tenant_id": str(project.tenant_id),
        "project_id": str(project.id),
        "pipeline_id": str(seed_run["pipeline"].id),
        "environment_id": str(seed_run["environment"].id),
        "status": "queued",
        "trigger_type": "schedule",
        "triggered_by": None,
        "git_ref": project.default_branch,
        "git_sha": None,
        "priority": waiting_run.priority,
        "attempt": 1,
        "metadata": expected_metadata,
        "schedule_id": str(schedule.id),
        "enqueued": False,
    }


@pytest.mark.asyncio
async def test_cron_tick_soft_deleted_pipeline_records_audit_without_run(
    seed_run,
    integration_db_engine,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, Schedule

    now = datetime.now(timezone.utc)
    project = seed_run["project"]
    pipeline = seed_run["pipeline"]
    schedule = await _create_due_schedule(
        integration_db_session,
        seed_run,
        next_run_at=now - timedelta(minutes=1),
    )
    before_runs = await _run_count(
        integration_db_session, project.id, trigger_type="schedule"
    )
    pipeline.deleted_at = now
    await integration_db_session.commit()

    await check_schedules(_ctx(integration_db_engine))

    assert (
        await _run_count(integration_db_session, project.id, trigger_type="schedule")
        == before_runs
    )
    refreshed = await integration_db_session.get(Schedule, schedule.id)
    assert refreshed is not None
    await integration_db_session.refresh(refreshed)
    assert refreshed.last_run_at is not None
    assert refreshed.last_error == "pipeline not found"
    assert refreshed.next_run_at is not None

    audit = (
        (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "schedule_skipped_missing_pipeline",
                    AuditEvent.resource_id == schedule.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.tenant_id == project.tenant_id
    assert audit.user_id is None
    assert audit.resource_type == "schedule"
    assert audit.after_state == {
        "schedule_id": str(schedule.id),
        "project_id": str(project.id),
        "pipeline_id": str(pipeline.id),
        "status": "skipped",
        "reason": "pipeline_not_found",
        "last_error": "pipeline not found",
        "next_run_at": refreshed.next_run_at.isoformat(),
    }


@pytest.mark.asyncio
async def test_manual_trigger_ignores_silent_windows(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    now = datetime.now(timezone.utc)
    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    await _save_silent_window(
        integration_db_session,
        project,
        start_at=now - timedelta(minutes=5),
        end_at=now + timedelta(minutes=5),
    )
    before_runs = await _run_count(
        integration_db_session, project.id, trigger_type="manual"
    )

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"pipeline_id": str(seed_run["pipeline"].id), "git_ref": "main"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    run_id = UUID(body["id"])
    assert body == _expected_trigger_run_response(
        body,
        seed_run,
        run_id=run_id,
        trigger_type="manual",
        git_ref="main",
        git_sha=None,
    )
    assert (
        await _run_count(integration_db_session, project.id, trigger_type="manual")
        == before_runs + 1
    )

    created = await _run_by_id(integration_db_session, run_id)
    assert created is not None
    assert created.trigger_type == "manual"
    assert created.triggered_by == user.id
    assert created.pipeline_id == seed_run["pipeline"].id
    assert created.environment_id == seed_run["environment"].id
    assert created.git_ref == "main"
    assert created.git_sha is None
    assert created.retry_group_id == created.id
    assert created.enqueued_at is None
    assert created.arq_job_id is None
    assert created.metadata_["git_url"] == project.git_url
    assert created.metadata_["default_branch"] == project.default_branch

    audit = await _audit_event(
        integration_db_session, action="run.trigger", resource_id=run_id
    )
    assert audit is not None
    assert audit.tenant_id == tenant.id
    assert audit.user_id == user.id
    assert audit.resource_type == "run"
    assert audit.before_state is None
    assert audit.after_state == body


@pytest.mark.asyncio
async def test_webhook_trigger_ignores_silent_windows(
    seed_run,
    integration_app,
    integration_client_as,
    integration_db_session,
):
    now = datetime.now(timezone.utc)
    project = seed_run["project"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]
    integration_app.state.container.arq_pool = None
    await _save_silent_window(
        integration_db_session,
        project,
        start_at=now - timedelta(minutes=5),
        end_at=now + timedelta(minutes=5),
    )
    before_runs = await _run_count(
        integration_db_session, project.id, trigger_type="webhook"
    )

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "silent-window-webhook"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    run_id = UUID(body["id"])
    assert body == _expected_trigger_run_response(
        body,
        seed_run,
        run_id=run_id,
        trigger_type="webhook",
        git_ref="refs/heads/main",
        git_sha="silent-window-webhook",
    )
    assert (
        await _run_count(integration_db_session, project.id, trigger_type="webhook")
        == before_runs + 1
    )

    created = await _run_by_id(integration_db_session, run_id)
    assert created is not None
    assert created.trigger_type == "webhook"
    assert created.triggered_by == user.id
    assert created.pipeline_id == seed_run["pipeline"].id
    assert created.environment_id == seed_run["environment"].id
    assert created.git_ref == "refs/heads/main"
    assert created.git_sha == "silent-window-webhook"
    assert created.dedup_key == f"webhook:{project.git_url}:silent-window-webhook:main"
    assert created.retry_group_id == created.id
    assert created.enqueued_at is None
    assert created.arq_job_id is None
    assert created.metadata_["git_url"] == project.git_url
    assert created.metadata_["default_branch"] == project.default_branch

    audit = await _audit_event(
        integration_db_session, action="run.trigger", resource_id=run_id
    )
    assert audit is not None
    assert audit.tenant_id == tenant.id
    assert audit.user_id == user.id
    assert audit.resource_type == "run"
    assert audit.before_state is None
    assert audit.after_state == body


@pytest.mark.parametrize(
    ("policy", "expected_runs"),
    # 落后三小时的整点 cron：到期槽本身 + 之后每小时一个，共四个
    [("skip", 0), ("run_once", 1), ("run_all", 4)],
)
@pytest.mark.asyncio
async def test_missed_fire_policy_decides_how_many_catchup_runs(
    seed_run,
    integration_db_engine,
    integration_db_session,
    policy,
    expected_runs,
):
    """停机三小时后恢复，三种策略给出三种不同的补跑数量。

    missed_fire_policy 此前落库却从不被读取：不论停机多久、配的是哪种策略，
    恢复后都只补跑一次。这是本次唯一会改变存量 schedule 行为的改动——默认值
    是 skip，而 skip 现在真的一个都不补。
    """
    from qaplatform.infra.database.models import Schedule
    from qaplatform.worker.settings import check_schedules

    now = datetime.now(timezone.utc)
    # 整点 cron + 落后三小时：错过 12:00 / 13:00 / 14:00 三个槽
    schedule = await _create_due_schedule(
        integration_db_session,
        seed_run,
        cron_expr="0 * * * *",
        missed_fire_policy=policy,
        next_run_at=(now - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0),
    )

    await check_schedules(_ctx(integration_db_engine))

    runs = await _schedule_runs(
        integration_db_session, seed_run["project"].id, schedule.id
    )
    assert len(runs) == expected_runs

    # 无论补跑几个，next_run_at 都必须越过 now：只前进一格会让 schedule 一直
    # 处于 due 状态，下个 tick 又捞到它，长停机下变成活锁
    refreshed = await integration_db_session.get(Schedule, schedule.id)
    await integration_db_session.refresh(refreshed)
    assert refreshed.next_run_at > now

    # 补跑出来的 Run 都要能看出是哪一次错过的
    for run in runs:
        assert run.metadata_["missed_fire"] is True
        assert run.metadata_["scheduled_for"]
    if expected_runs > 1:
        slots = sorted(run.metadata_["scheduled_for"] for run in runs)
        assert len(set(slots)) == expected_runs
