from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _block_between,
    _marked_block,
    _marked_block_or_tail,
    _quality_ops_row,
    _quality_ops_row_containing,
    _quality_ops_rows_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
API_ENDPOINTS = ROOT / "tests" / "integration" / "test_api_endpoints.py"
P3_TEST = ROOT / "tests" / "unit" / "test_api" / "test_p3.py"
PROJECTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_projects.py"
REAL_API_WRITE_STATE = ROOT / "tests" / "integration" / "test_real_api_write_state.py"
RUNS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_runs.py"
SSE_TEST = ROOT / "tests" / "unit" / "test_api" / "test_sse.py"
ENGINE_EVENTS_TEST = ROOT / "tests" / "unit" / "test_engine" / "test_events.py"


def test_quality_ops_capture_sse_route_rejection_exact_body_contract():
    sse_test = _read(SSE_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（SSE route rejection exact body 契约）"
    )
    logs_no_ticket_block = _block_between(sse_test, "async def test_logs_sse_no_ticket_returns_401_without_touching_redis", "\n\n@pytest.mark.asyncio")
    events_no_ticket_block = _block_between(sse_test, "async def test_events_sse_no_ticket_returns_401_without_touching_redis", "\n\n#")
    logs_forbidden_block = _block_between(sse_test, "async def test_stream_logs_same_tenant_no_project_perm_returns_403", "\n\n@pytest.mark.asyncio")
    events_forbidden_block = _block_between(sse_test, "async def test_stream_events_same_tenant_no_project_perm_returns_403", "\n\n@pytest.mark.asyncio")

    assert "SSE route rejection exact body 契约" in row
    assert (
        "`tests/unit/test_api/test_sse.py::test_logs_sse_no_ticket_returns_401_without_touching_redis tests/unit/test_api/test_sse.py::test_events_sse_no_ticket_returns_401_without_touching_redis tests/unit/test_api/test_sse.py::test_stream_logs_same_tenant_no_project_perm_returns_403 tests/unit/test_api/test_sse.py::test_stream_events_same_tenant_no_project_perm_returns_403` 4 passed"
        in row
    )
    assert "release quality docs contract full 261 passed" in row
    assert "targeted ruff passed" in row
    assert "`{\"detail\": \"Invalid or expired SSE ticket\"}`" in row
    assert "`{\"detail\": \"Insufficient permissions\"}`" in row
    assert "不触碰 Redis GETDEL" in row
    assert "不读 Redis stream/status" in row
    assert "只证明“detail 字段文案对”" in row

    for block in (logs_no_ticket_block, events_no_ticket_block):
        assert 'assert resp.json() == {"detail": "Invalid or expired SSE ticket"}' in (
            block
        )
        assert "mock_redis.getdel.assert_not_awaited()" in block
        assert 'resp.json()["detail"]' not in block

    for block in (logs_forbidden_block, events_forbidden_block):
        assert 'assert resp.json() == {"detail": "Insufficient permissions"}' in (
            block
        )
        assert "mock_run_repo.get_for_tenant.assert_awaited_once_with" in block
        assert "mock_redis.xread.assert_not_awaited()" in block
        assert "mock_redis.hget.assert_not_awaited()" in block
        assert 'resp.json()["detail"]' not in block


def test_quality_ops_capture_run_trigger_rejection_response_contracts():
    row = _quality_ops_row_containing("Run trigger pipeline/archived 错误契约")
    runs_test = _read(RUNS_TEST)

    assert "Run trigger pipeline/archived 错误契约" in row
    assert "缺失 pipeline 与跨租户 pipeline 固定返回 `NOT_FOUND` envelope" in (
        row
    )
    assert "archived project 固定 409" in row
    assert "_assert_pipeline_not_found_response" in runs_test
    assert '"message": "Pipeline not found"' in runs_test
    assert 'forbidden_values=[pipeline.id, pipeline.project_id]' in runs_test
    assert '"detail": "Project is archived; new runs cannot be triggered"' in (
        runs_test
    )
    assert "str(project.id) not in resp.text" in runs_test
    assert "mock_run_repo.create.assert_not_awaited()" in runs_test
    assert "mock_repos.audit.create.assert_not_awaited()" in runs_test


def test_quality_ops_capture_sse_stream_404_response_contracts():
    row = _quality_ops_row_containing("SSE stream run 404 错误契约")
    sse_test = _read(SSE_TEST)

    assert "SSE stream run 404 错误契约" in row
    assert "固定 `NOT_FOUND` envelope" in row
    assert "不回显 run_id" in row
    assert "不读 Redis stream/status" in row
    assert "_assert_run_not_found_response" in sse_test
    assert '"code": "NOT_FOUND"' in sse_test
    assert '"message": "Run not found"' in sse_test
    assert "str(run_id) not in resp.text" in sse_test
    assert "mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)" in (
        sse_test
    )
    assert "mock_redis.xread.assert_not_awaited()" in sse_test
    assert "mock_redis.hget.assert_not_awaited()" in sse_test
    assert 'body.get("detail") or body.get("error", {}).get("message", "")' not in (
        sse_test
    )


def test_quality_ops_capture_run_cancel_batch_real_api_exact_response_redis_audit_contract():
    real_api_write_state = _read(REAL_API_WRITE_STATE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_api_write_state.py::"
            "test_single_run_cancel_persists_state_redis_event_and_audit_row "
            "tests/integration/test_real_api_write_state.py::"
            "test_batch_run_apis_persist_state_and_audit_rows")

    assert "` 2 passed" in row
    assert "release quality docs contract full 242 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 RunResponse 投影" in row
    assert "Redis status stream/hash 完整 payload 与同一 timestamp" in row
    assert "`run.cancel` / `run.batch_cancel` / `run.batch_retry` AuditEvent" in row
    assert "tenant/user/resource/before_state/after_state 完整匹配" in row
    assert "batch retry after_state 精确等于 retry_run_id/source_run_id/status/attempt" in row
    assert "此前只抽查 response status、Redis event status/previous 和 audit status" in row
    assert "RunResponse 漏字段" in row
    assert "status hash 与 stream timestamp 不一致" in row
    assert "audit before/after 漏字段或用错版本" in row
    assert "batch retry after_state 错绑新旧 run" in row
    assert "取消/重试真实写路径测试只证明“状态大概 cancelled 且有两条 audit action”" in row

    for helper in [
        "def _json_datetime_or_none(value) -> str | None:",
        "def _expected_run_response(run, *, pipeline_name: str) -> dict:",
        "def _assert_run_cancel_redis_event(",
    ]:
        assert helper in real_api_write_state

    helper_block = _marked_block(
        real_api_write_state,
        "def _assert_run_cancel_redis_event(",
        "\n\n@pytest.mark.asyncio",
    )
    assert "assert decoded_event == {" in helper_block
    assert "assert decoded_status == {" in helper_block
    assert "assert set(decoded_event)" not in helper_block

    single_block = _marked_block(
        real_api_write_state,
        "async def test_single_run_cancel_persists_state_redis_event_and_audit_row",
        "async def test_batch_run_apis_persist_state_and_audit_rows",
    )
    batch_block = _marked_block(
        real_api_write_state,
        "async def test_batch_run_apis_persist_state_and_audit_rows",
        "async def test_schedule_api_rejects_cross_project_pipeline_without_persisting",
    )

    for expected in [
        "expected_before = _expected_run_response(",
        "expected_after = _expected_run_response(",
        "assert body == expected_after",
        "assert run.cancel_requested_at is not None",
        "assert run.finished_at is not None",
        "status_hash = await redis.hgetall(STATUS_HASH_KEY.format(run_id=str(run.id)))",
        "_assert_run_cancel_redis_event(decoded_event, decoded_status, run.id)",
        "await _assert_audit_actions(",
        'expected={"run.cancel"}',
        'assert audit.resource_type == "run"',
        "assert audit.resource_id == run.id",
        "assert audit.before_state == expected_before",
        "assert audit.after_state == expected_after",
    ]:
        assert expected in single_block

    for expected in [
        "from qaplatform.engine.events import EVENT_STREAM_KEY, STATUS_HASH_KEY",
        "expected_before = _expected_run_response(",
        "expected_cancelled = _expected_run_response(",
        'assert cancel_resp.json() == {"processed": 1, "failed": 0, "errors": []}',
        "status_hash = await redis.hgetall(STATUS_HASH_KEY.format(run_id=str(run.id)))",
        "_assert_run_cancel_redis_event(decoded_event, decoded_status, run.id)",
        'assert batch_cancel_audit.resource_type == "run"',
        "assert batch_cancel_audit.resource_id == run.id",
        "assert batch_cancel_audit.before_state == expected_before",
        "assert batch_cancel_audit.after_state == expected_cancelled",
        'assert retry_resp.json() == {"processed": 1, "failed": 0, "errors": []}',
        "assert batch_retry_audit.before_state == expected_cancelled",
        "assert batch_retry_audit.after_state == {",
        '"retry_run_id": str(retry_run.id)',
        '"source_run_id": str(run.id)',
        '"status": "queued"',
        '"attempt": retry_run.attempt',
        'assert actions == ["run.batch_cancel", "run.batch_retry"]',
    ]:
        assert expected in batch_block

    for weak_fragment in [
        'response.json()["status"]',
        'decoded_status["status"]',
        'decoded_event["status"]',
        'decoded_event["previous"]',
        'before_state["status"]',
        'after_state["status"]',
    ]:
        assert weak_fragment not in single_block + batch_block


