from __future__ import annotations

import asyncio
import logging
import shlex
import stat
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from qaplatform.domain.models.run import Run, RunStatus
from qaplatform.engine.docker_backend import ExitResult
from qaplatform.engine.executor import PipelineConfig, RunExecutor
from qaplatform.plugins.protocols import SourceRevision
from qaplatform.plugins.registry import PluginRegistry


@pytest.fixture
def mock_backend():
    backend = AsyncMock()
    backend.create.return_value = "container-123"
    backend.start.return_value = None
    backend.wait.return_value = MagicMock(exit_code=0, timed_out=False)
    backend.cleanup.return_value = None

    async def _empty_stream_logs(_execution_id):
        if False:
            yield  # async generator, never yields
    backend.stream_logs = _empty_stream_logs
    return backend


@pytest.fixture
def mock_log_stream():
    return AsyncMock()


@pytest.fixture
def mock_run_repo():
    repo = AsyncMock()
    repo.mark_running.return_value = True
    repo.mark_collecting.return_value = True
    repo.update_execution_id.return_value = None
    repo.update_git_sha.return_value = None
    repo.finish_if_current.return_value = True
    repo.fail_if_current.return_value = True
    repo.commit.return_value = None
    repo.is_cancel_requested.return_value = False
    return repo


@pytest.fixture
def mock_plugin_registry():
    registry = MagicMock(spec=PluginRegistry)
    source = AsyncMock()
    source.clone.return_value = SourceRevision(
        path=Path("/tmp/test-repo"),
        sha="abc123def456",
        ref="main",
    )
    registry.get_source.return_value = source
    return registry


@pytest.fixture
def executor(mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry):
    return RunExecutor(
        backend=mock_backend,
        log_stream=mock_log_stream,
        run_repo=mock_run_repo,
        plugin_registry=mock_plugin_registry,
    )


@pytest.fixture
def sample_run():
    run = MagicMock(spec=Run)
    run.id = uuid4()
    run.project_id = uuid4()
    run.git_ref = "main"
    run.git_sha = None
    run.metadata = {"git_url": "https://github.com/org/repo.git"}
    return run


def _mount_projection(mounts):
    return [
        {
            "source": mount.source,
            "target": mount.target,
            "read_only": mount.read_only,
        }
        for mount in mounts
    ]


