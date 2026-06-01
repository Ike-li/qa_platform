from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _block_between,
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
    _test_block,
)


ROOT = Path(__file__).resolve().parents[2]
AUTO_RETRY_REAL_DB = ROOT / "tests" / "integration" / "test_auto_retry_real_db.py"
PERFORMANCE_SMOKE = ROOT / "tests" / "integration" / "test_performance_smoke.py"


def test_quality_ops_capture_artifact_list_p99_exact_page_contract():
    p99_row = _quality_ops_row_containing("Artifact list p99 smoke")
    dto_row = _quality_ops_row_containing(
        "performance smoke 的 artifact list",
        "完整 ArtifactResponse 窗口",
    )
    performance_smoke = _read(PERFORMANCE_SMOKE)

    assert "Artifact list p99 smoke" in p99_row
    assert "完整 ArtifactResponse 窗口" in dto_row
    assert "包含 id/run_id/type/name/storage_path/size_bytes/mime_type" in dto_row
    assert "继续断言 DB-only 不触发 S3" in p99_row
    assert "expected_body = {" in performance_smoke
    assert "def assert_artifact_list_body(body: dict) -> None:" in (
        performance_smoke
    )
    assert "assert body == expected_body" in performance_smoke
    assert '"created_at": _json_datetime(artifact.created_at)' in (
        performance_smoke
    )
    assert '"data": expected_window' in performance_smoke
    assert '"mime_type": "text/html"' in performance_smoke
    assert '"expires_at": None' in performance_smoke
    assert 'item["name"]: item for item in body["data"]' not in performance_smoke
    assert "expected_artifacts_by_name = {" not in performance_smoke
    assert "expected_artifact_fields = {" not in performance_smoke
    assert 'assert [set(item) for item in body["data"]]' not in performance_smoke
    assert 'assert all(\n            set(item) == expected_artifact_fields' not in (
        performance_smoke
    )
    assert 'assert body["total"] >= 80' not in performance_smoke
    assert 'assert len(body["data"]) == len(expected_names)' not in (
        performance_smoke
    )
    assert "assert expected_names <= returned_names" not in performance_smoke
    assert "assert expected_names <= set(returned)" not in performance_smoke


def test_quality_ops_capture_performance_artifact_and_audit_full_dto_contract():
    row = _quality_ops_row_containing(
        "performance smoke 的 artifact list 与大集合分页"
    )
    performance_smoke = _read(PERFORMANCE_SMOKE)

    assert "performance smoke 的 artifact list 与大集合分页" in row
    assert "audit large filtered page 固定 tenant/user/action/resource scope" in (
        row
    )
    assert "避免性能 smoke 只数分页条数" in row
    assert "expected_body = {" in performance_smoke
    assert "assert body == expected_body" in performance_smoke
    assert '"created_at": _json_datetime(artifacts[index].created_at)' in (
        performance_smoke
    )
    assert "def _audit_event_response(event) -> dict:" in performance_smoke
    assert '"data": [_audit_event_response(event) for event in target_events[:50]]' in (
        performance_smoke
    )
    assert "_audit_event_response(target_events[index])" in performance_smoke
    assert "expected_audit_fields = {" not in performance_smoke
    assert 'assert {item["resource_id"] for item in body["data"]}' not in (
        performance_smoke
    )
    assert 'assert [set(item) for item in body["data"]]' not in performance_smoke
    assert 'assert all(set(item) == expected_audit_fields for item in body["data"])' not in (
        performance_smoke
    )
    assert 'assert len(body["data"]) == per_page' not in performance_smoke
    assert 'assert len(body["data"]) == 100' not in performance_smoke