def test_quality_ops_capture_run_list_filter_exact_results_contract():
    row = _quality_ops_row_containing(
        "Run list pipeline/git_ref/created range 真实 API 用例"
    )
    api_endpoints = _read(API_ENDPOINTS)

    assert "Run list pipeline/git_ref/created range 真实 API 用例" in row
    assert "pipeline_id 过滤 total=2" in row
    assert "created_at range 过滤 total=1" in row
    assert "_expected_run_response(later_run, pipeline_name=second_pipeline.name)" in (
        api_endpoints
    )
    assert "_expected_run_response(target_run, pipeline_name=second_pipeline.name)" in (
        api_endpoints
    )
    assert "expected_target_page = {" in api_endpoints
    assert "assert git_ref_body == expected_target_page" in api_endpoints
    assert "assert range_body == expected_target_page" in api_endpoints
    assert 'assert pipeline_body["total"] == 2' not in api_endpoints
    assert '[run["id"] for run in pipeline_body["data"]]' not in api_endpoints
    assert 'assert str(target_run.id) in {run["id"] for run in pipeline_body["data"]}' not in (
        api_endpoints
    )
    assert "assert str(target_run.id) in range_ids" not in api_endpoints


def test_quality_ops_capture_run_list_filter_exact_run_response_pagination_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
            "tests/integration/test_api_endpoints.py::TestRuns::"
            "test_list_runs_filters_pipeline_git_ref_and_created_range -q` 1 passed")

    assert "targeted docs contract passed" in row
    assert "targeted ruff passed" in row
    assert "`_expected_run_response` 固定" in row
    assert "完整分页响应" in row
    assert "RunResponse 字段、pipeline_name、page/per_page/total" in row
    assert "默认 `-created_at` 顺序全部等值" in row
    assert "只断言 total、id 顺序和 `all(pipeline_id)`" in row
    assert "响应漏 `tenant_id/pipeline_name/priority/timestamps`" in row
    assert "run list filter 集成测试只证明“筛出了这些 id”" in row

    block = _marked_block(
        api_endpoints,
        "async def test_list_runs_filters_pipeline_git_ref_and_created_range",
        "# --------------------------------------------------------------------------- #",
    )

    for expected in [
        "def _expected_run_response(run: Run, *, pipeline_name: str) -> dict:",
        '"pipeline_name": pipeline_name',
        '"priority": run.priority',
        '"created_at": _json_datetime(run.created_at)',
        '"updated_at": _json_datetime(run.updated_at)',
    ]:
        assert expected in api_endpoints

    for expected in [
        '"data": [',
        "_expected_run_response(later_run, pipeline_name=second_pipeline.name)",
        "_expected_run_response(target_run, pipeline_name=second_pipeline.name)",
        '"page": 1',
        '"per_page": 100',
        '"total": 2',
        "expected_target_page = {",
        'assert git_ref_body == expected_target_page',
        'assert range_body == expected_target_page',
    ]:
        assert expected in block
    assert 'assert pipeline_body["total"] == 2' not in block
    assert '[run["id"] for run in pipeline_body["data"]]' not in block
    assert "assert all(" not in block
    assert 'assert range_body["total"] == 1' not in block


def test_quality_ops_capture_run_trigger_get_integration_exact_response_audit_contract():
    api_endpoints = _read(API_ENDPOINTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
            "tests/integration/test_api_endpoints.py::TestRuns::test_trigger_run "
            "tests/integration/test_api_endpoints.py::TestRuns::test_get_run -q` "
            "2 passed")
    trigger_block = _block_between(api_endpoints, "async def test_trigger_run", "async def test_get_run")
    get_block = _block_between(api_endpoints, "async def test_get_run", "async def test_list_runs")

    assert "release quality docs contract full 311 passed" in row
    assert "targeted ruff passed" in row
    assert "复用 `_expected_run_response` 固定完整 RunResponse" in row
    assert "DB run 的 pipeline/environment/status/trigger_type/priority/user/git/retry_group" in row
    assert "`run.trigger` AuditEvent" in row
    assert "before_state/after_state 完整等于响应" in row
    assert "Run trigger/get integration exact response/audit 契约" in row
    assert "只证明“创建了 queued run 或能按 id 读到某个 run”" in row

    assert (
        'assert body == _expected_run_response(run, pipeline_name=seed_run["pipeline"].name)'
        in trigger_block
    )
    for expected in [
        "assert str(run.pipeline_id) == pipeline_id",
        "assert str(run.environment_id) == environment_id",
        "assert run.status == RunStatusEnum.QUEUED",
        'assert run.trigger_type == "manual"',
        "assert run.priority == 0",
        'assert run.git_ref == "main"',
        "assert run.git_sha == git_sha",
        "assert run.retry_group_id == run.id",
        "assert audit.before_state is None",
        "assert audit.after_state == body",
    ]:
        assert expected in trigger_block
    assert "assert body == _expected_run_response(" in get_block
    combined = trigger_block + get_block
    assert 'assert body["pipeline_id"] == pipeline_id' not in combined
    assert 'assert body["environment_id"] == environment_id' not in combined
    assert 'assert body["status"] == "queued"' not in combined
    assert 'assert body["id"] == run_id' not in get_block
    assert 'assert body["pipeline_id"] == str(seed_run["pipeline"].id)' not in get_block
    assert 'audit.after_state["git_sha"]' not in trigger_block


