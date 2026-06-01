from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _block_between,
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
GO_TEST_RUNNER_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_go_test_runner.py"
JEST_RUNNER_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_jest_runner.py"
JUNIT_COLLECTOR_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_junit_collector.py"
PLAYWRIGHT_RUNNER_TEST = (
    ROOT / "tests" / "unit" / "test_plugins" / "test_playwright_runner.py"
)
PLUGIN_REGISTRY_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_registry.py"
PYTEST_RUNNER_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_pytest_runner.py"


def test_quality_ops_capture_plugin_registry_builtins_exact_contract():
    row = _quality_ops_row_containing("PluginRegistry builtins 精确清单契约")
    plugin_registry_test = _read(PLUGIN_REGISTRY_TEST)

    assert "PluginRegistry builtins 精确清单契约" in row
    assert "不再只用子集/包含断言" in row
    assert 'registry.runner_names == ["pytest", "jest", "go_test", "playwright"]' in (
        plugin_registry_test
    )
    assert 'registry.collector_names == ["junit"]' in plugin_registry_test
    assert 'registry.source_names == ["git"]' in plugin_registry_test
    assert '{"pytest", "jest", "go_test", "playwright"} <= set(registry.runner_names)' not in (
        plugin_registry_test
    )


def test_quality_ops_capture_junit_upload_report_exact_artifact_s3_contract():
    junit_collector_test = _read(JUNIT_COLLECTOR_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（JUnit upload report exact artifact/S3 契约）"
    )

    assert "JUnit upload report exact artifact/S3 契约" in row
    assert (
        "`tests/unit/test_plugins/test_junit_collector.py::TestCollect::test_upload_report` 1 passed"
        in row
    )
    assert "junit collector full 24 passed" in row
    assert "release quality docs contract full 190 passed" in row
    assert "完整 ArtifactData（name/type/local_path/mime_type）" in row
    assert "S3 `put_object` 完整 kwargs（Bucket/Key/Body/ContentType）等值断言" in row
    assert "此前逐字段抽查 artifact 与 S3 kwargs" in row
    assert "JUnit 上传测试只证明“上传过一个叫 junit.xml 的对象”" in row

    assert "from qaplatform.plugins.protocols import ArtifactData, CollectorProtocol, TestResultData" in (
        junit_collector_test
    )
    block = _marked_block(
        junit_collector_test,
        "async def test_upload_report",
        "async def test_upload_report_no_file",
    )
    for expected in [
        "assert artifact == ArtifactData(",
        'name="junit.xml"',
        'type="report"',
        'local_path=results_dir / "junit.xml"',
        'mime_type="application/xml"',
        "mock_s3.put_object.assert_awaited_once()",
        "assert mock_s3.put_object.await_args.kwargs == {",
        '"Bucket": "my-bucket"',
        '"Key": f"reports/{run_id}/junit.xml"',
        '"Body": xml',
        '"ContentType": "application/xml"',
    ]:
        assert expected in block
    assert "assert artifact is not None" not in block
    assert "assert artifact.name ==" not in block
    assert "assert artifact.type ==" not in block
    assert "call_kwargs = mock_s3.put_object.await_args.kwargs" not in block
    assert 'call_kwargs["Bucket"]' not in block


