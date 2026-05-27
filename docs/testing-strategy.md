# 测试分层、风险矩阵与质量运营

更新日期：2026-05-27

## 分层口径

| 层级 | CI 入口 | 证明什么 | 不证明什么 |
| --- | --- | --- | --- |
| Unit | `backend-test` 跑 `tests/unit` + coverage | 分支逻辑、错误处理、权限 helper、worker/service 小闭环；mock 用于隔离外部系统和制造失败分支 | 真实数据库约束、跨请求事务、Redis/Docker/S3/SMTP 的真实可用性 |
| Required integration | `backend-integration-test` 在 PR/push 跑 `tests/integration -m "not heavy_docker and not external_stack"` | 真实 PostgreSQL/Redis/Testcontainers、FastAPI 路由、repository 约束、API 写入后的 DB 状态、RBAC/租户隔离 | Docker 容器执行、外部 API+worker compose 栈、平台相关 OOM 语义 |
| Heavy Docker integration | nightly/manual 跑 `tests/integration -m "heavy_docker and not external_stack"` | worker/container/cancel/state visibility 等需要真实 Docker 镜像和容器生命周期的链路 | 单独启动的 API/worker compose 栈；macOS/GitHub Actions 不稳定的 OOMKilled 语义默认不作为 PR 门禁 |
| External-stack integration | nightly/manual 跑 `tests/integration -m "external_stack"` | 已启动 API/worker compose 栈时的真实 worker 黑盒链路 | CI 未启动 compose API/worker 时会跳过，不能替代 required integration |
| E2E | PR 跑 `auth-flow.spec.ts`，manual 跑完整 Playwright | 浏览器登录/权限/导航冒烟；manual 覆盖创建项目、触发 run、查看 result/artifact | PR 级 `auth-flow` 是 UI mock 冒烟，不作为后端真实数据正确性的证据 |

## 稳定性标准

- 可重复：测试数据使用唯一 slug/name/UUID，不依赖固定执行顺序。
- 顺序无关：integration 通过 fixture 初始化真实 schema 和 seed 数据，测试间不共享可变业务状态。
- 失败日志清楚：CI pytest 使用 `--tb=short --durations=20`，Docker image pull 在 heavy lane 有 3 次重试并在最终失败时报错。
- 数据隔离：真实 DB 测试必须断言 tenant/project 过滤、soft-delete 隐藏、唯一约束 rollback 后 session 可恢复。
- 不掩盖真实失败：仅把 Docker daemon/registry/API stack/OOM 平台语义这类前置条件缺失记为 skip；业务断言失败仍然失败。

## 业务风险矩阵

| 风险面 | 当前证据 | 状态 |
| --- | --- | --- |
| RBAC：tenant role、project role、platform admin | audit events、cross-tenant API、SSE 403/404、真实 JWT/API token integration | 已覆盖主干；API token scope 已验证存储/认证/撤销，路由级细粒度 enforcement 属于行为变更，单独列为后续产品/安全决策 |
| 数据隔离：跨 tenant/project、soft-delete、随机 UUID | `test_cross_tenant_isolation.py`、repository/API 真实 DB 测试、artifact/result 隐藏测试 | 已作为 PR integration 门禁 |
| Repository：Audit/User/Artifact/TestResult/Run 查询、分页、唯一约束、级联/retention | `test_real_repository_matrix.py`、`test_real_auth_results_artifacts.py`、`test_real_db_persistence.py` | 已补真实 Postgres 直测 |
| API 写入后的真实 DB 状态 | credentials、environments、notification rules、runs、schedules、auth/token 链路 | 已补 required integration |
| Worker/queue 状态机 | 真实 PG repository 状态机、run claim、cancel、state visibility、executor/task 单测、heavy Docker cancel | 已覆盖 queued/preparing/running/collecting/done/failed/cancelled/timeout；worker 黑盒链路走 nightly/manual |
| Webhook/schedule 幂等与失败路径 | branch filter、dedup、silent window、terminal same commit、cross-tenant 404、archived project、missing pipeline/environment、enqueue conflict | Webhook/API/schedule worker 主风险已进 required integration；schedule pipeline missing 仍由 unit 覆盖，因为真实 DB FK 会把硬删除变成级联，软删除路径不等价于真实缺行 |
| 三条关键 E2E 冒烟 | 登录/权限、创建项目到触发 run、查看 run/result/artifact | 已有 Playwright 用例；PR 只跑轻量 auth-flow，完整链路 manual |

## Warning 登记

| Warning | 来源 | 处置 |
| --- | --- | --- |
| `testcontainers.redis.wait_container_is_ready` deprecation | 第三方 testcontainers Redis 模块 import | 登记保留，等上游或后续 testcontainers wait strategy 迁移 |
| SQLAlchemy `Run.project` relationship overlap | ORM mapper 配置 | 登记保留；修复会触碰模型关系配置，需单独评估业务行为不变性 |
| Redis pubsub `close()` deprecation | heavy cancel integration 触发 `engine.cancel` 关闭 pubsub | 登记保留；修复应作为小型兼容性变更单独验证 |

已清理项：

- SSE 单测的 `AsyncMockMixin._execute_mock_call was never awaited`：改为带同步 `pipeline()` 的轻量 Redis fake。
- httpx per-request `cookies=` deprecation：改为在 `AsyncClient.cookies` 上设置 refresh cookie。
- JWT wrong-secret 测试的 31 字节 HMAC key warning：换成 32 字节测试密钥。

## Flaky 与回归机制

- 新 flaky 先登记：记录测试名、失败环境、复现命令、最近失败日志、owner 和下一步。
- 只允许因外部前置条件 skip：Docker daemon 不可用、registry 拉取失败、external stack 未启动、平台 OOM 语义不稳定。
- 不引入测试重跑来掩盖业务失败；如需 retry，只用于 Docker image pull 这类外部前置条件。
- 每个线上/测试发现缺陷都要补一条能失败再变绿的回归测试，优先放在 required integration；只有纯分支逻辑才放 unit。
- Coverage 门槛按真实风险路径逐步提高；不得为了百分比添加无行为断言或重 mock 覆盖。