def test_quality_ops_capture_sse_stream_frame_payload_exact_contract():
    row = _quality_ops_row_containing("SSE stream frame/payload 精确契约")
    sse_test = _read(SSE_TEST)

    assert "SSE stream frame/payload 精确契约" in row
    assert (
        "`tests/unit/test_api/test_sse.py::test_logs_sse_streams_log_event_payload tests/unit/test_api/test_sse.py::test_events_sse_streams_status_event_payload tests/unit/test_api/test_sse.py::test_stream_logs_same_project_returns_200_event_stream` 3 passed"
        in row
    )
    assert "解析 EventSource frame" in row
    assert "固定事件序列为 `log/status_change -> done`" in row
    assert "首个事件 id、data JSON payload 与 done status" in row
    assert "Redis xread cursor/count/block" in row
    assert "`resp.text` 包含 `id:`、`event:` 和 JSON 片段" in row
    assert "事件顺序颠倒、done sentinel 丢失、data JSON 缺字段" in row
    assert "只证明“文本里出现过某些片段”" in row

    assert "def _parse_sse_events(text: str) -> list[dict[str, str]]:" in sse_test
    assert 'assert [event["event"] for event in events] == ["log", "done"]' in (
        sse_test
    )
    assert (
        'assert [event["event"] for event in events] == ["status_change", "done"]'
        in sse_test
    )
    assert 'assert events[0]["id"] == "1234-0"' in sse_test
    assert 'assert events[0]["id"] == "5678-0"' in sse_test
    assert 'assert json.loads(events[0]["data"]) == log_payload' in sse_test
    assert (
        'assert json.loads(events[1]["data"]) == {"status": RunStatus.DONE.value}'
        in sse_test
    )
    assert 'assert "id: 1234-0" in resp.text' not in sse_test
    assert 'assert "event: status_change" in resp.text' not in sse_test
    assert 'assert "expected-log-line" in resp.text' not in sse_test


def test_quality_ops_capture_sse_resume_frame_cursor_exact_contract():
    row = _quality_ops_row_containing(
        "SSE Last-Event-ID resume frame/cursor 精确契约"
    )
    sse_test = _read(SSE_TEST)

    assert "SSE Last-Event-ID resume frame/cursor 精确契约" in row
    assert (
        "`tests/unit/test_api/test_sse.py::test_stream_logs_accepts_last_event_id_query_param tests/unit/test_api/test_sse.py::test_stream_events_accepts_last_event_id_query_param` 2 passed"
        in row
    )
    assert "Redis xread cursor/count/block" in row
    assert "回放事件 id" in row
    assert "事件序列 `log/status_change -> done`" in row
    assert "data JSON 与 done status" in row
    assert "此前只断言首个 `xread` cursor" in row
    assert "响应退成 heartbeat、漏掉 done sentinel" in row
    assert "只证明“Redis 从某个游标读了”" in row

    logs_block = _marked_block(
        sse_test,
        "async def test_stream_logs_accepts_last_event_id_query_param",
        "async def test_stream_events_accepts_last_event_id_query_param"
    )
    events_block = _marked_block(
        sse_test,
        "async def test_stream_events_accepts_last_event_id_query_param",
        "async def test_authenticate_sse_ticket_consumes_atomically",
    )

    assert 'assert [event["event"] for event in events] == ["log", "done"]' in (
        logs_block
    )
    assert 'assert events[0]["id"] == "1235-0"' in logs_block
    assert 'assert json.loads(events[0]["data"]) == {"message": "resumed"}' in (
        logs_block
    )
    assert 'assert first_xread.kwargs == {"count": 100, "block": 5000}' in logs_block
    assert (
        'assert [event["event"] for event in events] == ["status_change", "done"]'
        in events_block
    )
    assert 'assert events[0]["id"] == "5679-0"' in events_block
    assert '"status": "done"' in events_block
    assert 'assert first_xread.kwargs == {"count": 50, "block": 5000}' in events_block
    assert (
        "assert mock_redis.xread.await_args_list[0].args[0] == {stream_key: "
        not in logs_block
    )
    assert (
        "assert mock_redis.xread.await_args_list[0].args[0] == {stream_key: "
        not in events_block
    )


def test_quality_ops_capture_route_rejection_detail_exact_body_contract():
    runs_test = _read(RUNS_TEST)
    webhook_tests = _read(P3_TEST)
    projects_test = _read(PROJECTS_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Route rejection detail exact body 契约） | `tests/unit/test_api/test_runs.py::test_cancel_already_terminal tests/unit/test_api/test_p3.py::TestWebhookTrigger::test_webhook_trigger_signed_project_requires_signature tests/unit/test_api/test_p3.py::TestWebhookTrigger::test_webhook_trigger_archived_project_409 tests/unit/test_api/test_projects.py::test_unauthenticated` 4 passed；release quality docs contract full 267 passed"
    )

    assert "terminal cancel、项目 webhook 缺签名" in row
    assert "归档项目 webhook trigger、未认证 project list" in row
    assert "完整 `{\"detail\": ...}` body" in row
    assert "不 cancel、不 publish Redis" in row
    assert "不查 pipeline/environment/run、不写 audit" in row
    assert "不触碰 project repository" in row
    assert '只断言 `json()["detail"]`' in row
    assert "run/project/webhook 识别信息、签名 hint 或 debug 字段" in row
    assert "route rejection detail exact body 契约" in row
    assert "只证明“状态码和 detail 文案对”" in row

    cancel_block = _block_between(runs_test, "async def test_cancel_already_terminal", "@pytest.mark.asyncio")
    missing_signature_block = _block_between(webhook_tests, "async def test_webhook_trigger_signed_project_requires_signature", "async def test_webhook_trigger_creates_run")
    archived_webhook_block = _block_between(webhook_tests, "async def test_webhook_trigger_archived_project_409", "async def test_webhook_trigger_filtered_branch_returns_200_without_run")
    unauth_projects_block = _block_between(projects_test, "async def test_unauthenticated", "@pytest.mark.asyncio")

    assert (
        'assert resp.json() == {"detail": "Run already in terminal status: done"}'
        in cancel_block
    )
    assert (
        'assert resp.json() == {"detail": "Missing X-Webhook-Signature header"}'
        in missing_signature_block
    )
    assert "assert resp.json() == {" in archived_webhook_block
    assert '"detail": "Project is archived; new runs cannot be triggered"' in (
        archived_webhook_block
    )
    assert (
        'assert resp.json() == {"detail": "Missing Authorization header"}'
        in unauth_projects_block
    )

    for block in (
        cancel_block,
        missing_signature_block,
        archived_webhook_block,
        unauth_projects_block,
    ):
        assert 'resp.json()["detail"]' not in block

    assert "mock_run_repo.cancel_if_current.assert_not_awaited()" in cancel_block
    assert "redis.publish.assert_not_awaited()" in cancel_block
    assert "mock_repos.pipeline.list_by_project.assert_not_awaited()" in (
        missing_signature_block
    )
    assert "mock_repos.audit.create.assert_not_awaited()" in archived_webhook_block
    assert "mock_project_repo.list.assert_not_awaited()" in unauth_projects_block


