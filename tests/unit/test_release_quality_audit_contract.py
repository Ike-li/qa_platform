from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _block_between,
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
AUDIT_EVENTS_API = ROOT / "tests" / "integration" / "test_audit_events_api.py"
AUDIT_EVENTS_DIRECT_TEST = (
    ROOT / "tests" / "unit" / "test_api" / "test_audit_events.py"
)
AUDIT_TEST = ROOT / "tests" / "unit" / "test_api" / "test_audit.py"
T02_AUDIT_QUERY = ROOT / "docs" / "tasks" / "T02_audit_query_api.md"


def test_quality_ops_capture_audit_events_owner_admin_exact_list_contract():
    row = _quality_ops_row_containing(
        "Audit events owner/admin 与过滤排序集成路径"
    )
    audit_events_api = _read(AUDIT_EVENTS_API)

    assert "Audit events owner/admin 与过滤排序集成路径" in row
    assert "完整 AuditEventResponse" in row
    assert "两次成功查询各写 1 条 `audit_events.list` 自审计" in row
    assert "def _json_datetime(value: datetime) -> str:" in audit_events_api
    assert "expected_event = {" in audit_events_api
    assert "assert owner_body == {" in audit_events_api
    assert "assert admin_body == {" in audit_events_api
    assert '"ip_address": None' in audit_events_api
    assert '"user_agent": None' in audit_events_api
    assert '"created_at": _json_datetime(event.created_at)' in audit_events_api
    assert 'assert [item["id"] for item in owner_body["data"]] == [str(event.id)]' not in (
        audit_events_api
    )
    assert 'assert [item["id"] for item in admin_body["data"]] == [str(event.id)]' not in (
        audit_events_api
    )
    assert 'assert all(item["resource_type"] == "project" for item in body["data"])' not in (
        audit_events_api
    )
    assert "assert before_denied_count == 2" in audit_events_api
    assert 'owner_body["total"] >= 1' not in audit_events_api
    assert 'admin_body["total"] >= 1' not in audit_events_api


def test_quality_ops_capture_audit_events_empty_list_exact_response_contract():
    row = _quality_ops_row_containing(
        "audit-events 跨租户隔离用例的成功空列表路径现在固定"
    )
    audit_events_api = _read(AUDIT_EVENTS_API)
    test_block = _block_between(audit_events_api, "async def test_audit_events_tenant_isolation_and_cross_tenant_ids_return_404", "async def test_audit_events_list_access_writes_audit_event")

    assert "audit-events 跨租户隔离用例的成功空列表路径现在固定" in row
    assert "release quality docs contract full 247 passed" in row
    assert "避免 audit-events 跨租户测试只证明“过滤后没有数据”" in (
        row
    )
    assert 'params={"resource_type": "credential", "page": 99, "per_page": 7}' in (
        test_block
    )
    assert "assert resource_type_resp.json() == {" in test_block
    assert '"data": []' in test_block
    assert '"page": 99' in test_block
    assert '"per_page": 7' in test_block
    assert '"total": 0' in test_block
    assert 'resource_type_resp.json()["total"]' not in test_block
    assert 'resource_type_resp.json()["data"]' not in test_block


