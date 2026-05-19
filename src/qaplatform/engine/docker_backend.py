from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Protocol

import aiodocker

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data types (match architecture §6.1)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResourceLimits:
    cpu_cores: float = 1.0
    memory_bytes: int = 512 * 1024 * 1024  # 512 MiB
    disk_bytes: int | None = None
    max_artifact_size_bytes: int = 500 * 1024 * 1024
    max_artifacts_count: int = 100


@dataclass(frozen=True)
class ExitResult:
    exit_code: int
    started_at: datetime
    finished_at: datetime
    oom_killed: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class SandboxSecurity:
    readonly_rootfs: bool = True
    seccomp_profile: str | None = None
    cap_drop: list[str] = field(default_factory=lambda: ["ALL"])
    cap_add: list[str] = field(default_factory=list)
    pids_limit: int = 256
    devices: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Mount:
    source: str
    target: str
    read_only: bool = False


@dataclass(frozen=True)
class ExecutionSpec:
    image: str
    command: list[str]
    env_vars: dict[str, str]
    mounts: list[Mount] = field(default_factory=list)
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    network_policy: str = "deny"
    user: str = "1000:1000"
    security: SandboxSecurity = field(default_factory=SandboxSecurity)
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LogLine:
    timestamp: datetime
    stream: str  # "stdout" | "stderr"
    content: str


# --------------------------------------------------------------------------- #
# Backend protocol (for testing / swapping)
# --------------------------------------------------------------------------- #


class ExecutionBackend(Protocol):
    """Execution backend abstraction, supporting Docker and Kubernetes."""

    async def create_execution(self, spec: ExecutionSpec) -> str: ...
    async def start(self, execution_id: str) -> None: ...
    def stream_logs(self, execution_id: str) -> AsyncIterator[LogLine]: ...
    async def wait(self, execution_id: str, timeout: int) -> ExitResult: ...
    async def cancel(self, execution_id: str) -> None: ...
    async def force_kill(self, execution_id: str) -> None: ...
    async def cleanup(self, execution_id: str) -> None: ...


# --------------------------------------------------------------------------- #
# Docker backend
# --------------------------------------------------------------------------- #


