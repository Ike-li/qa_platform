from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
PIPELINES_TEST = ROOT / "tests" / "unit" / "test_api" / "test_pipelines.py"
PROJECT_REPOSITORY_CONTRACTS = (
    ROOT / "tests" / "unit" / "test_project_repository_contracts.py"
)
REAL_DB_PERSISTENCE = ROOT / "tests" / "integration" / "test_real_db_persistence.py"
REAL_REPOSITORY_MATRIX = (
    ROOT / "tests" / "integration" / "test_real_repository_matrix.py"
)
RUN_REPOSITORY_CONTRACTS = ROOT / "tests" / "unit" / "test_run_repository_contracts.py"


def test_quality_ops_capture_audit_retention_exact_delete_count_contract():
    row = _quality_ops_row_containing("Audit retention 真实 PG 测试")
    real_repository_matrix = _read(REAL_REPOSITORY_MATRIX)

    assert "Audit retention 真实 PG 测试" in row
    assert "eligible_before 精确为 2" in row
    assert "`delete_older_than()` 返回值等于 eligible_before" in row
    assert "assert eligible_before == 2" in real_repository_matrix
    assert "assert deleted == eligible_before" in real_repository_matrix
    assert "assert deleted >= 2" not in real_repository_matrix
    assert "cutoff = datetime.now(timezone.utc) - timedelta(days=365)" in (
        real_repository_matrix
    )


def test_quality_ops_capture_run_retention_exact_delete_count_contract():
    row = _quality_ops_row_containing("Run retention 真实 PG 测试现在固定 cutoff")
    real_repository_matrix = _read(REAL_REPOSITORY_MATRIX)

    assert "Run retention 真实 PG 测试现在固定 cutoff" in row
    assert "eligible_before" in row
    assert "`delete_terminal_older_than()` 返回值精确等于 eligible_before" in (
        row
    )
    assert "assert eligible_before == len(eligible_run_ids)" in real_repository_matrix
    assert "assert deleted == eligible_before" in real_repository_matrix
    assert "assert deleted >= len(eligible_run_ids)" not in real_repository_matrix


def test_quality_ops_capture_project_repository_exact_tenant_list_contract():
    row = _quality_ops_row_containing("ProjectRepository 真实 PG persistence 用例")
    real_db_persistence = _read(REAL_DB_PERSISTENCE)

    assert "ProjectRepository 真实 PG persistence 用例" in row
    assert "tenant A total=2" in row
    assert "tenant B total=1" in row
    assert "assert total == 2" in real_db_persistence
    assert 'assert ids == {keep.id, seed_run["project"].id}' in real_db_persistence
    assert "assert tenant_b_total == 1" in real_db_persistence
    assert (
        'assert {item.id for item in tenant_b_items} == {seed_second_tenant["project"].id}'
        in real_db_persistence
    )
    assert "assert total >= 2" not in real_db_persistence
    assert "assert tenant_b_total >= 1" not in real_db_persistence


def test_quality_ops_capture_schedule_due_query_exact_result_contract():
    row = _quality_ops_row_containing(
        "Schedule due-query 真实 PG 用例现在断言返回 id 列表精确等于"
    )
    real_repository_matrix = _read(REAL_REPOSITORY_MATRIX)

    assert "Schedule due-query 真实 PG 用例现在断言返回 id 列表精确等于" in (
        row
    )
    assert "避免调度 repository 测试只证明“三个夹具里两个被过滤”" in row
    assert "assert [schedule.id for schedule in due] == [visible_due.id]" in (
        real_repository_matrix
    )
    assert "assert visible_due.id in due_ids" not in real_repository_matrix
    assert "assert deleted_due.id not in due_ids" not in real_repository_matrix
    assert "assert future.id not in due_ids" not in real_repository_matrix


