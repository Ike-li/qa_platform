from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)

ROOT = Path(__file__).resolve().parents[2]
ADMIN_TEST = ROOT / "tests" / "unit" / "test_api" / "test_admin.py"
DEPENDENCIES_TEST = ROOT / "tests" / "unit" / "test_dependencies.py"
HEALTH_TEST = ROOT / "tests" / "unit" / "test_api" / "test_health.py"
PROJECTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_projects.py"
RUNS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_runs.py"


def test_quality_ops_records_current_gate_data_runtime_evidence():
    health_test = _read(HEALTH_TEST)
    projects_test = _read(PROJECTS_TEST)
    runs_test = _read(RUNS_TEST)
    admin_test = _read(ADMIN_TEST)
    dependencies_test = _read(DEPENDENCIES_TEST)
    admin_status_terminal_denominator_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Admin status terminal denominator 契约）"
    )
    admin_status_zero_run_query_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Admin status zero-run query 精确契约）"
    )
    ready_health_probe_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Ready health probe SQL/response 精确契约）"
    )
    project_list_filter_sql_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project list filters SQL 精确契约）"
    )
    run_list_filter_sql_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run list filters SQL 精确契约）"
    )
    run_results_filter_sql_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Run results filters SQL 精确契约）"
    )
    dependency_session_exception_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（Dependency session exception 精确契约）"
    )
    analytics_success_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Analytics 查询成功路径仓储/RBAC 契约）"
    )
    dependency_transaction_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Dependency transaction boundary 契约）"
    )
    run_repository_scheduler_lock_row = _quality_ops_row(
        "| 2026-05-30 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_real_repository_matrix.py::test_run_repository_find_waiting_orders_by_priority_then_fifo`"
    )
    schedule_repository_due_lock_row = _quality_ops_row(
        "| 2026-05-30 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_real_repository_matrix.py::test_schedule_repository_due_query_ignores_soft_deleted_schedules`"
    )
    assert (
        "`tests/unit/test_api/test_health.py` 6 passed" in ready_health_probe_exact_row
    )
    assert "完整响应壳" in ready_health_probe_exact_row
    assert "DB probe SQL `SELECT 1`" in ready_health_probe_exact_row
    assert "多用 `len(container.session.statements) == 1`" in (
        ready_health_probe_exact_row
    )
    assert "只证明“探测被调用过”" in ready_health_probe_exact_row
    assert '"checks": {"db": "ok", "redis": "ok"}' in health_test
    assert (
        "assert [str(statement) for statement in container.session.statements] == ["
        in (health_test)
    )
    assert '"SELECT 1"' in health_test
    assert "assert len(container.session.statements) == 1" not in health_test
    assert (
        "`tests/unit/test_api/test_projects.py::test_list_projects tests/unit/test_api/test_projects.py::test_list_projects_with_search tests/unit/test_api/test_projects.py::test_list_projects_filters_by_status` 3 passed"
        in (project_list_filter_sql_exact_row)
    )
    assert "tenant filter" in project_list_filter_sql_exact_row
    assert "search `name/description ILIKE` filter" in project_list_filter_sql_exact_row
    assert "只用 `len(filters) == 1/2`" in project_list_filter_sql_exact_row
    assert "拆开 `tenant_filter.left/right`" in project_list_filter_sql_exact_row
    assert "某个过滤片段存在" in project_list_filter_sql_exact_row
    assert "def _render_filters(filters) -> list[str]:" in projects_test
    assert 'assert _render_filters(list_kwargs["filters"]) == [' in projects_test
    assert "f\"project.tenant_id = '{tenant_id.hex}'\"" in projects_test
    assert "lower(project.name) LIKE lower('%keyword%')" in projects_test
    assert "\"project.status = 'archived'\"" in projects_test
    assert 'assert len(list_kwargs["filters"]) == 1' not in projects_test
    assert 'assert len(list_kwargs["filters"]) == 2' not in projects_test
    assert 'getattr(tenant_filter.left, "name", None)' not in projects_test
    assert "assert any(\"project.status = 'archived'\" in r for r in rendered)" not in (
        projects_test
    )
    assert (
        "`tests/unit/test_api/test_runs.py::test_list_runs tests/unit/test_api/test_runs.py::test_list_runs_member_user_uses_project_member_repository tests/unit/test_api/test_runs.py::test_list_runs_multi_status_filter tests/unit/test_api/test_runs.py::test_list_runs_single_status_uses_equality` 4 passed"
        in (run_list_filter_sql_exact_row)
    )
    assert "tenant、project_id IN、status equality / IN" in (
        run_list_filter_sql_exact_row
    )
    assert '`getattr(expr.left, "name", None)`' in run_list_filter_sql_exact_row
    assert '`any("project_id IN" ...)`' in run_list_filter_sql_exact_row
    assert 'not any("IN" ...)' in run_list_filter_sql_exact_row
    assert "只证明“目标片段出现过”" in run_list_filter_sql_exact_row
    assert "run.tenant_id = '{tenant_id.hex}'" in runs_test
    assert "run.status = 'queued'" in runs_test
    assert "run.status IN ('queued', 'running')" in runs_test
    assert "run.project_id IN ('{project_id.hex}')" in runs_test
    assert 'getattr(expr.left, "name", None)' not in runs_test
    assert (
        'assert any("project_id IN" in r and project_id.hex in r for r in rendered)'
        not in runs_test
    )
    assert "expected IN-clause with both statuses" not in runs_test
    assert "assert any(\"= 'queued'\" in r for r in rendered)" not in runs_test
    assert (
        "`tests/unit/test_api/test_runs.py::test_get_run_results_filters_by_suite tests/unit/test_api/test_runs.py::test_get_run_results_filters_by_keyword tests/unit/test_api/test_runs.py::test_get_run_results_combines_suite_and_keyword tests/unit/test_api/test_runs.py::test_get_run_results_escapes_keyword_like_wildcards` 4 passed"
        in (run_results_filter_sql_exact_row)
    )
    assert "固定完整 filter 序列" in run_results_filter_sql_exact_row
    assert "name/error_message ILIKE" in run_results_filter_sql_exact_row
    assert "只用 `any(\"suite = 'checkout'\")`" in run_results_filter_sql_exact_row
    assert "某个片段出现过" in run_results_filter_sql_exact_row
    assert "def _render_filters(filters) -> list[str]:" in runs_test
    assert "assert _render_filters(filters) == [" in runs_test
    assert "test_result.run_id" in runs_test
    assert "lower(test_result.error_message) LIKE lower('%timeout%')" in runs_test
    assert r"lower(test_result.error_message) LIKE lower('%case\\%\\_\\\\%')" in (
        runs_test
    )
    assert "assert any(\"suite = 'checkout'\" in r for r in rendered)" not in runs_test
    assert "assert any(\"status = 'failed'\" in r for r in rendered)" not in runs_test
    assert "`tests/unit/test_api/test_admin.py` 4 passed" in (
        admin_status_terminal_denominator_row
    )
    assert "coverage unit 1280 passed" in admin_status_terminal_denominator_row
    assert "`success_rate_1h`" in admin_status_terminal_denominator_row
    assert "`done/failed/cancelled/timeout` 作为终态分母" in (
        admin_status_terminal_denominator_row
    )
    assert "只把 `done` 计入成功" in admin_status_terminal_denominator_row
    assert "12 个终态、8 个成功时返回 `0.6667`" in (
        admin_status_terminal_denominator_row
    )
    assert "旧 admin/status 用例把 total query 锁成 `done/failed`" in (
        admin_status_terminal_denominator_row
    )
    assert "取消和超时运行不进失败率" in admin_status_terminal_denominator_row
    assert "避免状态页测试只证明四个数字有形状" in (
        admin_status_terminal_denominator_row
    )
    assert "`tests/unit/test_api/test_admin.py` 4 passed" in (
        admin_status_zero_run_query_row
    )
    assert "正常与 zero-run 分支现在共用查询契约" in (admin_status_zero_run_query_row)
    assert "queue depth 查询 `queued/preparing`" in (admin_status_zero_run_query_row)
    assert "1h 分母查询 `done/failed/cancelled/timeout`" in (
        admin_status_zero_run_query_row
    )
    assert "同一个 timezone-aware `since` 对象" in (admin_status_zero_run_query_row)
    assert "await 次数" in admin_status_zero_run_query_row
    assert "只要返回 `success_rate_1h == 1.0` 旧测试仍可能绿" in (
        admin_status_zero_run_query_row
    )
    assert "没有运行时显示 100%" in admin_status_zero_run_query_row
    assert "def _assert_status_query_contract(repos):" in admin_test
    assert "] == [_QUEUE_STATUSES, _IN_FLIGHT_STATUSES]" in admin_test
    assert 'terminal_call.kwargs["statuses"] == _TERMINAL_STATUSES' in (admin_test)
    assert 'passed_call.kwargs["statuses"] == _PASSED_STATUSES' in admin_test
    assert 'terminal_call.kwargs["since"] is passed_call.kwargs["since"]' in (
        admin_test
    )
    assert "assert repos.run.count_by_statuses.await_count == 2" not in (admin_test)
    assert (
        "assert repos.run.count_finished_since_by_statuses.await_count == 2"
        not in admin_test
    )
    assert "`tests/unit/test_api/test_analytics.py` 6 passed" in (analytics_success_row)
    assert "coverage unit 1244 passed" in analytics_success_row
    assert "trends/flaky/test-history 成功路径" in analytics_success_row
    assert "project tenant lookup" in analytics_success_row
    assert "`RUN_READ` RBAC" in analytics_success_row
    assert "days/min_runs/suite/name/offset/limit/cutoff 仓储参数" in (
        analytics_success_row
    )
    assert "响应映射" in analytics_success_row
    assert "不能发现 trends/flaky/test-history 成功路径漏掉项目租户校验" in (
        analytics_success_row
    )
    assert "分页/过滤参数传错或汇总字段映射漂移" in analytics_success_row
    assert "`tests/unit/test_dependencies.py` 8 passed" in dependency_transaction_row
    assert "coverage unit 1263 passed" in dependency_transaction_row
    assert "global/request DB session 成功后 commit" in dependency_transaction_row
    assert "异常 rollback+reraise" in dependency_transaction_row
    assert "`_get_repos` 使用 request container/session" in dependency_transaction_row
    assert "`get_session_factory` 缺 DB 返回 503" in dependency_transaction_row
    assert "`qaplatform.api.deps` 覆盖率从 85% 提升到 90%" in (
        dependency_transaction_row
    )
    assert "`qaplatform.dependencies` 从 38% 提升到 54%" in (dependency_transaction_row)
    assert "route 单测 override `_get_db_session`" in dependency_transaction_row
    assert "真实依赖层不 commit/rollback" in dependency_transaction_row
    assert "repository bundle 绕过 request session" in dependency_transaction_row
    assert "8 条依赖边界契约" in dependency_transaction_row
    assert "`tests/unit/test_dependencies.py` 12 passed" in (
        dependency_session_exception_exact_row
    )
    assert "rollback 后透传同一个 RuntimeError 对象" in (
        dependency_session_exception_exact_row
    )
    assert "未初始化 database 固定 exact args" in (
        dependency_session_exception_exact_row
    )
    assert "`pytest.raises(..., match=...)`" in (dependency_session_exception_exact_row)
    assert "重新包装异常" in dependency_session_exception_exact_row
    assert "相似错误文本" in dependency_session_exception_exact_row
    assert "assert exc_info.value is error" in dependencies_test
    assert 'assert exc_info.value.args == ("Database not initialised",)' in (
        dependencies_test
    )
    assert 'with pytest.raises(RuntimeError, match="write failed")' not in (
        dependencies_test
    )
    assert 'with pytest.raises(RuntimeError, match="route failed")' not in (
        dependencies_test
    )
    assert (
        'with pytest.raises(RuntimeError, match="Database not initialised")'
        not in dependencies_test
    )
    assert (
        "test_run_repository_find_waiting_orders_by_priority_then_fifo` 1 passed"
        in (run_repository_scheduler_lock_row)
    )
    assert (
        "`tests/unit/test_run_repository_contracts.py tests/unit/test_worker/test_scheduler.py` 18 passed"
        in (run_repository_scheduler_lock_row)
    )
    assert "coverage unit 1267 passed" in run_repository_scheduler_lock_row
    assert "`RunRepository.find_waiting()`" in run_repository_scheduler_lock_row
    assert "`FOR UPDATE OF run SKIP LOCKED`" in run_repository_scheduler_lock_row
    assert "global/project active-or-enqueued 统计" in (
        run_repository_scheduler_lock_row
    )
    assert "waiting 计数" in run_repository_scheduler_lock_row
    assert (
        "`qaplatform.infra.database.repositories.run_repo` 覆盖率从 28% 提升到 34%"
        in (run_repository_scheduler_lock_row)
    )
    assert "`FairScheduler.try_dequeue_waiting()` 文档要求" in (
        run_repository_scheduler_lock_row
    )
    assert "现有 scheduler 单测全 mock repo" in run_repository_scheduler_lock_row
    assert "实际没锁行" in run_repository_scheduler_lock_row
    assert "ORM eager left join 上裸 `FOR UPDATE` 会失败" in (
        run_repository_scheduler_lock_row
    )
    assert "只锁 `run` 主表" in run_repository_scheduler_lock_row
    assert (
        "test_schedule_repository_due_query_ignores_soft_deleted_schedules` 1 passed"
        in (schedule_repository_due_lock_row)
    )
    assert (
        "`tests/unit/test_project_repository_contracts.py tests/unit/test_worker/test_check_schedules.py` 10 passed"
        in (schedule_repository_due_lock_row)
    )
    assert "coverage unit 1268 passed" in schedule_repository_due_lock_row
    assert "`ScheduleRepository.find_due_schedules()`" in (
        schedule_repository_due_lock_row
    )
    assert "`FOR UPDATE OF schedule SKIP LOCKED`" in schedule_repository_due_lock_row
    assert "enabled、非软删除、due time" in schedule_repository_due_lock_row
    assert "`next_run_at` 排序和 limit" in schedule_repository_due_lock_row
    assert (
        "`qaplatform.infra.database.repositories.project_repo` 覆盖率从 51% 提升到 54%"
        in (schedule_repository_due_lock_row)
    )
    assert "schedule worker 单测主要 mock repository" in (
        schedule_repository_due_lock_row
    )
    assert "真实 PG 用例只证明软删除过滤" in schedule_repository_due_lock_row
    assert "只锁 `schedule` 主表" in schedule_repository_due_lock_row