def test_quality_ops_capture_audit_events_list_access_exact_response_self_audit_contract():
    audit_events_api = _read(AUDIT_EVENTS_API)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_audit_events_api.py::test_audit_events_list_access_writes_audit_event -q` 1 passed | release quality docs contract full 335 passed"
    )
    test_block = _after(
        audit_events_api,
        "async def test_audit_events_list_access_writes_audit_event",
    )

    assert "audit-events list access 自审计集成用例" in row
    assert '`{"data":[],"page":1,"per_page":20,"total":0}`' in row
    assert "解包为唯一 `{resource_id,before_state,after_state}` 投影" in row
    assert "`after_state` 对 actor/action/resource/time/page/per_page/total 完整等值" in (
        row
    )
    assert "audit-events list access exact response/self-audit direct projection 契约" in row
    assert "只证明“访问会写自审计”" in row
    assert "后来仍用 `len(events) == 1`" in row

    assert "assert resp.json() == {" in test_block
    assert '"data": []' in test_block
    assert '"page": 1' in test_block
    assert '"per_page": 20' in test_block
    assert '"total": 0' in test_block
    assert "(event,) = [" in test_block
    assert '"resource_id": event.resource_id' in test_block
    assert '"before_state": event.before_state' in test_block
    assert '"after_state": event.after_state' in test_block
    assert 'assert event == {' in test_block
    assert '"resource_id": None' in test_block
    assert '"before_state": None' in test_block
    assert '"after_state": {' in test_block
    for expected in [
        '"actor_id": None',
        '"action": None',
        '"resource_type": None',
        '"resource_id": None',
        '"start_at": None',
        '"end_at": None',
        '"page": 1',
        '"per_page": 20',
        '"total": 0',
        'assert "data" not in event["after_state"]',
    ]:
        assert expected in test_block
    for removed in [
        "event = result.scalars().first()",
        "assert event is not None",
        "events = list(result.scalars().all())",
        "assert len(events) == 1",
        'event.after_state["page"]',
        'event.after_state["per_page"]',
    ]:
        assert removed not in test_block


def test_quality_ops_capture_audit_events_cross_tenant_exact_envelope_contract():
    audit_events_api = _read(AUDIT_EVENTS_API)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_audit_events_api.py::test_audit_events_refused_queries_do_not_write_self_audit tests/integration/test_audit_events_api.py::test_audit_events_tenant_isolation_and_cross_tenant_ids_return_404` 2 passed | release quality docs contract full 263 passed"
    )

    assert "audit-events 跨租户 404" in row
    assert (
        '`{"error":{"code":"NOT_FOUND","message":"Audit event not found","details":[]}}`'
        in row
    )
    assert "member/viewer 403 exact body" in row
    assert "tenant/user/project/event id 不回显" in row
    assert "不写 `audit_events.list` 自审计" in row
    assert '只断言 `resp.json()["error"]`' in row
    assert "顶层夹带 resource_id、tenant_id、hint 或 debug 字段" in row
    assert "audit-events cross-tenant exact envelope 契约" in row
    assert "只证明“error 子对象正确”" in row

    refused_block = _block_between(audit_events_api, "async def test_audit_events_refused_queries_do_not_write_self_audit", "async def test_audit_events_filters_combine_and_sort_desc")
    isolation_block = _block_between(audit_events_api, "async def test_audit_events_tenant_isolation_and_cross_tenant_ids_return_404", "async def test_audit_events_list_access_writes_audit_event")

    assert "assert cross_tenant_resp.json() == {" in refused_block
    assert "assert actor_resp.json() == not_found_body" in isolation_block
    assert "assert target_resp.json() == not_found_body" in isolation_block
    assert '"error": {' in refused_block
    assert '"error": {' in isolation_block
    assert 'json()["error"]' not in refused_block
    assert 'json()["error"]' not in isolation_block


def test_quality_ops_capture_audit_events_cross_tenant_exact_list_no_leak_contract():
    audit_events_api = _read(AUDIT_EVENTS_API)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 uv run pytest "
        "tests/integration/test_audit_events_api.py::"
        "test_audit_events_tenant_isolation_and_cross_tenant_ids_return_404 -q` "
        "1 passed"
    )
    isolation_block = _block_between(audit_events_api, "async def test_audit_events_tenant_isolation_and_cross_tenant_ids_return_404", "async def test_audit_events_list_access_writes_audit_event")

    assert "targeted docs contract passed" in row
    assert "targeted ruff passed" in row
    assert "唯一 action 固定完整 AuditEventResponse 分页 body" in row
    assert "跨租户 404 no-leak" in row
    assert "audit-events cross-tenant exact list/no-leak 契约" in row
    assert "只证明“看到 A 的 id 且没看到 B 的 id”" in row

    for expected in [
        'cross_tenant_action = f"project.update.{tenant_a.id.hex}"',
        "assert list_resp.json() == {",
        '"data": [',
        '"id": str(event_a.id)',
        '"tenant_id": str(tenant_a.id)',
        '"user_id": str(user_a.id)',
        '"action": cross_tenant_action',
        '"resource_type": "project"',
        '"resource_id": str(project_a.id)',
        '"before_state": None',
        '"after_state": {"ok": True}',
        '"ip_address": None',
        '"user_agent": None',
        '"created_at": _json_datetime(event_a.created_at)',
        '"page": 1',
        '"per_page": 100',
        '"total": 1',
        "leaked_cross_tenant_values = [",
        "assert leaked_cross_tenant_values == []",
    ]:
        assert expected in isolation_block
    assert 'ids = {item["id"] for item in list_resp.json()["data"]}' not in (
        isolation_block
    )
    assert "leaked_cross_tenant_ids.isdisjoint" not in isolation_block


