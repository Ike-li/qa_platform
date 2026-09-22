from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

from qaplatform.plugins.builtin._paths import (
    safe_workspace_output_path,
    safe_workspace_paths,
)
from qaplatform.plugins.protocols import TestRunResult

log = logging.getLogger(__name__)


class PytestRunner:
    """Built-in pytest runner plugin implementing RunnerProtocol.

    Generates a pytest command, runs it as a subprocess, captures stdout/stderr,
    and returns a structured TestRunResult.
    """

    name = "pytest"

    def build_command(self, config: dict[str, Any]) -> str:
        """Return the shell command to execute this runner inside a container."""
        cmd = self._build_command(config)
        return "cd /workspace && " + " ".join(shlex.quote(part) for part in cmd)

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        cmd = self._build_command(config)
        log.info("running pytest: %s (cwd=%s)", " ".join(cmd), working_dir)

        env_override = None
        if env_vars:
            env_override = os.environ.copy()
            env_override.update(env_vars)

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
        report_path = safe_workspace_output_path(
            config.get("junit_xml"),
            "results/junit.xml",
            field="junit_xml",
        )
        cmd += [f"--junitxml={report_path}"]

        if config.get("allure_enabled") is True:
            allure_results_path = safe_workspace_output_path(
                config.get("allure_results"),
                "results/allure-results",
                field="allure_results",
            )
            cmd += [f"--alluredir={allure_results_path}"]

        # Extra arguments (e.g. -k, --markers, -x)
        extra_args = config.get("args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        cmd.extend(extra_args)

        # Test paths
        if "test_paths" in config:
            test_paths = safe_workspace_paths(config.get("test_paths"), field="test_paths")
        elif "test_path" in config:
            test_paths = safe_workspace_paths(config.get("test_path"), field="test_path")
        else:
            test_paths = ["tests"]
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
            for match in re.finditer(r"(\d+)\s+([a-z]+)", lower):
                count = int(match.group(1))
                keyword = match.group(2)
                if keyword == "passed":
                    passed += count
                elif keyword in {"failed", "xpassed"}:
                    failed += count
                elif keyword in {"skipped", "xfailed"}:
                    skipped += count
                elif keyword in {"error", "errors"}:
                    error += count
            break

        return {"passed": passed, "failed": failed, "skipped": skipped, "error": error}
