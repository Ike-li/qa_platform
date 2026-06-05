# T02: 审计日志查询 API

> 状态：已完成于 `main`。当前实现位于 `src/qaplatform/api/v1/audit_events.py`，集成测试位于 `tests/integration/test_audit_events_api.py`；本文保留为验收档案。

> **来源**：feature-catalog.md §4.1（审计日志查询 API）
> **必要性**：P0（已完成，保留为验收档案；正式 PRD 章节仍待补）
> **预计**：S

## 背景

[feature-catalog.md](../feature-catalog.md) §4.1 要求提供审计日志查询 API（仅 Owner/Admin 可访问）。当前写入端 `api/audit.py`、仓储 `infra/database/repositories/audit_repo.py`、查询路由 `api/v1/audit_events.py`、`Action.AUDIT_READ` 权限和真实 API/DB 测试均已落地。

> 注意：旧文档曾引用 `PRD §9.6`（审计日志章节），但 `docs/product.md` 并无审计日志的正式 PRD 章节（编号功能需求到 §8，§9 为试点边界）。PR 描述不要继续引用不存在的章节；如需 PRD 出处，应先补 PRD 章节或引用 catalog。

## 已实现

- `GET /api/v1/audit-events` 返回 `PaginatedResponse[AuditEventResponse]`
- 支持 `actor_id`、`action`、`resource_type`、`resource_id`、`start_at`、`end_at`、`page`、`per_page` 组合过滤
- 默认按 `created_at DESC` 排序
- Owner/Admin 可访问，Member/Viewer 返回 403
- API token 必须具备 `audit.read`；`run.read`、`project.read`、空 scope 会被拒绝
- 成功查询写 `audit_events.list` 自审计，拒绝路径和跨租户过滤不写误导性自审计
- 跨租户资源 ID 过滤收敛为 404 或空结果，不返回其他租户数据

## 实施位置

- **ORM**：`infra/database/models.py::AuditEvent`
- **仓储**：`infra/database/repositories/audit_repo.py`
- **路由**：`src/qaplatform/api/v1/audit_events.py`
- **路由注册**：`src/qaplatform/main.py::create_app`
- **权限**：`api/auth/permissions.py::Action.AUDIT_READ`，tenant Owner/Admin 与具备 `audit.read` scope 的 API token 可访问
- **单元测试**：`tests/unit/test_api/test_audit.py`
- **集成测试**：`tests/integration/test_audit_events_api.py`、`tests/integration/test_real_auth_results_artifacts.py`

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

- [x] 仅租户 Owner/Admin 可访问（Member/Viewer 返回 403）
- [x] 跨租户隔离：列表只返回当前 tenant_id 的事件；带具体跨租户 resource id 的访问/过滤不得泄露存在性，按路由语义返回 404 或空结果
- [x] 所有过滤参数可组合
- [x] 默认按 `created_at DESC` 排序
- [x] 响应体沿用 `PaginatedResponse`，返回 `page` / `per_page` / `total` 字段（当前仓库分页不是 HTTP header 口径）
- [x] 集成测试：覆盖权限、过滤、跨租户隔离 3 类用例
- [x] 成功查询写 `audit_events.list` 自审计；拒绝路径不误写自审计
- [x] API token scope：`audit.read` 可查询，`run.read` / `project.read` / 空 scope 被拒绝

## 约束

- 跨租户资源 id 访问返回 **404 非 403**（project memory directive）；普通列表过滤不得返回其他 tenant 数据
- 端点本身的成功访问也要写 audit（self-referential：管理员看 audit 也被 audit）；拒绝路径不写误导性自审计
- 正式 PRD 章节仍待产品文档补齐；当前验收依据为 feature-catalog / TODO / 本档案

## 不要做

- 不要支持搜索全文（当前范围不做，见 catalog §5）
- 不要支持导出 CSV（当前范围不做，见 catalog §5）
- 不要修改写入端逻辑
