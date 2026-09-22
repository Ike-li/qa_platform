from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, patch

import pytest

from qaplatform.plugins.builtin.go_test_runner import (
    _GO_JUNIT_HELPER_SOURCE,
    GoTestRunner,
)
from qaplatform.plugins.protocols import RunnerProtocol, TestRunResult


def _find_testcase(root: ET.Element, name: str) -> ET.Element:
    testcase = root.find(f".//testcase[@name='{name}']")
    assert testcase is not None, f"{name} testcase missing"
    return testcase


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

    @staticmethod
    def _go_test_argv(command: str) -> list[str]:
        go_test_line = next(line for line in command.splitlines() if line.startswith("go test "))
        return shlex.split(go_test_line.split(" > ", 1)[0])

    def test_default_command(self):
        runner = GoTestRunner()
        cmd = runner.build_command({})
        lines = cmd.splitlines()
        assert lines[0] == (
            "cd /workspace && mkdir -p results && "
            "cat > /tmp/qaplatform-go-junit.go <<'QAP_GO_JUNIT'"
        )
        assert lines[-12:] == [
            "QAP_GO_JUNIT",
            "rm -f results/go-test.json.pipe",
            "mkfifo results/go-test.json.pipe",
            "tee results/go-test.json < results/go-test.json.pipe &",
            "tee_pid=$!",
            "go test -v -json ./... > results/go-test.json.pipe "
            "2> results/go-test.json.stderr",
            "status=$?",
            'wait "$tee_pid" || true',
            "rm -f results/go-test.json.pipe",
            "if [ -s results/go-test.json.stderr ]; then cat results/go-test.json.stderr >&2; fi",
            "GO111MODULE=off GOTOOLCHAIN=local "
            "go run /tmp/qaplatform-go-junit.go results/go-test.json results/junit.xml || true",
            "exit $status",
        ]
        assert self._go_test_argv(cmd) == ["go", "test", "-v", "-json", "./..."]

    def test_with_args(self):
        runner = GoTestRunner()
        cmd = runner.build_command({"args": ["-count=1"]})
        assert self._go_test_argv(cmd) == ["go", "test", "-v", "-json", "-count=1", "./..."]

    def test_with_test_paths(self):
        runner = GoTestRunner()
        cmd = runner.build_command({"test_paths": ["./pkg/..."]})
        assert self._go_test_argv(cmd) == ["go", "test", "-v", "-json", "./pkg/..."]

    def test_with_args_and_paths(self):
        runner = GoTestRunner()
        cmd = runner.build_command({"args": ["-run", "Test Login"], "test_paths": ["./internal/..."]})
        assert self._go_test_argv(cmd) == [
            "go",
            "test",
            "-v",
            "-json",
            "-run",
            "Test Login",
            "./internal/...",
        ]

    def test_custom_junit_xml_is_used_by_worker_command(self):
        runner = GoTestRunner()
        cmd = runner.build_command({"junit_xml": "custom report/junit.xml"})
        lines = cmd.splitlines()

        assert lines[0] == (
            "cd /workspace && mkdir -p 'custom report' results && "
            "cat > /tmp/qaplatform-go-junit.go <<'QAP_GO_JUNIT'"
        )
        assert lines[-2] == (
            "GO111MODULE=off GOTOOLCHAIN=local "
            "go run /tmp/qaplatform-go-junit.go results/go-test.json "
            "'custom report/junit.xml' || true"
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("junit_xml", "/tmp/report.xml"),
            ("junit_xml", "../report.xml"),
            ("json_output", "/tmp/go-test.json"),
            ("json_output", "../go-test.json"),
        ],
    )
    def test_rejects_output_paths_outside_workspace(self, field, value):
        runner = GoTestRunner()
        with pytest.raises(ValueError) as exc_info:
            runner.build_command({field: value})

        assert str(exc_info.value) == f"{field} must be a relative path inside the workspace"
        assert value not in str(exc_info.value)

    @pytest.mark.parametrize(
        "test_path",
        ["/tmp/tests", "../secret", "tests/../secret", r"C:\tmp\tests", "", "   "],
    )
    def test_rejects_test_paths_outside_workspace(self, test_path):
        runner = GoTestRunner()
        with pytest.raises(ValueError) as exc_info:
            runner.build_command({"test_paths": ["./pkg/...", test_path]})

        assert str(exc_info.value) == "test_paths must be a relative path inside the workspace"
        if test_path:
            assert test_path not in str(exc_info.value)


