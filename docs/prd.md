---
# QA 自动化执行平台 — 产品需求文档 v3

> 设计哲学：把"执行"做成管道，把"一切"做成插件。

---

## 1. 核心洞察

测试执行平台本质上是一个**受控的代码运行器**——接收代码输入、在隔离环境中执行、收集结构化输出。它不应该关心你用什么框架、跑什么语言、产出什么格式。

平台的价值不在于"又一个 CI"，而在于：

1. **执行可复现** — 同样的输入永远产出同样的结果
2. **结果可比较** — 跨时间、跨环境、跨分支的质量变化一目了然
3. **反馈可达** — 对的人在对的时间收到对的信息
4. **过程可观测** — 不是提交后等结果，而是全程透明

---

## 2. 系统边界

### 2.1 平台做什么

- 拉取代码、准备环境、执行测试、收集产物、呈现结果、触发通知
- 提供统一的质量视图和趋势分析
- 暴露完整 API 供外部系统集成

### 2.2 平台不做什么

- 不写测试（那是开发者的事）
- 不做代码构建（那是 CI 的事，平台假设代码已可执行）；平台可以安装测试运行依赖（如 pip/npm/go mod），但不负责编译、打包、制品发布等构建职责
- 不做部署（那是 CD 的事）
- 不做测试用例管理（那是 TestRail/Xray 的事，但可以对接）

---

## 3. 架构设计

### 3.1 分层架构

┌─────────────────────────────────────────────────┐
│                   Gateway Layer                   │
│       FastAPI (HTTP + SSE；WebSocket 预留)        │
├─────────────────────────────────────────────────┤
│                  Domain Layer                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Projects │ │ Runs     │ │ Quality Insights │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│                 Engine Layer                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Executor │ │ Collector│ │ Scheduler        │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│               Infrastructure Layer               │
│  PostgreSQL │ Redis │ S3/MinIO │ Docker Engine   │
└─────────────────────────────────────────────────┘

### 3.2 技术选型

| 层 | 选型 | 决策理由 |
|----|------|----------|
| API 框架 | FastAPI | async 原生、自动 OpenAPI、Pydantic 校验、生态活跃 |
| 任务引擎 | arq (Redis-based) | 轻量、async 原生、比 Celery 更简单的 API |
| 数据库 | PostgreSQL 16 | JSONB、事务一致性、行级安全预留、后期分区演进 |
| 缓存/队列 | Redis 7 (Valkey) | arq broker + 缓存 + 实时状态 |
| 对象存储 | S3 协议 (MinIO 开发/S3 生产) | 报告和产物存储，天然支持多节点 |
| 执行隔离 | Docker (开发) / Kubernetes Job (生产) | 统一容器接口，后端可切换 |
| 实时通信 | SSE (Server-Sent Events) | 比 WebSocket 简单、HTTP/2 友好、足够满足单向推送 |
| 前端 | Vue 3 + Vite | 比 React 更轻量、模板语法适合快速迭代、中文生态好 |
| ORM | SQLAlchemy 2.0 (async) | 成熟、类型安全、async session 支持 |
| 迁移 | Alembic | SQLAlchemy 生态标配 |

### 3.3 源码布局（已定稿）

PRD 中的 4 层是产品视角的逻辑分层；架构文档会把它展开成 6 个源码边界（`domain / api / engine / infra / plugins / worker`）。对应关系是：Gateway → `api`，Domain → `domain`，Engine → `engine + worker + plugins`，Infrastructure → `infra`。详细目录与依赖规则见 `docs/architecture.md`。

### 3.4 关键设计决策

**为什么不用 Celery？**

Celery 功能强大但过于复杂。测试执行任务的特点是：数量不大（每天几十到几百次）、单任务时间长（分钟级）、需要细粒度状态追踪。arq 更适合：async 原生、代码更简洁、Redis 依赖相同、job 状态内置。

**为什么用 SSE 而不是 WebSocket？**

执行日志和状态推送是单向的（服务端→客户端）。SSE 基于标准 HTTP、自动重连、不需要自定义协议、调试更简单。需要双向通信的场景（如远程终端）再升级到 WebSocket。

**为什么用 PostgreSQL 而不是 MySQL？**

JSONB 存储灵活的执行元数据、Redis Stream 驱动实时事件、普通表先保证外键和迁移简单，历史数据增长后再演进到分区表，行级安全策略简化企业版权限实现。

---

## 4. 核心领域模型

### 4.1 概念图

Tenant (workspace)
  └── Project
        ├── git_url / auth / branch (Git 仓库配置，内嵌于 Project)
        ├── Environment (执行环境定义)
        │     ├── base_image: str
        │     ├── setup_script: str
        │     └── env_vars: dict (非敏感变量；敏感值存 Credential 表)
        ├── Pipeline (执行流水线定义)
        │     ├── stages: list[Stage]
        │     ├── trigger: Trigger
        │     └── selector: Selector
        ├── Schedule (定时计划)
        ├── ProjectMember (项目成员)
        ├── NotificationRule (通知规则)
        └── Run (一次执行实例)
              ├── status: RunStatus
              ├── artifacts: list[Artifact]
              └── results: list[TestResult]
  └── AuditEvent (租户级审计事件)

