# T07: F-LS-04 测试结果 suite / 关键字过滤

> **来源**：feature-catalog.md §4.1 #7
> **必要性**：P0（未达 PRD §3.7 验收）
> **预计**：XS

## 背景

PRD §3.7 F-LS-04 验收"支持按 passed/failed/error/skipped 过滤；**支持 suite 名称过滤**"。当前 `api/v1/runs.py:444-455` `get_run_results` 只有 `status` 参数。

## 实施起点

- **路由**：`src/qaplatform/api/v1/runs.py:get_run_results`
- **仓储**：`src/qaplatform/infra/database/repositories/test_result_repo.py` 或类似
- **ORM**：`TestResult` 表（已有 `suite`、`name` 字段）

## API 改动

```
GET /api/v1/runs/{id}/results
  ?status=passed|failed|error|skipped  # 已有
  ?suite=<str>                          # NEW: 精确匹配 suite 名
  ?q=<str>                              # NEW: 关键字过滤 name / error_message ILIKE
```

## SQL 实现

```python
# 在仓储 list 方法中：
if suite:
    stmt = stmt.where(TestResult.suite == suite)
if q:
    escaped = _escape_like(q)  # 复用 projects.py 里的 LIKE 转义（fix-roadmap §1.1）
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

- 复用 `_escape_like` 函数（fix-roadmap §1.1 已实现）；不要再次复制
- commit：`feat: 测试结果 API 支持 suite 名称与关键字过滤`

## 不要做

- 不要做全文搜索（PG GIN 索引），目前 LIKE 足够
- 不要改 status 过滤逻辑
- 不要顺手分页（已有分页机制）