def test_quality_ops_capture_js_runner_subprocess_kwargs_direct_helper_contract():
    jest_runner_test = _read(JEST_RUNNER_TEST)
    playwright_runner_test = _read(PLAYWRIGHT_RUNNER_TEST)
    row = _quality_ops_row("|", contains="JS runner subprocess kwargs direct helper 契约")

    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestRunTests "
        "tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightRunTests` "
        "15 passed"
    ) in row
    assert "jest/playwright runner full 57 passed" in row
    assert "release quality docs contract full 341 passed" in row
    assert "targeted ruff passed" in row
    assert 'call_args.kwargs == {"cwd","stdout","stderr","env"}' in row
    assert "`assert set(call_args.kwargs)`" in row
    assert "kwargs key 集合看起来对" in row

    for runner_test, env_var, expected_args in (
        (
            jest_runner_test,
            "JEST_JUNIT_OUTPUT_FILE",
            (
                '"npx"',
                '"jest"',
                '"--ci"',
                '"--reporters=default"',
                '"--reporters=jest-junit"',
            ),
        ),
        (
            playwright_runner_test,
            "PLAYWRIGHT_JUNIT_OUTPUT_FILE",
            ('"npx"', '"playwright"', '"test"', '"--reporter=junit"'),
        ),
    ):
        helper_block = _block_between(runner_test, "def _assert_spawn_call", "\n\n    @pytest.mark.asyncio")
        assert "assert call_args.args == (" in helper_block
        for expected_arg in expected_args:
            assert expected_arg in helper_block
        assert "env = call_args.kwargs[\"env\"]" in helper_block
        assert "assert call_args.kwargs == {" in helper_block
        assert '"cwd": str(tmp_path)' in helper_block
        assert '"stdout": asyncio.subprocess.PIPE' in helper_block
        assert '"stderr": asyncio.subprocess.PIPE' in helper_block
        assert '"env": env' in helper_block
        assert f'assert env["{env_var}"] == junit_xml' in helper_block
        assert "assert set(call_args.kwargs)" not in runner_test

    assert (
        'self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")'
        in jest_runner_test
    )
    assert 'self._assert_spawn_call(call_args, tmp_path, "junit.xml")' in (
        jest_runner_test
    )
    assert 'self._assert_spawn_call(call_args, tmp_path, "nonexistent.xml")' in (
        jest_runner_test
    )
    assert (
        'self._assert_spawn_call(call_args, tmp_path, "nested/reports/junit.xml")'
        in jest_runner_test
    )
    assert 'self._assert_spawn_call(call_args, tmp_path, "configured.xml")' in (
        jest_runner_test
    )
    assert 'env = self._assert_spawn_call(call_args, tmp_path, "junit.xml")' in (
        jest_runner_test
    )
    assert 'assert env["NODE_ENV"] == "test"' in jest_runner_test
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in jest_runner_test

    assert (
        playwright_runner_test.count(
            'self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")'
        )
        == 4
    )
    assert (
        'self._assert_spawn_call(call_args, tmp_path, "nested/reports/junit.xml")'
        in playwright_runner_test
    )
    assert 'self._assert_spawn_call(call_args, tmp_path, "custom.xml")' in (
        playwright_runner_test
    )
    assert 'env = self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")' in (
        playwright_runner_test
    )
    assert 'assert env["BASE_URL"] == "http://localhost:3000"' in playwright_runner_test
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in playwright_runner_test


def test_quality_ops_capture_js_runner_junit_parent_subprocess_exact_contract():
    row = _quality_ops_row_containing(
        "Jest/Playwright JUnit parent subprocess exact 契约"
    )
    jest_runner_test = _read(JEST_RUNNER_TEST)
    playwright_runner_test = _read(PLAYWRIGHT_RUNNER_TEST)

    assert "Jest/Playwright JUnit parent subprocess exact 契约" in row
    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestRunTests::test_run_tests_creates_custom_junit_parent_directory tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightRunTests::test_run_tests_creates_custom_junit_parent_directory` 2 passed"
        in row
    )
    assert "jest/playwright runner full 57 passed" in row
    assert "release quality docs contract full 165 passed" in row
    assert "`create_subprocess_exec` 的完整 argv、cwd、stdout/stderr pipe" in (
        row
    )
    assert "runner 专属 JUnit env 覆盖值" in row
    assert "此前只用 side-effect 写报告并断言 `mock_exec.assert_awaited_once()`" in (
        row
    )
    assert "runner JUnit parent 测试只证明“目录存在且解析到了报告”" in (
        row
    )

    jest_block = _marked_block(
        jest_runner_test,
        "async def test_run_tests_creates_custom_junit_parent_directory",
        "async def test_env_vars_passed_through",
    )
    playwright_block = _marked_block(
        playwright_runner_test,
        "async def test_run_tests_creates_custom_junit_parent_directory",
        "async def test_run_tests_with_env_vars",
    )

    assert "import asyncio" in jest_runner_test
    assert "call_args = mock_exec.await_args" in jest_block
    assert (
        'self._assert_spawn_call(call_args, tmp_path, "nested/reports/junit.xml")'
        in jest_block
    )
    assert "assert set(call_args.kwargs)" not in jest_block

    assert "import asyncio" in playwright_runner_test
    assert "call_args = mock_exec.await_args" in playwright_block
    assert (
        'self._assert_spawn_call(call_args, tmp_path, "nested/reports/junit.xml")'
        in playwright_block
    )
    assert "assert set(call_args.kwargs)" not in playwright_block


def test_quality_ops_capture_js_runner_missing_junit_still_executes_contract():
    row = _quality_ops_row_containing(
        "Jest/Playwright missing JUnit still executes 契约"
    )
    jest_runner_test = _read(JEST_RUNNER_TEST)
    playwright_runner_test = _read(PLAYWRIGHT_RUNNER_TEST)

    assert "Jest/Playwright missing JUnit still executes 契约" in row
    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestRunTests::test_missing_junit_xml_returns_zeros tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightRunTests::test_run_tests_no_junit_file` 2 passed"
        in row
    )
    assert "jest/playwright runner full 57 passed" in row
    assert "release quality docs contract full 167 passed" in row
    assert "runner subprocess 的完整 argv、cwd、stdout/stderr pipe" in row
    assert "`process.communicate()` 被 await 后才返回全零计数" in row
    assert "此前只断言返回 0 计数" in row
    assert "实现完全跳过 `create_subprocess_exec`" in row
    assert "missing-report 测试只证明“没报告时能给 0”" in row

    jest_block = _marked_block(
        jest_runner_test,
        "async def test_missing_junit_xml_returns_zeros",
        "async def test_run_tests_creates_custom_junit_parent_directory",
    )
    playwright_block = _marked_block(
        playwright_runner_test,
        "async def test_run_tests_no_junit_file",
        "async def test_run_tests_creates_custom_junit_parent_directory",
    )

    assert "def _assert_spawn_call" in jest_runner_test
    assert 'assert call_args.kwargs == {' in jest_runner_test
    assert 'assert set(call_args.kwargs)' not in jest_runner_test
    assert "mock_exec.assert_awaited_once()" in jest_block
    assert "call_args = mock_exec.await_args" in jest_block
    assert 'self._assert_spawn_call(call_args, tmp_path, "nonexistent.xml")' in (
        jest_block
    )
    assert "process.communicate.assert_awaited_once_with()" in jest_block

    assert "def _assert_spawn_call" in playwright_runner_test
    assert 'assert call_args.kwargs == {' in playwright_runner_test
    assert 'assert set(call_args.kwargs)' not in playwright_runner_test
    assert "mock_exec.assert_awaited_once()" in playwright_block
    assert "call_args = mock_exec.await_args" in playwright_block
    assert 'self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")' in (
        playwright_block
    )
    assert "process.communicate.assert_awaited_once_with()" in playwright_block
    assert "assert result.exit_code == 0" in playwright_block


