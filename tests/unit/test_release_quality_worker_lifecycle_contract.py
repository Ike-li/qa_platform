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
ENGINE_RECLAIM_TEST = ROOT / "tests" / "unit" / "test_engine" / "test_reclaim.py"
WORKER_AUTO_RETRY_TEST = (
    ROOT / "tests" / "unit" / "test_worker" / "test_auto_retry.py"
)
WORKER_TASKS_TEST = ROOT / "tests" / "unit" / "test_worker" / "test_tasks.py"


def test_quality_ops_capture_worker_claim_commit_sequence_contract():
    quality_ops = _quality_ops_row_containing(
        "Worker claim row-lock commit 顺序契约"
    )
    worker_tasks_test = _read(WORKER_TASKS_TEST)

    assert "Worker claim row-lock commit 顺序契约" in quality_ops
    assert "记录 `claim -> commit -> execute`" in quality_ops
    assert "不再只断言 `session.commit` 至少调用一次" in quality_ops
    assert 'call_log[:3] == ["claim", "commit", "execute"]' in worker_tasks_test
    assert "commit.await_count >= 1" not in worker_tasks_test


def test_quality_ops_capture_worker_claim_none_no_side_effect_contract():
    quality_ops = _quality_ops_row_containing("Worker claim none 无副作用契约")
    worker_tasks_test = _read(WORKER_TASKS_TEST)

    assert "Worker claim none 无副作用契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_tasks.py::TestClaimReleasesRowLock::test_no_commit_when_claim_returns_none` 1 passed"
        in quality_ops
    )
    assert "不 commit、不 refresh、不查 project" in quality_ops
    assert "不会发布 preparing/cancelled status event" in quality_ops
    assert "不会执行 RunExecutor" in quality_ops
    assert "`mock_session.commit.await_count == 0`" in quality_ops
    assert "误发状态事件、刷新不存在的 run、查 project 或触发 executor" in quality_ops
    assert "claim 失败测试只证明“没提交事务”" in quality_ops
    assert "publish_status_event = AsyncMock()" in worker_tasks_test
    assert "executor = AsyncMock()" in worker_tasks_test
    assert "mock_session.commit.assert_not_awaited()" in worker_tasks_test
    assert "mock_session.refresh.assert_not_awaited()" in worker_tasks_test
    assert "mock_session.execute.assert_not_awaited()" in worker_tasks_test
    assert "publish_status_event.assert_not_awaited()" in worker_tasks_test
    assert "executor.execute.assert_not_awaited()" in worker_tasks_test
    assert "assert mock_session.commit.await_count == 0" not in worker_tasks_test


def test_quality_ops_capture_heartbeat_redis_set_parameter_contract():
    quality_ops = _quality_ops_rows_containing(
        "Heartbeat transient Redis error 确定性循环契约",
        "Heartbeat transient Redis error 参数契约",
    )
    worker_tasks_test = _read(WORKER_TASKS_TEST)

    assert "Heartbeat transient Redis error 确定性循环契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_tasks.py::TestHeartbeatLoop::test_heartbeat_continues_after_redis_error` 1 passed"
        in quality_ops
    )
    assert "受控 `asyncio.sleep` side effect 精确驱动失败后两次成功写入" in (
        quality_ops
    )
    assert "第三次 sleep 抛出 CancelledError" in quality_ops
    assert "三次 sleep interval、三次 Redis heartbeat key、UTC ISO timestamp 与 `ex=90` TTL" in (
        quality_ops
    )
    assert "真实 `sleep(0.2)` 和 `redis.set.await_count >= 3` 下界" in (
        quality_ops
    )
    assert "确定性三轮循环契约" in quality_ops
    assert "Heartbeat transient Redis error 参数契约" in quality_ops
    assert "逐次校验 heartbeat key、UTC ISO timestamp 与 `ex=90` TTL" in quality_ops
    assert "sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError])" in (
        worker_tasks_test
    )
    assert 'patch("qaplatform.worker.tasks.asyncio.sleep", new=sleep)' in (
        worker_tasks_test
    )
    assert "set_call.args[0] for set_call in redis.set.await_args_list" in (
        worker_tasks_test
    )
    assert "sleep_call.args for sleep_call in sleep.await_args_list" in (
        worker_tasks_test
    )
    assert "for set_call in redis.set.await_args_list:" in worker_tasks_test
    assert "key, timestamp = set_call.args" in worker_tasks_test
    assert 'key == f"worker:{worker_id}:heartbeat"' in worker_tasks_test
    assert "datetime.fromisoformat(timestamp)" in worker_tasks_test
    assert 'set_call.kwargs == {"ex": 90}' in worker_tasks_test
    assert "assert len(redis.set.await_args_list) == 3" not in worker_tasks_test
    assert "assert redis.set.await_count >= 3" not in worker_tasks_test
    assert "await asyncio.sleep(0.2)" not in worker_tasks_test


