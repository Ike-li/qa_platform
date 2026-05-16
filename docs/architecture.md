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

---

## 3. 技术选型

| 组件 | 选型 | 决策理由 |
|------|------|----------|
| API 框架 | FastAPI | async 原生、自动 OpenAPI、Pydantic 校验 |
| 任务引擎 | arq | 轻量 async、比 Celery 简单；接口抽象可切换 |
| 数据库 | PostgreSQL 16 | JSONB、事务一致性、成熟生态 |
| 缓存/队列 | Redis 7 | arq broker + 缓存 + 实时日志流 |
| 对象存储 | S3 协议（MinIO 开发 / S3 生产） | 报告和产物存储 |
| 执行隔离 | Docker（开发）/ K8s Job（生产） | 统一容器接口，后端可切换 |
| 实时通信 | SSE | 单向推送足够、HTTP 原生、自动重连 |
| ORM | SQLAlchemy 2.0 async | 类型安全、async session |
| 迁移 | Alembic | SQLAlchemy 生态标配 |
| 可观测性 | OpenTelemetry + Prometheus + structlog | 链路追踪 + 指标 + 结构化日志 |

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
│  (FastAPI)     │    │  (Vue 3)         │
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
入队 Redis (arq enqueue)
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

- 失败后由 domain service 创建新 Run（共享 `retry_group_id`，`attempt` 递增）
- 不依赖 arq 内置重试（避免隐式行为）
- 可配置最大重试次数和重试间隔
- 仅基础设施失败触发重试（超时、OOM、worker_lost）；测试断言失败不重试
- 重试通过事件异步触发，不阻塞当前 Worker

### 6.5 Webhook 接收流程

```
外部 Git 平台 (GitHub/GitLab/Gitee)
    │
    ▼
POST /webhooks/{provider}
    │
    ├── 验证签名（HMAC-SHA256，密钥按项目配置）
    ├── 解析事件类型（push/PR/tag）
    ├── 匹配项目（按 repo URL 查找）
    ├── 应用分支过滤规则
    ├── 去重检查（同 commit SHA 不重复触发）
    │
    ▼
创建 Run（同手动触发流程）
```

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
    ├── 如配置了自动重试，创建新 Run attempt
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
    async def run_tests(self, working_dir: Path, config: dict, env_vars: dict) -> TestRunResult: ...

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
| git_source | Source | Git clone（HTTPS/SSH），支持 shallow clone（Phase 1 待实现） |
| pytest_runner | Runner | 执行 pytest |
| junit_collector | Collector | 解析 JUnit XML |

### 7.4 扩展点

未来可扩展的插件类型：
- 更多 Runner：go test、jest、playwright、robot framework
- 更多 Collector：Allure JSON、TAP、自定义格式
- 通知渠道：作为插件注册新的通知后端

---

## 8. 数据架构

### 8.1 核心实体关系

```
Tenant 1──N User
Tenant 1──N Project
Tenant 1──N Credential

Project 1──N Pipeline
Project 1──N Environment
Project 1──N Schedule
Project 1──N NotificationRule

Pipeline N──1 Project
Run N──1 Pipeline
Run N──1 Environment
Run 1──N TestResult
Run 1──N Artifact
Run 1──N Notification
```

### 8.2 关键实体字段

| 实体 | 核心字段 | 说明 |
|------|----------|------|
| Tenant | name, settings(JSONB) | 租户级配置（默认资源限制等） |
| Run | status, trigger_type, priority, git_ref, git_sha, retry_group_id, attempt, duration_ms, summary | 执行记录，status 为状态机核心 |
| Pipeline | runner_type, runner_config(JSONB), collector_type, collector_config(JSONB), timeout_seconds, max_retries | 管道定义，config 使用 JSONB 支持不同插件 |
| TestResult | suite, name, status, duration_ms, error_message, stack_trace | 单条用例结果 |

### 8.3 关键设计决策

- **多租户**：所有业务表包含 `tenant_id`，查询层自动过滤
- **软删除**：核心实体使用 `deleted_at` 软删除，保留审计轨迹
- **JSONB 灵活字段**：`runner_config`、`collector_config`、`variables` 等使用 JSONB，避免频繁 DDL
- **时间字段**：统一 UTC 存储，展示层转换时区

### 8.4 数据保留策略

- 执行记录默认保留 90 天
- 超期数据批量归档到冷存储
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
- API Token 用于机器对机器调用，支持 scope 限制
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
- 容器网络隔离（不可访问宿主网络和其他容器）
- 资源限制（CPU/内存/磁盘）
- 执行结束后容器和临时文件销毁
- Docker Socket 通过 Socket Proxy 限制可用 API

### 9.4 敏感数据

