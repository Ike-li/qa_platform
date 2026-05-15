---
# QA 自动化执行平台 — 架构设计文档

> 基于 PRD；**后端源码采用 domain / api / engine / infra / plugins / worker 严格分层**（见第 2 章）。

---

## 1. 架构概览

### 1.1 架构风格

**模块化单体 + 插件架构 + 源码严格分层**

不走微服务路线（团队规模不支撑运维复杂度），也不走传统大单体（难以扩展）。选择模块化单体，且 **Python 包内采用 domain / api / engine / infra / plugins / worker 严格分层**（依赖自上而下，禁止 domain 依赖框架与 IO），与 PRD 中的逻辑分层一致。

- 单一部署单元，用目录与 import 边界约束耦合
- 持久化仅由 `infra.repositories` 访问；业务规则集中在 `domain`
- 执行引擎可独立水平扩展（Worker 进程）
- 插件系统提供扩展点，核心不膨胀

### 1.2 系统全景图

                ┌─────────────────────────────────┐
                │           Clients               │
                │  Web UI │ CLI │ CI/CD │ Webhook │
                └────────────────┬────────────────┘
                                 │ HTTPS
                ┌────────────────▼────────────────┐
                │         Reverse Proxy            │
                │       (Caddy / Nginx)            │
                │  TLS 终止 │ 静态文件 │ 路由分发   │
                └──────┬─────────────┬────────────┘
                       │             │
          ┌────────────▼───┐   ┌─────▼────────────┐
          │   API Server   │   │   Frontend SPA    │
          │   (FastAPI)    │   │   (Vue 3 + Vite)  │
          │                │   │   静态资源托管      │
          │  • REST API    │   └──────────────────┘
          │  • SSE Stream  │
          │  • OpenAPI Doc │
          └───┬────┬───┬──┘
              │    │   │
   ┌──────────┘    │   └──────────┐
   │               │              │
┌──────▼──────┐ ┌──────▼──────┐ ┌────▼───────┐
│ PostgreSQL  │ │    Redis     │ │   MinIO    │
│             │ │              │ │   (S3)     │
│ • 业务数据  │ │ • 任务队列   │ │ • 报告     │
│ • 审计日志  │ │ • 日志流     │ │ • 产物     │
│ • 聚合数据  │ │ • 缓存/限流  │ │ • 归档日志 │
└─────────────┘ └──────┬──────┘ └────────────┘
                       │
              ┌────────▼────────┐
              │   Worker Pool    │
              │   (arq workers)  │
              │                  │
              │ ┌──────────────┐ │
              │ │  Executor    │ │
              │ │  (Docker API)│ │
              │ └──────────────┘ │
              └──────────────────┘

### 1.3 进程模型

| 进程 | 数量 | 职责 |
|------|------|------|
| api-server | 1-N (Uvicorn workers) | HTTP 请求处理、SSE 推送 |
| worker | 1-N (arq workers) | 异步任务执行（Git、测试、通知） |
| scheduler | 1 (单例) | Cron 调度触发；独立于 Worker 以便独立升级和灰度发布 |
| migrate | 一次性 | 数据库迁移 |

#### 1.3.1 Scheduler 调度流程

Scheduler 进程（`worker/scheduler.py`）的职责边界：

```text
scheduler.py（定时轮询）
    │
    ├── 0. 获取 leader lock（PostgreSQL advisory lock）
    │       未获取则本轮跳过，避免多实例重复触发
    │
    ├── 1. 查询 schedule 表：WHERE next_run_at <= now() AND enabled = true
    │       并应用 quiet_windows 与 missed_fire_policy
    │
    ├── 2. 对每条命中记录：
    │       ├── 2a. 调用 domain.services.scheduling.create_scheduled_run()
    │       │       → 创建 Run 记录（DB，status=queued）
    │       │       → 计算并更新 schedule.next_run_at
    │       │
    │       └── 2b. 调用 FairScheduler.enqueue(run)
    │               → 写入 Redis 队列（queue:low）
    │               → 若配额不足，Run 保持 queued 状态等待后续重试
    │
    ├── 3. 写入心跳：SET scheduler:heartbeat <timestamp> EX 90
    │
    └── 4. 等待下一轮（默认 30s 间隔）
```

> **注意：** Scheduler 不直接调用 `worker/tasks/` 中的函数。`worker/tasks/` 中的 arq task 函数仅由 Worker 从 Redis 队列消费时调用。Scheduler 的职责是"创建 Run 记录 + 入队"，不涉及执行逻辑。

> **单例保障：** 部署层应保持 `scheduler` replicas=1；运行时仍使用 PostgreSQL advisory lock（例如 `pg_try_advisory_lock(hashtext('qaplatform.scheduler'))`）做 leader election。这样即使误启动多个 Scheduler，也只有拿到锁的实例会处理 due schedules。进程退出或连接断开时 PG 自动释放锁。

---

## 2. 模块划分

### 2.1 目录结构（严格分层）

qa-platform/
├── src/
│   └── qaplatform/
│       ├── __init__.py
│       ├── main.py                 # FastAPI app 工厂
│       ├── config.py               # 配置加载（pydantic-settings）
│       ├── dependencies.py         # 依赖注入容器
│       │
│       ├── domain/                 # 领域层（纯业务逻辑，无框架依赖）
│       │   ├── models/             # 领域模型（dataclass / Pydantic）
│       │   │   ├── project.py
│       │   │   ├── environment.py
│       │   │   ├── pipeline.py
│       │   │   ├── run.py
│       │   │   ├── result.py
│       │   │   └── user.py
│       │   ├── services/           # 领域服务
│       │   │   ├── execution.py    # 执行编排规则
│       │   │   ├── scheduling.py   # 调度与配额规则
│       │   │   ├── discovery.py    # 测试发现
│       │   │   └── analytics.py    # 质量分析
│       │   └── events.py           # 领域事件定义
│       │
│       ├── api/                    # 接口层（HTTP / SSE）
│       │   ├── v1/
│       │   │   ├── __init__.py     # v1 路由聚合
│       │   │   ├── projects.py
│       │   │   ├── environments.py
│       │   │   ├── runs.py
│       │   │   ├── pipelines.py
│       │   │   ├── schedules.py
│       │   │   ├── notification_rules.py
│       │   │   ├── credentials.py
│       │   │   ├── members.py
│       │   │   ├── dashboard.py
│       │   │   ├── auth.py
│       │   │   └── system.py
│       │   ├── middleware/
│       │   │   ├── auth.py
│       │   │   ├── rate_limit.py
│       │   │   └── correlation.py
│       │   ├── schemas/
│       │   └── deps.py
│       │
│       ├── engine/                 # 执行引擎层（容器、日志流、并发）
│       │   ├── executor.py
│       │   ├── docker_backend.py
│       │   ├── k8s_backend.py      # Phase 4 骨架，MVP 不实现
│       │   ├── log_stream.py
│       │   ├── concurrency.py
│       │   └── sandbox.py
│       │
│       ├── plugins/                # 插件实现（协议在 protocols）
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── runners/
│       │   ├── collectors/
│       │   ├── reporters/
│       │   ├── notifiers/
│       │   └── triggers/
│       │
│       ├── infra/                  # 基础设施层
│       │   ├── database/
│       │   │   ├── session.py
│       │   │   ├── models.py       # SQLAlchemy ORM
│       │   │   └── repositories/
│       │   ├── cache.py
│       │   ├── storage.py
│       │   ├── crypto.py
│       │   └── event_bus.py
│       │
│       └── worker/                 # arq Worker 入口与任务
│           ├── __init__.py
│           ├── settings.py
│           ├── tasks/
│           └── scheduler.py
│
├── migrations/
├── tests/
├── frontend/
├── deploy/
└── docs/

### 2.2 模块依赖规则

```
api → domain
api → infra
engine → domain
worker → engine → domain
worker → plugins（经 registry 与注入上下文）
infra → 外部库（DB/Redis/S3 客户端）
```

**禁止：**

- `domain` 不得依赖 `api` / `infra` / `engine` / `plugins`
- `api` 不直接依赖 `engine`（触发执行经队列由 `worker` 消费）
- `plugins` 不依赖 `infra`（IO 能力由 `ExecutionContext` 等注入）
- ORM 模型与查询仅存在于 `infra`；`domain` 只见领域类型与仓储接口（实现放在 `infra.repositories`）

**横切解耦：** 通知有两条路径，职责不同：

1. **Pipeline Stage notify**（可选）：Pipeline 中显式配置的 notify Stage，在流水线内同步执行。适用于"执行完立即发一条消息"的简单场景。notify Stage 默认 `continue_on_error: true`，其失败不影响 Run 终态。
2. **Event Bus 规则通知**（推荐）：Run 进入终态后发布 `run.completed` / `run.failed` 领域事件，由 `infra.event_bus` 分发给 NotificationRule 订阅方异步处理。适用于条件匹配、多渠道、模板化的通知规则。

两者可共存：Stage notify 做即时轻量通知，Event Bus 做规则驱动的复杂通知。通知发送失败不影响 Run 结果（Stage notify 通过 `continue_on_error: true` 保证，Event Bus 通知天然异步解耦）。

### 2.3 模块职责边界

| 模块 | 职责 | 不做什么 |
|------|------|----------|
| domain | 业务规则、状态机、校验逻辑 | 不做 IO、不知道数据库/HTTP |
| api | 请求解析、响应序列化、认证与权限检查 | 不做业务规则、不直接操作容器 |
| engine | 容器生命周期、日志采集、资源与沙箱 | 不做业务判断、不访问数据库 |
| plugins | 框架适配、格式转换、外部通知协议 | 不做流水线编排 |
| infra | 持久化、缓存、加密、事件分发、仓储实现 | 不做领域规则 |
| worker | 任务消费、Pipeline Stage 编排 | 不处理 HTTP |

---

## 3. 核心流程

### 3.1 执行引擎（API / Worker / Docker / Redis·PG）

执行引擎在隔离容器中运行流水线；自入队到完成的简化时序如下。


API Server                Worker                Docker Engine          Redis/PG
    │                        │                       │                     │
    │  POST /runs            │                       │                     │
    ├───── enqueue ──────────►                       │                     │
    │                        │                       │                     │
    │                   pick job                     │                     │
    │                        │                       │                     │
    │                        ├── update status ──────────────────────────► │
    │                        │   (queued→preparing)  │                     │
    │                        │                       │                     │
    │                        ├── git clone/pull ────►│                     │
    │                        │                       │                     │
    │                        ├── build env ─────────►│                     │
    │                        │   (create container)  │                     │
    │                        │                       │                     │
    │                        ├── update status ──────────────────────────► │
    │                        │   (preparing→running) │                     │
    │                        │                       │                     │
    │                        ├── start container ───►│                     │
    │                        │                       │                     │
    │                        │◄── stdout stream ─────┤                     │
    │                        ├── write log stream ──────────────────────► │
    │                        │                       │                     │
    │                        │◄── container exit ────┤                     │
    │                        │                       │                     │
    │                        ├── update status ──────────────────────────► │
    │                        │   (running→collecting)│                     │
    │                        │                       │                     │
    │                        ├── collect artifacts ──┤                     │
    │                        ├── parse results       │                     │
    │                        ├── upload to S3 ───────────────────────────► │
    │                        │                       │                     │
    │                        ├── update status ──────────────────────────► │
    │                        │   (collecting→done)   │                     │
    │                        │                       │                     │
    │                        ├── emit event ─────────────────────────────► │
    │                        │   (run.completed)     │                     │
    │                        │                       │                     │


### 3.2 Executor 后端抽象

执行后端只保留一套接口，统一命名为 `ExecutionBackend`，详细定义见 6.1。上层模块只依赖 `create_execution / start / stream_logs / wait / cancel / force_kill / cleanup` 这组语义，不直接引用 Docker 容器对象。`execution_id` 是跨 Docker / K8s 的统一控制面标识。

### 3.3 执行流水线（Run Pipeline）


这是系统最核心的流程，描述从触发到完成的全过程。

┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌──────────┐
│ Trigger  │────▶│  API     │────▶│  Redis Queue │────▶│  Worker  │
│(手动/定时│     │ (校验+入│     │  (arq job)   │     │ (消费)   │
│ /webhook)│     │  队)     │     │              │     │          │
└──────────┘     └──────────┘     └──────────────┘     └────┬─────┘
                                                             │
                      ┌──────────────────────────────────────┘
                      │
                      ▼
        ┌─────────────────────────────┐
        │   Pipeline Executor         │
        │                             │
        │  ┌─────────┐ ┌──────────┐  │
        │  │Stage 1: │ │Stage 2:  │  │
        │  │git-sync │→│dep-install│  │
        │  └─────────┘ └────┬─────┘  │
        │                    │        │
        │  ┌─────────┐ ┌────▼─────┐  │
        │  │Stage 4: │ │Stage 3:  │  │
        │  │report   │←│test-run  │  │
        │  └────┬────┘ └──────────┘  │
        │       │                     │
        │  ┌────▼─────┐ ┌─────────┐  │
        │  │Stage 5:  │ │Stage 6: │  │
        │  │collect   │→│notify   │  │
        │  └──────────┘ └─────────┘  │
        └─────────────────────────────┘

#### 3.3.1 详细时序

```text
API Server                Worker                 Docker              PostgreSQL         Redis
    │                        │                      │                    │                │
    │──create Run (queued)──▶│                      │                    │                │
    │                        │                      │                    │◀──INSERT run───│
    │                        │                      │                    │                │
    │──enqueue job──────────▶│                      │                    │                │──▶
    │                        │◀─────consume job─────│                    │                │
    │                        │                      │                    │                │
    │                        │──UPDATE status=preparing──────────────────▶                │
    │                        │──publish status──────│────────────────────│───────────────▶│
    │                        │                      │                    │                │
    │                        │──create container───▶│                    │                │
    │                        │──start container────▶│                    │                │
    │                        │                      │                    │                │
    │                        │◀─────stdout stream───│                    │                │
    │                        │──append log──────────│────────────────────│───────────────▶│ (Stream)
    │                        │                      │                    │                │
    │                        │◀─────exit code───────│                    │                │
    │                        │──collect results─────│────────────────────▶                │
    │                        │──upload artifacts────│────────────────────│──▶ MinIO       │
    │                        │                      │                    │                │
    │                        │──UPDATE status=done───────────────────────▶                │
    │                        │──publish terminal status─────────────────│───────────────▶│ (Stream + Hash)
    │                        │                      │                    │                │
    │                        │──enqueue notify──────│────────────────────│───────────────▶│
    │                        │                      │                    │                │
```

### 3.4 执行状态机

```python
class RunStatus(str, Enum):
    QUEUED = "queued"           # 已入队，等待 Worker 消费
    PREPARING = "preparing"    # Worker 已认领，准备环境中
    RUNNING = "running"        # 测试执行中
    COLLECTING = "collecting"  # 收集结果和产物中
    DONE = "done"              # 执行完成（测试可能有失败，但流水线正常走完）
    FAILED = "failed"          # 流水线执行失败（基础设施错误、Stage 异常退出等，非测试断言失败）
    CANCELLED = "cancelled"    # 用户取消
    TIMEOUT = "timeout"        # 超时终止
```

> **DONE vs FAILED 语义：** `DONE` 表示流水线正常走完所有 Stage，测试用例的 pass/fail 体现在 `summary.passed / summary.failed` 中，不影响 Run 状态。`FAILED` 仅在基础设施层面出错时使用（容器启动失败、git clone 失败、Stage 插件抛异常等）。PipelineExecutor 中 `result.status == "failed"` 指的是 Stage 插件报告自身执行失败（如 git-sync 网络超时），不是测试断言失败。测试断言失败由 Collector 解析后写入 `test_result` 表，Run 状态仍为 `DONE`。

合法状态转移：

queued → preparing → running → collecting → done
  │          │          │           │
  │          │          │           └──→ failed / timeout
  │          │          └──→ failed / timeout
  │          └──→ failed
  └──→ cancelled

任何非终态 → cancelled（用户主动取消）
running / collecting → timeout（pipeline 硬超时；TimeoutGuard 和 ResourceReclaimer 使用条件更新抢占终态）

> **arq job 失败同步：** Worker 任务函数使用 try/except 兜底（见 6.5 `execute_run`），确保任何未捕获异常都会将对应的 Run 状态更新为 failed。此外，arq 的 `after_job_end` hook 作为二级保障：在 Worker 启动时注册该 hook，检查 job 是否异常退出且 Run 仍处于非终态，若是则补偿标记为 failed。否则 arq job 失败后 Run 可能卡在 preparing/running 中间状态。

#### 3.4.1 取消协议

取消不是直接“杀容器”这么简单，因为 Run 可能处在三种不同位置：

1. **尚未入 arq 队列**：`status=queued AND enqueued_at IS NULL`。API 直接把 Run 原子更新为 `cancelled`，写入 `run_event(type="run.cancelled")`，随后通过统一状态发布器调用 `publish_status_change(run_id, "cancelled", None)`，确保 SSE 依赖的 Redis status Hash 也进入终态。
2. **已入 arq 队列但未开始**：`status=queued AND arq_job_id IS NOT NULL`。API 先设置 `cancel_requested_at`，再做 best-effort 队列撤销。若撤销成功，API 立即用条件更新把 Run 置为 `cancelled`，写入 `run_event(type="run.cancelled")`，并调用 `publish_status_change(run_id, "cancelled", None)`；若撤销失败，Worker 入口必须先检查 `cancel_requested_at`，命中后直接标记 `cancelled` 并返回。
3. **执行中**：`preparing/running/collecting`。API 设置 `cancel_requested_at` 并发布状态事件；Worker 在阶段边界和日志循环中检查该字段，若 `execution_id` 已存在则调用 `backend.cancel(execution_id)`，最终通过条件更新落终态：

```sql
UPDATE run
SET status = 'cancelled',
    finished_at = now(),
    status_updated_at = now()
WHERE id = :run_id
  AND status NOT IN ('done', 'failed', 'cancelled', 'timeout');
```

`execution_id`、`arq_job_id`、`worker_id` 都是控制面字段，必须在状态变化时写入 DB，ResourceReclaimer 也依赖这些字段做崩溃恢复。

### 3.5 日志流架构

```text
Container stdout/stderr
        │
        ▼
┌───────────────────┐
│ Worker Log Reader │  (异步读取容器输出)
│  - 按行分割       │
│  - 附加时间戳     │
│  - 标记 stream    │
└────────┬──────────┘
         │
    ┌────▼────┐
    │  Redis  │  XADD run:{id}:logs
    │ Stream  │  MAXLEN ~10000 (自动截断)
    └────┬────┘
         │
    ┌────▼─────────────┐
    │ SSE Subscriber   │  客户端通过 GET /runs/{id}/logs (Accept: text/event-stream)
    │ (per connection) │  XREAD BLOCK 从 last_id 开始消费
    └──────────────────┘

执行完成后：
    Redis Stream → 归档为 JSONL → 上传 S3 → 删除 Stream
```

日志归档由 `execute_run` 的 Worker 收尾流程触发：Run 进入终态并发布终态 status Hash 后，Worker 调用 `archive_log_stream(run_id)` 把 `run:{id}:logs` 从 Redis Stream 顺序导出为 JSONL，上传到 `logs/{run_id}.jsonl`，再设置短 TTL（默认 1h）而不是立即删除 Stream，保证已连接的 SSE 客户端完成排空。归档失败按 arq 重试策略重试；多次失败时保留 Stream 到 24h TTL，并写入 `run_event(type="log.archive_failed")` 供后台补偿任务扫描。

### 3.6 并发调度

公平调度在**入队端**实现，而非 Worker 消费端。arq 的工作模型是 Worker 从指定队列消费任务，无法在消费时按项目做自定义 selection。因此 FairScheduler 在 API Server / Scheduler 创建 Run 后，决定是否调用 arq `enqueue_job`。超过配额的 Run 只保留在 PostgreSQL 中（`status=queued, enqueued_at=NULL`），由 `try_dequeue_waiting()` 后续补入 arq 队列。

触发入口在创建 Run 前先执行幂等检查：如果 Pipeline 配置了 `trigger_config.dedup_window_seconds`，则按 `pipeline_id + trigger_type + git_ref/git_sha + event_id` 计算 `dedup_key`，先获取 `dedup_key` 级 advisory lock，再在同一事务中查询未过期的相同 `dedup_key` Run；命中时直接返回已有 Run。DB 的 `idx_run_active_dedup` 兜底防止并发创建两个活跃 Run。

**事件链路保护：** Event 触发时必须传递 `source_run_id` 和 `chain_depth`。创建 Run 时 `chain_depth = source_run.chain_depth + 1`。系统配置 `max_event_chain_depth`（默认 5），超过时拒绝触发并写入 `run_event(type="event.chain_depth_exceeded")`，防止 A→B→A 循环触发导致无限 Run。

#### 3.6.1 队列架构

```
API Server (FairScheduler)
    │
    ├── queue:high   (manual triggers)
    ├── queue:medium (webhook triggers)
    └── queue:low    (schedule triggers)

Worker (arq)
    每个 Worker 进程监听一个 queue_name：
    - worker-high   → queue:high
    - worker-medium → queue:medium
    - worker-low    → queue:low
```

arq 的 `enqueue_job(..., _queue_name=...)` 用于写入指定队列，WorkerSettings 的 `queue_name` 决定该 Worker 监听哪条队列。优先级通过 Worker 配额实现（例如 high/medium/low = 2/2/1），不手写 Redis list。

#### 3.6.2 FairScheduler 实现

```python
from datetime import timedelta
from enum import IntEnum

class Priority(IntEnum):
    HIGH = 0    # manual
    MEDIUM = 1  # webhook
    LOW = 2     # schedule

PRIORITY_QUEUES = {
    Priority.HIGH: "queue:high",
    Priority.MEDIUM: "queue:medium",
    Priority.LOW: "queue:low",
}

TRIGGER_PRIORITY = {
    "manual": Priority.HIGH,
    "webhook": Priority.MEDIUM,
    "api": Priority.MEDIUM,
    "event": Priority.MEDIUM,
    "schedule": Priority.LOW,
}

class FairScheduler:
    """
    公平调度器（入队端）：防止单个项目垄断所有 Worker。

    策略：
    1. 按触发类型映射优先级 → 写入对应队列
    2. 同优先级内按项目配额限流（超出配额的 Run 保持 queued 状态，不入队）
    3. 全局并发上限
    """

    def __init__(self, arq: ArqRedis, run_repo: RunRepository, settings: Settings):
        self.arq = arq
        self.run_repo = run_repo
        self.max_total = settings.max_concurrent_runs
        self.max_per_project = settings.max_concurrent_per_project

    async def enqueue(self, run: Run) -> bool:
        """尝试入队。返回 True 表示立即入队，False 表示排队等待。"""
        # 配额检查和 enqueued_at/arq_job_id 写入必须在同一把锁内完成：
        # 可用 DB advisory lock 或 Redis Lua，避免并发请求同时越过配额。
        async with self.run_repo.scheduler_lock():
            return await self._enqueue_if_capacity(run)

    async def _enqueue_if_capacity(self, run: Run) -> bool:
        """在已持有 scheduler_lock 的前提下检查配额并入队。"""
        if await self._active_or_enqueued_count() >= self.max_total:
            await self.run_repo.mark_waiting(run.id)
            return False

        if await self._project_active_or_enqueued_count(run.project_id) >= self.max_per_project:
            await self.run_repo.mark_waiting(run.id)
            return False

        return await self._enqueue_run(run)

    async def _enqueue_run(self, run: Run) -> bool:
        """执行实际 arq 入队，并持久化 queue_name / arq_job_id / enqueued_at。"""
        priority = TRIGGER_PRIORITY[run.trigger_type]
        queue = PRIORITY_QUEUES[priority]
        job_id = f"run:{run.id}"

        job = await self.arq.enqueue_job(
            "execute_run",
            str(run.id),
            _queue_name=queue,
            _job_id=job_id,  # arq 用于去重；重复入队会返回 None
            _expires=timedelta(hours=24),
        )
        if job is None:
            existing = await self.run_repo.get_by_arq_job_id(job_id)
            if existing and existing.id == run.id and existing.enqueued_at:
                return True  # 同一 Run 的幂等重试，之前已经成功入队

            await self.run_repo.mark_waiting(
                run.id,
                reason=f"arq job id conflict: {job_id}",
            )
            return False

        await self.run_repo.mark_enqueued(
            run.id,
            queue_name=queue,
            arq_job_id=job.job_id,
            enqueued_at=utcnow(),
        )
        return True

    async def try_dequeue_waiting(self) -> int:
        """
        定期调用（通过 arq cron_job）：当有空闲 Worker 时，
        从 DB 中查找 status=queued AND enqueued_at IS NULL 的 Run，尝试入队。
        查询使用 SELECT ... FOR UPDATE SKIP LOCKED，避免多个 Worker 重复补队。
        这处理了因配额限制而排队等待的 Run。
        """
        dequeued = 0
        async with self.run_repo.scheduler_lock():
            waiting = await self.run_repo.find_waiting(limit=10)
            for run in waiting:
                if await self._active_or_enqueued_count() >= self.max_total:
                    break

                if await self._project_active_or_enqueued_count(run.project_id) >= self.max_per_project:
                    continue

                if await self._enqueue_run(run):
                    dequeued += 1

        return dequeued
```