def test_quality_ops_capture_worker_early_cancel_release_order_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "Worker early cancel release 顺序精确契约"
    )
    worker_tasks_test = _read(WORKER_TASKS_TEST)

    assert "Worker early cancel release 顺序精确契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_tasks.py::TestArchiveBlocking::test_worker_releases_claim_when_run_was_already_cancel_requested` 1 passed"
        in quality_ops
    )
    assert "claim、第一次 commit、preparing status event、refresh、cancel_if_current、cancelled status event、release_worker、第二次 commit" in (
        quality_ops
    )
    assert "project lookup 的 `session.execute` 一旦被触碰就失败" in quality_ops
    assert "`mock_session.execute.await_count == 0`" in quality_ops
    assert "`mock_session.commit.await_count == 2`" in quality_ops
    assert "第一次 commit 挪到取消之后" in quality_ops
    assert "worker 早退取消测试只证明“没执行容器且提交过两次”" in quality_ops
    assert "operations = []" in worker_tasks_test
    assert "mock_session.execute = AsyncMock(" in worker_tasks_test
    assert "cancel-requested fast path must not query project" in worker_tasks_test
    assert "publish_status_event = AsyncMock(side_effect=_publish)" in worker_tasks_test
    assert "mock_session.execute.assert_not_awaited()" in worker_tasks_test
    assert "assert [operation[0] for operation in operations] == [" in (
        worker_tasks_test
    )
    for operation in [
        '"claim",',
        '"commit",',
        '"publish",',
        '"refresh",',
        '"cancel",',
        '"release",',
    ]:
        assert operation in worker_tasks_test
    assert '(ctx["redis"], str(fake_run.id), "preparing")' in worker_tasks_test
    assert '(ctx["redis"], str(fake_run.id), "cancelled")' in worker_tasks_test
    assert '{"worker_id": "worker-test"}' in worker_tasks_test
    assert "assert mock_session.execute.await_count == 0" not in worker_tasks_test
    assert "assert mock_session.commit.await_count == 2" not in worker_tasks_test


def test_quality_ops_capture_worker_source_auth_credential_lookup_exact_filters_contract():
    quality_ops = _quality_ops_row_containing(
        "Worker source auth credential lookup exact filters 契约"
    )
    worker_tasks_test = _read(WORKER_TASKS_TEST)

    assert "Worker source auth credential lookup exact filters 契约" in quality_ops
    assert (
        "`tests/unit/test_worker/test_tasks.py::test_build_source_auth_rejects_type_mismatch` 1 passed"
        in quality_ops
    )
    assert "worker tasks full 19 passed" in quality_ops
    assert "release quality docs contract full 346 passed" in quality_ops
    assert "exact RuntimeError 与 no-decrypt" in quality_ops
    assert "`credential.id/project_id/tenant_id/deleted_at IS NULL`" in quality_ops
    assert "从 rendered SQL 逐列提取绑定参数" in quality_ops
    assert "`credential.project_id -> project.id`" in quality_ops
    assert "`credential.tenant_id -> project.tenant_id`" in quality_ops
    assert "`project_id` / `tenant_id` 绑定互换" in quality_ops
    assert "漏掉 tenant/project 过滤" in quality_ops
    assert "允许软删除 credential" in quality_ops
    assert "把租户/项目过滤串错" in quality_ops
    assert "查过一条凭据并拒绝了解密" in quality_ops

    type_mismatch_block = _marked_block(
        worker_tasks_test,
        "async def test_build_source_auth_rejects_type_mismatch",
        "@pytest.fixture\ndef mock_session",
    )

    assert "statement = session.execute.await_args.args[0]" in type_mismatch_block
    assert "compiled = statement.compile(dialect=postgresql.dialect())" in (
        type_mismatch_block
    )
    assert 'assert "credential.id = " in rendered' in type_mismatch_block
    assert 'assert "credential.project_id = " in rendered' in type_mismatch_block
    assert 'assert "credential.tenant_id = " in rendered' in type_mismatch_block
    assert 'assert "credential.deleted_at IS NULL" in rendered' in (
        type_mismatch_block
    )
    assert "for column in [" in type_mismatch_block
    assert "re.search(rf\"{re.escape(column)} = %\\(([^)]+)\\)s\", rendered)" in (
        type_mismatch_block
    )
    assert "bound_values[column] = compiled.params[match.group(1)]" in (
        type_mismatch_block
    )
    assert 'assert bound_values == {' in type_mismatch_block
    assert '"credential.id": project.credential_id' in type_mismatch_block
    assert '"credential.project_id": project.id' in type_mismatch_block
    assert '"credential.tenant_id": project.tenant_id' in type_mismatch_block
    assert "assert set(compiled.params.values())" not in type_mismatch_block
    assert "crypto.decrypt.assert_not_called()" in type_mismatch_block


