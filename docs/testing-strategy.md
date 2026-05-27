# 测试分层、风险矩阵与质量运营

更新日期：2026-05-28

## 分层口径

| 层级 | CI 入口 | 证明什么 | 不证明什么 |
| --- | --- | --- | --- |
| Unit | `backend-test` 跑 `tests/unit` + coverage | 分支逻辑、错误处理、权限 helper、worker/service 小闭环；mock 用于隔离外部系统和制造失败分支 | 真实数据库约束、跨请求事务、Redis/Docker/S3/SMTP 的真实可用性 |
| Required integration | `backend-integration-test` 在 PR/push 跑 `tests/integration -m "not heavy_docker and not external_stack and not performance"` | 真实 PostgreSQL/Redis/Testcontainers、FastAPI 路由、repository 约束、API 写入后的 DB 状态、RBAC/租户隔离、auth 失败审计 outage 不变成 500、refresh revoke Redis blip 不阻断 token 轮换、worker 入口异常重试、manual priority 到 high/medium/low worker queue 元数据落库、单 run/batch cancel 的 Redis status event 与 audit before/after、schedule worker 自动触发 audit 与 missing-pipeline skip audit、SSE `Last-Event-ID` 断点续传、归档失败真实 Redis retry marker/worker cron 重试、归档日志读回分页/对象缺失、API token `run.read` scope 和跨租户 404、artifact 限制落库、S3 上传失败无孤儿 Artifact 行、artifact 列表元数据和下载链接 bucket/key/TTL、artifact API token `run.read` scope 与跨租户 404 收敛、签名 webhook 的 HMAC/branch filter/dedup/`run.trigger` audit、filtered/duplicate 决策 audit、保留 metadata 保护 | Docker 容器执行、外部 API+worker compose 栈、平台相关 OOM 语义与 performance smoke |
| Heavy Docker integration | nightly/manual 跑 `tests/integration -m "heavy_docker and not external_stack"` | worker/container/cancel/state visibility 等需要真实 Docker 镜像和容器生命周期的链路 | 单独启动的 API/worker compose 栈；macOS/GitHub Actions 不稳定的 OOMKilled 语义默认不作为 PR 门禁 |
| External-stack integration | nightly/manual 先启动 compose API/worker/MinIO，再跑 `tests/integration -m "external_stack"` | 真实 API 触发后由 compose worker 消费队列、执行容器、写回终态；验证真实 worker 后的 artifact 列表、预签名下载 URL 与对象内容、归档日志 API，以及 worker_lost 后自动 retry 再完成的黑盒链路 | 不是 PR 门禁；不替代 required integration 的快速 DB/API/RBAC 覆盖；clone/setup/Docker daemon 等其它基础设施失败重试仍由真实 DB/worker 入口测试覆盖 |
| Performance smoke | nightly/manual 跑 `tests/integration/test_performance_smoke.py -m performance` | 读 API、写 API、触发入队 SLO、取消 API p99、Redis 日志写读、SSE 实时日志推送 < 2s、归档日志读回 API、artifact 列表元数据 API、artifact 下载链接 API（单次与 burst）、audit events 查询 API、执行摘要生成 < 3s 的趋势哨兵；失败时输出 p50/p99/max 摘要 | 不是 PR 阻塞性 SLO 证明；发现退化后升格专项压测 |
| E2E | PR 跑 `auth-flow.spec.ts`，nightly 固定跑 `real-login-flow` / `real-run-trigger` / `special-regressions`，manual 跑完整 Playwright | 浏览器登录/权限/导航冒烟；nightly/manual 覆盖创建项目、触发 run、查看 result/artifact、归档日志回看、HTML artifact 预览、特殊回归 | PR 级 `auth-flow` 是 UI mock 冒烟，不作为后端真实数据正确性的证据 |

## 稳定性标准

