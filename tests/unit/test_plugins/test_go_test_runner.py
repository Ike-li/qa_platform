from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from qaplatform.plugins.builtin.go_test_runner import GoTestRunner
from qaplatform.plugins.protocols import RunnerProtocol, TestRunResult


class TestGoTestRunnerProtocol:
    """Verify GoTestRunner satisfies RunnerProtocol."""

    def test_implements_protocol(self):
        runner = GoTestRunner()
        assert isinstance(runner, RunnerProtocol)

    def test_has_name(self):
        runner = GoTestRunner()
        assert runner.name == "go_test"


class TestGoTestBuildCommand:
    """Test build_command output."""

    def test_default_command(self):
        runner = GoTestRunner()
        cmd = runner.build_command({})
        assert "go test -v -json" in cmd
        assert "./..." in cmd

    def test_with_args(self):
        runner = GoTestRunner()
        cmd = runner.build_command({"args": ["-count=1"]})
        assert "-count=1" in cmd

    def test_with_test_paths(self):
        runner = GoTestRunner()
        cmd = runner.build_command({"test_paths": ["./pkg/..."]})
        assert "./pkg/..." in cmd
        # Should not include default ./... when custom paths given
        assert "./..." not in cmd

    def test_with_args_and_paths(self):
        runner = GoTestRunner()
        cmd = runner.build_command({"args": ["-timeout=30s"], "test_paths": ["./internal/..."]})
        assert "-timeout=30s" in cmd
        assert "./internal/..." in cmd


class TestGoTestRunTests:
    """Test run_tests behavior with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return GoTestRunner()

    @pytest.mark.asyncio
    async def test_run_success(self, runner, tmp_path):
        stdout = (
            '{"Time":"2024-01-01T00:00:00Z","Action":"run","Package":"pkg","Test":"TestFoo"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"output","Package":"pkg","Test":"TestFoo","Output":"=== RUN   TestFoo\\n"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"pass","Package":"pkg","Test":"TestFoo","Elapsed":0.1}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert isinstance(result, TestRunResult)
        assert result.exit_code == 0
        assert result.passed == 1
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_run_with_failures(self, runner, tmp_path):
        stdout = (
            '{"Time":"2024-01-01T00:00:00Z","Action":"pass","Package":"pkg","Test":"TestFoo","Elapsed":0.1}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"run","Package":"pkg","Test":"TestBar"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"output","Package":"pkg","Test":"TestBar","Output":"--- FAIL: TestBar\\n"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"fail","Package":"pkg","Test":"TestBar","Elapsed":0.2}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.exit_code == 1
        assert result.passed == 1
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_run_with_skipped(self, runner, tmp_path):
        stdout = (
            '{"Time":"2024-01-01T00:00:00Z","Action":"run","Package":"pkg","Test":"TestSkip"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"output","Package":"pkg","Test":"TestSkip","Output":"--- SKIP: TestSkip\\n"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"skip","Package":"pkg","Test":"TestSkip","Elapsed":0}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 0
        assert result.skipped == 1

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

    @pytest.mark.asyncio
    async def test_mixed_event_types(self, runner, tmp_path):
        """Only pass/fail/skip actions on test-level events should be counted."""
        stdout = (
            '{"Time":"2024-01-01T00:00:00Z","Action":"start","Package":"pkg"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"run","Package":"pkg","Test":"TestA"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"output","Package":"pkg","Test":"TestA","Output":"line1\\n"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"pause","Package":"pkg","Test":"TestA"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"cont","Package":"pkg","Test":"TestA"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"pass","Package":"pkg","Test":"TestA","Elapsed":0.5}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"pass","Package":"pkg"}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 1
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_package_level_fail_counts_as_error(self, runner, tmp_path):
        """A package-level 'fail' (no Test field) increments the error count."""
        stdout = (
            '{"Time":"2024-01-01T00:00:00Z","Action":"fail","Package":"pkg"}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.error == 1
        assert result.passed == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_panic_output_ignored_gracefully(self, runner, tmp_path):
        """Non-JSON lines (e.g. panic output) are skipped without crashing."""
        stdout = (
            'panic: runtime error: invalid memory address\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"fail","Package":"pkg","Test":"TestPanic"}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_duplicate_test_events_use_last_action(self, runner, tmp_path):
        """If a test appears multiple times, only the final pass/fail/skip counts."""
        stdout = (
            '{"Time":"2024-01-01T00:00:00Z","Action":"pass","Package":"pkg","Test":"TestA"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"fail","Package":"pkg","Test":"TestA"}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        # Last action for TestA is "fail"
        assert result.passed == 0
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_env_vars_passed_through(self, runner, tmp_path):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(tmp_path, {}, env_vars={"CGO_ENABLED": "0"})

        _, kwargs = mock_exec.call_args
        assert kwargs["env"]["CGO_ENABLED"] == "0"


class TestGoTestRegistration:
    """Test that GoTestRunner is registered in builtins."""

    def test_register_builtins_includes_go_test(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "go_test" in registry.runner_names