def test_quality_ops_capture_worker_pipeline_collector_exact_list_contract():
    worker_tasks_test = _read(WORKER_TASKS_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Worker pipeline collector exact list 契约）"
    )

    assert "Worker pipeline collector exact list 契约" in row
    assert (
        "`tests/unit/test_worker/test_tasks.py::test_build_pipeline_config_maps_pipeline_collectors "
        "tests/unit/test_worker/test_tasks.py::test_build_pipeline_config_defaults_to_junit_collector` "
        "2 passed"
        in row
    )
    assert "worker tasks full 19 passed" in row
    assert "release quality docs contract full 206 passed" in row
    assert "targeted ruff passed" in row
    assert "自定义 junit 与 disabled coverage collector 的完整顺序列表" in row
    assert "collectors=None 只生成一个默认 junit collector" in row
    assert "此前只检查 `config.collectors[0]`" in row
    assert "丢掉第二个 collector" in row
    assert "忽略 `enabled=False`" in row
    assert "worker collector 映射测试只证明“第一个 junit 看起来对”" in row

    collectors_block = _marked_block(
        worker_tasks_test,
        "def test_build_pipeline_config_maps_pipeline_collectors",
        "def test_build_pipeline_config_defaults_to_junit_collector",
    )
    default_block = _marked_block(
        worker_tasks_test,
        "def test_build_pipeline_config_defaults_to_junit_collector",
        "@pytest.mark.asyncio",
    )

    assert '"plugin": "junit"' in collectors_block
    assert '"config": {"path": "custom/results.xml"}' in collectors_block
    assert '"plugin": "coverage"' in collectors_block
    assert '"format": "cobertura"' in collectors_block
    assert '"path": "coverage.xml"' in collectors_block
    assert '"enabled": False' in collectors_block
    assert "for collector in config.collectors" in collectors_block
    assert "config.collectors[0]" not in collectors_block
    assert '[{"plugin": "junit", "config": {}, "enabled": True}]' in (
        default_block
    )
    assert "for collector in config.collectors" in default_block
    assert "config.collectors[0]" not in default_block


