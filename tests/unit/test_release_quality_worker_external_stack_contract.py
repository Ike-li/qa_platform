from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _block_between,
    _quality_ops_row,
    _quality_ops_row_containing,
    _quality_ops_rows_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
BACKEND_TEST_AUDIT = ROOT / "docs" / "backend-test-audit.md"
TESTING_STRATEGY = ROOT / "docs" / "testing-strategy.md"
WORKER_EXECUTE = ROOT / "tests" / "integration" / "test_worker_execute.py"


def test_worker_external_stack_creation_assertions_are_exact():
    worker_execute = _read(WORKER_EXECUTE)
    quality_ops = _quality_ops_row_containing(
        "external-stack worker 创建/触发请求精确断言 201"
    )
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)

    assert "status_code in (200, 201)" not in worker_execute
    assert "project_resp.status_code == 201" in worker_execute
    assert "env_resp.status_code == 201" in worker_execute
    assert "pipeline_resp.status_code == 201" in worker_execute
    assert "trigger_resp.status_code == 201" in worker_execute
    assert "external-stack worker 创建/触发请求精确断言 201" in quality_ops
    assert "external-stack worker 创建/触发请求固定断言 201" in (
        testing_strategy
    )
    assert "external-stack worker 创建/触发请求精确断言 201" in backend_audit


def test_quality_ops_capture_worker_external_stack_artifact_names_exact_contract():
    worker_execute = _read(WORKER_EXECUTE)
    quality_ops = _quality_ops_rows_containing(
        "external-stack worker 多 artifact 读面",
        "artifact projection exact contract",
    )

    assert "external-stack worker 多 artifact 读面" in quality_ops
    assert "管理员 JWT 与 `run.read` token 只能看到 JUnit/HTML/log/Allure" in (
        quality_ops
    )
    assert "artifact 名称精确集合" in quality_ops
    assert "artifact projection exact contract" in quality_ops
    assert "完整 `{name,type,storage_path}` 列表" in quality_ops
    assert "def _artifact_projection(body: dict) -> list[dict[str, str]]:" in (
        worker_execute
    )
    assert "def _artifact_page_projection(body: dict) -> dict:" in worker_execute
    assert "assert _artifact_page_projection(artifacts_body) == expected_artifact_page" in (
        worker_execute
    )
    assert "assert _artifact_page_projection(token_artifacts_body) == expected_artifact_page" in (
        worker_execute
    )
    assert 'assert artifacts_body["total"] == len(expected_artifacts)' not in (
        worker_execute
    )
    assert 'assert token_artifacts_body["total"] == len(expected_artifacts)' not in (
        worker_execute
    )
    assert "assert set(artifacts_by_name) == set(expected_artifacts)" not in (
        worker_execute
    )
    assert "assert set(token_artifacts_by_name) == set(expected_artifacts)" not in (
        worker_execute
    )
    assert "expected_artifacts.keys() <= artifacts_by_name.keys()" not in (
        worker_execute
    )
    assert "expected_artifacts.keys() <= token_artifacts_by_name.keys()" not in (
        worker_execute
    )


def test_quality_ops_capture_worker_artifact_page_projection_followup_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
            "tests/integration/test_worker_execute.py::test_external_stack_worker_e2e_slo_smoke "
            "tests/integration/test_worker_execute.py::test_real_worker_persists_artifacts_and_archived_logs "
            "-q -rs` 2 skipped")

    assert "worker_execute full 8 skipped" in row
    assert "release quality docs contract targeted 4 passed" in row
    assert "release quality docs contract full 356 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "pending" not in row
    assert "`_artifact_page_projection` 锁住 `data/page/per_page/total`" in row
    assert "artifact page projection exact 契约" in row
    assert "外部栈 readiness" in row

    slo_block = _block_between(worker_execute, "async def test_external_stack_worker_e2e_slo_smoke", "\n\n@pytest.mark.asyncio")
    persist_block = _block_between(worker_execute, "async def test_real_worker_persists_artifacts_and_archived_logs", "\n\n@pytest.mark.asyncio")

    for expected in [
        "def _artifact_page_projection(body: dict) -> dict:",
        '"data": _artifact_projection(body)',
        '"page": body["page"]',
        '"per_page": body["per_page"]',
        '"total": body["total"]',
    ]:
        assert expected in worker_execute
    for expected in [
        "expected_artifact_projection = sorted(",
        "assert _artifact_page_projection(artifacts_body) == {",
        '"page": 1',
        '"per_page": 20',
        '"total": 2',
    ]:
        assert expected in slo_block
    for expected in [
        "expected_artifact_projection = sorted(",
        "expected_artifact_page = {",
        '"page": 1',
        '"per_page": 20',
        '"total": 4',
        "assert _artifact_page_projection(artifacts_body) == expected_artifact_page",
        "assert _artifact_page_projection(token_artifacts_body) == expected_artifact_page",
    ]:
        assert expected in persist_block
    for rejected in [
        'assert artifacts_body["total"] == len(expected_artifacts)',
        'assert token_artifacts_body["total"] == len(expected_artifacts)',
        "assert _artifact_projection(token_artifacts_body) == sorted(",
    ]:
        assert rejected not in worker_execute