- 可重复：测试数据使用唯一 slug/name/UUID，不依赖固定执行顺序。
- 顺序无关：integration 通过 fixture 初始化真实 schema 和 seed 数据，测试间不共享可变业务状态。
- 失败日志清楚：CI pytest 使用 `--tb=short --durations=20`，Docker image pull 在 heavy lane 有 3 次重试并在最终失败时报错。
- 数据隔离：真实 DB 测试必须断言 tenant/project 过滤、soft-delete 隐藏、唯一约束 rollback 后 session 可恢复。
- 不掩盖真实失败：仅把 Docker daemon/registry/API stack/OOM 平台语义这类前置条件缺失记为 skip；业务断言失败仍然失败。

## 业务风险矩阵

| 风险面 | 当前证据 | 状态 |
| --- | --- | --- |
| RBAC：tenant role、project role、platform admin、API token scope | audit events、cross-tenant API、SSE 403/404、SSE ticket + `Last-Event-ID` 真实续传、artifact list/download 与 archived logs 的 `run.read` scope、真实 JWT/API token integration、auth 失败审计 outage 与 refresh revoke Redis blip 回归、API token create/revoke 审计状态不泄露 token secret/hash | 已覆盖主干；API token scope 已补真实路由矩阵，只读/错误/空 scope 都会被门禁，artifact 元数据列表、预签名 URL 和归档日志读回都不能由 `project.read` token 换取，tenant A `run.read` token 不能枚举 tenant B artifact；login/refresh/logout 在审计写入异常下不把 401/204 变成 500，refresh revoke Redis 抖动不阻断 token 轮换；API token 创建/撤销审计只记录 name/scopes 等可追溯元数据 |
| 数据隔离：跨 tenant/project、soft-delete、随机 UUID | `test_cross_tenant_isolation.py`、repository/API 真实 DB 测试、artifact/result/归档日志隐藏测试、真实 API token 跨租户 artifact 下载 404 收敛 | 已作为 PR integration 门禁；Member/Viewer 项目级路由先归一 404 再做 RBAC；artifact 下载对跨租户真实 ID 与随机 UUID 不暴露差异且不调用 S3 presign |
| Repository：Audit/User/Artifact/TestResult/Run 查询、分页、唯一约束、级联/retention | `test_real_repository_matrix.py`、`test_real_auth_results_artifacts.py`、`test_real_db_persistence.py` | 已补真实 Postgres 直测；retention 覆盖超期 `done/failed/cancelled/timeout` 与 result/artifact/event 级联 |
| API 写入后的真实 DB 状态 | projects、project members、pipelines、credentials、environments、notification rules、runs、schedules、auth/token、single/batch cancel audit 链路、batch retry audit 链路 | 已补 required integration；项目 `git_url` userinfo、pipeline 复杂配置密钥、凭据明文、环境变量值、通知 channel/webhook/template 不落 audit before/after，project/pipeline/member/notification/schedule delete 和 run cancel 有删除/取消前快照 |
| Worker/queue 状态机与产物链路 | 真实 PG repository 状态机、run claim、cancel、state visibility、execute_run 基础设施异常重试、RunExecutor OOM/timeout 资源终止写真实 DB/Redis、manual priority 到 `queue:high/medium/low` 的真实 API/DB 入队元数据、executor/task 单测、cancel API 真实 Redis status event `previous` 与 p99 smoke、artifact size/count/recursive upload、S3 上传失败无孤儿 DB 行、artifact 列表元数据、下载链接 bucket/key/TTL/API token scope/跨租户 404 真实 DB/API 测试、归档失败真实 Redis retry marker/TTL + worker cron 重试、归档日志默认页/分页/缺失对象/API token scope/跨租户 404 API 测试、heavy Docker cancel/OOM、compose high/medium/low worker 配置、external-stack worker smoke 和 worker_lost retry 黑盒 | 已覆盖 queued/preparing/running/collecting/done/failed/cancelled/timeout；priority+FIFO 排序、manual priority 队列元数据、worker retry 落库、`oom_killed` / `timed_out` backend 结果到 Run `timeout` 终态和 Redis status event、artifact 递归落库、失败上传不落库、归档失败补偿、cancel 控制面的 Redis previous/audit 前后态、API p99 趋势和 artifact 列表/下载链接参数有真实 DB/API/RBAC/Redis 测试；artifact 元数据列表、预签名 URL 与归档日志读回都需要 `run.read` scope，跨租户 artifact ID 与随机 ID 同样 404；nightly/manual 真实外部栈覆盖 worker 解密环境变量后注入容器、产物内容下载、归档日志读回和 worker_lost 后自动 retry |
| Webhook/schedule 幂等与失败路径 | schedule worker 成功触发与 enqueue conflict 的系统 `run.trigger` audit、schedule missing pipeline 的系统 skip audit、HMAC 缺失/成功签名、branch filter、dedup、filtered/duplicate 决策 audit、terminal same commit、cross-tenant 404、archived project、missing pipeline/environment、enqueue conflict、保留 metadata 防覆盖 | Webhook/API/schedule worker 主风险已进 required integration；filtered/duplicate 和 schedule missing-pipeline 这类不创建 Run 的分支已有 AuditEvent 且 after_state 只含非敏感决策/排障字段 |
| 三条关键 E2E 冒烟 | 登录/权限、创建项目到触发 run、查看 run/result/artifact/归档日志 | 已有 Playwright 用例；`special-regressions` 已覆盖真实 DB+S3 准备后的归档日志回放、搜索和 HTML artifact 预览；PR 只跑轻量 auth-flow，nightly 固定跑真实链路，完整链路 manual |

