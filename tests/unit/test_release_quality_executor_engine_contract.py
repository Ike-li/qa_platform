from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _marked_block_or_tail,
    _quality_ops_row,
    _quality_ops_row_containing,
    _quality_ops_rows_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
AUTO_RETRY_REAL_DB = ROOT / "tests" / "integration" / "test_auto_retry_real_db.py"
CANCEL_E2E = ROOT / "tests" / "integration" / "test_cancel_e2e.py"
DOCKER_BACKEND_TEST = ROOT / "tests" / "unit" / "test_engine" / "test_docker_backend.py"
EXECUTOR_REDACTION_TEST = (
    ROOT / "tests" / "unit" / "test_engine" / "test_executor_redaction.py"
)
EXECUTOR_TEST = ROOT / "tests" / "unit" / "test_engine" / "test_executor.py"
LIFESPAN_TEST = ROOT / "tests" / "unit" / "test_lifespan.py"
OOM_E2E = ROOT / "tests" / "integration" / "test_oom_e2e.py"
WORKER_RESOURCE_TERMINATION = (
    ROOT / "tests" / "integration" / "test_worker_resource_termination.py"
)


def test_quality_ops_capture_auto_retry_real_db_failure_exact_error_contract():
    auto_retry_real_db = _read(AUTO_RETRY_REAL_DB)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_auto_retry_real_db.py::test_execute_run_infra_exception_marks_failed_and_schedules_retry_real_db")

    assert "auto retry real DB failure exact error 契约" in row
    assert "auto_retry_real_db full 7 passed" in row
    assert "release quality docs contract full 292 passed" in row
    assert "Docker infra、setup create infra、setup script exit、clone URL userinfo 脱敏、worker_lost heartbeat" in row
    assert "错误消息只做关键词包含" in row
    assert "原始 URL userinfo" in row
    assert "只证明“失败原因大概出现过”" in row

    for expected in [
        'assert original_row.error_message == "docker daemon unavailable"',
        'assert original_row.error_message == "docker daemon unavailable during setup"',
        'assert original_row.error_message == "Setup script failed (exit 1)"',
        '== "git clone failed: https://***@example.invalid/org/repo.git"',
        'assert original_row.error_message == (\n        f"worker_lost: heartbeat expired for {worker_id}"',
    ]:
        assert expected in auto_retry_real_db

    for old_weak_assertion in [
        'assert "docker daemon unavailable" in original_row.error_message',
        'assert "docker daemon unavailable during setup" in (',
        'assert "Setup script failed (exit 1)" in (original_row.error_message or "")',
        'assert "git clone failed" in (original_row.error_message or "")',
        'assert "worker_lost" in (original_row.error_message or "")',
        "assert worker_id in (original_row.error_message or \"\")",
    ]:
        assert old_weak_assertion not in auto_retry_real_db


def test_quality_ops_capture_executor_skipped_transition_exact_log_contract():
    executor_test = _read(EXECUTOR_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（RunExecutor skipped transition exact structured log 契约）"
    )

    assert "RunExecutor skipped transition exact structured log 契约" in row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestMarkRunningSkippedLog::"
        "test_executor_logs_when_mark_running_skipped "
        "tests/unit/test_engine/test_executor.py::TestMarkRunningSkippedLog::"
        "test_executor_logs_when_mark_collecting_skipped` 2 passed"
        in row
    )
    assert "release quality docs contract full 230 passed" in row
    assert "targeted ruff passed" in row
    assert "`qaplatform.engine.executor` INFO" in row
    assert "message 为 `run_status_transition_skipped`" in row
    assert "record.run_id 等于当前 run" in row
    assert "preparing→running" in row
    assert "running→collecting" in row
    assert "reason 精确保留 concurrent cancel 语义" in row
    assert "此前 patch 全局 `logging.Logger.info`" in row
    assert "只取第一条匹配日志并抽查 from_/to" in row
    assert "logger 名或级别漂移" in row
    assert "重复刷日志" in row
    assert "run_id/reason 丢失" in row
    assert "某处打过一条同名日志" in row

    block = _marked_block(
        executor_test,
        "class TestMarkRunningSkippedLog:",
        "async def test_executor_does_not_publish_running_when_mark_running_returns_false",
    )

    assert "import logging" in executor_test
    assert "def _skipped_transition_records(caplog):" in block
    assert 'record.name == "qaplatform.engine.executor"' in block
    assert 'record.getMessage() == "run_status_transition_skipped"' in block
    assert (
        'caplog.set_level(logging.INFO, logger="qaplatform.engine.executor")'
        in block
    )
    assert "assert result == RunStatus.CANCELLED" in block
    assert "for record in self._skipped_transition_records(caplog)" in block
    for expected in [
        "record.levelno",
        "record.run_id",
        "record.from_",
        "record.to",
        "record.reason",
        "logging.INFO",
        "str(sample_run.id)",
        "RunStatus.PREPARING.value",
        "RunStatus.RUNNING.value",
        "RunStatus.COLLECTING.value",
        '"row not in expected state — likely cancelled concurrently"',
    ]:
        assert expected in block
    assert 'patch("logging.Logger.info"' not in block
    assert "assert skipped," not in block
    assert "extra.get(" not in block
    assert "assert len(records) == 1" not in block
    assert "records[0]" not in block