def test_quality_ops_capture_worker_archive_exact_line_read_scope_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="external-stack worker archive exact line/read-scope 契约")
    persist_block = _block_between(worker_execute, "async def test_real_worker_persists_artifacts_and_archived_logs", "async def test_worker_lost_retry_completes_with_artifacts_and_archived_logs")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "管理员 JWT 与 `run.read` token" in row
    assert "均按预期出现且只出现一次" in row
    assert "只证明“几个关键片段大概出现过”" in row

    for expected in [
        "def _assert_line_once(lines: list[str], expected_line: str) -> None:",
        "_assert_line_once(lines, expected_line)",
        "_assert_line_once(token_lines, expected_line)",
        'redacted_stdout_line = "active stdout secret: [REDACTED]"',
        'redacted_stderr_line = "active stderr secret: [REDACTED]"',
        'redacted_bulk_line = f"{bulk_marker}-1001 active bulk secret: [REDACTED]"',
        '"Repository cloned successfully"',
        '*(f"Uploaded artifact: {artifact_name}" for artifact_name in expected_artifacts)',
        '"Skipped artifact zz-over-limit.txt: artifact count limit exceeded"',
        '"Run completed: done"',
    ]:
        assert expected in worker_execute

    for removed in [
        'assert any("Repository cloned successfully" in line for line in lines)',
        'assert any(f"Uploaded artifact: {artifact_name}" in line for line in lines)',
        'assert any("Run completed: done" in line for line in lines)',
        'assert any("Repository cloned successfully" in line for line in token_lines)',
        'assert any("Run completed: done" in line for line in token_lines)',
        '"Skipped artifact zz-over-limit.txt: artifact count limit exceeded" in line',
    ]:
        assert removed not in persist_block


def test_quality_ops_capture_worker_archive_page_projection_followup_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
            "tests/integration/test_worker_execute.py::test_real_worker_persists_artifacts_and_archived_logs "
            "-q -rs` 1 skipped")
    persist_block = _block_between(worker_execute, "async def test_real_worker_persists_artifacts_and_archived_logs", "async def test_worker_lost_retry_completes_with_artifacts_and_archived_logs")

    assert "worker_execute full 8 skipped" in row
    assert "release quality docs contract targeted 3 passed" in row
    assert "release quality docs contract full 357 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "pending" not in row
    assert "`_archive_page_projection` 固定两页 `{page,per_page,total,data_count}`" in (
        row
    )
    assert "archive page projection exact 契约" in row
    assert "`len(body.get(\"data\", [])) == 1000` 继续作为第一页填满的外部栈 readiness" in (
        row
    )

    for expected in [
        "def _archive_page_projection(body: dict) -> dict[str, int]:",
        '"page": body["page"]',
        '"per_page": body["per_page"]',
        '"total": body["total"]',
        '"data_count": len(body["data"])',
    ]:
        assert expected in worker_execute
    for expected in [
        "expected_archive_pages = [",
        '"total": len(lines)',
        '"data_count": len(lines) - 1000',
        "_archive_page_projection(archive_body)",
        "_archive_page_projection(archive_tail_body)",
        "_archive_page_projection(token_archive_body)",
        "_archive_page_projection(token_archive_tail_body)",
        "] == expected_archive_pages",
    ]:
        assert expected in persist_block
    for rejected in [
        'assert archive_body["page"] == 1',
        'assert archive_body["per_page"] == 1000',
        'assert archive_tail_body["page"] == 2',
        'assert archive_tail_body["per_page"] == 1000',
        'assert token_archive_body["page"] == 1',
        'assert token_archive_body["per_page"] == 1000',
        'assert token_archive_tail_body["page"] == 2',
        'assert token_archive_tail_body["per_page"] == 1000',
        'assert token_archive_tail_body["total"] == token_archive_body["total"]',
    ]:
        assert rejected not in persist_block


