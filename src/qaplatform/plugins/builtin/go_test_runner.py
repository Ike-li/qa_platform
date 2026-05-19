from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from pathlib import Path
from typing import Any

from qaplatform.plugins.protocols import TestRunResult

log = logging.getLogger(__name__)


class GoTestRunner:
    """Built-in Go test runner plugin implementing RunnerProtocol.

    Runs ``go test -v -json``, parses the NDJSON output for per-test results,
    and returns a structured TestRunResult.
    """

    name = "go_test"

    def build_command(self, config: dict[str, Any]) -> str:
        """Return the shell command to execute this runner inside a container."""
        args = config.get("args", [])
        test_paths = config.get("test_paths", ["./..."])
        extras = " ".join(args) if args else ""
        paths = " ".join(test_paths) if test_paths else ""
        parts = ["go test -v -json"]
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
        log.info("running go test: %s (cwd=%s)", " ".join(cmd), working_dir)

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

        counts = self._parse_ndjson(stdout)

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
        """Build the go test CLI command from plugin config."""
        cmd = ["go", "test", "-v", "-json"]

        extra_args = config.get("args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        cmd.extend(extra_args)

        test_paths = config.get("test_paths", ["./..."])
        if isinstance(test_paths, str):
            test_paths = [test_paths]
        cmd.extend(test_paths)

        return cmd

    @staticmethod
    def _parse_ndjson(stdout: str) -> dict[str, int]:
        """Parse ``go test -json`` NDJSON output to extract per-test counts.

        Each line is a JSON object with ``Action`` and ``Test`` fields.
        We track final results (pass/fail/skip) per unique ``(Package, Test)``
        pair so that sub-test duplicates do not inflate counts.
        """
        passed = failed = skipped = error = 0

        # Track the final action for each (Package, Test) pair
        results: dict[tuple[str, str], str] = {}

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            action = event.get("Action", "")
            package = event.get("Package", "")
            test = event.get("Test", "")

            # Only count per-test events (skip package-level output/fail)
            if not test:
                if action == "fail":
                    error += 1
                continue

            key = (package, test)
            if action in ("pass", "fail", "skip"):
                results[key] = action

        for action in results.values():
            if action == "pass":
                passed += 1
            elif action == "fail":
                failed += 1
            elif action == "skip":
                skipped += 1

        return {"passed": passed, "failed": failed, "skipped": skipped, "error": error}