def test_quality_ops_capture_performance_audit_large_self_audit_exact_list_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row(
        "| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
        "tests/integration/test_performance_smoke.py::"
        "test_audit_events_large_filtered_page_api_token_p99_smoke -q` "
        "1 passed；performance full 31 passed"
    )
    audit_large_block = _test_block(
        performance_smoke,
        "test_audit_events_large_filtered_page_api_token_p99_smoke",
    )

    assert "release quality docs contract targeted 2 passed" in row
    assert "release quality docs contract full 359 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "`self_audit_projections`" in row
    assert "tenant/user/action/resource/before_state/after_state" in row
    assert "查询分页摘要" in row
    assert "只看最新一条" not in row
    assert "audit large filtered page self-audit exact-list 契约" in row
    assert "数量断言保留为无额外同类自审计的副作用边界" in row

    for expected in [
        "expected_self_audit_count = 23",
        "self_audit_projections = [",
        '"tenant_id": str(self_audit.tenant_id)',
        '"user_id": str(self_audit.user_id)',
        '"action": self_audit.action',
        '"resource_type": self_audit.resource_type',
        '"resource_id": str(self_audit.resource_id)',
        '"before_state": self_audit.before_state',
        '"after_state": self_audit.after_state',
        "expected_self_audit_projection = {",
        '"action": "audit_events.list"',
        '"resource_type": "audit_event"',
        '"resource_id": None',
        '"page": 5',
        '"per_page": 100',
        '"total": target_count',
        "] * expected_self_audit_count",
    ]:
        assert expected in audit_large_block
    for rejected in [
        "latest_self_audit",
        ".limit(1)",
        "latest_self_audit.after_state",
        "assert len(self_audits)",
    ]:
        assert rejected not in audit_large_block


def test_quality_ops_capture_performance_direct_projection_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
            "tests/integration/test_performance_smoke.py --collect-only` "
            "31 tests collected", contains="performance smoke direct projection 契约")
    archived_block = _block_between(performance_smoke, "async def test_archived_log_replay_large_page_p99_smoke", "\n\n@pytest.mark.asyncio")
    artifact_list_block = _block_between(performance_smoke, "async def test_artifact_list_api_p99_smoke", "\n\n@pytest.mark.asyncio")
    artifact_large_block = _block_between(performance_smoke, "async def test_artifact_list_large_collection_page_p99_smoke", "\n\n@pytest.mark.asyncio")
    artifact_download_block = _block_between(performance_smoke, "async def test_artifact_download_url_api_p99_smoke", "\n\n@pytest.mark.asyncio")
    audit_list_block = _block_between(performance_smoke, "async def test_audit_events_list_api_p99_smoke", "\n\n@pytest.mark.asyncio")
    audit_large_block = _block_between(performance_smoke, "async def test_audit_events_large_filtered_page_api_token_p99_smoke", "\n\n@pytest.mark.asyncio")
    concurrent_block = _block_between(performance_smoke, "async def test_real_api_token_concurrent_read_paths_p99_smoke", "\n\n@pytest.mark.asyncio")
    concurrent_artifact_block = _marked_block(
        concurrent_block,
        "async def list_artifacts",
        "async def download_artifact",
    )

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "audit events 两个分页" in row
    assert "字段集合、artifact/audit DTO 字段集合" in row
    assert "concurrent run.read archived logs、artifact list 与 artifact download URL" in (
        row
    )
    assert "并发 artifact list 完整 ArtifactResponse item" in row
    assert "S3 presign 23 次与并发 7 次完整 `{method,params,expires_in}`" in row
    assert "`assert set(artifacts_by_id)`" in row
    assert "performance smoke direct projection 契约" in row
    assert "只证明“跑得快且大概有字段”" in row

    assert '"data": expected_window' in archived_block
    assert 'expected_log_fields = {"stream", "line"}' not in archived_block
    assert 'assert [set(item) for item in body["data"]]' not in archived_block
    assert 'assert all(set(item) == {"stream", "line"} for item in body["data"])' not in (
        archived_block
    )

    for block in (artifact_list_block, artifact_large_block):
        assert "expected_artifact_fields = {" not in block
        assert 'assert [set(item) for item in body["data"]]' not in block
        assert "set(item) == expected_artifact_fields for item in body[\"data\"]" not in (
            block
        )

    assert "expected_presign_call = {" in artifact_download_block
    assert '"method": "get_object"' in artifact_download_block
    assert '"Bucket": integration_app.state.container.settings.s3_bucket' in (
        artifact_download_block
    )
    assert '"Key": artifact.storage_path' in artifact_download_block
    assert '"expires_in": integration_app.state.container.settings.s3_presigned_url_ttl' in (
        artifact_download_block
    )
    assert "assert s3.presign_calls == [expected_presign_call] * 23" in (
        artifact_download_block
    )
    assert "assert all(call[\"method\"] == \"get_object\" for call in s3.presign_calls)" not in (
        artifact_download_block
    )

    for block in (audit_list_block, audit_large_block):
        assert "expected_body = {" in block
        assert "_audit_event_response(" in block
        assert "assert response.json() == expected_body" in block
        assert "expected_audit_fields = {" not in block
        assert 'assert [set(item) for item in body["data"]]' not in block
        assert "assert all(set(item) == expected_audit_fields for item in body[\"data\"])" not in (
            block
        )

    assert 'expected_log_fields = {"stream", "line"}' not in concurrent_block
    assert 'assert [set(item) for item in body["data"]]' not in concurrent_block
    assert "expected_audit_body = {" in concurrent_block
    assert "assert response.json() == expected_audit_body" in concurrent_block
    for expected in [
        "expected_artifact_body = {",
        "for item in sorted(",
        "key=lambda artifact_item: artifact_item.created_at",
        '"id": str(item.id)',
        '"run_id": str(run_id)',
        '"type": item.type',
        '"name": item.name',
        '"storage_path": item.storage_path',
        '"size_bytes": item.size_bytes',
        '"mime_type": item.mime_type',
        '"expires_at": (',
        "_json_datetime(item.expires_at) if item.expires_at else None",
        '"created_at": _json_datetime(item.created_at)',
        '"page": 1',
        '"per_page": 20',
        '"total": 3',
    ]:
        assert expected in concurrent_block
    for expected in [
        "assert body == expected_artifact_body",
    ]:
        assert expected in concurrent_artifact_block
    for rejected in [
        '"data": body["data"]',
        '"total": len(artifacts)',
        'artifact_items = sorted(body["data"], key=lambda item: item["id"])',
        "expected_artifact_items = sorted(",
        "assert artifact_items == expected_artifact_items",
        "artifacts_by_id =",
        "assert set(artifacts_by_id)",
        "response_item =",
        'assert response_item["mime_type"]',
    ]:
        assert rejected not in concurrent_artifact_block
    assert "expected_presign_call = {" in concurrent_block
    assert '"params": {"Bucket": bucket, "Key": artifact.storage_path}' in (
        concurrent_block
    )
    assert '"expires_in": app.state.container.settings.s3_presigned_url_ttl' in (
        concurrent_block
    )
    assert "assert s3.presign_calls == [expected_presign_call] * 7" in (
        concurrent_block
    )
    assert 'assert all(set(item) == {"stream", "line"} for item in body["data"])' not in (
        concurrent_block
    )


