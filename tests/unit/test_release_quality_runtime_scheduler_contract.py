from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _marked_block_or_tail,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
ENGINE_CANCEL_TEST = ROOT / "tests" / "unit" / "test_engine" / "test_cancel.py"
LOG_STREAM_TEST = ROOT / "tests" / "unit" / "test_engine" / "test_log_stream.py"
WORKER_CHECK_SCHEDULES_TEST = (
    ROOT / "tests" / "unit" / "test_worker" / "test_check_schedules.py"
)
WORKER_SCHEDULER_TEST = (
    ROOT / "tests" / "unit" / "test_worker" / "test_scheduler.py"
)


def test_quality_ops_capture_log_stream_batch_truncation_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "LogStream batch truncation Redis 参数精确契约"
    )
    log_stream_test = _read(LOG_STREAM_TEST)

    assert "LogStream batch truncation Redis 参数精确契约" in quality_ops
    assert (
        "`tests/unit/test_engine/test_log_stream.py::TestLogStreamLineTruncation::test_write_batch_truncates_each_entry` 1 passed"
        in quality_ops
    )
    assert "`pipeline(transaction=False)`" in quality_ops
    assert "两条 `xadd` 的 stream key、payload stream/line" in quality_ops
    assert "`maxlen=_MAXLEN`、`approximate=True`" in quality_ops
    assert "pipeline `execute()` 被 await" in quality_ops
    assert "`pipeline_mock.xadd.call_count == 2`" in quality_ops
    assert "写错 run stream key、把 stderr 写成 stdout" in quality_ops
    assert "batch 日志测试只证明“排了两条 xadd”" in quality_ops
    assert "self.redis.pipeline.assert_called_once_with(transaction=False)" in (
        log_stream_test
    )
    assert "pipeline_mock.xadd.call_args_list == [" in log_stream_test
    assert 'f"run:{self.run_id}:logs",' in log_stream_test
    assert '{"stream": "stdout", "line": "ok"}' in log_stream_test
    assert '{"stream": "stderr", "line": expected_truncated}' in log_stream_test
    assert "maxlen=_MAXLEN" in log_stream_test
    assert "approximate=True" in log_stream_test
    assert 'assert second == {"stream": "stderr", "line": expected_truncated}' in (
        log_stream_test
    )
    assert "pipeline_mock.execute.assert_awaited_once_with()" in log_stream_test
    assert "assert pipeline_mock.xadd.call_count == 2" not in log_stream_test


def test_quality_ops_capture_log_stream_truncation_exact_byte_prefix_contract():
    log_stream_test = _read(LOG_STREAM_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（LogStream truncation exact byte/prefix 契约）"
    )

    assert "LogStream truncation exact byte/prefix 契约" in row
    assert (
        "`tests/unit/test_engine/test_log_stream.py::TestLogStreamLineTruncation::test_oversize_line_truncated_with_marker "
        "tests/unit/test_engine/test_log_stream.py::TestLogStreamLineTruncation::test_truncation_preserves_utf8_boundary "
        "tests/unit/test_engine/test_log_stream.py::TestLogStreamLineTruncation::test_write_batch_truncates_each_entry` 3 passed"
        in row
    )
    assert "log stream full 18 passed" in row
    assert "release quality docs contract full 207 passed" in row
    assert "保留前缀到 `_MAX_LINE_BYTES - len(_TRUNCATION_MARKER)` byte budget" in row
    assert "ASCII 路径正好 4096 bytes" in row
    assert "UTF-8 路径必须停在完整字符边界" in row
    assert "batch 第二条 xadd payload 也必须等于同一 exact truncation" in row
    assert "`len(...encode()) <= 4096`" in row
    assert '`endswith("...[truncated]")`' in row
    assert "保留尾部" in row
    assert "marker 预算计算漂移" in row
    assert "只证明“结果不超长且看起来被截断了”" in row

    truncation_block = _marked_block_or_tail(
        log_stream_test,
        "class TestLogStreamLineTruncation",
        "\n\nclass ",
    )

    for expected in [
        "_MAX_LINE_BYTES",
        "_TRUNCATION_MARKER",
        'expected = "x" * (_MAX_LINE_BYTES - len(_TRUNCATION_MARKER)) + _TRUNCATION_MARKER',
        "assert out == expected",
        'assert len(out.encode("utf-8")) == _MAX_LINE_BYTES',
        'expected_prefix = "中" * (',
        '(_MAX_LINE_BYTES - len(_TRUNCATION_MARKER.encode("utf-8"))) // 3',
        "expected = expected_prefix + _TRUNCATION_MARKER",
        'assert len(out.encode("utf-8")) <= _MAX_LINE_BYTES',
        "expected_truncated = (",
        '"y" * (_MAX_LINE_BYTES - len(_TRUNCATION_MARKER)) + _TRUNCATION_MARKER',
        '{"stream": "stderr", "line": expected_truncated}',
        'assert second == {"stream": "stderr", "line": expected_truncated}',
    ]:
        assert expected in truncation_block
    assert 'assert out.endswith("...[truncated]")' not in truncation_block
    assert 'assert second["line"].endswith("...[truncated]")' not in truncation_block


