# 后端测试审计与补强记录

审计日期：2026-05-28

## 结论

从测试负责人视角看，后端测试现在可以按“覆盖率门禁 + 关键风险路径 + 真实数据链路 + CI 可复跑性”给出综合结论：当前已经达到可作为主分支门禁的水平，但还不是“零风险/零 warning”的状态。

本轮后的核心判断：

- 覆盖率指标：启用 coverage branch mode，CI 使用 `--cov-report=term-missing`，并设置 `fail_under = 83`。
- 关键业务路径：覆盖 pipeline API、项目/成员落库、run 状态迁移、schedule/webhook/cancel、worker 调度、manual priority 队列元数据、插件注册、日志配置。
- 安全风险路径：覆盖 JWT/API token 中间件、真实 JWT 注册到 API token 创建/使用/撤销、refresh revoke Redis 抖动不阻断 token 轮换、auth 失败审计写入异常不把 401/204 变成 500、register/refresh/logout 审计状态不泄露 password/access token/refresh token、API token create/revoke 审计状态不泄露 full token / secret / hash、API token scope 路由矩阵、artifact 下载与归档日志读回的 `run.read` scope、跨租户 404 收敛、签名 webhook HMAC 验证、审计失败路径、跨租户隔离、RBAC audit-events 拒绝路径，以及 audit-events 403/跨租户 404 不误写自审计；nightly/manual performance smoke 还观察这些拒绝路径的 p99。
- 真实数据路径：integration suite 使用真实 PostgreSQL/Redis/Testcontainers/FastAPI ASGI app；新增测试不 mock repository 或 database session。
- 数据保留/审计路径：retention 真实 Postgres 测试覆盖超期终态 Run 硬删与 result/artifact/event 级联；single/batch cancel API 覆盖真实 DB 终态、Redis status event `previous` 和 audit before/after，batch retry 覆盖真实 DB 状态和 audit 行写入；project、project member、pipeline、credentials、environments、notification rules、schedule API 与 schedule worker 自动触发已补真实 DB audit before/after 或 `run.trigger` 断言，项目 `git_url` userinfo、pipeline 复杂配置密钥、凭据明文、环境变量、通知 channel/template 不落审计状态。
- 日志归档补偿与回看：归档失败登记真实 Redis retry set 和失败 TTL，并由 required integration 通过 worker cron 入口验证重试成功、marker 清理、成功 TTL 与 JSONL 读回；SSE `Last-Event-ID` 断点续传由真实 JWT、真实 ticket、PostgreSQL/RBAC 与 Redis Stream 集成测试覆盖；归档 JSONL 读回 API 由真实 DB/RBAC/API 集成测试覆盖，并验证分页窗口、对象缺失 404、API token `run.read` scope，以及跨租户 Run ID 与随机 UUID 一致 404；`project.read` token 被拒绝时不会触碰 S3；nightly/manual performance smoke 进一步覆盖跨租户 archived logs 拒绝路径 p99，且拒绝路径不触发 S3 get_object。
- Artifact 风险：环境级产物大小/数量限制传入 worker 并在上传前强制校验，真实 DB 集成测试证明被跳过产物不会写 Artifact 行；S3 上传失败路径用真实 ArtifactRepository/PostgreSQL 验证不会留下孤儿 Artifact 行；`results/` 递归上传与 Allure 目录文件落库也有真实 DB/S3 证据；artifact 列表元数据到下载链接的真实 JWT/RBAC/API token scope/DB 行、bucket/key/TTL 参数已进入 required integration，`project.read` token 不能枚举 artifact 名称/路径，也不能生成预签名 URL，`run.read` token 才能查看列表或下载；tenant A 的真实 `run.read` API token 请求 tenant B artifact 与随机 UUID 返回一致 404 且不会调用 S3 presign；nightly/manual performance smoke 进一步把 artifact 列表拒绝路径不返回名称/路径、跨租户拒绝下载不触发 presign 纳入 p99 趋势。
- 真实 worker 黑盒：nightly/manual 会启动 compose API/worker/MinIO；external-stack smoke 覆盖真实 API 触发后 worker 执行容器、多 artifact 列表、逐个预签名下载链接、真实 MinIO 对象内容下载、artifact 元数据/下载内容/归档日志不泄露 worker 注入密钥、归档日志 API、worker_lost 后自动 retry 再完成、停掉 high/low worker 后 high/low priority run 不被 medium worker 误消费、启动匹配 worker 后完成，以及 credentialed clone 失败与 setup script 非 0 不误 retry/不落 artifact/不泄密的队列和失败边界链路。
- Worker 重试：真实 DB/Redis 集成测试覆盖 `execute_run` 基础设施异常路径、真实 `RunExecutor` setup 阶段 Docker daemon `ConnectionError` retry 边界、setup script 非 0 与 git clone 失败不误 retry，以及 `reclaim_resources` worker_lost 路径，验证原 Run failed、Redis status event `previous=running`、orphan cleanup、retry Run 落库并入队；clone 失败写回错误会脱敏 userinfo/token；external-stack 进一步扰动 medium worker，验证 reclaimer cron 创建 retry Run，重启 worker 后 retry Run 产出 artifact、可下载 JUnit 内容与归档日志，并验证 credentialed clone failure / setup exit 1 不创建 attempt=2 retry Run。
- Worker 队列：required integration 覆盖 `/api/v1/runs` 真实触发后，manual priority 0/1/2 经 FairScheduler 写入 `queue:high` / `queue:medium` / `queue:low`、`arq_job_id` 和 `enqueued_at` 到 PostgreSQL；nightly/manual external-stack 会停掉 high/low worker 后触发 priority 0/2 run，证明 medium worker 不会误消费这些队列，并在启动匹配 worker 后验证真实执行、artifact 下载和归档日志回看；ARQ 只在 required integration 中以 test double 代替外部队列服务，不替代 DB/API/RBAC 链路。
- 资源终止：required integration 通过 RunExecutor + 真实 PostgreSQL/Redis 验证 backend 返回 `oom_killed=True` 或 `timed_out=True` 时，Run 终态落 `timeout`、summary 写入、Redis status/event 进入 `timeout`，并保留 run log 收尾证据；真实 Docker OOMKilled 语义仍由 opt-in heavy Docker 在稳定 Linux 环境验证。
- Webhook/schedule 失败路径：required integration 断言 schedule worker 成功触发与 enqueue conflict 都会以系统身份写 `run.trigger` AuditEvent；schedule pipeline 不可见时不会创建 Run，会更新 `last_error` 并写 `schedule_skipped_missing_pipeline` AuditEvent；缺失 webhook HMAC 签名不会创建 Run；签名成功后写入真实 Run 与 `run.trigger` AuditEvent，且 payload 不能覆盖 `git_url` / `credential_id` / `shallow_clone` / `default_branch` 等保留执行配置；filtered/duplicate 这种不创建 Run 的分支会写项目级 `webhook.filtered` / `webhook.duplicate` AuditEvent，且 after_state 不落 repo URL、dedup_key 或任意 metadata；archived project、missing pipeline/environment、enqueue conflict、cross-project pipeline 也不会静默写错真实 DB 状态。
- CI 稳定性：后端 ruff 与单测覆盖率是同一门禁；PR/push 必跑 required integration；heavy Docker/worker integration 拆到 nightly/manual；heavy Docker fixture 先复用本地镜像、缺镜像才 pull，避免 registry/network 抖动制造误 skip；PR E2E 保留轻量 UI 冒烟，nightly 固定跑真实 E2E 主路径，完整真实 E2E 留给手动 workflow。
- 非功能 smoke：nightly/manual 覆盖读 API、写 API、触发入队 SLO、取消 API p99、Redis 日志写读、SSE 实时日志推送 < 2s、归档日志读回 API（小样本、1500 行大对象分页与跨租户拒绝不读 S3）、artifact 列表元数据 API、artifact 列表拒绝不返回元数据、artifact 下载链接 API（单次、burst 与跨租户拒绝不 presign）、audit events 查询 API 与成功自审计写入、audit-events 拒绝查询不写自审计、执行摘要生成 < 3s 趋势哨兵，并在失败时输出 p50/p99/max 摘要；不把性能环境抖动放进 PR 硬门禁。

