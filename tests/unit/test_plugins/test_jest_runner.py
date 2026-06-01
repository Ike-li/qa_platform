from __future__ import annotations

import asyncio
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from qaplatform.plugins.builtin.jest_runner import JestRunner
from qaplatform.plugins.protocols import RunnerProtocol, TestRunResult


class TestJestRunnerProtocol:
    """Verify JestRunner satisfies RunnerProtocol."""

    def test_implements_protocol(self):
        runner = JestRunner()
        assert isinstance(runner, RunnerProtocol)

    def test_has_name(self):
        runner = JestRunner()
        assert runner.name == "jest"


class TestJestBuildCommand:
    """Test build_command output."""

    @staticmethod
    def _jest_argv(
        command: str,
        expected_prefix: str = (
            "cd /workspace && mkdir -p results && "
            "JEST_JUNIT_OUTPUT_FILE=results/junit.xml"
        ),
    ) -> list[str]:
        prefix, tail = command.split(" npx ", 1)
        assert prefix == expected_prefix
        return ["npx", *shlex.split(tail)]

    def test_default_command(self):
        runner = JestRunner()
        cmd = runner.build_command({})
        assert cmd == (
            "cd /workspace && mkdir -p results && "
            "JEST_JUNIT_OUTPUT_FILE=results/junit.xml "
            "npx jest --ci --reporters=default --reporters=jest-junit"
        )
        assert self._jest_argv(cmd) == [
            "npx",
            "jest",
            "--ci",
            "--reporters=default",
            "--reporters=jest-junit",
        ]

    def test_custom_junit_xml_configures_jest_junit_output_file(self):
        runner = JestRunner()
        cmd = runner.build_command({"junit_xml": "reports/unit results.xml"})
        assert cmd == (
            "cd /workspace && mkdir -p reports && "
            "JEST_JUNIT_OUTPUT_FILE='reports/unit results.xml' "
            "npx jest --ci --reporters=default --reporters=jest-junit"
        )
        assert self._jest_argv(
            cmd,
            "cd /workspace && mkdir -p reports && "
            "JEST_JUNIT_OUTPUT_FILE='reports/unit results.xml'",
        ) == [
            "npx",
            "jest",
            "--ci",
            "--reporters=default",
            "--reporters=jest-junit",
        ]

    @pytest.mark.parametrize(
        "junit_xml",
        ["/tmp/report.xml", "../report.xml", "reports/../report.xml", r"C:\tmp\report.xml"],
    )
    def test_rejects_junit_xml_outside_workspace(self, junit_xml):
        runner = JestRunner()
        with pytest.raises(ValueError) as exc_info:
            runner.build_command({"junit_xml": junit_xml})

        assert str(exc_info.value) == "junit_xml must be a relative path inside the workspace"
        assert junit_xml not in str(exc_info.value)

    @pytest.mark.parametrize(
        "test_path",
        ["/tmp/tests", "../secret", "tests/../secret", r"C:\tmp\tests", "", "   "],
    )
    def test_rejects_test_paths_outside_workspace(self, test_path):
        runner = JestRunner()
        with pytest.raises(ValueError) as exc_info:
            runner.build_command({"test_paths": ["src/__tests__", test_path]})

        assert str(exc_info.value) == "test_paths must be a relative path inside the workspace"
        if test_path:
            assert test_path not in str(exc_info.value)

    def test_with_args(self):
        runner = JestRunner()
        cmd = runner.build_command({"args": ["--maxWorkers=2"]})
        assert self._jest_argv(cmd) == [
            "npx",
            "jest",
            "--ci",
            "--reporters=default",
            "--reporters=jest-junit",
            "--maxWorkers=2",
        ]

    def test_with_test_paths(self):
        runner = JestRunner()
        cmd = runner.build_command({"test_paths": ["src/__tests__"]})
        assert self._jest_argv(cmd) == [
            "npx",
            "jest",
            "--ci",
            "--reporters=default",
            "--reporters=jest-junit",
            "src/__tests__",
        ]

    def test_with_args_and_paths(self):
        runner = JestRunner()
        cmd = runner.build_command({
            "args": ["--testNamePattern", "login flow"],
            "test_paths": ["tests/unit/auth flow.test.ts"],
        })
        argv = self._jest_argv(cmd)
        assert argv == [
            "npx",
            "jest",
            "--ci",
            "--reporters=default",
            "--reporters=jest-junit",
            "--testNamePattern",
            "login flow",
            "tests/unit/auth flow.test.ts",
        ]


