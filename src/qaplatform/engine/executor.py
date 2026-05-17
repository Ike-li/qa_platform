from __future__ import annotations

import asyncio
import logging
import mimetypes
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Protocol
from uuid import UUID

from qaplatform.domain.models.run import Run, RunStatus
from qaplatform.engine.cancel import watch_for_cancel
from qaplatform.engine.docker_backend import (
    DockerBackend,
    ExecutionSpec,
    ExitResult,
    Mount,
    ResourceLimits,
    SandboxSecurity,
)
from qaplatform.engine.events import publish_status_event
from qaplatform.engine.log_stream import LogStream
from qaplatform.plugins.registry import PluginRegistry

_ARTIFACT_TYPE_BY_EXT = {
    ".xml": "junit",
    ".html": "report",
    ".htm": "report",
    ".json": "json",
    ".log": "log",
    ".txt": "log",
}

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Repository protocol (dependency injection, avoids ORM coupling)
# --------------------------------------------------------------------------- #


class RunRepositoryProtocol(Protocol):
    """Minimal run repository interface needed by the executor."""

    async def get(self, run_id: UUID | str) -> Run | None: ...
    async def mark_running(self, run_id: UUID | str) -> None: ...
    async def mark_collecting(self, run_id: UUID | str) -> None: ...
    async def finish_if_current(
        self,
        run_id: UUID | str,
        *,
        status: RunStatus,
        expected_in: Collection[RunStatus] | None = None,
        summary: dict[str, Any] | None = None,
    ) -> bool: ...
    async def fail_if_current(
        self,
        run_id: UUID | str,
        *,
        expected_in: Collection[RunStatus] | None = None,
        message: str = "",
    ) -> bool: ...
    async def cancel_if_current(
        self,
        run_id: UUID | str,
        *,
        expected_in: Collection[RunStatus] | None = None,
    ) -> bool: ...
    async def update_execution_id(self, run_id: UUID | str, execution_id: str) -> None: ...
    async def update_git_sha(self, run_id: UUID | str, sha: str) -> None: ...


# --------------------------------------------------------------------------- #
# Pipeline/config types
# --------------------------------------------------------------------------- #


class StageDefinition:
    """Represents a single stage in a pipeline."""

    def __init__(
        self,
        name: str,
        plugin: str,
        phase: str = "execute",
        config: dict[str, Any] | None = None,
        continue_on_error: bool = False,
    ) -> None:
        self.name = name
        self.plugin = plugin
        self.phase = phase
        self.config = config or {}
        self.continue_on_error = continue_on_error


class PipelineConfig:
    """Pipeline configuration for an execution run."""

    def __init__(
        self,
        image: str,
        stages: list[StageDefinition],
        env_vars: dict[str, str] | None = None,
        resource_limits: ResourceLimits | None = None,
        network_policy: str = "deny",
        timeout_seconds: int = 1800,
        setup_script: str | None = None,
    ) -> None:
        self.image = image
        self.stages = stages
        self.env_vars = env_vars or {}
        self.resource_limits = resource_limits or ResourceLimits()
        self.network_policy = network_policy
        self.timeout_seconds = timeout_seconds
        self.setup_script = setup_script


# --------------------------------------------------------------------------- #
# RunExecutor
# --------------------------------------------------------------------------- #


