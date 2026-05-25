# Codex 任务包索引

> 每个任务包文件自包含。codex 拿到任务文件后即可独立完成：PRD 出处、代码起点、参考实现、验收标准、约束都已就位。
> 任务来源：[`feature-catalog.md`](../feature-catalog.md) §4
> 命名规则：`T<NN>_<slug>.md`，编号与 catalog §4 一致

| 文件 | 必要性 | 主要修改面 | 是否需 alembic |
|---|---|---|---|
| [T01_env_vars_encryption.md](T01_env_vars_encryption.md) | P0 | `api/v1/environments.py` + 迁移 | ✅ 加密既有数据 |
| [T02_audit_query_api.md](T02_audit_query_api.md) | P0 | 新增 `api/v1/audit_events.py` | ❌ |
| [T03_dingtalk_notify.md](T03_dingtalk_notify.md) | P1 | `worker/notifications/channels.py` | ❌ |
| [T04_wecom_notify.md](T04_wecom_notify.md) | P1 | `worker/notifications/channels.py` | ❌ |
| [T05_silent_windows.md](T05_silent_windows.md) | P1 | `worker/scheduler.py` + 前端项目设置 | ❌ |
| [T06_webhook_branch_dedup.md](T06_webhook_branch_dedup.md) | P1 | `api/v1/webhooks.py` | ❌ |
| [T07_test_results_filter.md](T07_test_results_filter.md) | P0 | `api/v1/runs.py` | ❌ |
| [T10_opentelemetry.md](T10_opentelemetry.md) | P2 | `main.py` + `worker/settings.py` + `config.py` | ❌ |

## 执行约定（所有任务通用）

来自 project memory directives，每个任务都必须遵守：

- **审计日志**：写入禁用 ORM 实例直传；用 `_serialize(value.model_dump())` 做 PII/secret 脱敏
- **commit**：中文 commit message + semantic 前缀（feat/fix/test/chore/docs/refactor），**每个 commit 单一意图，宁拆勿合**
- **租户隔离**：跨租户 ID 访问返回 **404**（非 403）；用 `get_for_tenant` 而非 `get_by_id + 手工 tenant 校验`
- **Hook**：不跳过 `--no-verify` 或 `--no-gpg-sign`；预提交失败先修再提

## 验证基线

每个任务完成后必须满足：

1. `make lint` 干净（ruff check）
2. `make test` 单元测试通过
3. 新加的代码有对应的单元测试 + 必要时集成测试
4. 修改 ORM 时跑 `alembic check` 验证 schema 与 migration 一致
5. 涉及前端的更新 `make frontend-test`（若有），或本地 `npm run build` 通过

## 不要做（scope creep）

- 不要顺手重构相邻代码
- 不要修改 review 工具发现的其他问题（fix-roadmap 是历史档案）
- 不要新增依赖除非任务包明确允许
- 不要改 PRD（PRD 与代码当前已对齐，需要变更先讨论）
