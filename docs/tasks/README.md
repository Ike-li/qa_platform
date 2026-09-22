# 任务包索引

> 每个任务包文件自包含：需求出处、代码起点、参考实现、验收标准、约束都已就位。
> 任务来源：[`feature-catalog.md`](../feature-catalog.md) §4
> 路径约定：未带仓库前缀的后端路径默认相对 `src/qaplatform/`；未带仓库前缀的前端路径默认相对 `frontend/src/`。

| 文件 | 必要性 | 主要修改面 | Alembic / 数据迁移 |
|---|---|---|---|
| [T10_opentelemetry.md](T10_opentelemetry.md) | P2 / 待执行 | 收口既有 OpenTelemetry 基础装配：OTLP HTTP exporter 依赖决策、接收端部署验证和 trace-log 关联后续优化 | 不需要 |

已完成的任务包（T01–T07、T11–T17）于 2026-09-22 删除。它们描述的功能全部落地，代码与测试才是当前真相；当初的取舍理由记在对应 commit message 的 trailer 里（`Constraint:` / `Rejected:` / `Tested:` / `Not-tested:`），那些记录与代码同生共死，不会像文档一样单独腐败。

---

## 执行约定（所有任务通用）

- **审计日志**：写入禁用 ORM 实例直传；传入审计前先用不含 secret/PII 的 Pydantic schema 或 `value.model_dump()`，再交 `_serialize(...)` 规范化；不要依赖 `_serialize` 自动按 key 脱敏
- **commit**：中文 commit message + semantic 前缀（feat/fix/test/chore/docs/refactor），**每个 commit 单一意图，宁拆勿合**
- **租户隔离**：跨租户 ID 访问返回 **404**（非 403）；用 `get_for_tenant` 而非 `get_by_id + 手工 tenant 校验`
- **依赖**：不引入新依赖，除非任务包明确允许。确需新增时先改 `pyproject.toml`，再跑 `uv lock` 并提交 `uv.lock`——CI 的 `uv lock --check` 会拦住不同步的改动
- **Hook**：不要用 `--no-verify` 或 `--no-gpg-sign` 跳过 hook / 签名；预提交失败先修再提

## 验证基线

每个任务完成后必须满足：

1. 后端 `ruff check src tests` 全量干净；CI `backend-test` 会阻断新增 Python lint 债务
2. 后端任务至少运行 `pytest tests/unit -q`；涉及跨租户、worker、webhook、调度、审计等行为时补跑相关 integration 测试（`RUN_INTEGRATION_TESTS=1`）
3. 新加的代码有对应的单元测试 + 必要时集成测试
4. 修改 ORM schema 时跑 `alembic check` 验证 schema 与 migration 一致；仅写入既有 JSONB 字段不需要新增 migration
5. 涉及前端的更新必须保持 `npm run build`、`npm run lint -- --max-warnings=0` 和相关 E2E smoke 干净
6. 动手前先 `uv pip install -e '.[dev]' --upgrade`。CI 从 `uv.lock` 安装精确版本，本地版本落后时「本地全绿」不代表 CI 会绿

## 不要做（scope creep）

- 不要顺手重构相邻代码
- 不要新增依赖除非任务包明确允许
- 不要在功能任务里夹带文档大改；发现文档与代码冲突时单独开任务
