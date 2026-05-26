# QA 自动化执行平台 — 架构设计文档

## 1. 架构风格

**模块化单体 + 插件架构**

选择理由：
- 团队 < 5 人，微服务的运维复杂度不值得
- 单一部署单元，用目录与 import 边界约束耦合
- 执行引擎（Worker）可独立水平扩展
- 插件系统提供扩展点，核心不膨胀

演进路径：模块化单体 → 拆分 Worker 为独立服务 → 按需拆分其他模块

---

## 2. 分层架构

### 2.1 源码分层

```
src/qaplatform/
├── domain/       # 领域层：纯业务规则，不依赖框架和 IO
├── api/          # 接口层：HTTP 路由、认证、请求/响应 schema
├── engine/       # 执行引擎：容器编排、日志流、执行生命周期
├── infra/        # 基础设施：数据库、缓存、对象存储的具体实现
├── plugins/      # 插件系统：Protocol 定义 + 内置插件
├── worker/       # 异步任务：arq 任务定义、调度器、心跳
├── config.py     # 配置加载
└── main.py       # 应用入口
```

### 2.2 依赖规则

```
api → domain, engine, infra, plugins
engine → domain, infra, plugins
worker → domain, engine, infra, plugins
infra → domain
plugins → domain
domain → (无外部依赖)
```

**硬性约束：**
- `domain` 不得 import 框架级依赖（FastAPI、SQLAlchemy、Redis 等）；Pydantic 作为值对象/数据校验库、croniter 作为纯计算库允许使用
- `domain` 不得执行 IO 操作
- `infra` 是唯一接触数据库/缓存/存储的层
- `api` 不得直接操作数据库，必须通过 `infra.repositories`

**当前偏差（待技术债修复）：**
- `engine/executor.py` 为上报终态指标仍会局部 import `api.metrics.run_terminal_total`；目标是把指标定义迁到 `observability` / `infra` 外的中立模块，避免 engine 反向依赖 API。
- `engine/reclaim.py` 仍通过 worker 兼容 shim 引用 `worker._redact.redact_url_userinfo`；目标是直接使用 `engine.redact`，保留 worker shim 只服务旧调用方。
- `api/v1/admin.py`、`api/v1/analytics.py`、`api/v1/auth.py`、`api/v1/runs.py` 和 `api/deps.py` 仍存在直接 SQLAlchemy 查询；目标是把可复用查询下沉到 repositories / query service，逐步收敛到上面的分层规则。

---

## 3. 技术选型

| 组件 | 选型 | 决策理由 |
|------|------|----------|
| API 框架 | FastAPI | async 原生、自动 OpenAPI、Pydantic 校验 |
| 任务引擎 | arq | 轻量 async、比 Celery 简单；接口抽象可切换 |
| 数据库 | PostgreSQL 16 | JSONB、事务一致性、成熟生态 |
| 缓存/队列 | Redis 7 | arq broker + 缓存 + 实时日志流 |
| 对象存储 | S3 协议（MinIO 开发 / S3 生产） | 报告和产物存储 |
| 执行隔离 | Docker（当前）/ K8s Job（远期） | 统一容器接口，后端可切换 |
| 实时通信 | SSE | 单向推送足够、HTTP 原生、自动重连 |
| ORM | SQLAlchemy 2.0 async | 类型安全、async session |
| 迁移 | Alembic | SQLAlchemy 生态标配 |
| 可观测性 | Prometheus + structlog；OpenTelemetry 追踪待 T10 装配 | 指标 + 结构化日志；链路追踪为待办 |

---

## 4. 系统全景

