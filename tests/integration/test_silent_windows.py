from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from qaplatform.worker.settings import check_schedules


class _FakeArq:
    async def enqueue_job(self, *_args, _job_id: str, **_kwargs):
        return SimpleNamespace(job_id=_job_id)


async def _save_silent_window(session, project, *, start_at: datetime, end_at: datetime) -> None:
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


async def _create_due_schedule(session, seed_run, *, next_run_at: datetime):
    from qaplatform.infra.database.models import Schedule

    schedule = Schedule(
        project_id=seed_run["project"].id,
        pipeline_id=seed_run["pipeline"].id,
        cron_expr="* * * * *",
        timezone="UTC",
        missed_fire_policy="skip",
        quiet_windows=[],
        enabled=True,
        next_run_at=next_run_at,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


def _ctx(integration_db_engine):
    return {
        "db_session_factory": async_sessionmaker(integration_db_engine, expire_on_commit=False),
        "arq_pool": _FakeArq(),
        "settings": SimpleNamespace(max_concurrent_runs=100, max_concurrent_per_project=100),
    }


async def _run_count(session, project_id, *, trigger_type: str) -> int:
    from qaplatform.infra.database.models import Run

    result = await session.execute(
        select(func.count()).select_from(Run).where(
            Run.project_id == project_id,
            Run.trigger_type == trigger_type,
        )
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_cron_tick_in_silent_window_skips_run_writes_audit_and_preserves_last_run_at(
    seed_run,
    integration_db_engine,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent, Schedule

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
        start_at=now - timedelta(minutes=5),
        end_at=now + timedelta(minutes=5),
    )
    before_runs = await _run_count(integration_db_session, project.id, trigger_type="schedule")

    await check_schedules(_ctx(integration_db_engine))

    assert await _run_count(integration_db_session, project.id, trigger_type="schedule") == before_runs

    refreshed = await integration_db_session.get(Schedule, schedule.id)
    assert refreshed is not None
    await integration_db_session.refresh(refreshed)
    assert refreshed.last_run_at is None

    result = await integration_db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "schedule_skipped_silent_window",
            AuditEvent.resource_id == schedule.id,
        )
    )
    event = result.scalars().one()
    assert event.after_state["schedule_id"] == str(schedule.id)
    assert event.after_state["window"]["reason"] == "Release freeze"


@pytest.mark.asyncio
async def test_cron_tick_outside_silent_window_creates_run(
    seed_run,
    integration_db_engine,
    integration_db_session,
):
    from qaplatform.infra.database.models import Schedule

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
    before_runs = await _run_count(integration_db_session, project.id, trigger_type="schedule")

    await check_schedules(_ctx(integration_db_engine))

    assert await _run_count(integration_db_session, project.id, trigger_type="schedule") == before_runs + 1
    refreshed = await integration_db_session.get(Schedule, schedule.id)
    assert refreshed is not None
    await integration_db_session.refresh(refreshed)
    assert refreshed.last_run_at is not None


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
    before_runs = await _run_count(integration_db_session, project.id, trigger_type="manual")

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"pipeline_id": str(seed_run["pipeline"].id), "git_ref": "main"},
        )

    assert resp.status_code == 201, resp.text
    assert await _run_count(integration_db_session, project.id, trigger_type="manual") == before_runs + 1


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
    before_runs = await _run_count(integration_db_session, project.id, trigger_type="webhook")

    async with integration_client_as(user.id, tenant.id, role="owner") as client:
        resp = await client.post(
            f"/api/v1/webhooks/{project.id}/trigger",
            json={"git_ref": "refs/heads/main", "git_sha": "silent-window-webhook"},
        )

    assert resp.status_code == 201, resp.text
    assert await _run_count(integration_db_session, project.id, trigger_type="webhook") == before_runs + 1
