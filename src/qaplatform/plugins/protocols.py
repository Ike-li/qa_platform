from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True)
class TestRunResult:
    """Result returned by a Runner plugin after executing tests."""

    __test__ = False

    passed: int
    failed: int
    skipped: int
    error: int
    duration_ms: int
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class TestResultData:
    """A single parsed test case result from a Collector."""

    __test__ = False

    suite: str
    name: str
    status: str  # passed / failed / error / skipped / xfail
    duration_ms: int = 0
    error_message: str | None = None
    stack_trace: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactData:
    """An artifact produced during execution."""

    name: str
    type: str  # report / log / screenshot / video / coverage / custom
    local_path: Path
    mime_type: str = "application/octet-stream"


@dataclass(frozen=True)
class SourceRevision:
    """Result of fetching source code."""

    path: Path
    sha: str | None = None
    ref: str = ""


@runtime_checkable
class RunnerProtocol(Protocol):
    """Protocol for test runner plugins (e.g. pytest)."""

    name: str

    def build_command(self, config: dict[str, Any]) -> str:
        """Return the shell command to execute this runner inside a container."""
        raise NotImplementedError

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        """Execute tests in working_dir with the given config."""
        ...


@runtime_checkable
class CollectorProtocol(Protocol):
    """Protocol for result collector plugins (e.g. JUnit XML parser)."""

    name: str

    async def collect(
        self,
        run_id: UUID,
        working_dir: Path,
        config: dict[str, Any] | None = None,
    ) -> list[TestResultData]:
        """Parse test results from working_dir."""
        ...


@runtime_checkable
class SourceProtocol(Protocol):
    """Protocol for source code fetching plugins (e.g. git clone)."""

    name: str

    async def clone(
        self,
        url: str,
        ref: str,
        dest: Path,
        auth: dict[str, Any] | None = None,
    ) -> SourceRevision:
        """Clone/fetch source code into dest. Returns SourceRevision with path, sha, ref."""
        ...