class RunExecutor:
    """Orchestrates the full execution lifecycle of a Run.

    Flow:
    1. clone repo (git clone --depth 1)
    2. run setup_script
    3. execute Runner plugins per stage
    4. collect results via Collector plugins
    5. upload artifacts to S3
    6. write terminal state (finish_if_current)
    """

    def __init__(
        self,
        backend: DockerBackend,
        log_stream: LogStream,
        run_repo: RunRepositoryProtocol,
        plugin_registry: PluginRegistry | None = None,
        s3_client: Any = None,
        s3_bucket: str = "qa-platform",
        workspace_dir: str = "/workspace",
        artifact_repo: Any = None,
        redis: Any = None,
    ) -> None:
        self.backend = backend
        self.log_stream = log_stream
        self.run_repo = run_repo
        self.plugin_registry = plugin_registry
        self.s3_client = s3_client
        self.s3_bucket = s3_bucket
        self.workspace_dir = workspace_dir
        self.artifact_repo = artifact_repo
        self.redis = redis

    async def _publish(self, run_id: str, status: str, previous: str | None = None) -> None:
        await publish_status_event(self.redis, run_id, status, previous=previous)

    async def execute(self, run: Run, pipeline: PipelineConfig) -> RunStatus:
        """Execute a full pipeline run. Returns the terminal RunStatus."""
        run_id = str(run.id)
        working_dir = Path(tempfile.mkdtemp(prefix=f"qap-{run_id[:8]}-"))

        self._active_execution_id: str | None = None
        cancel_stop = asyncio.Event()
        cancel_task = asyncio.create_task(
            watch_for_cancel(
                self.redis,
                run_id,
                lambda: self._handle_cancel_signal(run_id),
                cancel_stop,
            )
        )

        try:
            # 1. Clone repository
            await self._clone_repo(run, working_dir)
            await self.log_stream.write_log(run_id, "Repository cloned successfully")

            # 2. Run setup script
            if pipeline.setup_script:
                await self._run_setup(run, pipeline, working_dir)

            # 3. Run all stages
            await self.run_repo.mark_running(run_id)
            await self._publish(run_id, RunStatus.RUNNING.value, previous=RunStatus.PREPARING.value)
            exit_result = await self._run_stages(run, pipeline, working_dir)

            if exit_result.exit_code != 0:
                await self.log_stream.write_log(
                    run_id,
                    f"Pipeline failed with code {exit_result.exit_code}",
                    stream="stderr",
                )

            # 4. Collect results
            await self.run_repo.mark_collecting(run_id)
            await self._publish(run_id, RunStatus.COLLECTING.value, previous=RunStatus.RUNNING.value)
            await self.log_stream.write_log(run_id, "Collecting test results...")

            collector = self.plugin_registry.get_collector("junit")

            results = await collector.collect(run.id, working_dir)
            passed = sum(1 for r in results if r.status == "passed")
            failed = sum(1 for r in results if r.status == "failed")
            skipped = sum(1 for r in results if r.status == "skipped")
            error = sum(1 for r in results if r.status == "error")
            total = passed + failed + skipped + error

            summary = {
                "total": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "error": error,
                "pass_rate": passed / total if total > 0 else 0.0,
            }

            # 5. Upload artifacts to S3
            if self.s3_client:
                await self._upload_artifacts(run_id, working_dir)

            # 6. Write terminal state
            status = RunStatus.DONE
            if exit_result.oom_killed or exit_result.timed_out:
                status = RunStatus.TIMEOUT
            elif exit_result.exit_code != 0:
                status = RunStatus.FAILED

            updated = await self.run_repo.finish_if_current(
                run_id,
                status=status,
                summary=summary,
            )
            if updated:
                await self._publish(run_id, status.value, previous=RunStatus.COLLECTING.value)
                await self.log_stream.write_log(run_id, f"Run completed: {status.value}")

            return status

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("execution failed for run %s", run_id)
            failed = await self.run_repo.fail_if_current(run_id, message=str(exc))
            if failed:
                await self._publish(run_id, RunStatus.FAILED.value)
            return RunStatus.FAILED
        finally:
            cancel_stop.set()
            if not cancel_task.done():
                cancel_task.cancel()
            try:
                await cancel_task
            except (asyncio.CancelledError, Exception):
                pass
            try:
                shutil.rmtree(working_dir, ignore_errors=True)
            except Exception:
                pass

    async def _graceful_stop(self, execution_id: str, *, reason: str) -> None:
        """SIGTERM → 30 s grace → SIGKILL teardown.

        Shared by the cancel signal path (F-EX-06) and the stage timeout
        path (F-PL-03). Each step swallows backend errors so a hiccup
        mid-teardown cannot leave the run in a half-cancelled state.
        """
        log.info(
            "graceful stop for container %s (reason=%s) -> SIGTERM",
            execution_id[:12],
            reason,
        )
        try:
            await self.backend.cancel(execution_id)
        except Exception:
            log.warning("cancel(SIGTERM) failed for %s", execution_id, exc_info=True)

        await asyncio.sleep(30)

        # Force-kill if still running. backend.force_kill is a no-op on
        # already-stopped containers (it logs and returns), so this is safe
        # even when the container exited gracefully on SIGTERM.
        try:
            await self.backend.force_kill(execution_id)
            log.info("force-killed container %s after grace period", execution_id[:12])
        except Exception:
            log.warning("force_kill failed for %s", execution_id, exc_info=True)

    async def _handle_cancel_signal(self, run_id: str) -> None:
        """Cancel callback wired to the redis cancel channel.

        Sends SIGTERM to the active container, waits 30 s for graceful
        shutdown, then SIGKILL if the container is still running. The 30 s
        grace window matches F-PL-03's contract for OOM/timeout teardown
        so cancel and resource-limit terminations behave the same way.
        """
        execution_id = self._active_execution_id
        if execution_id is None:
            log.info("cancel signal for run %s but no active container", run_id)
            return

        await self._graceful_stop(
            execution_id,
            reason=f"cancel signal received for run {run_id}",
        )

    # --------------------------------------------------------------------- #
    # private steps
    # --------------------------------------------------------------------- #

    async def _run_stages(self, run: Run, pipeline: PipelineConfig, working_dir: Path) -> ExitResult:
        """Run all stages sequentially using Docker containers."""
        # ExitResult requires started_at/finished_at; seed both to "now" so
        # a no-stage / all-pass pipeline still returns a well-formed result
        # (the executor calls .timed_out / .oom_killed on this further down).
        _now = datetime.now(timezone.utc)
        final_exit = ExitResult(exit_code=0, started_at=_now, finished_at=_now)
        
        for stage in pipeline.stages:
            await self.log_stream.write_log(str(run.id), f"Starting stage: {stage.name}")
            
            try:
                runner = self.plugin_registry.get_runner(stage.plugin)
                if hasattr(runner, 'build_command'):
                    cmd = runner.build_command(stage.config)
                else:
                    cmd = stage.config.get('command', 'echo "missing command"')
            except Exception as e:
                log.warning("failed to get runner for %s: %s", stage.plugin, e)
                cmd = stage.config.get('command', 'echo "missing command"')
                
            spec = ExecutionSpec(
                image=pipeline.image,
                command=["sh", "-c", cmd],
                env_vars=pipeline.env_vars,
                mounts=[
                    Mount(source=str(working_dir), target="/workspace", read_only=False),
                ],
                resource_limits=pipeline.resource_limits,
                network_policy=pipeline.network_policy,
                labels={"run_id": str(run.id), "stage": stage.name},
            )
            
            execution_id = await self.backend.create_execution(spec)
            await self.run_repo.update_execution_id(str(run.id), execution_id)
            self._active_execution_id = execution_id

            await self.backend.start(execution_id)

            # Stream logs in background while waiting
            log_task = asyncio.create_task(self._stream_container_logs(str(run.id), execution_id))

            stage_started_at = datetime.now(timezone.utc)
            try:
                # Outer guard so an unresponsive container (e.g. ignoring
                # the wait() timeout in the backend) cannot stall this
                # coroutine indefinitely. We then run the SIGTERM → 30 s →
                # SIGKILL teardown that F-PL-03 mandates and synthesise a
                # timed-out ExitResult so downstream status mapping
                # (RunStatus.TIMEOUT at executor.py around line 228) fires.
                try:
                    exit_result = await asyncio.wait_for(
                        self.backend.wait(execution_id, pipeline.timeout_seconds),
                        timeout=pipeline.timeout_seconds + 5,
                    )
                except asyncio.TimeoutError:
                    await self.log_stream.write_log(
                        str(run.id),
                        f"Stage '{stage.name}' exceeded timeout "
                        f"{pipeline.timeout_seconds}s, sending SIGTERM",
                        stream="stderr",
                    )
                    await self._graceful_stop(
                        execution_id,
                        reason=f"stage '{stage.name}' timeout {pipeline.timeout_seconds}s",
                    )
                    exit_result = ExitResult(
                        exit_code=-1,
                        started_at=stage_started_at,
                        finished_at=datetime.now(timezone.utc),
                        timed_out=True,
                    )
            finally:
                await log_task
                try:
                    await self.backend.cleanup(execution_id)
                except Exception:
                    log.warning("failed to cleanup container %s", execution_id)
                self._active_execution_id = None

            if exit_result.exit_code != 0:
                final_exit = exit_result
                if not stage.continue_on_error:
                    break
                    
        return final_exit

    async def _clone_repo(self, run: Run, dest: Path) -> None:
        """Clone the repository using the SourceProtocol plugin."""
        metadata = getattr(run, 'metadata_', None) or getattr(run, 'metadata', None) or {}
        git_url = metadata.get("git_url", "")
        if not git_url:
            await self.log_stream.write_log(str(run.id), "No git_url in metadata, using workspace")
            return

        source = self.plugin_registry.get_source("git")
        revision = await source.clone(git_url, run.git_ref, dest)

        if revision.sha:
            await self.run_repo.update_git_sha(run.id, revision.sha)

    async def _run_setup(
        self,
        run: Run,
        pipeline: PipelineConfig,
        working_dir: Path,
    ) -> None:
        """Run the environment setup script inside the same sandbox image as
        the stages.

        Setup scripts come from user-controlled environment configuration. We
        execute them in a Docker container with the same isolation profile as
        regular stages (read-write workspace mount, configured network policy,
        resource limits) — never on the worker host. A non-zero exit aborts
        the run.
        """
        run_id = str(run.id)
        await self.log_stream.write_log(run_id, "Running setup script...")

        spec = ExecutionSpec(
            image=pipeline.image,
            command=["sh", "-c", pipeline.setup_script or ""],
            env_vars=pipeline.env_vars,
            mounts=[
                Mount(source=str(working_dir), target="/workspace", read_only=False),
            ],
            resource_limits=pipeline.resource_limits,
            network_policy=pipeline.network_policy,
            labels={"run_id": run_id, "phase": "setup"},
        )

        execution_id = await self.backend.create_execution(spec)
        await self.backend.start(execution_id)
        self._active_execution_id = execution_id

        log_task = asyncio.create_task(self._stream_container_logs(run_id, execution_id))
        try:
            # Setup gets a tighter cap than stage timeout to keep slow scripts
            # from eating into stage time. Cap at min(pipeline_timeout, 600s).
            setup_timeout = min(pipeline.timeout_seconds, 600)
            exit_result = await self.backend.wait(execution_id, setup_timeout)
        finally:
            await log_task
            try:
                await self.backend.cleanup(execution_id)
            except Exception:
                log.warning("failed to cleanup setup container %s", execution_id)
            self._active_execution_id = None

        if exit_result.timed_out:
            raise RuntimeError(f"Setup script timed out after {setup_timeout}s")
        if exit_result.exit_code != 0:
            raise RuntimeError(f"Setup script failed (exit {exit_result.exit_code})")


    async def _stream_container_logs(self, run_id: str, execution_id: str) -> None:
        """Stream container logs to Redis. Runs as a background task."""
        try:
            async for log_line in self.backend.stream_logs(execution_id):
                await self.log_stream.write_log(run_id, log_line.content, stream=log_line.stream)
        except Exception:
            log.debug("log streaming ended for container %s", execution_id)

    async def _upload_artifacts(self, run_id: str, working_dir: Path) -> None:
        """Upload result artifacts from working directory to S3 and record rows."""
        results_dir = working_dir / "results"
        if not results_dir.exists():
            return

        for artifact_path in results_dir.iterdir():
            if not artifact_path.is_file():
                continue
            s3_key = f"reports/{run_id}/{artifact_path.name}"
            try:
                content = artifact_path.read_bytes()
                await self.s3_client.put_object(
                    Bucket=self.s3_bucket,
                    Key=s3_key,
                    Body=content,
                )
            except Exception:
                log.warning("failed to upload artifact %s", artifact_path)
                continue

            if self.artifact_repo is not None:
                ext = artifact_path.suffix.lower()
                artifact_type = _ARTIFACT_TYPE_BY_EXT.get(ext, "other")
                mime_type, _ = mimetypes.guess_type(artifact_path.name)
                try:
                    await self.artifact_repo.create(
                        run_id=UUID(run_id) if isinstance(run_id, str) else run_id,
                        type=artifact_type,
                        name=artifact_path.name,
                        storage_path=s3_key,
                        size_bytes=len(content),
                        mime_type=mime_type or "application/octet-stream",
                    )
                except Exception:
                    log.warning(
                        "failed to record artifact row for %s",
                        artifact_path,
                        exc_info=True,
                    )

            await self.log_stream.write_log(
                run_id,
                f"Uploaded artifact: {artifact_path.name}",
            )
