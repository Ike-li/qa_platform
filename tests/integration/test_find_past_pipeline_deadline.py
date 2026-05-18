"""集成测试：RunRepository.find_past_pipeline_deadline 按 pipeline.timeout_seconds 判定。

回归覆盖 P1-G：reclaim 的过期判断从硬编码 1800s 改为
  GREATEST(pipeline.timeout_seconds, 1800) + buffer_seconds

测试场景：
- pipeline.timeout_seconds=60，buffer_seconds=0（测试专用，消除时间抖动）
- run A：status_updated_at = now() - 100s  → 超过 (60+0)s，应被捞出
- run B：status_updated_at = now() - 30s   → 未超过，不应被捞出

Skipped by default; set RUN_INTEGRATION_TESTS=1 to enable.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from qaplatform.infra.database.models import (
    AppUser,
    Environment,
    Pipeline,
    Project,
    Run,
    RunStatusEnum,
    Tenant,
)
from qaplatform.infra.database.repositories.run_repo import RunRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


@pytest_asyncio.fixture
async def deadline_seed(integration_db_engine, integration_db_schema):
    """Seed a pipeline with timeout_seconds=60 and two runs at different ages."""
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(name=f"tenant-{uuid4().hex[:8]}")
        session.add(tenant)
        await session.flush()

        user = AppUser(
            tenant_id=tenant.id,
            username=f"u-{uuid4().hex[:8]}",
            email=f"u-{uuid4().hex[:8]}@test.local",
            password_hash="argon2:placeholder",
            role="owner",
            is_platform_admin=False,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        project = Project(
            tenant_id=tenant.id,
            name="deadline-test-project",
            slug=f"proj-{uuid4().hex[:8]}",
            git_url="file:///tmp/none",
            default_branch="main",
            root_path=".",
            shallow_clone=True,
            created_by=user.id,
        )
        session.add(project)
        await session.flush()

        environment = Environment(
            project_id=project.id,
            name="default",
            base_image="alpine:3.19",
            memory_mb=128,
            cpu_cores=0.5,
            network_policy="allow",
            env_vars={},
        )
        session.add(environment)
        await session.flush()

        # Pipeline with timeout_seconds=300 (< 1800 floor).
        # GREATEST(300, 1800) = 1800, so the effective deadline is 1800 + buffer.
        # This also validates the GREATEST floor logic.
        pipeline = Pipeline(
            project_id=project.id,
            name=f"deadline-pipe-{uuid4().hex[:8]}",
            stages=[{"name": "exec", "plugin": "pytest", "phase": "execute", "config": {}}],
            selector={},
            trigger_config={"type": "manual"},
            timeout_seconds=300,
            enabled=True,
        )
        session.add(pipeline)
        await session.flush()

        now = datetime.now(timezone.utc)

        # run_old: status_updated_at = now - 2000s → past deadline (GREATEST(300,1800)+0 = 1800s)
        run_old = Run(
            tenant_id=tenant.id,
            project_id=project.id,
            pipeline_id=pipeline.id,
            environment_id=environment.id,
            status=RunStatusEnum.RUNNING,
            trigger_type="manual",
            priority=1,
            triggered_by=user.id,
            git_ref="main",
            attempt=1,
            chain_depth=0,
            metadata_={},
        )
        session.add(run_old)
        await session.flush()

        # run_fresh: status_updated_at = now - 100s → within deadline (1800s floor)
        run_fresh = Run(
            tenant_id=tenant.id,
            project_id=project.id,
            pipeline_id=pipeline.id,
            environment_id=environment.id,
            status=RunStatusEnum.RUNNING,
            trigger_type="manual",
            priority=1,
            triggered_by=user.id,
            git_ref="main",
            attempt=1,
            chain_depth=0,
            metadata_={},
        )
        session.add(run_fresh)
        await session.flush()

        # Directly set status_updated_at via raw SQL to bypass ORM onupdate hooks
        await session.execute(
            text("UPDATE run SET status_updated_at = :ts WHERE id = :id"),
            {"ts": now - timedelta(seconds=2000), "id": run_old.id},
        )
        await session.execute(
            text("UPDATE run SET status_updated_at = :ts WHERE id = :id"),
            {"ts": now - timedelta(seconds=100), "id": run_fresh.id},
        )
        await session.commit()

        yield {
            "pipeline": pipeline,
            "run_old": run_old,
            "run_fresh": run_fresh,
        }


@pytest.mark.asyncio
async def test_find_past_pipeline_deadline_returns_only_overdue_run(
    deadline_seed, integration_db_engine
):
    """Only the run whose status_updated_at exceeds pipeline.timeout_seconds should be returned."""
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)

    run_old = deadline_seed["run_old"]
    run_fresh = deadline_seed["run_fresh"]

    async with factory() as session:
        repo = RunRepository(session)
        # buffer_seconds=0: no extra grace, purely tests the timeout_seconds logic
        overdue = await repo.find_past_pipeline_deadline(
            statuses=[RunStatusEnum.RUNNING],
            buffer_seconds=0,
        )

    overdue_ids = {r.id for r in overdue}
    assert run_old.id in overdue_ids, (
        "run_old (status_updated_at = now-2000s, GREATEST(300,1800)+0=1800s threshold) should be overdue"
    )
    assert run_fresh.id not in overdue_ids, (
        "run_fresh (status_updated_at = now-100s, threshold=1800s) should NOT be overdue"
    )


@pytest.mark.asyncio
async def test_find_past_pipeline_deadline_respects_buffer(
    deadline_seed, integration_db_engine
):
    """With buffer_seconds=300, threshold = GREATEST(300,1800)+300 = 2100s.
    run_old is 2000s old → NOT overdue (2000 < 2100).
    This verifies buffer_seconds shifts the cutoff correctly."""
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)

    run_old = deadline_seed["run_old"]

    async with factory() as session:
        repo = RunRepository(session)
        # threshold = GREATEST(300, 1800) + 300 = 2100s; run_old is 2000s old → not overdue
        overdue_with_buffer = await repo.find_past_pipeline_deadline(
            statuses=[RunStatusEnum.RUNNING],
            buffer_seconds=300,
        )

    overdue_ids = {r.id for r in overdue_with_buffer}
    # run_old is 2000s old, threshold is 2100s → NOT overdue with this buffer
    assert run_old.id not in overdue_ids, (
        "run_old (2000s ago) should NOT be overdue when buffer=300 raises threshold to 2100s"
    )