### 4.2 核心实体

#### Project

项目是组织单元，绑定一个代码源。

```text
class Project:
    id: UUID
    tenant_id: UUID
    name: str              # 唯一（租户内）
    slug: str              # URL 友好标识
    # --- Git 仓库配置（内嵌，单一代码源）---
    git_url: str
    git_auth_method: "token" | "ssh_key" | "none"
    credential_id: UUID | None  # 引用加密凭证
    default_branch: str
    root_path: str         # monorepo 子路径
    shallow_clone: bool
    # ----------------------------------------
    default_env_id: UUID | None  # 默认执行环境；项目创建后可再绑定
    settings: ProjectSettings  # JSONB
    created_at: datetime

Environment (执行环境)

class Environment:
    id: UUID
    project_id: UUID
    name: str
    base_image: str        # e.g. "python:3.12-slim"
    setup_script: str      # 环境初始化脚本
    resource_limits: ResourceLimits  # memory_mb, cpu_cores, max_artifact_size_mb, max_artifacts_count
    network_policy: "allow" | "deny" | "restricted"
    env_vars: dict  # 非敏感环境变量；合并优先级见本节“Stage 执行上下文”
    cache_key: str | None  # 依赖缓存指纹

Pipeline (执行管道)

class Pipeline:
    id: UUID
    project_id: UUID
    name: str
    stages: list[StageDefinition]  # 有序的阶段列表
    selector: TestSelector         # 用例选择规则
    trigger: TriggerConfig         # 触发配置
    timeout_seconds: int
    retry_policy: RetryPolicy | None
    enabled: bool

class TestSelector:
    include_paths: list[str]       # glob，例如 tests/api/**
    exclude_paths: list[str]
    tags: list[str]                # 框架标签/marker，AND 语义
    expression: str | None         # 可选表达式，例如 "smoke and not slow"
    regex: str | None              # 可选用例名正则
    on_empty: "fail" | "skip" | "warn"  # 默认 fail

选择器先应用 include/exclude 路径，再应用 tags/expression/regex。若最终没有发现用例，按 on_empty 处理：fail 产生 status=failed 的 Run，skip 产生 status=done 的 Run（summary 中 total=0 且标记 skipped_reason="no_tests_discovered"），warn 继续执行但在 Run summary 中记录告警。

class RetryPolicy:
    max_attempts: int              # 默认 1，即不重试
    retry_on: list["failed" | "timeout" | "infra_error"]
    backoff_seconds: int
    scope: "pipeline" | "stage"    # MVP 默认 pipeline；stage 级重试延后

MVP 的 retry_policy 只对基础设施失败和超时生效，不因测试断言失败自动重试；每次重试都会创建 Run attempt 记录，最终 Run 汇总最后一次尝试的结果。

Stage (阶段定义)

Pipeline 由多个 Stage 组成，每个 Stage 是一个独立的执行步骤：

class StageDefinition:
    name: str              # e.g. "setup", "test", "report"
    plugin: str            # 插件标识符
    config: dict           # 插件配置
    continue_on_error: bool
    phase: "prepare" | "execute" | "collect" | "notify" | None  # 可选，用于驱动 Run 状态机转换

内置 Stage 插件：
- git-sync — 克隆/拉取代码
- dependency-install — 安装依赖（pip/npm/go mod）
- test-run — 执行测试命令
- result-collect — 收集结构化结果
- report-generate — 生成 HTML 报告
- artifact-upload — 上传产物到对象存储
- notify — 发送通知

Stage 执行上下文中的环境变量按固定优先级合并：系统默认 < 项目配置 < Environment.env_vars < 触发时覆盖。敏感值不进入 env_vars 明文字段，只通过 Credential 引用解密后注入短生命周期环境变量。

Run (执行实例)

class Run:
    id: UUID
    tenant_id: UUID             # 冗余用于权限/审计；必须与 project.tenant_id 一致
    project_id: UUID
    pipeline_id: UUID
    status: "queued" | "preparing" | "running" | "collecting" | "done" | "failed" | "cancelled" | "timeout"
    trigger_type: "manual" | "schedule" | "webhook" | "api" | "event"
    priority: int               # 0=high, 1=medium, 2=low；由 trigger_type 映射
    triggered_by: UUID | None  # 用户 ID
    git_ref: str               # 分支/tag/commit
    git_sha: str | None        # 实际执行的 commit
    environment_id: UUID
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    # 重试
    retry_group_id: UUID | None    # 同一逻辑执行的多次 attempt 共享（首次等于 run.id）
    attempt: int                   # 当前第几次尝试，默认 1
    # 事件链路
    source_run_id: UUID | None     # Event 触发时的源 Run
    chain_depth: int               # 事件链深度，默认 0，超过 max_event_chain_depth 拒绝触发
    # 控制面
    dedup_key: str | None          # 幂等触发去重键
    queue_name: str | None         # queue:high / queue:medium / queue:low
    arq_job_id: str | None         # arq job id，用于队列撤销和幂等入队
    execution_id: str | None       # 容器 ID / K8s Job name
    worker_id: str | None
    enqueued_at: datetime | None
    cancel_requested_at: datetime | None
    status_updated_at: datetime
    summary: RunSummary | None  # JSONB: passed/failed/skipped counts
    error_message: str | None   # 失败原因（status=failed/timeout 时填充）
    metadata: dict              # JSONB: 任意扩展字段

TestResult (测试结果)

class TestResult:
    id: UUID
    run_id: UUID
    suite: str             # 文件路径或类名
    name: str              # 用例名
    status: "passed" | "failed" | "error" | "skipped" | "xfail"
    duration_ms: int
    error_message: str | None
    stack_trace: str | None
    tags: list[str]        # 标签（用于筛选和聚合）
    metadata: dict         # JSONB: 框架特有数据

Artifact (产物)

class Artifact:
    id: UUID
    run_id: UUID
    type: "report" | "log" | "screenshot" | "video" | "coverage" | "custom"
    name: str
    storage_path: str      # S3 key
    size_bytes: int
    mime_type: str
    expires_at: datetime | None

Credential (项目凭证)

class Credential:
    id: UUID
    tenant_id: UUID
    project_id: UUID       # MVP 项目私有；租户共享凭证延后
    name: str
    type: "token" | "ssh_key" | "password"
    encrypted_value: bytes # AES-256-GCM
    created_by: UUID
    created_at: datetime

Schedule (定时计划)

class Schedule:
    id: UUID
    project_id: UUID
    pipeline_id: UUID
    cron_expr: str
    timezone: str
    enabled: bool
    quiet_windows: list[QuietWindow]
    missed_fire_policy: "skip" | "run_once" | "run_all"
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_error: str | None         # 最近一次调度失败的错误信息

ProjectMember (项目成员)

class ProjectMember:
    project_id: UUID
    user_id: UUID
    role: "owner" | "maintainer" | "developer" | "viewer"
    created_at: datetime

NotificationRule (通知规则)

class NotificationRule:
    id: UUID
    project_id: UUID
    enabled: bool
    conditions: list[Condition]
    channels: list[ChannelConfig]
    template: str | None

AuditEvent (审计事件)

class AuditEvent:
    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    before_state: dict | None
    after_state: dict | None
    created_at: datetime

```