def test_quality_ops_capture_worker_auto_retry_waiting_exact_order_contract():
    auto_retry_test = _read(WORKER_AUTO_RETRY_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Worker auto retry waiting exact order 契约）"
    )

    assert "Worker auto retry waiting exact order 契约" in row
    assert (
        "`tests/unit/test_worker/test_auto_retry.py::TestAttemptRetry::test_waiting_retry_run_counts_as_scheduled` 1 passed"
        in row
    )
    assert "auto retry full 24 passed" in row
    assert "release quality docs contract full 201 passed" in row
    assert "get_by_id 原 run id" in row
    assert "refresh pipeline" in row
    assert "create -> enqueue(waiting) -> commit" in row
    assert "此前只断言 result/create/enqueue/commit" in row
    assert "提交顺序漂移" in row
    assert "跳过 pipeline refresh" in row
    assert "只证明“waiting 分支碰过几个 mock”" in row

    test_block = _marked_block_or_tail(
        auto_retry_test,
        "async def test_waiting_retry_run_counts_as_scheduled",
        "\n\n@pytest.mark.asyncio",
    )

    for expected in [
        "operations = []",
        "async def create_retry_run(**kwargs):",
        'operations.append(("create", kwargs["attempt"], kwargs["source_run_id"]))',
        "run_repo.create = AsyncMock(side_effect=create_retry_run)",
        "async def enqueue_waiting(run, **kwargs):",
        'operations.append(("enqueue", run.id, kwargs))',
        "scheduler.enqueue = AsyncMock(side_effect=enqueue_waiting)",
        "async def commit_session():",
        'operations.append(("commit", None, {}))',
        "session.commit.side_effect = commit_session",
        "sf.assert_called_once_with()",
        "run_repo.get_by_id.assert_awaited_once_with(str(original.id))",
        'session.refresh.assert_awaited_once_with(original, ["pipeline"])',
        "session.commit.assert_awaited_once_with()",
        "assert operations == [",
        '("create", 2, original.id)',
        '("enqueue", retry_run.id, {"_defer_by": 0})',
        '("commit", None, {})',
    ]:
        assert expected in test_block
    assert "scheduler.enqueue = AsyncMock(return_value=False)" not in test_block
    assert "session.commit.assert_awaited_once()\n" not in test_block


def test_quality_ops_capture_worker_auto_retry_reject_no_side_effect_contract():
    auto_retry_test = _read(WORKER_AUTO_RETRY_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Worker auto retry reject no-side-effect 契约）"
    )

    assert "Worker auto retry reject no-side-effect 契约" in row
    assert (
        "`tests/unit/test_worker/test_auto_retry.py::TestAttemptRetry::test_returns_false_when_should_retry_false tests/unit/test_worker/test_auto_retry.py::TestAttemptRetry::test_returns_false_when_original_not_found tests/unit/test_worker/test_auto_retry.py::TestAttemptRetry::test_non_infra_exception_not_retried` 3 passed"
        in row
    )
    assert "auto retry full 24 passed" in row
    assert "release quality docs contract full 286 passed" in row
    assert "targeted ruff passed" in row
    assert "固定 get_by_id、refresh pipeline、`_should_retry` 参数" in row
    assert "no create/no scheduler/no commit 副作用" in row
    assert "不 refresh、不创建 retry run、不构造 scheduler、不 commit" in row
    assert "此前只断言返回 False 和 create 未调用" in row
    assert "仍 refresh/commit" in row
    assert "policy 拒绝后仍构造 scheduler" in row
    assert "非 infra 异常仍触发重试副作用" in row
    assert "最后没 create retry run" in row

    should_retry_block = _marked_block(
        auto_retry_test,
        "async def test_returns_false_when_should_retry_false",
        "async def test_returns_false_when_original_not_found",
    )
    not_found_block = _marked_block(
        auto_retry_test,
        "async def test_returns_false_when_original_not_found",
        "async def test_skips_sleep_when_backoff_zero",
    )
    non_infra_block = _marked_block(
        auto_retry_test,
        "async def test_non_infra_exception_not_retried",
        "async def test_enqueues_with_exponential_backoff",
    )

    for expected in [
        'error = ConnectionError("fail")',
        'patch("qaplatform.worker.scheduler.FairScheduler") as scheduler_cls',
        'patch("qaplatform.worker.tasks._should_retry", return_value=False) as should_retry',
        "assert result is False",
        "sf.assert_called_once_with()",
        "run_repo.get_by_id.assert_awaited_once_with(str(original.id))",
        'session.refresh.assert_awaited_once_with(original, ["pipeline"])',
        "should_retry.assert_called_once_with(error, original.pipeline.retry_policy, original.attempt)",
        "run_repo.create.assert_not_awaited()",
        "scheduler_cls.assert_not_called()",
        "session.commit.assert_not_awaited()",
    ]:
        assert expected in should_retry_block

    for expected in [
        "missing_id = uuid4()",
        'patch("qaplatform.worker.scheduler.FairScheduler") as scheduler_cls',
        "assert result is False",
        "sf.assert_called_once_with()",
        "run_repo.get_by_id.assert_awaited_once_with(str(missing_id))",
        "session.refresh.assert_not_awaited()",
        "run_repo.create.assert_not_awaited()",
        "scheduler_cls.assert_not_called()",
        "session.commit.assert_not_awaited()",
    ]:
        assert expected in not_found_block

    for expected in [
        'error = RuntimeError("pipeline execution failed")',
        'patch("qaplatform.worker.scheduler.FairScheduler") as scheduler_cls',
        "assert result is False",
        "sf.assert_called_once_with()",
        "run_repo.get_by_id.assert_awaited_once_with(str(original.id))",
        'session.refresh.assert_awaited_once_with(original, ["pipeline"])',
        "run_repo.create.assert_not_awaited()",
        "scheduler_cls.assert_not_called()",
        "scheduler.enqueue.assert_not_awaited()",
        "session.commit.assert_not_awaited()",
    ]:
        assert expected in non_infra_block


