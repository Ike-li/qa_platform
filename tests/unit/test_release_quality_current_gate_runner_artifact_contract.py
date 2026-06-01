from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_runner_artifact_evidence():
    backend_junit_duplicate_row = _quality_ops_row(
        "| 2026-05-30 | N/A（backend integration JUnit 重复 nodeid 门禁）"
    )
    backend_junit_exact_errors_row = _quality_ops_row(
        "| 2026-05-31 | N/A（backend integration artifact validator 错误列表精确契约）"
    )
    runner_junit_parent_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Jest/Playwright JUnit parent 目录契约）"
    )
    runner_test_paths_row = _quality_ops_row(
        "| 2026-05-30 | N/A（内置 runner test_paths 工作区边界契约）"
    )
    go_runner_malformed_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Go runner malformed JSON/elapsed 容错契约）"
    )
    junit_duration_row = _quality_ops_row(
        "| 2026-05-30 | N/A（JUnit duration 输入容错契约）"
    )

    assert "`tests/unit/test_backend_integration_artifact_validator.py` 9 passed" in (
        backend_junit_duplicate_row
    )
    assert "targeted ruff passed" in backend_junit_duplicate_row
    assert "每个 JUnit testcase 必须且只能带一个 nodeid" in (
        backend_junit_duplicate_row
    )
    assert "拒绝重复 nodeid" in backend_junit_duplicate_row
    assert "testcase 数量与 nodeid 数量一致" in backend_junit_duplicate_row
    assert "原证据校验器只比较 collect/JUnit nodeid 集合" in (
        backend_junit_duplicate_row
    )
    assert "抓不到 JUnit 通过重复 testcase 膨胀通过数量" in (
        backend_junit_duplicate_row
    )
    assert "避免 backend integration 门禁只证明“集合覆盖了清单”" in (
        backend_junit_duplicate_row
    )
    assert "`tests/unit/test_backend_integration_artifact_validator.py` 9 passed" in (
        backend_junit_exact_errors_row
    )
    assert "targeted ruff passed" in backend_junit_exact_errors_row
    assert "targeted docs contract passed" in backend_junit_exact_errors_row
    assert "固定完整错误列表" in backend_junit_exact_errors_row
    assert "`startswith` / `any` / `in errors`" in backend_junit_exact_errors_row
    assert "升级为 `errors == [...]`" in backend_junit_exact_errors_row
    assert "避免 artifact validator 测试只证明“有个相似错误”" in (
        backend_junit_exact_errors_row
    )

    assert (
        "`tests/unit/test_plugins/test_jest_runner.py tests/unit/test_plugins/test_playwright_runner.py` 45 passed"
    ) in runner_junit_parent_row
    assert "coverage unit 1289 passed" in runner_junit_parent_row
    assert "自定义 `junit_xml`" in runner_junit_parent_row
    assert "subprocess 启动前创建 parent 目录" in runner_junit_parent_row
    assert "配置值覆盖外部 JUnit env var" in runner_junit_parent_row
    assert "既有 run_tests 用例都预先创建了 `results/`" in (runner_junit_parent_row)
    assert "绝对 `working_dir` 下 `if not junit_path.is_absolute()` 判断反向" in (
        runner_junit_parent_row
    )
    assert "避免 runner 测试只证明已有目录 happy path" in (runner_junit_parent_row)

    assert (
        "`tests/unit/test_plugins/test_pytest_runner.py tests/unit/test_plugins/test_jest_runner.py tests/unit/test_plugins/test_playwright_runner.py tests/unit/test_plugins/test_go_test_runner.py` 130 passed"
    ) in runner_test_paths_row
    assert "coverage unit 1323 passed" in runner_test_paths_row
    assert "pytest/jest/playwright/go runner" in runner_test_paths_row
    assert "`test_path`/`test_paths`" in runner_test_paths_row
    assert "拒绝绝对路径、`..` 越界路径、Windows 绝对路径和空白路径" in (
        runner_test_paths_row
    )
    assert "错误不回显原始路径" in runner_test_paths_row
    assert "只保护 JUnit/JSON 输出路径" in runner_test_paths_row
    assert "`/tmp`、`../secret`、Windows 绝对路径或空白路径" in runner_test_paths_row
    assert "26 个参数化红灯" in runner_test_paths_row
    assert "避免 runner 测试只证明报告路径不越界" in runner_test_paths_row

    assert "`tests/unit/test_plugins/test_go_test_runner.py` 34 passed" in (
        go_runner_malformed_row
    )
    assert (
        "`tests/unit/test_plugins/test_pytest_runner.py tests/unit/test_plugins/test_jest_runner.py tests/unit/test_plugins/test_playwright_runner.py tests/unit/test_plugins/test_go_test_runner.py` 136 passed"
    ) in go_runner_malformed_row
    assert "coverage unit 1329 passed" in go_runner_malformed_row
    assert "Go helper smoke passed" in go_runner_malformed_row
    assert "合法 JSON 但非 object" in go_runner_malformed_row
    assert "字符串/NaN/Infinity/负数 elapsed 统一归零" in go_runner_malformed_row
    assert "Python 本地路径和 worker shell helper" in go_runner_malformed_row
    assert "只覆盖 panic 这类非 JSON 行" in go_runner_malformed_row
    assert "`AttributeError`" in go_runner_malformed_row
    assert "负/非有限 JUnit duration" in go_runner_malformed_row
    assert "5 个红灯" in go_runner_malformed_row
    assert "避免 Go runner 测试只证明标准 go test NDJSON happy path" in (
        go_runner_malformed_row
    )

    assert "`tests/unit/test_plugins/test_junit_collector.py` 24 passed" in (
        junit_duration_row
    )
    assert "coverage unit 1287 passed" in junit_duration_row
    assert "空串、非数字、NaN、Infinity、负数统一归零" in junit_duration_row
    assert "保留 testcase 结果" in junit_duration_row
    assert "不让 collector 抛异常或写入负 duration" in junit_duration_row
    assert "malformed XML 和 missing time" in junit_duration_row
    assert "5 个参数化畸形 duration" in junit_duration_row
    assert "避免 JUnit collector 测试只证明 happy XML 和明显 parse error" in (
        junit_duration_row
    )
