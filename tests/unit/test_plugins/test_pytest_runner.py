from __future__ import annotations

import asyncio
import shlex
from unittest.mock import AsyncMock, patch

import pytest

from qaplatform.plugins.builtin.pytest_runner import PytestRunner
from qaplatform.plugins.protocols import RunnerProtocol, TestRunResult


class TestPytestRunnerProtocol:
    """Verify PytestRunner satisfies RunnerProtocol."""

    def test_implements_protocol(self):
        runner = PytestRunner()
        assert isinstance(runner, RunnerProtocol)

    def test_has_name(self):
        runner = PytestRunner()
        assert runner.name == "pytest"


class TestPytestBuildCommand:
    """Test build_command output (public string API)."""

    @staticmethod
    def _assert_command(command: str, expected_argv: list[str]) -> None:
        expected_command = "cd /workspace && " + " ".join(
            shlex.quote(part) for part in expected_argv
        )
        assert command == expected_command
        assert shlex.split(command.removeprefix("cd /workspace && ")) == expected_argv

    def test_default_command(self):
        runner = PytestRunner()
        cmd = runner.build_command({})
        self._assert_command(cmd, [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "tests",
        ])

    def test_with_extra_args(self):
        runner = PytestRunner()
        cmd = runner.build_command({"args": ["-v", "--tb=short"]})
        self._assert_command(cmd, [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "-v",
            "--tb=short",
            "tests",
        ])

    def test_with_custom_test_path(self):
        runner = PytestRunner()
        cmd = runner.build_command({"test_path": "tests/unit/"})
        self._assert_command(cmd, [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "tests/unit/",
        ])

    def test_with_markers(self):
        runner = PytestRunner()
        cmd = runner.build_command({"args": ["-m", "slow"]})
        self._assert_command(cmd, [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "-m",
            "slow",
            "tests",
        ])

    def test_with_k_expression(self):
        runner = PytestRunner()
        cmd = runner.build_command({"args": ["-k", "not slow"], "test_path": "tests/unit/"})
        self._assert_command(cmd, [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "-k",
            "not slow",
            "tests/unit/",
        ])

    def test_extra_args_as_string_is_split_before_shell_quoting(self):
        runner = PytestRunner()
        cmd = runner.build_command({"args": "-k 'not slow' --tb=short"})
        self._assert_command(cmd, [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "-k",
            "not slow",
            "--tb=short",
            "tests",
        ])


class TestPytestBuildCommandInternal:
    """Test _build_command (private list API used by run_tests)."""

    def test_default_command(self):
        runner = PytestRunner()
        cmd = runner._build_command({})
        assert cmd == [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "tests",
        ]

    def test_custom_executable(self):
        runner = PytestRunner()
        cmd = runner._build_command({"executable": "python3.11"})
        assert cmd == [
            "python3.11",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "tests",
        ]

    def test_custom_junit_xml(self):
        runner = PytestRunner()
        cmd = runner._build_command({"junit_xml": "output/report.xml"})
        assert cmd == [
            "python",
            "-m",
            "pytest",
            "--junitxml=output/report.xml",
            "tests",
        ]

    @pytest.mark.parametrize(
        "junit_xml",
        ["/tmp/report.xml", "../report.xml", "reports/../report.xml", r"C:\tmp\report.xml"],
    )
    def test_rejects_junit_xml_outside_workspace(self, junit_xml):
        runner = PytestRunner()
        with pytest.raises(ValueError) as exc_info:
            runner._build_command({"junit_xml": junit_xml})

        assert str(exc_info.value) == "junit_xml must be a relative path inside the workspace"
        assert junit_xml not in str(exc_info.value)

    @pytest.mark.parametrize(
        ("config", "field", "unsafe_path"),
        [
            ({"test_path": "/tmp/tests"}, "test_path", "/tmp/tests"),
            ({"test_path": ""}, "test_path", ""),
            ({"test_path": "   "}, "test_path", "   "),
            ({"test_paths": ["tests/unit", "../secret"]}, "test_paths", "../secret"),
            ({"test_paths": ["tests/../secret"]}, "test_paths", "tests/../secret"),
            ({"test_paths": [r"C:\tmp\tests"]}, "test_paths", r"C:\tmp\tests"),
            ({"test_paths": ["tests/unit", ""]}, "test_paths", ""),
            ({"test_paths": ["tests/unit", "   "]}, "test_paths", "   "),
        ],
    )
    def test_rejects_test_paths_outside_workspace(self, config, field, unsafe_path):
        runner = PytestRunner()
        with pytest.raises(ValueError) as exc_info:
            runner._build_command(config)

        assert str(exc_info.value) == f"{field} must be a relative path inside the workspace"
        if unsafe_path:
            assert unsafe_path not in str(exc_info.value)

    def test_extra_args_as_list(self):
        runner = PytestRunner()
        cmd = runner._build_command({"args": ["-x", "--strict-markers"]})
        assert cmd == [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "-x",
            "--strict-markers",
            "tests",
        ]

    def test_extra_args_as_string(self):
        runner = PytestRunner()
        cmd = runner._build_command({"args": "-x --strict-markers"})
        assert cmd == [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "-x",
            "--strict-markers",
            "tests",
        ]

    def test_custom_test_paths(self):
        runner = PytestRunner()
        cmd = runner._build_command({"test_paths": ["tests/unit", "tests/integration"]})
        assert cmd == [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "tests/unit",
            "tests/integration",
        ]

    def test_test_paths_as_string(self):
        runner = PytestRunner()
        cmd = runner._build_command({"test_paths": "tests/unit"})
        assert cmd == [
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "tests/unit",
        ]


