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


class PlaywrightRunner:
    """Built-in Playwright runner plugin implementing RunnerProtocol.

    Generates a ``npx playwright test`` command with JUnit reporter,
    runs it as a subprocess, parses the JUnit XML output, and returns
    a structured TestRunResult.
    """

    name = "playwright"

    def build_command(self, config: dict[str, Any]) -> str:
        """Return the shell command to execute this runner inside a container."""
        cmd = self._build_command(config)
        return " ".join(shlex.quote(c) for c in cmd)

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        cmd = self._build_command(config)
        log.info("running playwright: %s (cwd=%s)", " ".join(cmd), working_dir)

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

        # Parse JUnit XML output for test counts
        junit_path = working_dir / config.get("junit_xml", "results/junit.xml")
        counts = self._parse_junit_counts(junit_path)

        return TestRunResult(
            **counts,
            duration_ms=elapsed_ms,
            exit_code=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
        )

    # --------------------------------------------------------------------- #
    # private helpers
    # --------------------------------------------------------------------- #

    def _build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the ``npx playwright test`` CLI command from plugin config."""
        cmd = ["npx", "playwright", "test"]

        # JUnit XML output for collector
        report_path = config.get("junit_xml", "results/junit.xml")
        cmd += [f"--reporter=junit,{report_path}"]

        # Extra arguments (e.g. --grep, --project, --workers)
        extra_args = config.get("args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        cmd.extend(extra_args)

        # Test paths
        test_paths = config.get("test_paths", [])
        if isinstance(test_paths, str):
            test_paths = [test_paths]
        cmd.extend(test_paths)

        return cmd

    @staticmethod
    def _parse_junit_counts(xml_path: Path) -> dict[str, int]:
        """Parse a JUnit XML file to extract aggregated test counts."""
        passed = failed = skipped = error = 0

        if not xml_path.exists():
            return {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

        try:
            tree = ET.parse(xml_path)  # noqa: S314
        except ET.ParseError:
            log.warning("failed to parse JUnit XML: %s", xml_path)
            return {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

        root = tree.getroot()
        # Handle both <testsuites><testsuite>... and <testsuite>...
        test_suites = root.findall("testsuite")
        if not test_suites and root.tag == "testsuite":
            test_suites = [root]

        for suite_elem in test_suites:
            for tc_elem in suite_elem.findall("testcase"):
                if tc_elem.find("failure") is not None:
                    failed += 1
                elif tc_elem.find("error") is not None:
                    error += 1
                elif tc_elem.find("skipped") is not None:
                    skipped += 1
                else:
                    passed += 1

        return {"passed": passed, "failed": failed, "skipped": skipped, "error": error}
