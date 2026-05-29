from __future__ import annotations

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

    def test_default_command(self):
        runner = JestRunner()
        cmd = runner.build_command({})
        assert "npx jest --ci --reporters=default --reporters=jest-junit" in cmd

    def test_with_args(self):
        runner = JestRunner()
        cmd = runner.build_command({"args": ["--maxWorkers=2"]})
        assert "--maxWorkers=2" in cmd

    def test_with_test_paths(self):
        runner = JestRunner()
        cmd = runner.build_command({"test_paths": ["src/__tests__"]})
        assert "src/__tests__" in cmd

    def test_with_args_and_paths(self):
        runner = JestRunner()
        cmd = runner.build_command({"args": ["--verbose"], "test_paths": ["tests/unit"]})
        assert "--verbose" in cmd
        assert "tests/unit" in cmd


class TestJestRunTests:
    """Test run_tests behavior with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return JestRunner()

    def _write_junit_xml(self, path: Path, tests=5, failures=1, errors=0, skipped=0):
        """Write a minimal jest-junit XML file."""
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
        ET.SubElement(suite, "testcase", name="test1")
        tree = ET.ElementTree(root)
        tree.write(path, xml_declaration=True)

    @pytest.mark.asyncio
    async def test_run_success(self, runner, tmp_path):
        self._write_junit_xml(tmp_path / "junit.xml", tests=3, failures=0)
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"PASS", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {"junit_xml": "junit.xml"})

        assert isinstance(result, TestRunResult)
        assert result.exit_code == 0
        assert result.passed == 3
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_run_with_failures(self, runner, tmp_path):
        self._write_junit_xml(tmp_path / "junit.xml", tests=5, failures=2, skipped=1)
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (b"FAIL", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {"junit_xml": "junit.xml"})

        assert result.exit_code == 1
        assert result.failed == 2
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_missing_junit_xml_returns_zeros(self, runner, tmp_path):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {"junit_xml": "nonexistent.xml"})

        assert result.passed == 0
        assert result.failed == 0
        assert result.skipped == 0
        assert result.error == 0

    @pytest.mark.asyncio
    async def test_env_vars_passed_through(self, runner, tmp_path):
        self._write_junit_xml(tmp_path / "junit.xml")
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(
                tmp_path, {"junit_xml": "junit.xml"}, env_vars={"NODE_ENV": "test"}
            )

        _, kwargs = mock_exec.call_args
        assert kwargs["env"]["NODE_ENV"] == "test"


class TestJestRegistration:
    """Test that JestRunner is registered in builtins."""

    def test_register_builtins_includes_jest(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "jest" in registry.runner_names