class DockerBackend:
    """Docker execution backend using aiodocker."""

    def __init__(self, docker_client: aiodocker.Docker) -> None:
        self.client = docker_client

    async def create_execution(self, spec: ExecutionSpec) -> str:
        """Create a Docker container with sandbox security. Returns container id."""
        container_config: dict = {
            "Image": spec.image,
            "Cmd": spec.command,
            "Env": [f"{k}={v}" for k, v in spec.env_vars.items()],
            "User": spec.user,
            "HostConfig": {
                "Memory": spec.resource_limits.memory_bytes,
                # Match MemorySwap to Memory so Docker doesn't silently
                # grant 2× memory_bytes via swap (the default), which would
                # let workloads exceed the F-PL-03 memory cap. Equal values
                # disable swap entirely — the limit is a hard ceiling.
                "MemorySwap": spec.resource_limits.memory_bytes,
                "NanoCpus": int(spec.resource_limits.cpu_cores * 1e9),
                "ReadonlyRootfs": spec.security.readonly_rootfs,
                "SecurityOpt": self._security_opt(spec.security),
                "CapDrop": spec.security.cap_drop,
                "CapAdd": spec.security.cap_add,
                "PidsLimit": spec.security.pids_limit,
                "Devices": spec.security.devices,
                "NetworkMode": self._network_mode(spec.network_policy),
                # Init=True runs tini as PID 1; without it, sh/python/etc. as PID 1 ignore
                # non-SIGKILL signals per Linux kernel rules, breaking F-EX-06 cancel timing.
                "Init": True,
                "Binds": self._build_binds(spec.mounts),
                "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
            },
            "Labels": {
                "managed-by": "qaplatform",
                **spec.labels,
            },
        }

        run_id = spec.labels.get("run_id", "unknown")
        name = f"qap-run-{run_id}"
        container = await self.client.containers.create_or_replace(
            name=name,
            config=container_config,
        )
        log.info("created container %s for run %s", container.id[:12], run_id)
        return container.id

    async def start(self, execution_id: str) -> None:
        container = self.client.containers.container(execution_id)
        await container.start()
        log.info("started container %s", execution_id[:12])

    async def stream_logs(self, execution_id: str) -> AsyncIterator[LogLine]:
        container = self.client.containers.container(execution_id)
        async for raw in container.log(stdout=True, stderr=True, follow=True):
            stream, content = self._decode_log_frame(raw)
            yield LogLine(
                timestamp=datetime.now(timezone.utc),
                stream=stream,
                content=content,
            )

    async def wait(self, execution_id: str, timeout: int) -> ExitResult:
        container = self.client.containers.container(execution_id)
        started_at = datetime.now(timezone.utc)

        try:
            result = await container.wait(timeout=timeout)
        except Exception as e:
            log.error("container.wait failed for %s: %s", execution_id[:12], e)
            return ExitResult(
                exit_code=-1,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                oom_killed=False,
            )

        finished_at = datetime.now(timezone.utc)
        exit_code = result.get("StatusCode", -1)

        # Docker /containers/{id}/wait only returns {StatusCode, Error}; OOMKilled
        # lives on the container State, so inspect via /containers/{id}/json.
        try:
            info = await container.show()
            oom_killed = bool(info.get("State", {}).get("OOMKilled", False))
        except Exception:
            log.warning("failed to inspect OOMKilled for execution %s", execution_id[:12])
            oom_killed = False

        return ExitResult(
            exit_code=exit_code,
            started_at=started_at,
            finished_at=finished_at,
            oom_killed=oom_killed,
        )

    async def cancel(self, execution_id: str) -> None:
        """Send SIGTERM to the container (graceful stop)."""
        container = self.client.containers.container(execution_id)
        try:
            await container.kill(signal="SIGTERM")
            log.info("sent SIGTERM to container %s", execution_id[:12])
        except aiodocker.DockerError as exc:
            if exc.status == 409:
                log.debug("container %s already stopped", execution_id[:12])
            else:
                raise

    async def force_kill(self, execution_id: str) -> None:
        """Force-kill the container (SIGKILL)."""
        container = self.client.containers.container(execution_id)
        try:
            await container.kill(signal="SIGKILL")
            log.info("force-killed container %s", execution_id[:12])
        except aiodocker.DockerError as exc:
            if exc.status == 409:
                log.debug("container %s already stopped", execution_id[:12])
            else:
                raise

    async def cleanup(self, execution_id: str) -> None:
        """Remove the container."""
        container = self.client.containers.container(execution_id)
        try:
            await container.delete(force=True)
            log.info("removed container %s", execution_id[:12])
        except aiodocker.DockerError as exc:
            if exc.status == 404:
                log.debug("container %s already removed", execution_id[:12])
            else:
                raise

    # --------------------------------------------------------------------- #
    # private helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _security_opt(security: SandboxSecurity) -> list[str]:
        opts = ["no-new-privileges"]
        if security.seccomp_profile:
            opts.append(f"seccomp={security.seccomp_profile}")
        return opts

    @staticmethod
    def _network_mode(policy: str) -> str:
        if policy == "deny":
            return "none"
        if policy == "allow":
            return "bridge"
        if policy == "restricted":
            return "qap-restricted"
        raise ValueError(f"Unknown network policy: {policy}")

    @staticmethod
    def _build_binds(mounts: list[Mount]) -> list[str]:
        binds: list[str] = []
        for m in mounts:
            mode = "ro" if m.read_only else "rw"
            binds.append(f"{m.source}:{m.target}:{mode}")
        return binds

    @staticmethod
    def _decode_log_frame(raw: bytes) -> tuple[str, str]:
        """Decode a Docker multiplexed log frame.

        Frame format: header(8 bytes) + payload
        byte 0: 1=stdout, 2=stderr
        bytes 1-3: unused
        bytes 4-7: big-endian payload size
        """
        if len(raw) >= 8 and raw[0] in (1, 2):
            stream = "stdout" if raw[0] == 1 else "stderr"
            return stream, raw[8:].decode(errors="replace").rstrip()

        # TTY mode or non-multiplexed output
        return "stdout", raw.decode(errors="replace").rstrip()