class TestRunSetupContainerised:
    """Regression tests for the P0 fix that moved setup_script execution
    from `asyncio.create_subprocess_shell` (worker host) into the same
    sandbox backend as stages.
    """

    def test_workspace_dir_is_writable_by_fixed_container_uid(self):
        run_id = str(uuid4())
        working_dir = RunExecutor._create_workspace_dir(run_id)

        try:
            assert working_dir.name.startswith(f"qap-{run_id[:8]}-")
            assert stat.S_IMODE(working_dir.stat().st_mode) == 0o777
        finally:
            working_dir.rmdir()

    def test_workspace_dir_can_use_shared_docker_socket_root(self, tmp_path, monkeypatch):
        run_id = str(uuid4())
        shared_root = tmp_path / "qap-workspaces"
        monkeypatch.setenv("QAP_RUN_WORKSPACE_DIR", str(shared_root))

        working_dir = RunExecutor._create_workspace_dir(run_id)

        try:
            assert working_dir.parent == shared_root
            assert working_dir.name.startswith(f"qap-{run_id[:8]}-")
            assert stat.S_IMODE(shared_root.stat().st_mode) == 0o777
            assert stat.S_IMODE(working_dir.stat().st_mode) == 0o777
        finally:
            working_dir.rmdir()

    def test_workspace_dir_tolerates_bind_root_chmod_denied(self, tmp_path, monkeypatch):
        run_id = str(uuid4())
        shared_root = tmp_path / "qap-workspaces"
        monkeypatch.setenv("QAP_RUN_WORKSPACE_DIR", str(shared_root))
        original_chmod = Path.chmod

        def chmod_with_bind_root_denied(path: Path, mode: int, *args, **kwargs):
            if path == shared_root:
                raise PermissionError("bind root is not owned by container user")
            return original_chmod(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "chmod", chmod_with_bind_root_denied)

        working_dir = RunExecutor._create_workspace_dir(run_id)

        try:
            assert working_dir.parent == shared_root
            assert working_dir.name.startswith(f"qap-{run_id[:8]}-")
            assert stat.S_IMODE(working_dir.stat().st_mode) == 0o777
        finally:
            working_dir.rmdir()

    @pytest.fixture
    def setup_pipeline(self):
        from qaplatform.engine.executor import PipelineConfig
        return PipelineConfig(
            image="python:3.12-alpine",
            stages=[],
            env_vars={"FOO": "bar"},
            timeout_seconds=300,
            setup_script="pip install -r requirements.txt",
        )

    @pytest.mark.asyncio
    async def test_setup_runs_via_backend_not_subprocess(
        self, executor, mock_backend, sample_run, setup_pipeline, tmp_path
    ):
        """The setup script must be dispatched as an ExecutionSpec to the
        backend; under no circumstance should the executor shell out on
        the host (which is what the old code path did)."""
        from qaplatform.engine.executor import ExecutionSpec

        mock_backend.create_execution = AsyncMock(return_value="setup-container-1")
        mock_backend.start = AsyncMock()
        mock_backend.wait = AsyncMock(
            return_value=MagicMock(exit_code=0, timed_out=False)
        )
        mock_backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        mock_backend.stream_logs = _empty_logs

        with patch("asyncio.create_subprocess_shell") as shell_patch:
            await executor._run_setup(sample_run, setup_pipeline, tmp_path)
            shell_patch.assert_not_called()

        # backend.create_execution must receive an ExecutionSpec carrying the
        # script through the sandbox shell, rooted at the mounted workspace.
        mock_backend.create_execution.assert_awaited_once()
        spec = mock_backend.create_execution.await_args.args[0]
        assert isinstance(spec, ExecutionSpec)
        assert spec.image == "python:3.12-alpine"
        assert spec.command == ["sh", "-c", "cd /workspace && pip install -r requirements.txt"]
        assert spec.env_vars == {"FOO": "bar"}
        assert spec.resource_limits is setup_pipeline.resource_limits
        assert spec.network_policy == "deny"
        assert spec.user == "1000:1000"
        assert spec.security.readonly_rootfs is False
        assert _mount_projection(spec.mounts) == [
            {
                "source": str(tmp_path),
                "target": "/workspace",
                "read_only": False,
            }
        ]
        # Setup container is labeled distinctly so an operator inspecting
        # docker ps can tell setup containers from stage containers.
        assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}
        mock_backend.start.assert_awaited_once_with("setup-container-1")
        mock_backend.wait.assert_awaited_once_with("setup-container-1", 300)
        mock_backend.cleanup.assert_awaited_once_with("setup-container-1")
        assert executor._active_execution_id is None

    @pytest.mark.asyncio
    async def test_setup_timeout_capped_at_600s(
        self, executor, mock_backend, sample_run, tmp_path
    ):
        from qaplatform.engine.executor import ExecutionSpec, PipelineConfig
        pipeline = PipelineConfig(
            image="python:3.12-alpine",
            stages=[],
            timeout_seconds=3600,  # well over 600
            setup_script="echo hi",
        )

        mock_backend.create_execution = AsyncMock(return_value="setup-capped-container")
        mock_backend.start = AsyncMock()
        mock_backend.wait = AsyncMock(
            return_value=MagicMock(exit_code=0, timed_out=False)
        )
        mock_backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        mock_backend.stream_logs = _empty_logs

        await executor._run_setup(sample_run, pipeline, tmp_path)

        mock_backend.create_execution.assert_awaited_once()
        spec = mock_backend.create_execution.await_args.args[0]
        assert isinstance(spec, ExecutionSpec)
        assert spec.image == "python:3.12-alpine"
        assert spec.command == ["sh", "-c", "cd /workspace && echo hi"]
        assert spec.env_vars == {}
        assert spec.resource_limits is pipeline.resource_limits
        assert spec.network_policy == "deny"
        assert spec.user == "1000:1000"
        assert spec.security.readonly_rootfs is False
        assert _mount_projection(spec.mounts) == [
            {
                "source": str(tmp_path),
                "target": "/workspace",
                "read_only": False,
            }
        ]
        assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}
        mock_backend.start.assert_awaited_once_with("setup-capped-container")
        mock_backend.wait.assert_awaited_once_with("setup-capped-container", 600)
        mock_backend.cleanup.assert_awaited_once_with("setup-capped-container")
        assert executor._active_execution_id is None

    @pytest.mark.asyncio
    async def test_setup_uses_pipeline_timeout_when_below_cap(
        self, executor, mock_backend, sample_run, tmp_path
    ):
        from qaplatform.engine.executor import ExecutionSpec, PipelineConfig
        pipeline = PipelineConfig(
            image="python:3.12-alpine",
            stages=[],
            timeout_seconds=120,
            setup_script="echo hi",
        )

        mock_backend.create_execution = AsyncMock(return_value="setup-short-container")
        mock_backend.start = AsyncMock()
        mock_backend.wait = AsyncMock(
            return_value=MagicMock(exit_code=0, timed_out=False)
        )
        mock_backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        mock_backend.stream_logs = _empty_logs

        await executor._run_setup(sample_run, pipeline, tmp_path)
        mock_backend.create_execution.assert_awaited_once()
        spec = mock_backend.create_execution.await_args.args[0]
        assert isinstance(spec, ExecutionSpec)
        assert spec.image == "python:3.12-alpine"
        assert spec.command == ["sh", "-c", "cd /workspace && echo hi"]
        assert spec.env_vars == {}
        assert spec.resource_limits is pipeline.resource_limits
        assert spec.network_policy == "deny"
        assert spec.user == "1000:1000"
        assert spec.security.readonly_rootfs is False
        assert _mount_projection(spec.mounts) == [
            {
                "source": str(tmp_path),
                "target": "/workspace",
                "read_only": False,
            }
        ]
        assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}
        mock_backend.start.assert_awaited_once_with("setup-short-container")
        mock_backend.wait.assert_awaited_once_with("setup-short-container", 120)
        mock_backend.cleanup.assert_awaited_once_with("setup-short-container")
        assert executor._active_execution_id is None

    @pytest.mark.asyncio
    async def test_setup_nonzero_exit_raises(
        self, executor, mock_backend, sample_run, setup_pipeline, tmp_path
    ):
        from qaplatform.engine.executor import ExecutionSpec

        mock_backend.create_execution = AsyncMock(return_value="c")
        mock_backend.start = AsyncMock()
        mock_backend.wait = AsyncMock(
            return_value=MagicMock(exit_code=1, timed_out=False)
        )
        mock_backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        mock_backend.stream_logs = _empty_logs

        with pytest.raises(RuntimeError) as exc_info:
            await executor._run_setup(sample_run, setup_pipeline, tmp_path)

        assert exc_info.value.args == ("Setup script failed (exit 1)",)
        mock_backend.create_execution.assert_awaited_once()
        spec = mock_backend.create_execution.await_args.args[0]
        assert isinstance(spec, ExecutionSpec)
        assert spec.image == "python:3.12-alpine"
        assert spec.command == [
            "sh",
            "-c",
            "cd /workspace && pip install -r requirements.txt",
        ]
        assert spec.env_vars == {"FOO": "bar"}
        assert spec.resource_limits is setup_pipeline.resource_limits
        assert spec.network_policy == "deny"
        assert spec.user == "1000:1000"
        assert spec.security.readonly_rootfs is False
        assert _mount_projection(spec.mounts) == [
            {
                "source": str(tmp_path),
                "target": "/workspace",
                "read_only": False,
            }
        ]
        assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}
        mock_backend.start.assert_awaited_once_with("c")
        mock_backend.wait.assert_awaited_once_with("c", 300)
        mock_backend.cleanup.assert_awaited_once_with("c")
        assert executor._active_execution_id is None

    @pytest.mark.asyncio
    async def test_setup_timeout_raises(
        self, executor, mock_backend, sample_run, setup_pipeline, tmp_path
    ):
        from qaplatform.engine.executor import ExecutionSpec

        mock_backend.create_execution = AsyncMock(return_value="c")
        mock_backend.start = AsyncMock()
        mock_backend.wait = AsyncMock(
            return_value=MagicMock(exit_code=None, timed_out=True)
        )
        mock_backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        mock_backend.stream_logs = _empty_logs

        with pytest.raises(RuntimeError) as exc_info:
            await executor._run_setup(sample_run, setup_pipeline, tmp_path)

        assert exc_info.value.args == ("Setup script timed out after 300s",)
        mock_backend.create_execution.assert_awaited_once()
        spec = mock_backend.create_execution.await_args.args[0]
        assert isinstance(spec, ExecutionSpec)
        assert spec.image == "python:3.12-alpine"
        assert spec.command == [
            "sh",
            "-c",
            "cd /workspace && pip install -r requirements.txt",
        ]
        assert spec.env_vars == {"FOO": "bar"}
        assert spec.resource_limits is setup_pipeline.resource_limits
        assert spec.network_policy == "deny"
        assert spec.user == "1000:1000"
        assert spec.security.readonly_rootfs is False
        assert _mount_projection(spec.mounts) == [
            {
                "source": str(tmp_path),
                "target": "/workspace",
                "read_only": False,
            }
        ]
        assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}
        mock_backend.start.assert_awaited_once_with("c")
        mock_backend.wait.assert_awaited_once_with("c", 300)
        mock_backend.cleanup.assert_awaited_once_with("c")
        assert executor._active_execution_id is None

    @pytest.mark.asyncio
    async def test_setup_outer_wait_for_triggers_graceful_stop(
        self, executor, mock_backend, sample_run, setup_pipeline, tmp_path
    ):
        """P1-B: if backend.wait ignores its timeout, the outer asyncio.wait_for
        guard fires _graceful_stop and synthesises a timed_out result so the
        run still terminates instead of hanging forever.
        """
        mock_backend.create_execution = AsyncMock(return_value="c")
        mock_backend.start = AsyncMock()

        async def _hang(*_a, **_kw):
            await asyncio.sleep(3600)

        mock_backend.wait = AsyncMock(side_effect=_hang)
        mock_backend.cleanup = AsyncMock()
        mock_backend.cancel = AsyncMock()
        mock_backend.force_kill = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        mock_backend.stream_logs = _empty_logs

        # Shrink the setup timeout so the outer wait_for fires fast.
        setup_pipeline = setup_pipeline.__class__(
            image=setup_pipeline.image,
            stages=setup_pipeline.stages,
            env_vars=setup_pipeline.env_vars,
            timeout_seconds=0,
            setup_script=setup_pipeline.setup_script,
        )

        with patch.object(executor, "_graceful_stop", new=AsyncMock()) as graceful:
            with pytest.raises(RuntimeError) as exc_info:
                await executor._run_setup(sample_run, setup_pipeline, tmp_path)

        assert exc_info.value.args == ("Setup script timed out after 0s",)
        graceful.assert_awaited_once_with("c", reason="setup timeout 0s")
        mock_backend.cleanup.assert_awaited_once_with("c")
        mock_log_stream = executor.log_stream
        assert mock_log_stream.write_log.await_args_list == [
            call(str(sample_run.id), "Running setup script..."),
            call(
                str(sample_run.id),
                "Setup script exceeded timeout 0s, sending SIGTERM",
                stream="stderr",
            ),
        ]

    @pytest.mark.asyncio
    async def test_log_task_stuck_does_not_block_cleanup(
        self, executor, mock_backend, sample_run, setup_pipeline, tmp_path
    ):
        """P1-C: a wedged log-follow coroutine must not block backend.cleanup
        or pin the run's finally block. Cleanup runs first; log_task drain is
        bounded by _LOG_DRAIN_TIMEOUT.
        """
        mock_backend.create_execution = AsyncMock(return_value="c")
        mock_backend.start = AsyncMock()
        mock_backend.wait = AsyncMock(
            return_value=MagicMock(exit_code=0, timed_out=False)
        )
        mock_backend.cleanup = AsyncMock()

        # Simulate a log stream that never ends, even after the container
        # is cleaned up — exactly the failure mode P1-C guards against.
        async def _wedged_logs(_id):
            await asyncio.sleep(3600)
            if False:
                yield
        mock_backend.stream_logs = _wedged_logs

        # Patch the drain timeout down to keep the test fast.
        with patch("qaplatform.engine.executor._LOG_DRAIN_TIMEOUT", 0.05):
            await asyncio.wait_for(
                executor._run_setup(sample_run, setup_pipeline, tmp_path),
                timeout=2.0,
            )

        mock_backend.cleanup.assert_awaited_once_with("c")