> **设计决策：** FairScheduler 在入队端（API Server）而非消费端实现，原因有二：(1) arq 不支持自定义 job selection；(2) 入队端天然可做配额检查，避免 Worker 空转。

> **锁粒度说明：** MVP 使用全局 `scheduler_lock()` 串行化所有入队操作，实现简单且正确。当并发触发量增大后（多 webhook 同时到达），可优化为按 `project_id` 粒度加锁或使用 Redis Lua 原子配额检查。

### 3.7 认证流程

```text
┌────────────┐                    ┌──────────────┐
│   Client   │                    │  API Server  │
└─────┬──────┘                    └──────┬───────┘
      │                                  │
      │── POST /auth/login ─────────────▶│
      │   {username, password}           │
      │                                  │── verify password (argon2)
      │                                  │── generate JWT (access + refresh)
      │◀── {access_token, refresh_token}─│
      │                                  │
      │── GET /api/v1/runs ─────────────▶│
      │   Authorization: Bearer <jwt>    │
      │                                  │── validate JWT
      │                                  │── extract user_id + roles
      │                                  │── check permission
      │◀── 200 {data: [...]} ───────────│
      │                                  │

API Token 流程（机器对机器）：
      │── GET /api/v1/runs ─────────────▶│
      │   Authorization: Bearer qap_{token_id}_{secret}
      │                                  │── parse token_id
      │                                  │── lookup api_tokens by token_id
      │                                  │── argon2 verify(secret, secret_hash)
      │                                  │── check scope + expiry
      │◀── 200 {data: [...]} ───────────│

```

---

## 4. 数据架构

### 4.1 ER 图

┌──────────────┐       ┌──────────────┐       ┌──────────────────┐
│    tenant    │──1:N─▶│   project    │──1:N─▶│   environment    │
└──────────────┘       └──────┬───────┘       └──────────────────┘
                              │
                    ┌─────────┼──────────┐
                    │         │          │
             ┌──────▼───┐ ┌──▼────────┐ ┌──▼────────────────┐
             │ pipeline  │ │credential │ │ project_member    │
             └─────┬─────┘ └──────────┘ └───────────────────┘
                   │
            ┌──────▼──────┐
            │     run      │
            └──────┬───────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
  ┌─────▼────┐ ┌──▼─────┐ ┌──▼──────┐
  │test_result│ │artifact│ │run_event│
  └──────────┘ └────────┘ └─────────┘

┌──────────────┐
│     user     │──1:N─▶ api_token
└──────┬───────┘
       │
       └──1:N─▶ audit_event

### 4.2 核心表定义

> MVP 使用普通表，先保证主键、外键、迁移和查询语义简单可靠。`run`、`test_result`、`audit.event` 在 Phase 4+ 根据真实数据量迁移到按时间分区；不要在初始 DDL 中把 `PRIMARY KEY(id)` 直接放到按 `created_at/run_id` 分区的表上，否则 PostgreSQL 会因唯一约束未包含分区键而拒绝建表。

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS analytics;

-- 租户（多租户预留，MVP 单租户）
CREATE TABLE tenant (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    settings    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 用户
CREATE TABLE "user" (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    username        TEXT NOT NULL,
    email           TEXT NOT NULL,
    password_hash   TEXT NOT NULL,           -- argon2id
    role            TEXT NOT NULL DEFAULT 'user',  -- platform_admin / user
    is_active       BOOLEAN NOT NULL DEFAULT true,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, username),
    UNIQUE (tenant_id, email)
);

-- 项目
CREATE TABLE project (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,
    description     TEXT,
    git_url         TEXT NOT NULL,
    git_auth_method TEXT NOT NULL DEFAULT 'none',  -- none / token / ssh_key
    credential_id   UUID,                           -- 默认 Git 凭证，FK 在 credential 表创建后补
    default_branch  TEXT NOT NULL DEFAULT 'main',
    root_path       TEXT NOT NULL DEFAULT '.',
    shallow_clone   BOOLEAN NOT NULL DEFAULT true,
    default_env_id  UUID,                           -- FK 在 environment 表创建后补
    settings        JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'active',  -- active / archived
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, created_by) REFERENCES "user"(tenant_id, id),
    UNIQUE (tenant_id, slug)
);

-- 加密凭证
CREATE TABLE credential (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    project_id      UUID NOT NULL,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,           -- token / ssh_key / password
    encrypted_value BYTEA NOT NULL,          -- AES-256-GCM
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name),
    UNIQUE (project_id, id),
    FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, created_by) REFERENCES "user"(tenant_id, id)
);

-- 执行环境
CREATE TABLE environment (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    base_image      TEXT NOT NULL,
    setup_script    TEXT,
    resource_limits JSONB NOT NULL DEFAULT '{"memory_mb": 512, "cpu_cores": 1.0, "max_artifact_size_mb": 100, "max_artifacts_count": 50}',
    network_policy  TEXT NOT NULL DEFAULT 'deny',  -- allow / deny / restricted
    env_vars        JSONB NOT NULL DEFAULT '{}',   -- 非敏感变量；合并规则：系统默认 < 项目 < 环境 < 触发时覆盖
    cache_key       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name),
    UNIQUE (project_id, id)
);

ALTER TABLE project
    ADD CONSTRAINT fk_project_default_env
    FOREIGN KEY (id, default_env_id) REFERENCES environment(project_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE project
    ADD CONSTRAINT fk_project_credential
    FOREIGN KEY (id, credential_id) REFERENCES credential(project_id, id)
    DEFERRABLE INITIALLY DEFERRED;

-- default_env_id / credential_id 指向同项目资源；删除被引用资源前必须先清空 Project 上的默认引用。

-- Pipeline 定义
CREATE TABLE pipeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    stages          JSONB NOT NULL,         -- list[StageDefinition]
    selector        JSONB NOT NULL DEFAULT '{}',  -- 用例选择规则，包含 on_empty: "fail"|"skip"|"warn"
    trigger_config  JSONB NOT NULL DEFAULT '{}',  -- 触发配置，包含 dedup_window_seconds / webhook event 映射等
    timeout_seconds INT NOT NULL DEFAULT 1800,
    retry_policy    JSONB,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name),
    UNIQUE (project_id, id)
);

-- 执行实例
CREATE TABLE run (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    project_id      UUID NOT NULL,
    pipeline_id     UUID NOT NULL,
    environment_id  UUID NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    trigger_type    TEXT NOT NULL,           -- manual / schedule / webhook / api / event
    priority        SMALLINT NOT NULL DEFAULT 1, -- 0=high, 1=medium, 2=low
    triggered_by    UUID,
    git_ref         TEXT NOT NULL,
    git_sha         TEXT,
    -- 重试关联
    retry_group_id  UUID,                    -- 同一逻辑执行的多次 attempt 共享此 ID（首次执行时等于 run.id）
    attempt         INT NOT NULL DEFAULT 1,  -- 当前是第几次尝试
    -- 事件链路追踪
    source_run_id   UUID,                    -- Event 触发时的源 Run ID
    chain_depth     INT NOT NULL DEFAULT 0,  -- 事件链深度，防止 A→B→A 循环触发
    -- 去重与控制面
    dedup_key       TEXT,                    -- pipeline/trigger/git/event fingerprint
    dedup_expires_at TIMESTAMPTZ,
    queue_name      TEXT,                    -- arq queue name after enqueue
    arq_job_id      TEXT UNIQUE,             -- arq job id / dedup key
    execution_id    TEXT,                    -- Docker container id / K8s Job name
    worker_id       TEXT,
    enqueued_at     TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_ms     INT,
    summary         JSONB,                  -- {total, passed, failed, skipped, error, pass_rate}
    metadata        JSONB NOT NULL DEFAULT '{}',
    error_message   TEXT,
    status_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, id),
    FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, id),
    FOREIGN KEY (project_id, pipeline_id) REFERENCES pipeline(project_id, id),
    FOREIGN KEY (project_id, environment_id) REFERENCES environment(project_id, id),
    FOREIGN KEY (tenant_id, triggered_by) REFERENCES "user"(tenant_id, id)
);

-- 测试结果
CREATE TABLE test_result (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    suite           TEXT NOT NULL,
    name            TEXT NOT NULL,           -- 必须包含参数化后缀，如 test_foo[param1]
    status          TEXT NOT NULL,           -- passed / failed / error / skipped / xfail
    duration_ms     INT NOT NULL DEFAULT 0,
    error_message   TEXT,
    stack_trace     TEXT,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}',
    UNIQUE (run_id, suite, name)
);
-- 注意：Collector 插件必须保证 name 包含参数化后缀（如 pytest 的 test_foo[param1]），
-- 否则参数化用例会因 UNIQUE 约束冲突导致结果丢失。

-- 产物
CREATE TABLE artifact (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,           -- report / log / screenshot / video / coverage / custom
    name            TEXT NOT NULL,
    storage_path    TEXT NOT NULL,           -- S3 key
    size_bytes      BIGINT NOT NULL,
    mime_type       TEXT NOT NULL,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Run 事件流（状态变更、取消请求、恢复动作等持久事件）
CREATE TABLE run_event (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 项目成员
CREATE TABLE project_member (
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    project_id  UUID NOT NULL,
    user_id     UUID NOT NULL,
    role        TEXT NOT NULL DEFAULT 'developer',  -- owner / maintainer / developer / viewer
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id),
    FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, user_id) REFERENCES "user"(tenant_id, id) ON DELETE CASCADE
);

-- 通知规则
CREATE TABLE notification_rule (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    conditions  JSONB NOT NULL DEFAULT '[]',
    channels    JSONB NOT NULL,              -- list[{type, config}]
    template    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, id)
);

-- 通知日志
CREATE TABLE notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL,
    run_id          UUID NOT NULL,
    rule_id         UUID NOT NULL,
    channel_type    TEXT NOT NULL,
    status          TEXT NOT NULL,           -- sent / failed / skipped
    error_message   TEXT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, rule_id, channel_type),
    FOREIGN KEY (project_id, run_id) REFERENCES run(project_id, id) ON DELETE CASCADE,
    FOREIGN KEY (project_id, rule_id) REFERENCES notification_rule(project_id, id) ON DELETE CASCADE
);

-- Cron 调度
CREATE TABLE schedule (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL,
    pipeline_id UUID NOT NULL,
    cron_expr   TEXT NOT NULL,
    timezone    TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    missed_fire_policy TEXT NOT NULL DEFAULT 'skip', -- skip / run_once / run_all
    quiet_windows JSONB NOT NULL DEFAULT '[]',       -- list[{start,end,timezone}]
    enabled     BOOLEAN NOT NULL DEFAULT true,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    last_error   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, id),
    FOREIGN KEY (project_id, pipeline_id) REFERENCES pipeline(project_id, id) ON DELETE CASCADE
);