def test_quality_ops_capture_pipeline_list_exact_response_contract():
    ops_row = _quality_ops_row_containing("Pipeline list 精确响应契约")
    pipelines_test = _read(PIPELINES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Pipeline list redundant field-set guard removed）"
    )

    assert "Pipeline list redundant field-set guard removed" in row
    assert (
        "`tests/unit/test_api/test_pipelines.py::test_list_pipelines_returns_paginated_response` 1 passed"
        in row
    )
    assert "release quality docs contract full 335 passed" in row
    assert "完整 `data == {...}` 固定分页 body" in row
    assert "完整 PipelineResponse item" in row
    assert "删除重复的 `assert set(data[\"data\"][0]) == {...}`" in row
    assert "它不能发现完整 body 已发现不了的问题" in row
    assert "pipeline list no redundant field-set guard 契约" in row

    assert "Pipeline list 精确响应契约" in ops_row
    assert "固定完整 PipelineResponse 列表项" in ops_row
    assert "包含 stages/selector/trigger_config/collectors/retry_policy" in ops_row
    assert 'assert data == {' in pipelines_test
    assert '"continue_on_error": False' in pipelines_test
    assert '"trigger_config": {' in pipelines_test
    assert '"updated_at": pipeline.updated_at.isoformat().replace("+00:00", "Z")' in (
        pipelines_test
    )
    assert 'assert set(data["data"][0]) == {' not in pipelines_test
    assert 'data["data"][0]["name"] == "Smoke Pipeline"' not in pipelines_test


def test_quality_ops_capture_artifact_repository_pagination_exact_contract():
    row = _quality_ops_row_containing(
        "ArtifactRepository 真实 PG 用例现在固定软删除 first.log 后 total=2"
    )
    real_repository_matrix = _read(REAL_REPOSITORY_MATRIX)

    assert "ArtifactRepository 真实 PG 用例现在固定软删除 first.log 后 total=2" in (
        row
    )
    assert "按默认 `created_at desc` 返回最新 trace.zip" in row
    assert "assert [item.id for item in artifact_page] == [trace_artifact.id]" in (
        real_repository_matrix
    )
    assert "trace_artifact.created_at = artifact_order_base" in real_repository_matrix
    assert "assert first_artifact.id not in {item.id for item in artifact_page}" not in (
        real_repository_matrix
    )


def test_quality_ops_capture_pipeline_soft_delete_exact_visible_list_contract():
    row = _quality_ops_row_containing("Pipeline API 真实 DB 用例现在断言软删除后")
    real_db_persistence = _read(REAL_DB_PERSISTENCE)

    assert "Pipeline API 真实 DB 用例现在断言软删除后" in row
    assert "返回 total=1 且 visible id 列表只含 seed pipeline" in row
    assert "assert total == 1" in real_db_persistence
    assert 'assert [item.id for item in visible] == [seed_run["pipeline"].id]' in (
        real_db_persistence
    )
    assert "assert pipeline.id not in {item.id for item in visible}" not in (
        real_db_persistence
    )


def test_quality_ops_capture_repository_matrix_exact_total_contracts():
    projection_row = _quality_ops_row_containing(
        "repository matrix direct projection 契约"
    )
    total_row = _quality_ops_row_containing(
        "User repository tenant list 现在固定 total=2"
    )
    real_repository_matrix = _read(REAL_REPOSITORY_MATRIX)

    assert "User repository tenant list 现在固定 total=2" in total_row
    assert "Run repository project/pipeline list" in total_row
    assert "total=1 且返回 seed run id 精确列表" in total_row
    assert "repository matrix direct projection 契约" in projection_row
    assert "不再用 `len(users) == 1` / `len(project_runs) == 1`" in (
        projection_row
    )
    assert "完整 id/tenant/username/email 与 run scope 投影" in projection_row
    assert "assert total == 2" in real_repository_matrix
    assert '"username": shared_username' in real_repository_matrix
    assert '"email": email_a' in real_repository_matrix
    assert "assert project_total == 1" in real_repository_matrix
    assert '"project_id": item.project_id' in real_repository_matrix
    assert '"pipeline_id": item.pipeline_id' in real_repository_matrix
    assert "assert pipeline_total == 1" in real_repository_matrix
    assert "assert [item.id for item in pipeline_runs] == [run.id]" in (
        real_repository_matrix
    )
    assert "assert len(users) == 1" not in real_repository_matrix
    assert "assert len(project_runs) == 1" not in real_repository_matrix
    assert "project_runs[0]" not in real_repository_matrix
    assert "assert total >= 2" not in real_repository_matrix
    assert "assert project_total >= 1" not in real_repository_matrix
    assert "assert pipeline_total >= 1" not in real_repository_matrix


