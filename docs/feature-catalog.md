# 功能清单 · QA 自动化执行平台

> **用途**：一页看全产品功能盘子。PRD 对照 / 发版门禁 / 新人 onboarding 都从这里出发。
> **同步源**：`docs/prd.md`（功能 ID）、`docs/architecture.md`（实现位置）、`docs/TODO.md`（排期）。
> **最后更新**：2026-05-25

## 图例

| 标记 | 含义 |
|---|---|
| **必要性** | |
| P0 必要 | 删了产品定位不成立（"可复现 / 可观测 / 可比较 / 反馈可达"四个价值主张的载体） |
| P1 重要 | 强烈推荐，发版基本盘；缺它产品依然能用，但落地价值打折 |
| P2 可选 | 按需取舍，不在主路径上 |
| P3 不做 | 明确决策不在本产品范围内 |
| **状态** | |
| ✅ | 完成并合并 |
| ⚠️ | 部分完成 |
| ⏳ | 已排期 |
| ❌ | 未做（且应该做） |
| ⛔ | 已决策不做 |

---

## 1. PRD 功能 ID 对照（来自 `prd.md` §3）

### 1.1 项目管理

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-PM-01 | 创建项目 | P0 | ✅ | `api/v1/projects.py` |
| F-PM-02 | 凭证管理 | P0 | ✅ | `api/v1/credentials.py` · AES-256-GCM 加密、AAD 绑 context_id |
| F-PM-03 | 项目归档 | P0 | ✅ | `api/v1/projects.py` · archived 项目 `trigger_run` 返回 409 |

### 1.2 执行管道

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-PL-01 | 定义管道 | P0 | ✅ | `api/v1/pipelines.py` · JSONB runner_config / collector_config |
| F-PL-02 | 环境配置 | P0 | ⚠️ | `api/v1/environments.py` · `env_vars` 目前明文 JSONB；只有 `credentials` 加密。PRD 验收要求"环境变量加密存储"未达，见 §4 |
| F-PL-03 | 资源限制 | P0 | ✅ | `engine/executor.py` · CPU/内存/超时，SIGTERM → 30s → SIGKILL |

### 1.3 测试执行

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-EX-01 | 手动触发 | P0 | ✅ | `api/v1/runs.py` |
| F-EX-02 | Cron 定时触发 | P1 | ⚠️ | `api/v1/schedules.py` + `worker/scheduler.py` · timezone 已实现，PRD 验收要求的"静默窗口（发布冻结期）"未实现，见 §4 |
| F-EX-03 | Webhook 触发 | P1 | ⚠️ | `api/v1/webhooks.py` · HMAC-SHA256 签名验证已实现；PRD 验收要求"分支过滤 + 同 commit 去重"未实现（`dedup_key` 字段在 ORM 已有但 webhook 路由未传入），见 §4 |
| F-EX-04 | 执行隔离 | P0 | ✅ | `engine/docker_backend.py` · 网络隔离、非特权容器 |
| F-EX-05 | 实时日志 | P0 | ✅ | `engine/log_stream.py` + `api/v1/sse.py` · Redis Stream MAXLEN 10000 |
| F-EX-06 | 取消执行 | P0 | ✅ | `engine/cancel.py` |
| F-EX-07 | 自动重试 | P1 | ✅ | `engine/reclaim.py` + `worker/tasks.py` · 仅基础设施失败重试 |
| F-EX-08 | 优先级队列 | P2 | ✅ | `worker/scheduler.py:17-91` · 三档（high/medium/low）+ 触发类型→优先级映射 + 用户 API priority 覆盖 + per-project quota |

### 1.4 结果与报告

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-RE-01 | 结构化结果（JUnit） | P0 | ✅ | `plugins/builtin/junit_collector.py` |
| F-RE-02 | 执行摘要 | P0 | ✅ | `engine/executor.py` · passed/failed/skipped/errors |
| F-RE-03 | 失败详情 | P0 | ✅ | `api/v1/runs.py` test-results endpoint |
| F-RE-04 | 产物管理 | P0 | ✅ | `api/v1/artifacts.py` · 预签名 URL 有效期 1h；含 Allure HTML 报告在线预览（`engine/executor.py:646` 识别 + `components/runs/artifact-preview.tsx` iframe） |
| F-RE-05 | 用例级历史趋势 | P1 | ✅ | `api/v1/analytics.py` |

### 1.5 通知

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-NT-01 | 条件通知 | P1 | ✅ | `worker/notifications/channels.py` ChannelRouter · AND/OR 组合 |
| F-NT-02 | 多渠道通知 | P1 | ⚠️ | `worker/notifications/channels.py` · Email (SMTP) + Webhook (HTTP) 已实现；PRD §8"中国大陆网络"硬约束的钉钉/企业微信未实现，见 §4。Slack 已决策不做（见 §5） |
| F-NT-03 | 通知模板 | P1 | ✅ | `worker/notifications/` · 变量替换模板 |