```
┌─────────────────────────────────────────┐
│              Clients                     │
│   Web UI │ CLI │ CI/CD │ Webhook        │
└──────────────────┬──────────────────────┘
                   │ HTTPS
┌──────────────────▼──────────────────────┐
│           Reverse Proxy                  │
│         (Caddy / Nginx)                  │
└─────┬────────────────────────┬──────────┘
      │                        │
┌─────▼──────────┐    ┌───────▼──────────┐
│  API Server    │    │  Frontend SPA    │
│  (FastAPI)     │    │  (React)         │
│  • REST API    │    │  静态资源         │
│  • SSE Stream  │    └──────────────────┘
│  • OpenAPI     │
└──┬─────┬────┬──┘
   │     │    │
┌──▼──┐ ┌▼──┐ ┌▼─────┐
│ PG  │ │Redis│ │MinIO │
└─────┘ └─┬──┘ └──────┘
          │
   ┌──────▼──────┐
   │ Worker Pool │
   │ (arq)       │
   │  ↓          │
   │ Executor    │
   │ (Docker API)│
   └─────────────┘
```

---

## 5. 进程模型

| 进程 | 实例数 | 职责 |
|------|--------|------|
| api-server | 1-N（Uvicorn workers） | HTTP 请求、SSE 推送 |
| worker | 1-N（arq workers） | 异步任务执行 |
| scheduler | 1（单例，advisory lock 保证） | Cron 调度触发 |

---

## 6. 核心流程

### 6.1 测试执行流程

```
用户触发 (API/Cron/Webhook)
    │
    ▼
创建 Run (status: queued)
    │
    ▼
通过 FairScheduler 入队 Redis / arq
    │
    ▼
Worker 抢占 (queued → preparing)
    │
    ▼
克隆源码 (SourceProtocol)
    │
    ▼
启动容器执行 (status: running)
    │  ├── 实时日志 → Redis Stream → SSE 推送
    │  └── 心跳上报 (每 30s, TTL 90s)
    ▼
执行完成 (status: collecting)
    │
    ▼
收集结果 (CollectorProtocol → TestResult[])
    │
    ▼
上传产物 (S3)
    │
    ▼
写入摘要 (status: done/failed/timeout)
    │
    ▼
触发通知 (按规则)
```

当前资源与产物边界：Docker backend 已对 CPU / 内存设置容器限制，超时路径会走 SIGTERM → 30s → SIGKILL；但 `disk_bytes` 未进入 Docker HostConfig，OOM/timeout 的资源用量记录也未形成验收闭环。`engine/executor.py` 只扫描工作目录 `results/` 下的直接文件并写入 S3/Artifact；目录型 Allure HTML report、递归资源目录上传，以及环境级 `max_artifact_size_mb` / `max_artifacts_count` 传递到 worker 并在上传侧强制校验仍需补齐。

当前 collector 边界：Pipeline 的 stage `plugin` 可以选择测试运行器，但结果收集器还不是 pipeline 级配置项；`RunExecutor.execute()` 当前固定调用 JUnit collector。PRD F-PL-01 中“配置结果收集器”的验收需后续补实现，或由 maintainer 决定把 JUnit-only 写成正式产品限制。

当前队列边界：`worker/scheduler.py` 会按 Run `priority` 把任务写入 `queue:high` / `queue:medium` / `queue:low`，并在入队前执行全局并发与单项目并发配额；`RunRepository.find_waiting()` 对等待队列按 `priority, created_at` 排序。部署侧当前默认 `WorkerSettings.queue_name=queue:medium`，`docker-compose.yml` 只启动一个未设置 `QAP_WORKER_QUEUE` 的 worker，因此 high/low 队列消费、高优先级插队与同优先级 FIFO 仍需补配置和端到端测试后才能视为 F-EX-08 完整闭环。

### 6.2 状态机

```
queued → preparing → running → collecting → done
                                          → failed
                  → cancelled (任何阶段可取消)
                  → timeout
```

补充转换：`preparing` 可直接 → `failed`（如 git clone 失败）；`collecting` 可 → `timeout`（收集超时）；任何活跃状态可 → `cancelled`。

### 6.3 取消机制

- 用户请求取消 → 写入 `cancel_requested_at`
- Worker 执行循环中轮询该字段
- 检测到取消 → 向容器发送 SIGTERM → 等待优雅退出 → SIGKILL
- 标记状态为 `cancelled`

### 6.4 重试机制

当前 `main` 的自动重试仍是部分实现：

