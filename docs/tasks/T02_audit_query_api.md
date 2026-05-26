# T02: 审计日志查询 API

> **来源**：feature-catalog.md §4.1（审计日志查询 API）
> **必要性**：P0（未达 catalog §4.1 审计查询验收）
> **预计**：S

## 背景

[feature-catalog.md](../feature-catalog.md) §4.1 要求提供审计日志查询 API（仅 Admin+ 可访问）。当前写入端 `api/audit.py` + 仓储 `infra/database/repositories/audit_repo.py` 已就位，但**没有查询路由**。

> 注意：旧文档曾引用 `PRD §9.6`，但当前 `docs/prd.md` 实际只到第 8 章。PR 描述不要继续引用不存在的章节；如需 PRD 出处，应先补 PRD 章节或引用 catalog。

## 缺什么

新建 `src/qaplatform/api/v1/audit_events.py`，提供分页查询审计事件的 GET 端点。

## 实施起点

- **ORM**：`AuditEvent` 已存在（`infra/database/models.py`，在 AuditBase schema 下）
- **仓储**：`infra/database/repositories/audit_repo.py`（按需扩展 list 方法）
- **路由模式参考**：`api/v1/admin.py`（admin 端点组织方式参考） + `api/v1/runs.py`（分页参考）
- **权限**：`api/auth/permissions.py` 中租户 Owner/Admin 才能访问；注意 `admin.py::_require_platform_admin` 是平台管理员校验，不能直接照搬成 T02 的权限策略
- **路由注册**：新增 router 后必须在 `src/qaplatform/main.py::create_app` 引入并 `include_router(..., prefix="/api/v1")`；`api/v1/__init__.py` 当前不是自动发现机制
- **权限实现注意**：当前 `Action` 枚举没有 `AUDIT_READ`；实现时要么新增 tenant-scoped action 并只授予 Owner/Admin，要么在 T02 路由内写显式 Owner/Admin guard。不要复用会放行 Member 的现有读权限

## API 设计

```
GET /api/v1/audit-events
  ?actor_id=<uuid>           # 过滤操作人
  ?action=<str>              # 如 login_success / project_archive
  ?resource_type=<str>       # 如 project / credential / run；与 AuditEvent ORM 字段同名
  ?resource_id=<uuid>        # 配合 resource_type
  ?start_at=<iso8601>
  ?end_at=<iso8601>
  ?page=1&per_page=20        # 默认 20，最大 100
  
Response: PaginatedResponse[AuditEventResponse]
```

`AuditEventResponse` 应按 `AuditEvent` ORM 字段显式定义 Pydantic schema（`tenant_id/user_id/action/resource_type/resource_id/before_state/after_state/ip_address/user_agent/created_at` 等），不要把 SQLAlchemy ORM 类直接作为 API response model。

## 验收标准

- [ ] 仅租户 Owner/Admin 可访问（Member/Viewer 返回 403）
- [ ] 跨租户隔离：列表只返回当前 tenant_id 的事件；带具体跨租户 resource id 的访问/过滤不得泄露存在性，按路由语义返回 404 或空结果
- [ ] 所有过滤参数可组合
- [ ] 默认按 `created_at DESC` 排序
- [ ] 响应体沿用 `PaginatedResponse`，返回 `page` / `per_page` / `total` 字段（当前仓库分页不是 HTTP header 口径）
- [ ] 集成测试：覆盖权限、过滤、跨租户隔离 3 类用例

## 约束

- 跨租户资源 id 访问返回 **404 非 403**（project memory directive）；普通列表过滤不得返回其他 tenant 数据
- 端点本身的访问也要写 audit（self-referential：管理员看 audit 也被 audit）
- commit 拆分建议：
  1. `feat: audit_events 仓储 list 方法支持过滤参数`
  2. `feat: GET /api/v1/audit-events 路由 + Admin 权限`
  3. `test: audit_events 查询权限与跨租户隔离集成测试`

## 不要做

- 不要支持搜索全文（当前范围不做，见 catalog §5）
- 不要支持导出 CSV（当前范围不做，见 catalog §5）
- 不要修改写入端逻辑
