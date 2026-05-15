"""Tests for the Docker execution backend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest

from qaplatform.engine.docker_backend import (
    DockerBackend,
    ExecutionSpec,
    LogLine,
    Mount,
    ResourceLimits,
    SandboxSecurity,
)


class TestDockerBackend:
    def setup_method(self):
        self.docker_client = MagicMock()
        self.backend = DockerBackend(self.docker_client)

    # -- security helpers ----------------------------------------------------

    def test_security_opt_default(self):
        result = DockerBackend._security_opt(SandboxSecurity())
        assert result == ["no-new-privileges"]

    def test_security_opt_with_seccomp(self):
        sec = SandboxSecurity(seccomp_profile="/path/to/profile.json")
        result = DockerBackend._security_opt(sec)
        assert "no-new-privileges" in result
        assert "seccomp=/path/to/profile.json" in result

    def test_network_mode_deny(self):
        assert DockerBackend._network_mode("deny") == "none"

    def test_network_mode_allow(self):
        assert DockerBackend._network_mode("allow") == "bridge"

    def test_network_mode_restricted(self):
        assert DockerBackend._network_mode("restricted") == "qap-restricted"

    def test_network_mode_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown network policy"):
            DockerBackend._network_mode("unknown")

    def test_build_binds_empty(self):
        assert DockerBackend._build_binds([]) == []

    def test_build_binds_readwrite(self):
        mounts = [Mount(source="/src", target="/workspace")]
        result = DockerBackend._build_binds(mounts)
        assert result == ["/src:/workspace:rw"]

    def test_build_binds_readonly(self):
        mounts = [Mount(source="/src", target="/workspace", read_only=True)]
        result = DockerBackend._build_binds(mounts)
        assert result == ["/src:/workspace:ro"]

    # -- log frame decoding --------------------------------------------------

    def test_decode_log_frame_stdout(self):
        # Docker multiplexed frame: stream_type=1 (stdout), 4 bytes unused, 4 bytes size
        header = bytes([1, 0, 0, 0, 0, 0, 0, 5])
        payload = b"hello"
        stream, content = DockerBackend._decode_log_frame(header + payload)
        assert stream == "stdout"
        assert content == "hello"

    def test_decode_log_frame_stderr(self):
        header = bytes([2, 0, 0, 0, 0, 0, 0, 3])
        payload = b"err"
        stream, content = DockerBackend._decode_log_frame(header + payload)
        assert stream == "stderr"
        assert content == "err"

    def test_decode_log_frame_tty_mode(self):
        # Raw text without Docker header (TTY mode)
        raw = b"plain output\n"
        stream, content = DockerBackend._decode_log_frame(raw)
        assert stream == "stdout"
        assert content == "plain output"

    # -- create_execution ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_execution(self):
        mock_container = MagicMock()
        mock_container.id = "abc123def456"

        mock_containers = MagicMock()
        mock_containers.create_or_replace = AsyncMock(return_value=mock_container)
        self.docker_client.containers = mock_containers

        spec = ExecutionSpec(
            image="python:3.12",
            command=["pytest"],
            env_vars={"PYTHONDONTWRITEBYTECODE": "1"},
            labels={"run_id": "run-123"},
        )

        result = await self.backend.create_execution(spec)
        assert result == "abc123def456"

        # Verify container config
        call_kwargs = mock_containers.create_or_replace.call_args
        config = call_kwargs.kwargs["config"]
        assert config["Image"] == "python:3.12"
        assert config["User"] == "1000:1000"
        assert config["HostConfig"]["ReadonlyRootfs"] is True
        assert config["HostConfig"]["PidsLimit"] == 256
        assert config["HostConfig"]["NetworkMode"] == "none"  # deny -> none
        assert "managed-by" in config["Labels"]
        assert config["Labels"]["run_id"] == "run-123"
        assert config["HostConfig"]["Tmpfs"] == {"/tmp": "rw,noexec,nosuid,size=256m"}

    # -- start ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_start(self):
        mock_container = MagicMock()
        mock_container.start = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.start("container-id")
        mock_container.start.assert_awaited_once()

    # -- cancel ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cancel_sends_sigterm(self):
        mock_container = MagicMock()
        mock_container.kill = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.cancel("container-id")
        mock_container.kill.assert_awaited_once_with(signal="SIGTERM")

    # -- force_kill ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_force_kill_sends_sigkill(self):
        mock_container = MagicMock()
        mock_container.kill = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.force_kill("container-id")
        mock_container.kill.assert_awaited_once_with(signal="SIGKILL")

    # -- cleanup -------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cleanup_deletes_container(self):
        mock_container = MagicMock()
        mock_container.delete = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.cleanup("container-id")
        mock_container.delete.assert_awaited_once_with(force=True)

    # -- resource limits -----------------------------------------------------

    def test_resource_limits_defaults(self):
        rl = ResourceLimits()
        assert rl.cpu_cores == 1.0
        assert rl.memory_bytes == 512 * 1024 * 1024

    def test_execution_spec_default_security(self):
        spec = ExecutionSpec(image="test", command=["test"], env_vars={})
        assert spec.security.readonly_rootfs is True
        assert spec.security.pids_limit == 256
        assert spec.security.cap_drop == ["ALL"]
        assert spec.network_policy == "deny"
        assert spec.user == "1000:1000"