def test_quality_ops_capture_run_list_seeded_item_contract():
    quality_ops = _quality_ops_rows_containing(
        "Run list seeded item 集成契约",
        "core API list integration",
    )
    api_endpoints = _read(API_ENDPOINTS)

    assert "Run list seeded item 集成契约" in quality_ops
    assert "默认 `/runs` 列表只返回当前 seed tenant 的 1 条 run" in quality_ops
    assert "分页字段、run/project/pipeline/environment/user 映射" in quality_ops
    assert "pipeline_name/status/priority/git_ref/attempt" in quality_ops
    assert "core API list integration" in quality_ops
    assert '"id": str(seed_run["run"].id)' in api_endpoints
    assert '"tenant_id": str(seed_run["tenant"].id)' in api_endpoints
    assert '"project_id": str(seed_run["project"].id)' in api_endpoints
    assert '"pipeline_id": str(seed_run["pipeline"].id)' in api_endpoints
    assert '"environment_id": str(seed_run["environment"].id)' in api_endpoints
    assert '"triggered_by": str(seed_run["user"].id)' in api_endpoints
    assert '"pipeline_name": "smoke"' in api_endpoints
    assert '"status": "queued"' in api_endpoints
    assert '"git_ref": "main"' in api_endpoints
    assert '"git_sha": None' in api_endpoints
    assert '"created_at": _json_datetime(seed_run["run"].created_at)' in api_endpoints
    assert "len(body[\"data\"]) == 1" not in api_endpoints