def test_quality_ops_capture_worker_retry_priority_archive_exact_line_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="worker retry/priority archive exact line 契约")
    lost_block = _block_between(worker_execute, "async def test_worker_lost_retry_completes_with_artifacts_and_archived_logs", "async def test_priority_queues_wait_for_matching_external_workers_then_finish")
    priority_block = _block_between(worker_execute, "async def test_priority_queues_wait_for_matching_external_workers_then_finish", "async def test_worker_clone_and_setup_failures_do_not_retry_or_leak_external_stack")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`Repository cloned successfully`" in row
    assert "`Uploaded artifact: junit.xml`" in row
    assert "`Run completed: done`" in row
    assert "只证明“归档里有三个熟悉短语”" in row

    for block in (lost_block, priority_block):
        for expected in [
            '"Repository cloned successfully"',
            '"Uploaded artifact: junit.xml"',
            '"Run completed: done"',
            "_assert_line_once(lines, expected_line)",
            "_assert_line_once(token_lines, expected_line)",
        ]:
            assert expected in block
        for removed in [
            'assert any("Repository cloned successfully" in line for line in lines)',
            'assert any("Uploaded artifact: junit.xml" in line for line in lines)',
            'assert any("Run completed: done" in line for line in lines)',
            'assert any("Repository cloned successfully" in line for line in token_lines)',
            'assert any("Uploaded artifact: junit.xml" in line for line in token_lines)',
            'assert any("Run completed: done" in line for line in token_lines)',
        ]:
            assert removed not in block


def test_quality_ops_capture_worker_10_container_exact_final_statuses_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="worker 10-container exact final statuses 契约")
    test_block = _block_between(worker_execute, "async def test_external_stack_worker_e2e_slo_smoke", "async def test_real_worker_persists_artifacts_and_archived_logs")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert '`final_statuses == {run_id: "done" for run_id in run_id_set}`' in row
    assert "不再分开断 key 集合与 `all(status == \"done\")`" in row
    assert "只证明“所有状态看起来都是 done”" in row

    assert 'expected_final_statuses = {run_id: "done" for run_id in run_id_set}' in (
        test_block
    )
    assert "assert final_statuses == expected_final_statuses" in test_block
    assert "assert set(final_statuses) == run_ids" not in test_block
    assert 'assert all(status == "done" for status in final_statuses.values())' not in (
        test_block
    )


def test_quality_ops_capture_worker_10_container_run_id_running_direct_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="worker 10-container run-id/running direct projection 契约")
    test_block = _block_between(worker_execute, "async def test_external_stack_worker_e2e_slo_smoke", "async def test_real_worker_persists_artifacts_and_archived_logs")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "重复 id 列表为空" in row
    assert "`running_count == run_count`" in row
    assert "只证明“数量至少够了”" in row

    for expected in [
        "run_ids: list[str] = []",
        'run_ids.append(body["id"])',
        "duplicate_run_ids = sorted(",
        "assert duplicate_run_ids == []",
        "run_id_set = set(run_ids)",
        "_wait_for_running_qaplatform_container_count(\n        run_id_set,",
        "assert running_count == run_count",
        'expected_final_statuses = {run_id: "done" for run_id in run_id_set}',
    ]:
        assert expected in test_block
    assert "assert len(run_ids) == run_count" not in test_block
    assert "assert running_count >= run_count" not in test_block