-- API Token
CREATE TABLE api_token (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    token_id    TEXT NOT NULL UNIQUE,       -- 随机不可预测的公开定位符（16 bytes hex），防止枚举攻击
    secret_hash TEXT NOT NULL,              -- secret 的 argon2id hash，只用于 verify
    scopes      JSONB NOT NULL DEFAULT '["*"]',  -- 权限范围
    expires_at  TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    last_used_ip INET,
    is_revoked  BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 安全说明：token_id 必须使用密码学安全随机数生成（os.urandom(16).hex()），
-- 不可使用 UUID 或递增序列，防止攻击者枚举 token_id 后暴力破解 secret。
-- 认证失败按 IP 做专用 rate limit（rate_limit_auth_failure），独立于通用 API 限流。

-- 审计事件（独立 schema）
CREATE TABLE audit.event (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    user_id     UUID,
    action      TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID,
    before_state JSONB,
    after_state  JSONB,
    ip_address  INET,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- audit.event.user_id 不设置数据库外键：审计记录必须在用户删除后继续保留。
-- 写入审计事件时由应用层校验 user_id 是否属于 tenant_id；删除用户只做软删除或保留 tombstone。

-- 预聚合指标（物化视图或定时任务填充）
CREATE TABLE analytics.daily_metrics (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL,
    date        DATE NOT NULL,
    total_runs  INT NOT NULL DEFAULT 0,
    passed_runs INT NOT NULL DEFAULT 0,
    failed_runs INT NOT NULL DEFAULT 0,
    total_cases INT NOT NULL DEFAULT 0,
    passed_cases INT NOT NULL DEFAULT 0,
    avg_duration_ms INT,
    p90_duration_ms INT,
    flaky_count INT NOT NULL DEFAULT 0,
    UNIQUE (project_id, date)
);
```

### 4.3 索引策略

```sql
-- 高频查询覆盖索引
CREATE INDEX idx_run_project_status ON run(project_id, status, created_at DESC);
CREATE INDEX idx_run_project_created ON run(project_id, created_at DESC);
CREATE INDEX idx_run_status_created ON run(status, created_at) WHERE status IN ('queued', 'preparing', 'running');
CREATE UNIQUE INDEX idx_run_active_dedup ON run(project_id, pipeline_id, dedup_key)
    WHERE dedup_key IS NOT NULL AND status IN ('queued', 'preparing', 'running', 'collecting');
CREATE INDEX idx_run_dedup_lookup ON run(project_id, pipeline_id, dedup_key, dedup_expires_at)
    WHERE dedup_key IS NOT NULL;
CREATE INDEX idx_test_result_run ON test_result(run_id);
CREATE INDEX idx_test_result_status ON test_result(run_id, status);
CREATE INDEX idx_artifact_run ON artifact(run_id);
CREATE INDEX idx_run_event_run_created ON run_event(run_id, created_at);
CREATE INDEX idx_schedule_next ON schedule(next_run_at) WHERE enabled = true;
CREATE INDEX idx_audit_resource ON audit.event(resource_type, resource_id, created_at DESC);
CREATE INDEX idx_audit_user ON audit.event(user_id, created_at DESC);

-- Flaky 检测 & 失败聚类：跨 Run 查询同一用例的状态历史
CREATE INDEX idx_test_result_flaky ON test_result(suite, name, status);

-- 中间状态 Run 超时恢复：ResourceReclaimer 扫描。
-- running/collecting 的 pipeline deadline 使用 find_past_pipeline_deadline(status_updated_at + pipeline.timeout_seconds)，
-- idx_run_stale 只覆盖 preparing/collecting 的“阶段卡死”阈值扫描。
CREATE INDEX idx_run_stale ON run(status, status_updated_at) WHERE status IN ('preparing', 'collecting');
CREATE INDEX idx_run_waiting ON run(priority, created_at) WHERE status = 'queued' AND enqueued_at IS NULL;
```

### 4.4 数据生命周期

┌──────────────┬──────┬────────┬──────┬──────────────────────────────┐
│   数据类型   │ 热期 │  温期  │ 冷期 │           清理策略           │
├──────────────┼──────┼────────┼──────┼──────────────────────────────┤
│ Run 记录     │ 7 天 │ 90 天  │ 1 年 │ 软删除 → 批量归档/删除       │
├──────────────┼──────┼────────┼──────┼──────────────────────────────┤
│ TestResult   │ 7 天 │ 90 天  │ —    │ 随 Run 清理                  │
├──────────────┼──────┼────────┼──────┼──────────────────────────────┤
│ 日志 (Redis) │ 24h  │ —      │ —    │ Stream MAXLEN + TTL          │
├──────────────┼──────┼────────┼──────┼──────────────────────────────┤
│ 日志 (S3)    │ —    │ 90 天  │ 1 年 │ S3 Lifecycle Policy          │
├──────────────┼──────┼────────┼──────┼──────────────────────────────┤
│ 报告 (S3)    │ —    │ 30 天  │ —    │ S3 Lifecycle + DB expires_at │
├──────────────┼──────┼────────┼──────┼──────────────────────────────┤
│ 审计日志     │ —    │ 180 天 │ 3 年 │ 批量归档/删除；Phase 4+ 分区 │
├──────────────┼──────┼────────┼──────┼──────────────────────────────┤
│ 聚合指标     │ —    │ 永久   │ —    │ 不清理（数据量小）           │
└──────────────┴──────┴────────┴──────┴──────────────────────────────┘

---

## 5. 插件系统架构

### 5.1 插件协议

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from pathlib import Path

@dataclass
class PluginMeta:
    name: str
    version: str
    description: str
    config_schema: dict  # JSON Schema，用于校验配置

@runtime_checkable
class RunnerPlugin(Protocol):
    meta: PluginMeta

    async def validate_config(self, config: dict) -> list[str]:
        """校验配置，返回错误列表（空 = 通过）"""
        ...

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """在容器内执行测试"""
        ...

@runtime_checkable
class CollectorPlugin(Protocol):
    meta: PluginMeta
    supported_formats: list[str]

    async def collect(self, results_dir: Path) -> list[TestResultData]:
        """从结果目录解析测试结果"""
        ...

@runtime_checkable
class NotifierPlugin(Protocol):
    meta: PluginMeta

    async def validate_config(self, config: dict) -> list[str]:
        ...

    async def send(self, notification: Notification) -> None:
        """发送通知，失败抛异常"""
        ...

@runtime_checkable
class ReporterPlugin(Protocol):
    meta: PluginMeta

    async def generate(self, ctx: ExecutionContext, results: list[TestResultData]) -> list[ArtifactData]:
        """生成报告产物"""
        ...

@runtime_checkable
class TriggerPlugin(Protocol):
    meta: PluginMeta

    async def validate_config(self, config: dict) -> list[str]:
        ...

    async def parse(self, payload: dict) -> TriggerRequest:
        """把外部触发载荷转换为统一触发请求"""
        ...

@runtime_checkable
class SourcePlugin(Protocol):
    meta: PluginMeta

    async def fetch(self, ctx: SourceContext) -> SourceRevision:
        """获取代码并返回实际执行的 git_sha / revision"""
        ...

@dataclass
class ExecutionContext:
    """传递给插件的执行上下文"""
    run_id: str
    project_dir: Path        # 代码目录（只读）
    work_dir: Path           # 工作目录（读写）
    results_dir: Path        # 结果输出目录
    artifacts_dir: Path      # 产物输出目录
    env_vars: dict[str, str] # 环境变量
    config: dict             # 插件配置
    timeout_seconds: int
    log: Callable[[str], None]  # 日志回调
```

SourcePlugin 不作为普通 RunnerPlugin 执行。内置 `git-sync` Stage 是 PipelineExecutor 的系统阶段：它根据项目 Source 配置调用 `SourcePlugin.fetch()`，产出 `SourceRevision` 和只读 `project_dir`，再把该目录传给后续 Runner / Collector / Reporter。普通业务 Stage 通过 `registry.get_plugin(stage_def.plugin)` 获取 Runner/Collector/Reporter/Notifier；SourcePlugin 只负责代码获取边界，避免测试执行插件直接处理凭证和仓库拉取。

### 5.2 插件注册与发现

```python
class PluginRegistry:
    """
    插件注册表。
    内置插件在启动时自动注册。
    外部插件通过 entry_points 机制发现。
    """

    def __init__(self):
        self._runners: dict[str, RunnerPlugin] = {}
        self._collectors: dict[str, CollectorPlugin] = {}
        self._notifiers: dict[str, NotifierPlugin] = {}
        self._reporters: dict[str, ReporterPlugin] = {}
        self._triggers: dict[str, TriggerPlugin] = {}
        self._sources: dict[str, SourcePlugin] = {}

    def discover(self):
        """从 entry_points 发现外部插件"""
        for ep in importlib.metadata.entry_points(group="qaplatform.plugins"):
            plugin = ep.load()
            self._register(plugin)

    def get_runner(self, name: str) -> RunnerPlugin:
        ...
```

外部插件通过 `pyproject.toml` 声明：

```toml
[project.entry-points."qaplatform.plugins"]
my_custom_runner = "my_plugin:MyRunner"
```

### 5.3 Stage 执行引擎

```python
class PipelineExecutor:
    """
    按序执行 Pipeline 中的 Stages。
    每个 Stage 对应一个插件调用。
    状态机驱动：根据 stage_def.phase 推进 Run 状态。
    """

    async def execute(self, run: Run, pipeline: Pipeline) -> RunStatus:
        current_phase = "prepare"

        for stage_def in pipeline.stages:
            # 阶段边界检查取消请求；避免用户取消后继续启动下一个 Stage。
            fresh_run = await self.run_repo.get(run.id)
            if fresh_run.status in TERMINAL_STATUSES:
                return fresh_run.status
            if fresh_run.cancel_requested_at:
                return RunStatus.CANCELLED

            # 根据 stage phase 推进状态机
            stage_phase = stage_def.phase or self._infer_phase(stage_def.plugin)
            if stage_phase == "execute" and current_phase == "prepare":
                await self.run_repo.mark_running(run.id)
                await publish_status_change(run.id, "running", None)
                current_phase = "execute"
            elif stage_phase == "collect" and current_phase == "execute":
                await self.run_repo.mark_collecting(run.id)
                await publish_status_change(run.id, "collecting", None)
                current_phase = "collect"

            plugin = self.registry.get_plugin(stage_def.plugin)

            try:
                result = await self._dispatch(plugin, run, stage_def)

                if result.status == "failed" and not stage_def.continue_on_error:
                    return RunStatus.FAILED

            except Exception as e:
                # pipeline 级超时不通过 asyncio.TimeoutError 传播。
                # TimeoutGuard 会先抢占 DB 终态并 kill 容器；plugin.execute() 通常收到
                # DockerError / ConnectionError / stream closed 等后端异常后进入这里复查 DB。
                fresh_run = await self.run_repo.get(run.id)
                if fresh_run.status in TERMINAL_STATUSES:
                    return fresh_run.status
                await self._log(run.id, f"Stage '{stage_def.name}' error: {e}")
                if not stage_def.continue_on_error:
                    return RunStatus.FAILED

        return RunStatus.DONE

    def _infer_phase(self, plugin: str) -> str:
        """根据内置插件名推断 phase（用户未显式配置时的 fallback）"""
        PHASE_MAP = {
            "git-sync": "prepare",
            "dependency-install": "prepare",
            "test-run": "execute",
            "result-collect": "collect",
            "report-generate": "collect",
            "artifact-upload": "collect",
            "notify": "notify",
        }
        return PHASE_MAP.get(plugin, "execute")

    async def _dispatch(self, plugin, run: Run, stage_def) -> StageResult:
        """
        按插件协议类型分发调用。各插件协议方法名不同：
        - RunnerPlugin.execute(ctx)
        - CollectorPlugin.collect(results_dir)
        - ReporterPlugin.generate(ctx, results)
        - NotifierPlugin.send(notification)
        - SourcePlugin.fetch(ctx)
        PipelineExecutor 通过 isinstance 检查分发到正确方法。
        """
        ctx = self._build_context(run, stage_def)
        if isinstance(plugin, RunnerPlugin):
            return await plugin.execute(ctx)
        elif isinstance(plugin, CollectorPlugin):
            results = await plugin.collect(ctx.results_dir)
            await self._store_results(run.id, results)
            return StageResult(status="passed")
        elif isinstance(plugin, ReporterPlugin):
            artifacts = await plugin.generate(ctx, self._get_results(run.id))
            await self._store_artifacts(run.id, artifacts)
            return StageResult(status="passed")
        elif isinstance(plugin, NotifierPlugin):
            await plugin.send(self._build_notification(run))
            return StageResult(status="passed")
        elif isinstance(plugin, SourcePlugin):
            revision = await plugin.fetch(self._build_source_context(run))
            await self._update_git_sha(run.id, revision.sha)
            return StageResult(status="passed")
        else:
            raise ValueError(f"Unknown plugin type: {type(plugin)}")
```

Worker 收尾写终态时必须使用条件更新，不能用无条件 `update_status` 覆盖并发协程已经写入的终态。例如：`DONE` 使用 `complete_if_current(run_id, expected_in={RUNNING, COLLECTING})`，`FAILED` 使用 `fail_if_current(...)`，`CANCELLED` 使用 `cancel_if_current(...)`。若条件更新返回 0 行，说明 TimeoutGuard / 取消路径 / ResourceReclaimer 已经写入终态，Worker 只做资源清理和事件补偿，不再覆盖状态。

---

## 6. 执行引擎详设

### 6.1 容器执行后端接口

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class ResourceLimits:
    cpu_cores: float
    memory_bytes: int
    disk_bytes: int | None = None
    max_artifact_size_bytes: int = 500 * 1024 * 1024
    max_artifacts_count: int = 100

@dataclass
class ExitResult:
    exit_code: int
    started_at: datetime
    finished_at: datetime
    oom_killed: bool = False
    timed_out: bool = False

class ExecutionBackend(Protocol):
    """执行后端抽象，支持 Docker 和 Kubernetes"""

    async def create_execution(self, spec: ExecutionSpec) -> str:
        """创建执行环境，返回 execution_id"""
        ...

    async def start(self, execution_id: str) -> None:
        """启动执行"""
        ...

    async def stream_logs(self, execution_id: str) -> AsyncIterator[LogLine]:
        """流式获取日志"""
        ...

    async def wait(self, execution_id: str, timeout: int) -> ExitResult:
        """等待执行完成"""
        ...

    async def cancel(self, execution_id: str) -> None:
        """发送优雅取消信号（Docker: SIGTERM；K8s: delete job / terminate pod）"""
        ...

    async def force_kill(self, execution_id: str) -> None:
        """宽限期后强制终止执行环境"""
        ...

    async def cleanup(self, execution_id: str) -> None:
        """清理资源"""
        ...

@dataclass
class SandboxSecurity:
    readonly_rootfs: bool = True
    # Docker: None 表示使用 Docker daemon 默认 seccomp；自定义时传 profile json 路径。
    # Kubernetes: K8s 后端可把 None 映射为 RuntimeDefault。
    seccomp_profile: str | None = None
    cap_drop: list[str] = field(default_factory=lambda: ["ALL"])
    cap_add: list[str] = field(default_factory=list)
    pids_limit: int = 256
    devices: list[str] = field(default_factory=list)

@dataclass
class ExecutionSpec:
    image: str
    command: list[str]
    env_vars: dict[str, str]
    mounts: list[Mount]
    resource_limits: ResourceLimits
    network_policy: str
    user: str
    security: SandboxSecurity
    labels: dict[str, str]
```

> **K8s 后端风险提示：** K8s Job 的生命周期（apply → 自动调度 → pod logs → completion → 自动清理）与 Docker 的显式控制模型（create → start → stream → wait → stop → remove）不完全对齐。在实现 K8s 后端前需做 spike 验证，可能需要合并 `create_execution` + `start` 或增加 `supports_incremental_logs()` 方法。

### 6.2 Docker 后端实现

```python
from datetime import datetime, timezone

class DockerBackend:
    """Docker 执行后端"""

    def __init__(self, docker_client: aiodocker.Docker):
        self.client = docker_client

    async def create_execution(self, spec: ExecutionSpec) -> str:
        container_config = {
            "Image": spec.image,
            "Cmd": spec.command,
            "Env": [f"{k}={v}" for k, v in spec.env_vars.items()],
            "User": spec.user,  # 非 root，例如 "1000:1000"
            "HostConfig": {
                "Memory": spec.resource_limits.memory_bytes,
                "NanoCpus": int(spec.resource_limits.cpu_cores * 1e9),
                "ReadonlyRootfs": spec.security.readonly_rootfs,
                "SecurityOpt": self._security_opt(spec.security),
                "CapDrop": spec.security.cap_drop,
                "CapAdd": spec.security.cap_add,
                "PidsLimit": spec.security.pids_limit,
                "Devices": spec.security.devices,
                "NetworkMode": self._network_mode(spec.network_policy),
                "Binds": self._build_binds(spec.mounts),
                "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
            },
            "Labels": spec.labels,
        }
        container = await self.client.containers.create_or_replace(
            name=f"qap-run-{spec.labels['run_id']}",
            config=container_config,
        )
        return container.id

    def _security_opt(self, security: SandboxSecurity) -> list[str]:
        opts = ["no-new-privileges"]
        if security.seccomp_profile:
            opts.append(f"seccomp={security.seccomp_profile}")
        return opts

    def _network_mode(self, policy: str) -> str:
        if policy == "deny":
            return "none"
        if policy == "allow":
            return "bridge"
        if policy == "restricted":
            # 预创建受限网络，只允许访问内网依赖代理/白名单出口。
            return "qap-restricted"
        raise ValueError(f"Unknown network policy: {policy}")

    async def stream_logs(self, execution_id: str) -> AsyncIterator[LogLine]:
        container = self.client.containers.container(execution_id)
        async for raw in container.log(stdout=True, stderr=True, follow=True):
            stream, content = self._decode_log_frame(raw)
            yield LogLine(
                timestamp=datetime.now(timezone.utc),
                stream=stream,
                content=content,
            )

    def _decode_log_frame(self, raw: bytes) -> tuple[str, str]:
        if len(raw) >= 8 and raw[0] in (1, 2):
            stream = "stdout" if raw[0] == 1 else "stderr"
            return stream, raw[8:].decode(errors="replace").rstrip()

        # TTY 模式或非 multiplex 输出可能没有 Docker header。
        return "stdout", raw.decode(errors="replace").rstrip()
```

### 6.3 超时守护

```python
class TimeoutGuard:
    """
    独立的超时守护协程。
    不依赖容器自身的 timeout（那个不够可靠）。
    """

    async def watch(self, run_id: str, execution_id: str, timeout_seconds: int):
        try:
            await asyncio.sleep(timeout_seconds)
            # 先用条件更新抢占 TIMEOUT 终态，防止容器被 kill 后 PipelineExecutor 把异常覆盖成 FAILED。
            claimed = await self.run_repo.timeout_if_current(
                run_id,
                expected_in={RunStatus.RUNNING, RunStatus.COLLECTING},
            )
            if not claimed:
                return

            # 超时：先发 SIGTERM，给 30s 宽限期
            await self.backend.cancel(execution_id)
            try:
                await self.backend.wait(execution_id, timeout=30)
            except asyncio.TimeoutError:
                # 如果宽限期内还没退出，强制 kill
                await self.backend.force_kill(execution_id)
            await publish_status_change(run_id, "timeout", None)
        except asyncio.CancelledError:
            pass  # 正常完成时取消此守护
```

### 6.4 资源回收

> **运行位置：** ResourceReclaimer 作为独立的 arq cron job 运行在 Worker 进程中（通过 `arq` 的 `cron_jobs` 配置注册，间隔 60s）。不使用独立进程，也不在 API Server 中运行。arq 的 cron job 在 Worker 空闲时执行，不会阻塞正常的 job 消费。

```python
from arq import cron

class ResourceReclaimer:
    """
    定期扫描和回收孤立资源：
    - 失去关联的容器（Worker 崩溃后遗留）
    - 超时未完成的 Run（preparing/collecting 标记 failed，running 标记 timeout）
    - 过期的 Redis Stream
    """

    async def reclaim_once(self):
        await self._detect_dead_workers()
        await self._reclaim_orphan_containers()
        await self._timeout_stale_runs()
        await self._cleanup_expired_streams()

    async def _reclaim_orphan_containers(self):
        containers = await self.docker.containers.list(
            filters={"label": "managed-by=qaplatform"}
        )
        for container in containers:
            run_id = container.labels.get("run_id")
            if not run_id:
                await container.delete(force=True)
                continue
            run = await self.run_repo.get(run_id)
            if not run or run.status in TERMINAL_STATUSES:
                await container.delete(force=True)

    async def _timeout_stale_runs(self):
        """
        修复 Worker 崩溃或外部 IO 卡死导致的中间状态悬挂。
        阈值与执行超时分开配置：
        - preparing_timeout_seconds: 默认 300s
        - collecting_timeout_seconds: 默认 180s
        - running/collecting 超过 pipeline deadline: 标记 timeout
        """
        stale_preparing = await self.run_repo.find_stale(
            status=RunStatus.PREPARING,
            older_than=utcnow() - timedelta(seconds=self.settings.preparing_timeout_seconds),
        )
        for run in stale_preparing:
            await self.run_repo.fail_if_current(
                run.id,
                expected=RunStatus.PREPARING,
                message="Worker did not finish preparing before timeout",
            )

        past_deadline = await self.run_repo.find_past_pipeline_deadline(
            statuses=[RunStatus.RUNNING, RunStatus.COLLECTING],
        )
        for run in past_deadline:
            if run.execution_id:
                await self.backend.cancel(run.execution_id)
            await self.run_repo.timeout_if_current(
                run.id,
                expected_in={RunStatus.RUNNING, RunStatus.COLLECTING},
            )

        stale_collecting = await self.run_repo.find_stale(
            status=RunStatus.COLLECTING,
            older_than=utcnow() - timedelta(seconds=self.settings.collecting_timeout_seconds),
        )
        for run in stale_collecting:
            await self.run_repo.fail_if_current(
                run.id,
                expected=RunStatus.COLLECTING,
                message="Result collection did not finish before timeout",
            )


async def reclaim_resources(ctx):
    reclaimer: ResourceReclaimer = ctx["resource_reclaimer"]
    await reclaimer.reclaim_once()


async def dequeue_waiting(ctx):
    scheduler: FairScheduler = ctx["fair_scheduler"]
    await scheduler.try_dequeue_waiting()


class WorkerSettings:
    cron_jobs = [
        # 每分钟执行一次；不在 cron job 内部自循环。
        cron(reclaim_resources, second=0),
        # 每分钟执行一次，和资源回收错开 30s，回补因配额限制而等待的 Run。
        cron(dequeue_waiting, second=30),
    ]
```

### 6.4.1 Worker 心跳

arq cron job 在 Worker 执行长任务时无法抢占运行（arq 单 Worker 进程同时只处理一个 job），因此心跳不能依赖 cron job。改为在 `execute_run` 内部通过 `asyncio` 后台任务定期上报：

```python
async def _heartbeat_loop(worker_id: str, redis, interval: int = 30):
    """在 execute_run 协程内作为后台 task 运行，每 interval 秒刷新心跳。"""
    try:
        while True:
            await redis.set(f"worker:{worker_id}:heartbeat", utcnow().isoformat(), ex=90)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass

async def execute_run(ctx, run_id: str):
    # ... claim_for_worker 等前置逻辑 ...
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(ctx["worker_id"], ctx["redis"])
    )
    try:
        # ... 执行逻辑 ...
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        # ... 日志归档、release_worker ...
```

ResourceReclaimer 扫描时调用 `_detect_dead_workers()`：

```python
async def _detect_dead_workers(self):
    """检测心跳超时的 Worker，标记其持有的 Run 为 failed。"""
    active_runs = await self.run_repo.find_active_with_worker()
    for run in active_runs:
        heartbeat = await redis.get(f"worker:{run.worker_id}:heartbeat")
        if heartbeat is None:
            # Worker 心跳超时（>90s），认为已死
            if run.execution_id:
                await self.backend.force_kill(run.execution_id)
            await self.run_repo.fail_if_current(
                run.id,
                expected_in={RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.COLLECTING},
                message=f"Worker {run.worker_id} heartbeat timeout",
            )
```

> arq 的 `cron()` 支持 `second` 参数；这里使用 `second=0/30` 表示每分钟在对应秒触发一次，避免两个维护任务同时启动。

### 6.5 arq Worker 任务入口

> **arq 重试禁用：** `execute_run` 必须在 `WorkerSettings.functions` 中声明 `max_tries=1`，禁止 arq 内置重试（arq 默认 `max_tries=5`）。平台级重试由 `domain.services.execution` 根据 `RetryPolicy` 创建新的 Run attempt，两套重试模型不能并存。

```python
async def execute_run(ctx, run_id: str):
    run_repo: RunRepository = ctx["run_repo"]
    executor: PipelineExecutor = ctx["pipeline_executor"]
    log_archive: LogArchiveService = ctx["log_archive"]

    # claim_for_worker 把状态从 queued → preparing
    run = await run_repo.claim_for_worker(run_id, worker_id=ctx["worker_id"])
    if not run:
        return

    if run.cancel_requested_at:
        if await run_repo.cancel_if_current(run.id, expected=RunStatus.PREPARING):
            await publish_status_change(run.id, "cancelled", None)
        return

    try:
        # preparing 阶段：git-sync、依赖安装、容器创建等由 executor 内部完成。
        # executor.execute() 内部在容器实际启动后调用 mark_running(run.id)，
        # 在测试执行完成、进入结果收集前调用 mark_collecting(run.id)。
        status = await executor.execute(run, run.pipeline)

        await run_repo.finish_if_current(
            run.id,
            status=status,
            expected_in={RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.COLLECTING},
        )
        await publish_status_change(run.id, status.value, run.summary)
    except Exception as exc:
        await run_repo.fail_if_current(
            run.id,
            expected_in={RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.COLLECTING},
            message=str(exc),
        )
        await publish_status_change(run.id, "failed", {"error": str(exc)})
        # 不 re-raise：arq job 视为正常完成，避免触发 arq 内置重试。
        # 平台级重试由 domain.services.execution 根据 RetryPolicy 创建新 Run attempt。
    finally:
        # 无论终态是否由本 Worker 写入，都 best-effort 归档日志
        await log_archive.archive_log_stream(run.id, best_effort=True)
        await run_repo.release_worker(run.id, worker_id=ctx["worker_id"])
```

---

## 7. 实时通信设计

### 7.1 SSE（Server-Sent Events）架构

```python
@router.get("/runs/{run_id}/logs")
async def stream_logs(
    run_id: UUID,
    request: Request,
    last_event_id: str | None = Header(None),
):
    """SSE 端点：实时推送执行日志"""

    async def event_generator():
        cursor = last_event_id or "0"  # 支持断线重连
        terminal_seen = False
        run_status: str | None = None

        while True:
            # 从 Redis Stream 读取；终态后切到非阻塞排空模式，避免丢尾部日志。
            read_kwargs = {"count": 100}
            if not terminal_seen:
                read_kwargs["block"] = 5000  # 5s 长轮询

            entries = await redis.xread(
                {f"run:{run_id}:logs": cursor},
                **read_kwargs,
            )

            if entries:
                for stream_name, messages in entries:
                    for msg_id, data in messages:
                        cursor = msg_id
                        yield {
                            "id": msg_id,
                            "event": "log",
                            "data": json.dumps(data),
                        }
            elif terminal_seen:
                yield {"event": "done", "data": json.dumps({"status": run_status})}
                break
            else:
                # 发送心跳保持连接
                yield {"event": "heartbeat", "data": ""}

            if terminal_seen:
                continue

            # 检查 Run 是否已结束。Worker 必须先写完日志，再写终态状态。
            run_status = await redis.hget(f"run:{run_id}:status", "status")
            if run_status in TERMINAL_STATUSES:
                terminal_seen = True

    return EventSourceResponse(event_generator())
```

#### 7.1.1 并发连接管理

每个 SSE 客户端连接持有独立的 Redis XREAD 长轮询。当多个客户端订阅同一 Run 时，会产生并发 Redis 连接压力。

**缓解策略：**
- **单 Run 连接数上限：** 每个 Run 的 SSE 连接数限制为 20（可配置），超出返回 HTTP 429
- **API Server 粘性：** 多实例部署时，按 `run_id` 做连接粘性（Nginx/Caddy 的 ip_hash 或 cookie），避免跨实例重复读取
- **长连接超时：** 客户端 30s 无数据则发送心跳；服务端 5 分钟无活动主动断开

> **长期优化：** 如果同一 Run 的并发查看者超过 50，可在 API Server 内引入进程级 fan-out（一个 reader 读 Redis Stream，广播到所有该 Run 的 SSE 连接）。MVP 阶段不实现。

#### 7.1.2 SSE 认证

浏览器原生 `EventSource` API 不支持自定义 Header，无法直接传递 Bearer token。解决方案：

1. **前端使用 `fetch` + `ReadableStream`**（推荐）：前端不使用 `EventSource`，改用 `fetch(url, {headers: {Authorization: ...}})` 获取 SSE 流，通过 `response.body.getReader()` 逐行解析 SSE 事件。这是最简单且安全的方案。
2. **短期签名 URL**（备选）：`POST /api/v1/runs/{id}/logs/token` 返回一个短期有效（5 分钟）的签名 token，客户端拼接为 `GET /runs/{id}/logs?token={signed_token}`。签名使用 HMAC-SHA256，payload 包含 `run_id + user_id + expires_at`。

> **安全约束：** SSE 端点不接受 Cookie 认证（防止跨站静默订阅）。refresh 端点必须是 POST，不接受 GET。

#### 7.1.3 日志 S3 降级

当 Redis Stream 已过期（TTL 到期被删除）但客户端请求历史日志时，SSE 端点自动降级到 S3 JSONL 归档：

1. 尝试 XREAD Redis Stream
2. 若 Stream 不存在，检查 `logs/{run_id}.jsonl` 是否存在于 S3
3. 存在则流式读取 JSONL 逐行推送，最后发送 `done` 事件
4. 不存在则返回 HTTP 404

除了日志流，Run 状态变更也通过 SSE 推送：

```python
from datetime import datetime, timezone

# 发布端（Worker）— 使用 Redis Stream 而非 Pub/Sub，支持多 API Server 实例
async def publish_status_change(run_id: str, status: str, summary: dict | None):
    """
    发布 Run 状态变更。
    调用方必须保证：终态发布前，日志 Stream 已经写完；SSE 端依赖 status Hash 进入排空模式。
    """
    now = datetime.now(timezone.utc).isoformat()

    await redis.xadd(f"run:{run_id}:events", {
        "type": "status_change",
        "status": status,
        "summary": json.dumps(summary) if summary else "",
        "timestamp": now,
    }, maxlen=100)

    await redis.hset(f"run:{run_id}:status", mapping={
        "status": status,
        "updated_at": now,
    })
    if status in TERMINAL_STATUSES:
        await redis.expire(f"run:{run_id}:status", 3600)

# 订阅端（API Server SSE）— 支持断线重连（last_event_id）
@router.get("/runs/{run_id}/events")
async def stream_events(run_id: UUID, last_event_id: str | None = Header(None)):
    async def generator():
        cursor = last_event_id or "0"
        terminal_seen = False
        while True:
            read_kwargs = {"count": 50}
            if not terminal_seen:
                read_kwargs["block"] = 5000

            entries = await redis.xread(
                {f"run:{run_id}:events": cursor},
                **read_kwargs,
            )
            if entries:
                for stream_name, messages in entries:
                    for msg_id, data in messages:
                        cursor = msg_id
                        yield {"id": msg_id, "event": "status", "data": json.dumps(data)}
            elif terminal_seen:
                break
            else:
                yield {"event": "heartbeat", "data": ""}

            if terminal_seen:
                continue

            # 检查终态；进入非阻塞排空模式后再结束连接。
            run_status = await redis.hget(f"run:{run_id}:status", "status")
            if run_status in TERMINAL_STATUSES:
                terminal_seen = True
    return EventSourceResponse(generator())
```

---

## 8. 安全架构

### 8.1 认证与授权

┌─────────────────────────────────────────────────────────┐
│                    认证层                                 │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐ │
│  │ JWT Auth │  │API Token │  │ OIDC (v1.1)           │ │
│  │(Web 用户)│  │(机器调用)│  │(企业 SSO)             │ │
│  └─────┬────┘  └─────┬────┘  └───────────┬───────────┘ │
│        └──────────────┼───────────────────┘             │
│                       ▼                                 │
│              ┌────────────────┐                         │
│              │ Identity (who) │                         │
│              └───────┬────────┘                         │
└──────────────────────┼──────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│                    授权层                                  │
│                                                          │
│  ┌─────────────────┐    ┌─────────────────────────────┐ │
│  │ Global Role     │    │ Resource Permission          │ │
│  │ (platform_admin)│    │ (project_member.role)        │ │
│  └────────┬────────┘    └──────────────┬──────────────┘ │
│           └──────────────┬─────────────┘                 │
│                          ▼                               │
│              ┌─────────────────────┐                     │
│              │ Permission Decision │                     │
│              │ (allow / deny)      │                     │
│              └─────────────────────┘                     │
└──────────────────────────────────────────────────────────┘

Web UI 认证采用 `HttpOnly + Secure + SameSite=Lax` Cookie 保存 refresh token，access token 保存在内存并通过 `Authorization: Bearer` 调用 API。会产生服务端状态变更的 Cookie 认证请求必须携带 `X-CSRF-Token`，服务端用双提交 token 校验；纯 Bearer Token 的 API Token / CI 调用不需要 CSRF。SSE 订阅只读，可使用 Bearer token 或短期签名 URL，不接受跨站 Cookie 静默订阅。

### 8.2 权限决策逻辑

```python
class PermissionChecker:
    ROLE_PERMISSIONS = {
        "owner": {"*"},
        "maintainer": {"project.read", "project.edit", "run.trigger", "run.read", "run.cancel", "config.edit"},
        "developer": {"project.read", "run.trigger", "run.read", "run.cancel.own"},
        "viewer": {"project.read", "run.read"},
    }

    async def check(self, user: User, action: str, resource: Resource) -> bool:
        # 平台管理员：全部通过
        if user.role == "platform_admin":
            return True

        # 查找项目级角色
        membership = await self.get_membership(user.id, resource.project_id)
        if not membership:
            return False

        # 检查角色对应权限
        allowed = self.ROLE_PERMISSIONS.get(membership.role, set())
        if action in allowed or "*" in allowed:
            return True

        # Phase 1 资源级规则：developer 只能取消本人触发的 Run。
        if action == "run.cancel" and "run.cancel.own" in allowed:
            return isinstance(resource, Run) and resource.triggered_by == user.id

        return False
```

### 8.2.1 多租户隔离策略

MVP 单租户实现：
- `tenant`、`project`、`user`、`credential`、`run`、`project_member` 等权限/审计关键表保留 `tenant_id` 字段；`environment`、`pipeline`、`test_result`、`artifact` 等明细表通过 `project_id` / `run_id` 继承租户归属
- 应用层在 `dependencies.py` 中硬编码默认 tenant_id，所有仓储查询从当前 tenant 可见的 project/run 范围出发；DB 通过复合外键防止跨租户/跨项目误关联
- `user` 表 UNIQUE 约束为 `(tenant_id, username)` 和 `(tenant_id, email)`

**tenant_id 字段规则：**

| 策略 | 适用表 | 原因 |
|------|--------|------|
| 直接带 `tenant_id` | tenant, user, project, credential, run, project_member, audit.event | 权限判断/审计需要直接按租户过滤 |
| 通过 `project_id` 继承 | environment, pipeline, schedule, notification_rule, notification_log | 始终通过 project 访问，复合 FK 保证不跨项目 |
| 通过 `run_id` 继承 | test_result, artifact, run_event | 始终通过 run 访问，run 已带 tenant_id |

Phase 4+ 启用 RLS：
```sql
-- 直接带 tenant_id 的表使用 tenant_id policy
ALTER TABLE project ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON project USING (tenant_id = current_setting('app.current_tenant')::UUID);

ALTER TABLE run ENABLE ROW LEVEL SECURITY;
CREATE POLICY run_tenant_isolation ON run USING (tenant_id = current_setting('app.current_tenant')::UUID);

-- 明细表通过 run 反查租户，不要求每张明细表重复 tenant_id
ALTER TABLE test_result ENABLE ROW LEVEL SECURITY;
CREATE POLICY result_tenant_isolation ON test_result USING (
    EXISTS (
        SELECT 1
        FROM run
        WHERE run.id = test_result.run_id
          AND run.tenant_id = current_setting('app.current_tenant')::UUID
    )
);
```
- API Server 通过中间件从 JWT 中提取 tenant_id，调用 `SET LOCAL app.current_tenant`
- 迁移成本低：MVP 已在查询层注入 tenant_id，切换到 RLS 只需添加 policy

### 8.3 敏感数据加密

```python
class CryptoService:
    """
    使用 AES-256-GCM 加密敏感数据。
    密钥从环境变量加载，支持密钥轮转。

    密文格式: header(1) + nonce(12) + ciphertext(N)
    header 高 4 位 = format_version，低 4 位 = key_version（支持最多 16 个密钥并存）
    """

    def __init__(self, keys: dict[int, bytes]):
        # keys: {key_version: 32-byte key}，至少包含当前活跃密钥
        if not keys:
            raise ValueError("At least one encryption key is required")
        invalid_versions = [version for version in keys if version < 0 or version > 15]
        if invalid_versions:
            raise ValueError(f"Key version must be 0-15, got: {invalid_versions}")
        self._keys = keys
        self._current_key_version: int = max(keys.keys())

    def encrypt(self, plaintext: str, context_id: str = "") -> bytes:
        """
        加密敏感数据。context_id 作为 AAD 绑定密文到特定资源，
        防止密文被移植到其他记录（如 credential_id 或 tenant_id:project_id:credential_id）。
        """
        nonce = os.urandom(12)
        aad = context_id.encode() if context_id else None
        cipher = AESGCM(self._keys[self._current_key_version])
        ciphertext = cipher.encrypt(nonce, plaintext.encode(), aad)
        header = (0x1 << 4) | self._current_key_version  # format=1, key_version
        return bytes([header]) + nonce + ciphertext

    def decrypt(self, data: bytes, context_id: str = "") -> str:
        header = data[0]
        format_version = (header >> 4) & 0x0F
        key_version = header & 0x0F
        if format_version != 1:
            raise ValueError(f"Unsupported format version: {format_version}")
        if key_version not in self._keys:
            raise ValueError(f"Unknown key version: {key_version} (available: {list(self._keys.keys())})")
        nonce = data[1:13]
        ciphertext = data[13:]
        aad = context_id.encode() if context_id else None
        cipher = AESGCM(self._keys[key_version])
        return cipher.decrypt(nonce, ciphertext, aad).decode()
```

### 8.4 容器安全策略

```python
SANDBOX_SECURITY = {
    # 禁止特权提升
    "no_new_privileges": True,
    # 只读根文件系统
    "readonly_rootfs": True,
    # Docker 默认 seccomp 不需要显式配置；自定义时填 profile json 路径
    "seccomp_profile": None,
    # 移除所有 capabilities
    "cap_drop": ["ALL"],
    # 按需添加最小权限
    "cap_add": [],
    # 限制 PID 数（防止 fork 炸弹）
    "pids_limit": 256,
    # 禁止访问宿主机设备
    "devices": [],
}
```

### 8.5 频率限制

```python
class SlidingWindowRateLimiter:
    """
    Redis Sorted Set 实现的滑动窗口频率限制。
    """

    CHECK_SCRIPT = """
    local key = KEYS[1]
    local limit = tonumber(ARGV[1])
    local now = tonumber(ARGV[2])
    local window = tonumber(ARGV[3])
    local member = ARGV[4]

    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    local count = redis.call('ZCARD', key)
    if count >= limit then
        redis.call('EXPIRE', key, window)
        return 0
    end

    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window)
    return 1
    """

    async def check(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        allowed = await self.redis.eval(
            self.CHECK_SCRIPT,
            1,
            key,
            limit,
            now,
            window_seconds,
            str(uuid4()),
        )
        return bool(allowed)
```

---

## 9. 可观测性设计

### 9.1 结构化日志

```python
import structlog

# 配置 structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
)

# 使用
log = structlog.get_logger()

async def execute_run(run_id: str):
    structlog.contextvars.bind_contextvars(
        run_id=run_id,
        trace_id=correlation_id.get(),
    )
    log.info("run.started", project_id=run.project_id, trigger=run.trigger_type)
    ...
    log.info("run.completed", status="done", duration_ms=1234)
```

输出格式：

```json
{
  "timestamp": "2026-05-15T10:30:00.123Z",
  "level": "info",
  "event": "run.started",
  "run_id": "abc-123",
  "trace_id": "trace-xyz",
  "project_id": "proj-456",
  "trigger": "manual"
}
```

### 9.2 Prometheus 指标

```python
from prometheus_client import Counter, Histogram, Gauge

# 执行计数
runs_total = Counter(
    "qaplatform_runs_total",
    "Total number of runs",
    ["project", "status", "trigger_type"],
)

# 执行耗时
run_duration = Histogram(
    "qaplatform_run_duration_seconds",
    "Run execution duration",
    ["project"],
    buckets=[30, 60, 120, 300, 600, 1200, 1800, 3600],
)

# 队列深度
queue_depth = Gauge(
    "qaplatform_queue_depth",
    "Number of runs in queue",
    ["priority"],
)

# Worker 活跃数
workers_active = Gauge(
    "qaplatform_workers_active",
    "Number of active workers",
)

# API 延迟
http_duration = Histogram(
    "qaplatform_http_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint", "status"],
)
```

### 9.3 OpenTelemetry 追踪

```python
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