class TestExecutorUsesSourcePlugin:
    """Verify executor delegates to SourceProtocol plugin."""

    @pytest.mark.asyncio
    async def test_clone_repo_uses_plugin(self, executor, sample_run, mock_plugin_registry):
        dest = Path("/tmp/test")
        await executor._clone_repo(sample_run, dest)

        mock_plugin_registry.get_source.assert_called_once_with("git")
        source = mock_plugin_registry.get_source.return_value
        source.clone.assert_awaited_once_with(
            "https://github.com/org/repo.git", "main", dest,
        )

    @pytest.mark.asyncio
    async def test_clone_repo_prefers_full_commit_sha(
        self, executor, sample_run, mock_plugin_registry
    ):
        dest = Path("/tmp/test")
        sample_run.git_sha = "0123456789abcdef0123456789abcdef01234567"

        await executor._clone_repo(sample_run, dest)

        source = mock_plugin_registry.get_source.return_value
        source.clone.assert_awaited_once_with(
            "https://github.com/org/repo.git",
            "0123456789abcdef0123456789abcdef01234567",
            dest,
        )

    @pytest.mark.asyncio
    async def test_clone_repo_passes_source_auth(
        self, executor, sample_run, mock_plugin_registry
    ):
        dest = Path("/tmp/test")
        auth = {"method": "token", "secret": "secret-token"}

        await executor._clone_repo(sample_run, dest, auth)

        source = mock_plugin_registry.get_source.return_value
        source.clone.assert_awaited_once_with(
            "https://github.com/org/repo.git",
            "main",
            dest,
            auth,
        )

    @pytest.mark.asyncio
    async def test_clone_repo_updates_git_sha(self, executor, sample_run, mock_run_repo, mock_plugin_registry):
        dest = Path("/tmp/test")
        await executor._clone_repo(sample_run, dest)

        mock_run_repo.update_git_sha.assert_awaited_once_with(
            sample_run.id, "abc123def456",
        )

    @pytest.mark.asyncio
    async def test_clone_repo_skips_when_no_git_url(self, executor, mock_log_stream, mock_plugin_registry):
        run = MagicMock(spec=Run)
        run.id = uuid4()
        run.git_ref = "main"
        run.git_sha = None
        run.metadata = {}

        dest = Path("/tmp/test")
        await executor._clone_repo(run, dest)

        mock_plugin_registry.get_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_clone_repo_propagates_error(self, executor, sample_run, mock_plugin_registry):
        source = mock_plugin_registry.get_source.return_value
        source.clone.side_effect = RuntimeError("git clone failed (exit 128): fatal: repo not found")

        dest = Path("/tmp/test")
        with pytest.raises(RuntimeError) as exc_info:
            await executor._clone_repo(sample_run, dest)

        assert exc_info.value.args == ("git clone failed (exit 128): fatal: repo not found",)
        mock_plugin_registry.get_source.assert_called_once_with("git")
        source.clone.assert_awaited_once_with(
            "https://github.com/org/repo.git",
            "main",
            dest,
        )
        executor.run_repo.update_git_sha.assert_not_awaited()
        executor.run_repo.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_times_out_source_clone(
        self,
        mock_backend,
        mock_log_stream,
        mock_run_repo,
        mock_plugin_registry,
        sample_run,
    ):
        source = mock_plugin_registry.get_source.return_value

        async def _hang_clone(*_args, **_kwargs):
            await asyncio.Event().wait()

        source.clone.side_effect = _hang_clone
        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
            source_clone_timeout_seconds=0.01,
        )
        pipeline = PipelineConfig(image="python:3.12", stages=[])

        status = await executor.execute(sample_run, pipeline)

        assert status == RunStatus.FAILED
        mock_run_repo.fail_if_current.assert_awaited_once()
        assert mock_run_repo.fail_if_current.await_args.args == (str(sample_run.id),)
        assert mock_run_repo.fail_if_current.await_args.kwargs == {
            "message": "Source clone timed out after 0.01s",
        }
        assert mock_log_stream.write_log.await_args_list[0] == call(
            str(sample_run.id),
            "Source clone exceeded timeout 0.01s",
            stream="stderr",
        )
        mock_run_repo.mark_running.assert_not_awaited()