- Git 凭证和环境变量使用 AES-256-GCM 加密存储
- 加密密钥通过环境变量注入，不落盘
- API 响应中不返回凭证明文

### 9.5 API 防护

- 认证端点 rate limit：10 次/分钟/IP（防暴力破解）
- 通用 API rate limit：100 次/分钟/用户
- 连续认证失败 5 次后锁定账户 15 分钟
- 使用 Redis 滑动窗口计数器实现

### 9.6 审计

- 所有写操作记录审计事件（who/what/when/from_where）
- 审计事件类型：用户登录/登出、项目变更、凭证操作、执行触发/取消、权限变更
- 审计日志保留 3 年（1095 天），不可修改
- 提供审计日志查询 API（仅 Admin+ 可访问）

---

## 10. 实时通信

### 10.1 日志流

```
容器 stdout/stderr → Worker 写入 Redis Stream → API 读取 → SSE 推送到客户端
```

- 使用 Redis Stream 作为日志缓冲（MAXLEN 10000 条/Run）
- 客户端断线重连时通过 `Last-Event-ID` 续传
- 执行结束后日志归档到 S3，Redis Stream 在归档完成后删除
- 单条日志消息最大 4KB，超出截断
- 高并发保护：单 Worker 最多同时写入 10 个 Stream；Redis 内存超过阈值时拒绝新执行入队

### 10.2 状态事件

- Run 状态变更时发布事件到 Redis Pub/Sub
- SSE 端点订阅并推送给客户端
- 支持按 Run ID 订阅特定执行的事件

---

## 11. 可观测性

### 11.1 三大支柱

| 支柱 | 实现 | 用途 |
|------|------|------|
| 日志 | structlog（JSON 格式） | 调试、审计 |
| 指标 | Prometheus client | 告警、容量规划 |
| 追踪 | OpenTelemetry | 请求链路分析 |

### 11.2 关键指标

- `run_queue_duration_seconds` — 排队等待时间
- `run_execution_duration_seconds` — 执行耗时
- `run_status_total` — 按状态计数
- `worker_active_containers` — 当前活跃容器数
- `api_request_duration_seconds` — API 延迟

### 11.3 健康检查

- `/health/live` — 进程存活
- `/health/ready` — 依赖就绪（PG + Redis 可连接）

---

## 12. 部署架构

### 12.1 开发环境

```yaml
# docker-compose.yml
services:
  postgres:  # 端口 5432
  redis:     # 端口 6379
  minio:     # 端口 9000/9001
```

API 和 Worker 本地运行，基础设施容器化。

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
| Redis 数据丢失 | 日志流中断 | 日志同时写 S3；Redis AOF 持久化 |

---

## 15. 接口契约

### 15.1 API 版本策略

- URL 路径版本：`/api/v1/...`
- 破坏性变更发布新版本，旧版本保留至少 2 个大版本
- 非破坏性变更（新增字段、新增端点）在当前版本内发布

### 15.2 核心端点概览

| 模块 | 端点 | 说明 |
|------|------|------|
| 认证 | `POST /auth/login` | 登录获取 token |
| 认证 | `POST /auth/register` | 注册 |
| 认证 | `POST /auth/refresh` | 刷新 token |
| 项目 | `CRUD /projects` | 项目管理 |
| 管道 | `CRUD /pipelines` | 管道配置 |
| 环境 | `CRUD /environments` | 环境配置 |
| 执行 | `POST /runs` | 触发执行 |
| 执行 | `GET /runs/{id}` | 查询执行状态 |
| 执行 | `POST /runs/{id}/cancel` | 取消执行 |
| 执行 | `GET /runs/{id}/results` | 获取测试结果 |
| Webhook | `POST /webhooks/{provider}` | 接收外部 Webhook（GitHub/GitLab 等）[Phase 2] |
| 实时 | `GET /stream/{id}/logs` | SSE 日志流 |
| 实时 | `GET /stream/{id}/events` | SSE 状态事件 |

### 15.3 认证方式

- Bearer Token（JWT）：`Authorization: Bearer <token>`
- API Token：`X-API-Token: <token>`

---

## 16. 未来演进方向

| 方向 | 触发条件 | 变更范围 |
|------|----------|----------|
| K8s Job 执行后端 | 日执行量 > 500 或需要弹性扩缩 | 新增 `engine/k8s_backend.py`，实现相同接口 |
| Valkey 替换 Redis | Redis 许可证风险 | 配置切换，代码无需改动 |
| 分区表 | 单表 > 1000 万行 | DBA 迁移，应用层透明 |
| GraphQL 网关 | 前端查询复杂度上升 | 新增网关层，REST 保留 |
| 多区域部署 | 合规或延迟要求 | 数据库主从 + 对象存储复制 |