def test_quality_ops_capture_performance_enqueue_exact_arq_call_sequence_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
            "tests/integration/test_performance_smoke.py --collect-only` "
            "31 tests collected", contains="performance enqueue exact ARQ call sequence 契约")
    trigger_block = _block_between(performance_smoke, "async def test_trigger_run_enqueue_slo_smoke", "\n\n@pytest.mark.asyncio")
    webhook_block = _block_between(performance_smoke, "async def test_webhook_trigger_enqueue_slo_smoke", "\n\n@pytest.mark.asyncio")
    schedule_block = _block_between(performance_smoke, "async def test_schedule_tick_enqueue_slo_smoke", "\n\n@pytest.mark.asyncio")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`_expected_execute_run_call`" in row
    assert "`(\"execute_run\", str(run_id))`" in row
    assert "`run:{id}` job id 与 `_defer_by=0`" in row
    assert "`len(arq.calls) == 10`" in row
    assert "只证明“调用了 10 次队列”" in row

    assert "def _expected_execute_run_call(run_id: UUID, queue_name: str) -> dict:" in (
        performance_smoke
    )
    for expected in [
        '"args": ("execute_run", str(run_id))',
        '"_queue_name": queue_name',
        '"_job_id": f"run:{run_id}"',
        '"_defer_by": 0',
    ]:
        assert expected in performance_smoke

    for block, queue_name, ids_name in [
        (trigger_block, "queue:medium", "triggered_refs"),
        (webhook_block, "queue:medium", "triggered_payloads"),
        (schedule_block, "queue:low", "run_schedule_ids"),
    ]:
        assert "assert arq.calls == [" in block
        assert f'_expected_execute_run_call(run_id, "{queue_name}")' in block
        assert f"for run_id in {ids_name}" in block
        assert "assert len(arq.calls) == 10" not in block
    assert "{call[\"kwargs\"][\"_queue_name\"] for call in arq.calls}" not in (
        schedule_block
    )