class TestUploadArtifacts:
    """Verify _upload_artifacts uploads to S3 AND writes Artifact rows."""

    @pytest.mark.asyncio
    async def test_upload_writes_artifact_rows_with_inferred_type_and_mime(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, tmp_path
    ):
        s3 = AsyncMock()
        s3.put_object.return_value = None
        artifact_repo = AsyncMock()

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
            s3_client=s3,
            s3_bucket="test-bucket",
            artifact_repo=artifact_repo,
        )

        results_dir = tmp_path / "results"
        results_dir.mkdir()
        (results_dir / "junit.xml").write_bytes(b"<testsuites/>")
        (results_dir / "report.html").write_bytes(b"<html/>")
        (results_dir / "extra.bin").write_bytes(b"\x00\x01")

        run_id = "11111111-1111-1111-1111-111111111111"
        await executor._upload_artifacts(run_id, tmp_path)

        uploaded = [
            (
                upload.kwargs["Bucket"],
                upload.kwargs["Key"],
                Path(upload.kwargs["Body"].name).relative_to(results_dir).as_posix(),
            )
            for upload in s3.put_object.await_args_list
        ]
        assert uploaded == [
            ("test-bucket", f"reports/{run_id}/extra.bin", "extra.bin"),
            ("test-bucket", f"reports/{run_id}/junit.xml", "junit.xml"),
            ("test-bucket", f"reports/{run_id}/report.html", "report.html"),
        ]

        recorded_rows = [
            call.kwargs for call in artifact_repo.create.await_args_list
        ]
        junit_mime_type = next(
            (
                row.get("mime_type")
                for row in recorded_rows
                if row.get("name") == "junit.xml"
            ),
            None,
        )
        assert junit_mime_type in {"application/xml", "text/xml"}
        assert recorded_rows == [
            {
                "run_id": UUID(run_id),
                "type": "other",
                "name": "extra.bin",
                "storage_path": f"reports/{run_id}/extra.bin",
                "size_bytes": len(b"\x00\x01"),
                "mime_type": "application/octet-stream",
            },
            {
                "run_id": UUID(run_id),
                "type": "junit",
                "name": "junit.xml",
                "storage_path": f"reports/{run_id}/junit.xml",
                "size_bytes": len(b"<testsuites/>"),
                "mime_type": junit_mime_type,
            },
            {
                "run_id": UUID(run_id),
                "type": "report",
                "name": "report.html",
                "storage_path": f"reports/{run_id}/report.html",
                "size_bytes": len(b"<html/>"),
                "mime_type": "text/html",
            },
        ]

    @pytest.mark.asyncio
    async def test_upload_recurses_allure_report_directories(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, tmp_path
    ):
        s3 = AsyncMock()
        artifact_repo = AsyncMock()
        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
            s3_client=s3,
            s3_bucket="test-bucket",
            artifact_repo=artifact_repo,
        )
        results_dir = tmp_path / "results"
        (results_dir / "allure-report" / "assets").mkdir(parents=True)
        (results_dir / "allure-report" / "index.html").write_text("<html/>")
        (results_dir / "allure-report" / "assets" / "app.js").write_text("ok")

        run_id = "11111111-1111-1111-1111-111111111111"
        await executor._upload_artifacts(run_id, tmp_path)

        uploaded = [
            (
                upload.kwargs["Key"],
                Path(upload.kwargs["Body"].name).relative_to(results_dir).as_posix(),
            )
            for upload in s3.put_object.await_args_list
        ]
        assert uploaded == [
            (
                f"reports/{run_id}/allure-report/assets/app.js",
                "allure-report/assets/app.js",
            ),
            (
                f"reports/{run_id}/allure-report/index.html",
                "allure-report/index.html",
            ),
        ]
        assert [
            call.kwargs for call in artifact_repo.create.await_args_list
        ] == [
            {
                "run_id": UUID(run_id),
                "type": "allure-report",
                "name": "allure-report/assets/app.js",
                "storage_path": f"reports/{run_id}/allure-report/assets/app.js",
                "size_bytes": len("ok"),
                "mime_type": "text/javascript",
            },
            {
                "run_id": UUID(run_id),
                "type": "allure-report",
                "name": "allure-report/index.html",
                "storage_path": f"reports/{run_id}/allure-report/index.html",
                "size_bytes": len("<html/>"),
                "mime_type": "text/html",
            },
        ]

    @pytest.mark.asyncio
    async def test_generate_allure_report_runs_cli_when_results_exist(
        self,
        mock_backend,
        mock_log_stream,
        mock_run_repo,
        mock_plugin_registry,
        tmp_path,
    ):
        now = datetime.now(timezone.utc)
        mock_backend.create_execution.return_value = "allure-123"
        mock_backend.wait.return_value = ExitResult(
            exit_code=0,
            started_at=now,
            finished_at=now,
        )

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )
        (tmp_path / "results" / "allure-results").mkdir(parents=True)
        (tmp_path / "results" / "allure-results" / "result.json").write_text("{}")

        run_id = "11111111-1111-1111-1111-111111111111"
        pipeline = PipelineConfig(
            image="python:3.12",
            stages=[],
            env_vars={"TOKEN": "secret"},
            network_policy="allow",
        )
        await executor._generate_allure_report(run_id, tmp_path, pipeline)

        spec = mock_backend.create_execution.await_args.args[0]
        assert spec.image == "python:3.12"
        assert spec.command == [
            "sh",
            "-c",
            "cd /workspace && allure generate results/allure-results -o results/allure-report --clean",
        ]
        assert spec.env_vars == {"TOKEN": "secret"}
        assert spec.network_policy == "allow"
        assert _mount_projection(spec.mounts) == [
            {"source": str(tmp_path), "target": "/workspace", "read_only": False}
        ]
        assert spec.labels == {"run_id": run_id, "stage": "allure-report"}
        mock_backend.start.assert_awaited_once_with("allure-123")
        mock_backend.wait.assert_awaited_once_with("allure-123", 300)
        mock_backend.cleanup.assert_awaited_once_with("allure-123")
        mock_log_stream.write_log.assert_any_await(
            run_id,
            "Allure report generated: allure-report",
        )

    @pytest.mark.asyncio
    async def test_generate_allure_report_failure_is_logged_not_raised(
        self,
        mock_backend,
        mock_log_stream,
        mock_run_repo,
        mock_plugin_registry,
        tmp_path,
    ):
        now = datetime.now(timezone.utc)
        mock_backend.create_execution.return_value = "allure-123"
        mock_backend.wait.return_value = ExitResult(
            exit_code=1,
            started_at=now,
            finished_at=now,
        )

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )
        (tmp_path / "results" / "allure-results").mkdir(parents=True)
        (tmp_path / "results" / "allure-results" / "result.json").write_text("{}")

        run_id = "11111111-1111-1111-1111-111111111111"
        pipeline = PipelineConfig(image="python:3.12", stages=[])
        await executor._generate_allure_report(run_id, tmp_path, pipeline)

        mock_log_stream.write_log.assert_awaited_once_with(
            run_id,
            "Allure report generation failed with code 1",
            stream="stderr",
        )

    @pytest.mark.asyncio
    async def test_generate_allure_report_missing_cli_is_logged_not_raised(
        self,
        mock_backend,
        mock_log_stream,
        mock_run_repo,
        mock_plugin_registry,
        tmp_path,
    ):
        now = datetime.now(timezone.utc)
        mock_backend.create_execution.return_value = "allure-123"
        mock_backend.wait.return_value = ExitResult(
            exit_code=127,
            started_at=now,
            finished_at=now,
        )

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )
        (tmp_path / "results" / "allure-results").mkdir(parents=True)
        (tmp_path / "results" / "allure-results" / "result.json").write_text("{}")

        run_id = "11111111-1111-1111-1111-111111111111"
        pipeline = PipelineConfig(image="python:3.12", stages=[])
        await executor._generate_allure_report(run_id, tmp_path, pipeline)

        mock_log_stream.write_log.assert_awaited_once_with(
            run_id,
            "Allure report generation skipped: allure CLI is not installed in the execution image",
            stream="stderr",
        )

    @pytest.mark.asyncio
    async def test_upload_skips_artifact_row_when_repo_missing(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, tmp_path
    ):
        s3 = AsyncMock()
        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
            s3_client=s3,
            s3_bucket="test-bucket",
            artifact_repo=None,
        )
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "x.xml").write_bytes(b"<x/>")

        # Should not raise — artifact_repo=None is allowed (S3-only mode)
        run_id = "11111111-1111-1111-1111-111111111111"
        await executor._upload_artifacts(run_id, tmp_path)
        s3.put_object.assert_awaited_once()
        put_kwargs = s3.put_object.await_args.kwargs
        uploaded_body = put_kwargs["Body"]
        assert put_kwargs == {
            "Bucket": "test-bucket",
            "Key": f"reports/{run_id}/x.xml",
            "Body": uploaded_body,
        }
        assert Path(uploaded_body.name) == tmp_path / "results" / "x.xml"
        mock_log_stream.write_log.assert_awaited_once_with(
            run_id,
            "Uploaded artifact: x.xml",
        )

    @pytest.mark.asyncio
    async def test_upload_skips_artifact_row_when_s3_fails(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, tmp_path
    ):
        s3 = AsyncMock()
        s3.put_object.side_effect = RuntimeError("s3 down")
        artifact_repo = AsyncMock()

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
            s3_client=s3,
            artifact_repo=artifact_repo,
        )
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "x.xml").write_bytes(b"<x/>")

        await executor._upload_artifacts("rid", tmp_path)
        # S3 failed → DB row must NOT be written to avoid dangling reference
        artifact_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upload_skips_artifacts_over_size_limit(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, tmp_path
    ):
        from qaplatform.engine.docker_backend import ResourceLimits

        s3 = AsyncMock()
        artifact_repo = AsyncMock()
        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
            s3_client=s3,
            artifact_repo=artifact_repo,
        )
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "big.txt").write_bytes(b"too-large")
        (tmp_path / "results" / "small.txt").write_bytes(b"ok")

        run_id = "11111111-1111-1111-1111-111111111111"
        await executor._upload_artifacts(
            run_id,
            tmp_path,
            ResourceLimits(max_artifact_size_bytes=2, max_artifacts_count=10),
        )

        s3.put_object.assert_awaited_once()
        put_kwargs = s3.put_object.await_args.kwargs
        uploaded_body = put_kwargs["Body"]
        assert put_kwargs == {
            "Bucket": "qa-platform",
            "Key": f"reports/{run_id}/small.txt",
            "Body": uploaded_body,
        }
        assert Path(uploaded_body.name) == tmp_path / "results" / "small.txt"
        artifact_repo.create.assert_awaited_once_with(
            run_id=UUID(run_id),
            type="log",
            name="small.txt",
            storage_path=f"reports/{run_id}/small.txt",
            size_bytes=2,
            mime_type="text/plain",
        )
        assert mock_log_stream.write_log.await_args_list == [
            call(
                run_id,
                "Skipped artifact big.txt: size 9 exceeds limit 2 bytes",
                stream="stderr",
            ),
            call(
                run_id,
                "Uploaded artifact: small.txt",
            ),
        ]

    @pytest.mark.asyncio
    async def test_upload_skips_artifacts_over_count_limit(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, tmp_path
    ):
        from qaplatform.engine.docker_backend import ResourceLimits

        s3 = AsyncMock()
        artifact_repo = AsyncMock()
        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
            s3_client=s3,
            artifact_repo=artifact_repo,
        )
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "a.txt").write_bytes(b"a")
        (tmp_path / "results" / "b.txt").write_bytes(b"b")

        run_id = "11111111-1111-1111-1111-111111111111"
        await executor._upload_artifacts(
            run_id,
            tmp_path,
            ResourceLimits(max_artifact_size_bytes=100, max_artifacts_count=1),
        )

        s3.put_object.assert_awaited_once()
        put_kwargs = s3.put_object.await_args.kwargs
        uploaded_body = put_kwargs["Body"]
        assert put_kwargs == {
            "Bucket": "qa-platform",
            "Key": f"reports/{run_id}/a.txt",
            "Body": uploaded_body,
        }
        assert Path(uploaded_body.name) == tmp_path / "results" / "a.txt"
        artifact_repo.create.assert_awaited_once_with(
            run_id=UUID(run_id),
            type="log",
            name="a.txt",
            storage_path=f"reports/{run_id}/a.txt",
            size_bytes=1,
            mime_type="text/plain",
        )
        assert mock_log_stream.write_log.await_args_list == [
            call(
                run_id,
                "Uploaded artifact: a.txt",
            ),
            call(
                run_id,
                "Skipped artifact b.txt: artifact count limit exceeded",
                stream="stderr",
            )
        ]