def test_quality_ops_capture_executor_failed_tests_cap_direct_projection_contract():
    executor_test = _read(EXECUTOR_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（RunExecutor failed_tests cap direct list projection 契约）"
    )

    assert "RunExecutor failed_tests cap direct list projection 契约" in row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestExecutorCommitsAfterStateTransitions::test_execute_caps_failed_test_names_in_summary` 1 passed"
        in row
    )
    assert "前 20 条 `failed_tests` 完整 `{suite,name,status}` 列表" in row
    assert "`failed_tests_omitted == 5`" in row
    assert '`len(summary["failed_tests"]) == 20` 加首尾抽查' in row
    assert "中间失败用例顺序、名称或状态漂移" in row
    assert "通知 summary 截断测试只证明“数量对且首尾看起来对”" in row

    block = _marked_block(
        executor_test,
        "async def test_execute_caps_failed_test_names_in_summary",
        "async def test_old_collector_signature_still_works",
    )

    assert 'assert summary["failed_tests"] == [' in block
    assert '"suite": "suite"' in block
    assert '"name": f"test_{index}"' in block
    assert '"status": "failed"' in block
    assert "for index in range(20)" in block
    assert 'assert summary["failed_tests_omitted"] == 5' in block
    assert 'assert len(summary["failed_tests"]) == 20' not in block
    assert 'summary["failed_tests"][0]' not in block
    assert 'summary["failed_tests"][-1]' not in block


def test_quality_ops_capture_executor_state_transition_commit_sequence_contracts():
    row = _quality_ops_row_containing("Executor state transition commit 顺序契约")
    executor_test = _read(EXECUTOR_TEST)

    assert "Executor state transition commit 顺序契约" in row
    assert "不再只按 `commit.await_count >= 2` 证明总调用数" in row
    assert "可见状态转换的事务边界锁到“下一步必须 commit”" in row
    assert 'call_log[:2] == ["mark_running", "commit"]' in executor_test
    assert 'call_log[collecting_idx: collecting_idx + 2] == [' in executor_test
    assert '"mark_collecting",' in executor_test
    assert '"commit",' in executor_test
    assert "commit.await_count >= 2" not in executor_test


def test_quality_ops_capture_executor_timeout_artifact_log_exact_contract():
    row = _quality_ops_row_containing("RunExecutor timeout/artifact log 精确契约")
    executor_test = _read(EXECUTOR_TEST)

    assert "RunExecutor timeout/artifact log 精确契约" in row
    assert "exact RuntimeError args、graceful_stop reason、cleanup" in row
    assert "完整日志顺序、stderr 字段和上传/跳过消息" in row
    assert '`pytest.raises(..., match="timed out")`' in row
    assert "`assert any(...)` 找日志片段" in row
    assert "日志顺序漂移或额外/缺失日志" in row
    assert "有相似异常/日志片段" in row
    assert 'assert exc_info.value.args == ("Setup script timed out after 0s",)' in (
        executor_test
    )
    assert "graceful.assert_awaited_once_with(\"c\", reason=\"setup timeout 0s\")" in (
        executor_test
    )
    assert "mock_log_stream.write_log.await_args_list == [" in executor_test
    assert "Skipped artifact big.txt: size 9 exceeds limit 2 bytes" in executor_test
    assert "Uploaded artifact: small.txt" in executor_test
    assert "Uploaded artifact: a.txt" in executor_test
    assert "Skipped artifact b.txt: artifact count limit exceeded" in executor_test
    assert "timeout_executor.log_stream.write_log.await_args_list == [" in (
        executor_test
    )
    assert "Stage 'pytest' exceeded timeout 42s, sending SIGTERM" in executor_test
    assert 'with pytest.raises(RuntimeError, match="timed out")' not in executor_test
    assert '"exceeds limit" in call.args[1]' not in executor_test
    assert '"count limit exceeded" in call.args[1]' not in executor_test
    assert '"exceeded timeout" in m and "pytest" in m and "42" in m' not in (
        executor_test
    )


def test_quality_ops_capture_executor_artifact_limit_exact_storage_contract():
    executor_test = _read(EXECUTOR_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（RunExecutor artifact limit exact storage 契约）"
    )

    assert "RunExecutor artifact limit exact storage 契约" in row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestUploadArtifacts::test_upload_skips_artifacts_over_size_limit "
        "tests/unit/test_engine/test_executor.py::TestUploadArtifacts::test_upload_skips_artifacts_over_count_limit` 2 passed"
        in row
    )
    assert "executor full 42 passed" in row
    assert "release quality docs contract full 196 passed" in row
    assert "唯一 S3 upload 的完整 kwargs：bucket、完整 storage key、Body 本地文件" in row
    assert "artifact row 的 run_id/type/name/storage_path/size_bytes/mime_type exact 参数" in row
    assert "此前只用 `Key.endswith(...)` 和局部 artifact 字段断言" in row
    assert "artifact limit 测试只证明“超限文件被跳过且另一个文件大概上传”" in row

    size_block = _marked_block(
        executor_test,
        "async def test_upload_skips_artifacts_over_size_limit",
        "async def test_upload_skips_artifacts_over_count_limit",
    )
    count_block = _marked_block(
        executor_test,
        "async def test_upload_skips_artifacts_over_count_limit",
        "\n\n# --------------------------------------------------------------------------- #",
    )

    for expected in [
        "run_id = \"11111111-1111-1111-1111-111111111111\"",
        "uploaded_body = put_kwargs[\"Body\"]",
        "assert put_kwargs == {",
        "\"Bucket\": \"qa-platform\"",
        "\"Key\": f\"reports/{run_id}/small.txt\"",
        "\"Body\": uploaded_body",
        'Path(uploaded_body.name) == tmp_path / "results" / "small.txt"',
        "artifact_repo.create.assert_awaited_once_with(",
        "run_id=UUID(run_id)",
        "type=\"log\"",
        "name=\"small.txt\"",
        "storage_path=f\"reports/{run_id}/small.txt\"",
        "size_bytes=2",
        "mime_type=\"text/plain\"",
        "\"Skipped artifact big.txt: size 9 exceeds limit 2 bytes\"",
        "\"Uploaded artifact: small.txt\"",
    ]:
        assert expected in size_block
    for expected in [
        "run_id = \"11111111-1111-1111-1111-111111111111\"",
        "uploaded_body = put_kwargs[\"Body\"]",
        "assert put_kwargs == {",
        "\"Bucket\": \"qa-platform\"",
        "\"Key\": f\"reports/{run_id}/a.txt\"",
        "\"Body\": uploaded_body",
        'Path(uploaded_body.name) == tmp_path / "results" / "a.txt"',
        "artifact_repo.create.assert_awaited_once_with(",
        "run_id=UUID(run_id)",
        "type=\"log\"",
        "name=\"a.txt\"",
        "storage_path=f\"reports/{run_id}/a.txt\"",
        "size_bytes=1",
        "mime_type=\"text/plain\"",
        "\"Uploaded artifact: a.txt\"",
        "\"Skipped artifact b.txt: artifact count limit exceeded\"",
    ]:
        assert expected in count_block
    assert "put_kwargs[\"Key\"].endswith" not in size_block
    assert "put_kwargs[\"Key\"].endswith" not in count_block
    assert "assert set(put_kwargs)" not in size_block
    assert "assert set(put_kwargs)" not in count_block
    assert "artifact_kwargs = artifact_repo.create.await_args.kwargs" not in size_block
    assert "artifact_kwargs = artifact_repo.create.await_args.kwargs" not in count_block