def test_quality_ops_capture_scheduler_dequeue_capacity_metadata_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "FairScheduler dequeue capacity stop 元数据精确契约"
    )
    worker_scheduler_test = _read(WORKER_SCHEDULER_TEST)

    assert "FairScheduler dequeue capacity stop 元数据精确契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_scheduler.py::test_try_dequeue_waiting_enqueues_until_capacity_is_full` 1 passed"
        in quality_ops
    )
    assert "`find_waiting(limit=10)`" in quality_ops
    assert "global active count 两次" in quality_ops
    assert "project active count 只检查第一条 waiting run" in quality_ops
    assert "medium queue / `run:{id}` job id" in quality_ops
    assert "`mark_enqueued` 写入同一 queue/job/timezone-aware enqueued_at" in (
        quality_ops
    )
    assert "`repo.mark_enqueued.await_count == 1`" in quality_ops
    assert "错误队列、漏写 arq_job_id/queue_name/enqueued_at" in quality_ops
    assert "容量满前入队了一个 run" in quality_ops
    assert 'arq = _arq(job_id="job-first")' in worker_scheduler_test
    assert "repo.find_waiting.assert_awaited_once_with(limit=10)" in (
        worker_scheduler_test
    )
    assert "repo.count_active_or_enqueued.await_args_list" in worker_scheduler_test
    assert "repo.count_active_or_enqueued_by_project.await_args_list" in (
        worker_scheduler_test
    )
    assert "_queue_name=PRIORITY_QUEUES[Priority.MEDIUM]" in worker_scheduler_test
    assert '_job_id=f"run:{first.id}"' in worker_scheduler_test
    assert "_assert_mark_enqueued(" in worker_scheduler_test
    assert "queue_name=PRIORITY_QUEUES[Priority.MEDIUM]" in (
        worker_scheduler_test
    )
    assert 'arq_job_id="job-first"' in worker_scheduler_test
    assert 'assert enqueued_at.tzinfo is not None' in (
        worker_scheduler_test
    )
    assert "repo.mark_waiting.assert_not_awaited()" in worker_scheduler_test
    assert "assert repo.mark_enqueued.await_count == 1" not in worker_scheduler_test


def test_quality_ops_capture_scheduler_queue_choice_exact_metadata_contract():
    quality_ops = _quality_ops_row_containing(
        "FairScheduler queue choice exact enqueue metadata 契约"
    )
    worker_scheduler_test = _read(WORKER_SCHEDULER_TEST)
    helper_row = _quality_ops_row(
        "| 2026-05-31 | N/A（FairScheduler mark_enqueued direct kwargs helper follow-up）"
    )

    assert "FairScheduler queue choice exact enqueue metadata 契约" in quality_ops
    assert "invalid manual priority、schedule trigger、manual priority matrix" in (
        quality_ops
    )
    assert "explicit trigger override 用例现在固定完整" in quality_ops
    assert '`arq.enqueue_job("execute_run", str(run.id), _queue_name, _job_id, _defer_by=0)`' in (
        quality_ops
    )
    assert "`mark_enqueued(run.id, queue_name, arq_job_id, timezone-aware enqueued_at)`" in (
        quality_ops
    )
    assert "主要只看 `_queue_name`" in quality_ops
    assert "DB 仍写错队列名" in quality_ops
    assert "队列名看起来对" in quality_ops
    assert "FairScheduler mark_enqueued direct kwargs helper follow-up" in helper_row
    assert "`tests/unit/test_worker/test_scheduler.py` 14 passed" in helper_row
    assert "targeted docs contract passed" in helper_row
    assert "targeted ruff/py_compile passed" in helper_row
    assert "统一 `_assert_mark_enqueued`" in helper_row
    assert "完整等值 `{queue_name,arq_job_id,enqueued_at}`" in helper_row
    assert "逐字段抽查 `repo.mark_enqueued.await_args.kwargs[...]`" in helper_row
    assert "只证明“几个 kwargs 子字段对”" in helper_row

    queue_choice_block = _marked_block(
        worker_scheduler_test,
        "async def test_enqueue_falls_back_to_medium_for_invalid_manual_priority",
        "async def test_enqueue_job_conflict_is_idempotent_for_same_enqueued_run",
    )
    explicit_block = _marked_block_or_tail(
        worker_scheduler_test,
        "async def test_enqueue_run_convenience_uses_explicit_trigger_type_for_queue",
        "\n\n@pytest.mark.asyncio",
    )

    assert queue_choice_block.count("arq.enqueue_job.assert_awaited_once_with(") == 3
    assert "_queue_name=PRIORITY_QUEUES[Priority.MEDIUM]" in queue_choice_block
    assert "_queue_name=PRIORITY_QUEUES[Priority.LOW]" in queue_choice_block
    assert "_queue_name=PRIORITY_QUEUES[expected]" in queue_choice_block
    assert '_job_id=f"run:{run.id}"' in queue_choice_block
    assert "_defer_by=0" in queue_choice_block
    assert "def _assert_mark_enqueued(" in worker_scheduler_test
    assert "assert mark_args.kwargs == {" in worker_scheduler_test
    assert '"queue_name": queue_name' in worker_scheduler_test
    assert '"arq_job_id": arq_job_id' in worker_scheduler_test
    assert '"enqueued_at": enqueued_at' in worker_scheduler_test
    assert queue_choice_block.count("_assert_mark_enqueued(") == 3
    assert "repo.mark_enqueued.await_args.kwargs[" not in queue_choice_block
    assert "arq.enqueue_job.assert_awaited_once_with(" in explicit_block
    assert "_queue_name=PRIORITY_QUEUES[Priority.LOW]" in explicit_block
    assert "_assert_mark_enqueued(" in explicit_block
    assert 'arq_job_id="job-1"' in explicit_block
    assert "repo.mark_enqueued.await_args.kwargs[" not in explicit_block
    assert 'arq.enqueue_job.await_args.kwargs["_queue_name"]' not in (
        worker_scheduler_test
    )


