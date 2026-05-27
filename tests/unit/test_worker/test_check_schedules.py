"""Tests for the check_schedules periodic worker task."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.worker.settings import check_schedules


@pytest.fixture
def ctx():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)
    return {
        "db_session_factory": factory,
        "arq_pool": MagicMock(),
        "settings": MagicMock(),
    }


@pytest.fixture
def sample_schedule():
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        pipeline_id=uuid4(),
        cron_expr="0 * * * *",
        timezone="Asia/Shanghai",
        enabled=True,
        quiet_windows=[],
        next_run_at=datetime.now(timezone.utc),
        last_run_at=None,
        last_error=None,
    )


def _patch_repos(
    schedule_repo=None,
    pipeline_repo=None,
    project_repo=None,
    env_repo=None,
    run_repo=None,
    audit_repo=None,
):
    """Return a list of patches for all repository classes used by check_schedules."""
    return [
        patch("qaplatform.infra.database.repositories.project_repo.ScheduleRepository", return_value=schedule_repo or AsyncMock()),
        patch("qaplatform.infra.database.repositories.project_repo.PipelineRepository", return_value=pipeline_repo or AsyncMock()),
        patch("qaplatform.infra.database.repositories.project_repo.ProjectRepository", return_value=project_repo or AsyncMock()),
        patch("qaplatform.infra.database.repositories.project_repo.EnvironmentRepository", return_value=env_repo or AsyncMock()),
        patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo or AsyncMock()),
        patch("qaplatform.infra.database.repositories.audit_repo.AuditEventRepository", return_value=audit_repo or AsyncMock()),
    ]


class TestCheckSchedules:
    """Tests for the check_schedules periodic task."""

    @pytest.mark.asyncio
    async def test_no_due_schedules(self, ctx):
        """When no schedules are due, the task exits early."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[])

        patches = _patch_repos(schedule_repo=schedule_repo)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            await check_schedules(ctx)

        schedule_repo.find_due_schedules.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fires_due_schedule(self, ctx, sample_schedule):
        """A due schedule should create a run and enqueue it."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock()

        pipeline = MagicMock()
        pipeline.project = MagicMock()
        pipeline.project.tenant_id = uuid4()
        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=pipeline)

        project = MagicMock()
        project.tenant_id = pipeline.project.tenant_id
        project.default_branch = "main"
        project.settings = {}
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(return_value=project)

        env = MagicMock()
        env.id = uuid4()
        env_repo = AsyncMock()
        env_repo.list_by_project = AsyncMock(return_value=([env], 1))

        run = MagicMock()
        run.id = uuid4()
        run.tenant_id = project.tenant_id
        run.project_id = sample_schedule.project_id
        run.pipeline_id = sample_schedule.pipeline_id
        run.environment_id = env.id
        run.status = "queued"
        run.trigger_type = "schedule"
        run.triggered_by = None
        run.git_ref = "main"
        run.git_sha = None
        run.priority = 2
        run.attempt = 1
        run.metadata_ = {"schedule_id": str(sample_schedule.id)}
        run.retry_group_id = None
        run_repo = AsyncMock()
        run_repo.create = AsyncMock(return_value=run)
        audit_repo = AsyncMock()
        audit_repo.create = AsyncMock()

        patches = _patch_repos(
            schedule_repo=schedule_repo,
            pipeline_repo=pipeline_repo,
            project_repo=project_repo,
            env_repo=env_repo,
            run_repo=run_repo,
            audit_repo=audit_repo,
        )
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4], patches[5],
            patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock, return_value=True) as mock_enqueue,
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True),
            patch("qaplatform.domain.services.scheduling.compute_next_run_at", return_value=datetime.now(timezone.utc)),
        ):
            await check_schedules(ctx)

        run_repo.create.assert_awaited_once()
        mock_enqueue.assert_awaited_once()
        schedule_repo.update_after_fire.assert_awaited_once()
        assert run.retry_group_id == run.id
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.call_args.kwargs
        assert audit_kwargs["tenant_id"] == project.tenant_id
        assert audit_kwargs["user_id"] is None
        assert audit_kwargs["action"] == "run.trigger"
        assert audit_kwargs["resource_type"] == "run"
        assert audit_kwargs["resource_id"] == run.id
        assert audit_kwargs["after_state"]["trigger_type"] == "schedule"
        assert audit_kwargs["after_state"]["schedule_id"] == str(sample_schedule.id)
        assert audit_kwargs["after_state"]["enqueued"] is True

    @pytest.mark.asyncio
    async def test_skips_in_quiet_window(self, ctx, sample_schedule):
        """Schedules in a quiet window should be skipped."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])

        patches = _patch_repos(schedule_repo=schedule_repo)
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4], patches[5],
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=False),
        ):
            await check_schedules(ctx)

        schedule_repo.update_after_fire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_pipeline_not_found(self, ctx, sample_schedule):
        """When pipeline is missing, update schedule with error and continue."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock()

        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=None)

        patches = _patch_repos(schedule_repo=schedule_repo, pipeline_repo=pipeline_repo)
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4], patches[5],
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True),
            patch("qaplatform.domain.services.scheduling.compute_next_run_at", return_value=datetime.now(timezone.utc)),
        ):
            await check_schedules(ctx)

        schedule_repo.update_after_fire.assert_awaited_once()
        call_kwargs = schedule_repo.update_after_fire.call_args.kwargs
        assert call_kwargs["last_error"] == "pipeline not found"

    @pytest.mark.asyncio
    async def test_handles_enqueue_failure(self, ctx, sample_schedule):
        """When enqueue fails, record the error on the schedule."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock()

        pipeline = MagicMock()
        pipeline.project = MagicMock()
        pipeline.project.tenant_id = uuid4()
        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=pipeline)

        project = MagicMock()
        project.tenant_id = pipeline.project.tenant_id
        project.default_branch = "main"
        project.settings = {}
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(return_value=project)

        env = MagicMock()
        env.id = uuid4()
        env_repo = AsyncMock()
        env_repo.list_by_project = AsyncMock(return_value=([env], 1))

        run = MagicMock()
        run.id = uuid4()
        run.tenant_id = project.tenant_id
        run.project_id = sample_schedule.project_id
        run.pipeline_id = sample_schedule.pipeline_id
        run.environment_id = env.id
        run.status = "queued"
        run.trigger_type = "schedule"
        run.triggered_by = None
        run.git_ref = "main"
        run.git_sha = None
        run.priority = 2
        run.attempt = 1
        run.metadata_ = {"schedule_id": str(sample_schedule.id)}
        run.retry_group_id = None
        run_repo = AsyncMock()
        run_repo.create = AsyncMock(return_value=run)
        audit_repo = AsyncMock()
        audit_repo.create = AsyncMock()

        patches = _patch_repos(
            schedule_repo=schedule_repo,
            pipeline_repo=pipeline_repo,
            project_repo=project_repo,
            env_repo=env_repo,
            run_repo=run_repo,
            audit_repo=audit_repo,
        )
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4], patches[5],
            patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock, return_value=False),
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True),
            patch("qaplatform.domain.services.scheduling.compute_next_run_at", return_value=datetime.now(timezone.utc)),
        ):
            await check_schedules(ctx)

        schedule_repo.update_after_fire.assert_awaited_once()
        call_kwargs = schedule_repo.update_after_fire.call_args.kwargs
        assert call_kwargs["last_error"] == "enqueue failed"
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.call_args.kwargs
        assert audit_kwargs["action"] == "run.trigger"
        assert audit_kwargs["resource_id"] == run.id
        assert audit_kwargs["after_state"]["trigger_type"] == "schedule"
        assert audit_kwargs["after_state"]["schedule_id"] == str(sample_schedule.id)
        assert audit_kwargs["after_state"]["enqueued"] is False

    @pytest.mark.asyncio
    async def test_no_session_factory(self):
        """When session_factory is None, exit early."""
        ctx = {"db_session_factory": None, "arq_pool": MagicMock(), "settings": MagicMock()}
        await check_schedules(ctx)  # should not raise

    @pytest.mark.asyncio
    async def test_no_arq_pool(self):
        """When arq_pool is None, exit early."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        ctx = {"db_session_factory": MagicMock(return_value=session), "arq_pool": None, "settings": MagicMock()}
        await check_schedules(ctx)  # should not raise