---

## 5. 功能模块

### 5.1 执行引擎（核心）

这是平台的心脏。一次 Run 的完整生命周期：

触发 → 入队 → 分配 Worker → 准备环境 → 逐阶段执行 → 收集结果 → 清理 → 完成

#### 执行隔离
每个 Run 在独立容器中执行：

- 资源隔离：CPU、内存、磁盘 quota
- 网络隔离：默认禁止外网，白名单放行
- 文件系统：代码只读挂载，结果目录读写，tmpfs 工作区
- 超时控制：硬超时（SIGKILL）+ 软超时（SIGTERM + 宽限期）

#### 并发模型
┌─────────────┐
│  Priority   │  优先级队列（紧急可插队）
│   Queue     │
└──────┬──────┘
       │
┌──────▼──────┐
│  Scheduler  │  调度器（公平调度 + 资源感知）
└──────┬──────┘
       │
┌──────▼──────┐
│  Worker Pool│  Worker 池（可配置大小）
│  [W1][W2]..│  每个 Worker 同时处理一个 Run
└─────────────┘

- 系统级最大并发数（默认 5）
- 项目级并发配额（防止单项目垄断资源）
- 队列优先级：manual > webhook / api / event > schedule
- 公平调度：同优先级下轮询项目

#### 日志流
执行过程中 stdout/stderr 实时推送：

- 日志写入 Redis Stream（TTL 24h，热数据）
- 执行完成后归档到 S3（冷数据）
- 客户端通过 SSE 订阅实时日志
- 支持历史日志分页查询

### 5.2 插件系统

平台核心是薄的，功能通过插件扩展：

