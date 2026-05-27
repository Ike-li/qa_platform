"""Real PostgreSQL coverage for automatic retry scheduling."""

from __future__ import annotations

import asyncio
import os
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