def test_quality_ops_capture_scheduler_arq_conflict_exact_dedup_contract():
    worker_scheduler_test = _read(WORKER_SCHEDULER_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（FairScheduler ARQ conflict exact dedup 契约）"
    )

    assert "FairScheduler ARQ conflict exact dedup 契约" in row
    assert (
        "`tests/unit/test_worker/test_scheduler.py::test_enqueue_job_conflict_is_idempotent_for_same_enqueued_run tests/unit/test_worker/test_scheduler.py::test_enqueue_job_conflict_marks_waiting_for_different_run` 2 passed"
        in row
    )
    assert "scheduler full 14 passed" in row
    assert "release quality docs contract full 284 passed" in row
    assert "targeted ruff passed" in row
    assert '`enqueue_job("execute_run", str(run.id), queue:medium, run:{id}, _defer_by=0)`' in (
        row
    )
    assert '`get_by_arq_job_id("run:{id}")`' in row
    assert "同一已入队 run 不写 waiting/mark_enqueued" in row
    assert "不同 run 冲突只写 waiting reason" in row
    assert "dedup 查询 key 漂移" in row
    assert "ARQ job id 不再等于 `run:{id}`" in row
    assert "冲突时误写 `mark_enqueued`" in row
    assert "返回值方向大概对" in row

    idempotent_block = _marked_block(
        worker_scheduler_test,
        "async def test_enqueue_job_conflict_is_idempotent_for_same_enqueued_run",
        "async def test_enqueue_job_conflict_marks_waiting_for_different_run",
    )
    different_block = _marked_block(
        worker_scheduler_test,
        "async def test_enqueue_job_conflict_marks_waiting_for_different_run",
        "async def test_try_dequeue_waiting_enqueues_until_capacity_is_full",
    )

    for block in (idempotent_block, different_block):
        assert "arq.enqueue_job = AsyncMock(return_value=None)" in block
        assert "arq.enqueue_job.assert_awaited_once_with(" in block
        assert '"execute_run",' in block
        assert "str(run.id)," in block
        assert "_queue_name=PRIORITY_QUEUES[Priority.MEDIUM]" in block
        assert '_job_id=f"run:{run.id}"' in block
        assert "_defer_by=0" in block
        assert 'repo.get_by_arq_job_id.assert_awaited_once_with(f"run:{run.id}")' in (
            block
        )
        assert "repo.mark_enqueued.assert_not_awaited()" in block

    assert "repo.mark_waiting.assert_not_awaited()" in idempotent_block
    assert "repo.mark_waiting.assert_awaited_once_with(" in different_block
    assert 'reason=f"arq job id conflict: run:{run.id}",' in different_block