def test_quality_ops_capture_pipeline_missing_project_error_response_contract():
    row = _quality_ops_row_containing(
        "Pipeline missing project ErrorResponse 精确契约"
    )
    pipelines_test = _read(PIPELINES_TEST)

    assert "Pipeline missing project ErrorResponse 精确契约" in row
    assert "五个响应体完整等于标准 `NOT_FOUND` ErrorResponse" in row
    assert "只查 project tenant scope" in row
    assert "仍兼容 `detail` 或 `error.message` 两种形状" in row
    assert "FastAPI 默认 detail" in row
    assert "Project not found 文案出现过" in row
    assert "assert bodies == [" in pipelines_test
    assert '"code": "NOT_FOUND"' in pipelines_test
    assert '"message": "Project not found"' in pipelines_test
    assert '"details": []' in pipelines_test
    assert "assert all(body == bodies[0] for body in bodies)" not in (
        pipelines_test
    )
    assert "bodies[0].get(\"detail\")" not in pipelines_test


def test_quality_ops_capture_pipeline_nested_payload_exact_persistence_contract():
    pipelines_test = _read(PIPELINES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Pipeline nested payload exact persistence 契约）"
    )

    assert "Pipeline nested payload exact persistence 契约" in row
    assert (
        "`tests/unit/test_api/test_pipelines.py::test_create_pipeline_persists_nested_payload_and_writes_audit "
        "tests/unit/test_api/test_pipelines.py::test_update_pipeline_translates_partial_nested_updates` 2 passed"
        in row
    )
    assert "pipeline full 28 passed" in row
    assert "release quality docs contract full 205 passed" in row
    assert "repository create/update 的完整 kwargs" in row
    assert "stages/selector/trigger_config/collectors/retry_policy/enabled 默认壳" in row
    assert "raw credentialed clone URL" in row
    assert "审计 after_state 继续脱敏 userinfo/token" in row
    assert '只用 `endswith("@git.example/repo.git")`' in row
    assert "持久化 trigger_config 提前脱敏" in row
    assert "漏掉 selector/trigger 默认字段" in row
    assert "只证明“几个字段和脱敏片段看起来对”" in row

    create_block = _marked_block(
        pipelines_test,
        "async def test_create_pipeline_persists_nested_payload_and_writes_audit",
        "@pytest.mark.parametrize",
    )
    update_block = _marked_block(
        pipelines_test,
        "async def test_update_pipeline_translates_partial_nested_updates",
        "async def test_delete_pipeline_removes_existing_pipeline_and_audits",
    )

    for block in (create_block, update_block):
        assert (
            'raw_clone_url = f"https://x-access-token:{raw_token}@git.example/repo.git"'
            in block
        )
        assert '"continue_on_error": False' in block
        assert '"dedup_window_seconds": None' in block
        assert '"conditions": {}' in block
        assert '"target": {}' in block
        assert 'body["stages"] == expected_stages' in block
        assert 'body["selector"] == expected_selector' in block
        assert 'body["trigger_config"] == expected_trigger_config' in block
        assert 'body["collectors"] == expected_collectors' in block
        assert ".endswith(" not in block

    for expected in [
        "mock_repos.pipeline.create.assert_awaited_once_with(",
        "project_id=project_id,",
        'name="Smoke Pipeline",',
        "stages=expected_stages,",
        "selector=expected_selector,",
        "trigger_config=expected_trigger_config,",
        "collectors=expected_collectors,",
        "timeout_seconds=600,",
        "retry_policy=expected_retry_policy,",
        "enabled=True,",
        '"include_paths": ["tests/unit"]',
        '"exclude_paths": []',
        '"on_empty": "warn"',
        '"retry_on": ["infra"]',
        '"backoff_seconds": 0',
        'body["retry_policy"] == expected_retry_policy',
    ]:
        assert expected in create_block
    assert "create_kwargs = mock_repos.pipeline.create.await_args.kwargs" not in (
        create_block
    )

    for expected in [
        "mock_repos.pipeline.update.assert_awaited_once_with(",
        "pipeline,",
        'name="Updated",',
        "stages=expected_stages,",
        "selector=expected_selector,",
        "trigger_config=expected_trigger_config,",
        "collectors=expected_collectors,",
        "retry_policy=None,",
        "enabled=False,",
        '"include_paths": []',
        '"exclude_paths": ["tests/e2e"]',
        '"on_empty": "fail"',
        'body["retry_policy"] is None',
    ]:
        assert expected in update_block
    assert "update_kwargs = mock_repos.pipeline.update.await_args.kwargs" not in (
        update_block
    )