def test_quality_ops_capture_executor_artifact_upload_storage_exact_contract():
    executor_test = _read(EXECUTOR_TEST)
    direct_row = _quality_ops_row(
        "| 2026-05-31 | N/A（RunExecutor artifact row direct projection 契约）"
    )
    storage_row = _quality_ops_row_containing(
        "RunExecutor artifact upload storage 精确契约"
    )

    assert "RunExecutor artifact row direct projection 契约" in direct_row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestUploadArtifacts::test_upload_writes_artifact_rows_with_inferred_type_and_mime "
        "tests/unit/test_engine/test_executor.py::TestUploadArtifacts::test_upload_recurses_allure_report_directories` "
        "2 passed"
        in direct_row
    )
    assert "executor full 42 passed" in direct_row
    assert "release quality docs contract full 340 passed" in direct_row
    assert "S3 upload 顺序、Body 相对路径" in direct_row
    assert "artifact row 完整 `{run_id,type,name,storage_path,size_bytes,mime_type}` 列表" in (
        direct_row
    )
    assert "`set(recorded)` 和局部字段抽查" in direct_row
    assert "Allure 子文件只名字集合对了" in direct_row
    assert "artifact row direct projection 契约" in direct_row
    assert "artifact 上传测试只证明“名字集合对且几项字段看起来对”" in (
        direct_row
    )
    assert "RunExecutor artifact upload storage 精确契约" in storage_row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestUploadArtifacts::test_upload_writes_artifact_rows_with_inferred_type_and_mime` 1 passed"
        in storage_row
    )
    assert "三次 S3 `put_object` 的 bucket、storage key 与 Body 本地相对路径" in (
        storage_row
    )
    assert "artifact rows 的 name/run_id/storage_path 集合精确对应同一批上传对象" in (
        storage_row
    )
    assert "`s3.put_object.await_count == 3`" in storage_row
    assert "`artifact_repo.create.await_count == 3`" in storage_row
    assert "对象上传到错 bucket/key" in storage_row
    assert "上传和记录都发生了三次" in storage_row
    assert "uploaded = [" in executor_test
    assert 'upload.kwargs["Bucket"]' in executor_test
    assert 'upload.kwargs["Key"]' in executor_test
    assert 'Path(upload.kwargs["Body"].name).relative_to(results_dir).as_posix()' in (
        executor_test
    )
    assert '("test-bucket", f"reports/{run_id}/extra.bin", "extra.bin")' in (
        executor_test
    )
    assert '("test-bucket", f"reports/{run_id}/junit.xml", "junit.xml")' in (
        executor_test
    )
    assert '("test-bucket", f"reports/{run_id}/report.html", "report.html")' in (
        executor_test
    )
    upload_block = _marked_block(
        executor_test,
        "async def test_upload_writes_artifact_rows_with_inferred_type_and_mime",
        "async def test_upload_recurses_allure_report_directories",
    )
    allure_block = _marked_block(
        executor_test,
        "async def test_upload_recurses_allure_report_directories",
        "async def test_upload_skips_artifact_row_when_repo_missing",
    )

    for expected in [
        "recorded_rows = [",
        "call.kwargs for call in artifact_repo.create.await_args_list",
        "junit_mime_type = next(",
        'if row.get("name") == "junit.xml"',
        'assert junit_mime_type in {"application/xml", "text/xml"}',
        "assert recorded_rows == [",
        '"type": "other"',
        '"name": "extra.bin"',
        '"storage_path": f"reports/{run_id}/extra.bin"',
        '"size_bytes": len(b"\\x00\\x01")',
        '"mime_type": "application/octet-stream"',
        '"type": "junit"',
        '"name": "junit.xml"',
        '"mime_type": junit_mime_type',
        '"type": "report"',
        '"name": "report.html"',
        '"mime_type": "text/html"',
    ]:
        assert expected in upload_block

    for expected in [
        "uploaded = [",
        'upload.kwargs["Key"]',
        'Path(upload.kwargs["Body"].name).relative_to(results_dir).as_posix()',
        'f"reports/{run_id}/allure-report/assets/app.js"',
        '"allure-report/assets/app.js"',
        'f"reports/{run_id}/allure-report/index.html"',
        '"allure-report/index.html"',
        "call.kwargs for call in artifact_repo.create.await_args_list",
        '"type": "allure-report"',
        '"name": "allure-report/assets/app.js"',
        '"storage_path": f"reports/{run_id}/allure-report/assets/app.js"',
        '"size_bytes": len("ok")',
        '"mime_type": "text/javascript"',
        '"name": "allure-report/index.html"',
        '"storage_path": f"reports/{run_id}/allure-report/index.html"',
        '"size_bytes": len("<html/>")',
        '"mime_type": "text/html"',
    ]:
        assert expected in allure_block

    for rejected in [
        "assert set(recorded)",
        'assert {call["run_id"] for call in recorded.values()}',
        'assert {call["storage_path"] for call in recorded.values()}',
        'recorded["junit.xml"]',
        'recorded["allure-report/index.html"]',
        "uploaded_keys = {",
    ]:
        assert rejected not in upload_block
        assert rejected not in allure_block
    assert "assert s3.put_object.await_count == 3" not in executor_test
    assert "assert artifact_repo.create.await_count == 3" not in executor_test


def test_quality_ops_capture_executor_artifact_repo_missing_s3_exact_upload_contract():
    executor_test = _read(EXECUTOR_TEST)
    row = _quality_ops_row("|", contains="RunExecutor artifact_repo missing S3-only direct kwargs follow-up")

    assert (
        "`tests/unit/test_engine/test_executor.py::TestUploadArtifacts::test_upload_skips_artifact_row_when_repo_missing` "
        "1 passed"
    ) in row
    assert "executor full 42 passed" in row
    assert "release quality docs contract full 342 passed" in row
    assert "targeted ruff passed" in row
    assert "`put_object` 完整 kwargs 等值" in row
    assert "bucket、storage key、Body 本地文件对象" in row
    assert "`Uploaded artifact: x.xml` 日志对应同一个 run id" in row
    assert "ContentType、ACL、错误 metadata" in row
    assert "几个 S3 字段看起来对" in row

    block = _marked_block_or_tail(
        executor_test,
        "async def test_upload_skips_artifact_row_when_repo_missing",
        "\n    @pytest.mark.asyncio",
    )

    assert 's3_bucket="test-bucket"' in block
    assert 'run_id = "11111111-1111-1111-1111-111111111111"' in block
    assert "s3.put_object.assert_awaited_once()" in block
    assert 'uploaded_body = put_kwargs["Body"]' in block
    assert "assert put_kwargs == {" in block
    assert '"Bucket": "test-bucket"' in block
    assert '"Key": f"reports/{run_id}/x.xml"' in block
    assert '"Body": uploaded_body' in block
    assert (
        'Path(uploaded_body.name) == tmp_path / "results" / "x.xml"'
        in block
    )
    assert 'put_kwargs["Bucket"] == "test-bucket"' not in block
    assert 'put_kwargs["Key"] == f"reports/{run_id}/x.xml"' not in block
    assert 'Path(put_kwargs["Body"].name)' not in block
    assert "mock_log_stream.write_log.assert_awaited_once_with(" in block
    assert '"Uploaded artifact: x.xml"' in block


def test_quality_ops_capture_executor_mark_collecting_race_exact_publish_contract():
    executor_test = _read(EXECUTOR_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（RunExecutor mark_collecting race exact publish 契约）"
    )

    assert "RunExecutor mark_collecting race exact publish 契约" in row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestMarkRunningSkippedLog::test_executor_does_not_publish_collecting_when_mark_collecting_returns_false` 1 passed"
        in row
    )
    assert "executor full 42 passed" in row
    assert "release quality docs contract full 203 passed" in row
    assert "只发布一次 `RUNNING` status event" in row
    assert "(redis=None, run_id, running, previous=preparing)" in row
    assert "`mark_collecting(run_id)`" in row
    assert "不写 finish/fail 终态" in row
    assert "`Collecting test results...`" in row
    assert "`publish_status_event.assert_awaited_once()`" in row
    assert "`args[2] == running`" in row
    assert "误发布 collecting" in row
    assert "取消竞争后仍进入收集/终态写入" in row
    assert "发布过一个 running 事件" in row

    test_block = _marked_block_or_tail(
        executor_test,
        "async def test_executor_does_not_publish_collecting_when_mark_collecting_returns_false",
        "\n\nclass ",
    )

    for expected in [
        "publish_status_event.assert_awaited_once_with(",
        "None,",
        "str(sample_run.id),",
        "RunStatus.RUNNING.value,",
        "previous=RunStatus.PREPARING.value,",
        "mock_run_repo.mark_collecting.assert_awaited_once_with(str(sample_run.id))",
        "mock_run_repo.finish_if_current.assert_not_awaited()",
        "mock_run_repo.fail_if_current.assert_not_awaited()",
        "logged_messages = [",
        "log_call.args[1] for log_call in mock_log_stream.write_log.await_args_list",
        'assert "Collecting test results..." not in logged_messages',
    ]:
        assert expected in test_block
    assert "publish_status_event.assert_awaited_once()" not in test_block
    assert "publish_status_event.await_args.args[2]" not in test_block