# --------------------------------------------------------------------------- #
# F-PL-03 stage timeout grace-period contract
# --------------------------------------------------------------------------- #


class TestRunStagesTimeoutGracePeriod:
    """When ``backend.wait`` blocks past the pipeline timeout, _run_stages
    must drive the SIGTERM → 30 s → SIGKILL teardown contract from PRD
    F-PL-03 instead of falling through to the generic exception handler
    (which would force-kill immediately and skip the grace window).
    """

    def _make_pipeline(self, timeout_seconds: int = 60):
        from qaplatform.engine.executor import PipelineConfig, StageDefinition
        return PipelineConfig(
            image="python:3.12-alpine",
            stages=[StageDefinition(name="pytest", plugin="pytest")],
            timeout_seconds=timeout_seconds,
        )

    @pytest.fixture
    def timeout_executor(self):
        backend = AsyncMock()
        backend.create_execution = AsyncMock(return_value="container-xyz")
        backend.start = AsyncMock()
        backend.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        backend.cancel = AsyncMock()
        backend.force_kill = AsyncMock()
        backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        backend.stream_logs = _empty_logs

        plugin_registry = MagicMock(spec=PluginRegistry)
        runner = MagicMock()
        runner.build_command = MagicMock(return_value="pytest -q")
        plugin_registry.get_runner.return_value = runner

        run_repo = AsyncMock()
        run_repo.is_cancel_requested.return_value = False

        return RunExecutor(
            backend=backend,
            log_stream=AsyncMock(),
            run_repo=run_repo,
            plugin_registry=plugin_registry,
        )

    @pytest.mark.asyncio
    async def test_timeout_triggers_graceful_stop_and_marks_timed_out(
        self, timeout_executor, sample_run, tmp_path
    ):
        """Stage timeout drives backend.cancel → bounded grace wait →
        backend.force_kill and yields an ExitResult with timed_out=True
        so the executor can map it to RunStatus.TIMEOUT.

        The fixture's ``backend.wait`` raises ``asyncio.TimeoutError`` on
        every call, which models a stuck container that ignores SIGTERM
        — so we expect to fall through to force_kill.
        """
        pipeline = self._make_pipeline(timeout_seconds=60)

        exit_result = await timeout_executor._run_stages(sample_run, pipeline, tmp_path)

        timeout_executor.backend.cancel.assert_awaited_once_with("container-xyz")
        timeout_executor.backend.force_kill.assert_awaited_once_with("container-xyz")
        assert exit_result.timed_out is True
        assert exit_result.exit_code == -1

    @pytest.mark.asyncio
    async def test_timeout_writes_reason_log(
        self, timeout_executor, sample_run, tmp_path
    ):
        """Operators need to see why a stage was killed in the run log."""
        pipeline = self._make_pipeline(timeout_seconds=42)

        await timeout_executor._run_stages(sample_run, pipeline, tmp_path)

        assert timeout_executor.log_stream.write_log.await_args_list == [
            call(str(sample_run.id), "Starting stage: pytest"),
            call(
                str(sample_run.id),
                "Stage 'pytest' exceeded timeout 42s, sending SIGTERM",
                stream="stderr",
            ),
        ]

    @pytest.mark.asyncio
    async def test_timeout_status_maps_to_timeout(
        self, timeout_executor, sample_run, tmp_path, mock_log_stream
    ):
        """End-to-end: a timeout in _run_stages should propagate so execute()
        writes RunStatus.TIMEOUT (not FAILED) via finish_if_current."""
        from qaplatform.domain.models.run import RunStatus

        # Skip the clone step and stub setup-related dependencies.
        timeout_executor.run_repo.finish_if_current = AsyncMock(return_value=True)
        timeout_executor.run_repo.fail_if_current = AsyncMock(return_value=False)
        timeout_executor.run_repo.mark_running = AsyncMock()
        timeout_executor.run_repo.mark_collecting = AsyncMock()
        timeout_executor.run_repo.update_execution_id = AsyncMock()

        # Skip git/source: no git_url means _clone_repo returns silently.
        sample_run.metadata = {}

        # No collector configured, so stub registry to return one with no results.
        collector = AsyncMock()
        collector.collect = AsyncMock(return_value=[])
        timeout_executor.plugin_registry.get_collector = MagicMock(return_value=collector)

        pipeline = self._make_pipeline(timeout_seconds=10)

        status = await timeout_executor.execute(sample_run, pipeline)

        assert status == RunStatus.TIMEOUT
        finish_call = timeout_executor.run_repo.finish_if_current.await_args
        assert finish_call.kwargs["status"] == RunStatus.TIMEOUT


