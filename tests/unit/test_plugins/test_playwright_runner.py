from __future__ import annotations

import asyncio
import shlex
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

    @staticmethod
    def _playwright_argv(
        command: str,
        expected_prefix: str = (
            "cd /workspace && mkdir -p results && "
            "PLAYWRIGHT_JUNIT_OUTPUT_FILE=results/junit.xml"
        ),
    ) -> list[str]:
        prefix, tail = command.split(" npx ", 1)
        assert prefix == expected_prefix
        return ["npx", *shlex.split(tail)]

    def test_default_config(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({})
        assert cmd == (
            "cd /workspace && mkdir -p results && "
            "PLAYWRIGHT_JUNIT_OUTPUT_FILE=results/junit.xml "
            "npx playwright test --reporter=junit"
        )
        assert self._playwright_argv(cmd) == [
            "npx",
            "playwright",
            "test",
            "--reporter=junit",
        ]

    def test_custom_junit_xml_path(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"junit_xml": "out/report.xml"})
        assert cmd == (
            "cd /workspace && mkdir -p out && "
            "PLAYWRIGHT_JUNIT_OUTPUT_FILE=out/report.xml "
            "npx playwright test --reporter=junit"
        )
        assert self._playwright_argv(
            cmd,
            "cd /workspace && mkdir -p out && "
            "PLAYWRIGHT_JUNIT_OUTPUT_FILE=out/report.xml",
        ) == [
            "npx",
            "playwright",
            "test",
            "--reporter=junit",
        ]

    @pytest.mark.parametrize(
        "junit_xml",
        ["/tmp/report.xml", "../report.xml", "reports/../report.xml", r"C:\tmp\report.xml"],
    )
    def test_rejects_junit_xml_outside_workspace(self, junit_xml):
        runner = PlaywrightRunner()
        with pytest.raises(ValueError) as exc_info:
            runner.build_command({"junit_xml": junit_xml})

        assert str(exc_info.value) == "junit_xml must be a relative path inside the workspace"
        assert junit_xml not in str(exc_info.value)

    @pytest.mark.parametrize(
        "test_path",
        ["/tmp/tests", "../secret", "tests/../secret", r"C:\tmp\tests", "", "   "],
    )
    def test_rejects_test_paths_outside_workspace(self, test_path):
        runner = PlaywrightRunner()
        with pytest.raises(ValueError) as exc_info:
            runner.build_command({"test_paths": ["tests/e2e", test_path]})

        assert str(exc_info.value) == "test_paths must be a relative path inside the workspace"
        if test_path:
            assert test_path not in str(exc_info.value)

    def test_extra_args(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"args": ["--grep", "login flow", "--workers=4"]})
        argv = self._playwright_argv(cmd)
        assert argv == [
            "npx",
            "playwright",
            "test",
            "--reporter=junit",
            "--grep",
            "login flow",
            "--workers=4",
        ]

    def test_extra_args_as_string(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"args": "--grep smoke --project=chromium"})
        argv = self._playwright_argv(cmd)
        assert argv == [
            "npx",
            "playwright",
            "test",
            "--reporter=junit",
            "--grep",
            "smoke",
            "--project=chromium",
        ]

    def test_test_paths(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({"test_paths": ["tests/e2e", "tests/ui"]})
        assert self._playwright_argv(cmd) == [
            "npx",
            "playwright",
            "test",
            "--reporter=junit",
            "tests/e2e",
            "tests/ui",
        ]

    def test_full_config(self):
        runner = PlaywrightRunner()
        cmd = runner.build_command({
            "junit_xml": "custom/junit.xml",
            "args": ["--project=chromium"],
            "test_paths": ["e2e/"],
        })
        assert cmd == (
            "cd /workspace && mkdir -p custom && "
            "PLAYWRIGHT_JUNIT_OUTPUT_FILE=custom/junit.xml "
            "npx playwright test --reporter=junit --project=chromium e2e/"
        )
        assert self._playwright_argv(
            cmd,
            "cd /workspace && mkdir -p custom && "
            "PLAYWRIGHT_JUNIT_OUTPUT_FILE=custom/junit.xml",
        ) == [
            "npx",
            "playwright",
            "test",
            "--reporter=junit",
            "--project=chromium",
            "e2e/",
        ]


class TestPlaywrightRunTests:
    """Test run_tests with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return PlaywrightRunner()

    def _assert_spawn_call(self, call_args, tmp_path, junit_xml: str) -> dict[str, str]:
        assert call_args.args == (
            "npx",
            "playwright",
            "test",
            "--reporter=junit",
        )
        env = call_args.kwargs["env"]
        assert call_args.kwargs == {
            "cwd": str(tmp_path),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": env,
        }
        assert env["PLAYWRIGHT_JUNIT_OUTPUT_FILE"] == junit_xml
        return env

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
        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")
        process.communicate.assert_awaited_once_with()

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

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")
        process.communicate.assert_awaited_once_with()
        assert result.passed == 1
        assert result.failed == 1
        assert result.exit_code == 1
        assert result.stdout == "1 failed, 1 passed"

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

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")
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
            report_path.write_text(
                '<testsuite name="s" tests="1">'
                '<testcase name="t1" time="0.1"/>'
                '</testsuite>'
            )
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"1 passed", b"")
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
    async def test_run_tests_with_env_vars(self, runner, tmp_path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        (results_dir / "junit.xml").write_text(
            '<testsuite name="s" tests="1"><testcase name="t1" time="0.1"/></testsuite>'
        )

        with patch.dict("os.environ", {"QAP_EXISTING_ENV": "kept"}, clear=False), \
             patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(
                tmp_path, {}, env_vars={"BASE_URL": "http://localhost:3000"}
            )

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        env = self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")
        assert env["BASE_URL"] == "http://localhost:3000"
        assert env["QAP_EXISTING_ENV"] == "kept"
        process.communicate.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_junit_xml_config_wins_over_env_var(self, runner, tmp_path):
        xml_path = tmp_path / "custom.xml"
        xml_path.write_text(
            '<testsuite name="s" tests="2">'
            '<testcase name="t1" time="0.1"/>'
            '<testcase name="t2" time="0.1"/>'
            '</testsuite>'
        )

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await runner.run_tests(
                tmp_path,
                {"junit_xml": "custom.xml"},
                env_vars={"PLAYWRIGHT_JUNIT_OUTPUT_FILE": "wrong.xml"},
            )

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        self._assert_spawn_call(call_args, tmp_path, "custom.xml")
        process.communicate.assert_awaited_once_with()
        assert result.passed == 2


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