def test_quality_ops_capture_run_executor_setup_success_backend_lifecycle_contract():
    executor_test = _read(EXECUTOR_TEST)
    mount_row = _quality_ops_row_containing(
        "RunExecutor setup mount direct projection 契约"
    )
    success_row = _quality_ops_row_containing(
        "RunExecutor setup success backend lifecycle 契约"
    )

    assert "RunExecutor setup mount direct projection 契约" in mount_row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_runs_via_backend_not_subprocess tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_timeout_capped_at_600s tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_uses_pipeline_timeout_when_below_cap tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_nonzero_exit_raises tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_timeout_raises` 5 passed"
        in mount_row
    )
    assert "release quality docs contract full 339 passed" in mount_row
    assert "workspace mount 投影为唯一 `[{source,target,read_only}]`" in mount_row
    assert "`len(spec.mounts) == 1` 与 `spec.mounts[0]` 分散断言" in (
        mount_row
    )
    assert "setup mount direct projection 契约" in mount_row
    assert "setup sandbox 测试只证明“有一个挂载且索引 0 看起来对”" in (
        mount_row
    )

    assert "RunExecutor setup success backend lifecycle 契约" in success_row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_runs_via_backend_not_subprocess tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_timeout_capped_at_600s tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_uses_pipeline_timeout_when_below_cap` 3 passed"
        in success_row
    )
    assert "executor full 42 passed" in success_row
    assert "release quality docs contract full 289 passed" in success_row
    assert (
        "`ExecutionSpec` 的 image/command/env/resource_limits/network/security/user/mount/labels"
        in success_row
    )
    assert "`create_execution -> start -> wait -> cleanup` 使用同一个 execution id" in (
        success_row
    )
    assert "成功后 `_active_execution_id` 清空" in success_row
    assert "此前只证明 `create_execution` 被碰过、lifecycle id 和 timeout 参数正确" in (
        success_row
    )
    assert "setup command、env、workspace mount、resource limits 或 sandbox/user/labels 漂移" in (
        success_row
    )
    assert "backend spec+lifecycle 契约" in success_row
    assert "setup 成功路径测试只证明“timeout 参数看起来对”" in success_row

    spec_block = _marked_block(
        executor_test,
        "async def test_setup_runs_via_backend_not_subprocess",
        "async def test_setup_timeout_capped_at_600s",
    )
    capped_block = _marked_block(
        executor_test,
        "async def test_setup_timeout_capped_at_600s",
        "async def test_setup_uses_pipeline_timeout_when_below_cap",
    )
    below_cap_block = _marked_block(
        executor_test,
        "async def test_setup_uses_pipeline_timeout_when_below_cap",
        "async def test_setup_nonzero_exit_raises",
    )

    for expected in [
        "spec = mock_backend.create_execution.await_args.args[0]",
        "assert isinstance(spec, ExecutionSpec)",
        'assert spec.image == "python:3.12-alpine"',
        'assert spec.command == ["sh", "-c", "cd /workspace && pip install -r requirements.txt"]',
        'assert spec.env_vars == {"FOO": "bar"}',
        "assert spec.resource_limits is setup_pipeline.resource_limits",
        'assert spec.network_policy == "deny"',
        'assert spec.user == "1000:1000"',
        "assert spec.security.readonly_rootfs is False",
        "assert _mount_projection(spec.mounts) == [",
        '"source": str(tmp_path),',
        '"target": "/workspace",',
        '"read_only": False,',
        'assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}',
    ]:
        assert expected in spec_block

    assert 'mock_backend.start.assert_awaited_once_with("setup-container-1")' in (
        spec_block
    )
    assert 'mock_backend.wait.assert_awaited_once_with("setup-container-1", 300)' in (
        spec_block
    )
    assert 'mock_backend.cleanup.assert_awaited_once_with("setup-container-1")' in (
        spec_block
    )
    assert "assert executor._active_execution_id is None" in spec_block

    assert 'AsyncMock(return_value="setup-capped-container")' in capped_block
    assert "mock_backend.create_execution.assert_awaited_once()" in capped_block
    for expected in [
        "spec = mock_backend.create_execution.await_args.args[0]",
        "assert isinstance(spec, ExecutionSpec)",
        'assert spec.image == "python:3.12-alpine"',
        'assert spec.command == ["sh", "-c", "cd /workspace && echo hi"]',
        "assert spec.env_vars == {}",
        "assert spec.resource_limits is pipeline.resource_limits",
        'assert spec.network_policy == "deny"',
        'assert spec.user == "1000:1000"',
        "assert spec.security.readonly_rootfs is False",
        "assert _mount_projection(spec.mounts) == [",
        '"source": str(tmp_path),',
        '"target": "/workspace",',
        '"read_only": False,',
        'assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}',
    ]:
        assert expected in capped_block
    assert 'mock_backend.start.assert_awaited_once_with("setup-capped-container")' in (
        capped_block
    )
    assert (
        'mock_backend.wait.assert_awaited_once_with("setup-capped-container", 600)'
        in capped_block
    )
    assert (
        'mock_backend.cleanup.assert_awaited_once_with("setup-capped-container")'
        in capped_block
    )
    assert "assert executor._active_execution_id is None" in capped_block

    assert 'AsyncMock(return_value="setup-short-container")' in below_cap_block
    assert "mock_backend.create_execution.assert_awaited_once()" in below_cap_block
    for expected in [
        "spec = mock_backend.create_execution.await_args.args[0]",
        "assert isinstance(spec, ExecutionSpec)",
        'assert spec.image == "python:3.12-alpine"',
        'assert spec.command == ["sh", "-c", "cd /workspace && echo hi"]',
        "assert spec.env_vars == {}",
        "assert spec.resource_limits is pipeline.resource_limits",
        'assert spec.network_policy == "deny"',
        'assert spec.user == "1000:1000"',
        "assert spec.security.readonly_rootfs is False",
        "assert _mount_projection(spec.mounts) == [",
        '"source": str(tmp_path),',
        '"target": "/workspace",',
        '"read_only": False,',
        'assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}',
    ]:
        assert expected in below_cap_block
    assert 'mock_backend.start.assert_awaited_once_with("setup-short-container")' in (
        below_cap_block
    )
    assert (
        'mock_backend.wait.assert_awaited_once_with("setup-short-container", 120)'
        in below_cap_block
    )
    assert (
        'mock_backend.cleanup.assert_awaited_once_with("setup-short-container")'
        in below_cap_block
    )
    assert "assert executor._active_execution_id is None" in below_cap_block

    assert "timeout_passed = wait_args.args[1]" not in capped_block
    assert "wait_args = mock_backend.wait.await_args" not in capped_block
    assert "assert mock_backend.wait.await_args.args[1] == 120" not in (
        below_cap_block
    )
    assert "def _mount_projection(mounts):" in executor_test
    for old_mount_assertion in [
        "assert len(spec.mounts) == 1",
        "assert spec.mounts[0].source == str(tmp_path)",
        'assert spec.mounts[0].target == "/workspace"',
        "assert spec.mounts[0].read_only is False",
    ]:
        assert old_mount_assertion not in spec_block
        assert old_mount_assertion not in capped_block
        assert old_mount_assertion not in below_cap_block


