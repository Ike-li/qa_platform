# 后端测试审计与补强记录

审计日期：2026-05-27

## 结论

从测试负责人视角看，后端测试现在可以按“覆盖率门禁 + 关键风险路径 + 真实数据链路 + CI 可复跑性”给出综合结论：当前已经达到可作为主分支门禁的水平，但还不是“零风险/零 warning”的状态。

本轮后的核心判断：

- 覆盖率指标：启用 coverage branch mode，CI 使用 `--cov-report=term-missing`，并设置 `fail_under = 83`。
- 关键业务路径：覆盖 pipeline API、项目/成员落库、run 状态迁移、schedule/webhook/cancel、worker 调度、插件注册、日志配置。
- 安全风险路径：覆盖 JWT/API token 中间件、真实 JWT 注册到 API token 创建/使用/撤销、API token scope 路由矩阵、审计失败路径、跨租户隔离、RBAC audit-events 拒绝路径。
- 真实数据路径：integration suite 使用真实 PostgreSQL/Redis/Testcontainers/FastAPI ASGI app；新增测试不 mock repository 或 database session。
- 数据保留/审计路径：retention 真实 Postgres 测试覆盖超期终态 Run 硬删与 result/artifact/event 级联；batch cancel/retry API 覆盖真实 DB 状态和 audit 行写入；project、project member、pipeline、credentials、environments、notification rules 已补真实 DB audit before/after 断言，项目 `git_url` userinfo、凭据明文、环境变量、通知 channel/template 不落审计状态。
- 日志归档补偿与回看：归档失败登记 Redis retry set，worker cron 重试由单测锁定成功/失败路径；SSE `Last-Event-ID` 断点续传由真实 JWT、真实 ticket、PostgreSQL/RBAC 与 Redis Stream 集成测试覆盖；归档 JSONL 读回 API 由真实 DB/RBAC/API 集成测试覆盖，并验证分页窗口与对象缺失 404。
- Artifact 风险：环境级产物大小/数量限制传入 worker 并在上传前强制校验，真实 DB 集成测试证明被跳过产物不会写 Artifact 行；`results/` 递归上传与 Allure 目录文件落库也有真实 DB/S3 证据；artifact 列表到下载链接的真实 JWT/RBAC/DB 行、bucket/key/TTL 参数已进入 required integration。
- 真实 worker 黑盒：nightly/manual 会启动 compose API/worker/MinIO；external-stack smoke 覆盖真实 API 触发后 worker 执行容器、产物列表、预签名下载链接、实际下载对象内容、归档日志 API，以及 worker_lost 后自动 retry 再完成的链路。
- Worker 重试：真实 DB 集成测试覆盖 `execute_run` 基础设施异常路径，验证原 Run failed、retry Run 落库并入队；external-stack 进一步扰动 medium worker，验证 reclaimer cron 创建 retry Run，重启 worker 后 retry Run 产出 artifact、可下载 JUnit 内容与归档日志。
- Webhook/schedule 失败路径：新增 required integration 断言 archived project、missing pipeline/environment、enqueue conflict、cross-project pipeline 都不会静默写错真实 DB 状态。
- CI 稳定性：后端 ruff 与单测覆盖率是同一门禁；PR/push 必跑 required integration；heavy Docker/worker integration 拆到 nightly/manual；PR E2E 保留轻量 UI 冒烟，nightly 固定跑真实 E2E 主路径，完整真实 E2E 留给手动 workflow。
- 非功能 smoke：nightly/manual 覆盖读 API、写 API、触发入队 SLO、Redis 日志写读、SSE 实时日志推送 < 2s、归档日志读回 API、artifact 下载链接 API、执行摘要生成 < 3s 趋势哨兵，并在失败时输出 p50/p99/max 摘要；不把性能环境抖动放进 PR 硬门禁。

## Mock 使用口径

当前测试中仍然有 mock，但用途是分层隔离，不是替代真实数据功能验证：