### 1.6 权限与多租户

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-AU-01 | 用户认证 | P0 | ✅ | `api/v1/auth.py` · JWT + Argon2id |
| F-AU-02 | API Token | P1 | ✅ | `api/v1/auth.py` tokens + `api/auth/middleware.py` |
| F-AU-03 | 双层 RBAC | P0 | ✅ | `api/auth/permissions.py` · 租户 × 项目角色交集 |
| F-AU-04 | 租户隔离 | P0 | ✅ | repositories `get_for_tenant` + 跨租户返回 404 |

### 1.7 列表与搜索

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-LS-01 | 执行列表过滤 | P0 | ✅ | `api/v1/runs.py` · 状态/管道/分支/时间范围 |
| F-LS-02 | 分页 | P0 | ✅ | 全局 PaginatedResponse |
| F-LS-03 | 项目搜索 | P1 | ✅ | `api/v1/projects.py` · LIKE 转义已修复 |
| F-LS-04 | 测试结果过滤 | P0 | ⚠️ | `api/v1/runs.py` · 仅按状态过滤已实现；PRD 验收要求的 suite 名称过滤、关键字过滤未实现，见 §4 |

---

## 2. 扩展功能（Phase 2/3 新增，未占用 PRD ID）

| 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|
| 项目质量仪表盘 | P1 | ✅ | `api/v1/analytics.py` + `frontend/pages/projects/detail.tsx` |
| Flaky test 检测 | P1 | ✅ | `api/v1/analytics.py` |
| 多 Runner 插件（Jest / Playwright / Go test） | P2 | ✅ | `plugins/builtin/{jest,playwright,go_test}_runner.py` |
| 批量操作（批量取消/重试） | P1 | ✅ | `api/v1/runs.py` batch_cancel / batch_retry |
| 系统状态页 | P2 | ✅ | `api/v1/admin.py` + `frontend/pages/admin/status.tsx` |
| 项目成员管理 | P1 | ✅ | `api/v1/project_members.py` · 双层 RBAC 配套 |
| 通知规则 CRUD | P1 | ✅ | `api/v1/notifications.py` |
| SSE Ticket 鉴权 | P0 | ✅ | `api/v1/sse.py` · ticket 短期凭证防 EventSource 跨域 |
| 冒烟测试框架 | P2 | ✅ | `scripts/smoke/` · 6 页面 83 测试点 |

---

## 3. 安全与可观测（来自 `prd.md` §4 / `architecture.md` §9, §11）

| 项 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|
| JWT access + refresh token | P0 | ✅ | `api/v1/auth.py` · 1h / 7d |
| Argon2id 密码哈希 | P0 | ✅ | `api/v1/auth.py` |
| API Token 吊销 + scope | P1 | ✅ | `api/auth/middleware.py` |
| AES-256-GCM 凭据加密 | P0 | ✅ | `dependencies.py` CredentialCipher · 多版本密钥、AAD 绑 context_id |
| 认证 rate limit（5/min/IP） | P0 | ✅ | `api/middleware/rate_limit.py` + `config.py:62` `rate_limit_auth_failure=5` · Redis `TIME`，PRD §4 已对齐到 5 |
| 通用 API rate limit（100/min/IP） | P1 | ✅ | `api/middleware/rate_limit.py:147-148` · IP-based 滑动窗口 |
| Webhook 签名验证 | P1 | ✅ | `api/v1/webhooks.py` · HMAC-SHA256 |
| Container 安全头（X-Frame, HSTS 等） | P1 | ✅ | `api/middleware/security_headers.py`（CSP 等）+ `frontend/nginx.conf`（静态资源） |
| iframe sandbox 加固 | P0 | ✅ | `components/runs/artifact-preview.tsx` · 仅 `allow-scripts`，去掉 `allow-same-origin` |
| 审计日志（who/what/when/from） | P0 | ⚠️ | `api/audit.py` 写入端 best-effort + PII 脱敏 + `infra/database/repositories/audit_repo.py` 仓储已实现；**PRD §9.6 要求的查询 API 未实现**（无 `/admin/audit-events` 路由），见 §4 |
| structlog（JSON 格式） | P1 | ✅ | 全局 |
| OpenTelemetry 追踪 | P2 | ❌ | **未实现**。`pyproject.toml` 已声明 `opentelemetry-*` 依赖，但代码无 `TracerProvider` / `FastAPIInstrumentor` 装配，见 §4 |
| Prometheus 指标 | P1 | ✅ | `/metrics` endpoint |
| 健康检查 `/health/live` `/health/ready` | P0 | ✅ | `main.py` |
| Dockerfile USER 非 root | P1 | ✅ | `Dockerfile` |

