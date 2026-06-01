from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
LOG_STREAM_TEST = ROOT / "tests" / "unit" / "test_engine" / "test_log_stream.py"
GIT_SOURCE_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_git_source.py"
JUNIT_COLLECTOR_TEST = (
    ROOT / "tests" / "unit" / "test_plugins" / "test_junit_collector.py"
)
PYTEST_RUNNER_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_pytest_runner.py"
JEST_RUNNER_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_jest_runner.py"
PLAYWRIGHT_RUNNER_TEST = (
    ROOT / "tests" / "unit" / "test_plugins" / "test_playwright_runner.py"
)
GO_TEST_RUNNER_TEST = (
    ROOT / "tests" / "unit" / "test_plugins" / "test_go_test_runner.py"
)


def test_quality_ops_records_current_gate_runner_source_evidence():
    log_stream_test = _read(LOG_STREAM_TEST)
    git_source_test = _read(GIT_SOURCE_TEST)
    junit_collector_test = _read(JUNIT_COLLECTOR_TEST)
    pytest_runner_test = _read(PYTEST_RUNNER_TEST)
    jest_runner_test = _read(JEST_RUNNER_TEST)
    playwright_runner_test = _read(PLAYWRIGHT_RUNNER_TEST)
    go_test_runner_test = _read(GO_TEST_RUNNER_TEST)
    pytest_runner_command_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Pytest runner command argv 精确契约）"
    )
    js_runner_command_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Jest/Playwright runner command argv 精确契约）"
    )
    go_runner_command_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Go runner shell command 精确契约）"
    )
    git_source_clone_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（GitSource clone argv/auth env 精确契约）"
    )
    junit_collector_result_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（JUnit collector result data 精确契约）"
    )
    log_stream_live_read_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（LogStream live read entries 精确契约）"
    )
    assert (
        "`tests/unit/test_plugins/test_pytest_runner.py::TestPytestBuildCommand tests/unit/test_plugins/test_pytest_runner.py::TestPytestBuildCommandInternal` 25 passed"
        in (pytest_runner_command_exact_row)
    )
    assert "完整参数序列" in pytest_runner_command_exact_row
    assert "大量使用 `in cmd`" in pytest_runner_command_exact_row
    assert "只证明“关键字符串在里面”" in pytest_runner_command_exact_row
    assert "def _assert_command(command: str, expected_argv: list[str])" in (
        pytest_runner_test
    )
    assert 'expected_command = "cd /workspace && " + " ".join(' in (pytest_runner_test)
    assert "shlex.quote(part) for part in expected_argv" in pytest_runner_test
    assert "assert command == expected_command" in pytest_runner_test
    assert "assert shlex.split(command.removeprefix" in pytest_runner_test
    assert "assert cmd == [" in pytest_runner_test
    assert "assert command.startswith" not in pytest_runner_test
    assert "assert self._argv(cmd) == [" not in pytest_runner_test
    assert 'assert "python -m pytest" in cmd' not in pytest_runner_test
    assert 'assert "-x" in cmd' not in pytest_runner_test
    assert 'assert "tests/unit" in cmd' not in pytest_runner_test
    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestBuildCommand tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightBuildCommand` 31 passed"
        in (js_runner_command_exact_row)
    )
    assert "完整 argv 序列" in js_runner_command_exact_row
    assert "主要靠 `in cmd`" in js_runner_command_exact_row
    assert "只证明“几个片段出现过”" in js_runner_command_exact_row
    assert "JEST_JUNIT_OUTPUT_FILE=results/junit.xml" in jest_runner_test
    assert "assert self._jest_argv(cmd) == [" in jest_runner_test
    assert 'assert "--maxWorkers=2" in cmd' not in jest_runner_test
    assert 'assert "src/__tests__" in cmd' not in jest_runner_test
    assert "PLAYWRIGHT_JUNIT_OUTPUT_FILE=results/junit.xml" in playwright_runner_test
    assert "assert self._playwright_argv(cmd) == [" in playwright_runner_test
    assert 'assert "--workers=4" in argv' not in playwright_runner_test
    assert 'assert "tests/e2e" in cmd' not in playwright_runner_test
    assert (
        "`tests/unit/test_plugins/test_go_test_runner.py::TestGoTestBuildCommand` 15 passed"
        in (go_runner_command_exact_row)
    )
    assert "FIFO/tee 管道" in go_runner_command_exact_row
    assert "`go test` argv 序列" in go_runner_command_exact_row
    assert "只证明“脚本里有那些词”" in go_runner_command_exact_row
    assert "def _go_test_argv(command: str) -> list[str]:" in go_test_runner_test
    assert "assert lines[-12:] == [" in go_test_runner_test
    assert (
        'assert self._go_test_argv(cmd) == ["go", "test", "-v", "-json", "./..."]'
        in (go_test_runner_test)
    )
    assert 'assert "go test -v -json" in cmd' not in go_test_runner_test
    assert 'assert "./pkg/..." in cmd' not in go_test_runner_test
    assert (
        "`tests/unit/test_plugins/test_git_source.py::TestGitSourceClone` targeted passed"
        in (git_source_clone_exact_row)
    )
    assert "完整 `git clone` argv" in git_source_clone_exact_row
    assert "token askpass username" in git_source_clone_exact_row
    assert "只证明“几个参数在命令里”" in git_source_clone_exact_row
    assert "assert clone_call.args == (" in git_source_test
    assert (
        'assert clone_call.kwargs["env"]["QAP_GIT_USERNAME"] == "x-access-token"'
        in (git_source_test)
    )
    assert 'assert clone_call.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"' in (
        git_source_test
    )
    assert "assert mock_exec.await_args.args == (" in git_source_test
    assert 'assert "--depth" in cmd' not in git_source_test
    assert 'assert "--branch" in cmd' not in git_source_test
    assert "`tests/unit/test_plugins/test_junit_collector.py` 24 passed" in (
        junit_collector_result_exact_row
    )
    assert "完整 `TestResultData` 列表/对象" in junit_collector_result_exact_row
    assert "多用 `len(results)` 加少量字段检查" in junit_collector_result_exact_row
    assert "返回了几条且某些字段看起来对" in junit_collector_result_exact_row
    assert (
        "from qaplatform.plugins.protocols import ArtifactData, CollectorProtocol, TestResultData"
        in (junit_collector_test)
    )
    assert "assert results == [" in junit_collector_test
    assert "assert result == TestResultData(" in junit_collector_test
    assert "assert len(results)" not in junit_collector_test
    assert "assert results[0]" not in junit_collector_test
    assert (
        "`tests/unit/test_engine/test_log_stream.py::TestLogStream::test_read_logs_with_data` 1 passed"
        in (log_stream_live_read_exact_row)
    )
    assert "固定完整 entries 列表" in log_stream_live_read_exact_row
    assert '`xread({stream: "0"}, count=50)` await 参数' in (
        log_stream_live_read_exact_row
    )
    assert "只用 `len(entries)` 加首条字段和第二条 stream 抽查" in (
        log_stream_live_read_exact_row
    )
    assert "assert entries == [" in log_stream_test
    assert "self.redis.xread.assert_awaited_once_with(" in log_stream_test
    assert "assert len(entries) == 2" not in log_stream_test
