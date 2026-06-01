"""Tests for the Docker execution backend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiodocker
import pytest

from qaplatform.engine.docker_backend import (
    DockerBackend,
    ExecutionSpec,
    Mount,
    ResourceLimits,
    SandboxSecurity,
)


class TestDockerBackend:
    def setup_method(self):
        self.docker_client = MagicMock()
        self.backend = DockerBackend(self.docker_client)

    @staticmethod
    def _created_container_kwargs(mock_containers):
        mock_containers.create_or_replace.assert_awaited_once()
        return mock_containers.create_or_replace.await_args.kwargs

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
        with pytest.raises(ValueError) as exc_info:
            DockerBackend._network_mode("unknown")

        assert exc_info.value.args == ("Unknown network policy: unknown",)

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

    def test_decode_log_frame_aiodocker_text(self):
        stream, content = DockerBackend._decode_log_frame("plain output\n")
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

        assert self._created_container_kwargs(mock_containers) == {
            "name": "qap-run-run-123",
            "config": {
                "Image": "python:3.12",
                "Cmd": ["pytest"],
                "Env": ["PYTHONDONTWRITEBYTECODE=1"],
                "User": "1000:1000",
                "AttachStdout": True,
                "AttachStderr": True,
                "HostConfig": {
                    "Memory": 512 * 1024 * 1024,
                    "MemorySwap": 512 * 1024 * 1024,
                    "NanoCpus": 1_000_000_000,
                    "ReadonlyRootfs": True,
                    "SecurityOpt": ["no-new-privileges"],
                    "CapDrop": ["ALL"],
                    "CapAdd": [],
                    "PidsLimit": 256,
                    "Devices": [],
                    "NetworkMode": "none",
                    "Init": True,
                    "Binds": [],
                    "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
                },
                "Labels": {
                    "managed-by": "qaplatform",
                    "run_id": "run-123",
                },
            },
        }

    @pytest.mark.asyncio
    async def test_create_execution_sets_storage_opt_when_disk_limit_present(self):
        mock_container = MagicMock()
        mock_container.id = "disk-test"

        mock_containers = MagicMock()
        mock_containers.create_or_replace = AsyncMock(return_value=mock_container)
        self.docker_client.containers = mock_containers

        spec = ExecutionSpec(
            image="busybox",
            command=["true"],
            env_vars={},
            resource_limits=ResourceLimits(disk_bytes=64 * 1024 * 1024),
            labels={"run_id": "r"},
        )

        await self.backend.create_execution(spec)

        create_kwargs = self._created_container_kwargs(mock_containers)
        assert create_kwargs["name"] == "qap-run-r"
        config = create_kwargs["config"]
        assert config["HostConfig"]["StorageOpt"] == {"size": "64M"}

    @pytest.mark.asyncio
    async def test_create_execution_disables_swap_to_enforce_memory_cap(self):
        """F-PL-03: the memory cap must be a hard ceiling. Docker defaults
        MemorySwap to 2× Memory if unset, which would let workloads use
        twice the configured limit via swap. Setting MemorySwap == Memory
        disables swap entirely so the cap is real.
        """
        mock_container = MagicMock()
        mock_container.id = "swap-test"
        mock_containers = MagicMock()
        mock_containers.create_or_replace = AsyncMock(return_value=mock_container)
        self.docker_client.containers = mock_containers

        spec = ExecutionSpec(
            image="busybox",
            command=["true"],
            env_vars={},
            resource_limits=ResourceLimits(memory_bytes=128 * 1024 * 1024),
            labels={"run_id": "r"},
        )

        await self.backend.create_execution(spec)
        config = self._created_container_kwargs(mock_containers)["config"]
        memory = config["HostConfig"]["Memory"]
        memory_swap = config["HostConfig"]["MemorySwap"]
        assert memory == 128 * 1024 * 1024
        assert memory_swap == memory, (
            "MemorySwap must equal Memory; otherwise Docker grants 2× "
            "memory_bytes via swap and the F-PL-03 limit can be exceeded."
        )

    @pytest.mark.asyncio
    async def test_create_execution_enables_init_for_signal_forwarding(self):
        """Init=True ensures tini is PID 1, forwarding SIGTERM to user processes
        (without it, sh/python/etc. as PID 1 ignore non-SIGKILL signals,
        breaking F-EX-06 cancel timing)."""
        mock_container = MagicMock()
        mock_container.id = "init-test"
        mock_containers = MagicMock()
        mock_containers.create_or_replace = AsyncMock(return_value=mock_container)
        self.docker_client.containers = mock_containers

        spec = ExecutionSpec(
            image="busybox",
            command=["true"],
            env_vars={},
            resource_limits=ResourceLimits(memory_bytes=128 * 1024 * 1024),
            labels={"run_id": "r"},
        )

        await self.backend.create_execution(spec)
        config = self._created_container_kwargs(mock_containers)["config"]
        assert config["HostConfig"]["Init"] is True

    # -- start ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_start(self):
        mock_container = MagicMock()
        mock_container.start = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.start("container-id")
        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.start.assert_awaited_once_with()

    # -- wait -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_wait_reads_oom_killed_from_show(self):
        """OOMKilled lives on /containers/{id}/json State, not on /wait response."""
        mock_container = MagicMock()
        mock_container.wait = AsyncMock(return_value={"StatusCode": 137})
        mock_container.show = AsyncMock(
            return_value={"State": {"OOMKilled": True, "ExitCode": 137}}
        )
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        result = await self.backend.wait("container-id", timeout=10)

        assert result.oom_killed is True
        assert result.exit_code == 137
        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.wait.assert_awaited_once_with(timeout=10)
        mock_container.show.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_wait_retries_oom_inspect_after_sigkill_exit(self):
        mock_container = MagicMock()
        mock_container.wait = AsyncMock(return_value={"StatusCode": 137})
        mock_container.show = AsyncMock(
            side_effect=[
                {"State": {"OOMKilled": False, "ExitCode": 137}},
                {"State": {"OOMKilled": True, "ExitCode": 137}},
            ]
        )
        sleep = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        with patch("qaplatform.engine.docker_backend.asyncio.sleep", new=sleep):
            result = await self.backend.wait("container-id", timeout=10)

        assert result.oom_killed is True
        assert result.exit_code == 137
        mock_container.wait.assert_awaited_once_with(timeout=10)
        assert [show_call.args for show_call in mock_container.show.await_args_list] == [
            (),
            (),
        ]
        sleep.assert_awaited_once_with(0.25)

    @pytest.mark.asyncio
    async def test_wait_oom_killed_false_on_normal_exit(self):
        mock_container = MagicMock()
        mock_container.wait = AsyncMock(return_value={"StatusCode": 0})
        mock_container.show = AsyncMock(
            return_value={"State": {"OOMKilled": False, "ExitCode": 0}}
        )
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        result = await self.backend.wait("container-id", timeout=10)

        assert result.oom_killed is False
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_wait_oom_killed_defaults_false_on_show_error(self):
        """show() failure must not propagate; degrade to oom_killed=False."""
        mock_container = MagicMock()
        mock_container.wait = AsyncMock(return_value={"StatusCode": 0})
        mock_container.show = AsyncMock(side_effect=Exception("inspect failed"))
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        result = await self.backend.wait("container-id", timeout=10)

        assert result.oom_killed is False
        assert result.exit_code == 0

    def test_parse_resource_usage_reads_peak_memory_cpu_and_pids(self):
        stats = {
            "memory_stats": {
                "usage": 64 * 1024 * 1024,
                "max_usage": 96 * 1024 * 1024,
                "limit": 128 * 1024 * 1024,
            },
            "cpu_stats": {
                "cpu_usage": {"total_usage": 300, "percpu_usage": [150, 150]},
                "system_cpu_usage": 400,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 200,
            },
            "pids_stats": {"current": 5},
        }

        sample = DockerBackend._parse_resource_usage(stats)

        assert sample.memory_usage_bytes == 64 * 1024 * 1024
        assert sample.memory_max_usage_bytes == 96 * 1024 * 1024
        assert sample.memory_limit_bytes == 128 * 1024 * 1024
        assert sample.cpu_percent == pytest.approx(200.0)
        assert sample.pids_current == 5

    # -- cancel ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cancel_sends_sigterm(self):
        mock_container = MagicMock()
        mock_container.kill = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.cancel("container-id")
        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.kill.assert_awaited_once_with(signal="SIGTERM")

    @pytest.mark.asyncio
    async def test_cancel_ignores_already_stopped_conflict(self):
        mock_container = MagicMock()
        mock_container.kill = AsyncMock(
            side_effect=aiodocker.DockerError(409, "already stopped")
        )
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.cancel("container-id")

        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.kill.assert_awaited_once_with(signal="SIGTERM")

    @pytest.mark.asyncio
    async def test_cancel_reraises_unexpected_docker_error(self):
        docker_error = aiodocker.DockerError(500, "daemon exploded")
        mock_container = MagicMock()
        mock_container.kill = AsyncMock(side_effect=docker_error)
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        with pytest.raises(aiodocker.DockerError) as exc_info:
            await self.backend.cancel("container-id")

        assert exc_info.value is docker_error
        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.kill.assert_awaited_once_with(signal="SIGTERM")

    # -- force_kill ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_force_kill_sends_sigkill(self):
        mock_container = MagicMock()
        mock_container.kill = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.force_kill("container-id")
        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.kill.assert_awaited_once_with(signal="SIGKILL")

    @pytest.mark.asyncio
    async def test_force_kill_ignores_already_stopped_conflict(self):
        mock_container = MagicMock()
        mock_container.kill = AsyncMock(
            side_effect=aiodocker.DockerError(409, "already stopped")
        )
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.force_kill("container-id")

        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.kill.assert_awaited_once_with(signal="SIGKILL")

    # -- cleanup -------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cleanup_deletes_container(self):
        mock_container = MagicMock()
        mock_container.delete = AsyncMock()
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.cleanup("container-id")
        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.delete.assert_awaited_once_with(force=True)

    @pytest.mark.asyncio
    async def test_cleanup_ignores_already_removed_container(self):
        mock_container = MagicMock()
        mock_container.delete = AsyncMock(
            side_effect=aiodocker.DockerError(404, "not found")
        )
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        await self.backend.cleanup("container-id")

        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.delete.assert_awaited_once_with(force=True)

    @pytest.mark.asyncio
    async def test_cleanup_reraises_unexpected_docker_error(self):
        docker_error = aiodocker.DockerError(500, "daemon exploded")
        mock_container = MagicMock()
        mock_container.delete = AsyncMock(side_effect=docker_error)
        self.docker_client.containers.container = MagicMock(return_value=mock_container)

        with pytest.raises(aiodocker.DockerError) as exc_info:
            await self.backend.cleanup("container-id")

        assert exc_info.value is docker_error
        self.docker_client.containers.container.assert_called_once_with("container-id")
        mock_container.delete.assert_awaited_once_with(force=True)

    # -- resource limits -----------------------------------------------------

    def test_resource_limits_defaults(self):
        rl = ResourceLimits()
        assert rl.cpu_cores == 1.0
        assert rl.memory_bytes == 512 * 1024 * 1024
        assert rl.disk_bytes is None

    def test_execution_spec_default_security(self):
        spec = ExecutionSpec(image="test", command=["test"], env_vars={})
        assert spec.security.readonly_rootfs is True
        assert spec.security.pids_limit == 256
        assert spec.security.cap_drop == ["ALL"]
        assert spec.network_policy == "deny"
        assert spec.user == "1000:1000"
