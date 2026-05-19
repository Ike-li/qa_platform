from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from qaplatform.plugins.builtin.playwright_runner import PlaywrightRunner
from qaplatform.plugins.protocols import RunnerProtocol, TestRunResult


class TestPlaywrightProtocol:
    """Verify PlaywrightRunner satisfies RunnerProtocol."""

    def test_implements_protocol(self):
        runner = PlaywrightRunner()
        assert isinstance(runner, RunnerProtocol)

    def test_has_name(self):
        runner = PlaywrightRunner()
        assert runner.name == "playwright"


class TestPlaywrightBuildCommand:
    """Test build_command output."""

    def test_default_config(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({})
        assert "npx" in cmd
        assert "playwright" in cmd
        assert "test" in cmd
        assert "--reporter=junit" in cmd

    def test_custom_junit_xml_path(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"junit_xml": "out/report.xml"})
        assert "--reporter=junit,out/report.xml" in cmd

    def test_extra_args(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"args": ["--grep", "smoke", "--workers=4"]})
        assert "--grep" in cmd
        assert "smoke" in cmd
        assert "--workers=4" in cmd

    def test_extra_args_as_string(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"args": "--grep smoke --project=chromium"})
        assert "--grep" in cmd
        assert "smoke" in cmd
        assert "--project=chromium" in cmd

    def test_test_paths(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"test_paths": ["tests/e2e", "tests/ui"]})
        assert "tests/e2e" in cmd
        assert "tests/ui" in cmd

    def test_full_config(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({
            "junit_xml": "custom/junit.xml",
            "args": ["--project=chromium"],
            "test_paths": ["e2e/"],
        })
        assert "--reporter=junit,custom/junit.xml" in cmd
        assert "--project=chromium" in cmd
        assert "e2e/" in cmd


class TestPlaywrightRunTests:
    """Test run_tests with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return PlaywrightRunner()

    @pytest.mark.asyncio
    async def test_run_tests_success(self, runner, tmp_path):
        # Create a JUnit XML file for parsing
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        junit_xml = results_dir / "junit.xml"
        junit_xml.write_text(
            '<testsuite name="suite" tests="3">'
            '<testcase name="t1" time="0.1"/>'
            '<testcase name="t2" time="0.2"/>'
            '<testcase name="t3" time="0.3"/>'
            '</testsuite>'
        )

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"3 passed", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert isinstance(result, TestRunResult)
        assert result.passed == 3
        assert result.failed == 0
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_tests_with_failures(self, runner, tmp_path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        junit_xml = results_dir / "junit.xml"
        junit_xml.write_text(
            '<testsuite name="suite" tests="2">'
            '<testcase name="t1" time="0.1">'
            '<failure message="assertion error">Traceback...</failure>'
            '</testcase>'
            '<testcase name="t2" time="0.2"/>'
            '</testsuite>'
        )

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (b"1 failed, 1 passed", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 1
        assert result.failed == 1
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_run_tests_with_skipped(self, runner, tmp_path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        junit_xml = results_dir / "junit.xml"
        junit_xml.write_text(
            '<testsuite name="suite" tests="2">'
            '<testcase name="t1" time="0.1">'
            '<skipped message="not applicable"/>'
            '</testcase>'
            '<testcase name="t2" time="0.2"/>'
            '</testsuite>'
        )

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"1 passed, 1 skipped", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 1
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_run_tests_no_junit_file(self, runner, tmp_path):
        """When JUnit XML is missing, counts default to zero."""
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
    async def test_run_tests_with_env_vars(self, runner, tmp_path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        (results_dir / "junit.xml").write_text(
            '<testsuite name="s" tests="1"><testcase name="t1" time="0.1"/></testsuite>'
        )

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(
                tmp_path, {}, env_vars={"BASE_URL": "http://localhost:3000"}
            )

        # Verify env was passed through
        call_kwargs = mock_exec.call_args
        assert call_kwargs[1].get("env") == {"BASE_URL": "http://localhost:3000"}


class TestPlaywrightJUnitParsing:
    """Test JUnit XML count parsing directly."""

    def test_parse_testsuites_root(self, tmp_path):
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(
            '<testsuites><testsuite name="s1">'
            '<testcase name="t1" time="0.1"/>'
            '<testcase name="t2" time="0.2">'
            '<failure message="boom"/>'
            '</testcase>'
            '</testsuite></testsuites>'
        )
        counts = PlaywrightRunner._parse_junit_counts(xml_path)
        assert counts == {"passed": 1, "failed": 1, "skipped": 0, "error": 0}

    def test_parse_testsuite_root(self, tmp_path):
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(
            '<testsuite name="s1">'
            '<testcase name="t1" time="0.1">'
            '<error message="err"/>'
            '</testcase>'
            '<testcase name="t2" time="0.1">'
            '<skipped message="skip"/>'
            '</testcase>'
            '<testcase name="t3" time="0.1"/>'
            '</testsuite>'
        )
        counts = PlaywrightRunner._parse_junit_counts(xml_path)
        assert counts == {"passed": 1, "failed": 0, "skipped": 1, "error": 1}

    def test_parse_missing_file(self, tmp_path):
        counts = PlaywrightRunner._parse_junit_counts(tmp_path / "nope.xml")
        assert counts == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}

    def test_parse_malformed_xml(self, tmp_path):
        xml_path = tmp_path / "bad.xml"
        xml_path.write_text("not xml at all")
        counts = PlaywrightRunner._parse_junit_counts(xml_path)
        assert counts == {"passed": 0, "failed": 0, "skipped": 0, "error": 0}


class TestPlaywrightRegistration:
    """Test that PlaywrightRunner is registered in builtins."""

    def test_register_builtins_includes_playwright_runner(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "playwright" in registry.runner_names

    def test_get_playwright_runner(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        runner = registry.get_runner("playwright")
        assert isinstance(runner, PlaywrightRunner)
        assert runner.name == "playwright"