#### 插件类型
┌───────────┬──────────┬────────────────────────────────────────┐
│   类型    │   职责   │                  示例                  │
├───────────┼──────────┼────────────────────────────────────────┤
│ Source    │ 代码获取 │ git, svn, local                        │
├───────────┼──────────┼────────────────────────────────────────┤
│ Runner    │ 测试执行 │ pytest, jest, go-test, custom-script   │
├───────────┼──────────┼────────────────────────────────────────┤
│ Collector │ 结果解析 │ junit-xml, allure-json, tap, go-json   │
├───────────┼──────────┼────────────────────────────────────────┤
│ Reporter  │ 报告生成 │ allure-html, custom-html               │
├───────────┼──────────┼────────────────────────────────────────┤
│ Notifier  │ 通知发送 │ email, dingtalk, wecom, slack, webhook │
├───────────┼──────────┼────────────────────────────────────────┤
│ Trigger   │ 触发源   │ cron, github-webhook, gitlab-webhook   │
└───────────┴──────────┴────────────────────────────────────────┘

#### 插件接口（Python Protocol）

```text
@dataclass
class PluginMeta:
    name: str
    version: str
    description: str
    config_schema: dict  # JSON Schema，用于校验配置

class RunnerPlugin(Protocol):
    meta: PluginMeta

    async def validate_config(self, config: dict) -> list[str]:
        """校验插件配置，返回错误列表"""
        ...

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        """执行测试，返回结果"""
        ...
```

> 插件发现通过 `entry_points` 机制（启动时加载）。运行时安装新插件需重启服务。长期可扩展为目录监控热加载。

```text
class CollectorPlugin(Protocol):
    meta: PluginMeta
    supported_formats: list[str]

    async def collect(self, results_dir: Path) -> list[TestResultData]:
        """从结果目录解析测试结果"""
        ...
```

#### 内置插件（MVP）
- Runner: pytest（支持参数传递、marker 筛选）
- Collector: junit-xml（默认）, allure-json
- Reporter: allure-html（默认）
- Notifier: email, dingtalk, wecom
- Trigger: cron, manual, api

### 5.3 项目管理

#### 项目生命周期
创建 → 配置 → 活跃 → 归档 → 删除

#### Git 集成
- HTTPS + Token 认证（MVP）
- SSH Key 认证（v1.1）
- OAuth App 授权（v2.0）
- 浅克隆 + 增量拉取
- 分支/Tag/Commit 灵活指定
- Monorepo 支持（指定子目录）

#### 测试发现
可配置的发现规则（而非硬编码）：

```yaml
discovery:
  patterns:
    - "tests/**/test_*.py"
    - "tests/**/*_test.py"
  exclude:
    - "**/conftest.py"
    - "**/fixtures/**"
  tags_from:
    - path_segments    # tests/api/test_user.py → tag:api
    - markers          # @pytest.mark.slow → tag:slow
    - docstring        # 从 docstring 提取描述
  on_empty: "fail"     # fail（默认）| skip | warn — 零测试用例时的行为
```

### 5.4 触发与调度

#### 触发类型
┌─────────┬───────────────────┬────────────────────────┐
│  类型   │       实现        │          场景          │
├─────────┼───────────────────┼────────────────────────┤
│ 手动    │ Web UI / API 调用 │ 开发调试、临时执行     │
├─────────┼───────────────────┼────────────────────────┤
│ 定时    │ Cron 表达式       │ 每日回归、定期巡检     │
├─────────┼───────────────────┼────────────────────────┤
│ Webhook │ HTTP 回调         │ PR 触发、代码推送      │
├─────────┼───────────────────┼────────────────────────┤
│ 事件    │ 内部事件总线      │ Run A 完成后触发 Run B │
└─────────┴───────────────────┴────────────────────────┘

> trigger_type 枚举值：manual / schedule / webhook / api / event

Event 触发配置示例：

```yaml
trigger_config:
  type: event
  source:
    event_type: "run.completed"
    project_id: "source-project-id"
    pipeline_id: "source-pipeline-id"
  conditions:
    status_in: ["done"]
    min_pass_rate: 0.95
  target:
    pipeline_id: "target-pipeline-id"
    git_ref: "{{ source.git_ref }}"
    environment_id: "{{ source.environment_id }}"
  dedup_window_seconds: 300
```

Webhook 触发必须校验来源签名：GitHub 使用 `X-Hub-Signature-256`，GitLab 使用 `X-Gitlab-Token` 或实例支持的 HMAC 签名。所有 Webhook Trigger 都必须保存 secret 的加密引用，并把外部 delivery id 作为 `event_id` 参与幂等键计算。

**事件链路保护：** Event 触发时传递 `source_run_id` 和 `chain_depth`，新 Run 的 `chain_depth = source_run.chain_depth + 1`。超过 `max_event_chain_depth`（默认 5）时拒绝触发，防止 A→B→A 循环导致无限 Run 创建。

#### 调度器设计
采用**独立 Scheduler 进程**（单例），从数据库读取 schedule 配置并触发执行：

- 调度配置存 DB，变更即时生效
- 支持时区（项目级配置）
- 错过的调度（missed fire）策略：skip / run_once / run_all
- 静默窗口：指定时间段内暂停触发
- 触发幂等：支持 `dedup_window_seconds`，按 `pipeline_id + trigger_type + git_ref/git_sha + event_id` 计算去重键；窗口内重复触发返回已存在的 Run
- Scheduler 进程崩溃后由进程管理器自动重启（docker compose / systemd）

