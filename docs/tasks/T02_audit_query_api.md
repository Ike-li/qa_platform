# T02: 审计日志查询 API

> **来源**：feature-catalog.md §4.1 #2
> **必要性**：P0（未达 PRD §9.6 验收）
> **预计**：S

## 背景

PRD §9.6："提供审计日志查询 API（仅 Admin+ 可访问）"。当前写入端 `api/audit.py` + 仓储 `infra/database/repositories/audit_repo.py` 已就位，但**没有查询路由**。

## 缺什么

新建 `src/qaplatform/api/v1/audit_events.py`，提供分页查询审计事件的 GET 端点。

## 实施起点

- **ORM**：`AuditEvent` 已存在（`infra/database/models.py:653`，在 AuditBase schema 下）
- **仓储**：`infra/database/repositories/audit_repo.py`（按需扩展 list 方法）
- **路由模式参考**：`api/v1/admin.py`（admin 端点参考） + `api/v1/runs.py`（分页参考）
- **权限**：`api/auth/permissions.py` 中租户 Admin+ 才能访问

## API 设计

```
GET /api/v1/audit-events
  ?actor_id=<uuid>           # 过滤操作人
  ?action=<str>              # 如 login_success / project_archive
  ?target_type=<str>         # 如 project / credential / run
  ?target_id=<uuid>          # 配合 target_type
  ?start_at=<iso8601>
  ?end_at=<iso8601>
  ?page=1&per_page=20        # 默认 20，最大 100
  
Response: PaginatedResponse[AuditEvent]
```

## 验收标准

- [ ] 仅租户 Owner/Admin 可访问（Member/Viewer 返回 403）
- [ ] 跨租户隔离：只返回当前 tenant_id 的事件，跨租户 id 访问返回 404
- [ ] 所有过滤参数可组合
- [ ] 默认按 `created_at DESC` 排序
- [ ] 分页头返回 page/per_page/total
- [ ] 集成测试：覆盖权限、过滤、跨租户隔离 3 类用例

## 约束

- 跨租户返回 **404 非 403**（project memory directive）
- 端点本身的访问也要写 audit（self-referential：管理员看 audit 也被 audit）
- commit 拆分建议：
  1. `feat: audit_events 仓储 list 方法支持过滤参数`
  2. `feat: GET /api/v1/audit-events 路由 + Admin 权限`
  3. `test: audit_events 查询权限与跨租户隔离集成测试`

## 不要做

- 不要支持搜索全文（Phase 3 已决策不做）
- 不要支持导出 CSV（catalog §5 已决策不做）
- 不要修改写入端逻辑