- `worker/tasks.py::_should_retry()` 只允许 `ConnectionError` / `TimeoutError` / `OSError` 这类基础设施异常按 pipeline `retry_policy` 重试；测试断言失败不重试。
- 当前 API schema 写入的 `RetryPolicyInput` 字段是 `max_attempts` / `retry_on` / `backoff_seconds` / `scope`，但 `_should_retry()` 读取的是 `max_retries`；按 API 创建的策略不会满足 worker 当前读取口径。
- `worker/tasks.py::_attempt_retry()` 会创建共享 `retry_group_id`、`attempt + 1`、`source_run_id` 的新 Run，并用指数退避 `_defer_by` 重新入队。
- `execute_run()` 只有在 `RunExecutor.execute()` 向外抛异常时才会调用 `_attempt_retry()`；但当前 `RunExecutor.execute()` 会捕获多数 clone / setup / Docker 执行异常，写 `FAILED` 后返回 `RunStatus.FAILED`，导致真实执行期基础设施失败不会进入重试路径。
- `engine/reclaim.py` 的 worker_lost 逻辑当前只把失联 worker 的 Run 标记为 `failed` 并清理 orphan container，不会自动创建 retry Run。

因此 F-EX-07 的 retry predicate、retry Run 创建和单元测试已存在，但端到端自动重试闭环仍需补齐。

### 6.5 Webhook 触发流程

```
外部系统 / Git 平台
    │
    ▼
POST /api/v1/webhooks/{project_id}/trigger
    │
    ├── 按 tenant + project_id 读取项目；跨租户返回 404
    ├── 如配置 webhook_secret，则验证 X-Webhook-Signature（HMAC-SHA256）
    ├── 校验当前用户对项目有 RUN_TRIGGER 权限
    ├── 选择项目首个 pipeline 与默认/首个 environment
    ├── 使用请求体 git_ref / git_sha / metadata 创建 webhook Run
    │
    ▼
按当前 FairScheduler 入队执行（见 §6.1 队列边界）
```

当前 `main` 尚未实现 Git 平台事件类型解析、按 repo URL 匹配项目、分支过滤和同 commit 去重；这些由 T06 Webhook 分支过滤 + 去重任务补齐。

### 6.6 Worker 故障恢复

```
Worker 正常运行时：每 30s 刷新 Redis heartbeat key（TTL 90s）

Worker 崩溃时：
    │
    ├── heartbeat key 过期（90s 无更新）
    │
    ▼
Scheduler 定期扫描（每 60s）
    │
    ├── 发现 status=running 但 heartbeat 已过期的 Run
    ├── 标记为 failed（reason: worker_lost）
    ├── 清理孤儿容器（通过 Docker label 匹配 run_id）
    ├── 当前不创建自动重试 Run
    │
    ▼
恢复完成
```

---

## 7. 插件系统

### 7.1 设计原则

- 基于 Python Protocol（结构化子类型），不要求继承
- Runtime checkable，支持动态加载
- 内置插件与第三方插件使用相同接口
- Runner 和 Collector 在 Worker 进程中调用，但测试代码本身在 Docker 容器内执行；Runner 负责构建容器执行命令和解析退出码，不直接运行测试代码

### 7.2 插件接口

```python
@runtime_checkable
class RunnerProtocol(Protocol):
    name: str
    def build_command(self, config: dict) -> str: ...
    async def run_tests(self, working_dir: Path, config: dict, env_vars: dict[str, str] | None = None) -> TestRunResult: ...

@runtime_checkable
class CollectorProtocol(Protocol):
    name: str
    async def collect(self, run_id: UUID, working_dir: Path) -> list[TestResultData]: ...

@runtime_checkable
class SourceProtocol(Protocol):
    name: str
    async def clone(self, url: str, ref: str, dest: Path) -> SourceRevision: ...
```

`SourceRevision` 包含 `path: Path`、`sha: str`、`ref: str`，用于填充 Run 的 `git_sha` 字段。

### 7.3 内置插件

