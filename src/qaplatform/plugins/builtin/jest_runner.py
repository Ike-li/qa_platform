from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

from qaplatform.plugins.builtin._paths import (
    safe_workspace_output_path,
    safe_workspace_paths,
)
from qaplatform.plugins.protocols import TestRunResult

log = logging.getLogger(__name__)
_DEFAULT_JUNIT_XML = "results/junit.xml"


class JestRunner:
    """Built-in Jest runner plugin implementing RunnerProtocol.

    Runs Jest with jest-junit reporter, parses the XML output for test counts,
    and returns a structured TestRunResult.
    """

    name = "jest"

    def build_command(self, config: dict[str, Any]) -> str:
        """Return the shell command to execute this runner inside a container."""
        cmd = self._build_command(config)
        junit_xml = self._junit_xml_path(config)
        parent = PurePosixPath(junit_xml).parent.as_posix()
        mkdir = ""
        if parent not in {"", "."}:
            mkdir = f"mkdir -p {shlex.quote(parent)} && "
        env = f"JEST_JUNIT_OUTPUT_FILE={shlex.quote(junit_xml)} "
        return "cd /workspace && " + mkdir + env + " ".join(shlex.quote(part) for part in cmd)

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        cmd = self._build_command(config)
        log.info("running jest: %s (cwd=%s)", " ".join(cmd), working_dir)

        junit_xml = self._junit_xml_path(config)
        junit_path = working_dir / junit_xml
        junit_path.parent.mkdir(parents=True, exist_ok=True)

        env_override = os.environ.copy()
        if env_vars:
            env_override.update(env_vars)
        env_override["JEST_JUNIT_OUTPUT_FILE"] = junit_xml

        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_override,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        elapsed_ms = int((time.monotonic() - started) * 1000)

        stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""

        counts = self._parse_junit_xml(junit_path)

        return TestRunResult(
            passed=counts["passed"],
            failed=counts["failed"],
            skipped=counts["skipped"],
            error=counts["error"],
            duration_ms=elapsed_ms,
            exit_code=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
        )

    # --------------------------------------------------------------------- #
    # private helpers
    # --------------------------------------------------------------------- #

    def _build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the jest CLI command from plugin config."""
        cmd = ["npx", "jest", "--ci", "--reporters=default", "--reporters=jest-junit"]

        extra_args = config.get("args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        cmd.extend(extra_args)

        test_paths = safe_workspace_paths(config.get("test_paths"), field="test_paths")
        cmd.extend(test_paths)

        return cmd

    @staticmethod
    def _junit_xml_path(config: dict[str, Any]) -> str:
        return safe_workspace_output_path(
            config.get("junit_xml"),
            _DEFAULT_JUNIT_XML,
            field="junit_xml",
        )

    @staticmethod
    def _parse_junit_xml(junit_path: Path) -> dict[str, int]:
        """Parse jest-junit XML output to extract test counts."""
        passed = failed = skipped = error = 0

        try:
            tree = ET.parse(junit_path)
            root = tree.getroot()
        except (ET.ParseError, FileNotFoundError):
            return {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

        for testsuite in root.iter("testsuite"):
            try:
                tests = int(testsuite.get("tests", 0))
                failures = int(testsuite.get("failures", 0))
                errors = int(testsuite.get("errors", 0))
                skips = int(testsuite.get("skipped", 0))
            except ValueError:
                log.warning("failed to parse JUnit XML counts: %s", junit_path)
                return {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

            passed += max(tests - failures - errors - skips, 0)
            failed += failures
            error += errors
            skipped += skips

        return {"passed": passed, "failed": failed, "skipped": skipped, "error": error}