def test_quality_ops_capture_js_runner_failure_subprocess_exact_contract():
    row = _quality_ops_row_containing(
        "Jest/Playwright failure subprocess exact 契约"
    )
    jest_runner_test = _read(JEST_RUNNER_TEST)
    playwright_runner_test = _read(PLAYWRIGHT_RUNNER_TEST)

    assert "Jest/Playwright failure subprocess exact 契约" in row
    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestRunTests::test_run_with_failures tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightRunTests::test_run_tests_with_failures` 2 passed"
        in row
    )
    assert "jest/playwright runner full 57 passed" in row
    assert "release quality docs contract full 170 passed" in row
    assert "subprocess 完整 argv、cwd、stdout/stderr pipe" in row
    assert "非零 exit code 与失败计数/输出被保留" in row
    assert "此前预先写好 JUnit XML 后只断言解析结果" in row
    assert "runner 命令漂移、cwd 指错、JUnit env 未指向同一个报告路径" in (
        row
    )
    assert "失败路径测试只证明“能解析一个预置失败报告”" in row

    jest_block = _marked_block(
        jest_runner_test,
        "async def test_run_with_failures",
        "async def test_missing_junit_xml_returns_zeros",
    )
    playwright_block = _marked_block(
        playwright_runner_test,
        "async def test_run_tests_with_failures",
        "async def test_run_tests_with_skipped",
    )

    assert "mock_exec.assert_awaited_once()" in jest_block
    assert "call_args = mock_exec.await_args" in jest_block
    assert 'self._assert_spawn_call(call_args, tmp_path, "junit.xml")' in jest_block
    assert 'assert set(call_args.kwargs)' not in jest_block
    assert "process.communicate.assert_awaited_once_with()" in jest_block
    assert "assert result.exit_code == 1" in jest_block
    assert 'assert result.stdout == "FAIL"' in jest_block

    assert "mock_exec.assert_awaited_once()" in playwright_block
    assert "call_args = mock_exec.await_args" in playwright_block
    assert 'self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")' in (
        playwright_block
    )
    assert 'assert set(call_args.kwargs)' not in playwright_block
    assert "process.communicate.assert_awaited_once_with()" in playwright_block
    assert "assert result.exit_code == 1" in playwright_block
    assert 'assert result.stdout == "1 failed, 1 passed"' in playwright_block


def test_quality_ops_capture_js_runner_env_subprocess_exact_contract():
    row = _quality_ops_row_containing(
        "Jest/Playwright env subprocess exact 契约"
    )
    jest_runner_test = _read(JEST_RUNNER_TEST)
    playwright_runner_test = _read(PLAYWRIGHT_RUNNER_TEST)

    assert "Jest/Playwright env subprocess exact 契约" in row
    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestRunTests::test_env_vars_passed_through tests/unit/test_plugins/test_jest_runner.py::TestJestRunTests::test_junit_xml_config_wins_over_env_var tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightRunTests::test_run_tests_with_env_vars tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightRunTests::test_junit_xml_config_wins_over_env_var` 4 passed"
        in row
    )
    assert "jest/playwright runner full 57 passed" in row
    assert "release quality docs contract full 178 passed" in row
    assert "subprocess 完整 argv、cwd、stdout/stderr pipe" in row
    assert "runner 专属 JUnit env 覆盖值" in row
    assert "`process.communicate()` await" in row
    assert "此前只断言 `mock_exec.assert_awaited_once()` 后抽查 env" in (
        row
    )
    assert "Jest/Playwright 命令漂移" in row
    assert "JS runner env 测试只证明“env 字段看起来对”" in row

    jest_env_block = _marked_block(
        jest_runner_test,
        "async def test_env_vars_passed_through",
        "async def test_junit_xml_config_wins_over_env_var",
    )
    jest_config_block = _marked_block(
        jest_runner_test,
        "async def test_junit_xml_config_wins_over_env_var",
        "class TestJestRegistration",
    )

    playwright_env_block = _marked_block(
        playwright_runner_test,
        "async def test_run_tests_with_env_vars",
        "async def test_junit_xml_config_wins_over_env_var",
    )
    playwright_config_block = _marked_block(
        playwright_runner_test,
        "async def test_junit_xml_config_wins_over_env_var",
        "class TestPlaywrightJUnitParsing",
    )

    assert "import asyncio" in jest_runner_test
    for block in (jest_env_block, jest_config_block):
        assert "mock_exec.assert_awaited_once()" in block
        assert "call_args = mock_exec.await_args" in block
        assert "self._assert_spawn_call(call_args, tmp_path," in block
        assert "assert set(call_args.kwargs)" not in block
        assert "process.communicate.assert_awaited_once_with()" in block
        assert "kwargs = mock_exec.await_args.kwargs" not in block
    assert 'env = self._assert_spawn_call(call_args, tmp_path, "junit.xml")' in (
        jest_env_block
    )
    assert 'assert env["NODE_ENV"] == "test"' in jest_env_block
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in jest_env_block
    assert (
        'self._assert_spawn_call(call_args, tmp_path, "configured.xml")'
        in jest_config_block
    )
    assert "assert result.passed == 2" in jest_config_block

    assert "import asyncio" in playwright_runner_test
    for block in (playwright_env_block, playwright_config_block):
        assert "mock_exec.assert_awaited_once()" in block
        assert "call_args = mock_exec.await_args" in block
        assert "self._assert_spawn_call(call_args, tmp_path," in block
        assert "assert set(call_args.kwargs)" not in block
        assert "process.communicate.assert_awaited_once_with()" in block
        assert "kwargs = mock_exec.await_args.kwargs" not in block
    assert 'env = self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")' in (
        playwright_env_block
    )
    assert 'assert env["BASE_URL"] == "http://localhost:3000"' in playwright_env_block
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in playwright_env_block
    assert 'self._assert_spawn_call(call_args, tmp_path, "custom.xml")' in (
        playwright_config_block
    )
    assert "assert result.passed == 2" in playwright_config_block