| 插件 | 类型 | 说明 |
|------|------|------|
| git_source | Source | Git clone（支持 `https://` 与 SSH URL 形态校验，默认 `--depth 1` shallow clone）；私有 HTTPS token / SSH key 注入执行链路仍待补 |
| pytest_runner | Runner | 执行 pytest |
| jest_runner | Runner | 执行 Jest |
| playwright_runner | Runner | 执行 Playwright |
| go_test_runner | Runner | 执行 Go test |
| junit_collector | Collector | 解析 JUnit XML |

### 7.4 扩展点

未来可扩展的插件类型：
- 更多 Runner：Robot Framework、Cypress、自定义语言/框架 runner
- 更多 Collector：Allure JSON、TAP、自定义格式
- 通知渠道：作为插件注册新的通知后端

---

## 8. 数据架构

### 8.1 核心实体关系

```
Tenant 1──N AppUser
Tenant 1──N Project
Tenant 1──N Credential
AppUser 1──N ApiToken

Project 1──N Pipeline
Project 1──N Environment
Project 1──N Schedule
Project 1──N NotificationRule
Project 1──N ProjectMember

Pipeline N──1 Project
Run N──1 Pipeline
Run N──1 Environment
Run 1──N TestResult
Run 1──N Artifact
Run 1──N RunEvent
Run 1──N NotificationLog
```

### 8.2 关键实体字段

| 实体 | 核心字段 | 说明 |
|------|----------|------|
| Tenant | name, settings(JSONB) | 租户级配置（默认资源限制等） |
| AppUser | username, email, role, is_platform_admin, is_active, last_login_at | 登录用户与租户级角色 |
| ApiToken | token_id, secret_hash, scopes, expires_at, is_revoked | 机器访问 token，明文 token 不落库 |
| Project | slug, git_url, git_auth_method, credential_id, default_branch, settings(JSONB), status | 项目聚合根，settings 当前承载 `webhook_secret` 等嵌入配置；`allowed_branches` / `silent_windows` 为 T06 / T05 计划写入同一 JSONB 的字段；`credential_id` 已可绑定但执行侧 clone 使用待补 |
| Environment | base_image, setup_script, memory_mb, cpu_cores, resource_limits(JSONB), network_policy, env_vars(JSONB), cache_key | 执行环境；`memory_mb` / `cpu_cores` 是 ORM 离散列；API 暴露的 `max_artifact_size_mb` / `max_artifacts_count` 当前存放在 `resource_limits` JSONB 中，不是独立列；`env_vars` 当前仍为明文 JSONB，待 F-PL-02 加密 |
| Pipeline | stages(JSONB), selector(JSONB), trigger_config(JSONB), retry_policy(JSONB), timeout_seconds, enabled | 管道定义，使用 JSONB 支持多阶段执行与不同 runner；当前没有 collector 选择字段，执行器固定 JUnit collector |
| Schedule | cron_expr, timezone, quiet_windows(JSONB), next_run_at, last_run_at, last_error | 定时触发配置，当前已有 schedule 级 quiet window |
| Run | status, trigger_type, priority, git_ref, git_sha, retry_group_id, attempt, dedup_key, duration_ms, summary | 执行记录，status 为状态机核心 |
| TestResult | suite, name, status, duration_ms, error_message, stack_trace | 单条用例结果 |
| Artifact | type, name, storage_path, size_bytes, mime_type, expires_at | S3/MinIO 中的执行产物索引 |
| RunEvent | type, payload(JSONB), created_at | Run 生命周期事件 |
| NotificationRule | conditions(JSONB), channels(JSONB), template, enabled | 条件通知规则 |
| NotificationLog | run_id, rule_id, channel_type, status, error_message, sent_at | 通知发送记录 |
| ProjectMember | project_id, user_id, role | 项目级 RBAC 成员关系 |
| AuditEvent | action, resource_type, resource_id, before_state, after_state, ip_address, user_agent | `audit.event` schema 下的审计事件 |

### 8.3 关键设计决策

