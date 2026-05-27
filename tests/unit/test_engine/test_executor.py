from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.domain.models.run import Run, RunStatus
from qaplatform.engine.executor import RunExecutor
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
    run.metadata = {"git_url": "https://github.com/org/repo.git"}
    return run


class TestRunSetupContainerised:
    """Regression tests for the P0 fix that moved setup_script execution
    from `asyncio.create_subprocess_shell` (worker host) into the same
    sandbox backend as stages.
    """

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
        # script as ["sh", "-c", <script>] and the workspace mount.
        mock_backend.create_execution.assert_called_once()
        spec = mock_backend.create_execution.call_args.args[0]
        assert isinstance(spec, ExecutionSpec)
        assert spec.image == "python:3.12-alpine"
        assert spec.command[:2] == ["sh", "-c"]
        assert spec.command[2] == "pip install -r requirements.txt"
        assert any(m.target == "/workspace" for m in spec.mounts)
        # Setup container is labeled distinctly so an operator inspecting
        # docker ps can tell setup containers from stage containers.
        assert spec.labels.get("phase") == "setup"

    @pytest.mark.asyncio
    async def test_setup_timeout_capped_at_600s(
        self, executor, mock_backend, sample_run, tmp_path
    ):
        from qaplatform.engine.executor import PipelineConfig
        pipeline = PipelineConfig(
            image="python:3.12-alpine",
            stages=[],
            timeout_seconds=3600,  # well over 600
            setup_script="echo hi",
        )

        mock_backend.create_execution = AsyncMock(return_value="c")
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

        # The wait timeout is the second positional arg to backend.wait().
        wait_args = mock_backend.wait.call_args
        timeout_passed = wait_args.args[1]
        assert timeout_passed == 600, f"expected 600s cap, got {timeout_passed}"

    @pytest.mark.asyncio
    async def test_setup_uses_pipeline_timeout_when_below_cap(
        self, executor, mock_backend, sample_run, tmp_path
    ):
        from qaplatform.engine.executor import PipelineConfig
        pipeline = PipelineConfig(
            image="python:3.12-alpine",
            stages=[],
            timeout_seconds=120,
            setup_script="echo hi",
        )

        mock_backend.create_execution = AsyncMock(return_value="c")
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
        assert mock_backend.wait.call_args.args[1] == 120

    @pytest.mark.asyncio
    async def test_setup_nonzero_exit_raises(
        self, executor, mock_backend, sample_run, setup_pipeline, tmp_path
    ):
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

        with pytest.raises(RuntimeError, match="Setup script failed"):
            await executor._run_setup(sample_run, setup_pipeline, tmp_path)

    @pytest.mark.asyncio
    async def test_setup_timeout_raises(
        self, executor, mock_backend, sample_run, setup_pipeline, tmp_path
    ):
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

        with pytest.raises(RuntimeError, match="timed out"):
            await executor._run_setup(sample_run, setup_pipeline, tmp_path)

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

        with patch.object(
            executor, "_graceful_stop", new=AsyncMock()
        ) as graceful:
            with pytest.raises(RuntimeError, match="timed out"):
                await executor._run_setup(sample_run, setup_pipeline, tmp_path)

        graceful.assert_awaited_once()
        kwargs = graceful.call_args.kwargs
        assert "setup timeout" in kwargs.get("reason", "")
        mock_backend.cleanup.assert_awaited_once()

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

        mock_backend.cleanup.assert_awaited_once()