def test_quality_ops_capture_pipeline_core_schema_validation_detail_exact_contract():
    row = _quality_ops_row_containing(
        "Pipeline core schema validation detail 精确契约"
    )
    pipelines_test = _read(PIPELINES_TEST)

    assert "Pipeline core schema validation detail 精确契约" in row
    assert (
        "`tests/unit/test_api/test_pipelines.py::test_pipeline_routes_reject_invalid_schema_before_side_effects` 8 passed"
        in row
    )
    assert "为非 name 字段补合法 name" in row
    assert "避免 create 只靠缺少 name 失败" in row
    assert "固定 `_validation_detail_lines(response) == [expected_detail]`" in (
        row
    )
    assert "覆盖 name、timeout_seconds、stage name/plugin、collector plugin" in (
        row
    )
    assert "`expected_text in create_resp.text/update_resp.text`" in row
    assert "`body -> name: Field required`" in row
    assert "目标字段校验丢失、detail 数量变多、loc/type 文案漂移" in row
    assert "只证明“某段错误文本出现过”" in row

    schema_section = _marked_block(
        pipelines_test,
        '@pytest.mark.parametrize(\n    ("payload", "expected_detail")',
        '@pytest.mark.parametrize(\n    ("selector", "expected_detail")'
    )

    assert '("payload", "expected_text")' not in schema_section
    assert "expected_text in create_resp.text" not in schema_section
    assert "expected_text in update_resp.text" not in schema_section
    assert "assert _validation_detail_lines(response) == [expected_detail]" in (
        schema_section
    )
    assert '"name": "Invalid Schema Pipeline"' in schema_section
    assert (
        "body -> timeout_seconds: Input should be greater than or equal to 1"
        in schema_section
    )
    assert (
        "body -> stages -> 0 -> plugin: Value error, pipeline stage plugin must not be blank"
        in schema_section
    )
    assert (
        "body -> collectors -> 0 -> plugin: Value error, pipeline collector plugin must not be blank"
        in schema_section
    )


def test_quality_ops_capture_pipeline_nested_validation_detail_exact_contract():
    row = _quality_ops_row_containing(
        "Pipeline selector/retry/trigger_config validation detail 精确契约"
    )
    pipelines_test = _read(PIPELINES_TEST)

    assert (
        "Pipeline selector/retry/trigger_config validation detail 精确契约"
        in row
    )
    assert (
        "`tests/unit/test_api/test_pipelines.py::test_pipeline_routes_reject_invalid_selector_before_side_effects tests/unit/test_api/test_pipelines.py::test_pipeline_routes_reject_invalid_retry_policy_before_side_effects tests/unit/test_api/test_pipelines.py::test_pipeline_routes_reject_invalid_trigger_config_before_side_effects` 13 passed"
        in row
    )
    assert "固定 `_validation_detail_lines(response) == [expected_detail]`" in (
        row
    )
    assert (
        "pipeline selector include/exclude/tags、retry_policy retry_on、trigger_config type/dedup_window_seconds"
        in row
    )
    assert "列表上限错误的完整数量文案 `after validation, not 101/21`" in (
        row
    )
    assert '`expected_detail in " | ".join(...)`' in row
    assert "响应夹带额外 validation detail" in row
    assert "只证明“某段错误文本出现在某处”" in row

    selector_block = _marked_block(
        pipelines_test,
        "async def test_pipeline_routes_reject_invalid_selector_before_side_effects",
        '@pytest.mark.parametrize(\n    ("retry_policy", "expected_detail")'
    )
    retry_block = _marked_block(
        pipelines_test,
        "async def test_pipeline_routes_reject_invalid_retry_policy_before_side_effects",
        '@pytest.mark.parametrize(\n    ("trigger_config", "expected_detail")'
    )
    trigger_block = _marked_block(
        pipelines_test,
        "async def test_pipeline_routes_reject_invalid_trigger_config_before_side_effects",
        "async def test_get_pipeline_returns_404_for_missing_or_other_project"
    )

    assert "assert _validation_detail_lines(response) == [expected_detail]" in (
        selector_block
    )
    assert "assert _validation_detail_lines(response) == [expected_detail]" in (
        retry_block
    )
    assert "assert _validation_detail_lines(response) == [expected_detail]" in (
        trigger_block
    )
    assert 'expected_detail in " | ".join' not in selector_block
    assert 'expected_detail in " | ".join' not in retry_block
    assert 'expected_detail in " | ".join' not in trigger_block
    assert (
        "body -> selector -> include_paths: List should have at most 100 items after validation, not 101"
        in pipelines_test
    )
    assert (
        "body -> retry_policy -> retry_on: List should have at most 20 items after validation, not 21"
        in pipelines_test
    )