---

## 4. 待办（明确要做的）

> **可交付任务包见 [`tasks/`](tasks/README.md)**：每项待办都有独立的 codex-ready 任务文件（PRD 引用 + 代码起点 + 验收 + 约束），可直接分发。

按 PRD 验收口径分两组：未达验收的（必须做）/ 增强项（建议做）。

### 4.1 未达 PRD 验收（必须做）

| ID / 项 | 必要性 | 缺失点 | 备注 |
|---|---|---|---|
| F-PL-02 环境变量加密 | P0 | `env_vars` 明文 JSONB | PRD §3.2 验收"环境变量加密存储"；参考 `dependencies.py` CredentialCipher 包装 |
| 审计日志查询 API（PRD §9.6） | P0 | 仅写入端，无 `/admin/audit-events` 查询路由 | 写入端 `api/audit.py` + 仓储 `audit_repo.py` 已就位，仅缺路由 |
| F-EX-02 静默窗口 | P1 | 发布冻结期不触发 cron | PRD §3.3 验收 |
| F-EX-03 Webhook 分支过滤 + 同 commit 去重 | P1 | 路由未传 `dedup_key`，无分支过滤逻辑 | `dedup_key` 字段在 ORM 已有，路由层接入即可 |
| F-LS-04 测试结果 suite/关键字过滤 | P1 | 仅 status | PRD §3.7 验收 |
| F-NT-02 钉钉通知 | P1 | — | PRD §8 中国大陆网络硬约束 |
| F-NT-02 企业微信通知 | P1 | — | 同上 |

### 4.2 增强项（建议做，未阻塞合规）

| 项 | 必要性 | 备注 |
|---|---|---|
| OpenTelemetry 装配 | P2 | 仅声明依赖，无 `TracerProvider` / `FastAPIInstrumentor` 代码；设计见 §4.3 |
| 非功能性能压测 | P1 | 读/写 API p99、日志推送 < 2s 目标验证 |
| E2E 测试 CI 自动触发 | P1 | 当前 `workflow_dispatch` 手动；启用 push 触发 `auth-flow.spec.ts` |

### 4.3 设计决策（已定，可直接交付实施）

> 给执行 Agent 的提示：以下两项设计在交付前已锁定，无需再做架构决策；按下方规格编码即可。

#### F-EX-02 静默窗口

**作用域**：项目级（同项目所有 schedule 共用）；不影响手动触发。

**Schema**：嵌入既有 `Project.settings` JSONB（与 `webhook_secret` 同源），路径 `settings.silent_windows`（默认 `[]`），每个元素：

```python
class SilentWindow(BaseModel):
    start_at: datetime  # 必须带时区
    end_at: datetime
    reason: str = Field(min_length=1, max_length=200)  # 如 "Release freeze 2026 Q2"
```

**调度行为**（修改 `worker/scheduler.py`）：
- 在 cron tick 创建 Run 前调用 `is_in_silent_window(project, now)`
- 命中：**不创建 Run**，写 audit 事件 `schedule_skipped_silent_window`（含 schedule_id、window.reason）
- schedule 的 `last_run_at` 不更新（视为本次未触发）
- 手动触发（API / Webhook）忽略 silent_windows

**API**：复用 `PUT /api/v1/projects/{id}`，body 加 `silent_windows`；校验：`end_at > start_at`、单个项目 ≤ 20 条窗口。

**前端**：项目设置页加"静默窗口"区块（datetime 双选 + reason 文本框 + 列表删除）。

**不做**：周期性窗口（如"每周末"），当前用例不需要；后续可加 `cron_pattern` 字段扩展。

#### OpenTelemetry 装配

**协议**：OTLP/HTTP（非 gRPC，部署门槛低、所有后端兼容）。

**Instrumentation**：
- `FastAPIInstrumentor` — HTTP 入口链路（含 path、status_code、tenant_id）
- `SQLAlchemyInstrumentor` — DB 调用
- `RedisInstrumentor` — Redis 调用（含 arq broker、log_stream）
- `worker/tasks.py:execute_run` — 手动 `tracer.start_as_current_span("execute_run")` 包住整个执行；子 span："source_clone" / "container_run" / "collect_results" / "upload_artifacts"

**配置**（`config.py` 新增）：
```python
otel_enabled: bool = False  # 默认关闭，开发环境不强制依赖
otel_exporter_endpoint: str = "http://localhost:4318/v1/traces"
otel_service_name: str = "qa-platform"
otel_sample_rate: float = 1.0  # 生产环境降到 0.1 节省后端成本
```

