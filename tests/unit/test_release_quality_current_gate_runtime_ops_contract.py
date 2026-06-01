from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)

ROOT = Path(__file__).resolve().parents[2]
AUTO_RETRY_REAL_DB = ROOT / "tests" / "integration" / "test_auto_retry_real_db.py"
NOTIFICATION_DELIVERY = ROOT / "tests" / "integration" / "test_notification_delivery.py"
RATE_LIMIT_TEST = ROOT / "tests" / "unit" / "test_api" / "test_rate_limit.py"
SILENT_WINDOWS_INTEGRATION = ROOT / "tests" / "integration" / "test_silent_windows.py"
SSE_TEST = ROOT / "tests" / "unit" / "test_api" / "test_sse.py"


def test_quality_ops_records_current_gate_runtime_ops_evidence():
    auto_retry_real_db = _read(AUTO_RETRY_REAL_DB)
    silent_windows_integration = _read(SILENT_WINDOWS_INTEGRATION)
    notification_delivery = _read(NOTIFICATION_DELIVERY)
    rate_limit_test = _read(RATE_LIMIT_TEST)
    sse_test = _read(SSE_TEST)
    sse_ticket_atomic_getdel_row = _quality_ops_row(
        "| 2026-05-31 | N/A（SSE ticket atomic getdel 参数精确契约）"
    )
    silent_window_schedule_run_exact_row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_silent_windows.py::test_cron_tick_outside_silent_window_creates_run"
    )
    notification_delivery_log_exact_row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_notification_delivery.py`"
    )
    auto_retry_enqueue_exact_row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_auto_retry_real_db.py::test_attempt_retry_uses_api_max_attempts"
    )
    rate_limit_token_bucket_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Rate limit token bucket key 精确契约）"
    )
    worker_notification_lazy_project_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Worker notification project_name 懒加载契约）"
    )
    worker_notification_log_write_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Worker notification log write 异常语义契约）"
    )
    schedule_silent_window_naive_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Schedule silent window naive now 短路契约）"
    )
    assert (
        "`RUN_INTEGRATION_TESTS=1 tests/integration/test_silent_windows.py::test_cron_tick_outside_silent_window_creates_run tests/integration/test_silent_windows.py::test_cron_tick_enqueue_conflict_records_last_error_and_waiting_run` 2 passed"
        in (silent_window_schedule_run_exact_row)
    )
    assert "完整 schedule Run metadata" in silent_window_schedule_run_exact_row
    assert "`run.trigger` 审计 after_state" in silent_window_schedule_run_exact_row
    assert "只用 `len(runs) == 1` / `len(created) == 1`" in (
        silent_window_schedule_run_exact_row
    )
    assert "只证明“创建了一个 run”" in silent_window_schedule_run_exact_row
    assert "def _expected_schedule_metadata(project, schedule) -> dict:" in (
        silent_windows_integration
    )
    assert "assert [run.metadata_ for run in runs] == [expected_metadata]" in (
        silent_windows_integration
    )
    assert "assert [run.metadata_ for run in created] == [expected_metadata]" in (
        silent_windows_integration
    )
    assert 'assert run.queue_name == "queue:low"' in silent_windows_integration
    assert "assert waiting_run.queue_name is None" in silent_windows_integration
    assert "assert audit.after_state == {" in silent_windows_integration
    assert "assert len(runs) == 1" not in silent_windows_integration
    assert "assert len(created) == 1" not in silent_windows_integration
    assert (
        "`RUN_INTEGRATION_TESTS=1 tests/integration/test_notification_delivery.py` 7 passed"
        in (notification_delivery_log_exact_row)
    )
    assert "NotificationLog 固定为完整" in notification_delivery_log_exact_row
    assert "`{run_id, rule_id, channel_type, status, error_message}` 列表" in (
        notification_delivery_log_exact_row
    )
    assert "用 `len(logs) == 1` 加少量字段检查" in (notification_delivery_log_exact_row)
    assert "有一条日志" in notification_delivery_log_exact_row
    assert "def _log_projection(log: NotificationLog) -> dict:" in notification_delivery
    assert "assert [_log_projection(log) for log in logs] == [" in notification_delivery
    assert '"error_message": "unknown template variable: unknown"' in (
        notification_delivery
    )
    assert '"error_message": "smtp unavailable"' in notification_delivery
    assert "assert len(logs) == 1" not in notification_delivery
    assert (
        "`tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::test_different_tokens_independent_quotas tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::test_third_token_passes_when_others_exhausted` 2 passed"
        in (rate_limit_token_bucket_exact_row)
    )
    assert "`zadd` bucket key 完整序列" in rate_limit_token_bucket_exact_row
    assert "rate_limit:token:<sha16>:/api/v1/runs" in (
        rate_limit_token_bucket_exact_row
    )
    assert "`any(hash in key)`" in rate_limit_token_bucket_exact_row
    assert "某个 hash 出现在某个 key 里" in rate_limit_token_bucket_exact_row
    assert "def _zadd_keys(redis) -> list[str]:" in rate_limit_test
    assert 'f"rate_limit:token:{hash_a}:/api/v1/runs"' in rate_limit_test
    assert 'f"rate_limit:token:{hash_b}:/api/v1/runs"' in rate_limit_test
    assert 'f"rate_limit:token:{hash_c}:/api/v1/runs"' in rate_limit_test
    assert "assert any(hash_a in key for key in zadd_keys)" not in rate_limit_test
    assert "assert any(hash_b in key for key in zadd_keys)" not in rate_limit_test
    assert "assert any(hash_c in key for key in zadd_keys)" not in rate_limit_test
    assert (
        "test_execute_run_setup_docker_infra_error_uses_real_executor_and_schedules_retry"
        in (auto_retry_enqueue_exact_row)
    )
    assert (
        "test_reclaim_resources_worker_lost_marks_failed_publishes_event_and_schedules_retry_real_db"
        in (auto_retry_enqueue_exact_row)
    )
    assert "完整 `{args, _queue_name, _job_id, _defer_by}`" in (
        auto_retry_enqueue_exact_row
    )
    assert "setup 阶段 workspace mount 投影" in auto_retry_enqueue_exact_row
    assert "Redis event 字段集合和 timestamp 解析" in auto_retry_enqueue_exact_row
    assert "`len(arq.calls) == 1`" in auto_retry_enqueue_exact_row
    assert "只证明“有一次入队/有一个事件”" in auto_retry_enqueue_exact_row
    assert "def _assert_retry_enqueued_once(" in auto_retry_real_db
    assert '"args": ("execute_run", str(retry_run.id))' in auto_retry_real_db
    assert '"_queue_name": queue_name' in auto_retry_real_db
    assert '"_defer_by": 0' in auto_retry_real_db
    assert 'Path(mount.source).name.startswith(f"qap-{str(original_id)[:8]}-")' in (
        auto_retry_real_db
    )
    assert 'datetime.fromisoformat(event_payloads[0]["timestamp"])' in (
        auto_retry_real_db
    )
    assert "assert len(arq.calls) == 1" not in auto_retry_real_db
    assert 'arq.calls[0]["kwargs"]["_job_id"].startswith("run:")' not in (
        auto_retry_real_db
    )
    assert "assert len(setup_spec.mounts) == 1" not in auto_retry_real_db
    assert "assert len(events) == 1" not in auto_retry_real_db
    assert (
        "`tests/unit/test_api/test_sse.py::test_authenticate_sse_ticket_consumes_atomically` 1 passed"
        in (sse_ticket_atomic_getdel_row)
    )
    assert "一个 401 `Invalid or expired SSE ticket`" in (sse_ticket_atomic_getdel_row)
    assert "同一个 `sse_ticket:{ticket}` key" in sse_ticket_atomic_getdel_row
    assert "`get` + `delete` 非原子组合" in sse_ticket_atomic_getdel_row
    assert "手写 `call_count == 2`" in sse_ticket_atomic_getdel_row
    assert "key 拼错、第二次读取了不同 key" in sse_ticket_atomic_getdel_row
    assert "并发 ticket 测试只证明“两个调用一成一败”" in (sse_ticket_atomic_getdel_row)
    assert "mock_redis.getdel = AsyncMock(side_effect=[payload, None])" in (sse_test)
    assert "assert [call.args for call in mock_redis.getdel.await_args_list] == [" in (
        sse_test
    )
    assert '(f"sse_ticket:{ticket}",)' in sse_test
    assert 'assert failure.detail == "Invalid or expired SSE ticket"' in sse_test
    assert "assert ticket not in failure.detail" in sse_test
    assert "assert call_count == 2" not in sse_test
    assert "`tests/unit/test_worker/test_notifications.py` 32 passed" in (
        worker_notification_lazy_project_row
    )
    assert "coverage unit 1247 passed" in worker_notification_lazy_project_row
    assert "未引用 `project_name` 时不查 ProjectRepository" in (
        worker_notification_lazy_project_row
    )
    assert "按渠道模板/规则模板渲染" in worker_notification_lazy_project_row
    assert "归一 email config" in worker_notification_lazy_project_row
    assert "写两条 sent log" in worker_notification_lazy_project_row
    assert "实现改成每次发送都查项目" in worker_notification_lazy_project_row
    assert "隐性 DB 耦合/性能回退" in worker_notification_lazy_project_row
    assert "项目查询失败会把通知误记失败" in worker_notification_lazy_project_row
    assert "`tests/unit/test_worker/test_notifications.py` 35 passed" in (
        worker_notification_log_write_row
    )
    assert "coverage unit 1250 passed" in worker_notification_log_write_row
    assert "`uq_notification_log_run_rule_channel`" in worker_notification_log_write_row
    assert "其他 IntegrityError/RuntimeError 会在 send 后继续抛出" in (
        worker_notification_log_write_row
    )
    assert "且不 commit" in worker_notification_log_write_row
    assert "所有异常都记录成 `notification_log_already_exists`" in (
        worker_notification_log_write_row
    )
    assert "DB/FK/仓储故障会被吞掉" in worker_notification_log_write_row
    assert "duplicate/non-duplicate/write failure 三条契约" in (
        worker_notification_log_write_row
    )
    assert (
        "`tests/unit/test_services/test_schedule_silent_windows.py::test_is_in_silent_window_rejects_naive_now` 1 passed"
        in (schedule_silent_window_naive_row)
    )
    assert "naive now 用例从 raises-only 补成先校验时区、后窗口匹配的短路契约" in (
        schedule_silent_window_naive_row
    )
    assert "只证明会抛包含 `timezone-aware` 的 `ValueError`" in (
        schedule_silent_window_naive_row
    )
    assert "先遍历 silent window 再失败" in schedule_silent_window_naive_row
    assert "一旦迭代就失败的窗口列表" in schedule_silent_window_naive_row
    assert "错误文案固定且无 cause" in schedule_silent_window_naive_row
    assert "静默窗口时间测试只为异常覆盖率服务" in (schedule_silent_window_naive_row)