def test_quality_ops_capture_run_repository_scheduler_sql_column_bound_params_contract():
    run_repository_contracts = _read(RUN_REPOSITORY_CONTRACTS)
    row = _quality_ops_row(
        "| 2026-06-01 | N/A（RunRepository scheduler SQL column-bound params 契约）"
    )

    assert "RunRepository scheduler SQL column-bound params 契约" in row
    assert "`tests/unit/test_run_repository_contracts.py` 4 passed" in row
    assert "release quality docs contract full 347 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "从 rendered SQL 逐列提取" in row
    assert "`run.status =`" in row
    assert "`run.status IN`" in row
    assert "`run.project_id =`" in row
    assert "`LIMIT`" in row
    assert "params 只能包含这些列级绑定" in row
    assert "active status IN 保留无序集合语义但同时固定长度为 3" in row
    assert "`RunStatusEnum.QUEUED in params.values()`" in row
    assert "直接读 `status_1/status_2/project_id_1/param_1`" in row
    assert "status 绑定到错误表达式" in row
    assert "project 过滤列漂移" in row
    assert "limit 参数夹带" in row
    assert "参数值集合看起来对" in row

    for expected in [
        "import re",
        "def _bound_param_name(sql: str, expression: str) -> str:",
        "def _postcompile_param_name(sql: str, expression: str) -> str:",
        "def _assert_active_status_params(",
        'status_param = _bound_param_name(sql, "run.status =")',
        'limit_param = _bound_param_name(sql, "LIMIT")',
        "assert params == {",
        "_assert_active_status_params(sql=sql, params=params)",
        'project_param = _bound_param_name(sql, "run.project_id =")',
        "expected_extra_params={project_param: project_id}",
        "assert len(params[active_status_param]) == 3",
        "assert params[queued_status_param] == RunStatusEnum.QUEUED",
        "assert params == {status_param: RunStatusEnum.QUEUED}",
    ]:
        assert expected in run_repository_contracts
    assert "RunStatusEnum.QUEUED in params.values()" not in (
        run_repository_contracts
    )
    assert 'params["project_id_1"]' not in run_repository_contracts
    assert 'params["param_1"]' not in run_repository_contracts


def test_quality_ops_capture_schedule_repository_due_sql_column_bound_params_contract():
    project_repository_contracts = _read(PROJECT_REPOSITORY_CONTRACTS)
    row = _quality_ops_row(
        "| 2026-06-01 | N/A（ScheduleRepository due SQL column-bound params 契约）"
    )

    assert "ScheduleRepository due SQL column-bound params 契约" in row
    assert (
        "`tests/unit/test_project_repository_contracts.py::test_find_due_schedules_uses_skip_locked_schedule_row_lock` 1 passed"
        in row
    )
    assert "project repository contracts full 1 passed" in row
    assert "release quality docs contract full 350 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "从 rendered SQL 逐列提取" in row
    assert "`schedule.next_run_at <=`" in row
    assert "`LIMIT`" in row
    assert "params 只能包含 due_at 与 limit 两个绑定" in row
    assert "`now in params.values()`" in row
    assert '`params["param_1"]`' in row
    assert "now` 绑定到错误表达式" in row
    assert "limit 参数名变化" in row
    assert "查询夹带额外参数" in row
    assert "参数值集合看起来对" in row

    for expected in [
        "import re",
        "def _bound_param_name(sql: str, expression: str) -> str:",
        'due_at_param = _bound_param_name(sql, "schedule.next_run_at <=")',
        'limit_param = _bound_param_name(sql, "LIMIT")',
        "assert params == {",
        "due_at_param: now",
        "limit_param: 23",
    ]:
        assert expected in project_repository_contracts
    assert "now in params.values()" not in project_repository_contracts
    assert 'params["param_1"]' not in project_repository_contracts