def test_quality_ops_capture_js_runner_success_subprocess_exact_contract():
    row = _quality_ops_row_containing(
        "Jest/Playwright success subprocess exact 契约"
    )
    jest_runner_test = _read(JEST_RUNNER_TEST)
    playwright_runner_test = _read(PLAYWRIGHT_RUNNER_TEST)

    assert "Jest/Playwright success subprocess exact 契约" in row
    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestRunTests::test_run_success tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightRunTests::test_run_tests_success` 2 passed"
        in row
    )
    assert "jest/playwright runner full 57 passed" in row
    assert "release quality docs contract full 180 passed" in row
    assert "默认成功路径现在固定 subprocess 完整 argv" in row
    assert "默认 JUnit env 覆盖值" in row
    assert "stdout/stderr、exit code 和 pass/fail 计数" in row
    assert "此前只断言 `mock_exec.assert_awaited_once()` 后抽查默认 JUnit env" in (
        row
    )
    assert "命令少了 reporter" in row
    assert "JS runner happy path 测试只证明“能解析预置成功报告”" in (
        row
    )

    jest_block = _marked_block(
        jest_runner_test,
        "async def test_run_success",
        "async def test_run_with_failures",
    )
    playwright_block = _marked_block(
        playwright_runner_test,
        "async def test_run_tests_success",
        "async def test_run_tests_with_failures",
    )

    assert "import asyncio" in jest_runner_test
    assert "mock_exec.assert_awaited_once()" in jest_block
    assert "call_args = mock_exec.await_args" in jest_block
    assert 'self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")' in (
        jest_block
    )
    assert "assert set(call_args.kwargs)" not in jest_block
    assert "process.communicate.assert_awaited_once_with()" in jest_block
    assert 'assert result.stdout == "PASS"' in jest_block
    assert "kwargs = mock_exec.await_args.kwargs" not in jest_block

    assert "import asyncio" in playwright_runner_test
    assert "mock_exec.assert_awaited_once()" in playwright_block
    assert "call_args = mock_exec.await_args" in playwright_block
    assert 'self._assert_spawn_call(call_args, tmp_path, "results/junit.xml")' in (
        playwright_block
    )
    assert "assert set(call_args.kwargs)" not in playwright_block
    assert "process.communicate.assert_awaited_once_with()" in playwright_block
    assert "assert result.exit_code == 0" in playwright_block
    assert "kwargs = mock_exec.await_args.kwargs" not in playwright_block


def test_quality_ops_capture_pytest_go_runner_subprocess_kwargs_direct_helper_contract():
    pytest_runner_test = _read(PYTEST_RUNNER_TEST)
    go_runner_test = _read(GO_TEST_RUNNER_TEST)
    row = _quality_ops_row("|", contains="Pytest/Go runner subprocess kwargs direct helper 契约")

    assert (
        "`tests/unit/test_plugins/test_pytest_runner.py::TestPytestRunTests::test_env_vars_passed_through "
        "tests/unit/test_plugins/test_pytest_runner.py::TestPytestRunTests::test_working_dir_passed_through "
        "tests/unit/test_plugins/test_go_test_runner.py::TestGoTestRunTests::test_env_vars_passed_through` "
        "3 passed"
    ) in row
    assert "pytest runner full 45 passed" in row
    assert "go runner full 34 passed" in row
    assert "release quality docs contract full 342 passed" in row
    assert "targeted ruff passed" in row
    assert "`cwd/stdout/stderr/env` kwargs 等值" in row
    assert "旧的 `assert set(call_args.kwargs)` 字符串" in row
    assert "kwargs key 集合看起来对" in row

    for runner_test, expected_args in (
        (
            pytest_runner_test,
            ('"python"', '"-m"', '"pytest"', '"--junitxml=results/junit.xml"', '"tests"'),
        ),
        (go_runner_test, ('"go"', '"test"', '"-v"', '"-json"', '"./..."')),
    ):
        helper_block = _block_between(runner_test, "def _assert_spawn_call", "\n\n    @pytest.mark.asyncio")
        assert "assert call_args.args == (" in helper_block
        for expected_arg in expected_args:
            assert expected_arg in helper_block
        assert "env = call_args.kwargs[\"env\"]" in helper_block
        assert "assert call_args.kwargs == {" in helper_block
        assert '"cwd": str(tmp_path)' in helper_block
        assert '"stdout": asyncio.subprocess.PIPE' in helper_block
        assert '"stderr": asyncio.subprocess.PIPE' in helper_block
        assert '"env": env' in helper_block
        assert "assert set(call_args.kwargs)" not in runner_test

    assert "env = self._assert_spawn_call(call_args, tmp_path)" in pytest_runner_test
    assert 'assert env["PYTHONDONTWRITEBYTECODE"] == "1"' in pytest_runner_test
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in pytest_runner_test
    assert "assert env is None" in pytest_runner_test
    assert "env = self._assert_spawn_call(call_args, tmp_path)" in go_runner_test
    assert 'assert env["CGO_ENABLED"] == "0"' in go_runner_test
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in go_runner_test