def test_quality_ops_capture_residual_len_direct_projection_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    auto_retry_real_db = _read(AUTO_RETRY_REAL_DB)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
            "tests/integration/test_performance_smoke.py --collect-only` "
            "31 tests collected；`RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_auto_retry_real_db.py --collect-only` "
            "7 tests collected")
    schedule_block = _block_between(performance_smoke, "async def test_schedule_tick_enqueue_slo_smoke", "\n\n@pytest.mark.asyncio")
    log_stream_block = _block_between(performance_smoke, "async def test_log_stream_round_trip_smoke", "\n\n@pytest.mark.asyncio")
    concurrent_block = _block_between(performance_smoke, "async def test_real_api_token_concurrent_read_paths_p99_smoke", "\n\n@pytest.mark.asyncio")
    clone_failure_block = _block_between(auto_retry_real_db, "async def test_execute_run_clone_failure_is_not_retried_real_executor", "\n\n@pytest.mark.asyncio")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "schedule run 用单元素解包" in row
    assert "log stream roundtrip 固定 20 条完整 `{id,stream,line}`" in row
    assert "concurrent self-audit 固定 7 条 before/after_state" in row
    assert "source.clone 参数用三元解包" in row
    assert "residual len direct projection 契约" in row
    assert "只证明“数量看起来对”" in row

    assert "(run,) = schedule_runs" in schedule_block
    assert "assert len(schedule_runs) == 1" not in schedule_block
    assert 'entry_ids = [entry["id"] for entry in entries]' in log_stream_block
    assert 'assert entries == [\n        {"id": entry_ids[index], "stream": "stdout", "line": f"line-{index}"}' in (
        log_stream_block
    )
    assert "assert len(entries) == 20" not in log_stream_block
    assert "assert entries[-1][\"line\"] == \"line-19\"" not in log_stream_block
    assert '"before_state": self_audit.before_state' in concurrent_block
    assert '"after_state": self_audit.after_state' in concurrent_block
    assert "] * 7" in concurrent_block
    assert "assert len(self_audits) == 7" not in concurrent_block
    assert "assert len(warmup_samples) == 5" not in concurrent_block
    assert "clone_url, clone_ref, clone_path = source.clone.await_args.args" in (
        clone_failure_block
    )
    assert "assert clone_url ==" in clone_failure_block
    assert "assert clone_ref == \"main\"" in clone_failure_block
    assert "assert isinstance(clone_path, Path)" in clone_failure_block
    assert "assert len(clone_args) == 3" not in clone_failure_block


def test_quality_ops_capture_performance_write_trigger_direct_projection_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
            "tests/integration/test_performance_smoke.py::"
            "test_write_run_api_p99_smoke "
            "tests/integration/test_performance_smoke.py::"
            "test_trigger_run_enqueue_slo_smoke -q` "
            "2 passed")
    write_block = _block_between(performance_smoke, "async def test_write_run_api_p99_smoke", "async def test_trigger_run_enqueue_slo_smoke")
    trigger_block = _block_between(performance_smoke, "async def test_trigger_run_enqueue_slo_smoke", "async def test_webhook_trigger_enqueue_slo_smoke")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/collect-only passed" in row
    assert "targeted performance passed" in row
    assert "真实 DB Run row 投影" in row
    assert "{tenant_id,project_id,pipeline_id,environment_id,status,trigger_type,triggered_by,git_ref,priority,retry_group_id,enqueued/arq_job_id,queue_name}" in (
        row
    )
    assert "`run.trigger` audit 投影为完整 `{tenant_id,user_id,action,resource_type,before_state,after_state}` 等值" in (
        row
    )
    assert "`assert set(rows_by_id) == set(created_runs)`" in row
    assert "performance write/trigger DB-audit direct projection contract" in row

    for expected in [
        "row_projection_by_id = {",
        '"tenant_id": row.tenant_id',
        '"retry_group_id": row.retry_group_id',
        '"queue_name": row.queue_name',
        "assert row_projection_by_id == {",
        '"retry_group_id": run_id',
        '"enqueued_at": None',
        "audit_projection_by_run_id = {",
        '"before_state": event.before_state',
        '"after_state": event.after_state',
        "assert audit_projection_by_run_id == {",
        '"before_state": None',
        '"after_state": body',
    ]:
        assert expected in write_block
    for rejected in [
        "rows_by_id = {row.id: row for row in rows_result.scalars()}",
        "assert set(rows_by_id) == set(created_runs)",
        "audits_by_run_id = {event.resource_id: event",
        "assert set(audits_by_run_id) == set(created_runs)",
    ]:
        assert rejected not in write_block

    for expected in [
        "row_projection_by_id = {",
        '"tenant_id": row.tenant_id',
        '"arq_job_id": row.arq_job_id',
        '"enqueued": row.enqueued_at is not None',
        "assert row_projection_by_id == {",
        '"enqueued": True',
        "audit_projection_by_run_id = {",
        '"tenant_id": event.tenant_id',
        '"action": event.action',
        '"before_state": event.before_state',
        '"after_state": event.after_state',
        "assert audit_projection_by_run_id == {",
        '"user_id": user_id',
        '"before_state": None',
        '"after_state": body',
    ]:
        assert expected in trigger_block
    for rejected in [
        "audits_by_run_id = {event.resource_id: event",
        "assert set(audits_by_run_id) == set(triggered_refs)",
        'assert event.after_state["id"] == str(run_id)',
        'assert event.after_state["pipeline_id"] == str(pipeline_id)',
    ]:
        assert rejected not in trigger_block


