from __future__ import annotations

import asyncio
import logging
import os
from pathlib import PurePosixPath
import shlex
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from qaplatform.plugins.builtin._paths import safe_workspace_output_path, safe_workspace_paths
from qaplatform.plugins.protocols import TestRunResult

log = logging.getLogger(__name__)
_DEFAULT_JUNIT_XML = "results/junit.xml"


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
        junit_xml = self._junit_xml_path(config)
        parent = PurePosixPath(junit_xml).parent.as_posix()
        mkdir = ""
        if parent not in {"", "."}:
            mkdir = f"mkdir -p {shlex.quote(parent)} && "
        env = f"PLAYWRIGHT_JUNIT_OUTPUT_FILE={shlex.quote(junit_xml)} "
        return "cd /workspace && " + mkdir + env + " ".join(shlex.quote(c) for c in cmd)

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        cmd = self._build_command(config)
        log.info("running playwright: %s (cwd=%s)", " ".join(cmd), working_dir)

        junit_xml = self._junit_xml_path(config)
        junit_path = working_dir / junit_xml
        junit_path.parent.mkdir(parents=True, exist_ok=True)

        env_override = os.environ.copy()
        if env_vars:
            env_override.update(env_vars)
        env_override["PLAYWRIGHT_JUNIT_OUTPUT_FILE"] = junit_xml

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
        cmd += ["--reporter=junit"]

        # Extra arguments (e.g. --grep, --project, --workers)
        extra_args = config.get("args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        cmd.extend(extra_args)

        # Test paths
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