## Warning 登记

| Warning | 来源 | Owner / 截止条件 | 状态 |
| --- | --- | --- | --- |
| `testcontainers.redis.wait_container_is_ready` deprecation | 第三方 testcontainers Redis 模块 import | 测试平台维护者；2026-06-17 前在依赖升级窗口评估是否可去掉精确 filter，或迁移 Redis fixture 到结构化 wait strategy | 已登记并在 `pyproject.toml` 精确过滤第三方 warning，避免 CI 噪音掩盖真实失败 |
| SQLAlchemy `Run.project` relationship overlap | ORM mapper 配置 | 后端维护者；2026-05-27 已完成，后续若改 Run/Project/Pipeline 关系需保留 mapper 无 warning 验证 | 已清理：`Run.project` 明示 `overlaps`，integration mapper 配置不再产生该 warning |
| Redis pubsub `close()` deprecation | heavy cancel integration 触发 `engine.cancel` 关闭 pubsub | 后端维护者；2026-05-27 已完成，后续 Redis client 升级需保留 `aclose()` 优先路径 | 已清理：取消监听器优先调用 `pubsub.aclose()`，单测锁定该路径 |

已清理项：

- SSE 单测的 `AsyncMockMixin._execute_mock_call was never awaited`：改为带同步 `pipeline()` 的轻量 Redis fake。
- httpx per-request `cookies=` deprecation：改为在 `AsyncClient.cookies` 上设置 refresh cookie。
- JWT wrong-secret 测试的 31 字节 HMAC key warning：换成 32 字节测试密钥。

## Flaky 与回归机制

- 台账入口：`docs/testing-quality-ops.md`。新 flaky、线上/测试缺陷回归、性能/nonfunctional smoke 都在该文件按表登记。
- 新 flaky 先登记：记录测试名、失败环境、复现命令、最近失败日志、owner 和下一步。
- 只允许因外部前置条件 skip：Docker daemon 不可用、registry 拉取失败、本地未启动 external stack、平台 OOM 语义不稳定；CI nightly/manual 会主动启动 external stack。
- 不引入测试重跑来掩盖业务失败；如需 retry，只用于 Docker image pull 这类外部前置条件。
- 每个线上/测试发现缺陷都要补一条能失败再变绿的回归测试，优先放在 required integration；只有纯分支逻辑才放 unit。
- Coverage 门槛按真实风险路径逐步提高；不得为了百分比添加无行为断言或重 mock 覆盖。
- 后端静态检查由 CI `backend-test` 执行 `ruff check src tests`，和单元 coverage 门禁一起阻止新增 lint 债务。
