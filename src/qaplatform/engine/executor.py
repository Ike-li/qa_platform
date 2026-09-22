from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from opentelemetry import trace

from qaplatform.domain.models.run import Run, RunStatus
from qaplatform.domain.ports import (
    LogStreamProtocol,
    ObjectStorageProtocol,
    RunRepositoryProtocol,
)
from qaplatform.engine.cancel import watch_for_cancel
from qaplatform.engine.docker_backend import (
    DockerBackend,
    ExitResult,
    ResourceLimits,
)
from qaplatform.engine.events import publish_status_event
from qaplatform.engine import executor_artifacts as _executor_artifacts
from qaplatform.engine import executor_sources as _executor_sources
from qaplatform.engine import executor_specs as _executor_specs
from qaplatform.engine import executor_summaries as _executor_summaries
from qaplatform.engine import executor_workspace as _executor_workspace
from qaplatform.engine.executor_artifacts import (
    artifact_upload_info as _artifact_upload_info,
    iter_artifact_files as _iter_artifact_files,
)
from qaplatform.engine.executor_collectors import (
    collect_from_plugin as _collect_from_plugin,
    collector_accepts_config as _collector_accepts_config,
)
from qaplatform.engine.executor_results import (
    build_results_summary as _build_results_summary,
    build_test_result_rows as _build_test_result_rows,
)
from qaplatform.engine.executor_sources import (
    clone_ref_for_run as _clone_ref_for_run,
    git_url_for_run as _git_url_for_run,
)
from qaplatform.engine.executor_specs import (
    build_allure_report_execution_spec as _build_allure_report_execution_spec,
    build_setup_execution_spec as _build_setup_execution_spec,
    build_stage_execution_spec as _build_stage_execution_spec,
)
from qaplatform.engine.executor_summaries import (
    ResourceUsageTracker as _ResourceUsageTracker,
    attach_resource_usage as _attach_resource_usage,
    resource_termination_summary as _resource_termination_summary,
)
from qaplatform.engine.executor_terminal import (
    pipeline_failure_message as _pipeline_failure_message,
    resource_termination_log_message as _resource_termination_log_message,
    terminal_status_for_exit as _terminal_status_for_exit,
)
from qaplatform.engine.executor_tasks import (
    collect_resource_usage as _collect_resource_usage,
    drain_log_task as _drain_log_task,
    drain_resource_usage_task as _drain_resource_usage_task,
)
from qaplatform.engine import pipeline_config as _pipeline_config
from qaplatform.engine.redact import redact_sensitive_text
from qaplatform.plugins.registry import PluginRegistry

_ARTIFACT_TYPE_BY_EXT = _executor_artifacts.ARTIFACT_TYPE_BY_EXT
ExecutionSpec = _executor_specs.ExecutionSpec
_create_workspace_dir = _executor_workspace.create_workspace_dir
_failed_tests_summary = _executor_summaries.failed_tests_summary
_run_metadata = _executor_sources.run_metadata
CollectorDefinition = _pipeline_config.CollectorDefinition
PipelineConfig = _pipeline_config.PipelineConfig
StageDefinition = _pipeline_config.StageDefinition

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
_ALLURE_REPORT_TIMEOUT_SECONDS = 300
_FULL_GIT_SHA_RE = _executor_sources.FULL_GIT_SHA_RE

_INFRA_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)


