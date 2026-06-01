# T07: F-LS-04 测试结果 suite / 关键字过滤

> **来源**：feature-catalog.md §4.1（F-LS-04）
> **必要性**：P0 / 已完成
> **状态**：已完成于 `main`；本文件保留为验收档案
> **预计**：XS

## 背景

PRD §3.7 F-LS-04 验收要求"至少支持按 passed/failed/error/skipped 过滤；支持 suite 名称过滤"。当前 `main` 已完成 T07 范围：`GET /api/v1/runs/{run_id}/results` 支持 `status`、`suite`、`q` 组合过滤；`q` 会同时匹配用例名称和错误信息，并使用 LIKE 转义，避免 `%` / `_` 被当作通配符扩大结果集。

## 实施位置

- **路由**：`src/qaplatform/api/v1/runs.py::get_run_results`
- **过滤 helper**：`src/qaplatform/api/v1/_filters.py::escape_like`
- **仓储**：`src/qaplatform/infra/database/repositories/run_repo.py::TestResultRepository`
- **ORM**：`TestResult` 表已有 `suite`、`name`、`error_message`、`status` 字段

## 当前 API

```
GET /api/v1/runs/{run_id}/results
  ?status=passed|failed|error|skipped|xfail
  ?suite=<str>
  ?q=<str>
```

行为约束：

- `suite` 为精确匹配
- `q` 同时匹配 `TestResult.name` 与 `TestResult.error_message`
- `q` 使用 `escape_like` 后再构造 ILIKE，避免 `%`、`_`、`\` 改变搜索语义
- `status + suite + q` 可组合
- Run 仍先通过 `repos.run.get_for_tenant(run_id, user.tenant_id)` 收敛租户边界，再执行项目级 `RUN_READ`

## 验收标准

- [x] `suite` 参数精确匹配
- [x] `q` 参数同时匹配 `name` 和 `error_message`，使用 LIKE 转义
- [x] 多过滤参数可组合（status + suite + q）
- [x] 跨租户隔离保持（既有 `Run.tenant_id` lookup 不动）
- [x] 单元测试覆盖仅 suite / 仅 q / suite + q 组合 / q 包含 `%` `_` `\` 转义字符
- [x] 集成测试覆盖真实 DB 行过滤，以及 duplicate rollback 后查询恢复

## 自动化证据

- `tests/unit/test_api/test_runs.py::test_get_run_results_status_filter_is_openapi_enum`
- `tests/unit/test_api/test_runs.py::test_get_run_results_filters_by_suite`
- `tests/unit/test_api/test_runs.py::test_get_run_results_filters_by_keyword`
- `tests/unit/test_api/test_runs.py::test_get_run_results_combines_suite_and_keyword`
- `tests/unit/test_api/test_runs.py::test_get_run_results_escapes_keyword_like_wildcards`
- `tests/integration/test_real_auth_results_artifacts.py::test_run_results_api_filters_real_rows_and_recovers_after_duplicate`
- `tests/integration/test_cross_tenant_isolation.py::test_run_results_cross_tenant_returns_same_404`

## 不要做

- 不要做全文搜索（PG GIN 索引）；当前 LIKE 满足验收
- 不要改 status 过滤语义
- 不要把本任务扩成分页重构；结果接口已有分页机制