def test_quality_ops_capture_run_executor_setup_failure_spec_exact_contract():
    row = _quality_ops_row_containing("RunExecutor setup failure spec exact 契约")
    executor_test = _read(EXECUTOR_TEST)

    assert "RunExecutor setup failure spec exact 契约" in row
    assert (
        "`tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_nonzero_exit_raises tests/unit/test_engine/test_executor.py::TestRunSetupContainerised::test_setup_timeout_raises` 2 passed"
        in row
    )
    assert "executor full 42 passed" in row
    assert "release quality docs contract full 290 passed" in row
    assert (
        "失败容器 `ExecutionSpec` 的 image/command/env/resource_limits/network/security/user/mount/labels"
        in row
    )
    assert "失败路径绕过 env/resource_limits、workspace mount、user 或 labels" in (
        row
    )
    assert "失败测试只证明“异常和 cleanup 正常”" in row

    nonzero_block = _marked_block(
        executor_test,
        "async def test_setup_nonzero_exit_raises",
        "async def test_setup_timeout_raises",
    )
    timeout_block = _marked_block(
        executor_test,
        "async def test_setup_timeout_raises",
        "async def test_setup_outer_wait_for_triggers_graceful_stop",
    )

    for block in [nonzero_block, timeout_block]:
        for expected in [
            "from qaplatform.engine.executor import ExecutionSpec",
            "mock_backend.create_execution.assert_awaited_once()",
            "spec = mock_backend.create_execution.await_args.args[0]",
            "assert isinstance(spec, ExecutionSpec)",
            'assert spec.image == "python:3.12-alpine"',
            '"cd /workspace && pip install -r requirements.txt"',
            'assert spec.env_vars == {"FOO": "bar"}',
            "assert spec.resource_limits is setup_pipeline.resource_limits",
            'assert spec.network_policy == "deny"',
            'assert spec.user == "1000:1000"',
            "assert spec.security.readonly_rootfs is False",
            "assert _mount_projection(spec.mounts) == [",
            '"source": str(tmp_path),',
            '"target": "/workspace",',
            '"read_only": False,',
            'assert spec.labels == {"run_id": str(sample_run.id), "phase": "setup"}',
        ]:
            assert expected in block

    assert 'assert exc_info.value.args == ("Setup script failed (exit 1)",)' in (
        nonzero_block
    )
    assert 'mock_backend.wait.assert_awaited_once_with("c", 300)' in nonzero_block
    assert 'mock_backend.cleanup.assert_awaited_once_with("c")' in nonzero_block
    assert "assert executor._active_execution_id is None" in nonzero_block
    assert (
        'assert exc_info.value.args == ("Setup script timed out after 300s",)'
        in timeout_block
    )
    assert 'mock_backend.wait.assert_awaited_once_with("c", 300)' in timeout_block
    assert 'mock_backend.cleanup.assert_awaited_once_with("c")' in timeout_block
    assert "assert executor._active_execution_id is None" in timeout_block
    for old_mount_assertion in [
        "assert len(spec.mounts) == 1",
        "assert spec.mounts[0].source == str(tmp_path)",
        'assert spec.mounts[0].target == "/workspace"',
        "assert spec.mounts[0].read_only is False",
    ]:
        assert old_mount_assertion not in nonzero_block
        assert old_mount_assertion not in timeout_block