def test_quality_ops_capture_worker_lost_reclaim_stale_update_no_side_effect_contract():
    reclaim_test = _read(ENGINE_RECLAIM_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Worker-lost reclaim stale update no-side-effect 契约）"
    )

    assert "Worker-lost reclaim stale update no-side-effect 契约" in row
    assert (
        "`tests/unit/test_engine/test_reclaim.py::test_mark_worker_lost_returns_false_skips_event_and_cleanup tests/unit/test_engine/test_reclaim.py::test_redis_probe_failure_is_fail_open` 2 passed"
        in row
    )
    assert "reclaim full 11 passed" in row
    assert "release quality docs contract full 287 passed" in row
    assert "targeted ruff passed" in row
    assert "固定 heartbeat key" in row
    assert "`mark_worker_lost(run.id, worker_id, message)` 参数" in row
    assert "不 publish failed event、不触发 retry callback、不 cleanup" in row
    assert "fail-open" in row
    assert "只查目标 heartbeat key、不 mark、不 cleanup" in row
    assert "此前只断言返回 0、没有 Redis xadd/cleanup 或没有 mark" in row
    assert "条件更新使用错 worker/message 后返回 False" in row
    assert "失败开放路径查错 key/误清理容器" in row
    assert "最后没清理容器" in row

    stale_block = _marked_block(
        reclaim_test,
        "async def test_mark_worker_lost_returns_false_skips_event_and_cleanup",
        "async def test_redis_probe_failure_is_fail_open",
    )
    redis_block = _marked_block(
        reclaim_test,
        "async def test_redis_probe_failure_is_fail_open",
        "async def test_cleanup_failure_does_not_block_status_transition",
    )

    for expected in [
        "run_repo.mark_worker_lost = AsyncMock(return_value=False)",
        "on_reclaimed = AsyncMock()",
        'patch(\n        "qaplatform.engine.reclaim.publish_status_event",',
        "on_reclaimed=on_reclaimed",
        "assert n == 0",
        'redis.exists.assert_awaited_once_with(HEARTBEAT_KEY.format(worker_id="worker-a"))',
        "run_repo.mark_worker_lost.assert_awaited_once_with(",
        "run.id",
        'worker_id="worker-a"',
        'message="worker_lost: heartbeat expired for worker-a"',
        "publish_status_event.assert_not_awaited()",
        "on_reclaimed.assert_not_awaited()",
        "backend.cleanup.assert_not_awaited()",
    ]:
        assert expected in stale_block
    assert "redis.xadd.assert_not_awaited()" not in stale_block

    for expected in [
        'redis.exists = AsyncMock(side_effect=RuntimeError("redis down"))',
        "assert n == 0",
        'redis.exists.assert_awaited_once_with(HEARTBEAT_KEY.format(worker_id="worker-a"))',
        "run_repo.mark_worker_lost.assert_not_awaited()",
        "backend.cleanup.assert_not_awaited()",
    ]:
        assert expected in redis_block