def test_quality_ops_capture_pytest_run_tests_subprocess_env_cwd_exact_contract():
    row = _quality_ops_row_containing(
        "Pytest run_tests subprocess env/cwd exact 契约"
    )
    pytest_runner_test = _read(PYTEST_RUNNER_TEST)

    assert "Pytest run_tests subprocess env/cwd exact 契约" in row
    assert (
        "`tests/unit/test_plugins/test_pytest_runner.py::TestPytestRunTests::test_env_vars_passed_through tests/unit/test_plugins/test_pytest_runner.py::TestPytestRunTests::test_working_dir_passed_through` 2 passed"
        in row
    )
    assert "pytest runner full 45 passed" in row
    assert "release quality docs contract full 173 passed" in row
    assert "subprocess 完整 argv、cwd、stdout/stderr pipe" in row
    assert "env 覆盖/None 分支" in row
    assert "`process.communicate()` 被 await 后才返回" in row
    assert "此前只断言 `mock_exec.assert_awaited_once()` 后抽查 env 或 cwd" in (
        row
    )
    assert "实现丢掉 `--junitxml`" in row
    assert "pytest run_tests 测试只证明“env 或 cwd 字段看起来对”" in (
        row
    )

    env_block = _marked_block(
        pytest_runner_test,
        "async def test_env_vars_passed_through",
        "async def test_working_dir_passed_through",
    )
    cwd_block = _marked_block(
        pytest_runner_test,
        "async def test_working_dir_passed_through",
        "class TestPytestRegistration",
    )
    helper_block = _marked_block(
        pytest_runner_test,
        "def _assert_spawn_call",
        "@pytest.mark.asyncio",
    )

    assert "import asyncio" in pytest_runner_test
    assert "assert call_args.args == (" in helper_block
    assert '"python"' in helper_block
    assert '"-m"' in helper_block
    assert '"pytest"' in helper_block
    assert '"--junitxml=results/junit.xml"' in helper_block
    assert '"tests"' in helper_block
    assert 'env = call_args.kwargs["env"]' in helper_block
    assert "assert call_args.kwargs == {" in helper_block
    assert '"cwd": str(tmp_path)' in helper_block
    assert '"stdout": asyncio.subprocess.PIPE' in helper_block
    assert '"stderr": asyncio.subprocess.PIPE' in helper_block
    assert '"env": env' in helper_block
    assert "return env" in helper_block
    assert "assert set(call_args.kwargs)" not in helper_block

    assert "mock_exec.assert_awaited_once()" in env_block
    assert "call_args = mock_exec.await_args" in env_block
    assert "env = self._assert_spawn_call(call_args, tmp_path)" in env_block
    assert 'assert env["PYTHONDONTWRITEBYTECODE"] == "1"' in env_block
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in env_block
    assert "assert set(call_args.kwargs)" not in env_block
    assert "process.communicate.assert_awaited_once_with()" in env_block

    assert "mock_exec.assert_awaited_once()" in cwd_block
    assert "call_args = mock_exec.await_args" in cwd_block
    assert "env = self._assert_spawn_call(call_args, tmp_path)" in cwd_block
    assert "assert env is None" in cwd_block
    assert "assert set(call_args.kwargs)" not in cwd_block
    assert "process.communicate.assert_awaited_once_with()" in cwd_block


