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
    return backend


@pytest.fixture
def mock_log_stream():
    return AsyncMock()


@pytest.fixture
def mock_run_repo():
    repo = AsyncMock()
    repo.mark_running.return_value = None
    repo.mark_collecting.return_value = None
    repo.update_execution_id.return_value = None
    repo.update_git_sha.return_value = None
    repo.finish_if_current.return_value = True
    repo.fail_if_current.return_value = True
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
    run.git_ref = "main"
    run.metadata = {"git_url": "https://github.com/org/repo.git"}
    return run


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