class TestExecutorUsesSourcePlugin:
    """Verify executor delegates to SourceProtocol plugin."""

    @pytest.mark.asyncio
    async def test_clone_repo_uses_plugin(self, executor, sample_run, mock_plugin_registry):
        dest = Path("/tmp/test")
        await executor._clone_repo(sample_run, dest)

        mock_plugin_registry.get_source.assert_called_once_with("git")
        source = mock_plugin_registry.get_source.return_value
        source.clone.assert_called_once_with(
            "https://github.com/org/repo.git", "main", dest,
        )

    @pytest.mark.asyncio
    async def test_clone_repo_updates_git_sha(self, executor, sample_run, mock_run_repo, mock_plugin_registry):
        dest = Path("/tmp/test")
        await executor._clone_repo(sample_run, dest)

        mock_run_repo.update_git_sha.assert_called_once_with(
            sample_run.id, "abc123def456",
        )

    @pytest.mark.asyncio
    async def test_clone_repo_skips_when_no_git_url(self, executor, mock_log_stream, mock_plugin_registry):
        run = MagicMock(spec=Run)
        run.id = uuid4()
        run.git_ref = "main"
        run.metadata = {}

        dest = Path("/tmp/test")
        await executor._clone_repo(run, dest)

        mock_plugin_registry.get_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_clone_repo_propagates_error(self, executor, sample_run, mock_plugin_registry):
        source = mock_plugin_registry.get_source.return_value
        source.clone.side_effect = RuntimeError("git clone failed (exit 128): fatal: repo not found")

        dest = Path("/tmp/test")
        with pytest.raises(RuntimeError, match="git clone failed"):
            await executor._clone_repo(sample_run, dest)


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

        assert s3.put_object.await_count == 3
        assert artifact_repo.create.await_count == 3

        recorded = {call.kwargs["name"]: call.kwargs for call in artifact_repo.create.call_args_list}
        assert recorded["junit.xml"]["type"] == "junit"
        assert recorded["junit.xml"]["mime_type"] in {"application/xml", "text/xml"}
        assert recorded["junit.xml"]["storage_path"] == f"reports/{run_id}/junit.xml"
        assert recorded["junit.xml"]["size_bytes"] == len(b"<testsuites/>")

        assert recorded["report.html"]["type"] == "report"
        assert recorded["report.html"]["mime_type"] == "text/html"

        assert recorded["extra.bin"]["type"] == "other"
        assert recorded["extra.bin"]["mime_type"] == "application/octet-stream"

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

        uploaded_keys = {call.kwargs["Key"] for call in s3.put_object.await_args_list}
        assert uploaded_keys == {
            f"reports/{run_id}/allure-report/assets/app.js",
            f"reports/{run_id}/allure-report/index.html",
        }
        recorded = {call.kwargs["name"]: call.kwargs for call in artifact_repo.create.call_args_list}
        assert set(recorded) == {
            "allure-report/assets/app.js",
            "allure-report/index.html",
        }
        assert recorded["allure-report/index.html"]["type"] == "allure-report"
        assert recorded["allure-report/index.html"]["mime_type"] == "text/html"
        assert recorded["allure-report/assets/app.js"]["type"] == "allure-report"

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
            artifact_repo=None,
        )
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "x.xml").write_bytes(b"<x/>")

        # Should not raise — artifact_repo=None is allowed (S3-only mode)
        await executor._upload_artifacts("rid", tmp_path)
        s3.put_object.assert_awaited_once()

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

        await executor._upload_artifacts(
            "11111111-1111-1111-1111-111111111111",
            tmp_path,
            ResourceLimits(max_artifact_size_bytes=2, max_artifacts_count=10),
        )

        s3.put_object.assert_awaited_once()
        assert s3.put_object.call_args.kwargs["Key"].endswith("/small.txt")
        artifact_repo.create.assert_awaited_once()
        assert artifact_repo.create.call_args.kwargs["name"] == "small.txt"
        assert any(
            "exceeds limit" in call.args[1]
            for call in mock_log_stream.write_log.await_args_list
        )

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

        await executor._upload_artifacts(
            "11111111-1111-1111-1111-111111111111",
            tmp_path,
            ResourceLimits(max_artifact_size_bytes=100, max_artifacts_count=1),
        )

        s3.put_object.assert_awaited_once()
        assert s3.put_object.call_args.kwargs["Key"].endswith("/a.txt")
        artifact_repo.create.assert_awaited_once()
        assert artifact_repo.create.call_args.kwargs["name"] == "a.txt"
        assert any(
            "count limit exceeded" in call.args[1]
            for call in mock_log_stream.write_log.await_args_list
        )


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

        messages = [
            call.args[1]
            for call in timeout_executor.log_stream.write_log.await_args_list
        ]
        assert any(
            "exceeded timeout" in m and "pytest" in m and "42" in m for m in messages
        ), f"expected timeout log entry, got: {messages}"

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

    @pytest.mark.asyncio
    async def test_commit_called_after_mark_running(
        self, happy_executor, sample_run, mock_run_repo
    ):
        """mark_running must be followed by run_repo.commit()."""
        sample_run.metadata = {}  # skip _clone_repo
        await happy_executor.execute(sample_run, self._make_pipeline())

        mock_run_repo.mark_running.assert_awaited_once()
        # commit was invoked at least twice (after mark_running + mark_collecting)
        assert mock_run_repo.commit.await_count >= 2

    @pytest.mark.asyncio
    async def test_commit_called_after_mark_collecting(
        self, happy_executor, sample_run, mock_run_repo
    ):
        """mark_collecting must be followed by run_repo.commit()."""
        sample_run.metadata = {}
        await happy_executor.execute(sample_run, self._make_pipeline())

        mock_run_repo.mark_collecting.assert_awaited_once()
        assert mock_run_repo.commit.await_count >= 2

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

    @pytest.mark.asyncio
    async def test_executor_logs_when_mark_running_skipped(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, sample_run
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

        logged_calls: list[tuple] = []

        import logging
        original_info = logging.Logger.info

        def _capture_info(self_logger, msg, *args, **kwargs):
            logged_calls.append((msg, kwargs))
            return original_info(self_logger, msg, *args, **kwargs)

        sample_run.metadata = {}
        with patch("logging.Logger.info", _capture_info):
            await executor.execute(sample_run, self._make_pipeline())

        skipped = [
            (msg, kw) for msg, kw in logged_calls
            if msg == "run_status_transition_skipped"
        ]
        assert skipped, (
            "expected at least one 'run_status_transition_skipped' log call "
            f"when mark_running returns False; got log calls: {logged_calls}"
        )
        extra = skipped[0][1].get("extra", {})
        assert extra.get("from_") == "preparing", (
            f"expected from_='preparing' in log extra, got: {extra}"
        )
        assert extra.get("to") == "running", (
            f"expected to='running' in log extra, got: {extra}"
        )

    @pytest.mark.asyncio
    async def test_executor_logs_when_mark_collecting_skipped(
        self, mock_backend, mock_log_stream, mock_run_repo, mock_plugin_registry, sample_run
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

        logged_calls: list[tuple] = []

        import logging
        original_info = logging.Logger.info

        def _capture_info(self_logger, msg, *args, **kwargs):
            logged_calls.append((msg, kwargs))
            return original_info(self_logger, msg, *args, **kwargs)

        sample_run.metadata = {}
        with patch("logging.Logger.info", _capture_info):
            await executor.execute(sample_run, self._make_pipeline())

        skipped = [
            (msg, kw) for msg, kw in logged_calls
            if msg == "run_status_transition_skipped"
        ]
        assert skipped, (
            "expected at least one 'run_status_transition_skipped' log call "
            f"when mark_collecting returns False; got log calls: {logged_calls}"
        )
        extra = skipped[0][1].get("extra", {})
        assert extra.get("from_") == "running", (
            f"expected from_='running' in log extra, got: {extra}"
        )
        assert extra.get("to") == "collecting", (
            f"expected to='collecting' in log extra, got: {extra}"
        )

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
        result = await executor.execute(sample_run, self._make_pipeline())

        # Should return CANCELLED, not proceed to RUNNING
        assert result == RunStatus.CANCELLED, (
            f"expected RunStatus.CANCELLED when mark_running returns False, got {result}"
        )

        # _publish should NOT be called with RUNNING status
        # Check that no RUNNING status was published
        for call in mock_log_stream.method_calls:
            if "_publish" in str(call):
                # This is a mock call, check the arguments
                pass

        # More direct: check that _run_stages was never called
        # (it would be called after _publish(RUNNING))
        assert not mock_backend.create.called or mock_backend.create.call_count == 0, (
            "backend.create should not be called when mark_running returns False"
        )

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

        # backend.create should not be called (it's called in _run_stages)
        assert not mock_backend.create.called, (
            "backend.create should not be called when mark_running returns False; "
            "_run_stages should not be entered"
        )

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
        result = await executor.execute(sample_run, self._make_pipeline())

        # Should return CANCELLED, not proceed to COLLECTING
        assert result == RunStatus.CANCELLED, (
            f"expected RunStatus.CANCELLED when mark_collecting returns False, got {result}"
        )