# 自动注入
FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine)
RedisInstrumentor().instrument()

# 手动 span（关键路径）
tracer = trace.get_tracer("qaplatform.engine")

async def execute_pipeline(run: Run):
    with tracer.start_as_current_span("pipeline.execute") as span:
        span.set_attribute("run.id", str(run.id))
        span.set_attribute("project.id", str(run.project_id))

        for stage in pipeline.stages:
            with tracer.start_as_current_span(f"stage.{stage.name}"):
                await execute_stage(stage)
```

### 9.4 健康检查

```python
@router.get("/health")
async def health_check():
    checks = {
        "database": await check_db(),
        "redis": await check_redis(),
        "storage": await check_s3(),
        "docker": await check_docker(),
    }
    all_healthy = all(c["status"] == "ok" for c in checks.values())
    return JSONResponse(
        status_code=200 if all_healthy else 503,
        content={"status": "healthy" if all_healthy else "degraded", "checks": checks},
    )

@router.get("/ready")
async def readiness_check():
    """就绪检查：数据库迁移完成 + 核心服务可用"""
    ...
```

---

## 10. 部署架构

### 10.1 Docker Compose（开发 + 小团队生产）

```yaml
# docker-compose.yml
services:
  api:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://qap:qap@postgres:5432/qaplatform
      - REDIS_URL=redis://redis:6379/0
      - S3_ENDPOINT=http://minio:9000
      - S3_ACCESS_KEY=minioadmin
      - S3_SECRET_KEY=minioadmin
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
      - JWT_SECRET=${JWT_SECRET}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile.worker
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # Docker socket 挂载（不是 DinD）
      # 安全提示：生产环境建议使用 Docker Socket Proxy（tecnativa/docker-socket-proxy）
      # 限制 Worker 只能调用 containers/create、containers/start 等必要 API
      - workspace:/workspace
    environment:
      - DATABASE_URL=postgresql+asyncpg://qap:qap@postgres:5432/qaplatform
      - REDIS_URL=redis://redis:6379/0
      - S3_ENDPOINT=http://minio:9000
      - DOCKER_HOST=unix:///var/run/docker.sock
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  scheduler:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile.worker
    command: ["python", "-m", "qaplatform.worker.scheduler"]
    environment:
      - DATABASE_URL=postgresql+asyncpg://qap:qap@postgres:5432/qaplatform
      - REDIS_URL=redis://redis:6379/0
    healthcheck:
      test: ["CMD", "python", "-c", "import redis; r=redis.from_url('redis://redis:6379/0'); assert r.exists('scheduler:heartbeat')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  frontend:
    build:
      context: ./frontend
      dockerfile: ../deploy/docker/Dockerfile.frontend
    ports:
      - "3000:80"

  postgres:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=qaplatform
      - POSTGRES_USER=qap
      - POSTGRES_PASSWORD=qap
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U qap"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    volumes:
      - miniodata:/data
    ports:
      - "9001:9001"  # MinIO Console

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile
      - caddydata:/data

volumes:
  pgdata:
  redisdata:
  miniodata:
  workspace:
  caddydata:

networks:
  qap-restricted:
    name: qap-restricted
    driver: bridge
    internal: true
```

`qap-restricted` 是测试执行容器使用的受限网络，不是 API/Worker 服务通信网络。部署脚本需要确保该网络存在；如果不依赖 Compose 创建，可在启动前执行一次幂等初始化：`docker network inspect qap-restricted >/dev/null 2>&1 || docker network create --internal qap-restricted`。

生产 Compose 不直接挂载宿主 Docker Socket，必须通过 Docker Socket Proxy 暴露最小 API 面：

```yaml
# docker-compose.prod.yml override
services:
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    environment:
      - CONTAINERS=1
      - IMAGES=1
      - NETWORKS=1
      - INFO=1
      - POST=1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro

  worker:
    volumes:
      - workspace:/workspace
    environment:
      - DOCKER_HOST=tcp://docker-socket-proxy:2375
    depends_on:
      docker-socket-proxy:
        condition: service_started
```

### 10.2 生产部署拓扑

                    ┌─────────────────────┐
                    │   Load Balancer     │
                    │   (Caddy / Nginx)   │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
       ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
       │ API Server  │ │ API Server │ │  Frontend   │
       │ (instance 1)│ │ (instance 2)│ │  (CDN/静态) │
       └──────┬──────┘ └─────┬──────┘ └─────────────┘
              │               │
              └───────┬───────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
  ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐
  │PostgreSQL │ │  Redis  │ │   MinIO   │
  │(主+只读副 │ │(Sentinel│ │ (集群/S3) │
  │  本)      │ │  /集群) │ │           │
  └───────────┘ └─────────┘ └───────────┘

        ┌─────────────────────────────┐
        │        Worker Pool          │
        │  ┌────┐ ┌────┐ ┌────┐      │
        │  │ W1 │ │ W2 │ │ W3 │ ... │
        │  └──┬─┘ └──┬─┘ └──┬─┘      │
        └─────┼──────┼──────┼────────┘
              │      │      │
        ┌─────▼──────▼──────▼────────┐
        │      Docker Engine          │
        │  (每个 Worker 宿主机)       │
        └─────────────────────────────┘

### 10.3 Kubernetes 部署（v2）

```yaml
# 关键资源概览
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qaplatform-api
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: api
          image: qaplatform/api:latest
          resources:
            requests: { cpu: "250m", memory: "512Mi" }
            limits: { cpu: "1", memory: "1Gi" }
          livenessProbe:
            httpGet: { path: /health, port: 8000 }
          readinessProbe:
            httpGet: { path: /ready, port: 8000 }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qaplatform-worker
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: worker
          image: qaplatform/worker:latest
          resources:
            requests: { cpu: "500m", memory: "1Gi" }
            limits: { cpu: "2", memory: "4Gi" }
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: qaplatform-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: qaplatform-worker
  minReplicas: 1
  maxReplicas: 10
  metrics:
    - type: External
      external:
        metric:
          name: qaplatform_queue_depth
        target:
          type: AverageValue
          averageValue: "3"  # 每 Worker 3 个排队任务时扩容
```

---

## 11. 配置管理

### 11.1 配置层次

环境变量（最高优先级，部署时注入）
    ↓ 覆盖
.env 文件（本地开发）
    ↓ 覆盖
config/default.toml（代码仓库内的默认值）

### 11.2 配置模型

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 核心
    app_name: str = "QA Platform"
    debug: bool = False
    environment: str = "development"  # development / staging / production

    # 数据库
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str
    redis_max_connections: int = 50

    # 对象存储
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "qa-platform"
    s3_region: str = "us-east-1"

    # 安全
    jwt_secret: str
    jwt_access_token_ttl: int = 3600       # 1h
    jwt_refresh_token_ttl: int = 604800    # 7d
    encryption_key: str                     # 32 bytes hex
    encryption_keys: dict[int, str] | None = None  # 密钥轮转：{version: key_hex}，优先于 encryption_key

    # 执行引擎
    max_concurrent_runs: int = 5
    max_concurrent_per_project: int = 3
    default_timeout_seconds: int = 1800
    preparing_timeout_seconds: int = 300
    collecting_timeout_seconds: int = 180
    max_event_chain_depth: int = 5          # Event 触发链最大深度，防止循环
    docker_host: str = "unix:///var/run/docker.sock"

    # 频率限制
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_auth_failure: int = 5        # 认证失败专用限流：5 次/分钟/IP
    rate_limit_auth_failure_window: int = 60

    # 数据保留
    retention_runs_days: int = 90
    retention_reports_days: int = 30
    retention_audit_days: int = 1095    # 3 年

    # 可观测性
    otel_exporter_endpoint: str | None = None
    log_level: str = "INFO"
    log_format: str = "json"  # json / console

    class Config:
        env_file = ".env"
        env_prefix = "QAP_"
```

---

## 12. 错误处理与韧性

### 12.0 JSONB 迁移策略

JSONB 字段（stages、selector、trigger_config、summary、settings 等）采用防御性解析策略：

1. **代码层**：使用 Pydantic model + `model_validate(extra="ignore")` 解析，兼容缺失字段和新增字段
2. **迁移层**：Alembic 迁移脚本中对 JSONB 结构性变更增加数据补全步骤（如为已有记录填充新字段默认值）
3. **约束**：JSONB 字段嵌套不超过 2 层，保持 GIN 索引和查询的可维护性
4. **版本标注**：代码中对 JSONB 结构变更使用 Pydantic model 版本号追踪，避免隐式 schema 漂移

### 12.0.1 DDL 迁移策略

Alembic 迁移遵循零停机原则（expand-contract 模式）：

1. **加列**：`ALTER TABLE ADD COLUMN ... DEFAULT ...`（PG 11+ 不锁表）
2. **删列**：先在代码中停止读写 → 部署 → 再迁移删列
3. **改类型**：加新列 → 双写 → 回填 → 切读 → 删旧列
4. **大表 DDL**：使用 `CREATE INDEX CONCURRENTLY`（不阻塞写入）；`ALTER TABLE` 加 `lock_timeout` 防止长时间等锁
5. **数据回填**：批量处理（每批 1000 行 + `COMMIT`），避免长事务和 WAL 膨胀

> Phase 1 数据量小，可直接执行 DDL。此策略为 Phase 2+ 数据增长后的安全网。

### 12.1 错误分类

┌──────────────────┬──────────────────────┬────────────────────────────┐
│       类别       │       处理策略       │            示例            │
├──────────────────┼──────────────────────┼────────────────────────────┤
│ 客户端错误 (4xx) │ 立即返回，不重试     │ 参数校验失败、权限不足     │
├──────────────────┼──────────────────────┼────────────────────────────┤
│ 可恢复错误       │ 自动重试（指数退避） │ 网络超时、S3 暂时不可用    │
├──────────────────┼──────────────────────┼────────────────────────────┤
│ 不可恢复错误     │ 标记失败，告警       │ 镜像不存在、磁盘满         │
├──────────────────┼──────────────────────┼────────────────────────────┤
│ 部分失败         │ 降级服务             │ 通知发送失败不影响执行结果 │
└──────────────────┴──────────────────────┴────────────────────────────┘

### 12.2 重试策略

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((IOError, ConnectionError)),
)
async def upload_artifact(path: Path, s3_key: str):
    ...