# --------------------------------------------------------------------------- #
# P0-B: long-transaction split — commit after mark_running / mark_collecting
# --------------------------------------------------------------------------- #


class TestExecutorCommitsAfterStateTransitions:
    """P0-B step 2: executor must commit through the run_repo immediately
    after mark_running and mark_collecting so the new state is visible to
    other connections (cancel API polling, SSE status reads) instead of
    being held inside the long-lived worker transaction.
    """

    def _make_pipeline(self):
        from qaplatform.engine.executor import PipelineConfig, StageDefinition
        return PipelineConfig(
            image="python:3.12-alpine",
            stages=[StageDefinition(name="pytest", plugin="pytest")],
            timeout_seconds=60,
        )

    @pytest.fixture
    def happy_executor(self, mock_log_stream, mock_run_repo, mock_plugin_registry):
        backend = AsyncMock()
        backend.create_execution = AsyncMock(return_value="container-abc")
        backend.start = AsyncMock()
        exit_result = MagicMock()
        exit_result.exit_code = 0
        exit_result.oom_killed = False
        exit_result.timed_out = False
        backend.wait = AsyncMock(return_value=exit_result)
        backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        backend.stream_logs = _empty_logs

        runner = MagicMock()
        runner.build_command = MagicMock(return_value="pytest -q")
        mock_plugin_registry.get_runner = MagicMock(return_value=runner)
        collector = AsyncMock()
        collector.collect = AsyncMock(return_value=[])
        mock_plugin_registry.get_collector = MagicMock(return_value=collector)

        return RunExecutor(
            backend=backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )

    async def _execute_with_tracked_repo_calls(
        self, happy_executor, sample_run, mock_run_repo
    ) -> list[str]:
        call_log: list[str] = []

        async def _mark_running(*_args, **_kwargs):
            call_log.append("mark_running")
            return True

        async def _update_execution_id(*_args, **_kwargs):
            call_log.append("update_execution_id")

        async def _mark_collecting(*_args, **_kwargs):
            call_log.append("mark_collecting")
            return True

        async def _commit():
            call_log.append("commit")

        mock_run_repo.mark_running.side_effect = _mark_running
        mock_run_repo.update_execution_id.side_effect = _update_execution_id
        mock_run_repo.mark_collecting.side_effect = _mark_collecting
        mock_run_repo.commit.side_effect = _commit

        sample_run.metadata = {}  # skip _clone_repo
        await happy_executor.execute(sample_run, self._make_pipeline())

        return call_log

    @pytest.mark.asyncio
    async def test_commit_called_after_mark_running(
        self, happy_executor, sample_run, mock_run_repo
    ):
        """mark_running must be committed before stage execution row updates."""
        call_log = await self._execute_with_tracked_repo_calls(
            happy_executor,
            sample_run,
            mock_run_repo,
        )

        mock_run_repo.mark_running.assert_awaited_once_with(str(sample_run.id))
        assert call_log[:2] == ["mark_running", "commit"], (
            "mark_running must be followed immediately by commit before "
            f"later execution_id work; log={call_log}"
        )

    @pytest.mark.asyncio
    async def test_commit_called_after_mark_collecting(
        self, happy_executor, sample_run, mock_run_repo
    ):
        """mark_collecting must be committed before terminal result writes."""
        call_log = await self._execute_with_tracked_repo_calls(
            happy_executor,
            sample_run,
            mock_run_repo,
        )

        mock_run_repo.mark_collecting.assert_awaited_once_with(str(sample_run.id))
        collecting_idx = call_log.index("mark_collecting")
        assert call_log[collecting_idx: collecting_idx + 2] == [
            "mark_collecting",
            "commit",
        ], (
            "mark_collecting must be followed immediately by commit before "
            f"terminal result writes; log={call_log}"
        )

    @pytest.mark.asyncio
    async def test_execute_emits_manual_phase_spans(
        self, happy_executor, sample_run, monkeypatch
    ):
        """Execution traces should expose the four PRD-defined child phases."""
        from qaplatform.engine import executor as executor_module

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

        monkeypatch.setattr(
            executor_module.trace,
            "get_tracer",
            lambda name: _Tracer(),
        )

        sample_run.metadata = {}
        await happy_executor.execute(sample_run, self._make_pipeline())

        span_names = [name for name, _attrs in spans]
        assert span_names == [
            "source_clone",
            "container_run",
            "collect_results",
            "upload_artifacts",
        ]
        assert spans[0][1]["run.id"] == str(sample_run.id)

    @pytest.mark.asyncio
    async def test_execute_uses_configured_collector_plugin_and_config(
        self, happy_executor, sample_run
    ):
        from qaplatform.engine.executor import CollectorDefinition, PipelineConfig, StageDefinition

        sample_run.metadata = {}
        pipeline = PipelineConfig(
            image="python:3.12-alpine",
            stages=[StageDefinition(name="pytest", plugin="pytest")],
            collectors=[
                CollectorDefinition(
                    plugin="custom-junit",
                    config={"path": "reports/custom.xml"},
                )
            ],
        )

        await happy_executor.execute(sample_run, pipeline)

        happy_executor.plugin_registry.get_collector.assert_called_with("custom-junit")
        collector = happy_executor.plugin_registry.get_collector.return_value
        collector.collect.assert_awaited_once_with(
            sample_run.id,
            ANY,
            {"path": "reports/custom.xml"},
        )

    @pytest.mark.asyncio
    async def test_execute_persists_collected_test_results(
        self, happy_executor, sample_run
    ):
        from qaplatform.plugins.protocols import TestResultData

        sample_run.metadata = {}
        test_result = TestResultData(
            suite="worker-suite",
            name="test_worker_smoke",
            status="passed",
            duration_ms=12,
            tags=["e2e"],
            metadata={"source": "junit"},
        )
        collector = AsyncMock()
        collector.collect = AsyncMock(return_value=[test_result])
        happy_executor.plugin_registry.get_collector = MagicMock(return_value=collector)
        happy_executor.test_result_repo = AsyncMock()

        await happy_executor.execute(sample_run, self._make_pipeline())

        happy_executor.test_result_repo.bulk_create.assert_awaited_once_with(
            [
                {
                    "run_id": sample_run.id,
                    "suite": "worker-suite",
                    "name": "test_worker_smoke",
                    "status": "passed",
                    "duration_ms": 12,
                    "error_message": None,
                    "stack_trace": None,
                    "tags": ["e2e"],
                    "metadata_": {"source": "junit"},
                }
            ]
        )

    @pytest.mark.asyncio
    async def test_execute_counts_xfail_results_as_skipped_in_summary(
        self, happy_executor, sample_run, mock_run_repo
    ):
        from qaplatform.plugins.protocols import TestResultData

        sample_run.metadata = {}
        collector = AsyncMock()
        collector.collect = AsyncMock(
            return_value=[
                TestResultData(suite="suite", name="test_pass", status="passed"),
                TestResultData(suite="suite", name="test_xfail", status="xfail"),
            ]
        )
        happy_executor.plugin_registry.get_collector = MagicMock(return_value=collector)
        happy_executor.test_result_repo = AsyncMock()

        await happy_executor.execute(sample_run, self._make_pipeline())

        mock_run_repo.finish_if_current.assert_awaited_once_with(
            str(sample_run.id),
            status=RunStatus.DONE,
            summary=ANY,
        )
        summary = mock_run_repo.finish_if_current.await_args.kwargs["summary"]
        assert summary["total"] == 2
        assert summary["passed"] == 1
        assert summary["skipped"] == 1
        assert summary["failed"] == 0
        assert summary["error"] == 0
        assert summary["pass_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_execute_includes_failed_test_names_in_summary(
        self, happy_executor, sample_run, mock_run_repo
    ):
        from qaplatform.plugins.protocols import TestResultData

        sample_run.metadata = {}
        happy_executor.backend.wait.return_value.exit_code = 1
        collector = AsyncMock()
        collector.collect = AsyncMock(
            return_value=[
                TestResultData(suite="api", name="test_login", status="failed"),
                TestResultData(suite="ui", name="test_checkout", status="error"),
                TestResultData(suite="ui", name="test_skip", status="skipped"),
                TestResultData(suite="api", name="test_health", status="passed"),
            ]
        )
        happy_executor.plugin_registry.get_collector = MagicMock(return_value=collector)
        happy_executor.test_result_repo = AsyncMock()

        await happy_executor.execute(sample_run, self._make_pipeline())

        mock_run_repo.finish_if_current.assert_awaited_once_with(
            str(sample_run.id),
            status=RunStatus.FAILED,
            summary=ANY,
        )
        summary = mock_run_repo.finish_if_current.await_args.kwargs["summary"]
        assert summary["failed"] == 1
        assert summary["error"] == 1
        assert summary["failed_tests"] == [
            {"suite": "api", "name": "test_login", "status": "failed"},
            {"suite": "ui", "name": "test_checkout", "status": "error"},
        ]
        assert "failed_tests_omitted" not in summary

    @pytest.mark.asyncio
    async def test_execute_caps_failed_test_names_in_summary(
        self, happy_executor, sample_run, mock_run_repo
    ):
        from qaplatform.plugins.protocols import TestResultData

        sample_run.metadata = {}
        happy_executor.backend.wait.return_value.exit_code = 1
        collector = AsyncMock()
        collector.collect = AsyncMock(
            return_value=[
                TestResultData(suite="suite", name=f"test_{index}", status="failed")
                for index in range(25)
            ]
        )
        happy_executor.plugin_registry.get_collector = MagicMock(return_value=collector)
        happy_executor.test_result_repo = AsyncMock()

        await happy_executor.execute(sample_run, self._make_pipeline())

        summary = mock_run_repo.finish_if_current.await_args.kwargs["summary"]
        assert summary["failed_tests"] == [
            {
                "suite": "suite",
                "name": f"test_{index}",
                "status": "failed",
            }
            for index in range(20)
        ]
        assert summary["failed_tests_omitted"] == 5

    @pytest.mark.asyncio
    async def test_old_collector_signature_still_works(self, happy_executor, sample_run, tmp_path):
        class OldCollector:
            async def collect(self, run_id, working_dir):
                return []

        results = await happy_executor._collect_from_plugin(
            OldCollector(),
            sample_run.id,
            tmp_path,
            {"path": "reports/custom.xml"},
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_commit_ordering_running_then_collecting(
        self, happy_executor, sample_run, mock_run_repo
    ):
        """Order: mark_running -> commit -> mark_collecting -> commit."""
        call_log: list[str] = []

        async def _mark_running(*a, **kw):
            call_log.append("mark_running")
            return True

        async def _mark_collecting(*a, **kw):
            call_log.append("mark_collecting")
            return True

        async def _commit():
            call_log.append("commit")

        mock_run_repo.mark_running.side_effect = _mark_running
        mock_run_repo.mark_collecting.side_effect = _mark_collecting
        mock_run_repo.commit.side_effect = _commit

        sample_run.metadata = {}
        await happy_executor.execute(sample_run, self._make_pipeline())

        # Find indices and assert ordering.
        running_idx = call_log.index("mark_running")
        collecting_idx = call_log.index("mark_collecting")
        # First commit comes between mark_running and mark_collecting.
        between = call_log[running_idx + 1:collecting_idx]
        assert "commit" in between, (
            f"expected commit between mark_running and mark_collecting, log={call_log}"
        )
        # A second commit comes after mark_collecting.
        after = call_log[collecting_idx + 1:]
        assert "commit" in after, (
            f"expected commit after mark_collecting, log={call_log}"
        )

    def test_protocol_declares_commit(self):
        """RunRepositoryProtocol must expose commit() so executor.run_repo
        is type-correct under method-A (Protocol extension)."""
        from qaplatform.engine.executor import RunRepositoryProtocol
        assert hasattr(RunRepositoryProtocol, "commit")

    @pytest.mark.asyncio
    async def test_commit_called_after_update_execution_id(
        self, happy_executor, sample_run, mock_run_repo
    ):
        """update_execution_id must be followed by run_repo.commit() so the
        run row write lock is released before backend.wait blocks for the
        stage timeout — otherwise cancel API's UPDATE on the same row stalls
        for the full stage duration (P0-B follow-up, 60s blocking incident).
        """
        call_log: list[str] = []

        async def _update_execution_id(*a, **kw):
            call_log.append("update_execution_id")

        async def _wait(*a, **kw):
            call_log.append("backend.wait")
            return happy_executor.backend.wait.return_value

        async def _commit():
            call_log.append("commit")

        mock_run_repo.update_execution_id.side_effect = _update_execution_id
        mock_run_repo.commit.side_effect = _commit
        happy_executor.backend.wait.side_effect = _wait

        sample_run.metadata = {}
        await happy_executor.execute(sample_run, self._make_pipeline())

        update_idx = call_log.index("update_execution_id")
        wait_idx = call_log.index("backend.wait")
        between = call_log[update_idx + 1:wait_idx]
        assert "commit" in between, (
            f"expected commit between update_execution_id and backend.wait, log={call_log}"
        )


class TestMarkRunningSkippedLog:
    """P1-4: when mark_running / mark_collecting returns False (cancel race),
    executor must emit a structured log so post-mortem can correlate the
    missing transition."""

    def _make_pipeline(self):
        from qaplatform.engine.executor import PipelineConfig, StageDefinition
        from qaplatform.engine.docker_backend import ResourceLimits

        return PipelineConfig(
            image="alpine:3.19",
            stages=[StageDefinition(name="exec", plugin="pytest", phase="execute")],
            env_vars={},
            resource_limits=ResourceLimits(
                memory_bytes=128 * 1024 * 1024, cpu_cores=0.5
            ),
            network_policy="none",
            timeout_seconds=30,
        )

    @staticmethod
    def _skipped_transition_records(caplog):
        return [
            record for record in caplog.records
            if record.name == "qaplatform.engine.executor"
            and record.getMessage() == "run_status_transition_skipped"
        ]

    @pytest.mark.asyncio
    async def test_executor_logs_when_mark_running_skipped(
        self,
        mock_backend,
        mock_log_stream,
        mock_run_repo,
        mock_plugin_registry,
        sample_run,
        caplog,
    ):
        """P1-4: when mark_running returns False (cancel race), executor must
        emit a structured log so post-mortem can correlate the missing
        transition."""
        mock_run_repo.mark_running.return_value = False
        mock_run_repo.mark_collecting.return_value = True

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )

        sample_run.metadata = {}
        caplog.set_level(logging.INFO, logger="qaplatform.engine.executor")

        result = await executor.execute(sample_run, self._make_pipeline())

        assert result == RunStatus.CANCELLED
        assert [
            (
                record.levelno,
                record.run_id,
                record.from_,
                record.to,
                record.reason,
            )
            for record in self._skipped_transition_records(caplog)
        ] == [
            (
                logging.INFO,
                str(sample_run.id),
                RunStatus.PREPARING.value,
                RunStatus.RUNNING.value,
                "row not in expected state — likely cancelled concurrently",
            )
        ]

    @pytest.mark.asyncio
    async def test_executor_logs_when_mark_collecting_skipped(
        self,
        mock_backend,
        mock_log_stream,
        mock_run_repo,
        mock_plugin_registry,
        sample_run,
        caplog,
    ):
        """P1-4: when mark_collecting returns False (cancel race), executor must
        emit a structured log so post-mortem can correlate the missing
        transition."""
        mock_run_repo.mark_running.return_value = True
        mock_run_repo.mark_collecting.return_value = False

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )

        sample_run.metadata = {}
        caplog.set_level(logging.INFO, logger="qaplatform.engine.executor")

        result = await executor.execute(sample_run, self._make_pipeline())

        assert result == RunStatus.CANCELLED
        assert [
            (
                record.levelno,
                record.run_id,
                record.from_,
                record.to,
                record.reason,
            )
            for record in self._skipped_transition_records(caplog)
        ] == [
            (
                logging.INFO,
                str(sample_run.id),
                RunStatus.RUNNING.value,
                RunStatus.COLLECTING.value,
                "row not in expected state — likely cancelled concurrently",
            )
        ]

    @pytest.mark.asyncio
    async def test_executor_does_not_publish_running_when_mark_running_returns_false(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, sample_run
    ):
        """P1-4 regression: when mark_running returns False (cancel race),
        executor must NOT publish RUNNING status event. It should early-return
        with CANCELLED status instead."""
        mock_run_repo.mark_running.return_value = False
        mock_run_repo.mark_collecting.return_value = True

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )

        sample_run.metadata = {}
        with patch(
            "qaplatform.engine.executor.publish_status_event",
            new_callable=AsyncMock,
        ) as publish_status_event:
            result = await executor.execute(sample_run, self._make_pipeline())

        # Should return CANCELLED, not proceed to RUNNING
        assert result == RunStatus.CANCELLED, (
            f"expected RunStatus.CANCELLED when mark_running returns False, got {result}"
        )

        publish_status_event.assert_not_awaited()

        mock_backend.create_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_executor_does_not_enter_stages_when_mark_running_returns_false(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, sample_run
    ):
        """P1-4 regression: when mark_running returns False (cancel race),
        executor must NOT enter _run_stages. It should early-return immediately."""
        mock_run_repo.mark_running.return_value = False
        mock_run_repo.mark_collecting.return_value = True

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )

        sample_run.metadata = {}
        result = await executor.execute(sample_run, self._make_pipeline())

        # Should return CANCELLED
        assert result == RunStatus.CANCELLED

        mock_backend.create_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_executor_does_not_publish_collecting_when_mark_collecting_returns_false(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, sample_run
    ):
        """P1-4 regression: when mark_collecting returns False (cancel race),
        executor must NOT publish COLLECTING status event. It should early-return
        with CANCELLED status instead."""
        mock_run_repo.mark_running.return_value = True
        mock_run_repo.mark_collecting.return_value = False

        executor = RunExecutor(
            backend=mock_backend,
            log_stream=mock_log_stream,
            run_repo=mock_run_repo,
            plugin_registry=mock_plugin_registry,
        )

        sample_run.metadata = {}
        with patch(
            "qaplatform.engine.executor.publish_status_event",
            new_callable=AsyncMock,
        ) as publish_status_event:
            result = await executor.execute(sample_run, self._make_pipeline())

        # Should return CANCELLED, not proceed to COLLECTING
        assert result == RunStatus.CANCELLED, (
            f"expected RunStatus.CANCELLED when mark_collecting returns False, got {result}"
        )
        publish_status_event.assert_awaited_once_with(
            None,
            str(sample_run.id),
            RunStatus.RUNNING.value,
            previous=RunStatus.PREPARING.value,
        )
        mock_run_repo.mark_collecting.assert_awaited_once_with(str(sample_run.id))
        mock_run_repo.finish_if_current.assert_not_awaited()
        mock_run_repo.fail_if_current.assert_not_awaited()
        logged_messages = [
            log_call.args[1] for log_call in mock_log_stream.write_log.await_args_list
        ]
        assert "Collecting test results..." not in logged_messages