def test_quality_ops_capture_worker_external_stack_poll_predicates_are_targeted():
    worker_execute = _read(WORKER_EXECUTE)
    quality_ops = _quality_ops_rows_containing(
        "external-stack worker 的 artifact/log 轮询现在改为目标内容驱动",
        "`run.read` token artifact 响应也固定为精确单项 `junit.xml`",
    )

    assert "external-stack worker 的 artifact/log 轮询现在改为目标内容驱动" in (
        quality_ops
    )
    assert "不再用 `body[\"total\"] >= ...` 提前通过" in quality_ops
    assert "`run.read` token artifact 响应也固定为精确单项 `junit.xml`" in (
        quality_ops
    )
    assert "避免 external-stack 测试只证明“已经有点数据”" in quality_ops
    assert "def _has_exact_artifact_names(*expected_names: str):" in worker_execute
    assert "def _archive_contains_all(*fragments: str):" in worker_execute
    assert '_has_exact_artifact_names("junit.xml")' in worker_execute
    assert 'assert token_artifact_names == ["junit.xml"]' in worker_execute
    assert '_archive_contains_all("Starting stage: test", "Run completed: done")' in (
        worker_execute
    )
    assert (
        '_archive_contains_all(start_marker, end_marker, "Run completed: done")'
        in worker_execute
    )
    assert (
        'lambda body: body["total"] >= 1' not in worker_execute
    )
    assert (
        'lambda body: body["total"] >= 4' not in worker_execute
    )
    assert "token_junit_artifacts" not in worker_execute
    assert 'if artifact["name"] == "junit.xml"' not in worker_execute


def test_quality_ops_capture_worker_pytest_package_archive_exact_line_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="external-stack pytest package archive exact line 契约")
    test_block = _block_between(worker_execute, "async def test_trigger_run_completes_terminal_state", "\n\n@pytest.mark.asyncio")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`Starting stage: test` 与 `Run completed: done`" in row
    assert "精确日志行且各出现一次" in row
    assert "只证明“归档里有两个看起来像关键字的片段”" in row

    for expected in [
        'assert [line for line in archive_lines if line == "Starting stage: test"] == [',
        '"Starting stage: test"',
        'assert [line for line in archive_lines if line == "Run completed: done"] == [',
        '"Run completed: done"',
    ]:
        assert expected in test_block
    assert 'assert any("Starting stage: test" in line for line in archive_lines)' not in (
        test_block
    )
    assert 'assert any("Run completed: done" in line for line in archive_lines)' not in (
        test_block
    )


def test_quality_ops_capture_worker_live_sse_exact_marker_sequence_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="external-stack worker live SSE exact marker sequence direct projection 契约")
    live_block = _block_between(worker_execute, "async def test_real_worker_streams_live_logs_over_sse_external_stack", "\n\n@pytest.mark.asyncio")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "start marker 在首段 SSE 中用 `[_sse_log_line(event) ...] == [start_marker]`" in row
    assert "单元素解包 marker event" in row
    assert "resume 后 start marker 精确不重放" in row
    assert "归档日志中 start/end/`Run completed: done` 也分别精确出现一次" in row
    assert "后来仍用 `len(first_marker_events) == 1` 加 `[0]`" in row
    assert "external-stack worker live SSE exact marker sequence direct projection 契约" in row
    assert "只证明“日志里大概出现过这些片段”" in row

    for expected in [
        'assert "Starting stage: pytest" in first_lines',
        "first_marker_events = [",
        "if _sse_log_line(event) == start_marker",
        "assert [_sse_log_line(event) for event in first_marker_events] == [start_marker]",
        "(first_marker_event,) = first_marker_events",
        "replayed_start_markers = [line for line in second_lines if line == start_marker]",
        "assert replayed_start_markers == []",
        "end_marker_lines = [line for line in second_lines if line == end_marker]",
        "assert end_marker_lines == [end_marker]",
        "assert [line for line in archive_lines if line == start_marker] == [start_marker]",
        "assert [line for line in archive_lines if line == end_marker] == [end_marker]",
        'assert [line for line in archive_lines if line == "Run completed: done"] == [',
    ]:
        assert expected in live_block
    assert "assert all(start_marker not in line for line in second_lines)" not in (
        live_block
    )
    assert "assert any(end_marker in line for line in second_lines)" not in live_block
    assert "assert any(start_marker in line for line in archive_lines)" not in (
        live_block
    )
    assert "assert len(first_marker_events) == 1" not in live_block
    assert "first_marker_events[0]" not in live_block


