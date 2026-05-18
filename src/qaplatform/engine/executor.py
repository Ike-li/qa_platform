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

# F-PL-03 mandates a 30 s grace window between SIGTERM and SIGKILL when
# tearing down a stuck or cancelled container. This is the *upper bound*
# on how long ``_graceful_stop`` will wait — it returns as soon as the
# container exits, matching ``docker stop --time=30`` semantics.
GRACE_PERIOD_SECONDS = 30

# Cap on how long the executor waits for a log-follow task to drain after
# the container has been cleaned up. Without this, a stuck `_stream_container_logs`
# coroutine would block the run's finally block forever, leaving subsequent
# stages, the workdir teardown, and worker release dangling.
_LOG_DRAIN_TIMEOUT = 5


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
    async def is_cancel_requested(self, run_id: UUID | str) -> bool: ...
    async def update_execution_id(self, run_id: UUID | str, execution_id: str) -> None: ...
    async def update_git_sha(self, run_id: UUID | str, sha: str) -> None: ...
    async def commit(self) -> None: ...


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
        # P1-D: persistent flag the cancel watcher sets on every signal.
        # Initialised here (not just in execute()) so direct callers of
        # _run_stages / _check_cancel_boundary in tests still work.
        self._active_execution_id: str | None = None
        self._cancel_requested = asyncio.Event()

    async def _publish(self, run_id: str, status: str, previous: str | None = None) -> None:
        await publish_status_event(self.redis, run_id, status, previous=previous)

    async def execute(self, run: Run, pipeline: PipelineConfig) -> RunStatus:
        """Execute a full pipeline run. Returns the terminal RunStatus."""
        run_id = str(run.id)
        working_dir = Path(tempfile.mkdtemp(prefix=f"qap-{run_id[:8]}-"))

        self._active_execution_id = None
        # Reset across runs so a previous cancel doesn't bleed in. The
        # event still lives on the instance so test paths that call
        # _run_stages directly see a usable Event.
        self._cancel_requested.clear()
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
            # Commit so the RUNNING transition is visible to other connections (cancel API, SSE).
            await self.run_repo.commit()
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
            # Commit so the COLLECTING transition is visible to other connections.
            await self.run_repo.commit()
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

    async def _drain_log_task(self, log_task: asyncio.Task) -> None:
        """Bounded await on a `_stream_container_logs` task.

        After the container has been cleaned up, the log follow loop
        should observe the close and return promptly. We still cap the
        wait at ``_LOG_DRAIN_TIMEOUT`` so a stalled docker logs stream
        cannot pin the run's finally block, leaving the workdir + worker
        slot held indefinitely.
        """
        if log_task.done():
            try:
                log_task.result()
            except Exception:
                pass
            return
        try:
            await asyncio.wait_for(asyncio.shield(log_task), timeout=_LOG_DRAIN_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning("log task did not drain within %ss; cancelling", _LOG_DRAIN_TIMEOUT)
            log_task.cancel()
            await asyncio.gather(log_task, return_exceptions=True)
        except Exception:
            log.warning("log task raised during drain", exc_info=True)

    async def _graceful_stop(self, execution_id: str, *, reason: str) -> None:
        """SIGTERM → bounded wait (≤30 s) → SIGKILL teardown.

        Shared by the cancel signal path (F-EX-06) and the stage timeout
        path (F-PL-03). The 30 s grace window is an *upper bound* — the
        same semantics as ``docker stop --time=30``. We return as soon as
        the container exits and only escalate to SIGKILL if it ignores
        SIGTERM for the full grace period. Each step swallows backend
        errors so a hiccup mid-teardown cannot leave the run in a
        half-cancelled state.
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

        # Bounded wait: containers usually exit immediately on SIGTERM, so
        # a short-circuit here keeps cancel propagation under the F-EX-06
        # < 10 s budget. Only escalate when the container ignores SIGTERM
        # for the full F-PL-03 grace window.
        try:
            await asyncio.wait_for(
                self.backend.wait(execution_id, GRACE_PERIOD_SECONDS),
                timeout=GRACE_PERIOD_SECONDS,
            )
            log.info(
                "container %s exited within grace period", execution_id[:12]
            )
            return
        except asyncio.TimeoutError:
            log.warning(
                "container %s ignored SIGTERM, escalating to SIGKILL",
                execution_id[:12],
            )
        except Exception:
            # backend.wait may raise other errors (already-removed,
            # daemon hiccup); don't block the SIGKILL path.
            log.warning(
                "wait after SIGTERM failed for %s",
                execution_id,
                exc_info=True,
            )

        try:
            await self.backend.force_kill(execution_id)
            log.info("force-killed container %s after grace period", execution_id[:12])
        except Exception:
            log.warning("force_kill failed for %s", execution_id, exc_info=True)

    async def _handle_cancel_signal(self, run_id: str) -> None:
        """Cancel callback wired to the redis cancel channel.

        Sets the persistent ``_cancel_requested`` flag (so stage / setup
        boundaries can short-circuit even if no container is active when
        the signal arrives), then sends SIGTERM to whatever container is
        currently running. The 30s grace window matches F-PL-03's
        contract for OOM/timeout teardown so cancel and resource-limit
        terminations behave the same way.
        """
        self._cancel_requested.set()

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

    async def _check_cancel_boundary(self, run_id: str) -> bool:
        """Return True if the run should stop at this stage boundary.

        P1-D guard against two failure modes:

        1. **Pub/sub race** — the cancel API publishes to redis pub/sub
           which is fire-and-forget. If the worker subscribed *after* the
           publish, the message is lost. The cancel API also persists
           ``cancel_requested_at`` on the row, so a fresh SELECT recovers
           any dropped notification.
        2. **Stage transition race** — the watcher's callback only had
           a container to SIGTERM if ``_active_execution_id`` was set
           when the message arrived. Between stages it briefly is None.
           ``_cancel_requested`` is now set in the watcher callback
           regardless, so we still see the request here.
        """
        if self._cancel_requested.is_set():
            return True
        try:
            if await self.run_repo.is_cancel_requested(run_id):
                self._cancel_requested.set()
                return True
        except Exception:
            log.warning(
                "is_cancel_requested probe failed for %s", run_id, exc_info=True
            )
        return False

    async def _run_stages(self, run: Run, pipeline: PipelineConfig, working_dir: Path) -> ExitResult:
        """Run all stages sequentially using Docker containers."""
        # ExitResult requires started_at/finished_at; seed both to "now" so
        # a no-stage / all-pass pipeline still returns a well-formed result
        # (the executor calls .timed_out / .oom_killed on this further down).
        _now = datetime.now(timezone.utc)
        final_exit = ExitResult(exit_code=0, started_at=_now, finished_at=_now)

        for stage in pipeline.stages:
            if await self._check_cancel_boundary(str(run.id)):
                await self.log_stream.write_log(
                    str(run.id),
                    f"Cancel requested before stage '{stage.name}'; stopping",
                    stream="stderr",
                )
                break
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
            # Commit so the execution_id row update releases the run row lock
            # before backend.wait() blocks for the stage timeout — otherwise
            # cancel API's UPDATE on the same row stalls until the stage ends.
            await self.run_repo.commit()
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
                # Cleanup container first so the log follow loop sees EOF
                # and exits naturally; only then bound-await the log task
                # so a stalled docker logs stream cannot pin this run's
                # finally block forever (P1-C).
                try:
                    await self.backend.cleanup(execution_id)
                except Exception:
                    log.warning("failed to cleanup container %s", execution_id)
                await self._drain_log_task(log_task)
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
            # Release the row lock immediately so cancel API isn't blocked
            # by the long preparing/clone window before mark_running commits.
            await self.run_repo.commit()

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
        # Setup gets a tighter cap than stage timeout to keep slow scripts
        # from eating into stage time. Cap at min(pipeline_timeout, 600s).
        setup_timeout = min(pipeline.timeout_seconds, 600)
        setup_started_at = datetime.now(timezone.utc)
        try:
            # Outer guard mirrors _run_stages: if backend.wait ignores the
            # timeout (already-known risk), wait_for prevents setup from
            # pinning the run forever. On timeout we run the same SIGTERM
            # → 30s → SIGKILL teardown the stage path uses (P1-B).
            try:
                exit_result = await asyncio.wait_for(
                    self.backend.wait(execution_id, setup_timeout),
                    timeout=setup_timeout + 5,
                )
            except asyncio.TimeoutError:
                await self.log_stream.write_log(
                    run_id,
                    f"Setup script exceeded timeout {setup_timeout}s, sending SIGTERM",
                    stream="stderr",
                )
                await self._graceful_stop(
                    execution_id,
                    reason=f"setup timeout {setup_timeout}s",
                )
                exit_result = ExitResult(
                    exit_code=-1,
                    started_at=setup_started_at,
                    finished_at=datetime.now(timezone.utc),
                    timed_out=True,
                )
        finally:
            try:
                await self.backend.cleanup(execution_id)
            except Exception:
                log.warning("failed to cleanup setup container %s", execution_id)
            await self._drain_log_task(log_task)
            self._active_execution_id = None

        if exit_result.timed_out:
            raise RuntimeError(f"Setup script timed out after {setup_timeout}s")
        if exit_result.exit_code != 0:
            raise RuntimeError(f"Setup script failed (exit {exit_result.exit_code})")

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
