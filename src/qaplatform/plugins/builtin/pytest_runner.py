from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import Any

from qaplatform.plugins.protocols import TestRunResult

log = logging.getLogger(__name__)


class PytestRunner:
    """Built-in pytest runner plugin implementing RunnerProtocol.

    Generates a pytest command, runs it as a subprocess, captures stdout/stderr,
    and returns a structured TestRunResult.
    """

    name = "pytest"

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        cmd = self._build_command(config)
        log.info("running pytest: %s (cwd=%s)", " ".join(cmd), working_dir)

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

        return TestRunResult(
            **self._parse_summary(stdout),
            duration_ms=elapsed_ms,
            exit_code=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
        )

    # --------------------------------------------------------------------- #
    # private helpers
    # --------------------------------------------------------------------- #

    def _build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the pytest CLI command from plugin config."""
        cmd = [config.get("executable", "python"), "-m", "pytest"]

        # JUnit XML output for collector
        report_path = config.get("junit_xml", "results/junit.xml")
        cmd += [f"--junitxml={report_path}"]

        # Extra arguments (e.g. -k, --markers, -x)
        extra_args = config.get("args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        cmd.extend(extra_args)

        # Test paths
        test_paths = config.get("test_paths", ["tests"])
        if isinstance(test_paths, str):
            test_paths = [test_paths]
        cmd.extend(test_paths)

        return cmd

    @staticmethod
    def _parse_summary(stdout: str) -> dict[str, int]:
        """Parse pytest summary line to extract counts.

        Looks for lines like:
            ===== 5 passed, 2 failed, 1 skipped in 3.45s =====
        """
        passed = failed = skipped = error = 0

        for line in reversed(stdout.splitlines()):
            if "====" not in line:
                continue
            lower = line.lower()
            for token in lower.split(","):
                token = token.strip()
                parts = token.split()
                if len(parts) < 2:
                    continue
                try:
                    count = int(parts[0])
                except ValueError:
                    continue
                keyword = parts[1]
                if "passed" in keyword:
                    passed = count
                elif "failed" in keyword:
                    failed = count
                elif "skipped" in keyword:
                    skipped = count
                elif "error" in keyword:
                    error = count
            break

        return {"passed": passed, "failed": failed, "skipped": skipped, "error": error}