- **多租户**：聚合根（如 Project / Run）包含 `tenant_id` 并在查询层过滤；子资源通过聚合根间接隔离
- **软删除**：核心实体使用 `deleted_at` 软删除，保留审计轨迹
- **JSONB 灵活字段**：`stages`、`selector`、`trigger_config`、`settings` 等使用 JSONB，避免频繁 DDL
- **时间字段**：统一 UTC 存储，展示层转换时区

### 8.4 数据保留策略

- 执行记录保留配置默认 90 天；worker 已注册 `cleanup_old_runs` cron，但当前 `main` 的函数缺 `datetime/timezone` 导入会导致触发失败，且仓储方法只硬删已 soft-delete 的 `done/failed` Run，普通超期终态 Run、`cancelled/timeout`、artifact 对象清理和覆盖测试仍未闭环
- 审计日志默认保留配置为 1095 天（`QAP_RETENTION_AUDIT_DAYS`）；当前 `main` 只有配置项，尚未发现独立审计清理任务
- Run 日志归档到 S3；数据库执行记录当前目标是按保留期清理，DB 行冷归档未实现
- MVP 阶段使用普通表 + 覆盖索引；数据量达到阈值后迁移到按时间分区

### 8.5 数据迁移策略

- 使用 Alembic 管理 schema 变更
- 发布流程：先执行迁移，再部署新代码（migrate-then-deploy）
- 迁移脚本必须向后兼容：新代码可以读旧 schema，旧代码可以读新 schema（至少一个版本窗口）
- 破坏性变更（删列、改类型）分两步：第一次发布停止使用该列，第二次发布删除
- 大表迁移使用 `op.execute()` 分批处理，避免长事务锁表

---

## 9. 安全设计

### 9.1 认证

- JWT access token（短期，1 小时）+ refresh token（长期，7 天）
- API Token 用于机器对机器调用；当前创建、过期、吊销与认证已实现，scope enforcement 在 `check_permission` 层有能力，但项目级路由传递仍需补齐
- 密码使用 Argon2id 哈希

### 9.2 授权

双层角色模型：

**租户级角色**（`AppUser.role`）：

| 角色 | 权限 |
|------|------|
| Owner | 全部权限 + 删除租户 |
| Admin | 管理租户配置、成员 |
| Member | 加入项目、基本操作 |
| Viewer | 全局只读 |

**项目级角色**（`ProjectMember.role`）：

| 角色 | 权限 |
|------|------|
| Admin | 管理项目配置、凭证、成员 |
| Developer | 触发执行、查看结果 |
| Viewer | 项目内只读 |

实际权限取租户级和项目级的交集：租户 Viewer 即使是项目 Admin 也只能只读。

### 9.3 执行隔离

- 每次执行在独立容器中运行
- 容器网络策略按环境配置：默认 `deny` 对应 Docker `NetworkMode=none`；`allow` 显式使用 bridge；`restricted` 映射到 `qap-restricted`，该网络需部署侧预先创建
- 容器默认以 `1000:1000` 运行，rootfs 只读，drop all capabilities，并启用 `no-new-privileges`
- 资源限制：CPU / 内存已在 Docker HostConfig 中设置；磁盘限制、产物大小/数量上传侧校验、OOM/timeout 资源用量记录仍待补齐
- 执行结束后容器和临时文件销毁
- 当前 Compose worker 直接挂载 `/var/run/docker.sock` 以创建测试容器；生产部署必须按风险表加固为 Socket Proxy / rootless Docker / gVisor，或迁移到 K8s Job 后端

### 9.4 敏感数据

- Git 凭证使用 AES-256-GCM 加密存储；执行侧解密并安全注入 Git clone 仍待 F-PM-01 / F-PM-02 补齐
- 环境变量 `env_vars` 当前仍为明文 JSONB，待 T01 / F-PL-02 补齐加密存储
- 加密密钥通过环境变量注入，不落盘
- API 响应中不返回凭证明文

### 9.5 API 防护