- 单元测试里的 mock 用来锁定分支、错误处理、外部服务失败和边界输入，适合快速定位逻辑回归。
- `auth-flow.spec.ts` 的 E2E mock API 是前端登录/导航冒烟，不能作为后端数据正确性的证据。
- 真实后端数据正确性由 integration suite 承担：真实 PostgreSQL schema、真实事务/唯一约束/soft-delete、真实 FastAPI 路由、真实 JWT/API token、真实 audit/event 写入。
- 部分 integration fixture 会 override 当前用户以便稳定覆盖 RBAC/API 行为；本轮新增了无 current-user override 的真实 JWT/API token 与 artifact 下载链路，补上“鉴权是否真的能走通数据库”的证据。
- SSE 单测里的 Redis fake 只用于替代 rate-limit/SSE 单元边界的外部服务，真实 Redis/DB/API 状态由 required integration 验证。

## 覆盖率基线

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/tmp/qaplatform-final.coverage .venv/bin/python -m pytest tests/unit -q -p no:cacheprovider --cov=qaplatform --cov-report=term-missing --cov-report=json:/tmp/qaplatform-final-coverage.json --tb=short --durations=20
```

当前基线结果：

- 单元测试：758 passed
- 总覆盖率：83.37%
- 语句覆盖率：85.92%
- 分支覆盖率：70.14%
- warnings：项目内 SQLAlchemy overlap 与 Redis pubsub `close()` 已清理；testcontainers 第三方弃用提示已精确过滤并登记 owner/截止条件

真实 DB / API 集成验证：

```bash
RUN_INTEGRATION_TESTS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration --collect-only -q -p no:cacheprovider
RUN_INTEGRATION_TESTS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration -m "not heavy_docker and not external_stack and not performance" -q -p no:cacheprovider --tb=short --durations=20
RUN_INTEGRATION_TESTS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration -q -p no:cacheprovider --tb=short -rs
```

当前结果：

- integration 收集：121 tests
- PR/push 必跑 required integration：100 passed, 21 deselected
- 完整 local integration（未启动外部 API/worker 栈）：107 passed, 14 skipped
- performance smoke opt-in：8 passed
- skipped 来自 Docker image/registry 前置条件缺失、macOS Docker Desktop OOMKilled 平台语义、未设置 `RUN_PERFORMANCE_TESTS=1` 的 performance smoke，以及本地未启动 external stack；CI nightly/manual 会主动启动 external stack，业务断言失败不会被 skip 或 retry 掩盖

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
| `qaplatform.worker.settings` | 87% | 周期任务、资源回收、失败补偿路径已覆盖 |
| `qaplatform.api.v1.pipelines` | 84% | Pipeline API 主路径和常见失败路径已覆盖 |

## 门禁说明

`fail_under = 83` 是当前有效补强后的可持续门槛，而不是为了数字最大化设定的目标。设置 84% 在当前代码形态下会失败；继续硬抬主要会落到数据库 repository CRUD、依赖注入 glue、外部 SDK 初始化等区域，容易变成重 mock 的覆盖率工程。

后续提升覆盖率应优先靠真实风险路径或集成测试补齐，而不是仅为全局百分比补空行。

当前 CI 门禁分层：

- `backend-test`：跑后端单元测试和 coverage fail-under。
- `backend-test`：先跑 `ruff check src tests`，再跑后端单元测试和 coverage fail-under。
- `backend-integration-test`：PR/push 跑 `tests/integration -m "not heavy_docker and not external_stack and not performance"`；`workflow_dispatch`/nightly 额外跑 `heavy_docker`，再启动 compose API/worker/MinIO 后跑 `external_stack` 分组。
- `backend-integration-test`：`workflow_dispatch`/nightly 额外跑 `tests/integration/test_performance_smoke.py -m performance`，用于非功能趋势观察。
- `e2e-test`：PR 跑 `auth-flow.spec.ts` UI 冒烟；nightly 跑三条真实 E2E 主路径；`workflow_dispatch` 跑完整 Playwright E2E。
- 更多分层细节见 `docs/testing-strategy.md`。

## 残余缺口

- 数据库 repositories 已覆盖 Project/Pipeline/Run、Audit/User、API token、TestResult、Artifact 的真实 Postgres 行为，并覆盖分页、唯一约束 rollback、soft-delete 和 terminal run retention cascade；retention 已覆盖普通超期终态 Run 与 `cancelled/timeout`。
- batch cancel/retry 已补 API 写入后真实 DB 状态和 audit 行验证。
- project/project member/pipeline/credentials/environments/notification rules 已补 API 写入后的真实 DB 审计状态检查：项目 `git_url` userinfo、凭据明文、环境变量值、通知 channel 地址/webhook URL 和模板正文不进入 audit before/after；project、pipeline、project member、notification、schedule delete 已补删除前状态快照。
- log archive 失败已补 Redis retry set 与 worker cron 重试路径；归档日志读回 API 已补真实 DB/RBAC/API 集成测试，覆盖默认页、分页窗口和 S3 对象缺失 404 ErrorResponse；artifact 下载链接已补真实 JWT/RBAC/API/DB 行到预签名 bucket/key/TTL 的 required integration；external-stack worker smoke 与 worker_lost retry 进一步证明真实 worker 完成后可经 API 回看归档日志，并可经预签名 URL 下载真实 JUnit artifact 内容；前端 run detail 已接入终态 run 的归档日志回看，并用 Playwright 真实 DB+S3 数据覆盖日志搜索与 HTML artifact 预览。
- Webhook/API/schedule worker 新增真实 DB 失败路径后，project archived、pipeline/environment missing、cross-project pipeline、enqueue conflict 已进 required integration；schedule pipeline missing 仍保留 unit 覆盖，因为真实 FK 下硬删除会级联，软删除不等价于真实缺行。
- 分支覆盖率仍低于语句覆盖率：主要来自依赖初始化分支、外部 SDK/worker 边界和少量异常恢复路径。
- warnings 治理：项目内 SQLAlchemy overlap、Redis pubsub `close()`、SSE AsyncMock、httpx cookies、JWT key length warning 均已清理；testcontainers 第三方弃用提示已在 `pyproject.toml` 精确过滤并登记。
- PR E2E 是 mock API UI 冒烟，不证明真实后端；真实后端 E2E 已有 `real-login-flow`、`real-run-trigger`、`special-regressions`，其中 `special-regressions` 覆盖归档日志回看与 artifact 预览，当前 CI 在 nightly 固定执行这些真实主路径，manual 执行全量。

## 后续优先级

1. 自动重试已补 API-facing `max_attempts`、`retry_on`、waiting retry run、execute_run 基础设施异常、worker_lost callback 路径和 external-stack worker_lost 黑盒；后续如要继续提高信心，可继续补 clone/setup/Docker daemon 失败是否也应进入 retry 的产品化闭环。
2. 严格产品 SLO 与完整性能压测仍需专项环境；当前 smoke 已覆盖触发入队 < 5s、SSE 实时日志推送 < 2s、执行摘要生成 < 3s 趋势哨兵并输出失败摘要。
3. 通知更高级产品能力仍待补：OR 条件、连续失败次数、每渠道模板、项目名/失败用例变量；本轮已补真实 DB delivery、模板失败、发送失败与幂等。
4. 审计写入覆盖下一步应按高风险资源继续外扩到 webhook/schedule worker 自动触发、pipeline/webhook 复杂配置等写路径，重点检查“该写的 before/after 是否完整”和“敏感字段是否脱敏”，而不是只检查 action 名存在。
5. 后续提升 coverage 门槛应继续依赖真实风险路径，而不是为百分比增加无行为断言。
