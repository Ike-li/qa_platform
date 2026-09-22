"""Tests for the check_schedules periodic worker task."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
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
        missed_fire_policy="run_once",
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
        due_at = schedule_repo.find_due_schedules.await_args.args[0]
        assert due_at.tzinfo is not None
        assert due_at.utcoffset() is not None

    @pytest.mark.asyncio
    async def test_fires_due_schedule(self, ctx, sample_schedule):
        """A due schedule should create a run and enqueue it."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock(return_value=True)

        pipeline = MagicMock()
        pipeline.project = MagicMock()
        pipeline.project.tenant_id = uuid4()
        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=pipeline)

        project = MagicMock()
        project.tenant_id = pipeline.project.tenant_id
        project.git_url = "https://github.com/org/repo.git"
        project.git_auth_method = "none"
        project.credential_id = None
        project.shallow_clone = True
        project.default_branch = "main"
        project.default_env_id = None
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
        operations = []

        async def _create_run(**kwargs):
            operations.append(("create_run", kwargs))
            return run

        async def _set_retry_group(*args):
            operations.append(("set_retry_group", args))

        async def _update_after_fire(*args, **kwargs):
            operations.append(("update_after_fire", args, kwargs))
            # 返回值表示是否抢到该触发槽；返回 None 等同于抢输，会让后续
            # 的 Run 创建被跳过
            return True

        async def _audit_create(**kwargs):
            operations.append(("audit_create", kwargs))

        async def _enqueue(*args):
            operations.append(("enqueue", args))
            return True

        async def _commit():
            operations.append(("commit", None))

        run_repo.create = AsyncMock(side_effect=_create_run)
        run_repo.set_retry_group_id = AsyncMock(side_effect=_set_retry_group)
        audit_repo = AsyncMock()
        audit_repo.create = AsyncMock(side_effect=_audit_create)
        schedule_repo.update_after_fire = AsyncMock(side_effect=_update_after_fire)
        ctx_session = ctx["db_session_factory"].return_value.__aenter__.return_value
        ctx_session.commit.side_effect = _commit

        next_run_at = datetime.now(timezone.utc)
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
            patch("qaplatform.worker.scheduler.enqueue_run", AsyncMock(side_effect=_enqueue)) as mock_enqueue,
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True),
            patch("qaplatform.domain.services.scheduling.compute_next_run_at", return_value=next_run_at),
        ):
            await check_schedules(ctx)

        pipeline_repo.get_by_id.assert_awaited_once_with(sample_schedule.pipeline_id)
        project_repo.get_by_id.assert_awaited_once_with(sample_schedule.project_id)
        env_repo.list_by_project.assert_awaited_once_with(sample_schedule.project_id, limit=1)
        run_repo.create.assert_awaited_once_with(
            tenant_id=project.tenant_id,
            project_id=sample_schedule.project_id,
            pipeline_id=sample_schedule.pipeline_id,
            environment_id=env.id,
            git_ref="main",
            trigger_type="schedule",
            metadata_={
                "schedule_id": str(sample_schedule.id),
                "git_url": "https://github.com/org/repo.git",
                "shallow_clone": True,
                "default_branch": "main",
                # 记录这个 Run 对应哪个 cron 槽，补跑时才能看出是哪一次错过的
                "scheduled_for": sample_schedule.next_run_at.isoformat(),
            },
        )
        run_kwargs = run_repo.create.await_args.kwargs
        assert run_kwargs["tenant_id"] == project.tenant_id
        assert run_kwargs["project_id"] == sample_schedule.project_id
        assert run_kwargs["pipeline_id"] == sample_schedule.pipeline_id
        assert run_kwargs["environment_id"] == env.id
        assert run_kwargs["git_ref"] == "main"
        assert run_kwargs["trigger_type"] == "schedule"
        mock_enqueue.assert_awaited_once_with(
            ctx["arq_pool"],
            run_repo,
            run,
            "schedule",
            ctx["settings"],
        )
        schedule_repo.update_after_fire.assert_awaited_once()
        update_args = schedule_repo.update_after_fire.await_args
        assert update_args.args == (sample_schedule.id,)
        assert update_args.kwargs["last_run_at"].tzinfo is not None
        assert update_args.kwargs["next_run_at"] == next_run_at
        assert update_args.kwargs["last_error"] is None
        run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.await_args.kwargs
        assert audit_kwargs["tenant_id"] == project.tenant_id
        assert audit_kwargs["user_id"] is None
        assert audit_kwargs["action"] == "run.trigger"
        assert audit_kwargs["resource_type"] == "run"
        assert audit_kwargs["resource_id"] == run.id
        assert audit_kwargs["after_state"]["trigger_type"] == "schedule"
        assert audit_kwargs["after_state"]["schedule_id"] == str(sample_schedule.id)
        assert audit_kwargs["after_state"]["enqueued"] is True
        # 抢槽在建 Run 之前：条件 UPDATE 先把 next_run_at 推走，抢到了才创建。
        # 反过来（先建 Run 后推进）会在 enqueue 崩溃时重复触发——对回归调度器
        # 来说，丢一个周期是比重复一个周期更好的失败模式。
        assert [operation[0] for operation in operations] == [
            "update_after_fire",
            "commit",
            "create_run",
            "set_retry_group",
            "commit",
            "enqueue",
            "audit_create",
            "commit",
        ]

    @pytest.mark.asyncio
    async def test_fires_due_schedule_uses_project_default_environment(
        self,
        ctx,
        sample_schedule,
    ):
        """Project default environment takes precedence over fallback lookup."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock(return_value=True)

        pipeline = MagicMock()
        pipeline.project = MagicMock()
        pipeline.project.tenant_id = uuid4()
        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=pipeline)

        default_env_id = uuid4()
        project = MagicMock()
        project.tenant_id = pipeline.project.tenant_id
        project.git_url = "https://github.com/org/repo.git"
        project.git_auth_method = "none"
        project.credential_id = None
        project.shallow_clone = False
        project.default_branch = "main"
        project.default_env_id = default_env_id
        project.settings = {}
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(return_value=project)

        env_repo = AsyncMock()
        env_repo.list_by_project = AsyncMock()

        run = MagicMock()
        run.id = uuid4()
        run.tenant_id = project.tenant_id
        run.project_id = sample_schedule.project_id
        run.pipeline_id = sample_schedule.pipeline_id
        run.environment_id = default_env_id
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
        run_repo.set_retry_group_id = AsyncMock()
        audit_repo = AsyncMock()

        next_run_at = datetime.now(timezone.utc)
        patches = _patch_repos(
            schedule_repo=schedule_repo,
            pipeline_repo=pipeline_repo,
            project_repo=project_repo,
            env_repo=env_repo,
            run_repo=run_repo,
            audit_repo=audit_repo,
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patch(
                "qaplatform.worker.scheduler.enqueue_run",
                AsyncMock(return_value=True),
            ),
            patch(
                "qaplatform.domain.services.scheduling.should_fire",
                return_value=True,
            ),
            patch(
                "qaplatform.domain.services.scheduling.compute_next_run_at",
                return_value=next_run_at,
            ),
        ):
            await check_schedules(ctx)

        env_repo.list_by_project.assert_not_awaited()
        run_repo.create.assert_awaited_once()
        assert run_repo.create.await_args.kwargs["environment_id"] == default_env_id

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
        schedule_repo.update_after_fire = AsyncMock(return_value=True)

        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=None)
        project = MagicMock()
        project.tenant_id = uuid4()
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(return_value=project)
        env_repo = AsyncMock()
        env_repo.list_by_project = AsyncMock()
        run_repo = AsyncMock()
        run_repo.create = AsyncMock()
        run_repo.set_retry_group_id = AsyncMock()
        audit_repo = AsyncMock()
        audit_repo.create = AsyncMock()

        next_run_at = datetime.now(timezone.utc)
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
            patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock) as mock_enqueue,
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True) as should_fire,
            patch("qaplatform.domain.services.scheduling.compute_next_run_at", return_value=next_run_at) as compute_next_run_at,
        ):
            await check_schedules(ctx)

        should_fire.assert_called_once_with(sample_schedule, schedule_repo.find_due_schedules.await_args.args[0])
        pipeline_repo.get_by_id.assert_awaited_once_with(sample_schedule.pipeline_id)
        schedule_repo.update_after_fire.assert_awaited_once()
        update_args = schedule_repo.update_after_fire.await_args
        assert update_args.args == (sample_schedule.id,)
        assert update_args.kwargs["last_run_at"].tzinfo is not None
        assert update_args.kwargs["next_run_at"] == next_run_at
        assert update_args.kwargs["last_error"] == "pipeline not found"
        compute_next_run_at.assert_called_once_with(
            sample_schedule.cron_expr,
            sample_schedule.timezone,
            schedule_repo.find_due_schedules.await_args.args[0],
        )
        project_repo.get_by_id.assert_awaited_once_with(sample_schedule.project_id)
        env_repo.list_by_project.assert_not_awaited()
        run_repo.create.assert_not_awaited()
        run_repo.set_retry_group_id.assert_not_awaited()
        mock_enqueue.assert_not_awaited()
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.await_args.kwargs
        assert audit_kwargs == {
            "tenant_id": project.tenant_id,
            "user_id": None,
            "action": "schedule_skipped_missing_pipeline",
            "resource_type": "schedule",
            "resource_id": sample_schedule.id,
            "before_state": None,
            "after_state": {
                "schedule_id": str(sample_schedule.id),
                "project_id": str(sample_schedule.project_id),
                "pipeline_id": str(sample_schedule.pipeline_id),
                "status": "skipped",
                "reason": "pipeline_not_found",
                "last_error": "pipeline not found",
                "next_run_at": next_run_at.isoformat(),
            },
        }
        ctx_session = ctx["db_session_factory"].return_value.__aenter__.return_value
        ctx_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_project_not_found_commits_schedule_error_without_side_effects(
        self,
        ctx,
        sample_schedule,
    ):
        """When project is missing, persist the schedule error and do not enqueue."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock(return_value=True)

        pipeline = MagicMock()
        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=pipeline)
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(return_value=None)
        env_repo = AsyncMock()
        env_repo.list_by_project = AsyncMock()
        run_repo = AsyncMock()
        run_repo.create = AsyncMock()
        audit_repo = AsyncMock()
        audit_repo.create = AsyncMock()

        next_run_at = datetime.now(timezone.utc)
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
            patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock) as mock_enqueue,
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True),
            patch("qaplatform.domain.services.scheduling.compute_next_run_at", return_value=next_run_at),
        ):
            await check_schedules(ctx)

        pipeline_repo.get_by_id.assert_awaited_once_with(sample_schedule.pipeline_id)
        project_repo.get_by_id.assert_awaited_once_with(sample_schedule.project_id)
        schedule_repo.update_after_fire.assert_awaited_once()
        update_args = schedule_repo.update_after_fire.await_args
        assert update_args.args == (sample_schedule.id,)
        assert update_args.kwargs["last_run_at"].tzinfo is not None
        assert update_args.kwargs["next_run_at"] == next_run_at
        assert update_args.kwargs["last_error"] == "project not found"
        env_repo.list_by_project.assert_not_awaited()
        run_repo.create.assert_not_awaited()
        mock_enqueue.assert_not_awaited()
        audit_repo.create.assert_not_awaited()
        ctx_session = ctx["db_session_factory"].return_value.__aenter__.return_value
        ctx_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_project_silent_window_without_creating_run(self, ctx, sample_schedule):
        """Project silent windows should suppress schedule firing and leave an audit trail."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock(return_value=True)

        pipeline = MagicMock()
        pipeline.project = MagicMock()
        pipeline.project.tenant_id = uuid4()
        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=pipeline)

        now = datetime.now(timezone.utc)
        window = {
            "start_at": now - timedelta(minutes=5),
            "end_at": now + timedelta(minutes=5),
            "reason": "planned maintenance",
        }
        project = MagicMock()
        project.tenant_id = pipeline.project.tenant_id
        project.settings = {"silent_windows": [window]}
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(return_value=project)

        env_repo = AsyncMock()
        env_repo.list_by_project = AsyncMock()
        run_repo = AsyncMock()
        run_repo.create = AsyncMock()
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
            patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock) as mock_enqueue,
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True),
        ):
            await check_schedules(ctx)

        pipeline_repo.get_by_id.assert_awaited_once_with(sample_schedule.pipeline_id)
        project_repo.get_by_id.assert_awaited_once_with(sample_schedule.project_id)
        env_repo.list_by_project.assert_not_awaited()
        run_repo.create.assert_not_awaited()
        mock_enqueue.assert_not_awaited()
        schedule_repo.update_after_fire.assert_not_awaited()
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.await_args.kwargs
        assert audit_kwargs == {
            "tenant_id": project.tenant_id,
            "user_id": None,
            "action": "schedule_skipped_silent_window",
            "resource_type": "schedule",
            "resource_id": sample_schedule.id,
            "before_state": None,
            "after_state": {
                "schedule_id": str(sample_schedule.id),
                "window": {
                    "start_at": window["start_at"].isoformat().replace("+00:00", "Z"),
                    "end_at": window["end_at"].isoformat().replace("+00:00", "Z"),
                    "reason": "planned maintenance",
                },
            },
        }
        ctx_session = ctx["db_session_factory"].return_value.__aenter__.return_value
        ctx_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_enqueue_failure(self, ctx, sample_schedule):
        """When enqueue fails, record the error on the schedule."""
        schedule_repo = AsyncMock()
        schedule_repo.find_due_schedules = AsyncMock(return_value=[sample_schedule])
        schedule_repo.update_after_fire = AsyncMock(return_value=True)

        pipeline = MagicMock()
        pipeline.project = MagicMock()
        pipeline.project.tenant_id = uuid4()
        pipeline_repo = AsyncMock()
        pipeline_repo.get_by_id = AsyncMock(return_value=pipeline)

        project = MagicMock()
        project.tenant_id = pipeline.project.tenant_id
        project.git_url = "https://github.com/org/repo.git"
        project.git_auth_method = "none"
        project.credential_id = None
        project.shallow_clone = True
        project.default_branch = "main"
        project.default_env_id = None
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
        operations = []

        async def create_run(**kwargs):
            operations.append(("create", kwargs["trigger_type"], kwargs["metadata_"]["schedule_id"]))
            return run

        async def set_retry_group(source_run_id, retry_group_id):
            operations.append(("set_retry_group", source_run_id, retry_group_id))

        run_repo = AsyncMock()
        run_repo.create = AsyncMock(side_effect=create_run)
        run_repo.set_retry_group_id = AsyncMock(side_effect=set_retry_group)
        audit_repo = AsyncMock()

        async def create_audit(**kwargs):
            operations.append(("audit", kwargs["resource_id"], kwargs["after_state"]["enqueued"]))

        audit_repo.create = AsyncMock(side_effect=create_audit)
        next_run_at = datetime.now(timezone.utc)
        ctx_session = ctx["db_session_factory"].return_value.__aenter__.return_value

        async def commit_session():
            operations.append(("commit", None, None))

        async def enqueue_failed(arq, repo, queued_run, trigger_type, settings):
            operations.append(("enqueue", queued_run.id, trigger_type))
            return False

        async def update_after_fire(schedule_id, **kwargs):
            operations.append(("update_after_fire", schedule_id, kwargs["last_error"]))
            return True

        ctx_session.commit.side_effect = commit_session
        schedule_repo.update_after_fire = AsyncMock(side_effect=update_after_fire)

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
            patch("qaplatform.worker.scheduler.enqueue_run", new=AsyncMock(side_effect=enqueue_failed)) as mock_enqueue,
            patch("qaplatform.domain.services.scheduling.should_fire", return_value=True),
            patch("qaplatform.domain.services.scheduling.compute_next_run_at", return_value=next_run_at),
        ):
            await check_schedules(ctx)

        pipeline_repo.get_by_id.assert_awaited_once_with(sample_schedule.pipeline_id)
        project_repo.get_by_id.assert_awaited_once_with(sample_schedule.project_id)
        env_repo.list_by_project.assert_awaited_once_with(sample_schedule.project_id, limit=1)
        run_repo.create.assert_awaited_once_with(
            tenant_id=project.tenant_id,
            project_id=sample_schedule.project_id,
            pipeline_id=sample_schedule.pipeline_id,
            environment_id=env.id,
            git_ref="main",
            trigger_type="schedule",
            metadata_={
                "schedule_id": str(sample_schedule.id),
                "git_url": "https://github.com/org/repo.git",
                "shallow_clone": True,
                "default_branch": "main",
                # 记录这个 Run 对应哪个 cron 槽，补跑时才能看出是哪一次错过的
                "scheduled_for": sample_schedule.next_run_at.isoformat(),
            },
        )
        run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
        mock_enqueue.assert_awaited_once_with(
            ctx["arq_pool"],
            run_repo,
            run,
            "schedule",
            ctx["settings"],
        )
        # 两次：第一次抢占触发槽（带 expected_next_run_at），enqueue 失败后
        # 再写一次 last_error——抢槽时还不知道 enqueue 会不会成功
        assert schedule_repo.update_after_fire.await_count == 2
        claim_args, error_args = schedule_repo.update_after_fire.await_args_list
        assert claim_args.args == (sample_schedule.id,)
        assert claim_args.kwargs["expected_next_run_at"] == sample_schedule.next_run_at
        assert claim_args.kwargs["last_error"] is None
        assert error_args.args == (sample_schedule.id,)
        assert error_args.kwargs["last_run_at"].tzinfo is not None
        assert error_args.kwargs["next_run_at"] == next_run_at
        assert error_args.kwargs["last_error"] == "enqueue failed"
        audit_repo.create.assert_awaited_once()
        audit_kwargs = audit_repo.create.await_args.kwargs
        assert audit_kwargs == {
            "tenant_id": project.tenant_id,
            "user_id": None,
            "action": "run.trigger",
            "resource_type": "run",
            "resource_id": run.id,
            "before_state": None,
            "after_state": {
                "id": str(run.id),
                "tenant_id": str(run.tenant_id),
                "project_id": str(run.project_id),
                "pipeline_id": str(run.pipeline_id),
                "environment_id": str(run.environment_id),
                "status": run.status,
                "trigger_type": "schedule",
                "triggered_by": None,
                "git_ref": "main",
                "git_sha": None,
                "priority": 2,
                "attempt": 1,
                "metadata": {"schedule_id": str(sample_schedule.id)},
                "schedule_id": str(sample_schedule.id),
                "enqueued": False,
            },
        }
        ctx_session.commit.assert_has_awaits([call(), call()])
        assert operations == [
            ("update_after_fire", sample_schedule.id, None),
            ("commit", None, None),
            ("create", "schedule", str(sample_schedule.id)),
            ("set_retry_group", run.id, run.id),
            ("commit", None, None),
            ("enqueue", run.id, "schedule"),
            ("audit", run.id, False),
            ("update_after_fire", sample_schedule.id, "enqueue failed"),
            ("commit", None, None),
        ]

    @pytest.mark.asyncio
    async def test_no_session_factory(self):
        """When session_factory is None, exit early."""
        arq_pool = AsyncMock()
        ctx = {
            "db_session_factory": None,
            "arq_pool": arq_pool,
            "settings": MagicMock(),
        }
        await check_schedules(ctx)  # should not raise
        arq_pool.enqueue_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_arq_pool(self):
        """When arq_pool is None, exit early."""
        session_factory = MagicMock()
        ctx = {
            "db_session_factory": session_factory,
            "arq_pool": None,
            "settings": MagicMock(),
        }
        await check_schedules(ctx)  # should not raise
        session_factory.assert_not_called()