- 认证高风险端点 rate limit：5 次/分钟/限流桶（覆盖 login / register / token / refresh / SSE ticket，不是仅失败请求）
- 通用 API rate limit：100 次/分钟/限流桶
- 限流桶：Bearer 请求按 token hash 隔离；无 Bearer 时按 `QAP_TRUSTED_PROXIES` 解析后的客户端 IP
- 不做落库账户锁定；当前用 Redis 滑动窗口 rate limit 降低暴力破解风险
- 使用 Redis 滑动窗口计数器实现

### 9.6 审计

- 关键写操作记录审计事件（who/what/when/from_where）；当前主路径已覆盖，批量取消/批量重试等覆盖率仍需补齐
- 审计事件类型：用户登录/登出、项目变更、凭证操作、执行触发/取消、权限变更
- 审计日志默认保留配置为 3 年（1095 天），由 `QAP_RETENTION_AUDIT_DAYS` 控制
- 目标提供审计日志查询 API（仅 Admin+ 可访问）；当前 `main` 写入端已就位，查询路由待 T02 补齐

---

## 10. 实时通信

### 10.1 日志流

```
容器 stdout/stderr → Worker 写入 Redis Stream → API 读取 → SSE 推送到客户端
```

- 使用 Redis Stream 作为日志缓冲（MAXLEN 10000 条/Run）
- 客户端断线重连时通过 `Last-Event-ID` 续传
- 执行结束后日志归档到 S3；归档成功后 Redis Stream 设置短 TTL，归档失败时保留 24h TTL 便于排查；当前仅实现归档写入，Redis TTL 过期后的归档日志读回 API / UI 仍缺失；`retry_failed_archives` 当前仍为空占位，未实现自动重试
- 单条日志消息最大 4KB，超出截断
- 执行并发由 `QAP_MAX_CONCURRENT_RUNS` / `QAP_MAX_CONCURRENT_PER_PROJECT` 控制；当前未实现 Redis 内存阈值拒绝新执行入队

### 10.2 状态事件

- Run 状态变更时写入 Redis Stream `run:{id}:events`，同时更新 `run:{id}:status` hash
- SSE 端点通过 Redis Stream 读取并推送给客户端，终态检测读取 status hash
- 支持按 Run ID 订阅特定执行的事件

---

## 11. 可观测性

### 11.1 三大支柱

| 支柱 | 实现 | 用途 |
|------|------|------|
| 日志 | structlog（JSON 格式） | 调试、审计 |
| 指标 | Prometheus client | 告警、容量规划 |
| 追踪 | OpenTelemetry | 待 T10 装配，用于请求链路分析 |

### 11.2 关键指标

- `run_queue_duration_seconds` — 排队等待时间
- `run_execution_duration_seconds` — 执行耗时
- `run_status_total` — 按状态计数
- `worker_active_containers` — 当前活跃容器数
- `api_request_duration_seconds` — API 延迟

### 11.3 健康检查

- `/health` — 进程存活
- `/ready` — 依赖就绪（PG + Redis 可连接）

---

## 12. 部署架构

### 12.1 开发环境

```yaml
# docker-compose.yml
# 开发默认只启动基础设施服务
services:
  postgres:  # 端口 5432
  redis:     # 端口 6379
  minio:     # 端口 9000/9001
```

开发默认使用 `make infra-up` 只启动基础设施，API、Worker 和前端分别在本地进程中运行；需要完整 Compose 栈时使用 `make up`，会同时启动 postgres、redis、minio、api、frontend、worker。

### 12.2 生产环境（渐进式）

**阶段 1：单机 Compose**
- 所有组件在一台机器上
- 适合日执行量 < 200

**阶段 2：分离 Worker**
- API 和 Worker 分机部署
- Worker 可水平扩展
- 适合日执行量 200-2000

**阶段 3：Kubernetes**
- API 部署为 Deployment
- Worker 部署为 Deployment（HPA 按队列深度扩缩）
- 测试执行切换为 K8s Job
- 基础设施使用托管服务（RDS、ElastiCache、S3）

---

## 13. 关键设计决策（ADR 摘要）