### 5.5 结果与报告

#### 结果存储
- 结构化结果存 PostgreSQL（查询、聚合、趋势）
- HTML 报告存对象存储（静态托管）
- 原始产物（日志、截图）存对象存储（带 TTL）

#### 结果分析
- 通过率趋势：按天/周/月聚合
- 耗时分析：P50/P90/P99 分位数
- Flaky 检测：默认窗口为同一用例最近 20 次执行；状态翻转次数 ≥ 3 或失败率介于 20%-80% 时标记为 flaky；窗口和阈值按项目可配置
- 失败聚类：相同错误信息的用例自动归组
- 回归检测：与基线 Run 对比，标记新增失败

#### 报告托管
- 每个 Run 的报告通过唯一 URL 访问：/r/{run_id}/
- 报告文件存 S3，通过 presigned URL 或 CDN 分发
- 支持设置过期时间，过期自动清理

### 5.6 通知系统

#### 设计原则
- 通知是事件驱动的（不是轮询）
- 通知规则可组合（条件 + 渠道 + 模板）
- 通知幂等（同一事件不重复发送）

#### 通知规则

```text
class NotificationRule:
    project_id: UUID
    name: str
    enabled: bool
    conditions: list[Condition]  # AND 组合
    channels: list[ChannelConfig]
    template: str | None  # 自定义模板（Jinja2）
```

条件示例：
- run.status == "failed" — 执行失败时
- run.summary.pass_rate < 0.8 — 通过率低于 80%
- run.summary.pass_rate < previous_run.pass_rate — 通过率下降
- run.trigger_type == "schedule" — 仅定时执行

#### 渠道实现
每个渠道是一个 Notifier 插件：

- Email: aiosmtplib，支持 HTML 模板
- 钉钉: Webhook + Markdown 消息
- 企业微信: Webhook + Markdown 消息
- 通用 Webhook: POST JSON 到自定义 URL（用于对接任意系统）

### 5.7 质量看板

#### 全局看板
- 项目健康矩阵：每个项目的最近一次执行状态 + 通过率
- 执行队列：当前 running / queued 的 Run
- 系统负载：Worker 利用率、队列深度

#### 项目看板
- 通过率趋势图（可选粒度：日/周/月）
- 执行耗时趋势图
- Top 失败用例排行
- Flaky 用例列表
- 最近执行列表

#### 数据策略
- 热数据（7 天内）：实时查询
- 温数据（7-90 天）：预聚合表（每小时物化视图刷新）
- 冷数据（90 天+）：归档到对象存储，按需加载

### 5.8 用户与权限

#### 认证
- 本地账户（用户名 + 密码）+ JWT（access + refresh token）— MVP
- API Token（Bearer Token，格式 qap_{token_id}_{secret}）— MVP
- OIDC/OAuth2 SSO — v1.1

#### 多租户策略
- MVP：单租户，`tenant/project/user/credential/run` 等租户关键表保留 `tenant_id` 字段；测试结果、产物等明细表通过 `run_id` 继承租户归属
- v1.1+：启用 PostgreSQL Row-Level Security (RLS)，关键表按 `tenant_id` 隔离，明细表通过 `run` 反查租户
- 迁移路径：MVP 的所有仓储查询都从当前 tenant 出发，切换到 RLS 时补 policy；只在权限/审计关键表冗余 `tenant_id`

#### 权限模型
采用 RBAC + 资源级权限：

角色定义（全局）：
  - platform_admin: 平台管理员
  - user: 普通用户

资源级角色（项目粒度）：
  - owner: 项目所有者（全部权限）
  - maintainer: 维护者（配置 + 执行）
  - developer: 开发者（执行 + 查看）
  - viewer: 观察者（仅查看）

权限判断逻辑：
1. platform_admin → 全部通过
2. 检查项目级角色 → 对应权限集
3. 无角色 → 拒绝（除非项目设为公开可见）

Phase 1 最小权限矩阵（仅启用 `platform_admin / developer / viewer`；`owner / maintainer` 是 Phase 2 项目治理角色）：

| 能力 | platform_admin | developer | viewer |
|------|----------------|-----------|--------|
| 创建/编辑项目 | 允许 | 拒绝 | 拒绝 |
| 管理项目成员/凭证/环境/Pipeline | 允许 | 拒绝 | 拒绝 |
| 触发 Run | 允许 | 允许 | 拒绝 |
| 取消 Run | 允许 | 仅本人触发的 Run | 拒绝 |
| 查看 Run、日志、结果、产物 | 允许 | 允许 | 允许 |

`owner` / `maintainer` 在 Phase 2 引入，届时再开放项目配置和成员管理的资源级授权。