def test_quality_ops_capture_performance_enqueue_dequeue_full_projection_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
            "tests/integration/test_performance_smoke.py::"
            "test_webhook_trigger_enqueue_slo_smoke "
            "tests/integration/test_performance_smoke.py::"
            "test_schedule_tick_enqueue_slo_smoke "
            "tests/integration/test_performance_smoke.py::"
            "test_dequeue_waiting_runs_slo_smoke "
            "tests/integration/test_performance_smoke.py::"
            "test_dequeue_waiting_prioritizes_newer_high_runs_over_older_low_backlog_slo_smoke "
            "-q` 4 passed")
    dequeue_row = _quality_ops_row("|", contains="performance smoke 的 waiting dequeue 现在固定完整 row projection")
    webhook_block = _block_between(performance_smoke, "async def test_webhook_trigger_enqueue_slo_smoke", "async def test_schedule_tick_enqueue_slo_smoke")
    schedule_block = _block_between(performance_smoke, "async def test_schedule_tick_enqueue_slo_smoke", "async def test_dequeue_waiting_runs_slo_smoke")
    dequeue_block = _block_between(performance_smoke, "async def test_dequeue_waiting_runs_slo_smoke", "async def test_dequeue_waiting_prioritizes_newer_high_runs_over_older_low_backlog_slo_smoke")
    priority_block = _block_between(performance_smoke, "async def test_dequeue_waiting_prioritizes_newer_high_runs_over_older_low_backlog_slo_smoke", "\n\n@pytest.mark.asyncio")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "targeted performance passed" in row
    assert "webhook trigger、schedule trigger、waiting dequeue、priority backlog" in (
        row
    )
    assert "真实 DB Run row / AuditEvent 投影等值" in row
    assert "reserved metadata 和 delivery_id 不进入审计" in row
    assert "performance enqueue/dequeue full projection contract" in row
    assert "只证明“队列动作够快且 id 集合对”" in row
    assert "targeted docs contract passed" in dequeue_row
    assert "targeted ruff/py_compile passed" in dequeue_row
    assert "priority backlog run row/audit" in dequeue_row
    assert "`assert set(rows_by_id) == set(waiting_runs)`" in dequeue_row
    assert "performance smoke dequeue/audit direct projection 契约" in dequeue_row

    assert "def _project_run_metadata(project) -> dict:" in performance_smoke
    for block in (webhook_block, schedule_block, dequeue_block):
        assert "row_projection_by_id = {" in block
        assert "assert row_projection_by_id == {" in block

    for expected in [
        '"metadata": row.metadata_',
        '"metadata": {\n                **_project_run_metadata(project),',
        '"delivery_id": payload["delivery_id"]',
        "serialized_rows = repr(row_projection_by_id)",
        "serialized_audits = repr(audit_projection_by_run_id)",
        'assert payload["delivery_id"] not in serialized_audits',
        "assert audit_projection_by_run_id == {",
        '"after_state": payload["body"]',
    ]:
        assert expected in webhook_block
    for rejected in [
        "audits_by_run_id = {event.resource_id: event",
        "assert set(audits_by_run_id) == set(triggered_payloads)",
        'assert event.after_state["id"] == str(run_id)',
        'assert event.after_state["git_sha"] == payload["git_sha"]',
    ]:
        assert rejected not in webhook_block

    for expected in [
        '"trigger_type": "schedule"',
        '"metadata": {\n                **_project_run_metadata(project),',
        '"schedule_id": str(schedule_id)',
        '"enqueued": True',
        "audit_projection_by_run_id = {",
        "assert audit_projection_by_run_id == {",
        '"user_id": None',
        '"after_state": {',
    ]:
        assert expected in schedule_block
    for rejected in [
        "audits_by_run_id = {event.resource_id: event",
        "assert set(audits_by_run_id) == set(run_schedule_ids)",
        'assert event.after_state["trigger_type"] == "schedule"',
        'assert event.after_state["metadata"]["schedule_id"] == str(schedule_id)',
    ]:
        assert rejected not in schedule_block

    for expected in [
        '"queue_name": row.queue_name',
        '"arq_job_id": row.arq_job_id',
        '"metadata": row.metadata_',
        '"metadata": {"perf_dequeue": True, "priority": priority}',
        "samples = [",
    ]:
        assert expected in dequeue_block
    for rejected in [
        "assert set(rows_by_id) == set(waiting_runs)",
        "assert row.queue_name == expected_queue",
    ]:
        assert rejected not in dequeue_block

    for expected in [
        "created_row_projection_by_id = {",
        "assert created_row_projection_by_id == {",
        '"queue_name": None',
        '"enqueued": False',
        "audit_projection_by_run_id = {",
        "assert audit_projection_by_run_id == {",
    ]:
        assert expected in priority_block
    assert "assert set(created_rows) == all_run_ids" not in priority_block