def test_quality_ops_capture_scheduler_capacity_short_circuit_exact_contract():
    worker_scheduler_test = _read(WORKER_SCHEDULER_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（FairScheduler capacity short-circuit exact side-effect 契约）"
    )

    assert "FairScheduler capacity short-circuit exact side-effect 契约" in row
    assert (
        "`tests/unit/test_worker/test_scheduler.py::test_enqueue_marks_waiting_when_global_capacity_is_full tests/unit/test_worker/test_scheduler.py::test_enqueue_marks_waiting_when_project_capacity_is_full` 2 passed"
        in row
    )
    assert "scheduler full 14 passed" in row
    assert "release quality docs contract full 285 passed" in row
    assert "targeted ruff passed" in row
    assert "全局容量满现在固定只查 global count、不查 project count" in row
    assert "不入 ARQ、不写 mark_enqueued/get_by_arq_job_id" in row
    assert "项目容量满现在固定先查 global 再查 project" in row
    assert "只写 waiting、不入 ARQ、不写 enqueued/dedup 查询" in row
    assert "此前只断言返回 False 和 `mark_waiting(run.id)`" in row
    assert "全局满仍继续查项目" in row
    assert "容量满仍触发 ARQ 或误写 enqueued metadata" in row
    assert "最后变成 waiting" in row

    global_block = _marked_block(
        worker_scheduler_test,
        "async def test_enqueue_marks_waiting_when_global_capacity_is_full",
        "async def test_enqueue_marks_waiting_when_project_capacity_is_full",
    )
    project_block = _marked_block(
        worker_scheduler_test,
        "async def test_enqueue_marks_waiting_when_project_capacity_is_full",
        "async def test_enqueue_uses_manual_priority_queue_and_records_metadata",
    )

    assert "repo.count_active_or_enqueued.assert_awaited_once_with()" in global_block
    assert "repo.count_active_or_enqueued_by_project.assert_not_awaited()" in (
        global_block
    )
    assert "repo.mark_waiting.assert_awaited_once_with(run.id)" in global_block
    assert "repo.mark_enqueued.assert_not_awaited()" in global_block
    assert "repo.get_by_arq_job_id.assert_not_awaited()" in global_block
    assert "arq.enqueue_job.assert_not_awaited()" in global_block

    assert "repo.count_active_or_enqueued.assert_awaited_once_with()" in project_block
    assert (
        "repo.count_active_or_enqueued_by_project.assert_awaited_once_with(run.project_id)"
        in project_block
    )
    assert "repo.mark_waiting.assert_awaited_once_with(run.id)" in project_block
    assert "repo.mark_enqueued.assert_not_awaited()" in project_block
    assert "repo.get_by_arq_job_id.assert_not_awaited()" in project_block
    assert "scheduler.arq.enqueue_job.assert_not_awaited()" in project_block


def test_quality_ops_capture_log_stream_archive_retry_s3_ttl_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "LogStream archive retry S3/TTL 精确契约"
    )
    log_stream_test = _read(LOG_STREAM_TEST)

    assert "LogStream archive retry S3/TTL 精确契约" in quality_ops
    assert (
        "`tests/unit/test_engine/test_log_stream.py::TestLogStream::test_retry_failed_archives_replays_recorded_runs` 1 passed"
        in quality_ops
    )
    assert "retry set 两个 run 的 `xread` cursor 序列" in quality_ops
    assert "只上传成功 run 的 `logs/{run_id}.jsonl`" in quality_ops
    assert "S3 `Bucket/Key/Body/ContentType` 精确匹配" in quality_ops
    assert "成功 run 写 1h stream TTL 并清 retry marker" in quality_ops
    assert "失败 run 写 24h TTL 并保留 retry marker" in quality_ops
    assert "`s3_client.put_object.await_count == 1`" in quality_ops
    assert "上传错 bucket/key/body/content-type" in quality_ops
    assert "归档补偿测试只证明“某次重试上传了一次”" in quality_ops
    assert "assert self.redis.xread.await_args_list == [" in log_stream_test
    assert 'call({f"run:{self.run_id}:logs": "0"}, count=500)' in log_stream_test
    assert 'call({f"run:{self.run_id}:logs": "1-0"}, count=500)' in log_stream_test
    assert 'call({f"run:{failed_run}:logs": "0"}, count=500)' in log_stream_test
    assert "s3_client.put_object.assert_awaited_once_with(" in log_stream_test
    assert 'Key=f"logs/{self.run_id}.jsonl"' in log_stream_test
    assert 'Body=b\'{"stream": "stdout", "line": "ok"}\'' in log_stream_test
    assert 'ContentType="application/x-ndjson"' in log_stream_test
    assert "assert self.redis.expire.await_args_list == [" in log_stream_test
    assert "call(f\"run:{self.run_id}:logs\", _STREAM_TTL)" in log_stream_test
    assert "call(f\"run:{failed_run}:logs\", _ARCHIVE_FAILURE_TTL)" in (
        log_stream_test
    )
    assert "self.redis.srem.assert_awaited_once_with" in log_stream_test
    assert "self.redis.sadd.assert_awaited_once_with" in log_stream_test
    assert "assert s3_client.put_object.await_count == 1" not in log_stream_test