## Mock 使用口径

当前测试中仍然有 mock，但用途是分层隔离，不是替代真实数据功能验证：

- 单元测试里的 mock 用来锁定分支、错误处理、外部服务失败和边界输入，适合快速定位逻辑回归。
- `auth-flow.spec.ts` 的 E2E mock API 是前端登录/导航冒烟，不能作为后端数据正确性的证据。
- 真实后端数据正确性由 integration suite 承担：真实 PostgreSQL schema、真实事务/唯一约束/soft-delete、真实 FastAPI 路由、真实 JWT/API token、真实 audit/event 写入。
- 部分 integration fixture 会 override 当前用户以便稳定覆盖 RBAC/API 行为；当前真实 JWT/API token、artifact 下载、归档日志读回和 API token 审计断言均不 override current-user，补上“鉴权是否真的能走通数据库、审计是否真的写入且不泄密”的证据。
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
RUN_INTEGRATION_TESTS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration -q -p no:cacheprovider --tb=short --durations=20
```

当前结果：

- integration 收集：155 tests
- PR/push 必跑 required integration：123 passed, 32 deselected
- 完整 local integration（未启动外部 API/worker 栈）：131 passed, 24 skipped
- performance smoke opt-in：17 passed
- skipped 来自 macOS Docker Desktop OOMKilled 平台语义、未设置 `RUN_PERFORMANCE_TESTS=1` 的 performance smoke，以及本地未启动 external stack；CI nightly/manual 会主动启动 external stack，业务断言失败不会被 skip 或 retry 掩盖

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

- 数据库 repositories 已覆盖 Project/Pipeline/Run、Audit/User、API token、TestResult、Artifact 的真实 Postgres 行为，并覆盖分页、唯一约束 rollback、soft-delete 和 terminal run retention cascade；真实 API token 创建/撤销还断言 AuditEvent before/after 不包含 full token、secret 或 secret_hash；audit-events 成功列表会写 `audit_events.list` 自审计，nightly/manual smoke 还验证 p99 采样下成功查询会持续写入对应自审计行，member/viewer 403 与跨租户资源过滤 404 不会误写自审计行，且拒绝路径 p99 已进入 nightly/manual smoke；retention 已覆盖普通超期终态 Run 与 `cancelled/timeout`。
- auth 安全审计故障已补 required integration：login/refresh/logout 的失败审计写入异常不会把预期 401/204 变成 500；refresh token revoke Redis 抖动会记录 `token_revoke_failed` 并继续签发新 access token；register/refresh/logout 审计防泄密已补真实 JWT/cookie/API/PostgreSQL 证据，证明 password、access token、旧/新 refresh token 不进入 AuditEvent before/after；对应日志上下文改用 logging `extra`，避免告警路径因非法 kwargs 二次失败。
- 环境变量加密已补 API/DB/migration/worker 证据：API create/fetch/update 路径会以 AES-256-GCM envelope 存入 `Environment.env_vars` JSONB，AAD 错配会返回 500 并写 `environment.env_vars_decrypt_failed` audit，migration `007` 会加密既有明文并跳过已加密 envelope；nightly/manual external-stack worker smoke 会验证加密 env var 经 worker 解密后注入真实执行容器，且该密钥不会出现在 artifact 列表元数据、预签名下载内容或归档日志回看响应中。
- single run cancel 已补 API 写入后真实 DB 终态、Redis status event `previous=running` 和 audit before/after 验证，并进入 nightly/manual 取消 API p99 smoke；batch cancel/retry 已补 API 写入后真实 DB 状态、cancel Redis status event 和 audit 行验证。
- OOM/timeout 资源终止已补 RunExecutor + 真实 DB/Redis required integration，覆盖 `oom_killed=True` 和 `timed_out=True` 两条 backend 结果写成 Run `timeout` 终态、Redis `timeout` status event 和 run log 收尾；内部 `disk_mb` → `ResourceLimits.disk_bytes` → Docker `StorageOpt.size` 已有单元证据，但 API 暴露磁盘配额和资源用量记录仍是 F-PL-03 剩余缺口。
- project/project member/pipeline/credentials/environments/notification rules 已补 API 写入后的真实 DB 审计状态检查：项目 `git_url` userinfo、pipeline stages/trigger_config 复杂配置里的 token/password/secret/credential/Authorization、凭据明文、环境变量值、通知 channel 地址/webhook URL 和模板正文不进入 audit before/after；project、pipeline、project member、notification、schedule delete 已补删除前状态快照。
- log archive 失败已补真实 Redis retry set、失败/成功 TTL 与 worker cron 重试路径；归档日志读回 API 已补真实 DB/RBAC/API 集成测试，覆盖默认页、分页窗口、S3 对象缺失 404 ErrorResponse、API token `run.read` scope，以及跨租户 archived-log Run ID 与随机 UUID 一致 404；`project.read` token 被拒绝时不会读取 S3；nightly/manual performance smoke 额外覆盖跨租户 archived logs 拒绝 p99，且拒绝路径不触发 S3 get_object；artifact 上传失败已补真实 PostgreSQL 断言，证明 S3 put 失败后不会写孤儿 Artifact 行；artifact 列表元数据和下载链接已补真实 JWT/RBAC/API token scope/API/DB 行到预签名 bucket/key/TTL 的 required integration，`project.read` token 不能枚举 artifact 名称/路径或换取 URL，并覆盖真实 API token 跨租户 404 收敛；nightly/manual performance smoke 额外覆盖 artifact 列表拒绝不返回名称/路径、跨租户 artifact 拒绝下载 p99，且拒绝下载路径不触发 S3 presign；external-stack worker smoke 与 worker_lost retry 进一步证明真实 worker 完成后可经 API 回看归档日志，并可经预签名 URL 下载真实 JUnit、HTML、log、Allure artifact 内容，且 worker 注入密钥不会从 artifact 元数据、下载内容或 archived logs 泄出；前端 run detail 已接入终态 run 的归档日志回看，并用 Playwright 真实 DB+S3 数据覆盖日志搜索与 HTML artifact 预览。
- manual priority 0/1/2 已补真实 API/DB 入队元数据测试，证明 `/api/v1/runs` 写入后会经 FairScheduler 把 queue name、ARQ job id 和 enqueued_at 持久化到 Run 行；nightly/manual external-stack 进一步覆盖 high/low worker 停止时 priority 0/2 run 保持 queued、medium worker 不误消费，启动匹配 worker 后真实执行并完成 artifact/归档日志闭环；worker_lost reclaimer 已补真实 DB/Redis status event 与 retry Run 入队证据；真实 `RunExecutor` 已覆盖 setup Docker daemon 基础设施错误会进入 worker retry，setup script 非 0 与 git clone 失败不会误 retry，clone 错误会脱敏；external-stack 已把 credentialed clone failure 和 setup exit 1 扩成真实 API/worker/MinIO 黑盒证据。
- Webhook/API/schedule worker 新增真实 DB 失败路径后，schedule worker 自动触发 `run.trigger` audit、schedule missing-pipeline skip audit、缺失 HMAC 签名、签名成功、保留 metadata 防覆盖、webhook `run.trigger` audit、filtered/duplicate 决策 audit、project archived、pipeline/environment missing、cross-project pipeline、enqueue conflict 已进 required integration。
- 分支覆盖率仍低于语句覆盖率：主要来自依赖初始化分支、外部 SDK/worker 边界和少量异常恢复路径。
- warnings 治理：项目内 SQLAlchemy overlap、Redis pubsub `close()`、SSE AsyncMock、httpx cookies、JWT key length warning 均已清理；testcontainers 第三方弃用提示已在 `pyproject.toml` 精确过滤并登记。
- PR E2E 是 mock API UI 冒烟，不证明真实后端；真实后端 E2E 已有 `real-login-flow`、`real-run-trigger`、`special-regressions`，其中 `special-regressions` 覆盖归档日志回看与 artifact 预览，当前 CI 在 nightly 固定执行这些真实主路径，manual 执行全量。

## 后续优先级

1. 自动重试已补 API-facing `max_attempts`、`retry_on`、waiting retry run、execute_run 基础设施异常、真实 `RunExecutor` setup Docker daemon retry 边界、setup/clone 业务失败不误 retry、worker_lost callback 路径、external-stack worker_lost 黑盒，以及 external-stack clone/setup 业务失败不 retry 黑盒；后续如要继续提高信心，可把 Docker daemon 扰动扩到 nightly/manual external-stack 黑盒。
2. 严格产品 SLO 与完整性能压测仍需专项环境；当前 smoke 已覆盖触发入队 < 5s、取消 API p99、SSE 实时日志推送 < 2s、归档日志 1500 行大对象分页回看、归档日志拒绝 no-S3-read、artifact 下载链接单次、burst 与拒绝 no-presign、audit events 查询 API 与成功自审计写入、执行摘要生成 < 3s 趋势哨兵并输出失败摘要。
3. 通知更高级产品能力仍待补：OR 条件、连续失败次数、每渠道模板、项目名/失败用例变量；本轮已补真实 DB delivery、模板失败、发送失败与幂等。
4. 审计写入覆盖下一步应按高风险资源继续外扩到尚未进入业务矩阵的写路径，重点检查“该写的 before/after 是否完整”和“敏感字段是否脱敏”，而不是只检查 action 名存在。
5. 后续提升 coverage 门槛应继续依赖真实风险路径，而不是为百分比增加无行为断言。