def test_quality_ops_capture_performance_dequeue_audit_direct_projection_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row("|", contains="performance smoke 的 waiting dequeue 现在固定完整 row projection")
    dequeue_block = _block_between(performance_smoke, "async def test_dequeue_waiting_runs_slo_smoke", "\n\n@pytest.mark.asyncio")
    priority_block = _block_between(performance_smoke, "async def test_dequeue_waiting_prioritizes_newer_high_runs_over_older_low_backlog_slo_smoke", "\n\n@pytest.mark.asyncio")
    sse_ticket_block = _block_between(performance_smoke, "async def test_sse_ticket_create_api_p99_smoke", "\n\n@pytest.mark.asyncio")

    assert (
        "`RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 tests/integration/test_performance_smoke.py --collect-only` 31 tests collected"
        in row
    )
    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "完整 row projection" in row
    assert "priority/created_at 顺序" in row
    assert "priority backlog run row/audit 改为按 run_id 的完整投影等值" in row
    assert "SSE ticket audit 改为完整投影列表等值" in row
    assert "performance smoke dequeue/audit direct projection 契约" in row
    assert "只证明“数量看起来对且速度够快”" in row

    assert "assert our_calls == [" in dequeue_block
    assert "_expected_execute_run_call(run_id, expected_queue)" in dequeue_block
    assert "row_projection_by_id = {" in dequeue_block
    assert "assert row_projection_by_id == {" in dequeue_block
    assert "assert set(rows_by_id) == set(waiting_runs)" not in dequeue_block
    assert "key=lambda item: (item[1][0], rows_by_id[item[0]].created_at)" in (
        dequeue_block
    )
    assert "assert len(our_calls) == len(waiting_runs)" not in dequeue_block

    assert "audit_projection_by_run_id = {" in priority_block
    assert '"action": event.action' in priority_block
    assert '"after_state": event.after_state' in priority_block
    assert "assert audit_projection_by_run_id == {" in priority_block
    assert '"action": "run.trigger"' in priority_block
    assert "assert len(audits) == len(all_run_ids)" not in priority_block
    assert "created_row_projection_by_id = {" in priority_block
    assert "assert created_row_projection_by_id == {" in priority_block
    assert "assert set(created_rows) == all_run_ids" not in priority_block

    assert "audit_projections = [" in sse_ticket_block
    assert "assert audit_projections == [" in sse_ticket_block
    assert "] * len(tickets)" in sse_ticket_block
    assert "serialized_audits = json.dumps(audit_projections, sort_keys=True)" in (
        sse_ticket_block
    )
    assert "assert len(audits) == len(tickets)" not in sse_ticket_block


