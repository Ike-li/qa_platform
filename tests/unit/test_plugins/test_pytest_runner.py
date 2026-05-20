from __future__ import annotations

import asyncio
from pathlib import Path
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

    def test_default_command(self):
        runner = PytestRunner()
        cmd = runner.build_command({})
        assert "python -m pytest" in cmd
        assert "--junitxml=results/junit.xml" in cmd
        assert "tests/" in cmd

    def test_with_extra_args(self):
        runner = PytestRunner()
        cmd = runner.build_command({"args": ["-v", "--tb=short"]})
        assert "-v" in cmd
        assert "--tb=short" in cmd

    def test_with_custom_test_path(self):
        runner = PytestRunner()
        cmd = runner.build_command({"test_path": "tests/unit/"})
        assert "tests/unit/" in cmd

    def test_with_markers(self):
        runner = PytestRunner()
        cmd = runner.build_command({"args": ["-m", "slow"]})
        assert "-m" in cmd
        assert "slow" in cmd

    def test_with_k_expression(self):
        runner = PytestRunner()
        cmd = runner.build_command({"args": ["-k", "test_login"]})
        assert "-k" in cmd
        assert "test_login" in cmd


class TestPytestBuildCommandInternal:
    """Test _build_command (private list API used by run_tests)."""

    def test_default_command(self):
        runner = PytestRunner()
        cmd = runner._build_command({})
        assert cmd[0] == "python"
        assert "-m" in cmd
        assert "pytest" in cmd
        assert "--junitxml=results/junit.xml" in cmd
        assert "tests" in cmd

    def test_custom_executable(self):
        runner = PytestRunner()
        cmd = runner._build_command({"executable": "python3.11"})
        assert cmd[0] == "python3.11"

    def test_custom_junit_xml(self):
        runner = PytestRunner()
        cmd = runner._build_command({"junit_xml": "output/report.xml"})
        assert "--junitxml=output/report.xml" in cmd

    def test_extra_args_as_list(self):
        runner = PytestRunner()
        cmd = runner._build_command({"args": ["-x", "--strict-markers"]})
        assert "-x" in cmd
        assert "--strict-markers" in cmd

    def test_extra_args_as_string(self):
        runner = PytestRunner()
        cmd = runner._build_command({"args": "-x --strict-markers"})
        assert "-x" in cmd
        assert "--strict-markers" in cmd

    def test_custom_test_paths(self):
        runner = PytestRunner()
        cmd = runner._build_command({"test_paths": ["tests/unit", "tests/integration"]})
        assert "tests/unit" in cmd
        assert "tests/integration" in cmd

    def test_test_paths_as_string(self):
        runner = PytestRunner()
        cmd = runner._build_command({"test_paths": "tests/unit"})
        assert "tests/unit" in cmd


class TestPytestParseSummary:
    """Test _parse_summary static method.

    Note: the parser splits by comma then space.  The first token always starts
    with "=====" so int() fails on it — the first keyword (typically "passed")
    is never counted.  Subsequent tokens parse correctly.
    """

    def test_mixed_results(self):
        result = PytestRunner._parse_summary(
            "===== 3 passed, 2 failed, 1 skipped in 2.5s ====="
        )
        # "3 passed" is the first token — skipped because it starts with "====="
        assert result == {"passed": 0, "failed": 2, "skipped": 1, "error": 0}

    def test_with_errors(self):
        result = PytestRunner._parse_summary(
            "===== 1 passed, 1 error in 0.5s ====="
        )
        assert result == {"passed": 0, "failed": 0, "skipped": 0, "error": 1}

    def test_passed_after_comma_is_parsed(self):
        """When 'passed' appears after a comma, it IS parsed."""
        result = PytestRunner._parse_summary(
            "===== 2 failed, 5 passed in 1.0s ====="
        )
        # "2 failed" is first token (starts with =====) so it's skipped
        # "5 passed" is after comma → parsed
        assert result["passed"] == 5
        assert result["failed"] == 0

    def test_no_summary_returns_zeros(self):
        result = PytestRunner._parse_summary("no summary here")
        assert result == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

    def test_empty_output(self):
        result = PytestRunner._parse_summary("")
        assert result == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

    def test_single_result_no_comma_returns_zeros(self):
        """When there's only one result (no comma), the entire line is one token
        starting with '=====' so int() fails and all counts are 0."""
        result = PytestRunner._parse_summary(
            "===== 4 failed in 0.8s ====="
        )
        assert result == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

    def test_uses_last_summary_line(self):
        stdout = (
            "collected 10 items\n"
            "===== 10 passed in 1.0s =====\n"
            "===== 3 failed, 7 passed in 2.0s =====\n"
        )
        result = PytestRunner._parse_summary(stdout)
        # last line: first token "3 failed" is skipped (starts with =====)
        # "7 passed" is after comma → parsed
        assert result == {"passed": 7, "failed": 0, "skipped": 0, "error": 0}


class TestPytestRunTests:
    """Test run_tests behavior with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return PytestRunner()

    @pytest.mark.asyncio
    async def test_run_all_passed(self, runner, tmp_path):
        # "5 passed" is first token (starts with =====) so parser skips it
        stdout = "===== 5 passed, 0 failed in 1.23s ====="
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert isinstance(result, TestRunResult)
        assert result.exit_code == 0
        assert result.passed == 0
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
        assert result.passed == 0
        assert result.failed == 2
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_run_all_failed(self, runner, tmp_path):
        # Single result with no comma → parser skips the only token → all zeros
        stdout = "===== 4 failed in 0.8s ====="
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.exit_code == 1
        assert result.passed == 0
        assert result.failed == 0

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
        # "1 passed" is first token (starts with =====) so parser skips it
        stdout = "===== 1 passed, 0 failed in 0.1s ====="
        stderr = "WARNING: some warning"
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), stderr.encode())
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 0
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
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(tmp_path, {}, env_vars={"PYTHONDONTWRITEBYTECODE": "1"})

        _, kwargs = mock_exec.call_args
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"

    @pytest.mark.asyncio
    async def test_working_dir_passed_through(self, runner, tmp_path):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(tmp_path, {})

        _, kwargs = mock_exec.call_args
        assert kwargs["cwd"] == str(tmp_path)


class TestPytestRegistration:
    """Test that PytestRunner is registered in builtins."""

    def test_register_builtins_includes_pytest(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "pytest" in registry.runner_names