class TestGoTestRunTests:
    """Test run_tests behavior with mocked subprocess."""

    @pytest.fixture
    def runner(self):
        return GoTestRunner()

    def _assert_spawn_call(self, call_args, tmp_path):
        assert call_args.args == (
            "go",
            "test",
            "-v",
            "-json",
            "./...",
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
        assert (tmp_path / "results" / "go-test.json").read_text() == stdout
        junit_xml = tmp_path / "results" / "junit.xml"
        assert junit_xml.exists()
        root = ET.parse(junit_xml).getroot()
        assert root.get("tests") == "1"
        assert root.get("failures") == "0"
        assert root.get("errors") == "0"
        assert root.get("skipped") == "0"
        testcase = _find_testcase(root, "TestFoo")
        assert testcase.get("name") == "TestFoo"
        assert testcase.get("classname") == "pkg"
        assert testcase.get("time") == "0.100000"
        assert testcase.find("failure") is None
        assert testcase.find("error") is None
        assert testcase.find("skipped") is None

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
        root = ET.parse(tmp_path / "results" / "junit.xml").getroot()
        assert root.tag == "testsuites"
        assert root.attrib == {
            "tests": "2",
            "failures": "1",
            "errors": "0",
            "skipped": "0",
        }
        suite = root.find("./testsuite")
        assert suite is not None
        assert suite.attrib == {
            "name": "pkg",
            "tests": "2",
            "failures": "1",
            "errors": "0",
            "skipped": "0",
        }
        passed = _find_testcase(root, "TestFoo")
        assert passed.attrib == {"classname": "pkg", "name": "TestFoo", "time": "0.100000"}
        assert list(passed) == []
        failure = _find_testcase(root, "TestBar").find("failure")
        assert failure is not None
        failed = _find_testcase(root, "TestBar")
        assert failed.attrib == {"classname": "pkg", "name": "TestBar", "time": "0.200000"}
        assert list(failed) == [failure]
        assert failure.attrib == {"message": "go test failed"}
        assert failure.text == "--- FAIL: TestBar"

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
        root = ET.parse(tmp_path / "results" / "junit.xml").getroot()
        assert root.tag == "testsuites"
        assert root.attrib == {
            "tests": "1",
            "failures": "0",
            "errors": "0",
            "skipped": "1",
        }
        suite = root.find("./testsuite")
        assert suite is not None
        assert suite.attrib == {
            "name": "pkg",
            "tests": "1",
            "failures": "0",
            "errors": "0",
            "skipped": "1",
        }
        testcase = _find_testcase(root, "TestSkip")
        skipped = testcase.find("skipped")
        assert skipped is not None
        assert testcase.attrib == {
            "classname": "pkg",
            "name": "TestSkip",
            "time": "0.000000",
        }
        assert list(testcase) == [skipped]
        assert skipped.attrib == {"message": "go test skipped"}
        assert skipped.text == "--- SKIP: TestSkip"

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
            '{"Time":"2024-01-01T00:00:00Z","Action":"output","Package":"pkg","Output":"setup failed\\n"}\n'
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
        root = ET.parse(tmp_path / "results" / "junit.xml").getroot()
        testcase = root.find("./testsuite/testcase")
        assert testcase is not None
        assert testcase.get("name") == "package_error"
        error = testcase.find("error")
        assert error is not None
        assert error.get("message") == "go test package failed"
        assert error.text == "setup failed"

    @pytest.mark.asyncio
    async def test_real_go_package_fail_after_test_fail_is_not_double_counted(
        self, runner, tmp_path
    ):
        stdout = (
            '{"Time":"2024-01-01T00:00:00Z","Action":"run","Package":"pkg","Test":"TestBar"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"output","Package":"pkg","Test":"TestBar","Output":"--- FAIL: TestBar\\n"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"fail","Package":"pkg","Test":"TestBar","Elapsed":0.2}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"output","Package":"pkg","Output":"FAIL\\n"}\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"fail","Package":"pkg","Elapsed":0.2}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 1
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.failed == 1
        assert result.error == 0
        root = ET.parse(tmp_path / "results" / "junit.xml").getroot()
        assert root.get("failures") == "1"
        assert root.get("errors") == "0"

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
    async def test_valid_json_non_object_lines_ignored_gracefully(self, runner, tmp_path):
        stdout = (
            '["valid-json-but-not-an-event"]\n'
            '"also-not-an-event"\n'
            '{"Time":"2024-01-01T00:00:00Z","Action":"pass","Package":"pkg","Test":"TestFoo"}\n'
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 1
        assert result.failed == 0
        root = ET.parse(tmp_path / "results" / "junit.xml").getroot()
        assert root.get("tests") == "1"
        assert _find_testcase(root, "TestFoo").get("time") == "0.000000"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("elapsed", ["not-a-number", "NaN", "Infinity", -0.25])
    async def test_malformed_elapsed_does_not_abort_result_collection(
        self, runner, tmp_path, elapsed
    ):
        stdout = json.dumps(
            {
                "Time": "2024-01-01T00:00:00Z",
                "Action": "pass",
                "Package": "pkg",
                "Test": "TestFoo",
                "Elapsed": elapsed,
            }
        ) + "\n"
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (stdout.encode(), b"")
            mock_exec.return_value = process

            result = await runner.run_tests(tmp_path, {})

        assert result.passed == 1
        root = ET.parse(tmp_path / "results" / "junit.xml").getroot()
        assert _find_testcase(root, "TestFoo").get("time") == "0.000000"

    def test_go_junit_helper_handles_malformed_elapsed_when_go_available(
        self, tmp_path
    ):
        go_binary = shutil.which("go")
        if go_binary is None:
            pytest.skip("go toolchain unavailable")

        helper = tmp_path / "helper.go"
        source = tmp_path / "go-test.json"
        output = tmp_path / "junit.xml"
        helper.write_text(_GO_JUNIT_HELPER_SOURCE, encoding="utf-8")
        source.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "Action": "pass",
                            "Package": "pkg",
                            "Test": "TestStringElapsed",
                            "Elapsed": "not-a-number",
                        }
                    ),
                    json.dumps(
                        {
                            "Action": "pass",
                            "Package": "pkg",
                            "Test": "TestInfiniteElapsed",
                            "Elapsed": "Infinity",
                        }
                    ),
                    json.dumps(
                        {
                            "Action": "pass",
                            "Package": "pkg",
                            "Test": "TestNegativeElapsed",
                            "Elapsed": -0.25,
                        }
                    ),
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [go_binary, "run", str(helper), str(source), str(output)],
            check=False,
            env={**os.environ, "GO111MODULE": "off", "GOTOOLCHAIN": "local"},
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        root = ET.parse(output).getroot()
        assert root.get("tests") == "3"
        assert _find_testcase(root, "TestStringElapsed").get("time") == "0.000000"
        assert _find_testcase(root, "TestInfiniteElapsed").get("time") == "0.000000"
        assert _find_testcase(root, "TestNegativeElapsed").get("time") == "0.000000"

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
        with patch.dict("os.environ", {"QAP_EXISTING_ENV": "kept"}, clear=False), \
             patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            await runner.run_tests(tmp_path, {}, env_vars={"CGO_ENABLED": "0"})

        mock_exec.assert_awaited_once()
        call_args = mock_exec.await_args
        env = self._assert_spawn_call(call_args, tmp_path)
        assert env["CGO_ENABLED"] == "0"
        assert env["QAP_EXISTING_ENV"] == "kept"
        process.communicate.assert_awaited_once_with()


class TestGoTestRegistration:
    """Test that GoTestRunner is registered in builtins."""

    def test_register_builtins_includes_go_test(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "go_test" in registry.runner_names