#### API Token
- 格式：qap_{token_id}_{secret}，`token_id` 为密码学安全随机数生成的公开定位符（`os.urandom(16).hex()`，不可使用 UUID 或递增序列），`secret` 为 32 bytes 随机值的 base62 编码
- 存储：`token_id` 明文索引用于查找，`secret` 使用 Argon2id 哈希存储并通过 verify 校验；不支持对完整 token 重新 hash 后等值查询
- 作用域：可限制到特定项目、特定操作
- 过期策略：必须设置过期时间（最长 1 年）
- 使用审计：记录每次使用的时间、IP、端点
- 安全限流：认证失败按 IP 做专用 rate limit（默认 5 次/分钟），独立于通用 API 限流，防止暴力破解

### 5.9 审计与合规

- 所有写操作产生审计事件
- 审计事件结构：who / what / when / where / before / after
- 存储在独立表，与业务数据生命周期解耦
- 支持导出（合规审查场景）

---

## 6. API 设计

### 6.1 原则

- RESTful + 资源导向
- 版本化（/api/v1/）
- 一致的错误格式
- 分页、筛选、排序遵循统一约定
- OpenAPI 3.1 自动生成

### 6.2 核心端点

```text
# 项目
GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{id}
PATCH  /api/v1/projects/{id}
DELETE /api/v1/projects/{id}

# 环境
GET    /api/v1/projects/{id}/environments
POST   /api/v1/projects/{id}/environments
PATCH  /api/v1/projects/{id}/environments/{env_id}

# Pipeline
GET    /api/v1/projects/{id}/pipelines
POST   /api/v1/projects/{id}/pipelines
PATCH  /api/v1/projects/{id}/pipelines/{pipe_id}

# 执行
POST   /api/v1/runs                    # 触发执行
GET    /api/v1/runs                    # 列表（支持筛选）
GET    /api/v1/runs/{id}               # 详情
POST   /api/v1/runs/{id}/cancel        # 取消
GET    /api/v1/runs/{id}/logs          # 日志（SSE 流）
GET    /api/v1/runs/{id}/results       # 测试结果
GET    /api/v1/runs/{id}/artifacts     # 产物列表

# 调度
GET    /api/v1/projects/{id}/schedules
POST   /api/v1/projects/{id}/schedules
PATCH  /api/v1/projects/{id}/schedules/{schedule_id}
DELETE /api/v1/projects/{id}/schedules/{schedule_id}

# 通知规则
GET    /api/v1/projects/{id}/notification-rules
POST   /api/v1/projects/{id}/notification-rules
PATCH  /api/v1/projects/{id}/notification-rules/{rule_id}
DELETE /api/v1/projects/{id}/notification-rules/{rule_id}

# 凭证
GET    /api/v1/projects/{id}/credentials
POST   /api/v1/projects/{id}/credentials
DELETE /api/v1/projects/{id}/credentials/{credential_id}

# 项目成员
GET    /api/v1/projects/{id}/members
POST   /api/v1/projects/{id}/members
PATCH  /api/v1/projects/{id}/members/{user_id}
DELETE /api/v1/projects/{id}/members/{user_id}

# 看板
GET    /api/v1/dashboard/overview      # 全局概览
GET    /api/v1/dashboard/projects/{id} # 项目看板数据

# 用户
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh            # 刷新 Token
POST   /api/v1/auth/tokens             # 创建 API Token
DELETE /api/v1/auth/tokens/{token_id}  # 撤销 API Token
GET    /api/v1/users/me
PATCH  /api/v1/users/me                # 更新个人信息

# 系统
GET    /api/v1/health
GET    /api/v1/system/config           # 系统配置（admin）
```

### 6.3 通用约定

```text
// 分页请求
GET /api/v1/runs?page=1&per_page=20&sort=-created_at&status=failed

// 分页响应
{
  "data": [...],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 142,
    "pages": 8
  }
}

// 错误响应
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid cron expression",
    "details": [{"field": "schedule", "reason": "..."}]
  }
}
```

---

## 7. 非功能需求

### 7.1 性能目标

| 指标 | 目标 | 测量方式 |
|------|------|----------|
| API P95 延迟 | < 100ms | 排除文件上传；普通 CRUD/详情接口 |
| 执行启动延迟 | < 15s（有缓存） / < 60s（冷启动） | 从入队到容器 running |
| 日志流延迟 | < 1s | 从产生到客户端接收 |
| 并发执行 | 单节点 10+ | 取决于硬件 |
| 看板加载 | < 2s | 依赖 analytics 预聚合；首屏数据完整呈现 |

### 7.2 可靠性

- Worker 崩溃后由 arq 重试策略 + Run 状态恢复任务兜底，避免 Run 长期卡在中间状态
- 执行超时自动终止 + 状态标记
- 数据备份：每日全量 + WAL 连续归档
- 服务可用性目标：99.9%（不含计划维护）

### 7.3 安全

