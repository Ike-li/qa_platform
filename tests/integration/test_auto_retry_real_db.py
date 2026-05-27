"""Real PostgreSQL coverage for automatic retry scheduling."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


class _FakeArq:
    def __init__(self):
        self.calls: list[dict] = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(job_id=kwargs["_job_id"])


def _decode_redis_mapping(mapping: dict) -> dict[str, str]:
    return {
        key.decode() if isinstance(key, bytes) else key: (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in mapping.items()
    }


@pytest.mark.asyncio
async def test_attempt_retry_uses_api_max_attempts_and_persists_retry_run(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run
    from qaplatform.worker.tasks import _attempt_retry

    original = seed_run["run"]
    seed_run["pipeline"].retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
    }
    await integration_db_session.commit()

    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    arq = _FakeArq()
    settings = SimpleNamespace(max_concurrent_runs=10, max_concurrent_per_project=10)

    scheduled = await _attempt_retry(
        str(original.id),
        ConnectionError("docker daemon unavailable"),
        {"arq_pool": arq, "settings": settings},
        factory,
    )

    assert scheduled is True
    assert len(arq.calls) == 1
    assert arq.calls[0]["kwargs"]["_job_id"].startswith("run:")

    result = await integration_db_session.execute(
        select(Run).where(Run.source_run_id == original.id)
    )
    retry_run = result.scalar_one()
    assert retry_run.attempt == 2
    assert retry_run.retry_group_id == original.id
    assert retry_run.git_ref == original.git_ref
    assert retry_run.priority == original.priority
    assert retry_run.enqueued_at is not None
    assert retry_run.queue_name == "queue:medium"


@pytest.mark.asyncio
async def test_attempt_retry_stops_when_api_max_attempts_exhausted(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run
    from qaplatform.worker.tasks import _attempt_retry

    original = seed_run["run"]
    original.attempt = 2
    seed_run["pipeline"].retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
    }
    await integration_db_session.commit()

    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    arq = _FakeArq()
    settings = SimpleNamespace(max_concurrent_runs=10, max_concurrent_per_project=10)

    scheduled = await _attempt_retry(
        str(original.id),
        ConnectionError("docker daemon unavailable"),
        {"arq_pool": arq, "settings": settings},
        factory,
    )

    assert scheduled is False
    assert arq.calls == []
    result = await integration_db_session.execute(
        select(Run).where(Run.source_run_id == original.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_execute_run_infra_exception_marks_failed_and_schedules_retry_real_db(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.worker.tasks import execute_run

    original = seed_run["run"]
    original_id = original.id
    seed_run["pipeline"].retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
    }
    await integration_db_session.commit()

    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    arq = _FakeArq()
    ctx = {
        "log_stream": AsyncMock(),
        "worker_id": "worker-integration",
        "redis": AsyncMock(),
        "db_session_factory": factory,
        "docker_backend": AsyncMock(),
        "plugin_registry": AsyncMock(),
        "s3_client": None,
        "s3_bucket": "qa-platform-test",
        "arq_pool": arq,
        "settings": SimpleNamespace(
            max_concurrent_runs=10,
            max_concurrent_per_project=10,
        ),
        "container": SimpleNamespace(crypto_service=None),
    }

    with patch(
        "qaplatform.engine.executor.RunExecutor.execute",
        new=AsyncMock(side_effect=ConnectionError("docker daemon unavailable")),
    ):
        await asyncio.wait_for(execute_run(ctx, str(original_id)), timeout=5)

    integration_db_session.expire_all()
    original_row = (
        await integration_db_session.execute(
            select(Run).where(Run.id == original_id)
        )
    ).scalar_one()
    assert original_row.status == RunStatusEnum.FAILED
    assert "docker daemon unavailable" in original_row.error_message

    retry_run = (
        await integration_db_session.execute(
            select(Run).where(Run.source_run_id == original_id)
        )
    ).scalar_one()
    assert retry_run.attempt == 2
    assert retry_run.retry_group_id == original_id
    assert retry_run.queue_name == "queue:medium"
    assert retry_run.enqueued_at is not None
    assert len(arq.calls) == 1


@pytest.mark.asyncio
async def test_execute_run_setup_docker_infra_error_uses_real_executor_and_schedules_retry(
    integration_app,
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import STATUS_HASH_KEY
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.worker.tasks import execute_run

    original = seed_run["run"]
    original_id = original.id
    seed_run["pipeline"].retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
    }
    seed_run["environment"].setup_script = "echo setup"
    await integration_db_session.commit()

    redis = integration_app.state.container.redis_client
    await redis.delete(
        STATUS_HASH_KEY.format(run_id=str(original_id)),
        LogStream._stream_key(original_id),
    )

    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    arq = _FakeArq()
    docker_backend = AsyncMock()
    docker_backend.create_execution = AsyncMock(
        side_effect=ConnectionError("docker daemon unavailable during setup")
    )
    docker_backend.start = AsyncMock()

    await asyncio.wait_for(
        execute_run(
            {
                "log_stream": LogStream(redis),
                "worker_id": "worker-real-executor-infra",
                "redis": redis,
                "db_session_factory": factory,
                "docker_backend": docker_backend,
                "plugin_registry": AsyncMock(),
                "s3_client": None,
                "s3_bucket": "qa-platform-test",
                "arq_pool": arq,
                "settings": SimpleNamespace(
                    max_concurrent_runs=10,
                    max_concurrent_per_project=10,
                ),
                "container": SimpleNamespace(crypto_service=None),
            },
            str(original_id),
        ),
        timeout=5,
    )

    integration_db_session.expire_all()
    original_row = (
        await integration_db_session.execute(
            select(Run).where(Run.id == original_id)
        )
    ).scalar_one()
    assert original_row.status == RunStatusEnum.FAILED
    assert original_row.worker_id is None
    assert "docker daemon unavailable during setup" in (
        original_row.error_message or ""
    )

    retry_run = (
        await integration_db_session.execute(
            select(Run).where(Run.source_run_id == original_id)
        )
    ).scalar_one()
    assert retry_run.status == RunStatusEnum.QUEUED
    assert retry_run.attempt == 2
    assert retry_run.retry_group_id == original_id
    assert retry_run.queue_name == "queue:medium"
    assert retry_run.arq_job_id == f"run:{retry_run.id}"
    assert retry_run.enqueued_at is not None
    assert len(arq.calls) == 1
    assert arq.calls[0]["args"] == ("execute_run", str(retry_run.id))
    assert arq.calls[0]["kwargs"]["_job_id"] == f"run:{retry_run.id}"

    docker_backend.create_execution.assert_awaited_once()
    docker_backend.start.assert_not_awaited()
    status_hash = await redis.hgetall(
        STATUS_HASH_KEY.format(run_id=str(original_id))
    )
    assert _decode_redis_mapping(status_hash)["status"] == "failed"

    log_entries = await LogStream(redis).read_logs(original_id, count=20)
    log_lines = [entry["line"] for entry in log_entries]
    assert "Repository cloned successfully" in log_lines
    assert "Running setup script..." in log_lines


@pytest.mark.asyncio
async def test_execute_run_setup_script_failure_is_not_retried_real_executor(
    integration_app,
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.docker_backend import ExitResult
    from qaplatform.engine.events import STATUS_HASH_KEY
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.worker.tasks import execute_run

    original = seed_run["run"]
    original_id = original.id
    seed_run["pipeline"].retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
    }
    seed_run["environment"].setup_script = "exit 1"
    await integration_db_session.commit()

    redis = integration_app.state.container.redis_client
    await redis.delete(
        STATUS_HASH_KEY.format(run_id=str(original_id)),
        LogStream._stream_key(original_id),
    )

    async def _empty_logs(_execution_id):
        if False:
            yield

    now = datetime.now(timezone.utc)
    docker_backend = AsyncMock()
    docker_backend.create_execution = AsyncMock(return_value="setup-container-nonzero")
    docker_backend.start = AsyncMock()
    docker_backend.wait = AsyncMock(
        return_value=ExitResult(exit_code=1, started_at=now, finished_at=now)
    )
    docker_backend.cleanup = AsyncMock()
    docker_backend.stream_logs = _empty_logs

    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    arq = _FakeArq()
    await asyncio.wait_for(
        execute_run(
            {
                "log_stream": LogStream(redis),
                "worker_id": "worker-real-executor-setup-failure",
                "redis": redis,
                "db_session_factory": factory,
                "docker_backend": docker_backend,
                "plugin_registry": AsyncMock(),
                "s3_client": None,
                "s3_bucket": "qa-platform-test",
                "arq_pool": arq,
                "settings": SimpleNamespace(
                    max_concurrent_runs=10,
                    max_concurrent_per_project=10,
                ),
                "container": SimpleNamespace(crypto_service=None),
            },
            str(original_id),
        ),
        timeout=5,
    )

    integration_db_session.expire_all()
    original_row = (
        await integration_db_session.execute(
            select(Run).where(Run.id == original_id)
        )
    ).scalar_one()
    assert original_row.status == RunStatusEnum.FAILED
    assert original_row.worker_id is None
    assert "Setup script failed (exit 1)" in (original_row.error_message or "")

    retry_run = (
        await integration_db_session.execute(
            select(Run).where(Run.source_run_id == original_id)
        )
    ).scalar_one_or_none()
    assert retry_run is None
    assert arq.calls == []
    docker_backend.cleanup.assert_awaited_once_with("setup-container-nonzero")

    status_hash = await redis.hgetall(
        STATUS_HASH_KEY.format(run_id=str(original_id))
    )
    assert _decode_redis_mapping(status_hash)["status"] == "failed"

    log_entries = await LogStream(redis).read_logs(original_id, count=20)
    log_lines = [entry["line"] for entry in log_entries]
    assert "Repository cloned successfully" in log_lines
    assert "Running setup script..." in log_lines


@pytest.mark.asyncio
async def test_execute_run_clone_failure_is_not_retried_real_executor(
    integration_app,
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import STATUS_HASH_KEY
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.worker.tasks import execute_run

    original = seed_run["run"]
    original_id = original.id
    seed_run["pipeline"].retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
    }
    original.metadata_ = {
        "git_url": "https://x-access-token:secret@example.invalid/org/repo.git"
    }
    await integration_db_session.commit()

    redis = integration_app.state.container.redis_client
    await redis.delete(
        STATUS_HASH_KEY.format(run_id=str(original_id)),
        LogStream._stream_key(original_id),
    )

    source = AsyncMock()
    source.clone = AsyncMock(
        side_effect=RuntimeError(
            "git clone failed: https://x-access-token:secret@example.invalid/org/repo.git"
        )
    )
    plugin_registry = SimpleNamespace(get_source=lambda _name: source)
    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    arq = _FakeArq()

    await asyncio.wait_for(
        execute_run(
            {
                "log_stream": LogStream(redis),
                "worker_id": "worker-real-executor-clone-failure",
                "redis": redis,
                "db_session_factory": factory,
                "docker_backend": AsyncMock(),
                "plugin_registry": plugin_registry,
                "s3_client": None,
                "s3_bucket": "qa-platform-test",
                "arq_pool": arq,
                "settings": SimpleNamespace(
                    max_concurrent_runs=10,
                    max_concurrent_per_project=10,
                ),
                "container": SimpleNamespace(crypto_service=None),
            },
            str(original_id),
        ),
        timeout=5,
    )

    integration_db_session.expire_all()
    original_row = (
        await integration_db_session.execute(
            select(Run).where(Run.id == original_id)
        )
    ).scalar_one()
    assert original_row.status == RunStatusEnum.FAILED
    assert original_row.worker_id is None
    assert "git clone failed" in (original_row.error_message or "")
    assert "secret" not in (original_row.error_message or "")
    assert "x-access-token" not in (original_row.error_message or "")

    retry_run = (
        await integration_db_session.execute(
            select(Run).where(Run.source_run_id == original_id)
        )
    ).scalar_one_or_none()
    assert retry_run is None
    assert arq.calls == []
    source.clone.assert_awaited_once()

    status_hash = await redis.hgetall(
        STATUS_HASH_KEY.format(run_id=str(original_id))
    )
    assert _decode_redis_mapping(status_hash)["status"] == "failed"


@pytest.mark.asyncio
async def test_reclaim_resources_worker_lost_marks_failed_publishes_event_and_schedules_retry_real_db(
    integration_app,
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    from qaplatform.engine.events import EVENT_STREAM_KEY, STATUS_HASH_KEY
    from qaplatform.engine.reclaim import HEARTBEAT_KEY
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.worker.settings import reclaim_resources

    original = seed_run["run"]
    original_id = original.id
    worker_id = "worker-lost-required-integration"
    execution_id = "container-worker-lost-required-integration"
    seed_run["pipeline"].retry_policy = {
        "max_attempts": 2,
        "retry_on": ["infra"],
        "backoff_seconds": 0,
    }
    original.status = RunStatusEnum.RUNNING
    original.worker_id = worker_id
    original.execution_id = execution_id
    original.retry_group_id = original.id
    await integration_db_session.commit()

    redis = integration_app.state.container.redis_client
    await redis.delete(
        HEARTBEAT_KEY.format(worker_id=worker_id),
        EVENT_STREAM_KEY.format(run_id=str(original_id)),
        STATUS_HASH_KEY.format(run_id=str(original_id)),
    )

    factory = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    arq = _FakeArq()
    docker_backend = AsyncMock()
    await reclaim_resources(
        {
            "db_session_factory": factory,
            "redis": redis,
            "arq_pool": arq,
            "settings": SimpleNamespace(
                max_concurrent_runs=10,
                max_concurrent_per_project=10,
            ),
            "docker_backend": docker_backend,
        }
    )

    integration_db_session.expire_all()
    original_row = (
        await integration_db_session.execute(
            select(Run).where(Run.id == original_id)
        )
    ).scalar_one()
    assert original_row.status == RunStatusEnum.FAILED
    assert original_row.worker_id is None
    assert "worker_lost" in (original_row.error_message or "")
    assert worker_id in (original_row.error_message or "")

    retry_run = (
        await integration_db_session.execute(
            select(Run).where(Run.source_run_id == original_id)
        )
    ).scalar_one()
    assert retry_run.status == RunStatusEnum.QUEUED
    assert retry_run.attempt == 2
    assert retry_run.retry_group_id == original_id
    assert retry_run.queue_name == "queue:medium"
    assert retry_run.arq_job_id == f"run:{retry_run.id}"
    assert retry_run.enqueued_at is not None
    assert len(arq.calls) == 1
    assert arq.calls[0]["args"] == ("execute_run", str(retry_run.id))
    assert arq.calls[0]["kwargs"]["_queue_name"] == "queue:medium"
    assert arq.calls[0]["kwargs"]["_job_id"] == f"run:{retry_run.id}"

    docker_backend.cleanup.assert_awaited_once_with(execution_id)

    status_hash = await redis.hgetall(
        STATUS_HASH_KEY.format(run_id=str(original_id))
    )
    assert _decode_redis_mapping(status_hash)["status"] == "failed"
    events = await redis.xrange(
        EVENT_STREAM_KEY.format(run_id=str(original_id)),
        count=1,
    )
    assert len(events) == 1
    event = _decode_redis_mapping(events[0][1])
    assert event["run_id"] == str(original_id)
    assert event["status"] == "failed"
    assert event["previous"] == "running"