# --------------------------------------------------------------------------- #
# T13 retry-failed subset filtering
# --------------------------------------------------------------------------- #


class TestRetryFailedSubsetFiltering:
    """A retry-failed run must execute only the failed cases.

    The reconstructed nodeids and the stage's configured ``test_path`` are
    both pytest positional arguments, so passing them together makes pytest
    re-collect the whole directory and the subset filter silently degrades
    into a full re-run. These tests drive the real PytestRunner so the
    assertion is on the actual command line, not on a re-derived shape.
    """

    def _make_executor(self, captured):
        from qaplatform.plugins.builtin.pytest_runner import PytestRunner

        backend = AsyncMock()
        backend.create_execution = AsyncMock(return_value="exec-1")
        backend.start = AsyncMock()
        backend.wait = AsyncMock(
            return_value=ExitResult(
                exit_code=0,
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )
        backend.cleanup = AsyncMock()

        async def _empty_logs(_id):
            if False:
                yield
        backend.stream_logs = _empty_logs

        registry = MagicMock(spec=PluginRegistry)
        real_runner = PytestRunner()

        class _CapturingRunner:
            def build_command(self, config):
                cmd = real_runner.build_command(config)
                captured.append(cmd)
                return cmd

        registry.get_runner.return_value = _CapturingRunner()

        run_repo = AsyncMock()
        run_repo.is_cancel_requested.return_value = False

        return RunExecutor(
            backend=backend,
            log_stream=AsyncMock(),
            run_repo=run_repo,
            plugin_registry=registry,
        )

    def _make_pipeline(self):
        from qaplatform.engine.executor import StageDefinition
        return PipelineConfig(
            image="python:3.12-slim",
            stages=[
                StageDefinition(
                    name="pytest",
                    plugin="pytest",
                    config={"test_path": "tests/", "args": ["-v"]},
                )
            ],
            timeout_seconds=60,
        )

    def _make_run(self, metadata):
        run = MagicMock(spec=Run)
        run.id = uuid4()
        run.project_id = uuid4()
        run.git_ref = "main"
        run.git_sha = None
        run.metadata = metadata
        return run

    @pytest.mark.asyncio
    async def test_nodeids_replace_test_path(self, tmp_path):
        """Only the two failed nodeids may reach pytest; the broad
        ``tests/`` path must be gone or pytest re-collects everything."""
        captured: list[str] = []
        executor = self._make_executor(captured)
        run = self._make_run({
            "git_url": "https://github.com/org/repo.git",
            "retry_failed_cases": [
                {"suite": "tests.test_mixed", "name": "test_beta_fails"},
                {"suite": "tests.test_mixed", "name": "test_gamma_fails"},
            ],
        })

        await executor._run_stages(run, self._make_pipeline(), tmp_path)

        assert len(captured) == 1
        cmd = captured[0]
        for nodeid in (
            "tests/test_mixed.py::test_beta_fails",
            "tests/test_mixed.py::test_gamma_fails",
        ):
            assert nodeid in cmd, f"{nodeid} missing from: {cmd}"
        tokens = shlex.split(cmd.replace("cd /workspace && ", ""))
        assert "tests/" not in tokens, (
            f"broad test path still passed to pytest, subset filter is a no-op: {cmd}"
        )

    @pytest.mark.asyncio
    async def test_normal_run_keeps_test_path(self, tmp_path):
        """A run without retry_failed_cases must still run the whole path."""
        captured: list[str] = []
        executor = self._make_executor(captured)
        run = self._make_run({"git_url": "https://github.com/org/repo.git"})

        await executor._run_stages(run, self._make_pipeline(), tmp_path)

        assert len(captured) == 1
        tokens = shlex.split(captured[0].replace("cd /workspace && ", ""))
        assert "tests/" in tokens