| # | 决策 | 理由 | 风险与缓解 |
|---|------|------|------------|
| 001 | arq 而非 Celery | async 原生、API 简洁、轻量 | 社区小 → 接口抽象可切换 |
| 002 | SSE 而非 WebSocket | 单向推送足够、HTTP 原生、调试简单 | 需双向时升级 → 当前不需要 |
| 003 | 先归档后分区 | 分区表外键约束复杂，MVP 数据量不需要 | 数据增长 → 保留索引+归档任务缓解 |
| 004 | 严格分层目录 | 依赖可静态检查、领域可单测 | 跨层改动多 → 小而稳定的接口缓解 |
| 005 | Protocol 插件而非继承 | 结构化子类型、无侵入、易测试 | 接口变更破坏插件 → 语义化版本+适配层 |
| 006 | Domain 层使用 Pydantic | 比 dataclass 更强的校验能力、自带序列化、immutable 配置 | 与"不依赖框架"原则的张力 → Pydantic 定位为值对象库而非 Web 框架，允许使用 |

---

## 14. 技术风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| arq 社区较小 | 遇到问题支持有限 | 任务层抽象为接口，可切换到 Celery/Dramatiq |
| Docker Socket 暴露 | Worker 越权管理宿主容器 | Socket Proxy / rootless Docker / gVisor |
| PostgreSQL 单点 | 数据库挂掉全站不可用 | 主从复制 + Patroni 自动故障转移 |
| 容器逃逸 | 安全风险 | 非特权容器 + seccomp + 网络隔离 |
| Redis 数据丢失 | 日志流中断 | 执行结束后归档日志到 S3；Redis AOF 持久化 |

---

## 15. 接口契约

### 15.1 API 版本策略

- URL 路径版本：`/api/v1/...`
- 破坏性变更发布新版本，旧版本保留至少 2 个大版本
- 非破坏性变更（新增字段、新增端点）在当前版本内发布

### 15.2 核心端点概览

| 模块 | 端点 | 说明 |
|------|------|------|
| 认证 | `POST /api/v1/auth/login` | 登录获取 token |
| 认证 | `POST /api/v1/auth/register` | 注册 |
| 认证 | `POST /api/v1/auth/refresh` | 刷新 token |
| 项目 | `CRUD /api/v1/projects` | 项目管理 |
| 管道 | `CRUD /api/v1/projects/{project_id}/pipelines` | 管道配置 |
| 环境 | `CRUD /api/v1/projects/{project_id}/environments` | 环境配置 |
| 执行 | `POST /api/v1/runs` | 触发执行 |
| 执行 | `GET /api/v1/runs/{id}` | 查询执行状态 |
| 执行 | `POST /api/v1/runs/{id}/cancel` | 取消执行 |
| 执行 | `GET /api/v1/runs/{id}/results` | 获取测试结果 |
| Webhook | `POST /api/v1/webhooks/{project_id}/trigger` | 接收外部 Webhook |
| 实时 | `GET /api/v1/runs/{id}/logs?ticket=...` | SSE 日志流 |
| 实时 | `GET /api/v1/runs/{id}/events?ticket=...` | SSE 状态事件 |

### 15.3 认证方式

- JWT：`Authorization: Bearer <jwt>`
- API Token：`Authorization: Bearer qap_<token_id>_<secret>`（当前 middleware 不解析 `X-API-Token`）

---

## 16. 未来演进方向

| 方向 | 触发条件 | 变更范围 |
|------|----------|----------|
| K8s Job 执行后端 | 日执行量 > 500 或需要弹性扩缩 | 新增 `engine/k8s_backend.py`，实现相同接口 |
| Valkey 替换 Redis | Redis 许可证风险 | 配置切换，代码无需改动 |
| 分区表 | 单表 > 1000 万行 | DBA 迁移，应用层透明 |
| GraphQL 网关 | 前端查询复杂度上升 | 新增网关层，REST 保留 |
| 多区域部署 | 合规或延迟要求 | 数据库主从 + 对象存储复制 |
