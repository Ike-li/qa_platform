# Codex 任务包索引

> 每个任务包文件自包含。codex 拿到任务文件后即可独立完成：PRD 出处、代码起点、参考实现、验收标准、约束都已就位。
> 任务来源：[`feature-catalog.md`](../feature-catalog.md) §4
> 命名规则：`T<NN>_<slug>.md`；`T<NN>` 是首批任务包的稳定编号，不等同于 catalog §4 当前行号
> 路径约定：未带仓库前缀的后端路径默认相对 `src/qaplatform/`；未带仓库前缀的前端路径默认相对 `frontend/src/`。

| 文件 | 必要性 | 主要修改面 | Alembic / 数据迁移 |
|---|---|---|---|
| [T01_env_vars_encryption.md](T01_env_vars_encryption.md) | P0 | `api/v1/environments.py` + 迁移 | 需要：加密既有数据 |
| [T02_audit_query_api.md](T02_audit_query_api.md) | P0 | 新增 `src/qaplatform/api/v1/audit_events.py` | 不需要 |
| [T03_dingtalk_notify.md](T03_dingtalk_notify.md) | P1 | `worker/notifications/channels.py` | 不需要 |
| [T04_wecom_notify.md](T04_wecom_notify.md) | P1 | `worker/notifications/channels.py` | 不需要 |
| [T05_silent_windows.md](T05_silent_windows.md) | P1 | `worker/settings.py` cron tick + 前端项目设置 | 不需要：写入既有 `Project.settings` JSONB |
| [T06_webhook_branch_dedup.md](T06_webhook_branch_dedup.md) | P1 | `api/v1/webhooks.py` | 不需要：写入既有 `Project.settings` JSONB |
| [T07_test_results_filter.md](T07_test_results_filter.md) | P0 | `api/v1/runs.py` | 不需要 |
| [T10_opentelemetry.md](T10_opentelemetry.md) | P2 | 新增 `observability/tracing.py` + `main.py` + `worker/settings.py` + `config.py` | 不需要 |

## 执行约定（所有任务通用）

来自 project memory directives，每个任务都必须遵守：

- **审计日志**：写入禁用 ORM 实例直传；传入审计前先使用不含 secret/PII 的 Pydantic schema 或 `value.model_dump()`，再交 `_serialize(...)` 规范化；不要依赖 `_serialize` 自动按 key 脱敏
- **commit**：中文 commit message + semantic 前缀（feat/fix/test/chore/docs/refactor），**每个 commit 单一意图，宁拆勿合**
- **租户隔离**：跨租户 ID 访问返回 **404**（非 403）；用 `get_for_tenant` 而非 `get_by_id + 手工 tenant 校验`
- **依赖**：不引入新依赖，除非任务包明确允许；确需新增时必须在 PR 偏离说明中写清
- **Hook**：不要使用 `--no-verify` 或 `--no-gpg-sign` 跳过 hook / 签名；预提交失败先修再提

## 验证基线

每个任务完成后必须满足：

1. 改动过的 Python 文件 `ruff check <paths>` 干净，且不引入新的 lint 错误。
2. 后端任务至少运行 `pytest tests/unit -q`；涉及跨租户、worker、webhook、调度、审计等行为时补跑相关 integration 测试。
3. 新加的代码有对应的单元测试 + 必要时集成测试。
4. 修改 ORM schema 时跑 `alembic check` 验证 schema 与 migration 一致；仅写入既有 JSONB 字段不需要新增 migration。
5. 涉及前端的更新，以“改动文件 TS 干净 + 不引入新 TS 错误”为准；若 `npm run build` 因 main 既有 TS 债务失败，必须确认错误不来自本任务改动文件并在 PR 描述中说明。
6. 若当前 `main` 存在历史 lint / TS 债务，不要在功能任务中顺手清理；单独任务处理。

## 不要做（scope creep）

- 不要顺手重构相邻代码
- 不要修改 review 工具发现的其他问题（fix-roadmap 是历史档案）
- 不要新增依赖除非任务包明确允许
- 不要改 PRD（如发现 PRD / catalog / task 与代码冲突，先在任务报告或 `docs/doc-conflict-audit.md` 中记录，必要时单独开文档任务）