def test_quality_ops_capture_go_run_tests_env_subprocess_exact_contract():
    row = _quality_ops_row_containing("Go run_tests env subprocess exact 契约")
    go_runner_test = _read(GO_TEST_RUNNER_TEST)

    assert "Go run_tests env subprocess exact 契约" in row
    assert (
        "`tests/unit/test_plugins/test_go_test_runner.py::TestGoTestRunTests::test_env_vars_passed_through` 1 passed"
        in row
    )
    assert "go runner full 34 passed" in row
    assert "release quality docs contract full 176 passed" in row
    assert "subprocess 完整 argv、cwd、stdout/stderr pipe" in row
    assert "env 覆盖值" in row
    assert "`process.communicate()` 被 await 后才写 JSON/JUnit" in row
    assert "此前只断言 `mock_exec.assert_awaited_once()` 后抽查 env" in (
        row
    )
    assert "实现丢掉 `-v -json ./...`" in row
    assert "Go runner env 测试只证明“env 字段看起来对”" in row

    env_block = _marked_block(
        go_runner_test,
        "async def test_env_vars_passed_through",
        "class TestGoTestRegistration",
    )
    helper_block = _marked_block(
        go_runner_test,
        "def _assert_spawn_call",
        "@pytest.mark.asyncio",
    )

    assert "import asyncio" in go_runner_test
    assert "assert call_args.args == (" in helper_block
    assert '"go"' in helper_block
    assert '"test"' in helper_block
    assert '"-v"' in helper_block
    assert '"-json"' in helper_block
    assert '"./..."' in helper_block
    assert 'env = call_args.kwargs["env"]' in helper_block
    assert "assert call_args.kwargs == {" in helper_block
    assert '"cwd": str(tmp_path)' in helper_block
    assert '"stdout": asyncio.subprocess.PIPE' in helper_block
    assert '"stderr": asyncio.subprocess.PIPE' in helper_block
    assert '"env": env' in helper_block
    assert "return env" in helper_block
    assert "assert set(call_args.kwargs)" not in helper_block

    assert "mock_exec.assert_awaited_once()" in env_block
    assert "call_args = mock_exec.await_args" in env_block
    assert "env = self._assert_spawn_call(call_args, tmp_path)" in env_block
    assert 'assert env["CGO_ENABLED"] == "0"' in env_block
    assert 'assert env["QAP_EXISTING_ENV"] == "kept"' in env_block
    assert "assert set(call_args.kwargs)" not in env_block
    assert "process.communicate.assert_awaited_once_with()" in env_block
    assert "kwargs = mock_exec.await_args.kwargs" not in env_block