- 密码：Argon2id 哈希
- 敏感数据：AES-256-GCM 加密存储（密钥通过 KMS 或环境变量注入）
- 容器：无特权、只读根文件系统、seccomp 默认配置
- API：频率限制（滑动窗口，默认 100 req/min/token）
- CSRF：SameSite cookie + token 双重验证
- 依赖：自动安全扫描（GitHub Dependabot / Safety）

### 7.4 可观测性

┌──────┬─────────────────────────┬───────────────────────────┐
│ 维度 │          工具           │           输出            │
├──────┼─────────────────────────┼───────────────────────────┤
│ 日志 │ structlog → JSON        │ stdout（容器原生）        │
├──────┼─────────────────────────┼───────────────────────────┤
│ 指标 │ Prometheus client       │ /metrics 端点             │
├──────┼─────────────────────────┼───────────────────────────┤
│ 追踪 │ OpenTelemetry           │ Jaeger / Tempo            │
├──────┼─────────────────────────┼───────────────────────────┤
│ 告警 │ Prometheus Alertmanager │ 执行队列堆积、Worker 离线 │
└──────┴─────────────────────────┴───────────────────────────┘

关键指标：
- qaplatform_runs_total{project, status, trigger_type} — 执行计数
- qaplatform_run_duration_seconds{project} — 执行耗时直方图
- qaplatform_queue_depth{priority} — 队列深度
- qaplatform_workers_active — 活跃 Worker 数
- qaplatform_http_duration_seconds{method, endpoint, status} — API 延迟

### 7.5 部署

#### 开发环境
docker compose up  # 一条命令启动全部服务

包含：API server、Worker、PostgreSQL、Redis、MinIO、前端 dev server

#### 生产环境
两种部署模式：

单机（Docker Compose） — 5 人以下团队
- docker-compose.prod.yml
- 内置 Caddy 反向代理（自动 HTTPS）
- 数据卷持久化

集群（Kubernetes） — 大规模
- Helm Chart
- HPA 自动伸缩 Worker
- PVC 或外部 S3
- Ingress + cert-manager

---

## 8. 数据存储设计
### 8.1 PostgreSQL Schema 策略

- 使用 schema 隔离：public（业务表）、audit（审计表）、analytics（聚合表）
- JSONB 字段迁移策略：
  - 代码层使用 Pydantic model + `model_validate(extra="ignore")` 做防御性解析，兼容缺失字段
  - Alembic 迁移脚本中对 JSONB 结构性变更增加数据补全步骤（如为已有记录填充新字段默认值）
  - JSONB 字段避免嵌套超过 2 层，保持查询和索引的可维护性
- 大表策略：MVP 使用普通表 + 覆盖索引 + 批量归档/清理，避免 PostgreSQL 分区表主键/外键约束复杂化；Phase 4+ 数据量验证后再迁移到按时间分区
- 关键索引覆盖所有查询模式
- JSONB 字段用于可扩展的 metadata（避免频繁 DDL）

### 8.2 Redis 用途

┌────────────┬────────────┬────────────────────┐
│    用途    │  数据结构  │        TTL         │
├────────────┼────────────┼────────────────────┤
│ 任务队列   │ arq 内置   │ 任务完成后清理     │
├────────────┼────────────┼────────────────────┤
│ 执行日志流 │ Stream     │ 24h                │
├────────────┼────────────┼────────────────────┤
│ 执行状态   │ Hash       │ 执行完成后 1h      │
├────────────┼────────────┼────────────────────┤
│ 频率限制   │ Sorted Set │ 滑动窗口自清理     │
├────────────┼────────────┼────────────────────┤
│ 会话       │ String     │ 配置的 session TTL │
└────────────┴────────────┴────────────────────┘

### 8.3 对象存储结构

bucket: qa-platform
├── reports/{run_id}/           # HTML 报告
├── artifacts/{run_id}/{name}   # 产物文件
├── logs/{run_id}.jsonl         # 归档日志
└── cache/{env_hash}/           # 环境缓存层

---

## 9. 交付计划
Phase 1: 核心引擎（4 周）

交付一个可用的"代码拉取 → pytest 执行 → 结果查看"闭环。

- FastAPI 骨架 + 认证（本地账户 + API Token）
- 项目 CRUD + Git 集成（HTTPS + Token）
- 容器化执行引擎（Docker，单 Worker）
- pytest Runner 插件 + JUnit XML Collector
- 执行列表 + 详情页 + 实时日志（SSE）
- 基础 RBAC（platform_admin + 项目级 developer / viewer；owner / maintainer 延后到 Phase 2）
- 优先级队列与公平调度的基础入队策略（使用默认配额；配置化和可观测性延后）
- 手动触发（Web + API）
- Docker Compose 开发环境

Phase 2: 自动化与通知（3 周）

- Cron 调度
- Allure 报告生成 + 托管
- 通知系统（钉钉 + 企业微信 + Email）
- 测试发现（可配置规则）
- 项目看板（通过率趋势、耗时、失败排行）

