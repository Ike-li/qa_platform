from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_API_CONTRACT = ROOT / "tests" / "unit" / "test_frontend_api_contract.py"
FRONTEND_TYPES = ROOT / "frontend" / "src" / "types" / "api.ts"
RUN_DETAIL_PAGE = ROOT / "frontend" / "src" / "pages" / "runs" / "detail.tsx"
RUN_HOOK = ROOT / "frontend" / "src" / "hooks" / "use-runs.ts"


def test_quality_ops_capture_frontend_openapi_exact_field_contract():
    row = _quality_ops_row_containing("Frontend/OpenAPI 字段集合精确契约")
    frontend_contract = _read(FRONTEND_API_CONTRACT)

    assert "Frontend/OpenAPI 字段集合精确契约" in row
    assert "字段集合现在必须精确等于 OpenAPI schema" in row
    assert "create payload 的可选字段也会做类型/nullability 校验" in (
        row
    )
    assert "assert frontend_fields == backend_fields" in frontend_contract
    assert "assert set(frontend_members) == set(backend_properties)" in (
        frontend_contract
    )
    assert "assert backend_fields <= frontend_fields" not in frontend_contract
    assert "assert backend_required <= set(frontend_members)" not in (
        frontend_contract
    )


def test_quality_ops_capture_trigger_run_payload_exact_field_contract():
    row = _quality_ops_row_containing("TriggerRun payload 精确字段契约")
    frontend_contract = _read(FRONTEND_API_CONTRACT)

    assert "TriggerRun payload 精确字段契约" in row
    assert "TriggerRunPayload 现在固定只包含" in row
    assert "branch 映射到后端 `git_ref`" in row
    assert "assert payload_fields == {" in frontend_contract
    assert '"pipeline_id",' in frontend_contract
    assert '"branch",' in frontend_contract
    assert '"git_sha",' in frontend_contract
    assert '"environment_id",' in frontend_contract
    assert '"priority",' in frontend_contract
    assert (
        'assert {"pipeline_id", "branch", "git_sha", "environment_id", '
        '"priority"} <= payload_fields'
    ) not in frontend_contract


def test_quality_ops_capture_notification_rule_create_required_exact_contract():
    row = _quality_ops_row_containing("NotificationRuleCreate required 精确契约")
    frontend_contract = _read(FRONTEND_API_CONTRACT)

    assert "NotificationRuleCreate required 精确契约" in row
    assert "后端 required 现在必须精确等于 name/channels" in row
    assert "误把 enabled、conditions 或 template 改成必填" in row
    assert 'assert backend_required == {"name", "channels"}' in frontend_contract
    assert 'assert {"name", "channels"} <= backend_required' not in frontend_contract


def test_quality_ops_capture_frontend_run_terminal_polling_archive_contract():
    frontend_contract = _read(FRONTEND_API_CONTRACT)
    frontend_types = _read(FRONTEND_TYPES)
    run_hook = _read(RUN_HOOK)
    detail_page = _read(RUN_DETAIL_PAGE)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Frontend run terminal polling/archive 契约）"
    )

    assert "Frontend run terminal polling/archive 契约" in row
    assert "`tests/unit/test_frontend_api_contract.py` 35 passed" in row
    assert "frontend build passed" in row
    assert "release quality docs contract full 211 passed" in row
    assert "targeted ruff passed" in row
    assert "`is_terminal`" in row
    assert "`done/failed/cancelled/timeout`" in row
    assert "run detail 轮询和 archived logs 开关使用该字段" in row
    assert "不再用 UI `status` 判断" in row
    assert "后端 `done + total=0` 会被前端显示为 `Unknown`" in row
    assert "持续 5s 轮询且不启用 archived logs" in row
    assert "展示状态与后端终态分离" in row
    assert "只证明列表行显示 Unknown" in row

    for expected in [
        "is_terminal: boolean",
    ]:
        assert expected in frontend_types

    for expected in [
        "BACKEND_TERMINAL_RUN_STATUSES: readonly BackendRunStatus[]",
        '"done"',
        '"failed"',
        '"cancelled"',
        '"timeout"',
        "is_terminal: BACKEND_TERMINAL_RUN_STATUSES.includes(run.status)",
        "return query.state.data?.is_terminal ? false : 5000;",
    ]:
        assert expected in run_hook
    assert "const TERMINAL_RUN_STATUSES" not in run_hook
    assert "const archivedLogsEnabled = run.is_terminal;" in detail_page
    assert "const terminalRunStatuses" not in detail_page

    assert (
        "def test_run_hooks_use_backend_terminal_status_for_polling_and_archived_logs"
        in frontend_contract
    )


def test_quality_ops_capture_frontend_create_payload_optionality_exact_contract():
    frontend_contract = _read(FRONTEND_API_CONTRACT)
    frontend_types = _read(FRONTEND_TYPES)
    row = _quality_ops_row(
        "| 2026-06-01 | N/A（Frontend create payload optionality exact contract）"
    )

    assert "Frontend create payload optionality exact contract" in row
    assert (
        "`tests/unit/test_frontend_api_contract.py::test_frontend_create_payloads_keep_backend_required_fields` 4 passed"
        in row
    )
    assert "frontend build passed" in row
    assert "release quality docs contract full 348 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "后端 required 字段必须是 TS 非可选" in row
    assert "后端 non-required 字段必须是 TS 可选" in row
    assert "`ProjectCreatePayload.git_auth_method/default_branch/root_path`" in row
    assert "创建表单仍保留自己的默认值" in row
    assert "required 只检查必填字段非可选" in row
    assert "后端可选字段不能被前端误建为必填" in row
    assert "`git_auth_method/default_branch/root_path` 这类有后端默认值" in row
    assert "字段名和类型大概一致" in row

    for expected in [
        'assert frontend_members[field_name]["optional"] is True, field_name',
        'assert frontend_members[field_name]["optional"] is False, field_name',
    ]:
        assert expected in frontend_contract

    payload_block = _marked_block(
        frontend_types,
        "export interface ProjectCreatePayload",
        "\n}",
    )
    for expected in [
        "git_auth_method?: GitAuthMethod;",
        "default_branch?: string;",
        "root_path?: string;",
    ]:
        assert expected in payload_block
    assert "git_auth_method: GitAuthMethod;" not in payload_block
    assert "default_branch: string;" not in payload_block
    assert "root_path: string;" not in payload_block