def test_quality_ops_capture_cancel_watcher_repeated_message_keeps_listening():
    quality_ops = _quality_ops_row_containing(
        "Cancel watcher repeated message 持续监听契约"
    )
    cancel_test = _read(ENGINE_CANCEL_TEST)

    assert "Cancel watcher repeated message 持续监听契约" in quality_ops
    assert (
        "`tests/unit/test_engine/test_cancel.py::TestWatchForCancel::test_callback_invoked_for_each_message` 1 passed"
        in quality_ops
    )
    assert "两个 Event 等待每次 callback" in quality_ops
    assert "第一条和第二条消息处理后都断言 watcher task 仍未结束" in quality_ops
    assert "第一条后没有 unsubscribe/close" in quality_ops
    assert "pubsub stream 关闭后才精确执行两次无参 callback" in quality_ops
    assert "一次 unsubscribe 和 `aclose`" in quality_ops
    assert "`on_cancel.await_count == 2`" in quality_ops
    assert "提前关闭订阅" in quality_ops
    assert "取消监听测试只证明“收到过两次回调”" in quality_ops
    assert "first_seen = asyncio.Event()" in cancel_test
    assert "second_seen = asyncio.Event()" in cancel_test
    assert "await asyncio.wait_for(first_seen.wait(), timeout=1.0)" in cancel_test
    assert "await asyncio.wait_for(second_seen.wait(), timeout=1.0)" in cancel_test
    assert "assert deliveries == [1]" in cancel_test
    assert "assert deliveries == [1, 2]" in cancel_test
    assert "assert not task.done()" in cancel_test
    assert "assert pubsub.unsubscribed == []" in cancel_test
    assert "assert pubsub.closed_with is None" in cancel_test
    assert "assert on_cancel.await_args_list == [call(), call()]" in cancel_test
    assert 'assert pubsub.unsubscribed == [f"{CANCEL_CHANNEL_PREFIX}r"]' in (
        cancel_test
    )
    assert 'assert pubsub.closed_with == "aclose"' in cancel_test
    assert "assert on_cancel.await_count == 2" not in cancel_test


def test_quality_ops_capture_cancel_watcher_handler_exception_exact_log_contract():
    cancel_test = _read(ENGINE_CANCEL_TEST)

    new_row = _quality_ops_row("| 2026-05-31 | N/A（Cancel watcher handler exception direct error projection 契约）")
    row = _quality_ops_row("| 2026-05-31 | N/A（Cancel watcher handler exception exact continuation/log 契约）")

    assert (
        "`tests/unit/test_engine/test_cancel.py::TestWatchForCancel::test_swallows_handler_exceptions` "
        "1 passed"
        in row
    )
    assert "release quality docs contract full 339 passed" in new_row
    assert "ERROR 投影为 `{levelno,message,exc_type,exc_message}`" in new_row
    assert "task 不退出" in new_row
    assert "第二条 cancel 仍触发 callback" in new_row
    assert "`len(error_records) == 1` 与 `error_records[0]`" in new_row
    assert "direct error projection 契约" in new_row
    assert "有一条错误日志看起来对" in new_row
    assert "cancel full 16 passed" in row
    assert "release quality docs contract full 222 passed" in row
    assert "targeted ruff passed" in row
    assert "第一条 cancel 抛 `RuntimeError(\"boom\")` 后 task 仍未结束" in row
    assert "第二条 cancel 继续触发无参 callback" in row
    assert "`qaplatform.engine.cancel` ERROR 投影唯一" in row
    assert "message 精确为 `cancel handler raised for run r`" in row
    assert "exc_info 保留原始异常" in row
    assert "只断言 `caplog.text` 包含错误文案" in row
    assert "handler 异常后 watcher 提前退出" in row
    assert "日志级别漂移" in row
    assert "日志里有一句话且任务没炸" in row

    block = _marked_block(
        cancel_test,
        "async def test_swallows_handler_exceptions",
        "# --------------------------------------------------------------------------- #\n"
        "# RunExecutor._handle_cancel_signal",
    )

    assert "on_cancel = AsyncMock(side_effect=[RuntimeError(\"boom\"), None])" in block
    assert "assert not task.done()" in block
    assert "assert on_cancel.await_args_list == [call(), call()]" in block
    assert "record.name == \"qaplatform.engine.cancel\"" in block
    assert "record.levelno == logging.ERROR" in block
    assert '"levelno": record.levelno' in block
    assert '"message": record.getMessage()' in block
    assert '"exc_type": (' in block
    assert '"exc_message": (' in block
    assert "assert error_records == [" in block
    assert '"levelno": logging.ERROR' in block
    assert '"message": "cancel handler raised for run r"' in block
    assert '"exc_type": "RuntimeError"' in block
    assert '"exc_message": "boom"' in block
    assert 'assert pubsub.unsubscribed == [f"{CANCEL_CHANNEL_PREFIX}r"]' in block
    assert 'assert pubsub.closed_with == "aclose"' in block
    assert "assert \"cancel handler raised for run r\" in caplog.text" not in block
    assert "assert len(error_records) == 1" not in block
    assert "error_records[0]" not in block