def test_quality_ops_capture_performance_smoke_exact_response_windows_contract():
    row = _quality_ops_row_containing(
        "performance smoke 的 archived logs 大页、audit events 列表"
    )
    performance_smoke = _read(PERFORMANCE_SMOKE)

    assert "performance smoke 的 archived logs 大页、audit events 列表" in (
        row
    )
    assert "真实 API token 并发读现在在计时循环内同时固定完整分页窗口" in (
        row
    )
    assert "避免性能门禁只证明“快”，却漏掉返回内容漂移" in row
    assert "expected_window = entries[1400:1500]" in performance_smoke
    assert '"data": expected_window' in performance_smoke
    assert "expected_body = {" in performance_smoke
    assert '"data": [_audit_event_response(event) for event in target_events[:50]]' in (
        performance_smoke
    )
    assert "expected_indices = list(range(50))" not in performance_smoke
    assert 'assert [set(item) for item in body["data"]]' not in performance_smoke
    assert "expected_audit_fields" not in performance_smoke
    assert "expected_archive_window = archive_entries[80:120]" in (
        performance_smoke
    )
    assert 'expected_log_fields = {"stream", "line"}' not in performance_smoke
    assert "expected_audit_indices = list(range(30))" not in performance_smoke
    assert '"data": expected_archive_window' in performance_smoke
    assert "expected_audit_body = {" in performance_smoke
    assert "assert response.json() == expected_audit_body" in (
        performance_smoke
    )
    assert 'assert body["data"][0]["line"] == "archived-large-line-1400"' not in (
        performance_smoke
    )
    assert 'assert body["data"][0]["line"] == f"{marker}-archived-line-080"' not in (
        performance_smoke
    )
    assert 'assert len(body["data"]) == 50' not in performance_smoke
    assert 'assert len(body["data"]) == 30' not in performance_smoke


def test_quality_ops_capture_performance_denied_exact_error_body_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
        "tests/integration/test_performance_smoke.py::test_artifact_list_denied_no_metadata_p99_smoke"
    )
    artifact_block = _block_between(performance_smoke, "async def test_artifact_list_denied_no_metadata_p99_smoke", "\n\n@pytest.mark.asyncio")
    audit_block = _block_between(performance_smoke, "async def test_audit_events_denied_queries_no_self_audit_p99_smoke", "\n\n@pytest.mark.asyncio")
    api_token_block = _block_between(performance_smoke, "async def test_audit_events_api_token_denied_no_self_audit_p99_smoke", "\n\n@pytest.mark.asyncio")

    assert "performance smoke denied exact error body 契约" in row
    assert "release quality docs contract full 254 passed" in row
    assert "targeted ruff passed" in row
    assert "`{\"detail\": \"Insufficient permissions\"}`" in row
    assert (
        "`{\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"Run not found\","
        "\"details\":[]}}`"
    ) in row
    assert (
        "`{\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"Audit event not found\","
        "\"details\":[]}}`"
    ) in row
    assert "artifact metadata、audit query 与 self-audit 不泄漏证据" in row
    assert "只证明“拒绝得快且状态码对”" in row

    assert (
        artifact_block.count(
            'assert response.json() == {"detail": "Insufficient permissions"}'
        )
        == 1
    )
    for expected in [
        '"error": {',
        '"code": "NOT_FOUND"',
        '"message": "Run not found"',
        '"details": []',
    ]:
        assert expected in artifact_block
    assert "assert_no_artifact_metadata(response.text)" in artifact_block
    assert (
        "assert response.status_code == 403, response.text\n"
        "                assert_no_artifact_metadata(response.text)"
        not in artifact_block
    )
    assert (
        "assert response.status_code == 404, response.text\n"
        "            assert_no_artifact_metadata(response.text)"
        not in artifact_block
    )

    assert (
        audit_block.count(
            'assert response.json() == {"detail": "Insufficient permissions"}'
        )
        == 2
    )
    for expected in [
        '"error": {',
        '"code": "NOT_FOUND"',
        '"message": "Audit event not found"',
        '"details": []',
    ]:
        assert expected in audit_block
    assert "assert await count_self_audits() == before_count" in audit_block
    assert (
        "assert response.status_code == 403, response.text\n"
        "            samples.append(elapsed_ms)"
        not in audit_block
    )
    assert (
        "assert response.status_code == 404, response.text\n"
        "            samples.append(elapsed_ms)"
        not in audit_block
    )

    assert (
        api_token_block.count(
            'assert response.json() == {"detail": "Insufficient permissions"}'
        )
        == 1
    )
    assert "assert action not in response.text" in api_token_block
    assert "assert str(project_id) not in response.text" in api_token_block
    assert "assert await count_self_audits() == before_self_audits" in (
        api_token_block
    )
    assert (
        "assert response.status_code == 403, response.text\n"
        "                assert action not in response.text"
        not in api_token_block
    )