def test_quality_ops_capture_worker_slo_exact_marker_archive_sequence_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="external-stack worker SLO exact marker/archive sequence 契约")
    slo_block = _block_between(worker_execute, "async def test_external_stack_worker_e2e_slo_smoke", "\n\n@pytest.mark.external_stack")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "首个 live SSE 中 `Starting stage: pytest`" in row
    assert "`done_marker` 与 `Run completed: done` 的精确行集合" in row
    assert "三条关键日志各出现一次" in row
    assert "只证明“关键日志片段大概出现过”" in row

    for expected in [
        'assert "Starting stage: pytest" in first_lines',
        "assert [line for line in first_lines if line == first_marker] == [first_marker]",
        'lambda body: {done_marker, "Run completed: done"}.issubset(',
        '{entry["line"] for entry in body["data"]}',
        "assert [line for line in archive_lines if line == first_marker] == [first_marker]",
        "assert [line for line in archive_lines if line == done_marker] == [done_marker]",
        'assert [line for line in archive_lines if line == "Run completed: done"] == [',
    ]:
        assert expected in slo_block
    assert 'assert any("Starting stage: pytest" in line for line in first_lines)' not in (
        slo_block
    )
    assert "done_marker in entry[\"line\"] or \"Run completed: done\" in entry[\"line\"]" not in (
        slo_block
    )
    assert "assert any(first_marker in line for line in archive_lines)" not in (
        slo_block
    )
    assert "assert any(done_marker in line for line in archive_lines)" not in (
        slo_block
    )


def test_quality_ops_capture_worker_failure_empty_artifact_exact_response_contract():
    worker_execute = _read(WORKER_EXECUTE)
    quality_ops = _quality_ops_row_containing(
        "external-stack worker clone/setup failure 的 artifact 空列表现在固定完整"
    )
    test_block = _after(
        worker_execute,
        "async def test_worker_clone_and_setup_failures_do_not_retry_or_leak_external_stack",
    )

    assert "external-stack worker clone/setup failure 的 artifact 空列表现在固定完整" in (
        quality_ops
    )
    assert "release quality docs contract full 249 passed" in quality_ops
    assert "避免 worker 失败路径只证明“没有 artifact 总数”" in quality_ops
    assert "assert clone_artifacts == {" in test_block
    assert "assert setup_artifacts == {" in test_block
    assert test_block.count('"data": []') >= 2
    assert test_block.count('"page": 1') >= 2
    assert test_block.count('"per_page": 20') >= 2
    assert test_block.count('"total": 0') >= 2
    assert 'clone_artifacts["total"] == 0' not in test_block
    assert 'setup_artifacts["total"] == 0' not in test_block


def test_quality_ops_capture_worker_failure_no_retry_direct_attempt_list_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="direct unexpected-attempt list 契约")
    helper_block = _block_between(worker_execute, "async def _assert_project_has_no_retry_runs", "def _host_reachable_presigned_request")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`unexpected_attempts == []`" in row
    assert "完整 observed attempts" in row
    assert "只证明“所有 attempt 看起来都是 1”" in row

    for expected in [
        "unexpected_attempts = [attempt for attempt in attempts if attempt != 1]",
        "assert unexpected_attempts == []",
        "unexpected_attempts={unexpected_attempts}; ",
        "observed_attempts={observed_attempts}",
    ]:
        assert expected in helper_block
    assert "assert all(attempt == 1 for attempt in attempts)" not in helper_block