class TestPytestParseSummary:
    """Test _parse_summary static method.

    These assertions intentionally cover the first summary token and single-result
    summaries because those shapes previously parsed as all zero counts.
    """

    def test_mixed_results(self):
        result = PytestRunner._parse_summary(
            "===== 3 passed, 2 failed, 1 skipped in 2.5s ====="
        )
        assert result == {"passed": 3, "failed": 2, "skipped": 1, "error": 0}

    def test_with_errors(self):
        result = PytestRunner._parse_summary(
            "===== 1 passed, 1 error in 0.5s ====="
        )
        assert result == {"passed": 1, "failed": 0, "skipped": 0, "error": 1}

    def test_passed_after_comma_is_parsed(self):
        """When 'passed' appears after a comma, it IS parsed."""
        result = PytestRunner._parse_summary(
            "===== 2 failed, 5 passed in 1.0s ====="
        )
        assert result["passed"] == 5
        assert result["failed"] == 2

    def test_no_summary_returns_zeros(self):
        result = PytestRunner._parse_summary("no summary here")
        assert result == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

    def test_empty_output(self):
        result = PytestRunner._parse_summary("")
        assert result == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

    def test_single_result_no_comma_is_parsed(self):
        """Single-result summaries must still count the terminal state."""
        result = PytestRunner._parse_summary(
            "===== 4 failed in 0.8s ====="
        )
        assert result == {"passed": 0, "failed": 4, "skipped": 0, "error": 0}

    def test_xfailed_counts_as_skipped(self):
        result = PytestRunner._parse_summary(
            "===== 1 passed, 1 skipped, 2 xfailed, 3 warnings in 0.8s ====="
        )
        assert result == {"passed": 1, "failed": 0, "skipped": 3, "error": 0}

    def test_xpassed_counts_as_failed(self):
        result = PytestRunner._parse_summary(
            "===== 1 passed, 2 xpassed in 0.8s ====="
        )
        assert result == {"passed": 1, "failed": 2, "skipped": 0, "error": 0}

    def test_uses_last_summary_line(self):
        stdout = (
            "collected 10 items\n"
            "===== 10 passed in 1.0s =====\n"
            "===== 3 failed, 7 passed in 2.0s =====\n"
        )
        result = PytestRunner._parse_summary(stdout)
        assert result == {"passed": 7, "failed": 3, "skipped": 0, "error": 0}


class TestPytestRunTests:
    """Test run_tests behavior with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return PytestRunner()

    def _assert_spawn_call(self, call_args, tmp_path):
        assert call_args.args == (
            "python",
            "-m",
            "pytest",
            "--junitxml=results/junit.xml",
            "tests",
        )
        env = call_args.kwargs["env"]
        assert call_args.kwargs == {
            "cwd": str(tmp_path),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": env,
        }
        return env

    @pytest.mark.asyncio
    async def test_run_all_passed(self, runner, tmp_path):
        stdout = "===== 5 passed, 0 failed in 1.23s ====="
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert isinstance(result, TestRunResult)
        assert result.exit_code == 0
        assert result.passed == 5
        assert result.failed == 0
        assert result.skipped == 0
        assert result.error == 0

    @pytest.mark.asyncio
    async def test_run_partial_failures(self, runner, tmp_path):
        stdout = "===== 3 passed, 2 failed, 1 skipped in 2.5s ====="
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.exit_code == 1
        assert result.passed == 3
        assert result.failed == 2
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_run_all_failed(self, runner, tmp_path):
        stdout = "===== 4 failed in 0.8s ====="
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.exit_code == 1
        assert result.passed == 0
        assert result.failed == 4

    @pytest.mark.asyncio
    async def test_empty_output_returns_zeros(self, runner, tmp_path):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 0
        assert result.failed == 0
        assert result.skipped == 0
        assert result.error == 0
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_subprocess_returns_stderr(self, runner, tmp_path):
        stdout = "===== 1 passed, 0 failed in 0.1s ====="
        stderr = "WARNING: some warning"
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), stderr.encode())
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 1
        assert "WARNING" in result.stderr

    @pytest.mark.asyncio
    async def test_exit_code_none_normalized_to_zero(self, runner, tmp_path):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = None
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_env_vars_passed_through(self, runner, tmp_path):
        with patch.dict("os.environ", {"QAP_EXISTING_ENV": "kept"}, clear=False), \
             patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(tmp_path, {}, env_vars={"PYTHONDONTWRITEBYTECODE": "1"})

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        env = self._assert_spawn_call(call_args, tmp_path)
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        assert env["QAP_EXISTING_ENV"] == "kept"
        process.communicate.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_working_dir_passed_through(self, runner, tmp_path):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(tmp_path, {})

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        env = self._assert_spawn_call(call_args, tmp_path)
        assert env is None
        process.communicate.assert_awaited_once_with()


class TestPytestRegistration:
    """Test that PytestRunner is registered in builtins."""

    def test_register_builtins_includes_pytest(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "pytest" in registry.runner_names
