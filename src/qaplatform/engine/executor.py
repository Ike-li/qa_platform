from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qaplatform.domain.models.run import Run, RunStatus
from qaplatform.engine.docker_backend import (
    DockerBackend,
    ExecutionSpec,
    ExitResult,
    Mount,
    ResourceLimits,
    SandboxSecurity,
)
from qaplatform.engine.log_stream import LogStream
from qaplatform.plugins.builtin.junit_collector import JUnitCollector
from qaplatform.plugins.builtin.pytest_runner import PytestRunner

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
        summary: dict[str, Any] | None = None,
    ) -> bool: ...
    async def fail_if_current(
        self,
        run_id: UUID | str,
        *,
        message: str = "",
    ) -> bool: ...
    async def cancel_if_current(self, run_id: UUID | str) -> bool: ...
    async def update_execution_id(self, run_id: UUID | str, execution_id: str) -> None: ...


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
        s3_client: Any = None,
        s3_bucket: str = "qa-platform",
        workspace_dir: str = "/workspace",
    ) -> None:
        self.backend = backend
        self.log_stream = log_stream
        self.run_repo = run_repo
        self.s3_client = s3_client
        self.s3_bucket = s3_bucket
        self.workspace_dir = workspace_dir

    async def execute(self, run: Run, pipeline: PipelineConfig) -> RunStatus:
        """Execute a full pipeline run. Returns the terminal RunStatus."""
        run_id = str(run.id)
        working_dir = Path(tempfile.mkdtemp(prefix=f"qap-{run_id[:8]}-"))
        execution_id: str | None = None

        try:
            # 1. Clone repository
            await self._clone_repo(run, working_dir)
            await self.log_stream.write_log(run_id, "Repository cloned successfully")

            # 2. Run setup script
            if pipeline.setup_script:
                await self._run_setup(pipeline.setup_script, working_dir, pipeline.env_vars)

            # 3. Create and start container
            execution_id = await self._create_container(run, pipeline, working_dir)
            await self.run_repo.update_execution_id(run_id, execution_id)
            await self.backend.start(execution_id)
            await self.run_repo.mark_running(run_id)

            # 4. Stream logs from container
            await self._stream_container_logs(run_id, execution_id)

            # 5. Wait for container exit
            exit_result = await self.backend.wait(execution_id, pipeline.timeout_seconds)

            if exit_result.exit_code != 0:
                await self.log_stream.write_log(
                    run_id,
                    f"Container exited with code {exit_result.exit_code}",
                    stream="stderr",
                )

            # 6. Collect results
            await self.run_repo.mark_collecting(run_id)
            await self.log_stream.write_log(run_id, "Collecting test results...")

            test_runner = PytestRunner()
            collector = JUnitCollector()

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

            # 7. Upload artifacts to S3
            if self.s3_client:
                await self._upload_artifacts(run_id, working_dir)

            # 8. Write terminal state
            status = RunStatus.DONE
            if exit_result.oom_killed or exit_result.timed_out:
                status = RunStatus.TIMEOUT

            updated = await self.run_repo.finish_if_current(
                run_id,
                status=status,
                summary=summary,
            )
            if updated:
                await self.log_stream.write_log(run_id, f"Run completed: {status.value}")

            return status

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("execution failed for run %s", run_id)
            await self.run_repo.fail_if_current(run_id, message=str(exc))
            return RunStatus.FAILED
        finally:
            # Best-effort cleanup
            if execution_id:
                try:
                    await self.backend.cleanup(execution_id)
                except Exception:
                    log.warning("failed to cleanup container %s", execution_id)

            try:
                shutil.rmtree(working_dir, ignore_errors=True)
            except Exception:
                pass

    # --------------------------------------------------------------------- #
    # private steps
    # --------------------------------------------------------------------- #

    async def _clone_repo(self, run: Run, dest: Path) -> None:
        """Clone the repository at the specified git ref."""
        # For MVP, assume git_url is available from run metadata
        git_url = run.metadata.get("git_url", "")
        if not git_url:
            await self.log_stream.write_log(str(run.id), "No git_url in metadata, using workspace")
            return

        cmd = ["git", "clone", "--depth", "1", "--branch", run.git_ref, git_url, str(dest)]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git clone failed (exit {process.returncode}): {err_msg}")

    async def _run_setup(
        self,
        script: str,
        working_dir: Path,
        env_vars: dict[str, str],
    ) -> None:
        """Run the environment setup script inside the working directory."""
        await self.log_stream.write_log(
            str(working_dir.name),
            "Running setup script...",
        )
        process = await asyncio.create_subprocess_shell(
            script,
            cwd=str(working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env_vars},
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"Setup script failed (exit {process.returncode}): {err_msg}")

    async def _create_container(
        self,
        run: Run,
        pipeline: PipelineConfig,
        working_dir: Path,
    ) -> str:
        """Create a Docker container for the run."""
        spec = ExecutionSpec(
            image=pipeline.image,
            command=["sh", "-c", "cd /workspace && python -m pytest --junitxml=results/junit.xml tests/"],
            env_vars=pipeline.env_vars,
            mounts=[
                Mount(source=str(working_dir), target="/workspace", read_only=False),
            ],
            resource_limits=pipeline.resource_limits,
            network_policy=pipeline.network_policy,
            labels={"run_id": str(run.id)},
        )
        return await self.backend.create_execution(spec)

    async def _stream_container_logs(self, run_id: str, execution_id: str) -> None:
        """Stream container logs to Redis. Runs as a background task."""
        try:
            async for log_line in self.backend.stream_logs(execution_id):
                await self.log_stream.write_log(run_id, log_line.content, stream=log_line.stream)
        except Exception:
            log.debug("log streaming ended for container %s", execution_id)

    async def _upload_artifacts(self, run_id: str, working_dir: Path) -> None:
        """Upload result artifacts from working directory to S3."""
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
                await self.log_stream.write_log(
                    run_id,
                    f"Uploaded artifact: {artifact_path.name}",
                )
            except Exception:
                log.warning("failed to upload artifact %s", artifact_path)
