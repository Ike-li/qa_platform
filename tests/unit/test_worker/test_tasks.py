"""Unit tests for qaplatform.worker.tasks.execute_run.

P0-B: verify the long-lived worker transaction is split — the row lock
acquired by claim_for_worker (UPDATE...RETURNING) must be released
immediately after a successful claim so the cancel API and status reads
on other connections aren't blocked for the duration of the run.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from qaplatform.dependencies import CryptoService
from qaplatform.domain.services.env_vars_crypto import encrypt_env_vars


@pytest.fixture
def fake_run():
    run = MagicMock()
    run.id = uuid4()
    run.cancel_requested_at = None
    run.pipeline = MagicMock()
    run.pipeline.stages = []
    run.pipeline.collectors = [{"plugin": "junit", "config": {}, "enabled": True}]
    run.pipeline.timeout_seconds = 60
    run.pipeline.retry_policy = None
    run.environment = MagicMock()
    run.environment.base_image = "python:3.12-alpine"
    run.environment.env_vars = {}
    run.environment.memory_mb = 512
    run.environment.cpu_cores = 1.0
    run.environment.resource_limits = {}
    run.environment.network_policy = "deny"
    run.environment.setup_script = None
    return run


def test_build_pipeline_config_decrypts_environment_env_vars(fake_run):
    from qaplatform.worker.tasks import _build_pipeline_config

    crypto = CryptoService({0: b"\x00" * 32})
    fake_run.environment.id = uuid4()
    fake_run.environment.env_vars = encrypt_env_vars(
        {"API_TOKEN": "secret-value"},
        environment_id=fake_run.environment.id,
        crypto=crypto,
    )

    config = _build_pipeline_config(
        fake_run,
        fake_run.pipeline,
        fake_run.environment,
        crypto,
    )

    assert config.env_vars == {"API_TOKEN": "secret-value"}


def test_build_pipeline_config_requires_crypto_for_encrypted_env_vars(fake_run):
    from qaplatform.worker.tasks import _build_pipeline_config

    crypto = CryptoService({0: b"\x00" * 32})
    fake_run.environment.id = uuid4()
    fake_run.environment.env_vars = encrypt_env_vars(
        {"API_TOKEN": "secret-value"},
        environment_id=fake_run.environment.id,
        crypto=crypto,
    )

    with patch("qaplatform.engine.executor.PipelineConfig") as pipeline_config:
        with pytest.raises(RuntimeError) as exc_info:
            _build_pipeline_config(fake_run, fake_run.pipeline, fake_run.environment)

    assert str(exc_info.value) == "Crypto service not initialised"
    assert "API_TOKEN" not in str(exc_info.value)
    assert "secret-value" not in str(exc_info.value)
    assert fake_run.environment.env_vars["ciphertext"] not in str(exc_info.value)
    pipeline_config.assert_not_called()


def test_build_pipeline_config_maps_environment_artifact_limits(fake_run):
    from qaplatform.worker.tasks import _build_pipeline_config

    fake_run.environment.resource_limits = {
        "disk_mb": 256,
        "max_artifact_size_mb": 42,
        "max_artifacts_count": 9,
    }

    config = _build_pipeline_config(fake_run, fake_run.pipeline, fake_run.environment)

    assert config.resource_limits.disk_bytes == 256 * 1024 * 1024
    assert config.resource_limits.max_artifact_size_bytes == 42 * 1024 * 1024
    assert config.resource_limits.max_artifacts_count == 9


def test_build_pipeline_config_maps_pipeline_collectors(fake_run):
    from qaplatform.worker.tasks import _build_pipeline_config

    fake_run.pipeline.collectors = [
        {
            "plugin": "junit",
            "config": {"path": "custom/results.xml"},
            "enabled": True,
        },
        {
            "plugin": "coverage",
            "config": {"format": "cobertura", "path": "coverage.xml"},
            "enabled": False,
        }
    ]

    config = _build_pipeline_config(fake_run, fake_run.pipeline, fake_run.environment)

    assert [
        {
            "plugin": collector.plugin,
            "config": collector.config,
            "enabled": collector.enabled,
        }
        for collector in config.collectors
    ] == [
        {
            "plugin": "junit",
            "config": {"path": "custom/results.xml"},
            "enabled": True,
        },
        {
            "plugin": "coverage",
            "config": {"format": "cobertura", "path": "coverage.xml"},
            "enabled": False,
        },
    ]


def test_build_pipeline_config_defaults_to_junit_collector(fake_run):
    from qaplatform.worker.tasks import _build_pipeline_config

    fake_run.pipeline.collectors = None

    config = _build_pipeline_config(fake_run, fake_run.pipeline, fake_run.environment)

    assert [
        {
            "plugin": collector.plugin,
            "config": collector.config,
            "enabled": collector.enabled,
        }
        for collector in config.collectors
    ] == [{"plugin": "junit", "config": {}, "enabled": True}]


def _assert_worker_heartbeat_set_call(set_call, worker_id: str) -> None:
    key, timestamp = set_call.args
    assert key == f"worker:{worker_id}:heartbeat"
    heartbeat_at = datetime.fromisoformat(timestamp)
    assert heartbeat_at.tzinfo is not None
    assert heartbeat_at.utcoffset() == timedelta(0)
    assert set_call.kwargs == {"ex": 90}


@pytest.mark.asyncio
async def test_build_source_auth_decrypts_project_git_credential(fake_run):
    from qaplatform.worker.tasks import _build_source_auth

    crypto = CryptoService({0: b"\x00" * 32})
    project = MagicMock()
    project.id = fake_run.project_id = uuid4()
    project.tenant_id = uuid4()
    project.git_auth_method = "token"
    project.credential_id = uuid4()
    credential = MagicMock()
    credential.id = project.credential_id
    credential.name = "git-token"
    credential.type = "token"
    credential.encrypted_value = crypto.encrypt(
        "secret-token",
        context_id=f"credential:{project.id}:git-token",
    )
    fake_run.metadata_ = {
        "git_auth_method": "token",
        "credential_id": str(project.credential_id),
    }

    result = MagicMock()
    result.scalar_one_or_none.return_value = credential
    session = AsyncMock()
    session.execute.return_value = result

    auth = await _build_source_auth(fake_run, project, session, crypto)

    assert auth == {"method": "token", "secret": "secret-token"}


@pytest.mark.asyncio
async def test_build_source_auth_uses_rotated_git_credential_secret(fake_run):
    from qaplatform.worker.tasks import _build_source_auth

    crypto = CryptoService({0: b"\x00" * 32})
    project = MagicMock()
    project.id = fake_run.project_id = uuid4()
    project.tenant_id = uuid4()
    project.git_auth_method = "token"
    project.credential_id = uuid4()
    credential = MagicMock()
    credential.id = project.credential_id
    credential.name = "git-token"
    credential.type = "token"
    credential.encrypted_value = crypto.encrypt(
        "rotated-secret-token",
        context_id=f"credential:{project.id}:git-token",
    )
    fake_run.metadata_ = {
        "git_auth_method": "token",
        "credential_id": str(project.credential_id),
    }

    result = MagicMock()
    result.scalar_one_or_none.return_value = credential
    session = AsyncMock()
    session.execute.return_value = result

    auth = await _build_source_auth(fake_run, project, session, crypto)

    assert auth == {"method": "token", "secret": "rotated-secret-token"}


@pytest.mark.asyncio
async def test_build_source_auth_rejects_type_mismatch(fake_run):
    from qaplatform.worker.tasks import _build_source_auth

    project = MagicMock()
    project.id = fake_run.project_id = uuid4()
    project.tenant_id = uuid4()
    project.git_auth_method = "token"
    project.credential_id = uuid4()
    credential = MagicMock()
    credential.type = "ssh_key"

    result = MagicMock()
    result.scalar_one_or_none.return_value = credential
    session = AsyncMock()
    session.execute.return_value = result

    crypto = MagicMock()

    with pytest.raises(RuntimeError) as exc_info:
        await _build_source_auth(
            fake_run,
            project,
            session,
            crypto,
        )

    assert exc_info.value.args == ("Project Git credential type mismatch",)
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    rendered = str(compiled)
    assert "credential.id = " in rendered
    assert "credential.project_id = " in rendered
    assert "credential.tenant_id = " in rendered
    assert "credential.deleted_at IS NULL" in rendered
    bound_values = {}
    for column in [
        "credential.id",
        "credential.project_id",
        "credential.tenant_id",
    ]:
        match = re.search(rf"{re.escape(column)} = %\(([^)]+)\)s", rendered)
        assert match is not None, rendered
        bound_values[column] = compiled.params[match.group(1)]
    assert bound_values == {
        "credential.id": project.credential_id,
        "credential.project_id": project.id,
        "credential.tenant_id": project.tenant_id,
    }
    crypto.decrypt.assert_not_called()


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    # Default: session.execute returns an active project (for archive check)
    active_project = MagicMock()
    active_project.status = "active"
    active_project.git_auth_method = "none"
    active_project.credential_id = None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = active_project
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    factory = MagicMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = mock_session
    cm.__aexit__.return_value = None
    factory.return_value = cm
    return factory


@pytest.fixture
def ctx(mock_session_factory):
    return {
        "log_stream": AsyncMock(),
        "worker_id": "worker-test",
        "redis": AsyncMock(),
        "db_session_factory": mock_session_factory,
        "docker_backend": MagicMock(),
        "plugin_registry": MagicMock(),
        "s3_client": None,
        "s3_bucket": "qa-platform",
    }


class TestClaimReleasesRowLock:
    """P0-B step 1: claim_for_worker -> session.commit() must run before
    the long execute() phase so PREPARING row lock is released early."""

    @pytest.mark.asyncio
    async def test_execute_run_emits_parent_span(self, ctx):
        from qaplatform.worker import tasks as worker_tasks

        spans: list[tuple[str, dict | None]] = []

        class _SpanContext:
            def __init__(self, name: str, attributes: dict | None):
                self.name = name
                self.attributes = attributes

            def __enter__(self):
                spans.append((self.name, self.attributes))
                return MagicMock()

            def __exit__(self, exc_type, exc, tb):
                return False

        class _Tracer:
            def start_as_current_span(self, name: str, attributes=None):
                return _SpanContext(name, attributes)

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=None)

        with patch.object(
            worker_tasks.trace,
            "get_tracer",
            return_value=_Tracer(),
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=AsyncMock(),
        ):
            await worker_tasks.execute_run(ctx, "run-123")

        assert spans == [("execute_run", {"run.id": "run-123"})]

    @pytest.mark.asyncio
    async def test_commit_called_immediately_after_successful_claim(
        self, ctx, mock_session, fake_run
    ):
        from qaplatform.worker import tasks as worker_tasks

        call_log: list[str] = []

        async def _claim(*_args, **_kwargs):
            call_log.append("claim")
            return fake_run

        async def _commit():
            call_log.append("commit")

        async def _execute(*_args, **_kwargs):
            call_log.append("execute")
            raise RuntimeError("stop after claim+commit")

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(side_effect=_claim)
        run_repo.release_worker = AsyncMock()
        run_repo.finish_if_current = AsyncMock(return_value=True)
        run_repo.fail_if_current = AsyncMock(return_value=False)

        mock_session.commit = AsyncMock(side_effect=_commit)

        executor = AsyncMock()
        executor.execute = AsyncMock(side_effect=_execute)

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ), patch(
            "qaplatform.worker.tasks._attempt_retry", new_callable=AsyncMock
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        run_repo.claim_for_worker.assert_awaited_once_with(
            str(fake_run.id),
            worker_id="worker-test",
        )
        assert call_log[:3] == ["claim", "commit", "execute"], (
            "claim_for_worker must release its row lock before execute() can "
            f"run, even when execute later fails; log={call_log}"
        )

    @pytest.mark.asyncio
    async def test_commit_ordering_claim_then_commit_before_execute(
        self, ctx, mock_session, fake_run
    ):
        """Order: claim_for_worker -> session.commit -> executor.execute."""
        from qaplatform.worker import tasks as worker_tasks

        call_log: list[str] = []

        async def _claim(*args, **kwargs):
            call_log.append("claim")
            return fake_run

        async def _commit():
            call_log.append("commit")

        async def _execute(*args, **kwargs):
            call_log.append("execute")
            from qaplatform.domain.models.run import RunStatus
            return RunStatus.DONE

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(side_effect=_claim)
        run_repo.release_worker = AsyncMock()
        run_repo.finish_if_current = AsyncMock(return_value=True)
        run_repo.fail_if_current = AsyncMock(return_value=False)

        mock_session.commit = AsyncMock(side_effect=_commit)

        executor = AsyncMock()
        executor.execute = AsyncMock(side_effect=_execute)

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        # The first commit MUST come between claim and execute.
        assert call_log[0] == "claim"
        assert call_log[1] == "commit"
        assert "execute" in call_log
        assert call_log.index("commit") < call_log.index("execute")

    @pytest.mark.asyncio
    async def test_no_commit_when_claim_returns_none(
        self, ctx, mock_session, fake_run
    ):
        """If claim_for_worker returns None (already claimed by someone
        else), the function returns early — no commit is required since
        UPDATE matched zero rows and the transaction holds nothing."""
        from qaplatform.worker import tasks as worker_tasks

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=None)
        executor = AsyncMock()
        publish_status_event = AsyncMock()

        with patch(
            "qaplatform.engine.events.publish_status_event", new=publish_status_event
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            run_id = str(uuid4())
            await worker_tasks.execute_run(ctx, run_id)

        run_repo.claim_for_worker.assert_awaited_once_with(
            run_id,
            worker_id="worker-test",
        )
        # No-op fast path: no commits expected.
        mock_session.commit.assert_not_awaited()
        mock_session.refresh.assert_not_awaited()
        mock_session.execute.assert_not_awaited()
        publish_status_event.assert_not_awaited()
        executor.execute.assert_not_awaited()


class TestArchiveBlocking:
    """Worker-side archive check: archived projects cancel queued runs."""

    @pytest.mark.asyncio
    async def test_worker_skips_archived_project(self, ctx, mock_session, fake_run):
        """When project is archived, worker cancels the run without executing."""
        from qaplatform.worker import tasks as worker_tasks

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=fake_run)
        run_repo.cancel_if_current = AsyncMock(return_value=True)
        run_repo.release_worker = AsyncMock()

        # Mock session.execute to return archived project
        archived_project = MagicMock()
        archived_project.status = "archived"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = archived_project
        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = AsyncMock()

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        # Run was cancelled
        run_repo.cancel_if_current.assert_awaited_once_with(fake_run.id)
        run_repo.release_worker.assert_awaited_once_with(
            fake_run.id,
            worker_id="worker-test",
        )
        # Executor was never called
        executor.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_worker_skips_deleted_project(self, ctx, mock_session, fake_run):
        """When project is soft-deleted (None), worker cancels the run."""
        from qaplatform.worker import tasks as worker_tasks

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=fake_run)
        run_repo.cancel_if_current = AsyncMock(return_value=True)
        run_repo.release_worker = AsyncMock()

        # Mock session.execute to return None (deleted project)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = AsyncMock()

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        run_repo.cancel_if_current.assert_awaited_once_with(fake_run.id)
        run_repo.release_worker.assert_awaited_once_with(
            fake_run.id,
            worker_id="worker-test",
        )
        executor.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_worker_executes_active_project(self, ctx, mock_session, fake_run):
        """When project is active, worker proceeds with execution."""
        from qaplatform.worker import tasks as worker_tasks
        from qaplatform.domain.models.run import RunStatus

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(return_value=fake_run)
        run_repo.release_worker = AsyncMock()
        run_repo.finish_if_current = AsyncMock(return_value=True)
        run_repo.fail_if_current = AsyncMock(return_value=False)

        # Mock session.execute to return active project
        active_project = MagicMock()
        active_project.status = "active"
        active_project.git_auth_method = "none"
        active_project.credential_id = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active_project
        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = AsyncMock()
        executor.execute = AsyncMock(return_value=RunStatus.DONE)

        with patch(
            "qaplatform.engine.events.publish_status_event", new=AsyncMock()
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        executor.execute.assert_awaited_once()
        execute_call = executor.execute.await_args
        assert execute_call.kwargs == {}
        executed_run, config = execute_call.args
        assert executed_run is fake_run
        assert {
            "image": config.image,
            "stages": [
                {
                    "name": stage.name,
                    "plugin": stage.plugin,
                    "phase": stage.phase,
                    "config": stage.config,
                    "continue_on_error": stage.continue_on_error,
                }
                for stage in config.stages
            ],
            "env_vars": config.env_vars,
            "resource_limits": {
                "memory_bytes": config.resource_limits.memory_bytes,
                "cpu_cores": config.resource_limits.cpu_cores,
                "disk_bytes": config.resource_limits.disk_bytes,
                "max_artifact_size_bytes": (
                    config.resource_limits.max_artifact_size_bytes
                ),
                "max_artifacts_count": config.resource_limits.max_artifacts_count,
            },
            "network_policy": config.network_policy,
            "timeout_seconds": config.timeout_seconds,
            "setup_script": config.setup_script,
            "collectors": [
                {
                    "plugin": collector.plugin,
                    "config": collector.config,
                    "enabled": collector.enabled,
                }
                for collector in config.collectors
            ],
            "source_auth": config.source_auth,
        } == {
            "image": "python:3.12-alpine",
            "stages": [],
            "env_vars": {},
            "resource_limits": {
                "memory_bytes": 512 * 1024 * 1024,
                "cpu_cores": 1.0,
                "disk_bytes": None,
                "max_artifact_size_bytes": 100 * 1024 * 1024,
                "max_artifacts_count": 50,
            },
            "network_policy": "deny",
            "timeout_seconds": 60,
            "setup_script": None,
            "collectors": [{"plugin": "junit", "config": {}, "enabled": True}],
            "source_auth": None,
        }
        # cancel_if_current was NOT called for archive reason
        run_repo.cancel_if_current.assert_not_awaited()
        run_repo.release_worker.assert_awaited_once_with(
            str(fake_run.id),
            worker_id="worker-test",
        )

    @pytest.mark.asyncio
    async def test_worker_releases_claim_when_run_was_already_cancel_requested(
        self,
        ctx,
        mock_session,
        fake_run,
    ):
        """A claim that discovers a pre-existing cancel request must not
        leave worker_id attached to a terminal run."""
        from qaplatform.worker import tasks as worker_tasks

        fake_run.cancel_requested_at = datetime.now(timezone.utc)
        operations = []

        async def _claim(*args, **kwargs):
            operations.append(("claim", args, kwargs))
            return fake_run

        async def _commit():
            operations.append(("commit",))

        async def _refresh(*args):
            operations.append(("refresh", args))

        async def _cancel(*args):
            operations.append(("cancel", args))
            return True

        async def _release(*args, **kwargs):
            operations.append(("release", args, kwargs))

        async def _publish(*args, **kwargs):
            operations.append(("publish", args, kwargs))

        run_repo = AsyncMock()
        run_repo.claim_for_worker = AsyncMock(side_effect=_claim)
        run_repo.cancel_if_current = AsyncMock(side_effect=_cancel)
        run_repo.release_worker = AsyncMock(side_effect=_release)
        mock_session.commit = AsyncMock(side_effect=_commit)
        mock_session.refresh = AsyncMock(side_effect=_refresh)
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("cancel-requested fast path must not query project")
        )

        executor = AsyncMock()

        publish_status_event = AsyncMock(side_effect=_publish)
        with patch(
            "qaplatform.engine.events.publish_status_event",
            new=publish_status_event,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.RunRepository",
            return_value=run_repo,
        ), patch(
            "qaplatform.infra.database.repositories.run_repo.ArtifactRepository",
            return_value=AsyncMock(),
        ), patch(
            "qaplatform.engine.executor.RunExecutor",
            return_value=executor,
        ):
            await worker_tasks.execute_run(ctx, str(fake_run.id))

        run_repo.cancel_if_current.assert_awaited_once_with(fake_run.id)
        run_repo.release_worker.assert_awaited_once_with(
            fake_run.id,
            worker_id="worker-test",
        )
        executor.execute.assert_not_awaited()
        mock_session.execute.assert_not_awaited()
        assert [operation[0] for operation in operations] == [
            "claim",
            "commit",
            "publish",
            "refresh",
            "cancel",
            "publish",
            "release",
            "commit",
        ]
        assert operations[2] == (
            "publish",
            (ctx["redis"], str(fake_run.id), "preparing"),
            {"previous": "queued"},
        )
        assert operations[4] == ("cancel", (fake_run.id,))
        assert operations[5] == (
            "publish",
            (ctx["redis"], str(fake_run.id), "cancelled"),
            {"previous": "preparing"},
        )
        assert operations[6] == (
            "release",
            (fake_run.id,),
            {"worker_id": "worker-test"},
        )


class TestHeartbeatLoop:
    """P1-5: _heartbeat_loop resilience to transient Redis errors."""

    @pytest.mark.asyncio
    async def test_heartbeat_writes_reclaimer_key_with_ttl_and_utc_timestamp(self):
        """Heartbeat must write the exact Redis key shape the reclaimer scans."""
        from qaplatform.worker.tasks import _heartbeat_loop

        worker_id = "test-worker-ttl"
        redis = AsyncMock()

        with patch(
            "qaplatform.worker.tasks.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ), pytest.raises(asyncio.CancelledError):
            await _heartbeat_loop(worker_id, redis, interval=30)

        redis.set.assert_awaited_once()
        _assert_worker_heartbeat_set_call(redis.set.await_args, worker_id)

    @pytest.mark.asyncio
    async def test_heartbeat_continues_after_redis_error(self):
        """Verify that transient Redis errors don't kill the heartbeat loop.

        Scenario: redis.set() fails on first call, succeeds on second.
        Expected: loop continues, subsequent set() calls are made.
        """
        from qaplatform.worker.tasks import _heartbeat_loop

        worker_id = "test-worker-1"
        redis = AsyncMock()

        # First call raises Exception, second and third succeed.
        redis.set = AsyncMock(side_effect=[
            Exception("Redis connection error"),
            None,  # success
            None,  # success
        ])
        sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError])

        with patch("qaplatform.worker.tasks.asyncio.sleep", new=sleep), pytest.raises(
            asyncio.CancelledError
        ):
            await _heartbeat_loop(worker_id, redis, interval=0.05)

        assert [set_call.args[0] for set_call in redis.set.await_args_list] == [
            f"worker:{worker_id}:heartbeat",
            f"worker:{worker_id}:heartbeat",
            f"worker:{worker_id}:heartbeat",
        ]
        assert [sleep_call.args for sleep_call in sleep.await_args_list] == [
            (0.05,),
            (0.05,),
            (0.05,),
        ]
        for set_call in redis.set.await_args_list:
            _assert_worker_heartbeat_set_call(set_call, worker_id)

    @pytest.mark.asyncio
    async def test_heartbeat_propagates_cancelled(self):
        """Verify that CancelledError propagates cleanly from heartbeat loop.

        Scenario: heartbeat is running normally, then cancelled.
        Expected: task exits with CancelledError, not suppressed.
        """
        from qaplatform.worker.tasks import _heartbeat_loop

        worker_id = "test-worker-2"
        redis = AsyncMock()
        redis.set = AsyncMock()

        task = asyncio.create_task(_heartbeat_loop(worker_id, redis, interval=0.1))

        # Let it run for a bit
        await asyncio.sleep(0.05)

        # Cancel it
        task.cancel()
        results = await asyncio.gather(task, return_exceptions=True)

        # Should get CancelledError
        assert [type(result) for result in results] == [asyncio.CancelledError]