def test_quality_ops_capture_audit_events_list_exact_response_contract():
    audit_test = _read(AUDIT_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Audit events list exact pagination body 契约） | `tests/unit/test_api/test_audit.py::test_audit_events_list_applies_filters_pagination_and_self_audits_summary` 1 passed；release quality docs contract full 335 passed"
    )

    assert "完整分页 body" in row
    assert "`page=3`、`per_page=2`、`total=7`" in row
    assert "完整 AuditEventResponse item 必须整体等值" in row
    assert "audit-events list exact pagination body 契约" in row
    assert '`body["page"]` / `body["per_page"]` / `body["total"]` 分散断言' in row
    assert "只证明“data 和几个分页数字分别看起来对”" in row

    audit_list_block = _block_between(audit_test, "async def test_audit_events_list_applies_filters_pagination_and_self_audits_summary", "\n\n@pytest.mark.asyncio")

    assert "assert body == {" in audit_list_block
    assert '"action": "project.create"' in audit_list_block
    assert '"resource_type": "project"' in audit_list_block
    assert '"before_state": None' in audit_list_block
    assert '"ip_address": "127.0.0.1"' in audit_list_block
    assert '"user_agent": "pytest"' in audit_list_block
    assert '"created_at": end_at.isoformat().replace("+00:00", "Z")' in audit_list_block
    assert '"page": 3' in audit_list_block
    assert '"per_page": 2' in audit_list_block
    assert '"total": 7' in audit_list_block
    assert 'assert body["page"] == 3' not in audit_list_block
    assert 'assert body["per_page"] == 2' not in audit_list_block
    assert 'assert body["total"] == 7' not in audit_list_block
    assert 'assert body["data"] == [' not in audit_list_block
    assert 'assert set(body["data"][0]) == {' not in audit_list_block
    assert 'body["data"][0]["after_state"] == event.after_state' not in audit_test


def test_quality_ops_capture_audit_events_unit_exact_envelope_contract():
    audit_test = _read(AUDIT_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Audit events unit exact envelope 契约） | `tests/unit/test_api/test_audit.py::test_audit_events_list_masks_cross_tenant_matches_without_self_audit tests/unit/test_api/test_audit.py::test_audit_events_rejects_invalid_text_filters_without_repo_lookup tests/unit/test_api/test_audit.py::test_audit_events_rejects_reversed_time_range_without_repo_lookup` 6 passed；release quality docs contract full 265 passed"
    )

    assert "audit-events 单元层跨租户 404 与参数 422" in row
    assert (
        '`{"error":{"code":"NOT_FOUND","message":"Audit event not found","details":[]}}`'
        in row
    )
    assert "`VALIDATION_ERROR` envelope" in row
    assert "不查仓储/不写 `audit_events.list` 自审计" in row
    assert '只断言 `resp.json()["error"]`' in row
    assert "resource_id、tenant_id、raw params、hint/debug 字段" in row
    assert "audit-events unit exact envelope 契约" in row
    assert "只证明“error 子对象正确且状态码对”" in row

    cross_tenant_block = _block_between(audit_test, "async def test_audit_events_list_masks_cross_tenant_matches_without_self_audit", "@pytest.mark.parametrize")
    invalid_filter_block = _block_between(audit_test, "async def test_audit_events_rejects_invalid_text_filters_without_repo_lookup", "@pytest.mark.asyncio\nasync def test_audit_events_rejects_reversed_time_range_without_repo_lookup")
    reversed_range_block = _block_between(audit_test, "async def test_audit_events_rejects_reversed_time_range_without_repo_lookup", "def test_audit_events_list_422_uses_error_response_schema")

    assert "assert resp.json() == {" in cross_tenant_block
    assert "assert resp.json() == {" in invalid_filter_block
    assert "assert resp.json() == {" in reversed_range_block
    assert '"error": {' in cross_tenant_block
    assert '"error": {' in invalid_filter_block
    assert '"error": {' in reversed_range_block
    assert 'resp.json()["error"]' not in cross_tenant_block
    assert 'resp.json()["error"]' not in invalid_filter_block
    assert 'resp.json()["error"]' not in reversed_range_block


