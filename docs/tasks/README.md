# Codex 任务包索引

> 每个任务包文件自包含。codex 拿到任务文件后即可独立完成：PRD 出处、代码起点、参考实现、验收标准、约束都已就位。
> 任务来源：[`feature-catalog.md`](../feature-catalog.md) §4
> 命名规则：`T<NN>_<slug>.md`；`T<NN>` 是首批任务包的稳定编号，不等同于 catalog §4 当前行号
> 路径约定：未带仓库前缀的后端路径默认相对 `src/qaplatform/`；未带仓库前缀的前端路径默认相对 `frontend/src/`。

| 文件 | 必要性 | 主要修改面 | Alembic / 数据迁移 |
|---|---|---|---|
| [T01_env_vars_encryption.md](T01_env_vars_encryption.md) | P0 / 已完成 | `api/v1/environments.py` + 迁移 + worker 解密注入 | 已完成：migration `007` 加密既有数据 |
| [T02_audit_query_api.md](T02_audit_query_api.md) | P0 / 已完成 | 审计日志查询 API 验收档案：`src/qaplatform/api/v1/audit_events.py` 已实现，正式 PRD 章节仍待补 | 不需要 |
| [T03_dingtalk_notify.md](T03_dingtalk_notify.md) | P1 / 已完成 | `worker/notifications/channels.py` + 前端通知规则表单 | 不需要 |
| [T04_wecom_notify.md](T04_wecom_notify.md) | P1 / 已完成 | `worker/notifications/channels.py` + 前端通知规则表单 | 不需要 |
| [T05_silent_windows.md](T05_silent_windows.md) | P1 / 已完成 | `worker/settings.py` cron tick + 前端项目设置 | 不需要：写入既有 `Project.settings` JSONB |
| [T06_webhook_branch_dedup.md](T06_webhook_branch_dedup.md) | P1 / 已完成 | Webhook 分支过滤 + 同 commit 去重验收档案；更完整 Git provider 矩阵仍见 catalog/TODO | 不需要：写入既有 `Project.settings` JSONB |
| [T07_test_results_filter.md](T07_test_results_filter.md) | P0 / 已完成 | 测试结果 `status` / `suite` / `q` 组合过滤验收档案 | 不需要 |
| [T10_opentelemetry.md](T10_opentelemetry.md) | P2 | 收口既有 OpenTelemetry 基础装配：OTLP HTTP exporter 依赖决策、接收端部署验证和 trace-log 关联后续优化 | 不需要 |
| [T11_T16_regression_platform_plan.md](T11_T16_regression_platform_plan.md) | P0 / 部分完成 | 持续回归平台改造总纲（6 个自包含 WP）：T11 结果导入 API ✅、T12 失败分诊 ✅、T13 失败子集重跑 ✅、T14 dogfooding 数据流 ✅、T15 置信度+通知降噪、T16 用例身份规范化 | T16 可选 `010_` functional index |

## 执行约定（所有任务通用）

来自 project memory directives，每个任务都必须遵守：

- **审计日志**：写入禁用 ORM 实例直传；传入审计前先使用不含 secret/PII 的 Pydantic schema 或 `value.model_dump()`，再交 `_serialize(...)` 规范化；不要依赖 `_serialize` 自动按 key 脱敏
- **commit**：中文 commit message + semantic 前缀（feat/fix/test/chore/docs/refactor），**每个 commit 单一意图，宁拆勿合**
- **租户隔离**：跨租户 ID 访问返回 **404**（非 403）；用 `get_for_tenant` 而非 `get_by_id + 手工 tenant 校验`
- **依赖**：不引入新依赖，除非任务包明确允许；确需新增时必须在 PR 偏离说明中写清
- **Hook**：不要使用 `--no-verify` 或 `--no-gpg-sign` 跳过 hook / 签名；预提交失败先修再提

## 验证基线

每个任务完成后必须满足：

1. 后端 `ruff check src tests` 全量干净；CI `backend-test` 会阻断新增 Python lint 债务。
2. 后端任务至少运行 `pytest tests/unit -q`；涉及跨租户、worker、webhook、调度、审计等行为时补跑相关 integration 测试。
3. 新加的代码有对应的单元测试 + 必要时集成测试。
4. 修改 ORM schema 时跑 `alembic check` 验证 schema 与 migration 一致；仅写入既有 JSONB 字段不需要新增 migration。
5. 涉及前端的更新必须保持 `npm run build`、`npm run lint -- --max-warnings=0` 和相关 E2E smoke 干净；不再允许用历史 TS 债务豁免解释失败。
6. 若未来出现新的前端 TS 或 lint 债务，先登记 owner、恢复条件和验证命令，再单独任务处理；功能任务不得把新增失败留给后续清理。

## 不要做（scope creep）

- 不要顺手重构相邻代码
- 不要修改 review 工具发现的其他问题（`docs/archive/fix-roadmap.md` 是历史档案）
- 不要新增依赖除非任务包明确允许
- 不要改 PRD（如发现 PRD / catalog / task 与代码冲突，先在任务报告或 `docs/archive/doc-conflict-audit.md` 中记录，必要时单独开文档任务）
