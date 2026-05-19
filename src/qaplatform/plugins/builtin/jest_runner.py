from __future__ import annotations

import asyncio
import logging
import shlex
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from qaplatform.plugins.protocols import TestRunResult

log = logging.getLogger(__name__)


class JestRunner:
    """Built-in Jest runner plugin implementing RunnerProtocol.

    Runs Jest with jest-junit reporter, parses the XML output for test counts,
    and returns a structured TestRunResult.
    """

    name = "jest"

    def build_command(self, config: dict[str, Any]) -> str:
        """Return the shell command to execute this runner inside a container."""
        args = config.get("args", [])
        test_paths = config.get("test_paths", [])
        extras = " ".join(args) if args else ""
        paths = " ".join(test_paths) if test_paths else ""
        parts = ["npx jest --ci --reporters=default --reporters=jest-junit"]
        if extras:
            parts.append(extras)
        if paths:
            parts.append(paths)
        return " ".join(parts)

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        cmd = self._build_command(config)
        log.info("running jest: %s (cwd=%s)", " ".join(cmd), working_dir)

        env_override = dict(env_vars) if env_vars else None

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

        junit_path = config.get("junit_xml", "junit.xml")
        counts = self._parse_junit_xml(working_dir / junit_path)

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

        test_paths = config.get("test_paths", [])
        if isinstance(test_paths, str):
            test_paths = [test_paths]
        cmd.extend(test_paths)

        return cmd

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
            passed += int(testsuite.get("tests", 0)) - int(
                testsuite.get("failures", 0)
            ) - int(testsuite.get("errors", 0)) - int(testsuite.get("skipped", 0))
            failed += int(testsuite.get("failures", 0))
            error += int(testsuite.get("errors", 0))
            skipped += int(testsuite.get("skipped", 0))

        return {"passed": passed, "failed": failed, "skipped": skipped, "error": error}