def test_quality_ops_capture_write_audit_helper_complete_kwargs_contract():
    row = _quality_ops_row_containing("write_audit helper complete kwargs 契约")
    audit_test = _read(AUDIT_TEST)

    assert "write_audit helper complete kwargs 契约" in row
    assert "pydantic/dict/None/error-swallow 四条用例现在固定完整" in (
        row
    )
    assert "`repos.audit.create.await_args.kwargs`" in row
    assert "tenant/user/action/resource/before_state/after_state" in row
    assert "逐字段抽查少量 kwargs" in row
    assert "漏掉 before/after 的 `None` 壳" in row
    assert "几个字段看起来对" in row

    helper_block = _marked_block(
        audit_test,
        "async def test_write_audit_passes_through_to_repo",
        "# --- End-to-end route wiring verification ---",
    )

    assert helper_block.count("assert repos.audit.create.await_args.kwargs == {") == 4
    assert '"action": "project.create"' in helper_block
    assert '"action": "project.update"' in helper_block
    assert '"action": "anything"' in helper_block
    assert '"action": "env.update"' in helper_block
    assert '"before_state": None' in helper_block
    assert '"after_state": None' in helper_block
    assert '"before_state": {"name": "old", "value": 1}' in helper_block
    assert '"after_state": {"name": "new", "value": 2}' in helper_block
    assert '"before_state": {"a": 1}' in helper_block
    assert '"after_state": {"a": 2}' in helper_block
    assert "kwargs = repos.audit.create.await_args.kwargs" not in helper_block