def test_quality_ops_capture_lifespan_worker_startup_exact_init_sequence_contract():
    quality_ops = _quality_ops_row_containing(
        "Lifespan/worker startup exact init sequence 契约"
    )
    lifespan_test = _read(LIFESPAN_TEST)

    assert "Lifespan/worker startup exact init sequence 契约" in quality_ops
    assert "`init_db -> init_redis -> init_arq -> init_s3 -> init_crypto -> ensure_plugin_registry`" in (
        quality_ops
    )
    assert "`init_db -> init_redis -> init_arq -> init_s3 -> init_crypto`" in (
        quality_ops
    )
    assert "隔离 tracing provider 影响" in quality_ops
    assert "只证明 `init_s3` 在 `init_arq` 后出现" in quality_ops
    assert "`init_crypto` 被删" in quality_ops
    assert "DB/Redis/ARQ/S3 顺序被重排" in quality_ops
    assert "S3 大概排在 ARQ 后面" in quality_ops

    assert "def _ensure_registry(_container):" in lifespan_test
    assert "call_order.append(\"ensure_plugin_registry\")" in lifespan_test
    assert (
        "patch(\"qaplatform.main._ensure_plugin_registry\", side_effect=_ensure_registry)"
        in lifespan_test
    )
    assert "patch(\"qaplatform.main.setup_tracing\", return_value=None)" in lifespan_test
    assert (
        "patch(\"qaplatform.worker.settings.setup_tracing\", return_value=None)"
        in lifespan_test
    )
    assert "assert call_order == [" in lifespan_test
    assert '"init_db",\n            "init_redis",\n            "init_arq",\n            "init_s3",\n            "init_crypto",' in (
        lifespan_test
    )
    assert '"ensure_plugin_registry",' in lifespan_test
    assert 'assert "init_s3" in call_order' not in lifespan_test
    assert 'call_order.index("init_arq") < call_order.index("init_s3")' not in (
        lifespan_test
    )


def test_quality_ops_capture_lifespan_shutdown_close_no_cancel_exact_contract():
    lifespan_test = _read(LIFESPAN_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Lifespan shutdown close/no-cancel exact 契约）"
    )

    assert "Lifespan shutdown close/no-cancel exact 契约" in row
    assert (
        "`tests/unit/test_lifespan.py::TestLifespanShutdownNoCancelAll::test_shutdown_does_not_cancel_concurrent_tasks tests/unit/test_lifespan.py::TestLifespanShutdownNoCancelAll::test_shutdown_calls_container_close tests/unit/test_lifespan.py::TestLifespanShutdownNoCancelAll::test_shutdown_does_not_raise_with_no_tasks` 3 passed"
        in row
    )
    assert "lifespan full 9 passed" in row
    assert "release quality docs contract full 213 passed" in row
    assert "targeted ruff passed" in row
    assert "不取消并发任务且任务仍 pending" in row
    assert "测试手动 cancel 收尾" in row
    assert "`container.close()` 以零参数被 await 一次" in row
    assert "此前只证明 concurrent task 未进入 CancelledError" in row
    assert "close 调用夹带参数" in row
    assert "无任务路径和并发路径表现不一致" in row
    assert "任务提前完成但不抛 CancelledError" in row
    assert "只证明“看起来没有 cancel-all 且 close 被碰过”" in row

    for expected in [
        "assert not bg.done()",
        "container.close.assert_awaited_once_with()",
    ]:
        assert expected in lifespan_test
    assert "container.close.assert_awaited_once()" not in lifespan_test


