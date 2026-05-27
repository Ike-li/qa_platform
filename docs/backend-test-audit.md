# 后端测试审计与补强记录

审计日期：2026-05-27

## 结论

从测试负责人视角看，后端测试现在可以按“覆盖率门禁 + 关键风险路径 + 真实数据链路 + CI 可复跑性”给出综合结论：当前已经达到可作为主分支门禁的水平，但还不是“零风险/零 warning”的状态。

本轮后的核心判断：

- 覆盖率指标：启用 coverage branch mode，CI 使用 `--cov-report=term-missing`，并设置 `fail_under = 83`。
- 关键业务路径：覆盖 pipeline API、项目/成员落库、run 状态迁移、schedule/webhook/cancel、worker 调度、插件注册、日志配置。
- 安全风险路径：覆盖 JWT/API token 中间件、真实 JWT 注册到 API token 创建/使用/撤销、审计失败路径、跨租户隔离、RBAC audit-events 拒绝路径。
- 真实数据路径：integration suite 使用真实 PostgreSQL/Redis/Testcontainers/FastAPI ASGI app；新增测试不 mock repository 或 database session。
- CI 稳定性：后端单测有覆盖率门槛；PR/push 必跑 required integration；heavy Docker/worker integration 拆到 nightly/manual；PR E2E 保留轻量 UI 冒烟，完整真实 E2E 留给手动 workflow。

## Mock 使用口径

当前测试中仍然有 mock，但用途是分层隔离，不是替代真实数据功能验证：

- 单元测试里的 mock 用来锁定分支、错误处理、外部服务失败和边界输入，适合快速定位逻辑回归。
- `auth-flow.spec.ts` 的 E2E mock API 是前端登录/导航冒烟，不能作为后端数据正确性的证据。
- 真实后端数据正确性由 integration suite 承担：真实 PostgreSQL schema、真实事务/唯一约束/soft-delete、真实 FastAPI 路由、真实 JWT/API token、真实 audit/event 写入。
- 部分 integration fixture 会 override 当前用户以便稳定覆盖 RBAC/API 行为；本轮新增了无 current-user override 的真实 JWT/API token 链路，补上“鉴权是否真的能走通数据库”的证据。
- SSE 单测里的 Redis fake 只用于替代 rate-limit/SSE 单元边界的外部服务，真实 Redis/DB/API 状态由 required integration 验证。

## 覆盖率基线

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/tmp/qaplatform-final.coverage .venv/bin/python -m pytest tests/unit -q -p no:cacheprovider --cov=qaplatform --cov-report=term-missing --cov-report=json:/tmp/qaplatform-final-coverage.json --tb=short --durations=20
```

当前结果：

- 单元测试：729 passed
- 总覆盖率：83.24%
- 语句覆盖率：85.88%
- 分支覆盖率：69.16%
- warnings：3（剩余为 testcontainers 第三方弃用提示 + SQLAlchemy mapper overlap 登记项）

真实 DB / API 集成验证：

```bash
RUN_INTEGRATION_TESTS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration --collect-only -q -p no:cacheprovider
RUN_INTEGRATION_TESTS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration -m "not heavy_docker and not external_stack" -q -p no:cacheprovider --tb=short --durations=20
RUN_INTEGRATION_TESTS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration -q -p no:cacheprovider --tb=short -rs
```

当前结果：

- integration 收集：83 tests
- PR/push 必跑 required integration：72 passed, 11 deselected, 3 warnings
- 完整 local integration：81 passed, 2 skipped, 9 warnings
- skipped 只来自 macOS Docker Desktop OOMKilled 平台语义；业务断言失败不会被 skip 或 retry 掩盖

E2E 冒烟验证：

```bash
E2E_ADMIN_PASSWORD=admin123 npm run test:e2e -- tests/e2e/auth-flow.spec.ts --project=chromium
```

当前结果：

- PR 级 UI 冒烟：1 passed

关键补强模块：

| 模块 | 本轮后覆盖率 | 判断 |
| --- | ---: | --- |
| `qaplatform.api.auth.middleware` | 98% | 安全主干和失败分支已覆盖，分支覆盖 100% |
| `qaplatform.domain.services.scheduling` | 100% | 调度计算核心已覆盖 |
| `qaplatform.plugins.registry` | 100% | 插件注册/发现路径已覆盖 |
| `qaplatform.logging` | 100% | JSON/console logging 配置已覆盖 |
| `qaplatform.worker.scheduler` | 95% | 队列容量、优先级、去重入队路径已覆盖 |
| `qaplatform.worker.settings` | 89% | 周期任务、资源回收、失败补偿路径已覆盖 |
| `qaplatform.api.v1.pipelines` | 84% | Pipeline API 主路径和常见失败路径已覆盖 |

## 门禁说明

`fail_under = 83` 是当前有效补强后的可持续门槛，而不是为了数字最大化设定的目标。设置 84% 在当前代码形态下会失败；继续硬抬主要会落到数据库 repository CRUD、依赖注入 glue、外部 SDK 初始化等区域，容易变成重 mock 的覆盖率工程。

后续提升覆盖率应优先靠真实风险路径或集成测试补齐，而不是仅为全局百分比补空行。

当前 CI 门禁分层：

- `backend-test`：跑后端单元测试和 coverage fail-under。
- `backend-integration-test`：PR/push 跑 `tests/integration -m "not heavy_docker and not external_stack"`；`workflow_dispatch`/nightly 额外跑 `heavy_docker` 和 `external_stack` 分组。
- `e2e-test`：PR 跑 `auth-flow.spec.ts` UI 冒烟；`workflow_dispatch` 跑完整 Playwright E2E。
- 更多分层细节见 `docs/testing-strategy.md`。

## 残余缺口

- 数据库 repositories 已覆盖 Project/Pipeline/Run、Audit/User、API token、TestResult、Artifact 的真实 Postgres 行为，并覆盖分页、唯一约束 rollback、soft-delete 和 terminal run retention cascade。
- 分支覆盖率仍低于语句覆盖率：主要来自 API 路由错误分支、通知 channel 网络异常矩阵和依赖初始化分支。
- warnings 尚未清零：剩余主要是 testcontainers 第三方弃用提示、SQLAlchemy relationship overlap 提示、Redis pubsub `close()` 弃用提示；已清理 SSE AsyncMock、httpx per-request cookies 和 JWT key length warning。
- PR E2E 是 mock API UI 冒烟，不证明真实后端；真实后端 E2E 已有 `real-login-flow`、`real-run-trigger`、`special-regressions`，但当前 CI 仅在手动 workflow 全量执行，避免 PR 过慢和 flaky。

## 后续优先级

1. 扩展 webhook/schedule 的 pipeline missing、project archived、enqueue failed 失败路径到更多真实 DB/API 场景。
2. 为 API token scope 做更细的端到端权限矩阵，并继续补 notifications 外部 channel 网络异常。
3. 在不改 API 行为的前提下单独评估 SQLAlchemy overlap、Redis pubsub `close()` 与 testcontainers deprecation；warnings 收敛后再考虑把 `fail_under` 提升到 84+。