def test_quality_ops_capture_check_schedules_commit_order_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "Check schedules run trigger commit 顺序精确契约"
    )
    check_schedules_test = _read(WORKER_CHECK_SCHEDULES_TEST)
    happy_block = _marked_block(
        check_schedules_test,
        "async def test_fires_due_schedule",
        "async def test_skips_in_quiet_window",
    )

    assert "Check schedules run trigger commit 顺序精确契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_check_schedules.py::TestCheckSchedules::test_fires_due_schedule` 1 passed"
        in quality_ops
    )
    assert "create run、set retry group、第一次 commit、enqueue、audit、update_after_fire、第二次 commit" in (
        quality_ops
    )
    assert "run 在入队前已提交" in quality_ops
    assert "schedule 更新和 audit 进入第二个事务" in quality_ops
    assert "`ctx_session.commit.await_count == 2`" in quality_ops
    assert "把 enqueue 放到 run commit 之前" in quality_ops
    assert "schedule worker 主路径测试只证明“提交过两次”" in quality_ops
    assert "operations = []" in happy_block
    assert "ctx_session.commit.side_effect = _commit" in happy_block
    assert "patch(\"qaplatform.worker.scheduler.enqueue_run\", AsyncMock(side_effect=_enqueue))" in (
        happy_block
    )
    assert "assert [operation[0] for operation in operations] == [" in (
        happy_block
    )
    for operation in [
        '"create_run",',
        '"set_retry_group",',
        '"commit",',
        '"enqueue",',
        '"audit_create",',
        '"update_after_fire",',
    ]:
        assert operation in happy_block
    assert "assert ctx_session.commit.await_count == 2" not in happy_block


def test_quality_ops_capture_check_schedules_failure_update_audit_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "Check schedules failure update/audit 精确契约"
    )
    check_schedules_test = _read(WORKER_CHECK_SCHEDULES_TEST)

    assert "Check schedules failure update/audit 精确契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_check_schedules.py::TestCheckSchedules::test_handles_pipeline_not_found tests/unit/test_worker/test_check_schedules.py::TestCheckSchedules::test_handles_enqueue_failure` 2 passed"
        in quality_ops
    )
    assert "check_schedules full 9 passed" in quality_ops
    assert "固定 `update_after_fire` args/kwargs、`next_run_at`、commit 边界" in (
        quality_ops
    )
    assert "无 env/run/enqueue 副作用" in quality_ops
    assert "skipped/run.trigger audit 的完整 payload" in quality_ops
    assert "enqueue failure 还锁住 run.create、set retry group 和 enqueue 参数" in (
        quality_ops
    )
    assert "此前只看 `last_error` 和少量 audit 字段" in quality_ops
    assert "missing pipeline 仍创建 run/enqueue" in quality_ops
    assert "schedule worker 失败测试只证明“错误字符串被写过”" in quality_ops

    missing_block = _marked_block(
        check_schedules_test,
        "async def test_handles_pipeline_not_found",
        "async def test_handles_project_not_found_commits_schedule_error_without_side_effects",
    )
    enqueue_block = _marked_block(
        check_schedules_test,
        "async def test_handles_enqueue_failure",
        "async def test_no_session_factory",
    )

    for block in (missing_block, enqueue_block):
        assert "schedule_repo.update_after_fire.assert_awaited_once()" in block
        assert "update_args = schedule_repo.update_after_fire.await_args" in block
        assert "assert update_args.args == (sample_schedule.id,)" in block
        assert 'assert update_args.kwargs["last_run_at"].tzinfo is not None' in block
        assert 'assert update_args.kwargs["next_run_at"] == next_run_at' in block
        assert "assert audit_kwargs == {" in block
        assert '"before_state": None' in block
        assert "ctx_session = ctx[" in block

    assert 'assert update_args.kwargs["last_error"] == "pipeline not found"' in (
        missing_block
    )
    assert "compute_next_run_at.assert_called_once_with(" in missing_block
    assert "env_repo.list_by_project.assert_not_awaited()" in missing_block
    assert "run_repo.create.assert_not_awaited()" in missing_block
    assert "run_repo.set_retry_group_id.assert_not_awaited()" in missing_block
    assert "mock_enqueue.assert_not_awaited()" in missing_block
    assert '"action": "schedule_skipped_missing_pipeline"' in missing_block
    assert '"resource_type": "schedule"' in missing_block
    assert '"reason": "pipeline_not_found"' in missing_block
    assert "ctx_session.commit.assert_awaited_once()" in missing_block

    assert "run_repo.create.assert_awaited_once_with(" in enqueue_block
    assert "run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)" in (
        enqueue_block
    )
    assert "mock_enqueue.assert_awaited_once_with(" in enqueue_block
    assert 'assert update_args.kwargs["last_error"] == "enqueue failed"' in (
        enqueue_block
    )
    assert '"action": "run.trigger"' in enqueue_block
    assert '"resource_type": "run"' in enqueue_block
    assert '"enqueued": False' in enqueue_block
    assert "ctx_session.commit.assert_has_awaits([call(), call()])" in enqueue_block
    assert "assert ctx_session.commit.await_count == 2" not in enqueue_block

    assert 'call_kwargs = schedule_repo.update_after_fire.await_args.kwargs' not in (
        missing_block + enqueue_block
    )
    assert 'assert call_kwargs["last_error"] == "pipeline not found"' not in (
        missing_block
    )
    assert 'assert call_kwargs["last_error"] == "enqueue failed"' not in (
        enqueue_block
    )