def test_quality_ops_capture_docker_backend_create_execution_exact_config_contract():
    docker_backend_test = _read(DOCKER_BACKEND_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（DockerBackend create execution exact config 契约）"
    )

    assert "DockerBackend create execution exact config 契约" in row
    assert (
        "`tests/unit/test_engine/test_docker_backend.py::TestDockerBackend::test_create_execution` 1 passed"
        in row
    )
    assert "docker backend full 33 passed" in row
    assert "release quality docs contract full 193 passed" in row
    assert "`containers.create_or_replace` 的完整 kwargs" in row
    assert "完整 HostConfig 沙箱字段集合、Tmpfs 和 Labels" in row
    assert "dict 等值证明没有多余 StorageOpt" in row
    assert "此前虽然覆盖了很多字段，但仍是逐字段抽查" in row
    assert "Docker 创建测试只证明“关键字段大概都在”" in row

    block = _marked_block(
        docker_backend_test,
        "async def test_create_execution",
        "async def test_create_execution_sets_storage_opt_when_disk_limit_present",
    )
    for expected in [
        "assert self._created_container_kwargs(mock_containers) == {",
        '"name": "qap-run-run-123"',
        '"config": {',
        '"Image": "python:3.12"',
        '"Cmd": ["pytest"]',
        '"Env": ["PYTHONDONTWRITEBYTECODE=1"]',
        '"User": "1000:1000"',
        '"AttachStdout": True',
        '"AttachStderr": True',
        '"HostConfig": {',
        '"Memory": 512 * 1024 * 1024',
        '"MemorySwap": 512 * 1024 * 1024',
        '"NanoCpus": 1_000_000_000',
        '"ReadonlyRootfs": True',
        '"SecurityOpt": ["no-new-privileges"]',
        '"CapDrop": ["ALL"]',
        '"CapAdd": []',
        '"PidsLimit": 256',
        '"Devices": []',
        '"NetworkMode": "none"',
        '"Init": True',
        '"Binds": []',
        '"Tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"}',
        '"Labels": {',
        '"managed-by": "qaplatform"',
        '"run_id": "run-123"',
    ]:
        assert expected in block
    assert 'create_kwargs["name"]' not in block
    assert 'config["HostConfig"]["Memory"]' not in block
    assert '"StorageOpt" not in config["HostConfig"]' not in block


def test_quality_ops_capture_docker_backend_oom_retry_backoff_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "DockerBackend OOM inspect retry backoff 精确契约"
    )
    docker_backend_test = _read(DOCKER_BACKEND_TEST)

    assert "DockerBackend OOM inspect retry backoff 精确契约" in quality_ops
    assert (
        "`tests/unit/test_engine/test_docker_backend.py::TestDockerBackend::test_wait_retries_oom_inspect_after_sigkill_exit` 1 passed"
        in quality_ops
    )
    assert "固定两次无参 `container.show()`" in quality_ops
    assert "第一次 `OOMKilled=False` 后只 sleep 一次 `0.25` 再重查" in (
        quality_ops
    )
    assert "第二次 `OOMKilled=True` 后直接返回" in quality_ops
    assert "`mock_container.show.await_count == 2`" in quality_ops
    assert "忙等 Docker inspect" in quality_ops
    assert "只证明“inspect 了两次”" in quality_ops
    assert "from unittest.mock import AsyncMock, MagicMock, patch" in docker_backend_test
    assert "sleep = AsyncMock()" in docker_backend_test
    assert 'patch("qaplatform.engine.docker_backend.asyncio.sleep", new=sleep)' in (
        docker_backend_test
    )
    assert "show_call.args for show_call in mock_container.show.await_args_list" in (
        docker_backend_test
    )
    assert "sleep.assert_awaited_once_with(0.25)" in docker_backend_test
    assert "assert mock_container.show.await_count == 2" not in docker_backend_test


def test_quality_ops_capture_worker_resource_termination_exact_log_fields_contract():
    worker_resource = _read(WORKER_RESOURCE_TERMINATION)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
            "tests/integration/test_worker_resource_termination.py::"
            "test_executor_resource_termination_persists_timeout_status_and_redis_event -q` "
            "1 passed")

    assert "worker resource termination 集成用例" in row
    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`Resource termination` 字段日志投影必须精确等于单元素期望" in row
    assert "reason/exit_code/duration_ms/oom_killed/timed_out 与 summary 完全一致" in (
        row
    )
    assert "worker resource termination exact log fields direct projection 契约" in row
    assert "后来仍用 `len(termination_lines) == 1`" in row
    assert "只证明“DB summary 对了且日志里有几个关键词”" in row

    assert "def _resource_termination_log_fields(line: str) -> dict[str, str]:" in (
        worker_resource
    )
    assert 'prefix = "Resource termination: "' in worker_resource
    assert "assert [line for line in lines if line == f\"Starting stage: {scenario}\"]" in (
        worker_resource
    )
    assert 'failed_log = f"Pipeline failed with code {backend.exit_code}"' in (
        worker_resource
    )
    assert "assert [line for line in lines if line == failed_log] == [failed_log]" in (
        worker_resource
    )
    assert "_resource_termination_log_fields(line)" in worker_resource
    assert 'if line.startswith("Resource termination: ")' in worker_resource
    for expected in [
        '"reason": expected_reason',
        '"exit_code": str(backend.exit_code)',
        '"duration_ms": str(resource_termination["duration_ms"])',
        '"oom_killed": str(backend.oom_killed)',
        '"timed_out": str(backend.timed_out)',
        'assert [line for line in lines if line == "Run completed: timeout"] == [',
    ]:
        assert expected in worker_resource
    assert 'assert any(f"Starting stage: {scenario}" in line for line in lines)' not in (
        worker_resource
    )
    assert 'f"Pipeline failed with code {backend.exit_code}" in line' not in (
        worker_resource
    )
    assert 'f"Resource termination: reason={expected_reason}" in line' not in (
        worker_resource
    )
    assert "assert len(termination_lines) == 1" not in worker_resource
    assert "termination_lines[0]" not in worker_resource


def test_quality_ops_capture_oom_e2e_exact_resource_termination_log_contract():
    oom_e2e = _read(OOM_E2E)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 QAP_TEST_OOM=1 "
            "tests/integration/test_oom_e2e.py --collect-only` 3 tests collected")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "OOM opt-in e2e" in row
    assert "`Pipeline failed with code {exit_code}`" in row
    assert "termination reason/exit_code/duration_ms/oom_killed/timed_out" in row
    assert "投影列表必须精确等于单元素期望" in row
    assert "OOM e2e exact resource termination log direct projection 契约" in row
    assert "随后仍用 `len(termination_lines) == 1`" in row
    assert "只证明“状态对且日志里有几个关键词”" in row

    assert "def _assert_log_line_once(lines: list[str], expected_line: str) -> None:" in (
        oom_e2e
    )
    assert "def _resource_termination_log_fields(line: str) -> dict[str, str]:" in (
        oom_e2e
    )
    assert '_assert_log_line_once(lines, "Starting stage: oom")' in oom_e2e
    assert "failure_line = f\"Pipeline failed with code {resource_termination['exit_code']}\"" in (
        oom_e2e
    )
    assert "_assert_log_line_once(lines, failure_line)" in oom_e2e
    assert "_resource_termination_log_fields(line)" in oom_e2e
    assert 'if line.startswith("Resource termination: ")' in oom_e2e
    for expected in [
        '"reason": "oom"',
        '"exit_code": str(resource_termination["exit_code"])',
        '"duration_ms": str(resource_termination["duration_ms"])',
        '"oom_killed": "True"',
        '"timed_out": "False"',
        '_assert_log_line_once(lines, "Run completed: timeout")',
    ]:
        assert expected in oom_e2e
    for removed in [
        'assert any("Starting stage: oom" in line for line in lines)',
        'assert any("Resource termination: reason=oom" in line for line in lines)',
        'assert any("Run completed: timeout" in line for line in lines)',
        "assert len(termination_lines) == 1",
        "termination_lines[0]",
    ]:
        assert removed not in oom_e2e