def test_quality_ops_capture_run_list_exact_response_default_sort_contract():
    runs_test = _read(RUNS_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Run list exact response/default sort 契约）")

    assert "`tests/unit/test_api/test_runs.py::test_list_runs` 1 passed" in row
    assert "release quality docs contract full 244 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 RunResponse 分页壳" in row
    assert "tenant/project/pipeline/environment/pipeline_name/status/priority/trigger/git/timestamps/summary/error" in row
    assert "`page=1/per_page=10 -> offset=0/limit=10`" in row
    assert "默认 `run.created_at DESC` 排序" in row
    assert "tenant/status filter 和读列表不写 audit" in row
    assert "此前只断言 `resp.json()[\"total\"] == 1` 和第一条 `status`" in row
    assert "RunResponse 漏字段" in row
    assert "tenant_id 与过滤租户不一致" in row
    assert "默认排序漂移" in row
    assert "run list 单测只证明“有一条 queued run”" in row

    block = _marked_block(
        runs_test,
        "async def test_list_runs(",
        "async def test_list_runs_member_user_uses_project_member_repository",
    )

    for expected in [
        "run = _make_orm_run(tenant_id=tenant_id)",
        "mock_run_repo.list.return_value = ([run], 1)",
        '"/api/v1/runs?status=queued&page=1&per_page=10"',
        '"data": [_expected_run_response(run)]',
        '"page": 1',
        '"per_page": 10',
        '"total": 1',
        'assert list_kwargs["offset"] == 0',
        'assert list_kwargs["limit"] == 10',
        'assert str(list_kwargs["order_by"]) == "run.created_at DESC"',
        "assert _render_filters(list_kwargs[\"filters\"]) == [",
        "f\"run.tenant_id = '{tenant_id.hex}'\"",
        '"run.status = \'queued\'"',
        "mock_repos.audit.create.assert_not_awaited()",
    ]:
        assert expected in block

    for weak_fragment in [
        'resp.json()["total"] == 1',
        'resp.json()["data"][0]["status"]',
    ]:
        assert weak_fragment not in block


def test_quality_ops_capture_run_results_exact_page_rbac_contract():
    runs_test = _read(RUNS_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Run results exact page/RBAC 契约）")

    assert "`tests/unit/test_api/test_runs.py::test_get_run_results` 1 passed" in row
    assert "release quality docs contract full 243 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 TestResultResponse 分页壳" in row
    assert "id/run_id/suite/name/status/duration_ms/error_message/stack_trace/tags/metadata" in row
    assert "`page=3/per_page=7 -> offset=14/limit=7`" in row
    assert "tenant-scoped run lookup" in row
    assert "RBAC `RUN_READ`" in row
    assert "run_id filter 和读列表不写 audit" in row
    assert "此前只断言 `resp.json()[\"total\"] == 0`" in row
    assert "route 漏掉 RUN_READ" in row
    assert "分页 offset 算错" in row
    assert "run_id filter 丢失" in row
    assert "结果列表单测只证明“能返回一个空分页 total”" in row

    for helper in [
        "def _make_orm_test_result(**overrides):",
        "def _expected_test_result_response(result) -> dict:",
    ]:
        assert helper in runs_test

    block = _marked_block(
        runs_test,
        "async def test_get_run_results(",
        "async def test_get_run_results_rejects_unknown_status",
    )

    for expected in [
        "from qaplatform.api.auth.permissions import Action",
        "result = _make_orm_test_result(run_id=run_id)",
        "mock_result_repo.list.return_value = ([result], 42)",
        'f"/api/v1/runs/{run_id}/results?page=3&per_page=7"',
        '"data": [_expected_test_result_response(result)]',
        '"page": 3',
        '"per_page": 7',
        '"total": 42',
        "mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)",
        "enforce_project_action.assert_awaited_once()",
        "Action.RUN_READ",
        'assert list_kwargs["offset"] == 14',
        'assert list_kwargs["limit"] == 7',
        "assert _render_filters(list_kwargs[\"filters\"]) == [",
        "f\"test_result.run_id = '{run_id.hex}'\"",
        "mock_repos.audit.create.assert_not_awaited()",
    ]:
        assert expected in block

    for weak_fragment in [
        'resp.json()["total"] == 0',
        'resp.json()["total"]',
    ]:
        assert weak_fragment not in block


def test_quality_ops_capture_run_cancel_success_exact_response_redis_audit_contract():
    quality_ops = _quality_ops_rows_containing(
        "Run cancel status event direct payload/timestamp 契约",
        "Run cancel success exact response/Redis/audit 契约",
    )
    runs_test = _read(RUNS_TEST)

    assert "Run cancel status event direct payload/timestamp 契约" in quality_ops
    assert (
        "`tests/unit/test_api/test_runs.py::test_cancel_run` 1 passed；runs full 51 passed；release quality docs contract full 339 passed"
        in quality_ops
    )
    assert "status event timestamp 解析为 timezone-aware UTC" in quality_ops
    assert "完整 event dict 等值锁住 run_id/status/previous/timestamp" in (
        quality_ops
    )
    assert "`assert set(event)` 字段集合守门" in quality_ops
    assert "timestamp 变成本地/naive 时间" in quality_ops
    assert "cancel status event direct payload/timestamp 契约" in quality_ops
    assert "取消事件测试只证明“字段集合看起来对”" in quality_ops

    assert "Run cancel success exact response/Redis/audit 契约" in quality_ops
    assert (
        "`tests/unit/test_api/test_runs.py::test_cancel_run` 1 passed；runs full 50 passed"
        in quality_ops
    )
    assert "固定完整响应体、`cancel_if_current` 可取消状态集合" in quality_ops
    assert "status stream/hash 的完整 payload 与同一 timestamp" in quality_ops
    assert "`run.cancel` 审计的完整 before/after/cancel_reason payload" in (
        quality_ops
    )
    assert "此前只抽查 response id/status、Redis event/hash 的 status/previous" in (
        quality_ops
    )
    assert "可取消状态少了 preparing/collecting" in quality_ops
    assert "status hash 与 stream timestamp 不一致" in quality_ops
    assert "取消成功测试只证明“状态大概变成 cancelled”" in quality_ops

    assert "def _json_datetime(value: datetime) -> str:" in runs_test
    assert "def _expected_run_response(run) -> dict:" in runs_test
    block = _marked_block(
        runs_test,
        "async def test_cancel_run",
        "async def test_cancel_run_rejects_overlong_reason_without_side_effects",
    )

    assert "expected_before = _expected_run_response(before_run)" in block
    assert "expected_after = _expected_run_response(after_run)" in block
    assert (
        'expected_after_audit = {**expected_after, "cancel_reason": "operator-request"}'
        in block
    )
    assert "assert body == expected_after" in block
    assert "assert cancel_args.kwargs == {" in block
    for status in [
        "RunStatusEnum.QUEUED",
        "RunStatusEnum.PREPARING",
        "RunStatusEnum.RUNNING",
        "RunStatusEnum.COLLECTING",
    ]:
        assert status in block
    assert 'event_timestamp = datetime.fromisoformat(event["timestamp"])' in block
    assert "assert event_timestamp.tzinfo is not None" in block
    assert (
        "assert event_timestamp.utcoffset() == timezone.utc.utcoffset(event_timestamp)"
        in block
    )
    assert "assert set(event)" not in block
    assert '"timestamp": event["timestamp"]' in block
    assert "assert redis.hset.await_args.args == (f\"run:{run_id}:status\",)" in (
        block
    )
    assert "assert redis.hset.await_args.kwargs == {" in block
    assert '"mapping": {"status": "cancelled", "timestamp": event["timestamp"]}' in (
        block
    )
    assert "assert audit_kwargs == {" in block
    for audit_field in [
        '"tenant_id": mock_user.tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "run.cancel"',
        '"resource_type": "run"',
        '"resource_id": run_id',
        '"before_state": expected_before',
        '"after_state": expected_after_audit',
    ]:
        assert audit_field in block

    assert 'body["id"]' not in block
    assert 'body["status"]' not in block
    assert 'cancel_args.kwargs["expected_in"]' not in block
    assert 'redis.hset.await_args.kwargs["mapping"]["status"]' not in block
    assert 'audit_kwargs["action"]' not in block
    assert 'audit_kwargs["after_state"]["status"]' not in block


def test_quality_ops_capture_run_trigger_success_exact_response_audit_rbac_contract():
    runs_test = _read(RUNS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run trigger success exact response/audit/RBAC 契约）"
    )

    assert "Run trigger success exact response/audit/RBAC 契约" in row
    assert (
        "`tests/unit/test_api/test_runs.py::test_trigger_run tests/unit/test_api/test_runs.py::test_trigger_run_stays_queued_and_audited_without_arq_pool` 2 passed"
        in row
    )
    assert "runs full 51 passed" in row
    assert "release quality docs contract full 183 passed" in row
    assert "固定完整 RunResponse、`RUN_TRIGGER` 权限参数" in row
    assert "`run.create` metadata/priority、retry_group、queue metadata 或 no-queue 副作用" in (
        row
    )
    assert "`run.trigger` audit tenant/user/before_state/after_state 完整等于响应" in (
        row
    )
    assert "此前只抽查 status/project_id/pipeline_id/environment/git_ref 和 audit status" in (
        row
    )
    assert "audit after_state 只写子集" in row
    assert "no-arq 分支误写 queue metadata" in row
    assert "手动触发成功测试只证明“Run 大概 queued 且审计大概写过”" in row

    assert "def _assert_run_trigger_audit(" in runs_test
    helper_block = _marked_block(
        runs_test,
        "def _assert_run_trigger_audit(",
        "_TOO_LONG_RESULT_FILTER",
    )
    for expected in [
        '"tenant_id": mock_user.tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "run.trigger"',
        '"resource_type": "run"',
        '"resource_id": run.id',
        '"before_state": None',
        '"after_state": after_state',
    ]:
        assert expected in helper_block

    trigger_block = _marked_block(
        runs_test,
        "async def test_trigger_run(",
        "async def test_trigger_run_includes_git_auth_metadata_without_plaintext",
    )
    no_arq_block = _marked_block(
        runs_test,
        "async def test_trigger_run_stays_queued_and_audited_without_arq_pool",
        "async def test_trigger_run_pipeline_not_found",
    )

    for block in [trigger_block, no_arq_block]:
        assert "from qaplatform.api.auth.permissions import Action" in block
        assert '"qaplatform.api.v1.runs.enforce_project_action"' in block
        assert "assert body == _expected_run_response(run)" in block
        assert "assert enforce_project_action.await_args.kwargs == {}" in block
        assert "Action.RUN_TRIGGER" in block
        assert "_assert_run_trigger_audit(mock_repos, mock_user, run, body)" in block
        assert 'body["status"] == "queued"' not in block
        assert 'audit_kwargs["after_state"]["status"]' not in block

    assert "mock_run_repo.mark_enqueued.assert_awaited_once()" in trigger_block
    assert "mock_run_repo.mark_waiting.assert_not_awaited()" in trigger_block
    assert "mock_run_repo.mark_enqueued.assert_not_awaited()" in no_arq_block
    assert "mock_run_repo.mark_waiting.assert_not_awaited()" in no_arq_block


def test_quality_ops_capture_run_trigger_priority_exact_queue_audit_contract():
    runs_test = _read(RUNS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run trigger priority exact queue/audit 契约）"
    )

    assert "Run trigger priority exact queue/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_runs.py::test_trigger_run_with_high_priority tests/unit/test_api/test_runs.py::test_trigger_run_default_priority` 2 passed"
        in row
    )
    assert "runs full 51 passed" in row
    assert "release quality docs contract full 189 passed" in row
    assert "固定完整 RunResponse" in row
    assert "`RUN_TRIGGER` 权限" in row
    assert "pipeline/project/default environment 查找" in row
    assert "`run.create` 完整 kwargs" in row
    assert "ARQ queue:high/queue:medium 入队参数" in row
    assert "mark_enqueued metadata" in row
    assert "`run.trigger` audit 完整等于响应" in row
    assert "此前只断言响应 `priority` 和 create kwargs 里的 priority" in row
    assert "Run priority 正向测试只证明“priority 数字写进去了”" in row

    high_block = _marked_block(
        runs_test,
        "async def test_trigger_run_with_high_priority",
        "async def test_trigger_run_priority_validation",
    )
    default_block = _marked_block_or_tail(
        runs_test,
        "async def test_trigger_run_default_priority",
        "\n\n@pytest.mark.asyncio",
    )

    for block, priority, queue in [
        (high_block, "0", "queue:high"),
        (default_block, "1", "queue:medium"),
    ]:
        for expected in [
            "from qaplatform.api.auth.permissions import Action",
            '"qaplatform.api.v1.runs.enforce_project_action"',
            "assert body == _expected_run_response(run)",
            "enforce_project_action.assert_awaited_once()",
            "assert enforce_project_action.await_args.kwargs == {}",
            "Action.RUN_TRIGGER",
            "mock_pipeline_repo.get_by_id.assert_awaited_once_with(pipeline_id)",
            "mock_project_repo.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)",
            "mock_environment_repo.get_by_id.assert_not_awaited()",
            "mock_environment_repo.list_by_project.assert_not_awaited()",
            "mock_run_repo.create.assert_awaited_once_with(",
            "tenant_id=tenant_id",
            "project_id=project_id",
            "pipeline_id=pipeline_id",
            "environment_id=env_id",
            'git_ref="main"',
            "git_sha=None",
            "triggered_by=mock_user.user_id",
            'trigger_type="manual"',
            f"priority={priority}",
            '"git_url": "https://github.com/example/repo.git"',
            '"shallow_clone": True',
            '"default_branch": "main"',
            "mock_run_repo.set_retry_group_id.assert_awaited_once_with(run.id, run.id)",
            "mock_arq.enqueue_job.assert_awaited_once_with(",
            f'_queue_name="{queue}"',
            '_job_id=f"run:{run.id}"',
            "_defer_by=0",
            "assert mock_run_repo.mark_enqueued.await_args.args == (run.id,)",
            f'await_args.kwargs["queue_name"] == "{queue}"',
            "await_args.kwargs[\"arq_job_id\"] == f\"run:{run.id}\"",
            'await_args.kwargs["enqueued_at"].tzinfo is not None',
            "mock_run_repo.mark_waiting.assert_not_awaited()",
            "_assert_run_trigger_audit(mock_repos, mock_user, run, body)",
        ]:
            assert expected in block
        assert 'resp.json()["priority"]' not in block
        assert 'create_kwargs = mock_run_repo.create.await_args.kwargs' not in block
        assert 'create_kwargs["priority"]' not in block


def test_quality_ops_capture_run_artifacts_list_exact_response_contract():
    runs_test = _read(RUNS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run artifacts list exact response/DB-only 契约）"
    )

    assert "Run artifacts list exact response/DB-only 契约" in row
    assert "`tests/unit/test_api/test_runs.py::test_get_run_artifacts` 1 passed" in (
        row
    )
    assert "runs full 50 passed" in row
    assert "release quality docs contract full 165 passed" in row
    assert "完整 ArtifactResponse 分页壳" in row
    assert "id/run_id/type/name/storage_path/size_bytes/mime_type/expires_at/created_at" in (
        row
    )
    assert "`page=3/per_page=7 -> offset=14/limit=7`" in row
    assert "tenant-scoped run lookup" in row
    assert "RBAC `RUN_READ`" in row
    assert "DB-only 列表不触碰 S3 get/presign" in row
    assert "此前只断言 `total == 0`" in row
    assert "漏掉权限校验" in row
    assert "分页 offset 算错" in row
    assert "run artifacts 单测只证明“能返回一个空分页”" in row

    test_block = _marked_block(
        runs_test,
        "async def test_get_run_artifacts",
        "async def test_get_archived_run_logs_reads_s3_jsonl",
    )

    assert "from qaplatform.api.auth.permissions import Action" in test_block
    assert "artifact.id = artifact_id" in test_block
    assert "artifact.run_id = run_id" in test_block
    assert 'artifact.type = "junit"' in test_block
    assert 'artifact.name = "reports/junit.xml"' in test_block
    assert "artifact.storage_path =" in test_block
    assert "artifact.size_bytes = 4096" in test_block
    assert 'artifact.mime_type = "application/xml"' in test_block
    assert "artifact.expires_at = expires_at" in test_block
    assert "artifact.created_at = created_at" in test_block
    assert "page=3&per_page=7" in test_block
    assert "assert body == {" in test_block
    for response_field in [
        '"id": str(artifact_id)',
        '"run_id": str(run_id)',
        '"type": "junit"',
        '"name": "reports/junit.xml"',
        '"storage_path": f"s3://qa-platform/artifacts/{run_id}/junit.xml"',
        '"size_bytes": 4096',
        '"mime_type": "application/xml"',
        '"expires_at": _json_datetime(expires_at)',
        '"created_at": _json_datetime(created_at)',
        '"page": 3',
        '"per_page": 7',
        '"total": 42',
    ]:
        assert response_field in test_block
    assert "mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)" in (
        test_block
    )
    assert "enforce_project_action.assert_awaited_once()" in test_block
    assert "Action.RUN_READ" in test_block
    assert "mock_artifact_repo.list_by_run.assert_awaited_once_with(" in test_block
    assert "offset=14" in test_block
    assert "limit=7" in test_block
    assert "s3_client.get_object.assert_not_awaited()" in test_block
    assert "s3_client.generate_presigned_url.assert_not_awaited()" in test_block
    assert 'resp.json()["total"]' not in test_block


def test_quality_ops_capture_run_archived_logs_s3_key_page_rbac_contract():
    runs_test = _read(RUNS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run archived logs S3 key/page/RBAC 契约）"
    )

    assert "Run archived logs S3 key/page/RBAC 契约" in row
    assert (
        "`tests/unit/test_api/test_runs.py::test_get_archived_run_logs_reads_s3_jsonl` 1 passed"
        in row
    )
    assert "runs full 50 passed" in row
    assert "release quality docs contract full 166 passed" in row
    assert "`page=2&per_page=1`" in row
    assert "只回放第二条 stderr" in row
    assert "tenant-scoped run lookup" in row
    assert "RBAC `RUN_READ`" in row
    assert 'S3 `get_object(Bucket="qa-platform", Key=f"logs/{run.id}.jsonl")`' in (
        row
    )
    assert "不会生成 presign URL" in row
    assert "此前只检查 `total == 2` 和完整 data 内容" in row
    assert "route 忽略分页" in row
    assert "读错 S3 key/bucket" in row
    assert "archived logs 成功单测只证明“能解析一段 JSONL”" in row

    test_block = _marked_block(
        runs_test,
        "async def test_get_archived_run_logs_reads_s3_jsonl",
        "async def test_get_archived_run_logs_returns_503_without_s3",
    )

    assert "from qaplatform.api.auth.permissions import Action" in test_block
    assert "project_id = uuid.uuid4()" in test_block
    assert "_make_orm_run(tenant_id=tenant_id, project_id=project_id)" in (
        test_block
    )
    assert "logs/archive?page=2&per_page=1" in test_block
    assert "assert resp.json() == {" in test_block
    for expected in [
        '"data": [{"stream": "stderr", "line": "second"}]',
        '"page": 2',
        '"per_page": 1',
        '"total": 2',
        "mock_run_repo.get_for_tenant.assert_awaited_once_with(run.id, tenant_id)",
        "enforce_project_action.assert_awaited_once()",
        "Action.RUN_READ",
        "s3_client.get_object.assert_awaited_once_with(",
        'Bucket="qa-platform"',
        'Key=f"logs/{run.id}.jsonl"',
        "s3_client.generate_presigned_url.assert_not_awaited()",
    ]:
        assert expected in test_block
    assert 'body["total"]' not in test_block
    assert 'body["data"]' not in test_block


def test_quality_ops_capture_run_notifications_exact_page_rbac_contract():
    runs_test = _read(RUNS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run notifications exact page/RBAC 契约）"
    )

    assert "Run notifications exact page/RBAC 契约" in row
    assert (
        "`tests/unit/test_api/test_runs.py::test_get_run_notifications_returns_exact_page_and_rbac` 1 passed"
        in row
    )
    assert "runs full 51 passed" in row
    assert "release quality docs contract full 168 passed" in row
    assert "完整 NotificationLogResponse 分页壳" in row
    assert "id/project_id/run_id/rule_id/channel_type/status/error_message/sent_at" in (
        row
    )
    assert "`page=3/per_page=4 -> offset=8/limit=4`" in row
    assert "tenant-scoped run lookup" in row
    assert "RBAC `NOTIFICATION_READ`" in row
    assert "列表读面不写 audit" in row
    assert "此前只有缺失 run 短路覆盖" in row
    assert "漏掉通知读权限" in row
    assert "分页参数算错" in row
    assert "缺失资源不会触碰下游" in row

    test_block = _marked_block(
        runs_test,
        "async def test_get_run_notifications_returns_exact_page_and_rbac",
        "async def test_trigger_run_archived_project_returns_409",
    )

    assert "from qaplatform.api.auth.permissions import Action" in test_block
    assert "sent_at = datetime(2026, 5, 31, 15, 16, 17, tzinfo=timezone.utc)" in (
        test_block
    )
    assert "logs.archive" not in test_block
    assert "notifications?page=3&per_page=4" in test_block
    assert "assert resp.json() == {" in test_block
    for expected in [
        '"id": str(log_id)',
        '"project_id": str(project_id)',
        '"run_id": str(run_id)',
        '"rule_id": str(rule_id)',
        '"channel_type": "email"',
        '"status": "failed"',
        '"error_message": "SMTP timeout"',
        '"sent_at": _json_datetime(sent_at)',
        '"page": 3',
        '"per_page": 4',
        '"total": 9',
        "mock_run_repo.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)",
        "enforce_project_action.assert_awaited_once()",
        "Action.NOTIFICATION_READ",
        "mock_repos.notification_log.list_by_run.assert_awaited_once_with(",
        "offset=8",
        "limit=4",
        "mock_repos.audit.create.assert_not_awaited()",
    ]:
        assert expected in test_block


def test_quality_ops_capture_run_detail_exact_response_rbac_contract():
    runs_test = _read(RUNS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run detail exact response/RBAC 契约）"
    )

    assert "Run detail exact response/RBAC 契约" in row
    assert "`tests/unit/test_api/test_runs.py::test_get_run` 1 passed" in row
    assert "runs full 51 passed" in row
    assert "release quality docs contract full 169 passed" in row
    assert "完整 RunResponse" in row
    assert "tenant/project/pipeline/environment/pipeline_name/status/priority/trigger/git/timestamps/summary/error" in (
        row
    )
    assert "`get_for_tenant(run.id, tenant_id)`" in row
    assert "RBAC `RUN_READ`" in row
    assert "此前只断言响应 id 和 tenant-scoped lookup" in row
    assert "详情 DTO 漏字段" in row
    assert "项目级读权限" in row
    assert "run detail 测试只证明“能按 id 返回一个对象”" in row

    test_block = _marked_block(
        runs_test,
        "async def test_get_run",
        "async def test_get_run_not_found",
    )

    assert "from qaplatform.api.auth.permissions import Action" in test_block
    assert "with patch(" in test_block
    assert '"qaplatform.api.v1.runs.enforce_project_action"' in test_block
    assert "assert resp.json() == _expected_run_response(run)" in test_block
    assert "mock_run_repo.get_for_tenant.assert_awaited_once_with(run.id, tenant_id)" in (
        test_block
    )
    assert "enforce_project_action.assert_awaited_once()" in test_block
    assert "Action.RUN_READ" in test_block
    assert 'resp.json()["id"]' not in test_block


def test_quality_ops_capture_sse_ticket_atomic_exact_projection_contract():
    sse_test = _read(SSE_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（SSE ticket atomic result exact projection 契约）"
    )

    assert "SSE ticket atomic result exact projection 契约" in row
    assert (
        "`tests/unit/test_api/test_sse.py::test_authenticate_sse_ticket_consumes_atomically` 1 passed"
        in row
    )
    assert "sse full 23 passed" in row
    assert "release quality docs contract full 197 passed" in row
    assert "`asyncio.gather` 的两个返回结果投影为 exact unordered list" in row
    assert "一个 401 `Invalid or expired SSE ticket`" in row
    assert "完整 UserIdentity(user_id/role/tenant_id/scopes)" in row
    assert "no `get`/`delete` fallback" in row
    assert "`len(successes) == 1` / `len(failures) == 1`" in row
    assert "只证明“一成一败”" in row
    assert "无意外返回类型" in row
    assert "ticket 防泄漏" in row
    assert "只为覆盖 atomic 分支而存在" in row

    test_block = _marked_block(
        sse_test,
        "async def test_authenticate_sse_ticket_consumes_atomically",
        "async def test_authenticate_sse_ticket_rejects_legacy_payload_without_scopes",
    )

    for expected in [
        "def _project_result(result):",
        "return (",
        '"success",',
        "str(result.user_id)",
        "result.role",
        "str(result.tenant_id)",
        "result.scopes",
        'return ("failure", result.status_code, result.detail)',
        'return ("unexpected", type(result).__name__, repr(result))',
        "assert sorted(_project_result(result) for result in results) == [",
        '("failure", 401, "Invalid or expired SSE ticket")',
        '("success", str(user_id), role, str(tenant_id), None)',
        "failure = next(result for result in results if isinstance(result, HTTPException))",
        'assert failure.detail == "Invalid or expired SSE ticket"',
        "assert ticket not in failure.detail",
        "assert ticket not in repr(results)",
        "assert [call.args for call in mock_redis.getdel.await_args_list] == [",
        "mock_redis.get.assert_not_awaited()",
        "mock_redis.delete.assert_not_awaited()",
    ]:
        assert expected in test_block
    assert "successes = [" not in test_block
    assert "failures = [" not in test_block
    assert "assert len(successes)" not in test_block
    assert "assert len(failures)" not in test_block
    assert "success = successes[0]" not in test_block
    assert "failure = failures[0]" not in test_block


def test_quality_ops_capture_run_status_event_direct_payload_projection_contract():
    events_test = _read(ENGINE_EVENTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run status event direct payload/log projection 契约） | `tests/unit/test_engine/test_events.py` 4 passed；release quality docs contract full 336 passed"
    )

    assert "xadd event 直接等值为完整 payload dict" in row
    assert "warning 投影为唯一 `{levelno,message,exc_type,exc_message}`" in row
    assert "`assert set(event)`" in row
    assert "`len(records)` / `records[0]`" in row
    assert "direct payload/log projection 契约" in row
    assert "字段集合和 warning 数量看起来对" in row

    assert "assert set(event)" not in events_test
    assert "assert len(records) == 1" not in events_test
    assert "records[0]" not in events_test

    previous_block = _block_between(events_test, "async def test_publish_status_event_writes_stream_and_hash", "async def test_publish_status_event_omits_previous_when_none")
    no_previous_block = _block_between(events_test, "async def test_publish_status_event_omits_previous_when_none", "async def test_publish_status_event_silent_when_redis_none")
    failure_block = _after(
        events_test,
        "async def test_publish_status_event_swallows_redis_errors",
    )

    for block in [previous_block, no_previous_block, failure_block]:
        assert "assert event == {" in block
        assert '"timestamp": event["timestamp"]' in block

    assert '"previous": "preparing"' in previous_block
    assert '"previous": "preparing"' not in no_previous_block
    assert "warning_records = [" in failure_block
    assert "assert warning_records == [" in failure_block
    assert '"levelno": logging.WARNING' in failure_block
    assert '"message": "failed to publish status event for run rid (status=running)"' in (
        failure_block
    )
    assert '"exc_type": "RuntimeError"' in failure_block
    assert '"exc_message": "redis down"' in failure_block


def test_quality_ops_capture_run_status_event_no_previous_exact_stream_hash_contract():
    events_test = _read(ENGINE_EVENTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run status event no-previous exact stream/hash 契约）"
    )

    assert "Run status event no-previous exact stream/hash 契约" in row
    assert (
        "`tests/unit/test_engine/test_events.py::test_publish_status_event_omits_previous_when_none` 1 passed"
        in row
    )
    assert "events full 4 passed" in row
    assert "release quality docs contract full 199 passed" in row
    assert "完整 xadd stream 与 payload dict" in row
    assert "timezone-aware timestamp" in row
    assert "hset status hash 与 stream event 复用同一个 timestamp" in row
    assert "此前只检查 `\"previous\" not in event`" in row
    assert "stream key 漂移" in row
    assert "hset 不写或使用另一 timestamp" in row
    assert "只证明“payload 没有 previous 字段”" in row

    test_block = _marked_block(
        events_test,
        "async def test_publish_status_event_omits_previous_when_none",
        "async def test_publish_status_event_silent_when_redis_none",
    )

    for expected in [
        'run_id = "rid"',
        "redis.xadd.assert_awaited_once_with(",
        "EVENT_STREAM_KEY.format(run_id=run_id)",
        '"run_id": run_id',
        '"status": "queued"',
        '"timestamp": ANY',
        "assert event == {",
        '"timestamp": event["timestamp"]',
        'datetime.fromisoformat(event["timestamp"]).tzinfo is not None',
        "redis.hset.assert_awaited_once_with(",
        "STATUS_HASH_KEY.format(run_id=run_id)",
        '"timestamp": event["timestamp"]',
    ]:
        assert expected in test_block
    assert 'assert "previous" not in event' not in test_block
    assert "assert set(event)" not in test_block


def test_quality_ops_capture_run_status_event_previous_exact_stream_hash_contract():
    events_test = _read(ENGINE_EVENTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run status event previous exact stream/hash 契约）"
    )

    assert "Run status event previous exact stream/hash 契约" in row
    assert (
        "`tests/unit/test_engine/test_events.py::test_publish_status_event_writes_stream_and_hash` 1 passed"
        in row
    )
    assert "events full 4 passed" in row
    assert "release quality docs contract full 220 passed" in row
    assert "xadd stream 与完整 payload dict" in row
    assert "UTC timestamp 请求窗口" in row
    assert "previous 值" in row
    assert "hset status hash 与 stream event 复用同一个 timestamp" in row
    assert "此前只逐字段抽查 run_id/status/previous" in row
    assert "timestamp 使用非 UTC 或陈旧时间" in row
    assert "hash timestamp 与 event timestamp 分叉" in row
    assert "写了 running/preparing 这几个字段" in row

    test_block = _marked_block(
        events_test,
        "async def test_publish_status_event_writes_stream_and_hash",
        "async def test_publish_status_event_omits_previous_when_none",
    )

    for expected in [
        "started_at = datetime.now(timezone.utc)",
        "finished_at = datetime.now(timezone.utc)",
        "redis.xadd.assert_awaited_once_with(",
        "EVENT_STREAM_KEY.format(run_id=run_id)",
        '"run_id": run_id',
        '"status": "running"',
        '"timestamp": ANY',
        '"previous": "preparing"',
        'event = redis.xadd.await_args.args[1]',
        'event_timestamp = datetime.fromisoformat(event["timestamp"])',
        "assert event == {",
        '"timestamp": event["timestamp"]',
        "assert started_at <= event_timestamp <= finished_at",
        "assert event_timestamp.tzinfo is timezone.utc",
        "redis.hset.assert_awaited_once_with(",
        "STATUS_HASH_KEY.format(run_id=run_id)",
        '"timestamp": event["timestamp"]',
    ]:
        assert expected in test_block

    assert 'datetime.fromisoformat(event["timestamp"]).tzinfo is not None' not in (
        test_block
    )
    assert "assert set(event)" not in test_block


def test_quality_ops_capture_run_status_event_redis_failure_exact_log_no_hash_contract():
    events_test = _read(ENGINE_EVENTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run status event Redis failure exact log/no-hash 契约）"
    )

    assert "Run status event Redis failure exact log/no-hash 契约" in row
    assert (
        "`tests/unit/test_engine/test_events.py::test_publish_status_event_swallows_redis_errors` 1 passed"
        in row
    )
    assert "events full 4 passed" in row
    assert "release quality docs contract full 219 passed" in row
    assert "xadd stream 与完整 payload dict" in row
    assert "UTC timestamp 请求窗口" in row
    assert "hset 不执行" in row
    assert "warning 投影唯一" in row
    assert "exc_info 保留原始 `RuntimeError(\"redis down\")`" in row
    assert "此前只用 `caplog.text` 包含式" in row
    assert "事件 timestamp 退成本地时区" in row
    assert "异常上下文被吞掉" in row
    assert "没有抛异常且日志里有 run id" in row

    test_block = _marked_block_or_tail(
        events_test,
        "async def test_publish_status_event_swallows_redis_errors",
        "\n\n@pytest.mark.asyncio",
    )

    for expected in [
        'redis.xadd.side_effect = RuntimeError("redis down")',
        "started_at = datetime.now(timezone.utc)",
        "finished_at = datetime.now(timezone.utc)",
        "redis.xadd.assert_awaited_once_with(",
        'EVENT_STREAM_KEY.format(run_id="rid")',
        '"run_id": "rid"',
        '"status": "running"',
        '"timestamp": ANY',
        'event = redis.xadd.await_args.args[1]',
        'event_timestamp = datetime.fromisoformat(event["timestamp"])',
        "assert event == {",
        '"timestamp": event["timestamp"]',
        "assert started_at <= event_timestamp <= finished_at",
        "assert event_timestamp.tzinfo is timezone.utc",
        "redis.hset.assert_not_awaited()",
        "warning_records = [",
        '"levelno": record.levelno',
        '"message": record.getMessage()',
        '"exc_type": (',
        '"exc_message": (',
        "assert warning_records == [",
        '"levelno": logging.WARNING',
        '"message": "failed to publish status event for run rid (status=running)"',
        '"exc_type": "RuntimeError"',
        '"exc_message": "redis down"',
    ]:
        assert expected in test_block

    assert 'assert "failed to publish status event for run rid" in caplog.text' not in (
        test_block
    )
    assert "assert len(records) == 1" not in test_block
    assert "assert set(event)" not in test_block
    assert "records[0]" not in test_block
    assert "redis.hset.assert_awaited_once" not in test_block


def test_quality_ops_capture_run_results_filter_empty_page_exact_contract():
    runs_test = _read(RUNS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run results filter empty page exact 契约）"
    )

    assert "Run results filter empty page exact 契约" in row
    assert (
        "`tests/unit/test_api/test_runs.py::test_get_run_results_filters_by_suite tests/unit/test_api/test_runs.py::test_get_run_results_filters_by_keyword tests/unit/test_api/test_runs.py::test_get_run_results_combines_suite_and_keyword tests/unit/test_api/test_runs.py::test_get_run_results_escapes_keyword_like_wildcards` 4 passed"
        in row
    )
    assert "空结果分页响应体" in row
    assert "`{\"data\":[],\"page\":1,\"per_page\":20,\"total\":0}`" in row
    assert "默认 offset/limit" in row
    assert "只断言 200 与 repo filters" in row
    assert "过滤条件大概传下去了" in row

    for expected in [
        "def _assert_empty_paginated_response(resp, *, page: int = 1, per_page: int = 20) -> None:",
        "_assert_empty_paginated_response(resp)",
        'assert list_kwargs["offset"] == 0',
        'assert list_kwargs["limit"] == 20',
        'assert resp.json() == {',
        '"data": [],',
        '"page": page,',
        '"per_page": per_page,',
        '"total": 0,',
    ]:
        assert expected in runs_test