def test_quality_ops_capture_check_schedules_enqueue_failure_commit_order_exact_contract():
    check_schedules_test = _read(WORKER_CHECK_SCHEDULES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Check schedules enqueue failure exact commit order 契约）"
    )

    assert "Check schedules enqueue failure exact commit order 契约" in row
    assert (
        "`tests/unit/test_worker/test_check_schedules.py::TestCheckSchedules::test_handles_enqueue_failure` 1 passed"
        in row
    )
    assert "check_schedules full 9 passed" in row
    assert "release quality docs contract full 288 passed" in row
    assert "targeted ruff passed" in row
    assert "create run、set retry group、第一次 commit、enqueue 返回 False" in row
    assert "run.trigger audit、update_after_fire(enqueue failed)、第二次 commit" in row
    assert "`ctx_session.commit.await_count == 2`" in row
    assert "enqueue 放到 run 提交前" in row
    assert "提交过两次" in row

    enqueue_block = _marked_block(
        check_schedules_test,
        "async def test_handles_enqueue_failure",
        "async def test_no_session_factory",
    )

    assert "from unittest.mock import AsyncMock, MagicMock, call, patch" in (
        check_schedules_test
    )
    for expected in [
        "operations = []",
        "async def create_run(**kwargs):",
        'operations.append(("create", kwargs["trigger_type"], kwargs["metadata_"]["schedule_id"]))',
        "run_repo.create = AsyncMock(side_effect=create_run)",
        "async def set_retry_group(source_run_id, retry_group_id):",
        'operations.append(("set_retry_group", source_run_id, retry_group_id))',
        "run_repo.set_retry_group_id = AsyncMock(side_effect=set_retry_group)",
        "async def create_audit(**kwargs):",
        'operations.append(("audit", kwargs["resource_id"], kwargs["after_state"]["enqueued"]))',
        "audit_repo.create = AsyncMock(side_effect=create_audit)",
        "async def commit_session():",
        'operations.append(("commit", None, None))',
        "ctx_session.commit.side_effect = commit_session",
        "async def enqueue_failed(arq, repo, queued_run, trigger_type, settings):",
        'operations.append(("enqueue", queued_run.id, trigger_type))',
        "return False",
        "new=AsyncMock(side_effect=enqueue_failed)",
        "async def update_after_fire(schedule_id, **kwargs):",
        'operations.append(("update_after_fire", schedule_id, kwargs["last_error"]))',
        "schedule_repo.update_after_fire = AsyncMock(side_effect=update_after_fire)",
        "ctx_session.commit.assert_has_awaits([call(), call()])",
        "assert operations == [",
        '("create", "schedule", str(sample_schedule.id))',
        '("set_retry_group", run.id, run.id)',
        '("commit", None, None)',
        '("enqueue", run.id, "schedule")',
        '("audit", run.id, False)',
        '("update_after_fire", sample_schedule.id, "enqueue failed")',
    ]:
        assert expected in enqueue_block
    assert "assert ctx_session.commit.await_count == 2" not in enqueue_block