def test_quality_ops_capture_performance_log_artifact_denial_exact_body_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
        "tests/integration/test_performance_smoke.py::test_archived_log_denied_no_s3_read_p99_smoke"
    )
    archive_block = _block_between(performance_smoke, "async def test_archived_log_denied_no_s3_read_p99_smoke", "\n\n@pytest.mark.asyncio")
    artifact_download_block = _block_between(performance_smoke, "async def test_artifact_download_denied_no_presign_p99_smoke", "\n\n@pytest.mark.asyncio")
    empty_scope_block = _block_between(performance_smoke, "async def test_run_read_empty_scope_denied_logs_and_artifacts_no_s3_p99_smoke", "\n\n@pytest.mark.asyncio")

    assert "performance log/artifact denial exact body 契约" in row
    assert "release quality docs contract full 255 passed" in row
    assert "targeted ruff passed" in row
    assert (
        "`{\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"Run not found\","
        "\"details\":[]}}`"
    ) in row
    assert (
        "`{\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"Artifact not found\","
        "\"details\":[]}}`"
    ) in row
    assert "`{\"detail\": \"Insufficient permissions\"}`" in row
    assert "no-S3 get/presign 与敏感 metadata 不回显证据" in row
    assert "只证明“拒绝后没有 S3 副作用”" in row

    for expected in [
        '"error": {',
        '"code": "NOT_FOUND"',
        '"message": "Run not found"',
        '"details": []',
        "assert random_response.json() == expected_404",
        "assert response.json() == expected_404",
        "assert s3.get_calls == []",
    ]:
        assert expected in archive_block
    assert "expected_404 = random_response.json()" not in archive_block

    for expected in [
        '"error": {',
        '"code": "NOT_FOUND"',
        '"message": "Artifact not found"',
        '"details": []',
        "assert random_response.json() == expected_404",
        "assert response.json() == expected_404",
        "assert s3.presign_calls == []",
        "assert s3.get_calls == []",
    ]:
        assert expected in artifact_download_block
    assert "expected_404 = random_response.json()" not in artifact_download_block

    assert (
        empty_scope_block.count(
            'assert response.json() == {"detail": "Insufficient permissions"}'
        )
        == 1
    )
    for expected in [
        "assert marker not in response_text",
        "assert archive_key not in response_text",
        "assert artifact.name not in response_text",
        "assert artifact.storage_path not in response_text",
        "assert s3.get_calls == []",
        "assert s3.presign_calls == []",
        'f"/api/v1/runs/{run_id}/logs/archive"',
        'f"/api/v1/runs/{run_id}/artifacts"',
        'f"/api/v1/artifacts/{artifact.id}/download"',
    ]:
        assert expected in empty_scope_block
    assert (
        "assert response.status_code == 403, response.text\n"
        "            assert_no_sensitive_metadata(response.text)"
        not in empty_scope_block
    )


def test_quality_ops_capture_performance_priority_backlog_order_followup_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    row = _quality_ops_row(
        "| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
        "tests/integration/test_performance_smoke.py::"
        "test_dequeue_waiting_prioritizes_newer_high_runs_over_older_low_backlog_slo_smoke -q` "
        "1 passed"
    )
    priority_block = _test_block(
        performance_smoke,
        "test_dequeue_waiting_prioritizes_newer_high_runs_over_older_low_backlog_slo_smoke",
    )

    assert "performance full 31 passed" in row
    assert "release quality docs contract targeted 2 passed" in row
    assert "release quality docs contract full 355 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "pending" not in row
    assert "exact ARQ order / row projection / audit exact-list 契约" in row
    assert "`all(...)` 仍判定为异步等待条件" in row

    for expected in [
        "assert high_calls == [",
        '_expected_execute_run_call(run_id, "queue:high")',
        "key=lambda run_id: rows_by_id[run_id].created_at",
        "assert low_calls == []",
        "post_dequeue_projection_by_id = {",
        "expected_post_dequeue_projection_by_id = {",
        "expected_post_dequeue_projection_by_id.update(",
        "assert post_dequeue_projection_by_id == expected_post_dequeue_projection_by_id",
        "audit_after_dequeue_projection = sorted(",
        '"resource_id": event.resource_id',
        '"resource_type": event.resource_type',
        '"after_state": event.after_state',
        "assert audit_after_dequeue_projection == sorted(",
    ]:
        assert expected in priority_block
    for rejected in [
        'assert {UUID(call["args"][1]) for call in high_calls} == set(high_run_ids)',
        '{call["kwargs"]["_job_id"] for call in high_calls}',
        '{call["kwargs"]["_queue_name"] for call in high_calls}',
        'assert row.queue_name == "queue:high"',
        'assert row.queue_name is None',
        "(event.resource_id, event.action)",
        '{(run_id, "run.trigger") for run_id in all_run_ids}',
    ]:
        assert rejected not in priority_block