def test_quality_ops_capture_worker_active_run_pipeline_config_exact_projection_contract():
    worker_tasks_test = _read(WORKER_TASKS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Worker active run PipelineConfig exact projection 契约）"
    )

    assert "Worker active run PipelineConfig exact projection 契约" in row
    assert (
        "`tests/unit/test_worker/test_tasks.py::TestArchiveBlocking::test_worker_executes_active_project` 1 passed"
        in row
    )
    assert "worker tasks full 19 passed" in row
    assert "release quality docs contract full 209 passed" in row
    assert "targeted ruff passed" in row
    assert "`executor.execute(run, config)` 的无 kwargs 双参数调用" in row
    assert "image/stages/env_vars/resource_limits/network/timeout/setup_script/collectors/source_auth" in row
    assert "此前只抽查 image、timeout、network、memory/cpu、第一个 collector 与 source_auth" in row
    assert "default artifact limit 漂移" in row
    assert "collector 列表夹带额外项" in row
    assert "只证明“核心字段大概能传给 executor”" in row

    test_block = _marked_block(
        worker_tasks_test,
        "async def test_worker_executes_active_project",
        "async def test_worker_releases_claim_when_run_was_already_cancel_requested",
    )

    for expected in [
        "execute_call = executor.execute.await_args",
        "assert execute_call.kwargs == {}",
        "executed_run, config = execute_call.args",
        '"stages": [',
        '"env_vars": config.env_vars',
        '"resource_limits": {',
        '"disk_bytes": config.resource_limits.disk_bytes',
        '"max_artifact_size_bytes": (',
        '"max_artifacts_count": config.resource_limits.max_artifacts_count',
        '"setup_script": config.setup_script',
        '"collectors": [',
        '"source_auth": config.source_auth',
        '"env_vars": {}',
        '"max_artifact_size_bytes": 100 * 1024 * 1024',
        '"max_artifacts_count": 50',
        '"collectors": [{"plugin": "junit", "config": {}, "enabled": True}]',
    ]:
        assert expected in test_block
    assert "assert len(execute_call.args) == 2" not in test_block
    assert 'assert config.collectors[0].plugin == "junit"' not in test_block


def test_quality_ops_capture_heartbeat_redis_set_exact_utc_arity_contract():
    worker_tasks_test = _read(WORKER_TASKS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Heartbeat Redis set exact UTC/arity 契约）"
    )

    assert "Heartbeat Redis set exact UTC/arity 契约" in row
    assert (
        "`tests/unit/test_worker/test_tasks.py::TestHeartbeatLoop::test_heartbeat_writes_reclaimer_key_with_ttl_and_utc_timestamp tests/unit/test_worker/test_tasks.py::TestHeartbeatLoop::test_heartbeat_continues_after_redis_error` 2 passed"
        in row
    )
    assert "worker tasks full 19 passed" in row
    assert "release quality docs contract full 210 passed" in row
    assert "targeted ruff passed" in row
    assert "只有 key/timestamp 两个 positional 参数" in row
    assert "UTC offset `+00:00` timestamp" in row
    assert '唯一 kwargs `{"ex": 90}`' in row
    assert "此前只验证 timestamp 有时区" in row
    assert "本地时区" in row
    assert "夹带额外参数" in row
    assert "只证明“写了一个带时区的心跳键”" in row

    for expected in [
        "def _assert_worker_heartbeat_set_call(set_call, worker_id: str) -> None:",
        "key, timestamp = set_call.args",
        'key == f"worker:{worker_id}:heartbeat"',
        "heartbeat_at = datetime.fromisoformat(timestamp)",
        "assert heartbeat_at.tzinfo is not None",
        "assert heartbeat_at.utcoffset() == timedelta(0)",
        'assert set_call.kwargs == {"ex": 90}',
        "_assert_worker_heartbeat_set_call(redis.set.await_args, worker_id)",
        "_assert_worker_heartbeat_set_call(set_call, worker_id)",
    ]:
        assert expected in worker_tasks_test
    assert "assert len(set_call.args) == 2" not in worker_tasks_test
    assert "assert heartbeat_at.utcoffset() is not None" not in worker_tasks_test
    assert 'assert redis.set.await_args.kwargs["ex"] == 90' not in worker_tasks_test