# --------------------------------------------------------------------------- #
# Repository protocol (dependency injection, avoids ORM coupling)
# --------------------------------------------------------------------------- #



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
        log_stream: LogStreamProtocol,
        run_repo: RunRepositoryProtocol,
        plugin_registry: PluginRegistry | None = None,
        s3_client: ObjectStorageProtocol | None = None,
        s3_bucket: str = "qa-platform",
        workspace_dir: str = "/workspace",
        artifact_repo: Any = None,
        test_result_repo: Any = None,
        redis: Any = None,
        source_clone_timeout_seconds: int = 300,
    ) -> None:
        self.backend = backend
        self.log_stream = log_stream
        self.run_repo = run_repo
        self.plugin_registry = plugin_registry
        self.s3_client = s3_client
        self.s3_bucket = s3_bucket
        self.workspace_dir = workspace_dir
        self.artifact_repo = artifact_repo
        self.test_result_repo = test_result_repo
        self.redis = redis
        self.source_clone_timeout_seconds = source_clone_timeout_seconds
        # P1-D: persistent flag the cancel watcher sets on every signal.
        # Initialised here (not just in execute()) so direct callers of
        # _run_stages / _check_cancel_boundary in tests still work.
        self._active_execution_id: str | None = None
        self._cancel_requested = asyncio.Event()

    async def _publish(self, run_id: str, status: str, previous: str | None = None) -> None:
        await publish_status_event(self.redis, run_id, status, previous=previous)

    def _collector_accepts_config(self, collector: Any) -> bool:
        return _collector_accepts_config(collector)

    async def _collect_from_plugin(
        self,
        collector: Any,
        run_id: UUID,
        working_dir: Path,
        config: dict[str, Any],
    ) -> list[Any]:
        return await _collect_from_plugin(collector, run_id, working_dir, config)

    @staticmethod
    def _create_workspace_dir(run_id: str) -> Path:
        return _create_workspace_dir(run_id)

    async def execute(self, run: Run, pipeline: PipelineConfig) -> RunStatus:
        """Execute a full pipeline run. Returns the terminal RunStatus."""
        run_id = str(run.id)
        tracer = trace.get_tracer(__name__)
        working_dir = self._create_workspace_dir(run_id)

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
        source_clone_attributes = {"run.id": run_id}
        project_id = getattr(run, "project_id", None)
        if project_id is not None:
            source_clone_attributes["run.project_id"] = str(project_id)

        try:
            # 1. Clone repository
            with tracer.start_as_current_span(
                "source_clone",
                attributes=source_clone_attributes,
            ):
                try:
                    await asyncio.wait_for(
                        self._clone_repo(run, working_dir, pipeline.source_auth),
                        timeout=self.source_clone_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    await self.log_stream.write_log(
                        run_id,
                        "Source clone exceeded timeout "
                        f"{self.source_clone_timeout_seconds}s",
                        stream="stderr",
                    )
                    raise RuntimeError(
                        "Source clone timed out after "
                        f"{self.source_clone_timeout_seconds}s"
                    ) from exc
            await self.log_stream.write_log(run_id, "Repository cloned successfully")

            # 2. Run setup script
            if pipeline.setup_script:
                await self._run_setup(run, pipeline, working_dir)

            # 3. Run all stages
            if not await self.run_repo.mark_running(run_id):
                log.info(
                    "run_status_transition_skipped",
                    extra={
                        "run_id": str(run_id),
                        "from_": RunStatus.PREPARING.value,
                        "to": RunStatus.RUNNING.value,
                        "reason": "row not in expected state — likely cancelled concurrently",
                    },
                )
                return RunStatus.CANCELLED
            # Commit so the RUNNING transition is visible to other connections (cancel API, SSE).
            await self.run_repo.commit()
            await self._publish(run_id, RunStatus.RUNNING.value, previous=RunStatus.PREPARING.value)
            with tracer.start_as_current_span(
                "container_run",
                attributes={"run.id": run_id, "stage.count": len(pipeline.stages)},
            ):
                exit_result = await self._run_stages(run, pipeline, working_dir)

            if exit_result.exit_code != 0:
                await self.log_stream.write_log(
                    run_id,
                    _pipeline_failure_message(exit_result.exit_code),
                    stream="stderr",
                )
            resource_termination = _resource_termination_summary(exit_result)
            if resource_termination:
                await self.log_stream.write_log(
                    run_id,
                    _resource_termination_log_message(resource_termination),
                    stream="stderr",
                )

            # 4. Collect results
            if not await self.run_repo.mark_collecting(run_id):
                log.info(
                    "run_status_transition_skipped",
                    extra={
                        "run_id": str(run_id),
                        "from_": RunStatus.RUNNING.value,
                        "to": RunStatus.COLLECTING.value,
                        "reason": "row not in expected state — likely cancelled concurrently",
                    },
                )
                return RunStatus.CANCELLED
            # Commit so the COLLECTING transition is visible to other connections.
            await self.run_repo.commit()
            await self._publish(run_id, RunStatus.COLLECTING.value, previous=RunStatus.RUNNING.value)
            await self.log_stream.write_log(run_id, "Collecting test results...")

            enabled_collectors = [c for c in pipeline.collectors if c.enabled]
            collector_names = ",".join(c.plugin for c in enabled_collectors)
            with tracer.start_as_current_span(
                "collect_results",
                attributes={
                    "run.id": run_id,
                    "collector.count": len(enabled_collectors),
                    "collector.plugins": collector_names,
                },
            ):
                results = []
                for collector_config in enabled_collectors:
                    collector = self.plugin_registry.get_collector(collector_config.plugin)
                    collector_results = await self._collect_from_plugin(
                        collector,
                        run.id,
                        working_dir,
                        collector_config.config,
                    )
                    results.extend(collector_results)
                summary = _build_results_summary(results, resource_termination)

                if self.test_result_repo is not None and results:
                    await self.test_result_repo.bulk_create(
                        _build_test_result_rows(run.id, results)
                    )

            await self._generate_allure_report(run_id, working_dir, pipeline)

            # 5. Upload artifacts to S3
            with tracer.start_as_current_span(
                "upload_artifacts",
                attributes={
                    "run.id": run_id,
                    "artifact.upload.enabled": self.s3_client is not None,
                },
            ):
                if self.s3_client:
                    await self._upload_artifacts(
                        run_id,
                        working_dir,
                        pipeline.resource_limits,
                    )

            # 6. Write terminal state
            status = _terminal_status_for_exit(exit_result)

            updated = await self.run_repo.finish_if_current(
                run_id,
                status=status,
                summary=summary,
            )
            if updated:
                from qaplatform.observability.metrics import run_terminal_total
                run_terminal_total.labels(status=status.value).inc()
                await self._publish(run_id, status.value, previous=RunStatus.COLLECTING.value)
                await self.log_stream.write_log(run_id, f"Run completed: {status.value}")

            return status

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("execution failed for run %s", run_id)
            failed = await self.run_repo.fail_if_current(
                run_id, message=redact_sensitive_text(str(exc), pipeline.env_vars)
            )
            if failed:
                from qaplatform.observability.metrics import run_terminal_total
                run_terminal_total.labels(status=RunStatus.FAILED.value).inc()
                await self._publish(run_id, RunStatus.FAILED.value)
            if isinstance(exc, _INFRA_EXCEPTIONS):
                raise
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
        await _drain_log_task(log_task, timeout=_LOG_DRAIN_TIMEOUT)

    async def _collect_resource_usage(
        self,
        execution_id: str,
        tracker: _ResourceUsageTracker,
    ) -> None:
        """Collect best-effort resource stats for backends that expose them."""
        await _collect_resource_usage(self.backend, execution_id, tracker)

    async def _drain_resource_usage_task(self, usage_task: asyncio.Task | None) -> None:
        await _drain_resource_usage_task(usage_task)

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

            runner = self.plugin_registry.get_runner(stage.plugin)

            # 注入失败子集过滤（retry_failed）
            stage_config = dict(stage.config)
            retry_failed_cases = _run_metadata(run).get("retry_failed_cases")
            if retry_failed_cases and stage.plugin == "pytest":
                from qaplatform.domain.services.pytest_nodeid import reconstruct_nodeid

                nodeids = [
                    reconstruct_nodeid(case["suite"], case["name"])
                    for case in retry_failed_cases
                ]
                # nodeid 取代 test_path：两者都是 pytest 位置参数，
                # 同时传会让 pytest 重新收集整个目录，过滤就失效了
                stage_config["test_paths"] = nodeids
                stage_config.pop("test_path", None)

                await self.log_stream.write_log(
                    str(run.id),
                    f"Retry-failed: filtering to {len(nodeids)} test case(s)",
                )

            cmd = runner.build_command(stage_config)

            spec = _build_stage_execution_spec(
                run_id=str(run.id),
                stage_name=stage.name,
                image=pipeline.image,
                command=cmd,
                env_vars=pipeline.env_vars,
                working_dir=working_dir,
                resource_limits=pipeline.resource_limits,
                network_policy=pipeline.network_policy,
            )

            execution_id = await self.backend.create_execution(spec)
            await self.run_repo.update_execution_id(str(run.id), execution_id)
            # Commit so the execution_id row update releases the run row lock
            # before backend.wait() blocks for the stage timeout — otherwise
            # cancel API's UPDATE on the same row stalls until the stage ends.
            await self.run_repo.commit()
            self._active_execution_id = execution_id

            await self.backend.start(execution_id)

            log_task = asyncio.create_task(
                self._stream_container_logs(
                    str(run.id),
                    execution_id,
                    redact_env_vars=pipeline.env_vars,
                )
            )
            usage_tracker = _ResourceUsageTracker()
            usage_task = asyncio.create_task(
                self._collect_resource_usage(execution_id, usage_tracker)
            )

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
                # After wait() returns, the log follower should naturally drain
                # container stdout/stderr. Bound the await before cleanup so
                # removing the container does not cut off buffered Docker logs
                # on fast CI runners.
                await self._drain_log_task(log_task)
                try:
                    await self.backend.cleanup(execution_id)
                except Exception:
                    log.warning("failed to cleanup container %s", execution_id)
                await self._drain_resource_usage_task(usage_task)
                self._active_execution_id = None
            exit_result = _attach_resource_usage(exit_result, usage_tracker.summary())

            if exit_result.exit_code != 0:
                final_exit = exit_result
                if not stage.continue_on_error:
                    break

        return final_exit

    async def _clone_repo(
        self,
        run: Run,
        dest: Path,
        source_auth: dict[str, str] | None = None,
    ) -> None:
        """Clone the repository using the SourceProtocol plugin."""
        git_url = _git_url_for_run(run)
        if not git_url:
            await self.log_stream.write_log(str(run.id), "No git_url in metadata, using workspace")
            return

        source = self.plugin_registry.get_source("git")
        clone_ref = _clone_ref_for_run(run)
        if source_auth:
            revision = await source.clone(git_url, clone_ref, dest, source_auth)
        else:
            revision = await source.clone(git_url, clone_ref, dest)

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

        spec = _build_setup_execution_spec(
            run_id=run_id,
            pipeline=pipeline,
            working_dir=working_dir,
        )

        execution_id = await self.backend.create_execution(spec)
        await self.backend.start(execution_id)
        self._active_execution_id = execution_id

        log_task = asyncio.create_task(
            self._stream_container_logs(
                run_id,
                execution_id,
                redact_env_vars=pipeline.env_vars,
            )
        )
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
            await self._drain_log_task(log_task)
            try:
                await self.backend.cleanup(execution_id)
            except Exception:
                log.warning("failed to cleanup setup container %s", execution_id)
            self._active_execution_id = None

        if exit_result.timed_out:
            raise RuntimeError(f"Setup script timed out after {setup_timeout}s")
        if exit_result.exit_code != 0:
            raise RuntimeError(f"Setup script failed (exit {exit_result.exit_code})")


    async def _stream_container_logs(
        self,
        run_id: str,
        execution_id: str,
        *,
        redact_env_vars: dict[str, str] | None = None,
    ) -> None:
        """Stream container logs to Redis. Runs as a background task."""
        try:
            async for log_line in self.backend.stream_logs(execution_id):
                content = redact_sensitive_text(log_line.content, redact_env_vars)
                await self.log_stream.write_log(
                    run_id,
                    content,
                    stream=log_line.stream,
                )
        except Exception:
            log.debug("log streaming ended for container %s", execution_id)

    async def _upload_artifacts(
        self,
        run_id: str,
        working_dir: Path,
        resource_limits: ResourceLimits | None = None,
    ) -> None:
        """Upload result artifacts from working directory to S3 and record rows."""
        results_dir = working_dir / "results"
        if not results_dir.exists():
            return
        limits = resource_limits or ResourceLimits()
        uploaded_count = 0

        for artifact_path in _iter_artifact_files(results_dir):
            artifact = _artifact_upload_info(
                run_id=run_id,
                results_dir=results_dir,
                path=artifact_path,
            )
            if uploaded_count >= limits.max_artifacts_count:
                await self.log_stream.write_log(
                    run_id,
                    f"Skipped artifact {artifact.rel_path}: artifact count limit exceeded",
                    stream="stderr",
                )
                continue
            if artifact.size_bytes > limits.max_artifact_size_bytes:
                await self.log_stream.write_log(
                    run_id,
                    (
                        f"Skipped artifact {artifact.rel_path}: size "
                        f"{artifact.size_bytes} exceeds limit "
                        f"{limits.max_artifact_size_bytes} bytes"
                    ),
                    stream="stderr",
                )
                continue
            try:
                with open(artifact_path, "rb") as f:
                    await self.s3_client.put_object(
                        Bucket=self.s3_bucket,
                        Key=artifact.storage_path,
                        Body=f,
                    )
            except Exception:
                log.warning("failed to upload artifact %s", artifact_path)
                continue

            if self.artifact_repo is not None:
                try:
                    await self.artifact_repo.create(
                        run_id=UUID(run_id) if isinstance(run_id, str) else run_id,
                        type=artifact.type,
                        name=artifact.rel_path,
                        storage_path=artifact.storage_path,
                        size_bytes=artifact.size_bytes,
                        mime_type=artifact.mime_type,
                    )
                except Exception:
                    log.warning(
                        "failed to record artifact row for %s",
                        artifact_path,
                        exc_info=True,
                    )

            await self.log_stream.write_log(
                run_id,
                f"Uploaded artifact: {artifact.rel_path}",
            )
            uploaded_count += 1

    async def _generate_allure_report(
        self,
        run_id: str,
        working_dir: Path,
        pipeline: PipelineConfig,
    ) -> None:
        """Generate static Allure HTML inside the same execution image."""
        results_dir = working_dir / "results" / "allure-results"
        if not results_dir.exists() or not any(results_dir.iterdir()):
            return

        spec = _build_allure_report_execution_spec(
            run_id=run_id,
            pipeline=pipeline,
            working_dir=working_dir,
        )
        execution_id: str | None = None
        log_task: asyncio.Task | None = None
        try:
            execution_id = await self.backend.create_execution(spec)
            await self.backend.start(execution_id)
            log_task = asyncio.create_task(
                self._stream_container_logs(
                    run_id,
                    execution_id,
                    redact_env_vars=pipeline.env_vars,
                )
            )
            try:
                exit_result = await asyncio.wait_for(
                    self.backend.wait(execution_id, _ALLURE_REPORT_TIMEOUT_SECONDS),
                    timeout=_ALLURE_REPORT_TIMEOUT_SECONDS + 5,
                )
            except asyncio.TimeoutError:
                await self.log_stream.write_log(
                    run_id,
                    "Allure report generation timed out",
                    stream="stderr",
                )
                await self._graceful_stop(
                    execution_id,
                    reason="allure report generation timeout",
                )
                return
        except Exception as exc:
            log.warning("failed to generate Allure report for run %s", run_id, exc_info=True)
            detail = redact_sensitive_text(str(exc), pipeline.env_vars)
            await self.log_stream.write_log(
                run_id,
                f"Allure report generation failed: {detail}",
                stream="stderr",
            )
            return
        finally:
            if log_task is not None:
                await self._drain_log_task(log_task)
            if execution_id is not None:
                try:
                    await self.backend.cleanup(execution_id)
                except Exception:
                    log.warning("failed to cleanup Allure report container %s", execution_id)

        if exit_result.exit_code == 127:
            await self.log_stream.write_log(
                run_id,
                "Allure report generation skipped: allure CLI is not installed in the execution image",
                stream="stderr",
            )
            return
        if exit_result.exit_code != 0:
            await self.log_stream.write_log(
                run_id,
                f"Allure report generation failed with code {exit_result.exit_code}",
                stream="stderr",
            )
            return

        await self.log_stream.write_log(run_id, "Allure report generated: allure-report")