def test_quality_ops_capture_check_schedules_silent_window_audit_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "Schedule silent-window audit exact payload 契约"
    )
    check_schedules_test = _read(WORKER_CHECK_SCHEDULES_TEST)
    silent_block = _marked_block(
        check_schedules_test,
        "async def test_skips_project_silent_window_without_creating_run",
        "async def test_handles_enqueue_failure",
    )

    assert "Schedule silent-window audit exact payload 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_check_schedules.py::TestCheckSchedules::test_skips_project_silent_window_without_creating_run` 1 passed"
        in quality_ops
    )
    assert "check_schedules full 9 passed" in quality_ops
    assert "release quality docs contract full 216 passed" in quality_ops
    assert "tenant/user/action/resource/before_state/after_state 完整等值" in (
        quality_ops
    )
    assert "窗口 start/end 以 JSON `Z` 时间序列化" in quality_ops
    assert "此前只抽查 audit action、schedule_id 和 window reason" in (
        quality_ops
    )
    assert "silent-window 单测只证明“跳过时写过一条大概对的审计”" in (
        quality_ops
    )

    assert "assert audit_kwargs == {" in silent_block
    assert '"action": "schedule_skipped_silent_window"' in silent_block
    assert '"resource_type": "schedule"' in silent_block
    assert '"resource_id": sample_schedule.id' in silent_block
    assert '"before_state": None' in silent_block
    assert '"after_state": {' in silent_block
    assert '"schedule_id": str(sample_schedule.id)' in silent_block
    assert '"window": {' in silent_block
    assert '"start_at": window["start_at"].isoformat().replace("+00:00", "Z")' in (
        silent_block
    )
    assert '"end_at": window["end_at"].isoformat().replace("+00:00", "Z")' in (
        silent_block
    )
    assert '"reason": "planned maintenance"' in silent_block
    assert "env_repo.list_by_project.assert_not_awaited()" in silent_block
    assert "run_repo.create.assert_not_awaited()" in silent_block
    assert "mock_enqueue.assert_not_awaited()" in silent_block
    assert "schedule_repo.update_after_fire.assert_not_awaited()" in silent_block
    assert "ctx_session.commit.assert_awaited_once()" in silent_block
    assert 'audit_kwargs["action"]' not in silent_block
    assert 'audit_kwargs["after_state"]["window"]["reason"]' not in silent_block


def test_quality_ops_capture_log_stream_archive_success_cursor_s3_exact_contract():
    log_stream_test = _read(LOG_STREAM_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（LogStream archive success cursor/S3 exact 契约）"
    )

    assert "LogStream archive success cursor/S3 exact 契约" in row
    assert (
        "`tests/unit/test_engine/test_log_stream.py::TestLogStream::test_archive_logs_success` 1 passed"
        in row
    )
    assert "log stream full 18 passed" in row
    assert "release quality docs contract full 184 passed" in row
    assert "Redis `xread` cursor 序列 `0 -> 2-0`" in row
    assert "S3 `Bucket/Key/Body/ContentType` 精确参数" in row
    assert "1h stream TTL 和清除 retry marker" in row
    assert "`put_object.assert_awaited_once()` 后抽查 bucket/key/content-type" in row
    assert "游标没推进" in row
    assert "只证明“上传过一个能解析的 JSONL”" in row

    test_block = _marked_block(
        log_stream_test,
        "async def test_archive_logs_success",
        "async def test_archive_logs_failure_sets_long_ttl",
    )

    for expected in [
        "assert self.redis.xread.await_args_list == [",
        'call({f"run:{self.run_id}:logs": "0"}, count=500)',
        'call({f"run:{self.run_id}:logs": "2-0"}, count=500)',
        "expected_body = (",
        'b\'{"stream": "stdout", "line": "line1"}\\n\'',
        'b\'{"stream": "stdout", "line": "line2"}\'',
        "s3_client.put_object.assert_awaited_once_with(",
        'Bucket="qa-platform"',
        'Key=f"logs/{self.run_id}.jsonl"',
        "Body=expected_body",
        'ContentType="application/x-ndjson"',
        "self.redis.expire.assert_awaited_once_with(",
        "self.redis.srem.assert_awaited_once_with(_ARCHIVE_RETRY_SET, str(self.run_id))",
    ]:
        assert expected in test_block
    assert "s3_client.put_object.assert_awaited_once()\n" not in test_block
    assert 'call_kwargs["Bucket"]' not in test_block
