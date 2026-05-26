# T07: F-LS-04 测试结果 suite / 关键字过滤

> **来源**：feature-catalog.md §4.1（F-LS-04）
> **必要性**：P0（未达 PRD §3.7 验收）
> **预计**：XS

## 背景

PRD §3.7 F-LS-04 验收"至少支持按 passed/failed/error/skipped 过滤；**支持 suite 名称过滤**"。当前 `api/v1/runs.py::get_run_results` 只有 `status` 参数；后端 TestResult 状态枚举还包含 `xfail`，本任务只补 suite / q，不改变既有 status 过滤逻辑。

## 实施起点

- **路由**：`src/qaplatform/api/v1/runs.py::get_run_results`
- **仓储**：`src/qaplatform/infra/database/repositories/run_repo.py::TestResultRepository`
- **ORM**：`TestResult` 表（已有 `suite`、`name` 字段）

## API 改动

```
GET /api/v1/runs/{id}/results
  ?status=passed|failed|error|skipped|xfail  # 已有；PRD 最低验收为前四项
  ?suite=<str>                          # NEW: 精确匹配 suite 名
  ?q=<str>                              # NEW: 关键字过滤 name / error_message ILIKE
```

## SQL 实现

```python
# 在仓储 list 方法中：
if suite:
    stmt = stmt.where(TestResult.suite == suite)
if q:
    escaped = _escape_like(q)  # 使用与 projects.py 相同的 LIKE 转义规则
    stmt = stmt.where(
        or_(
            TestResult.name.ilike(f"%{escaped}%", escape="\\"),
            TestResult.error_message.ilike(f"%{escaped}%", escape="\\"),
        )
    )
```

## 验收标准

- [ ] `suite` 参数精确匹配
- [ ] `q` 参数同时匹配 `name` 和 `error_message`，使用 LIKE 转义
- [ ] 多过滤参数可组合（status + suite + q）
- [ ] 跨租户隔离保持（既有 `Run.tenant_id` join 不动）
- [ ] 单元测试：
  - 仅 suite / 仅 q / suite + q 组合 / q 包含 `%` `_` 转义字符 4 种

## 约束

- 保持与 `projects.py` 搜索相同的 LIKE 转义规则。注意当前 `_escape_like` 是 `list_projects()` 内部局部函数，不能直接 import；实现时可提取共享 helper，或在 `runs.py` 放一个同规则的私有 helper，避免跨模块复制业务逻辑时改坏现有项目搜索
- commit：`feat: 测试结果 API 支持 suite 名称与关键字过滤`

## 不要做

- 不要做全文搜索（PG GIN 索引），目前 LIKE 足够
- 不要改 status 过滤逻辑
- 不要顺手分页（已有分页机制）