def test_quality_ops_capture_write_audit_failure_exact_warning_contract():
    audit_test = _read(AUDIT_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（write_audit failure exact warning 契约）")

    assert (
        "`tests/unit/test_api/test_audit.py::test_write_audit_swallows_repo_errors` "
        "1 passed"
        in row
    )
    assert "audit unit full 13 passed" in row
    assert "release quality docs contract full 223 passed" in row
    assert "targeted ruff passed" in row
    assert "只记录一条 `qaplatform.api.audit` WARNING" in row
    assert "message 精确包含 action/resource/id" in row
    assert "exc_info 保留原始 `RuntimeError(\"audit table is down\")`" in row
    assert "完整 `repos.audit.create` kwargs" in row
    assert "只断言 `caplog.text` 包含 `audit write failed`" in row
    assert "日志级别漂移" in row
    assert "resource id/action 丢失" in row
    assert "日志里出现过一个大概的错误片段" in row

    block = _marked_block(
        audit_test,
        "async def test_write_audit_swallows_repo_errors",
        "async def test_write_audit_handles_dict_states",
    )

    assert "with caplog.at_level(logging.WARNING, logger=\"qaplatform.api.audit\"):" in (
        block
    )
    assert "assert repos.audit.create.await_args.kwargs == {" in block
    assert "record.name == \"qaplatform.api.audit\"" in block
    assert "record.levelno == logging.WARNING" in block
    assert '"levelno": record.levelno' in block
    assert '"message": record.getMessage()' in block
    assert '"exc_type": (' in block
    assert '"exc_message": (' in block
    assert "assert warning_records == [" in block
    assert '"levelno": logging.WARNING' in block
    assert (
        "f\"audit write failed (action=anything resource=x id={resource_id})\""
        in block
    )
    assert '"exc_type": "RuntimeError"' in block
    assert '"exc_message": "audit table is down"' in block
    assert "assert len(warning_records) == 1" not in block
    assert "warning_records[0]" not in block
    assert "assert \"audit write failed\" in caplog.text" not in block


def test_quality_ops_capture_project_create_audit_route_exact_wiring_contract():
    audit_test = _read(AUDIT_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project create audit route exact wiring 契约）"
    )

    assert "Project create audit route exact wiring 契约" in row
    assert (
        "`tests/unit/test_api/test_audit.py::test_project_create_route_invokes_audit` 1 passed"
        in row
    )
    assert "audit API full 13 passed" in row
    assert "release quality docs contract full 185 passed" in row
    assert "positional args 为 `(repos, user)`" in row
    assert "kwargs 精确等于 `project.create/project/project_id/after=response body`" in row
    assert "此前只证明 `write_audit` 被 await 且 after 非空" in row
    assert "路由传错 repos/user" in row
    assert "after_state 与响应体不一致" in row
    assert "项目创建审计接线测试只证明“审计函数大概被调用过”" in row

    block = _marked_block(
        audit_test,
        "async def test_project_create_route_invokes_audit",
        "async def test_audit_events_list_applies_filters_pagination_and_self_audits_summary",
    )

    assert "body = resp.json()" in block
    assert "audit_recorder.assert_awaited_once()" in block
    assert "assert audit_recorder.await_args.args == (repos, user)" in block
    assert "assert kwargs == {" in block
    for expected in [
        '"action": "project.create"',
        '"resource_type": "project"',
        '"resource_id": project_orm.id',
        '"after": body',
    ]:
        assert expected in block

    assert 'kwargs["action"]' not in block
    assert 'kwargs["resource_type"]' not in block
    assert 'kwargs["resource_id"]' not in block
    assert 'kwargs["after"] is not None' not in block


def test_quality_ops_capture_audit_events_direct_duplicate_cleanup_contract():
    t02 = _read(T02_AUDIT_QUERY)
    audit_test = _read(AUDIT_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Audit events direct duplicate weak-test 清理）"
    )

    assert "Audit events direct duplicate weak-test 清理" in row
    assert (
        "`tests/unit/test_api/test_audit.py::test_audit_events_list_applies_filters_pagination_and_self_audits_summary tests/unit/test_api/test_audit.py::test_audit_events_list_masks_cross_tenant_matches_without_self_audit` 2 passed"
        in row
    )
    assert "audit API full 13 passed" in row
    assert "release quality docs contract full 191 passed" in row
    assert "删除 `tests/unit/test_api/test_audit_events.py`" in row
    assert "更强的 HTTP route 单元契约" in row
    assert "完整分页 body、完整 AuditEventResponse item" in row
    assert "tenant/user/resource 自审计 payload" in row
    assert "跨租户 404 envelope" in row
    assert "只抽查 response total/id/after_state" in row
    assert "覆盖率幻觉" in row
    assert "为数量和覆盖率服务" in row

    assert not AUDIT_EVENTS_DIRECT_TEST.exists()
    assert (
        "**单元测试**：`tests/unit/test_api/test_audit.py`" in t02
    )
    assert "tests/unit/test_api/test_audit_events.py" not in t02

    for expected in [
        "async def test_audit_events_list_applies_filters_pagination_and_self_audits_summary",
        "async def test_audit_events_list_masks_cross_tenant_matches_without_self_audit",
        "assert body == {",
        '"page": 3',
        '"per_page": 2',
        '"total": 7',
        '"action": "project.create"',
        '"resource_type": "project"',
        '"before_state": None',
        "repos.audit.create.assert_awaited_once()",
        "audit_kwargs = repos.audit.create.await_args.kwargs",
        "assert audit_kwargs[\"tenant_id\"] == tenant_id",
        "assert audit_kwargs[\"user_id\"] == user.user_id",
        "assert audit_kwargs[\"resource_id\"] is None",
        'assert "data" not in after_state',
        "assert resp.json() == {",
        "repos.audit.create.assert_not_awaited()",
    ]:
        assert expected in audit_test
