# T05: F-EX-02 静默窗口

> **来源**：feature-catalog.md §4.1（F-EX-02；设计见 feature-catalog.md §4.3）
> **必要性**：P1（PRD §3.3 验收项，当前已完成）
> **预计**：M（后端 + 前端）
> **当前状态**：已落地到 API、worker、前端、unit、required integration 与 E2E 证据；保留本文作为实现口径档案。

## 背景

PRD §3.3 F-EX-02 验收"支持时区；支持静默窗口（如发布冻结期不触发）"。timezone 与项目级静默窗口均已实现：项目设置写入 `Project.settings.silent_windows`，cron 命中时不触发 Run，手动触发与 webhook 不受影响。

本文保留为实现口径档案，重点锁住 `quiet_windows` 与 `silent_windows` 的边界，避免后续维护时误改行为。

## 核心口径

- `silent_windows` 嵌入既有 `Project.settings` JSONB，不新增 alembic 列。
- `start_at` / `end_at` 必须为 tz-aware datetime，且 `end_at > start_at`。
- `Project.settings.silent_windows` 是项目级发布冻结期，影响 cron tick。
- `Schedule.quiet_windows` 是 schedule 级窗口，由既有 scheduling 逻辑处理；不要与项目级静默窗口混用。
- 命中 `silent_windows` 时不创建 Run、不更新 `schedule.last_run_at`，写 audit `schedule_skipped_silent_window`。
- 手动触发和 webhook 触发完全忽略 `silent_windows`。

## 关键位置

- API schema：`src/qaplatform/api/schemas/projects.py`
- 项目路由：`src/qaplatform/api/v1/projects.py`
- 静默窗口判定：`src/qaplatform/domain/services/schedule.py`
- cron firing：`src/qaplatform/worker/schedule_firing.py`
- 项目设置 UI：`frontend/src/pages/projects/detail.tsx`

## 验收标准

- [x] `PUT /api/v1/projects/{project_id}` 接受 silent_windows，校验 `end_at > start_at`、单项目 ≤ 20 条窗口
- [x] cron tick 命中窗口 → 不创建 Run + 写 audit `schedule_skipped_silent_window`
- [x] audit 的 `after_state` 包含 `schedule_id` 与命中的 `window`（当前 `AuditEvent` 无 `metadata` 列，不为 T05 新增 audit schema migration）
- [x] cron tick 命中窗口 → schedule 的 `last_run_at` 不更新
- [x] **手动触发 / Webhook 触发 完全忽略 silent_windows**
- [x] 时区敏感：start_at/end_at 必须 tz-aware，不接受 naive datetime
- [x] 前端项目设置页可添加/删除/编辑窗口
- [x] 单元测试：is_in_silent_window 边界（窗口起止时刻、跨夜、不同时区）
- [x] 集成测试：真实 API/DB 保存、window 内 cron tick、window 外 cron tick、手动触发与 webhook 不受影响

## 约束

- audit 写入必须使用不含 secret/PII 的 dict/schema。
- cron worker 没有 `CurrentUser`，不要调用依赖 user 的 API helper。
- 当前 `AuditEvent` 没有 `metadata` 列，静默窗口跳过详情写入 `after_state`。

## 不要做

- 不要做周期性窗口（如"每周末"），未来扩展 `cron_pattern` 字段时再加
- 不要 alembic 加新列（嵌入 `settings` JSONB）
- 不要让静默窗口影响手动触发（用户旅程明确只针对 cron）
