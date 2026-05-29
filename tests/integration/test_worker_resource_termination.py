"""Real DB/Redis evidence for worker resource termination outcomes."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


class _TerminationRunner:
    def build_command(self, _config):
        return "pytest -q"


class _EmptyCollector:
    async def collect(self, _run_id, _working_dir):
        return []


class _TerminationPluginRegistry:
    def get_runner(self, _name):
        return _TerminationRunner()

    def get_collector(self, _name):
        return _EmptyCollector()


class _TerminationBackend:
    def __init__(self, *, exit_code: int, oom_killed: bool, timed_out: bool) -> None:
        self.exit_code = exit_code
        self.oom_killed = oom_killed
        self.timed_out = timed_out
        self.execution_id = f"resource-termination-{uuid4().hex}"
        self.cleanup_calls = 0

    async def create_execution(self, _spec):
        return self.execution_id

    async def start(self, _execution_id):
        return None

    async def wait(self, _execution_id, _timeout):
        from qaplatform.engine.docker_backend import ExitResult

        await asyncio.sleep(0)
        now = datetime.now(timezone.utc)
        return ExitResult(
            exit_code=self.exit_code,
            started_at=now,
            finished_at=now,
            oom_killed=self.oom_killed,
            timed_out=self.timed_out,
        )

    async def stream_resource_usage(self, _execution_id):
        from qaplatform.engine.docker_backend import ResourceUsageSample

        now = datetime.now(timezone.utc)
        yield ResourceUsageSample(
            timestamp=now,
            memory_usage_bytes=64 * 1024 * 1024,
            memory_limit_bytes=128 * 1024 * 1024,
            memory_max_usage_bytes=96 * 1024 * 1024,
            cpu_percent=125.5,
            pids_current=4,
        )

    async def cleanup(self, _execution_id):
        self.cleanup_calls += 1

    async def stream_logs(self, _execution_id):
        if False:
            yield


async def _create_preparing_run(integration_db_session, seed_ids, *, git_ref: str):
    from qaplatform.infra.database.models import Run, RunStatusEnum

    run = Run(
        tenant_id=seed_ids["tenant_id"],
        project_id=seed_ids["project_id"],
        pipeline_id=seed_ids["pipeline_id"],
        environment_id=seed_ids["environment_id"],
        status=RunStatusEnum.PREPARING,
        trigger_type="manual",
        priority=1,
        triggered_by=seed_ids["user_id"],
        git_ref=git_ref,
        attempt=1,
        chain_depth=0,
        metadata_={"git_url": ""},
    )
    integration_db_session.add(run)
    await integration_db_session.commit()
    await integration_db_session.refresh(run)
    return run


def _decode_redis_mapping(mapping: dict) -> dict[str, str]:
    return {
        key.decode() if isinstance(key, bytes) else key: (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in mapping.items()
    }


@pytest.mark.asyncio
async def test_executor_resource_termination_persists_timeout_status_and_redis_event(
    integration_app,
    integration_db_session,
    seed_run,
):
    from qaplatform.domain.models.run import RunStatus
    from qaplatform.engine.events import EVENT_STREAM_KEY, STATUS_HASH_KEY
    from qaplatform.engine.executor import PipelineConfig, RunExecutor, StageDefinition
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import Run, RunStatusEnum
    from qaplatform.infra.database.repositories.run_repo import RunRepository

    redis = integration_app.state.container.redis_client
    seed_ids = {
        "tenant_id": seed_run["tenant"].id,
        "project_id": seed_run["project"].id,
        "pipeline_id": seed_run["pipeline"].id,
        "environment_id": seed_run["environment"].id,
        "user_id": seed_run["user"].id,
    }
    scenarios = [
        ("oom", _TerminationBackend(exit_code=137, oom_killed=True, timed_out=False)),
        ("timeout", _TerminationBackend(exit_code=-1, oom_killed=False, timed_out=True)),
    ]

    for scenario, backend in scenarios:
        run = await _create_preparing_run(
            integration_db_session,
            seed_ids,
            git_ref=f"resource-{scenario}/{uuid4().hex}",
        )
        run_id = run.id
        executor = RunExecutor(
            backend=backend,
            log_stream=LogStream(redis),
            run_repo=RunRepository(integration_db_session),
            plugin_registry=_TerminationPluginRegistry(),
            redis=redis,
        )
        pipeline = PipelineConfig(
            image="python:3.12-alpine",
            stages=[StageDefinition(name=scenario, plugin="pytest")],
            timeout_seconds=30,
        )

        status = await executor.execute(run, pipeline)
        assert status == RunStatus.TIMEOUT
        assert backend.cleanup_calls == 1

        integration_db_session.expire_all()
        persisted = await integration_db_session.get(Run, run_id)
        assert persisted is not None
        assert persisted.status == RunStatusEnum.TIMEOUT
        assert persisted.finished_at is not None
        assert persisted.summary is not None
        summary = dict(persisted.summary)
        resource_termination = summary.pop("resource_termination")
        assert summary == {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "pass_rate": 0.0,
        }
        expected_reason = "oom" if backend.oom_killed else "timeout"
        assert resource_termination["reason"] == expected_reason
        assert resource_termination["exit_code"] == backend.exit_code
        assert resource_termination["oom_killed"] is backend.oom_killed
        assert resource_termination["timed_out"] is backend.timed_out
        assert resource_termination["duration_ms"] >= 0
        assert resource_termination["started_at"]
        assert resource_termination["finished_at"]
        assert resource_termination["resource_usage"] == {
            "sample_count": 1,
            "memory_peak_bytes": 96 * 1024 * 1024,
            "memory_limit_bytes": 128 * 1024 * 1024,
            "memory_peak_percent": 75.0,
            "cpu_peak_percent": 125.5,
            "pids_peak": 4,
        }

        status_hash = await redis.hgetall(STATUS_HASH_KEY.format(run_id=str(run_id)))
        assert _decode_redis_mapping(status_hash)["status"] == "timeout"

        events = await redis.xrange(EVENT_STREAM_KEY.format(run_id=str(run_id)))
        assert events, f"{scenario} did not publish Redis status events"
        _event_id, latest_event = events[-1]
        decoded_event = _decode_redis_mapping(latest_event)
        assert decoded_event["status"] == "timeout"
        assert decoded_event["previous"] == "collecting"

        logs = await executor.log_stream.read_logs(run_id, count=100)
        lines = [entry["line"] for entry in logs]
        assert any(f"Starting stage: {scenario}" in line for line in lines)
        assert any(
            f"Pipeline failed with code {backend.exit_code}" in line
            for line in lines
        )
        assert any(
            f"Resource termination: reason={expected_reason}" in line
            for line in lines
        )
        assert any("Run completed: timeout" in line for line in lines)