def test_quality_ops_capture_worker_setup_failure_run_detail_exact_error_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` 8 tests collected", contains="setup failure run detail exact error 契约")
    failure_block = _after(
        worker_execute,
        "async def test_worker_clone_and_setup_failures_do_not_retry_or_leak_external_stack",
    )

    assert "release quality docs contract full 291 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert '`error_message == "Setup script failed (exit 1)"`' in row
    assert "`setup-boundary-failure` 只出现在归档日志读面" in row
    assert "setup stderr、调试信息或日志片段拼进 run detail" in row
    assert "只证明“错误短语出现过”" in row

    assert (
        'assert setup_detail.get("error_message") == "Setup script failed (exit 1)"'
        in failure_block
    )
    assert "serialized_setup_detail = json.dumps(" in failure_block
    assert 'assert "setup-boundary-failure" not in serialized_setup_detail' in (
        failure_block
    )
    assert '"Setup script failed (exit 1)" in (' not in failure_block
    assert '_archive_contains_all(' in failure_block
    assert '"setup-boundary-failure",' in failure_block
    assert 'assert any("setup-boundary-failure" in line for line in lines)' not in (
        failure_block
    )


def test_quality_ops_capture_worker_setup_failure_archive_exact_line_read_scope_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` "
            "8 tests collected", contains="external-stack setup failure archive exact line/read-scope 契约")
    failure_block = _after(
        worker_execute,
        "async def test_worker_clone_and_setup_failures_do_not_retry_or_leak_external_stack",
    )

    assert "release quality docs contract full 328 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "管理员 JWT 与 `run.read` token 读面" in row
    assert "`Repository cloned successfully`" in row
    assert "`Running setup script...`" in row
    assert "`setup-boundary-failure`" in row
    assert "每条必须只出现一次" in row
    assert "只证明“归档里大概出现过三段文本”" in row

    for expected in [
        'for expected_line in [',
        '"Repository cloned successfully",',
        '"Running setup script...",',
        '"setup-boundary-failure",',
        "_assert_line_once(lines, expected_line)",
        "_assert_line_once(setup_token_lines, expected_line)",
    ]:
        assert expected in failure_block

    for removed in [
        'assert any("Repository cloned successfully" in line for line in lines)',
        'assert any("Running setup script..." in line for line in lines)',
        'assert any("setup-boundary-failure" in line for line in lines)',
        'assert any("Repository cloned successfully" in line for line in setup_token_lines)',
        'assert any("Running setup script..." in line for line in setup_token_lines)',
        'assert any("setup-boundary-failure" in line for line in setup_token_lines)',
    ]:
        assert removed not in failure_block