def test_quality_ops_capture_cancel_e2e_create_execution_spec_exact_contract():
    cancel_e2e = _read(CANCEL_E2E)
    quality_ops = _quality_ops_rows_containing(
        "cancel E2E create_execution spec/zero-launch 精确契约",
        "cancel E2E create_execution direct projection 契约",
    )

    assert "cancel E2E create_execution spec/zero-launch 精确契约" in quality_ops
    assert (
        "`RUN_INTEGRATION_TESTS=1 tests/integration/test_cancel_e2e.py::test_cancel_at_stage_boundary_skips_next_stage tests/integration/test_cancel_e2e.py::test_cancel_recovered_when_published_before_subscribe --collect-only` 2 tests collected"
        in quality_ops
    )
    assert "stage-boundary cancel 现在固定唯一 `create_execution` 的 spec 必须是 stage-1" in (
        quality_ops
    )
    assert "cancel E2E create_execution direct projection 契约" in quality_ops
    assert "所有 `create_execution` await args 投影为唯一" in quality_ops
    assert "pre-subscribe cancel 现在用 `assert_not_awaited()` 禁止任何容器启动" in (
        quality_ops
    )
    assert "`create_execution_spy.await_count == 1` / `== 0`" in quality_ops
    assert "跳过 stage-1 却启动 stage-2 一次" in quality_ops
    assert "取消竞态测试只证明“容器启动次数看起来对”" in quality_ops
    assert (
        "execution_specs = [\n"
        "            call.args[0] for call in create_execution_spy.await_args_list\n"
        "        ]"
        in cancel_e2e
    )
    assert '"labels": spec.labels' in cancel_e2e
    assert '"command": spec.command' in cancel_e2e
    assert '"stage": "stage-1"' in cancel_e2e
    assert '"command": ["sh", "-c", "sleep 1"]' in cancel_e2e
    assert "create_execution_spy.assert_not_awaited()" in cancel_e2e
    assert "assert len(create_execution_spy.await_args_list) == 1" not in cancel_e2e
    assert "(stage_1_spec,) = create_execution_spy.await_args.args" not in cancel_e2e
    assert "assert create_execution_spy.await_count == 1" not in cancel_e2e
    assert "assert create_execution_spy.await_count == 0" not in cancel_e2e


def test_quality_ops_capture_executor_container_log_redaction_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "RunExecutor container log redaction 写日志精确契约"
    )
    redaction_test = _read(EXECUTOR_REDACTION_TEST)

    assert "RunExecutor container log redaction 写日志精确契约" in quality_ops
    assert (
        "`tests/unit/test_engine/test_executor_redaction.py::TestExecutorLogRedaction::test_stream_container_logs_redacts_environment_secret_values` 1 passed"
        in quality_ops
    )
    assert "`log_stream.write_log` 的完整 await 序列" in quality_ops
    assert "同一个 run id、stdout/stderr 两条脱敏后 line" in quality_ops
    assert "对应 stream kwarg 都必须精确匹配" in quality_ops
    assert "`log_stream.write_log.await_count == 2`" in quality_ops
    assert "`all(...)` 检查两条 line 不含 secret" in quality_ops
    assert "写错 run_id、stdout/stderr 对调" in quality_ops
    assert "日志脱敏测试只证明“写了两条看起来脱敏的日志”" in quality_ops
    assert "assert log_stream.write_log.await_args_list == [" in redaction_test
    assert 'call("run-1", "stdout printed [REDACTED]", stream="stdout")' in (
        redaction_test
    )
    assert 'call("run-1", "stderr printed [REDACTED]", stream="stderr")' in (
        redaction_test
    )
    assert "assert log_stream.write_log.await_count == 2" not in redaction_test
    assert "all(secret not in line for line in written)" not in redaction_test
    assert "all(\"[REDACTED]\" in line for line in written)" not in (
        redaction_test
    )


def test_quality_ops_capture_auto_retry_setup_log_exact_once_contract():
    auto_retry_real_db = _read(AUTO_RETRY_REAL_DB)
    row = _quality_ops_row(
        "| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_auto_retry_real_db.py::test_execute_run_setup_docker_infra_error_uses_real_executor_and_schedules_retry"
    )

    assert "test_execute_run_setup_script_failure_is_not_retried_real_executor" in row
    assert "2 passed" in row
    assert "auto_retry_real_db full 7 passed" in row
    assert "release quality docs contract full 349 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`_assert_log_line_once`" in row
    assert "`Repository cloned successfully`" in row
    assert "`Running setup script...`" in row
    assert "setup Docker infra retry" in row
    assert "setup script non-retry" in row
    assert '只用 `assert "... " in log_lines`' in row
    assert "setup 阶段重复执行" in row
    assert "至少出现过" in row
    assert "两条熟悉日志出现过" in row

    for expected in [
        "def _assert_log_line_once(log_lines: list[str], expected_line: str) -> None:",
        "assert [line for line in log_lines if line == expected_line] == [expected_line]",
        '_assert_log_line_once(log_lines, "Repository cloned successfully")',
        '_assert_log_line_once(log_lines, "Running setup script...")',
    ]:
        assert expected in auto_retry_real_db
    assert 'assert "Repository cloned successfully" in log_lines' not in (
        auto_retry_real_db
    )
    assert 'assert "Running setup script..." in log_lines' not in auto_retry_real_db