def test_quality_ops_capture_js_runner_command_prefix_exact_helper_contract():
    jest_runner = _read(JEST_RUNNER_TEST)
    playwright_runner = _read(PLAYWRIGHT_RUNNER_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（JS runner command prefix exact helper 契约）")
    assert (
        "`tests/unit/test_plugins/test_jest_runner.py::TestJestBuildCommand "
        "tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightBuildCommand` 31 passed"
    ) in row
    assert "release quality docs contract full 281 passed" in row
    assert "targeted ruff passed" in row
    assert "把 `npx` 前缀拆出并完整等值断言" in row
    assert "JS runner command prefix exact helper 契约" in row
    assert "npx argv 对、前缀大概存在" in row

    for source, helper, env_name in [
        (jest_runner, "_jest_argv", "JEST_JUNIT_OUTPUT_FILE"),
        (playwright_runner, "_playwright_argv", "PLAYWRIGHT_JUNIT_OUTPUT_FILE"),
    ]:
        helper_block = _block_between(source, f"def {helper}", "\n\n    def test_default")
        assert "expected_prefix: str = (" in helper_block
        assert "prefix, tail = command.split(\" npx \", 1)" in helper_block
        assert "assert prefix == expected_prefix" in helper_block
        assert f"{env_name}=results/junit.xml" in helper_block
        assert "command.startswith" not in helper_block
        assert f'" {env_name}=" in command' not in helper_block

    assert '"cd /workspace && mkdir -p reports && "' in jest_runner
    assert "\"JEST_JUNIT_OUTPUT_FILE='reports/unit results.xml'\"" in jest_runner
    assert '"cd /workspace && mkdir -p out && "' in playwright_runner
    assert '"PLAYWRIGHT_JUNIT_OUTPUT_FILE=out/report.xml"' in playwright_runner
    assert '"cd /workspace && mkdir -p custom && "' in playwright_runner
    assert '"PLAYWRIGHT_JUNIT_OUTPUT_FILE=custom/junit.xml"' in playwright_runner


def test_quality_ops_capture_pytest_runner_shell_command_exact_helper_contract():
    pytest_runner = _read(PYTEST_RUNNER_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Pytest runner shell command exact helper 契约）")
    helper_block = _block_between(pytest_runner, "def _assert_command", "\n\n    def test_default_command")
    public_block = _block_between(pytest_runner, "class TestPytestBuildCommand:", "\n\nclass TestPytestBuildCommandInternal:")

    assert (
        "`tests/unit/test_plugins/test_pytest_runner.py::TestPytestBuildCommand` "
        "6 passed"
    ) in row
    assert "pytest runner full 45 passed" in row
    assert "release quality docs contract full 294 passed" in row
    assert "targeted ruff passed" in row
    assert "`command == \"cd /workspace && \" + shlex.quote(argv...)`" in row
    assert "带空格参数会还原为原 argv" in row
    assert '`startswith("cd /workspace && ")`' in row
    assert "前缀对且解析后 argv 大概对" in row

    assert 'expected_command = "cd /workspace && " + " ".join(' in helper_block
    assert "shlex.quote(part) for part in expected_argv" in helper_block
    assert "assert command == expected_command" in helper_block
    assert "assert shlex.split(command.removeprefix" in helper_block
    assert "command.startswith" not in helper_block

    assert public_block.count("self._assert_command(cmd, [") == 6
    assert '"not slow",' in public_block
    assert 'assert self._argv(cmd) == [' not in public_block
    assert "argv = self._argv(cmd)" not in public_block


def test_quality_ops_capture_go_runner_junit_failure_skip_exact_subtree_contract():
    go_test_runner = _read(GO_TEST_RUNNER_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Go runner JUnit failure/skip exact subtree 契约）")
    assert (
        "`tests/unit/test_plugins/test_go_test_runner.py::TestGoTestRunTests::test_run_with_failures "
        "tests/unit/test_plugins/test_go_test_runner.py::TestGoTestRunTests::test_run_with_skipped` 2 passed"
    ) in row
    assert "release quality docs contract full 280 passed" in row
    assert "targeted ruff passed" in row
    assert "`testsuites` 汇总、唯一 `testsuite` 属性、`testcase` classname/name/time" in row
    assert "Go runner JUnit failure/skip exact subtree 契约" in row
    assert "失败/跳过文本片段出现过" in row

    failure_block = _block_between(go_test_runner, "async def test_run_with_failures", "\n\n    @pytest.mark.asyncio")
    skipped_block = _block_between(go_test_runner, "async def test_run_with_skipped", "\n\n    @pytest.mark.asyncio")

    for expected in [
        'assert root.tag == "testsuites"',
        "assert root.attrib == {",
        'suite = root.find("./testsuite")',
        "assert suite is not None",
        "assert suite.attrib == {",
        "assert list(",
    ]:
        assert expected in failure_block
        assert expected in skipped_block

    for expected in [
        'passed.attrib == {"classname": "pkg", "name": "TestFoo", "time": "0.100000"}',
        'failed.attrib == {"classname": "pkg", "name": "TestBar", "time": "0.200000"}',
        "assert list(failed) == [failure]",
        'assert failure.attrib == {"message": "go test failed"}',
        'assert failure.text == "--- FAIL: TestBar"',
    ]:
        assert expected in failure_block

    for expected in [
        'assert testcase.attrib == {\n            "classname": "pkg",\n            "name": "TestSkip",\n            "time": "0.000000",\n        }',
        "assert list(testcase) == [skipped]",
        'assert skipped.attrib == {"message": "go test skipped"}',
        'assert skipped.text == "--- SKIP: TestSkip"',
    ]:
        assert expected in skipped_block

    assert 'assert "--- FAIL: TestBar" in (failure.text or "")' not in failure_block
    assert 'assert "--- SKIP: TestSkip" in (skipped.text or "")' not in skipped_block


def test_quality_ops_capture_plugin_registry_discover_failure_exact_contract():
    plugin_registry_test = _read(PLUGIN_REGISTRY_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Plugin registry discover failure exact continuation 契约）"
    )

    assert "Plugin registry discover failure exact continuation 契约" in row
    assert (
        "`tests/unit/test_plugins/test_registry.py::test_discover_registers_loadable_entry_points_and_continues_after_failures` 1 passed"
        in row
    )
    assert "plugin registry full 7 passed" in row
    assert "release quality docs contract full 212 passed" in row
    assert "targeted ruff passed" in row
    assert '`entry_points(group="qaplatform.plugins")`' in row
    assert "两个 entry point 都只 load 一次" in row
    assert "broken 只记录 ERROR 且不污染 registry" in row
    assert "runner 继续注册为唯一 runner" in row
    assert "此前只证明失败后仍能 `get_runner" in row
    assert "discovery group 漂移" in row
    assert "失败污染 collector/source registry" in row
    assert "只证明“某个可用插件最后能取到”" in row

    for expected in [
        "import logging",
        "self.load_calls = 0",
        "self.load_calls += 1",
        "def test_discover_registers_loadable_entry_points_and_continues_after_failures(",
        "caplog,",
        "as entry_points_mock:",
        'with caplog.at_level(logging.INFO, logger="qaplatform.plugins.registry"):',
        'entry_points_mock.assert_called_once_with(group="qaplatform.plugins")',
        "assert [ep.load_calls for ep in entry_points] == [1, 1]",
        'assert registry.runner_names == ["dummy-runner"]',
        "assert registry.collector_names == []",
        "assert registry.source_names == []",
        'runner = registry.get_runner("dummy-runner")',
        "assert isinstance(runner, DummyRunner)",
        'assert runner.name == "dummy-runner"',
        "assert [(record.levelno, record.getMessage()) for record in caplog.records] == [",
        '(logging.ERROR, "failed to load plugin entry point: broken")',
        '(logging.INFO, "registered runner plugin: dummy-runner")',
        '(logging.INFO, "discovered external plugin: runner (pkg:Runner)")',
    ]:
        assert expected in plugin_registry_test
    assert 'assert registry.get_runner("dummy-runner").name == "dummy-runner"' not in (
        plugin_registry_test
    )