**装配位置**：
- `main.py` lifespan 启动时调 `setup_tracing(settings)` → 装配 FastAPI/SQLAlchemy/Redis instrumentor
- `worker/settings.py` worker 启动时同样调一次（trace context 跨进程通过 redis stream headers 传递）

**敏感字段过滤**：FastAPIInstrumentor 的 `request_hook` 中剔除 `Authorization` / `X-API-Token` header，避免 token 进入 trace。

**不做**：日志-trace 关联（structlog inject trace_id）；后续 P3 优化。

---

## 5. 已决策不做（⛔）

| 项 | 决策理由 |
|---|---|
| 跨分支/跨环境对比专属视图 | PRD §2.3 测试经理诉求可由"按 branch 手动触发执行 + 仪表盘对比通过率"覆盖；专属视图工程量大、使用频次低。注：当前 `analytics.py` **尚未支持 branch / git_ref 过滤**，若后续要做替代方案需先加这一参数 |
| 历史日志全文搜索 | 实时关键字过滤已能解决主路径；历史全文搜索需 ES/PG GIN，ROI 低 |
| 数据导出 CSV | PRD 提及但未绑定用户旅程；REST API 已可被外部脚本导出 |
| Slack 通知（F-NT-02e） | 国内团队优先级低；Webhook 通用通道可走 Slack incoming webhook |
| Phase 4 Kubernetes Job 后端 | PRD §8 假设"日 < 500、用户 < 50"。单机 Compose 够用，等容量墙再做 |
| Phase 4 多 Worker 节点管理 | arq 自身的 worker 注册够用 |
| Phase 4 历史数据分区 | 数据量未到阈值，定期归档脚本即可 |
| Phase 4 开放插件市场 | "远期目标"，无第二组织使用 |
| 邮箱验证（Phase 2 列出） | 内部工具场景，注册即同事 |
| 独立 Webhook 配置管理模块 | 合并到项目设置页即可 |
| 审计日志 3 年保留 | 小团队无外部合规要求，缩短到 90 天对齐执行记录保留 |
| 账户锁定（连续失败 5 次/15min） | 已与 PRD §4 同步删除。Redis 滑动窗口 rate limit（5/min/IP）已能挡住绝大多数暴力破解；小团队内部工具场景下落库锁定 + unlock 窗口 + 审计的 ROI 低 |

---

## 6. 非功能指标对照（PRD §4）

状态机：`✅ 达标 / ⚠️ 未达 / ⏳ 未测量 / N/A 不适用`

| 维度 | 指标 | 目标 | 状态 |
|---|---|---|---|
| 响应时间 | 读 API p99 | < 100ms | ⏳ 未测量 |
| 响应时间 | 写 API p99 | < 300ms | ⏳ 未测量 |
| 吞吐量 | 单 Worker 并发 | ≥ 10 容器 | ⏳ 未测量 |
| 可用性 | 月度可用率 | ≥ 99.5% | N/A 内部环境 |
| 日志延迟 | 实时推送 | < 2s | ⏳ 未测量 |
| 容量 | 单 Run 日志缓冲 | 10000 条 / MAXLEN | ✅ |
| 容量 | 单条日志大小 | 4KB 上限 | ✅ |
| 安全 | 凭证加密 | AES-256-GCM | ✅ |
| 安全 | 通用 API Rate limit | 100/min/IP | ✅ |
| 安全 | 认证 Rate limit | 5/min/IP | ✅ |
| 数据保留 | 执行记录 | 默认 90 天 | ✅ `worker/settings.py:121` cleanup_old_runs cron |

---

## 7. 维护约定

1. **新增功能**：在 §1 或 §2 添加一行；如属于 PRD §3 范围，先在 `prd.md` 增功能 ID 再回填到此表
2. **不得自造 PRD 子 ID**：禁止在 catalog 写 `F-XX-NNa/b/c` 这类子拆分；如确需拆分须先提 PRD 增补 PR 合并后再回填
3. **决策不做**：移到 §5，写清楚理由；理由不得引用尚未实现的功能作为替代方案
4. **状态变更**：✅ / ❌ / ⚠️ / ⏳ 与 `docs/TODO.md` 严格同步；catalog §4 是 TODO 的真相源
5. **代码与 catalog 冲突时**：优先信代码（grep 验证），同时更新 catalog；不能反过来用 catalog "认为"的状态去推断代码
6. **commit 风格**（项目惯例）：中文 commit message + semantic prefix（feat/fix/test/chore/docs），单一意图、宁拆勿合

### 已知偏移

- 无（2026-05-25 经 critic review + 用户决策同步：PRD §6 Vue→React 已修、PRD §4 rate limit 10→5 已对齐、PRD §4 账户锁定已删除）