Phase 3: 智能与集成（3 周）

- Webhook 触发（GitHub / GitLab）
- Flaky 检测 + 失败聚类
- 执行对比视图
- 通用 Webhook 通知器
- 环境缓存（依赖指纹 → 复用镜像层）
- Prometheus metrics + 健康检查

Phase 4: 企业级（4 周）

- OIDC SSO
- 多 Worker 弹性伸缩 + 公平调度配置化和可观测性（基础队列策略已在 Phase 1 引入）
- Kubernetes Job 执行后端
- 参数化执行（矩阵）
- 数据归档 + 清理策略
- Helm Chart

---

## 10. 成功指标
Phase 1 先验证技术闭环：
- 手动触发 pytest Run 成功率 > 95%（示例项目）
- 从触发到容器启动 P95 < 60s（冷启动）
- SSE 日志端到端延迟 < 1s
- Run 终态一致性：无卡在 preparing/running/collecting 超过阈值的记录

Phase 2+ 再衡量业务目标：

┌────────────────────────┬───────────────────────┬─────────────────────────┐
│          指标          │         基线          │          目标           │
├────────────────────────┼───────────────────────┼─────────────────────────┤
│ 测试执行频率           │ 手动跑，每周 1-2 次   │ 每日自动 + 按需触发     │
├────────────────────────┼───────────────────────┼─────────────────────────┤
│ 从提交到质量反馈的时间 │ 小时级（等人跑+截图） │ 分钟级（自动触发+通知） │
├────────────────────────┼───────────────────────┼─────────────────────────┤
│ 质量信息获取成本       │ 问人/翻聊天记录       │ 打开看板 < 5s           │
├────────────────────────┼───────────────────────┼─────────────────────────┤
│ 环境问题导致的误报     │ 频繁"本地能跑"        │ 趋近于零（容器隔离）    │
├────────────────────────┼───────────────────────┼─────────────────────────┤
│ 回归漏跑率             │ 靠记忆，经常漏        │ 0%（定时+事件触发）     │
└────────────────────────┴───────────────────────┴─────────────────────────┘

---

## 附录 A: 与现有方案的关键分歧

┌──────────┬────────────────────────────┬────────────────────┬───────────────────┐
│   维度   │           本方案           │ PRD v1 (Flask实现) │ PRD v2 (Opus 4.6) │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 架构风格 │ 模块化单体 + 插件          │ 经典 MVC 单体      │ 微服务倾向        │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 核心抽象 │ Pipeline + Stage (可编排)  │ 固定三阶段流水线   │ Run + Job         │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 扩展方式 │ 插件协议 (Python Protocol) │ 硬编码             │ 适配器模式        │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 任务引擎 │ arq (轻量 async)           │ Celery (重量级)    │ Temporal (重量级) │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 数据库   │ PostgreSQL (JSONB+后期分区)│ MySQL              │ PostgreSQL        │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 前端     │ Vue 3 SPA                  │ Jinja2 SSR         │ React SPA         │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 实时通信 │ SSE (单向足够)             │ WebSocket          │ WebSocket         │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 存储     │ S3 协议对象存储            │ 本地 Volume        │ S3                │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 报告     │ Allure 默认，插件可替换    │ 硬绑 Allure        │ 可选              │
├──────────┼────────────────────────────┼────────────────────┼───────────────────┤
│ 部署     │ Compose → K8s 渐进         │ 仅 Compose         │ Compose + K8s     │
└──────────┴────────────────────────────┴────────────────────┴───────────────────┘

## 附录 B: 技术风险与缓解

┌───────────────────────┬────────────────────────┬────────────────────────────────────────────┐
│         风险          │          影响          │                  缓解措施                  │
├───────────────────────┼────────────────────────┼────────────────────────────────────────────┤
│ arq 社区较小          │ 遇到问题支持有限       │ 任务层抽象为接口，可切换到 Celery/Dramatiq │
├───────────────────────┼────────────────────────┼────────────────────────────────────────────┤
│ Docker Socket 暴露    │ Worker 越权管理宿主容器 │ 使用 Socket Proxy / rootless Docker / gVisor │
├───────────────────────┼────────────────────────┼────────────────────────────────────────────┤
│ PostgreSQL 单点       │ 数据库挂掉全站不可用   │ 主从复制 + 自动故障转移 (Patroni)          │
├───────────────────────┼────────────────────────┼────────────────────────────────────────────┤
│ 对象存储依赖          │ MinIO 挂掉报告不可访问 │ 关键元数据仍在 PG，报告可重新生成          │
├───────────────────────┼────────────────────────┼────────────────────────────────────────────┤
│ 插件接口变更          │ 破坏已有插件           │ 语义化版本 + 适配层                        │
└───────────────────────┴────────────────────────┴────────────────────────────────────────────┘

---