```

### 12.3 断路器

```python
class CircuitOpenError(Exception):
    """断路器处于打开状态，拒绝请求"""
    pass

class CircuitBreaker:
    """
    保护对外部服务的调用。
    状态：closed → open → half_open → closed
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failures = 0
        self.threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "closed"
        self.last_failure_time = None
        self._half_open_probe_in_flight = False
        self._lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        probe = False
        async with self._lock:
            if self.state == "open":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "half_open"
                    self._half_open_probe_in_flight = True
                    probe = True
                else:
                    raise CircuitOpenError()
            elif self.state == "half_open":
                if self._half_open_probe_in_flight:
                    raise CircuitOpenError()
                self._half_open_probe_in_flight = True
                probe = True

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                if probe and self.state == "half_open":
                    self.state = "closed"
                    self._half_open_probe_in_flight = False
                self.failures = 0
            return result
        except Exception:
            async with self._lock:
                if probe:
                    self._half_open_probe_in_flight = False
                self.failures += 1
                self.last_failure_time = time.time()
                if probe or self.failures >= self.threshold:
                    self.state = "open"
            raise
```

### 12.4 优雅关闭

```python
async def graceful_shutdown(app: FastAPI):
    """
    收到 SIGTERM 后：
    1. 停止接受新请求（健康检查返回 503）
    2. 等待进行中的请求完成（最多 30s）
    3. Worker：停止消费新任务，等待当前任务完成
    4. 关闭数据库连接池
    5. 退出
    """
    app.state.shutting_down = True

    # 等待活跃请求完成，最多 30s；active_requests 由 HTTP middleware 增减。
    deadline = time.monotonic() + 30
    while app.state.active_requests > 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.5)

    # 关闭连接
    await app.state.db_pool.dispose()
    await app.state.redis.close()
```

---

## 13. 前端架构概览

### 13.1 技术栈

| 层 | 选型 | 说明 |
|------|------|------|
| 框架 | Vue 3 (Composition API) | SFC + `<script setup>` |
| 构建 | Vite 5 | 开发热更新 + 生产构建 |
| 状态管理 | Pinia | 轻量、TypeScript 友好 |
| 路由 | Vue Router 4 | 嵌套路由 + 路由守卫做权限检查 |
| UI 组件库 | Naive UI / Element Plus | 中文生态好、组件丰富 |
| HTTP 客户端 | Axios | 拦截器统一处理 token 刷新和错误 |
| SSE 客户端 | fetch + ReadableStream | 支持自定义 Header 传递 Bearer token |
| 图表 | ECharts | 趋势图、通过率图 |
| 类型 | TypeScript | 严格模式 |

### 13.2 目录结构

```
frontend/
├── src/
│   ├── api/            # API 调用封装（按资源分文件）
│   ├── components/     # 通用组件
│   ├── composables/    # 组合式函数（useSSE, useAuth, usePagination）
│   ├── layouts/        # 页面布局
│   ├── pages/          # 路由页面
│   ├── stores/         # Pinia stores
│   ├── types/          # TypeScript 类型定义
│   └── utils/          # 工具函数
├── public/
└── vite.config.ts
```

### 13.3 关键设计

- **Token 管理：** access token 存内存（Pinia store），refresh token 由 HttpOnly Cookie 管理。Axios 拦截器在 401 时自动调用 refresh 端点。
- **SSE 封装：** `useSSE(url)` composable 使用 `fetch` + `ReadableStream` 实现，支持 Bearer token、自动重连、背压控制。
- **路由权限：** 全局路由守卫检查用户角色和项目成员关系，未授权页面重定向到 403。

---

## 14. 测试策略

### 14.1 测试金字塔

        ┌───────────┐
        │   E2E     │  10%  — 关键用户旅程（Playwright）
        ├───────────┤
        │Integration│  30%  — API + DB + Redis 集成
        ├───────────┤
        │   Unit    │  60%  — 领域逻辑、工具函数
        └───────────┘

### 14.2 测试基础设施

```python
# 集成测试使用 testcontainers
import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()

@pytest.fixture(scope="session")
def redis():
    with RedisContainer("redis:7-alpine") as r:
        yield r.get_connection_url()

@pytest.fixture
async def client(postgres, redis):
    app = create_app(Settings(database_url=postgres, redis_url=redis))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

### 14.3 关键测试场景

┌──────────┬──────────────────────────────────────┐
│   模块   │               必须覆盖               │
├──────────┼──────────────────────────────────────┤
│ 执行引擎 │ 状态机转换、超时处理、并发限制、取消 │
├──────────┼──────────────────────────────────────┤
│ 权限     │ 每个角色 × 每个端点的 allow/deny     │
├──────────┼──────────────────────────────────────┤
│ 插件     │ 各格式的解析正确性、异常输入处理     │
├──────────┼──────────────────────────────────────┤
│ 调度     │ Cron 触发准确性、错过调度处理        │
├──────────┼──────────────────────────────────────┤
│ 通知     │ 条件匹配、幂等性、重试               │
└──────────┴──────────────────────────────────────┘

---

## 15. 演进路径

### 15.1 从单体到分布式的渐进路径

Phase 1 (MVP):
  单进程 API + 单 Worker + 本地 Docker
  ↓
Phase 2:
  多 Worker（同一台机器多个进程，或多台机器）
  ↓
Phase 3:
  API 无状态水平扩展 + Worker 按需伸缩
  ↓
Phase 4 (如果需要):
  拆分独立服务：执行引擎、调度服务、通知服务

### 15.2 模块可替换性

设计时预留的切换点：

┌──────────────┬─────────────┬──────────────────────────────┐
│     组件     │  当前实现   │           可切换到           │
├──────────────┼─────────────┼──────────────────────────────┤
│ 任务引擎     │ arq         │ Celery / Dramatiq / Temporal │
├──────────────┼─────────────┼──────────────────────────────┤
│ 执行后端     │ Docker      │ Kubernetes Job / Firecracker │
├──────────────┼─────────────┼──────────────────────────────┤
│ 对象存储     │ MinIO       │ AWS S3 / GCS / Azure Blob    │
├──────────────┼─────────────┼──────────────────────────────┤
│ 数据库       │ PostgreSQL  │ — (不建议切换)               │
├──────────────┼─────────────┼──────────────────────────────┤
│ 缓存         │ Redis       │ Valkey / DragonflyDB         │
├──────────────┼─────────────┼──────────────────────────────┤
│ 搜索（未来） │ PG 全文搜索 │ Elasticsearch / Meilisearch  │
└──────────────┴─────────────┴──────────────────────────────┘

每个切换点通过 Protocol (接口) 隔离，切换只需实现新的后端类并修改依赖注入配置。

---

## 附录 A: ADR 记录

#### ADR-001: 选择 arq 而非 Celery

- 状态: 已采纳
- 上下文: 需要异步任务执行引擎
- 决策: 使用 arq
- 理由: async 原生、API 简洁、同样依赖 Redis、足够满足当前规模
- 风险: 社区小、功能有限；已通过接口抽象降低切换成本

#### ADR-002: SSE 优先于 WebSocket

- 状态: 已采纳
- 上下文: 需要实时推送日志和状态
- 决策: 主用 SSE，WebSocket 作为保留方案
- 理由: 单向推送足够、HTTP 原生、自动重连、调试简单
- 风险: 需要双向通信时需升级；当前场景不需要

#### ADR-003: PostgreSQL 历史数据先归档、后分区

- 状态: 已采纳
- 上下文: run 和 test_result 表会持续增长
- 决策: MVP 使用普通表 + 覆盖索引 + 批量归档/删除；Phase 4+ 根据真实数据量再迁移到按时间分区
- 理由: PostgreSQL 分区表的主键/唯一约束必须包含分区键，会显著复杂化 `run` 与 `test_result`/`artifact` 的外键关系；MVP 数据量不需要提前承担该复杂度
- 风险: 历史数据持续增长后普通表清理会变慢；通过保留 `created_at` 索引和归档任务缓解，达到阈值后执行分区迁移

#### ADR-004: 后端采用严格分层目录（domain / api / engine / infra / plugins / worker）

- 状态: 已采纳
- 上下文: 需在「模块化单体」内约束依赖方向，并与 PRD 逻辑分层对齐
- 决策: 源码按层分包；领域规则在 `domain`，HTTP 在 `api`，容器与日志在 `engine`，ORM/Redis/S3 在 `infra`，可扩展点在 `plugins`，arq 任务在 `worker`
- 理由: 依赖可静态检查、领域可单测、执行与 IO 边界清晰
- 代价: 改动单功能常跨多层；通过小而稳定的领域服务与仓储接口缓解

---