class TestJestRunTests:
    """Test run_tests behavior with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return JestRunner()

    def _assert_spawn_call(self, call_args, tmp_path: Path, junit_xml: str) -> dict[str, str]:
        assert call_args.args == (
            "npx",
            "jest",
            "--ci",
            "--reporters=default",
            "--reporters=jest-junit",
        )
        env = call_args.kwargs["env"]
        assert call_args.kwargs == {
            "cwd": str(tmp_path),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": env,
        }
        assert env["JEST_JUNIT_OUTPUT_FILE"] == junit_xml
        return env

    def _write_junit_xml(self, path: Path, tests=5, failures=1, errors=0, skipped=0):
        """Write a semantically consistent jest-junit XML file."""
        root = ET.Element("testsuites")
        suite = ET.SubElement(
            root,
            "testsuite",
            name="suite",
            tests=str(tests),
            failures=str(failures),
            errors=str(errors),
            skipped=str(skipped),
        )
        passed = tests - failures - errors - skipped
        for index in range(passed):
            ET.SubElement(suite, "testcase", name=f"pass{index + 1}")
        for index in range(failures):
            testcase = ET.SubElement(suite, "testcase", name=f"fail{index + 1}")
            ET.SubElement(testcase, "failure", message="assertion failed")
        for index in range(errors):
            testcase = ET.SubElement(suite, "testcase", name=f"error{index + 1}")
            ET.SubElement(testcase, "error", message="runtime error")
        for index in range(skipped):
            testcase = ET.SubElement(suite, "testcase", name=f"skip{index + 1}")
            ET.SubElement(testcase, "skipped", message="not applicable")
        tree = ET.ElementTree(root)
        tree.write(path, xml_declaration=True)

    def test_parse_junit_xml_counts_all_result_types(self, runner, tmp_path):
        self._write_junit_xml(
            tmp_path / "junit.xml",
            tests=6,
            failures=2,
            errors=1,
            skipped=1,
        )

        counts = runner._parse_junit_xml(tmp_path / "junit.xml")

        assert counts == {"passed": 2, "failed": 2, "skipped": 1, "error": 1}

    def test_parse_malformed_junit_count_returns_zeros(self, runner, tmp_path):
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(
            '<testsuites><testsuite name="suite" tests="not-a-number" '
            'failures="0" errors="0" skipped="0"/></testsuites>'
        )

        counts = runner._parse_junit_xml(xml_path)

        assert counts == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

    @pytest.mark.asyncio
    async def test_run_success(self, runner, tmp_path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        self._write_junit_xml(results_dir / "junit.xml", tests=3, failures=0)
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"PASS", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert isinstance(result, TestRunResult)
        assert result.exit_code == 0
        assert result.passed == 3
        assert result.failed == 0
        assert result.skipped == 0
        assert result.error == 0
        assert result.stdout == "PASS"
        assert result.stderr == ""
        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")
        process.communicate.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_run_with_failures(self, runner, tmp_path):
        self._write_junit_xml(
            tmp_path / "junit.xml",
            tests=6,
            failures=2,
            errors=1,
            skipped=1,
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (b"FAIL", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {"junit_xml": "junit.xml"})

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "junit.xml")
        process.communicate.assert_awaited_once_with()
        assert result.exit_code == 1
        assert result.passed == 2
        assert result.failed == 2
        assert result.skipped == 1
        assert result.error == 1
        assert result.stdout == "FAIL"

    @pytest.mark.asyncio
    async def test_missing_junit_xml_returns_zeros(self, runner, tmp_path):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {"junit_xml": "nonexistent.xml"})

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "nonexistent.xml")
        process.communicate.assert_awaited_once_with()
        assert result.passed == 0
        assert result.failed == 0
        assert result.skipped == 0
        assert result.error == 0
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_tests_creates_custom_junit_parent_directory(
        self,
        runner,
        tmp_path,
    ):
        report_path = tmp_path / "nested" / "reports" / "junit.xml"

        async def _spawn(*_args, **_kwargs):
            assert report_path.parent.is_dir()
            self._write_junit_xml(report_path, tests=1, failures=0)
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"PASS", b"")
            return process

        with patch("asyncio.create_subprocess_exec", side_effect=_spawn) as mock_exec:
            result = await runner.run_tests(
                tmp_path,
                {"junit_xml": "nested/reports/junit.xml"},
            )

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "nested/reports/junit.xml")
        assert result.passed == 1
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_env_vars_passed_through(self, runner, tmp_path):
        self._write_junit_xml(tmp_path / "junit.xml")
        with patch.dict("os.environ", {"QAP_EXISTING_ENV": "kept"}, clear=False), \
             patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(
                tmp_path, {"junit_xml": "junit.xml"}, env_vars={"NODE_ENV": "test"}
            )

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        env = self._assert_spawn_call(call_args, tmp_path, "junit.xml")
        assert env["NODE_ENV"] == "test"
        assert env["QAP_EXISTING_ENV"] == "kept"
        process.communicate.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_junit_xml_config_wins_over_env_var(self, runner, tmp_path):
        self._write_junit_xml(tmp_path / "configured.xml", tests=2, failures=0)
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(
                tmp_path,
                {"junit_xml": "configured.xml"},
                env_vars={"JEST_JUNIT_OUTPUT_FILE": "wrong.xml"},
            )

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "configured.xml")
        process.communicate.assert_awaited_once_with()
        assert result.passed == 2


class TestJestRegistration:
    """Test that JestRunner is registered in builtins."""

    def test_register_builtins_includes_jest(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "jest" in registry.runner_names