def test_quality_ops_capture_worker_lost_original_error_exact_heartbeat_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` 8 tests collected", contains="external-stack worker_lost original error exact heartbeat 契约")
    lost_block = _block_between(worker_execute, "async def test_worker_lost_retry_completes_with_artifacts_and_archived_logs", "\n\n@pytest.mark.asyncio")

    assert "release quality docs contract full 293 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`worker_lost: heartbeat expired for `" in row
    assert "本轮删除的 Redis heartbeat key" in row
    assert "`worker-[0-9a-f]{8}`" in row
    assert "混入 debug context、指向错误 worker" in row
    assert "只证明“错误关键词出现过”" in row

    assert "import re" in worker_execute
    assert 'error_prefix = "worker_lost: heartbeat expired for "' in lost_block
    assert "assert error_message.startswith(error_prefix)" in lost_block
    assert "reclaimed_worker_id = error_message.removeprefix(error_prefix)" in (
        lost_block
    )
    assert "deleted_worker_ids = {" in lost_block
    assert 'key.removeprefix("worker:").removesuffix(":heartbeat")' in lost_block
    assert "assert reclaimed_worker_id in deleted_worker_ids" in lost_block
    assert (
        'assert re.fullmatch(r"worker-[0-9a-f]{8}", reclaimed_worker_id)'
        in lost_block
    )
    assert (
        'assert "worker_lost" in (original_detail.get("error_message") or "")'
        not in lost_block
    )


def test_quality_ops_capture_worker_external_stack_denied_exact_body_contract():
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_worker_execute.py --collect-only` 8 tests collected", contains="external-stack worker denied exact body 契约")
    live_block = _block_between(worker_execute, "async def test_real_worker_streams_live_logs_over_sse_external_stack", "\n\n@pytest.mark.asyncio")
    persist_block = _block_between(worker_execute, "async def test_real_worker_persists_artifacts_and_archived_logs", "\n\n@pytest.mark.asyncio")
    lost_block = _block_between(worker_execute, "async def test_worker_lost_retry_completes_with_artifacts_and_archived_logs", "\n\n@pytest.mark.asyncio")
    priority_block = _block_between(worker_execute, "async def test_priority_queues_wait_for_matching_external_workers_then_finish", "\n\n@pytest.mark.asyncio")
    failure_block = _after(
        worker_execute,
        "async def test_worker_clone_and_setup_failures_do_not_retry_or_leak_external_stack",
    )

    assert "external-stack worker denied exact body 契约" in row
    assert "release quality docs contract full 260 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`{\"detail\": \"Invalid or expired SSE ticket\"}`" in row
    assert "`{\"detail\": \"Insufficient permissions\"}`" in row
    assert "worker secret、artifact/log path、JUnit 内容、clone URL secret" in row
    assert "只证明“状态码拒绝且没明显泄漏片段”" in row

    for expected in [
        'assert no_ticket_resp.json() == {"detail": "Invalid or expired SSE ticket"}',
        'assert reuse_resp.json() == {"detail": "Invalid or expired SSE ticket"}',
        'assert denied_resp.json() == {"detail": "Insufficient permissions"}',
        "assert fragment not in denied_resp.text",
        "start_marker",
        "end_marker",
        'f"logs/{run_id}.jsonl"',
        'f"reports/{run_id}/"',
    ]:
        assert expected in live_block
    assert (
        "assert no_ticket_resp.status_code == 401, no_ticket_resp.text\n\n"
        not in live_block
    )
    assert (
        "assert reuse_resp.status_code == 401, reuse_resp.text\n\n"
        not in live_block
    )

    for block in (persist_block, lost_block, priority_block):
        assert (
            'assert response.json() == {"detail": "Insufficient permissions"}'
            in block
        )
        assert "for fragment in forbidden_fragments:" in block
        assert "assert fragment not in response.text" in block

    for expected in [
        "denied_detail_resp",
        "denied_project_detail_resp",
        "denied_live_resp",
        "denied_archive_resp",
        "denied_list_resp",
        "denied_download_responses",
        "worker-secret",
        "artifact count limit exceeded",
    ]:
        assert expected in persist_block

    for expected in [
        "denied_archive_resp",
        "denied_list_resp",
        "denied_download_resp",
        "worker-lost-retry",
        "<testsuite name='worker-lost-retry'",
    ]:
        assert expected in lost_block

    for expected in [
        "denied_archive_resp",
        "denied_list_resp",
        "denied_download_resp",
        "priority-queue",
        "<testsuite name='priority-queue'",
    ]:
        assert expected in priority_block

    for expected in [
        'assert clone_denied_archive_resp.json() == {"detail": "Insufficient permissions"}',
        'assert setup_denied_archive_resp.json() == {"detail": "Insufficient permissions"}',
        "secret,",
        '"x-access-token",',
        "missing_repo_url,",
        '"git clone failed",',
        "assert fragment not in clone_denied_archive_resp.text",
        '"setup-boundary-failure",',
        "assert fragment not in setup_denied_archive_resp.text",
    ]:
        assert expected in failure_block


def test_quality_ops_capture_external_stack_performance_artifact_exact_contract():
    worker_execute = _read(WORKER_EXECUTE)
    quality_ops = _quality_ops_row_containing(
        "external-stack performance smoke 现在固定 artifact total=2"
    )

    assert "external-stack performance smoke 现在固定 artifact total=2" in (
        quality_ops
    )
    assert "名称/类型/storage_path 必须精确等于 junit.xml 与 logs/e2e-slo.txt" in (
        quality_ops
    )
    assert "避免 SLO smoke 只证明关键 artifact 至少存在" in quality_ops
    assert '"logs/e2e-slo.txt": ("log", f"reports/{run_id}/logs/e2e-slo.txt")' in (
        worker_execute
    )
    assert 'lambda body: body["total"] == len(expected_artifacts)' in worker_execute
    assert "assert _artifact_page_projection(artifacts_body) == {" in (
        worker_execute
    )
    assert '"page": 1' in worker_execute
    assert '"per_page": 20' in worker_execute
    assert '"total": 2' in worker_execute
    assert "assert set(artifacts_by_name) == set(expected_artifacts)" not in (
        worker_execute
    )
    assert '{"junit.xml", "logs/e2e-slo.txt"} <= artifacts_by_name.keys()' not in (
        worker_execute
    )
