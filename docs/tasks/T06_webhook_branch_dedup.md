# T06: F-EX-03 Webhook 分支过滤 + 同 commit 去重

> **来源**：feature-catalog.md §4.1（F-EX-03）
> **必要性**：P1 / 已完成
> **状态**：已完成于 `main`；本文件保留为验收档案
> **预计**：S

## 背景

PRD §3.3 F-EX-03 验收要求"支持分支过滤；支持去重（同 commit 不重复触发）"。当前 `main` 已完成 T06 范围：项目级 webhook 支持 HMAC-SHA256 签名验证、`Project.settings.allowed_branches` 分支过滤、同 commit `Run.dedup_key` 活跃态去重、终态同 commit 再触发，并写入 filtered / duplicate 决策审计。

F-EX-03 更宽的 Git provider 矩阵仍是 catalog/TODO 中的增强缺口：GitHub push provider 已实现，GitLab/Gitee provider、PR/fork 策略、URL 规范化和更完整事件矩阵仍需后续专项处理。这些不属于 T06 的 branch filter / dedup 验收范围。

## 核心口径

- `src/qaplatform/api/v1/webhooks.py` 只处理 webhook request/response，业务判断下沉到 webhook helper。
- `allowed_branches` 为空时默认全部允许；非空时按 `fnmatch` 匹配分支名。
- 分支不匹配返回 `200 OK` decision response，不创建 Run，写 `webhook.filtered`。
- `git_sha` 存在时生成 `Run.dedup_key`；同 project/pipeline/dedup_key 有活跃 Run 时返回 `200 OK` duplicate，不创建新 Run。
- `git_sha` 缺失时跳过去重，但仍执行分支过滤并保持既有 webhook 兼容。
- filtered / duplicate 审计只记录必要 decision state，不回写 repo URL、credential_id 等敏感或可枚举字段。

## 关键位置

- 路由：`src/qaplatform/api/v1/webhooks.py`
- helper：`src/qaplatform/api/webhook_helpers.py`
- 配置校验：`src/qaplatform/api/schemas/projects.py`
- 存储约束：`Run.dedup_key` ORM 字段与 active-run partial unique index
- 集成证据：`tests/integration/test_webhook_branch_dedup.py`

## 验收标准

- [x] `Project.settings.allowed_branches` 空时不过滤（默认全部允许）
- [x] `Project.settings.allowed_branches` 非空时必须是合法 `list[str]`，非法类型/空字符串在项目配置写入时被 422 拒绝
- [x] 非空时按 fnmatch 通配符匹配；不匹配 → 200 OK 返回 `{"status": "filtered"}`，不创建 Run
- [x] 同 commit 在活跃状态时再次 push → 200 OK 返回 `{"status": "duplicate"}`，不创建新 Run
- [x] `filtered` / `duplicate` 响应不会被 `RunResponse` response model 校验拦截；OpenAPI 已声明 200 decision response
- [x] `git_sha` 缺失时不做 dedup，但仍按 `git_ref` 做分支过滤并保持既有 webhook 兼容
- [x] 已完成（done/failed/cancelled）的同 commit 可以再次触发（partial unique index 不冲突）
- [x] 单元测试覆盖 allowed_branches 空 / 单分支 / 通配符 / 不匹配、dedup key、IntegrityError duplicate 和 OpenAPI decision response
- [x] 集成测试覆盖 signed webhook、GitHub provider、filtered、duplicate、终态同 commit 再触发、跨租户 404、enqueue conflict 与审计 payload

## 自动化证据

- `tests/unit/test_api/test_projects.py::test_create_project_rejects_invalid_allowed_branches`
- `tests/unit/test_api/test_projects.py::test_update_project_rejects_invalid_allowed_branches`
- `tests/unit/test_api/test_p3.py::test_webhook_allowed_branches`
- `tests/unit/test_api/test_p3.py::test_webhook_dedup_key_and_audit_state_defaults`
- `tests/unit/test_api/test_p3.py::test_webhook_routes_document_actual_non_run_responses`
- `tests/unit/test_api/test_p3.py::TestWebhookTrigger::test_webhook_trigger_filtered_branch_returns_200_without_run`
- `tests/unit/test_api/test_p3.py::TestWebhookTrigger::test_webhook_trigger_dedup_integrity_error_returns_duplicate`
- `tests/integration/test_webhook_branch_dedup.py`

## 不要做

- 不要新加 alembic 列；branch 配置仍嵌入既有 `Project.settings` JSONB
- 不要把 fnmatch 改成正则
- 不要对手动触发应用 `allowed_branches`；PRD 验收只针对 Webhook
- 不要把 T06 扩成完整 Git provider 矩阵；GitLab/Gitee、PR/fork 和 URL 规范化属于 F-EX-03 剩余增强
