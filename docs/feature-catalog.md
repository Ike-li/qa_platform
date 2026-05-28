# 功能清单 · QA 自动化执行平台

> **用途**：一页看全产品功能盘子。PRD 对照 / 发版门禁 / 新人 onboarding 都从这里出发。
> **当前真源**：`docs/prd.md` 提供产品目标与功能 ID，`docs/architecture.md` 提供当前实现边界，`docs/TODO.md` 提供排期；`docs/doc-conflict-audit.md` 仅作审计证据档案，不作为实时状态源。
> **最后更新**：2026-05-28
> **路径约定**：未带仓库前缀的后端路径默认相对 `src/qaplatform/`；未带仓库前缀的前端路径默认相对 `frontend/src/`。

## 图例

| 标记 | 含义 |
|---|---|
| **必要性** | |
| P0 必要 | 删了产品定位不成立（"可复现 / 可观测 / 可比较 / 反馈可达"四个价值主张的载体） |
| P1 重要 | 强烈推荐，发版基本盘；缺它产品依然能用，但落地价值打折 |
| P2 可选 | 按需取舍，不在主路径上 |
| P3 不做 | 明确决策不在本产品范围内 |
| **状态** | |
| ✅ | 当前 `main` 已完成 |
| ⚠️ | 部分完成 |
| ⏳ | 已排期 |
| ❌ | 未做（且应该做） |
| ⛔ | 当前范围已决策不做 |

---

## 1. PRD 功能 ID 对照（来自 `prd.md` §3）

### 1.1 项目管理

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-PM-01 | 创建项目 | P0 | ⚠️ | `api/v1/projects.py` · 项目创建、Git URL、默认分支和 `git_auth_method` / `credential_id` 字段已实现；但私有 HTTPS token / SSH key 未接入 clone 执行链路，见 §4 |
| F-PM-02 | 凭证管理 | P0 | ⚠️ | `api/v1/credentials.py` · AES-256-GCM 加密、AAD 绑定 `credential:{project_id}:{name}`、轮换与删除保护已实现；执行侧尚未解密并注入 Git clone，见 §4 |
| F-PM-03 | 项目归档 | P0 | ✅ | `api/v1/projects.py` · archived 项目 `trigger_run` 返回 409 |

### 1.2 执行管道

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-PL-01 | 定义管道 | P0 | ⚠️ | `api/v1/pipelines.py` · stages / selector / trigger_config / retry_policy 与多 Pipeline 已实现；但 PRD 要求的结果收集器配置未暴露，执行器当前固定使用 JUnit collector，见 §4 |
| F-PL-02 | 环境配置 | P0 | ✅ | `api/v1/environments.py` + `domain/services/env_vars_crypto.py` + migration `007` · `env_vars` 以 JSON-safe AES-256-GCM envelope 存入 JSONB，AAD 绑定 environment_id；API create/fetch/update 解密返回，解密失败写 audit；worker 执行侧解密后注入容器环境变量，external-stack smoke 已覆盖真实 worker 使用，并断言注入密钥不出现在平台产出的 artifact 元数据、下载内容或归档日志；用户测试进程主动打印密钥后的平台级日志脱敏策略未另行实现 |
| F-PL-03 | 资源限制 | P0 | ⚠️ | `engine/docker_backend.py` + `engine/executor.py` · CPU/内存/超时与 SIGTERM → 30s → SIGKILL 已实现；environment `memory_mb` / `cpu_cores` / artifact limit 已有 API create/get/list/update 读回、真实 DB 持久化和 audit 脱敏 integration 证据；OOM/timeout backend 结果到 Run `timeout` 终态、Redis status event 和日志收尾已有真实 DB/Redis integration 证据；API 磁盘限制暴露与资源用量记录仍未闭环，见 §4 |

### 1.3 测试执行

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-EX-01 | 手动触发 | P0 | ⚠️ | `api/v1/runs.py` · 当前已支持按 pipeline 触发、可指定 `git_ref` 与 priority；“触发后 < 5s 入队”已进入 nightly/manual performance smoke，并校验每次采样都写 `run.trigger` 审计且 queued/manual/git_ref/priority/pipeline_id 状态一致；PRD 要求的 commit / environment 指定入参未闭环，见 §4 |
| F-EX-02 | Cron 定时触发 | P1 | ⚠️ | `api/v1/schedules.py` + `worker/settings.py::check_schedules` · timezone 已实现；schedule worker 成功触发、missing-pipeline skip audit、静默窗口和 schedule tick 入队 SLO 已有自动化证据；既有 schedule 级 `quiet_windows` 存在，但 PRD 验收要求的项目级"静默窗口（发布冻结期）"未实现，见 §4 |
| F-EX-03 | Webhook 触发 | P1 | ⚠️ | `api/v1/webhooks.py` · 项目级 webhook 已实现 HMAC-SHA256 签名验证、`allowed_branches` 分支过滤、同 commit `dedup_key` 去重、终态同 commit 再触发；webhook 成功触发后的入队 SLO、真实 Run metadata 保留字段保护和 `run.trigger` audit 脱敏已进入 nightly/manual performance smoke；仍缺 Git 平台 push/PR 事件解析与按 repo URL 匹配项目的正式入口，见 §4 |
| F-EX-04 | 执行隔离 | P0 | ✅ | `engine/docker_backend.py` · 默认 `network_policy=deny` → `NetworkMode=none`；容器以 `1000:1000`、只读 rootfs、drop all caps、no-new-privileges 运行；`allow` 会显式使用 bridge，`restricted` 需要部署侧提供 `qap-restricted` 网络 |
| F-EX-05 | 实时日志 | P0 | ⚠️ | `engine/log_stream.py` + `api/v1/sse.py` + `api/v1/runs.py` · Redis Stream 实时日志/状态事件、`Last-Event-ID` 续传、S3 JSONL 归档写入与归档日志读回 API 已实现；真实 API/RBAC/DB/Redis 测试覆盖 `/logs` 与 `/events` SSE 断点续传、归档失败 retry marker/worker cron 重试、归档读回分页、1500 行大页只读归档对象不 presign、对象缺失 404、存储未配置 503、跨租户 404 一致性，以及同一 `run.read` token 下归档日志回看 + artifact 列表 + 下载 URL 联合路径；nightly/manual external-stack 断言 worker 注入密钥不出现在平台产出的归档日志或真实 `run.trigger` 审计状态，并用真实 `run.read` API token 重读 worker 产出的 archived logs，空 scope token 不能读且不回显 worker secret、日志 key 或日志行；clone/setup failure 的 archived logs 也用真实 `run.read` token 回看，空 scope token 403 不回显日志 key、credentialed URL secret/userinfo 或 setup stderr；用户测试进程主动打印密钥后的日志脱敏策略未另行实现；nightly/manual performance smoke 覆盖真实日志 SSE 与状态事件 SSE 推送 < 2s、真实 API token 下归档日志分页 + artifact presign + audit-events list 并发读路径、归档大页回看、成功回看只读 `logs/{run_id}.jsonl` 且不 presign、对象缺失稳定 404 且只读目标归档对象、存储未配置稳定 503，以及跨租户拒绝不读 S3；前端终态 Run 回看入口已接入归档日志 API，剩余大日志体验/异常可观测性见 §4 |
| F-EX-06 | 取消执行 | P0 | ✅ | `engine/cancel.py` + `api/v1/runs.py` · required integration 覆盖单 run/batch cancel 的真实 DB 终态、Redis status event `previous` 与 audit before/after 一致性；nightly/manual performance smoke 覆盖取消 API p99；heavy Docker 覆盖真实容器取消 |
| F-EX-07 | 自动重试 | P1 | ⚠️ | `worker/tasks.py` 已按 API-facing `max_attempts` / `retry_on` 创建 retry Run，execute_run 基础设施异常会先提交 failed 再调度 retry；`engine/reclaim.py` 的 worker_lost callback 会创建 retry Run，nightly/manual external-stack 已覆盖 worker_lost 黑盒 retry，并对 attempt=2 retry Run 用真实 `run.read` API token 回看 archived logs、artifact list 和 JUnit download，空 scope token 对三面拒绝且不泄露日志 key、artifact 路径/名称或 JUnit 内容片段；同时覆盖 credentialed clone failure / setup exit 1 不 retry、不落 artifact、不泄密；clone/setup failure 还会用真实 `run.read` API token 回看 archived logs，空 scope token 403 不回显日志 key、secret/userinfo、clone error 或 setup stderr。Docker daemon 失败 external-stack 扰动仍作为后续增强 |
| F-EX-08 | 优先级队列 | P2 | ⚠️ | `worker/scheduler.py` 已按 priority 写入 `queue:high/medium/low` 并做 per-project quota；compose/CI nightly 启动 medium/high/low 三组 worker；required integration 覆盖 manual priority 0/1/2 经真实 API/DB 写入对应 queue metadata；nightly/manual performance smoke 覆盖 `dequeue_waiting` cron 恢复 waiting Run 时按 priority 写回 high/medium/low queue metadata，并覆盖容量受限长队中 newer high priority 越过 older low backlog；nightly/manual external-stack 会停掉 high/low worker，证明 medium worker 不误消费 high/low queue，并在匹配 worker 完成后用真实 `run.read`/空 scope token 覆盖 detail、logs、artifact list、JUnit download 与 403 不泄露；剩余更大规模长队公平性黑盒验收仍见 §4 |

### 1.4 结果与报告

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-RE-01 | 结构化结果（JUnit） | P0 | ✅ | `plugins/builtin/junit_collector.py` |
| F-RE-02 | 执行摘要 | P0 | ✅ | `engine/executor.py` · `passed` / `failed` / `skipped` / `error` / `pass_rate`；PRD 的 < 3s 生成目标已进入 nightly/manual performance smoke |
| F-RE-03 | 失败详情 | P0 | ✅ | `api/v1/runs.py` · `/runs/{run_id}/results` 返回 `error_message` / `stack_trace`；前端测试结果表支持展开失败用例详情 |
| F-RE-04 | 产物管理 | P0 | ⚠️ | `api/v1/artifacts.py` · 返回预签名 URL，required integration 已覆盖环境级 artifact limit 的 API 读回、真实 JWT/RBAC/API token scope/API/DB 行到 artifact 列表分页/越界页、DB-only 无 S3 副作用、同一 `run.read` token 下归档日志回看 + artifact 列表 + 下载 URL 联合路径、bucket/key/TTL、多 artifact 下载逐条 presign-only、软删除下载 404 no-presign 和存储未配置 503，`project.read` token 不能生成下载链接，跨租户真实 artifact ID 与随机 UUID 一致 404 且不 presign；nightly/manual performance smoke 还覆盖 artifact 列表成功路径 DB-only 不触发 S3 presign/get_object、artifact 下载成功路径每请求一次 presign 且不读取对象、artifact 下载存储未配置稳定 503、artifact 列表拒绝不返回名称/路径、拒绝下载 p99 且拒绝路径不触发 presign；nightly/manual external-stack 断言 worker 注入密钥不出现在平台产出的 artifact 元数据或下载内容，并用真实 `run.read` API token 读取 worker 产出的 artifact list 和 JUnit/HTML/log/Allure 四类 artifact download，空 scope token 不能读且不回显 artifact 名称、路径、内容片段或 worker secret；`engine/executor.py` 递归上传 `results/` 下文件并强制环境级产物数量/大小限制，Allure 目录文件会标记为 `allure-report`，S3 上传失败不会写孤儿 Artifact 行；前端 Allure/HTML 预览主路径已有 E2E，磁盘/资源用量闭环待补 |
| F-RE-05 | 历史趋势 | P1 | ⚠️ | `api/v1/analytics.py` · 项目级每日 run 趋势与 flaky 测试聚合已实现；单个用例的历史趋势视图/API 未实现 |

### 1.5 通知

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-NT-01 | 条件通知 | P1 | ⚠️ | `worker/notifications/__init__.py` · 当前支持 `status` / `pass_rate` / `failed` 多条件 AND；OR 组合与连续失败次数未实现 |
| F-NT-02 | 多渠道通知 | P1 | ⚠️ | `worker/notifications/channels.py` · Email (SMTP) + Webhook (HTTP) 已实现；PRD §8"中国大陆网络"硬约束的钉钉/企业微信未实现，见 §4。Slack 当前范围不做（见 §5） |
| F-NT-03 | 通知模板 | P1 | ⚠️ | `worker/notifications/` · 当前为规则级模板，变量仅 `run_id/status/passed/failed/total/pass_rate`；PRD 要求的每渠道模板、项目名、失败用例等变量未闭环 |

### 1.6 权限与多租户

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-AU-01 | 用户认证 | P0 | ✅ | `api/v1/auth.py` · username/password 登录，注册时收集 email；JWT + Argon2id |
| F-AU-02 | API Token | P1 | ✅ | `api/v1/auth.py` tokens + `api/auth/middleware.py` · 创建/过期/吊销/认证已实现；scope 已传入 tenant/project 权限依赖，真实 API 覆盖只读、run.trigger、artifact download 与 archived logs 的 run.read、audit-events 的 audit.read、错误/空 scope；create/revoke AuditEvent 只记录可追溯元数据，不落 full token / secret / hash |
| F-AU-03 | 双层 RBAC | P0 | ✅ | `api/auth/permissions.py` · 租户 × 项目角色交集 |
| F-AU-04 | 租户隔离 | P0 | ⚠️ | 聚合根查询与 Owner/Admin 主要路径使用 `get_for_tenant` / tenant filter 并返回 404；但 `require_project_permission` 对非 Owner/Admin 的 path `project_id` 路由会在资源查询前因缺少 `ProjectMember` 返回 403，跨租户 404 硬约束需补齐 |

### 1.7 列表与搜索

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-LS-01 | 执行列表过滤 | P0 | ⚠️ | `api/v1/runs.py` · 当前 `main` 支持状态多选、项目过滤与创建时间排序；PRD 要求的 pipeline / git_ref / time range 过滤未实现 |
| F-LS-02 | 分页 | P0 | ⚠️ | 主要列表已使用 `PaginatedResponse`（projects/runs/pipelines/environments/schedules/notifications/results/artifacts）；credentials、project members、auth tokens 仍返回直接 list |
| F-LS-03 | 项目搜索 | P1 | ⚠️ | `api/v1/projects.py` · LIKE 转义已修复；当前搜索 name/description，默认仍按 `created_at desc`，PRD 要求的名称字母序未实现 |
| F-LS-04 | 测试结果过滤 | P0 | ⚠️ | `api/v1/runs.py` · 当前 `main` 仅按状态过滤，后端状态枚举含 `passed/failed/error/skipped/xfail`；suite 名称/关键字过滤在 `feature/T07-test-results-filter` 已推送但未合入 `main` |

---

## 2. 扩展功能（Phase 2/3 新增，未占用 PRD ID）

| 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|
| 项目质量仪表盘 | P1 | ⚠️ | `api/v1/analytics.py` + `pages/projects/detail.tsx` / `components/projects/analytics-panel.tsx` 已有趋势与 flaky 前端入口；但 `analytics-panel.tsx` 仍在已知 `T-FRONTEND-TS` build 债务内，生产 build 需先清该 TS 错误 |
| Flaky test 检测 | P1 | ✅ | `api/v1/analytics.py` · 同一 suite/name 在时间窗口内既有 passed 又有 failed/error 的聚合判定 |
| 多 Runner 插件（Jest / Playwright / Go test） | P2 | ✅ | `plugins/builtin/jest_runner.py` · `plugins/builtin/playwright_runner.py` · `plugins/builtin/go_test_runner.py` |
| 批量操作（批量取消/重试） | P1 | ✅ | `api/v1/runs.py` batch_cancel / batch_retry |
| 系统状态页 | P2 | ✅ | `api/v1/admin.py` + `pages/admin/status.tsx` |
| 项目成员管理 | P1 | ✅ | `api/v1/project_members.py` · 双层 RBAC 配套 |
| 通知规则 CRUD | P1 | ✅ | `api/v1/notifications.py` |
| SSE Ticket 鉴权 | P0 | ✅ | `api/v1/sse.py` · ticket 短期凭证防 EventSource 跨域 |
| 冒烟测试框架 | P2 | ✅ | `scripts/smoke/` · 6 个页面脚本，具体检查点以脚本内 `log_step` 为准 |

---

## 3. 安全与可观测（来自 PRD §4 / architecture §9 / architecture §11）

| 项 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|
| JWT access + refresh token | P0 | ✅ | `api/v1/auth.py` · 1h / 7d |
| Argon2id 密码哈希 | P0 | ✅ | `api/v1/auth.py` |
| API Token 吊销 + scope | P1 | ✅ | `api/auth/middleware.py` + `api/auth/permissions.py` · token 吊销/过期/认证已实现；scope 已传入 tenant/project 权限依赖；真实 API 覆盖只读、run.trigger、artifact download 与 archived logs 的 run.read、audit-events 的 audit.read、错误/空 scope |
| AES-256-GCM 凭据加密 | P0 | ✅ | `dependencies.py::CryptoService` · 多版本密钥、凭据路由经 `container.crypto_service` 加密，并用 `credential:{project_id}:{name}` 做 AAD |
| 认证高风险端点 rate limit（5/min/限流桶） | P0 | ✅ | `api/middleware/rate_limit.py` + `config.py` `rate_limit_auth_failure=5` · 覆盖 login / register / token / refresh / SSE ticket；变量名保留历史 `auth_failure`，实际是端点级 strict limit；Bearer 请求按 token hash，其他请求按可信代理解析后的 IP；required integration 已用真实 FastAPI + Redis 验证 login、register、refresh、API token create、SSE ticket 第 6 次请求 429，Bearer 路径 Redis key 不存原始 token，IP/cookie 路径 Redis key 不含 username/password/refresh token，限流请求不额外写审计 |
| 通用 API rate limit（100/min/限流桶） | P1 | ✅ | `api/middleware/rate_limit.py` · Bearer 请求按 token hash，其他请求按可信代理解析后的 IP |
| Webhook 签名验证 | P1 | ✅ | `api/v1/webhooks.py` · HMAC-SHA256 |
| Container 安全头（X-Frame, HSTS 等） | P1 | ✅ | `api/middleware/security_headers.py`（CSP 等）+ `frontend/nginx.conf`（静态资源） |
| iframe sandbox 加固 | P0 | ✅ | `components/runs/artifact-preview.tsx` · 仅 `allow-scripts`，去掉 `allow-same-origin` |
| 审计日志（who/what/when/from） | P0 | ⚠️ | `api/audit.py` 写入端 + `infra/database/repositories/audit_repo.py` 仓储已实现；单 run cancel、批量取消/批量重试、SSE ticket、projects/project members/pipelines/credentials/environments/notification rules/schedules、schedule worker 自动触发与 missing-pipeline skip、签名 webhook `run.trigger` 与 webhook filtered/duplicate 决策 audit 已补写入，cancel 控制面 Redis previous 与 audit before/after 一致性已有真实 DB/Redis 验证，项目 `git_url` userinfo、pipeline 复杂配置密钥、通知/环境/凭据等敏感字段脱敏或 delete before_state 的真实 DB 验证已覆盖；查询 API 已实现，且 API token `audit.read` 成功查询写摘要自审计，`run.read`/`project.read`/空 scope 拒绝不误写自审计，nightly/manual 还观察这些拒绝路径 p99，但正式 PRD 章节仍未补，见 §4 |
| structlog（JSON 格式） | P1 | ⚠️ | `qaplatform.logging.configure_logging` 已在 API app 默认 factory 路径配置 structlog / JSON renderer；worker 入口未调用该配置，worker/engine/plugin 多处仍直接使用 stdlib `logging.getLogger`，全局结构化日志待补 |
| OpenTelemetry 追踪 | P2 | ❌ | **未实现**。`pyproject.toml` 已声明部分 OTel 依赖，但缺 OTLP HTTP exporter；代码无 `TracerProvider` / `FastAPIInstrumentor` 装配，见 §4 |
| Prometheus 指标 | P1 | ✅ | `/metrics` endpoint |
| 健康检查 `/health` `/ready` | P0 | ✅ | `main.py` |
| Dockerfile USER 非 root | P1 | ✅ | `Dockerfile` |

---

## 4. 待办（明确要做的）

> **首批可交付任务包见 [`tasks/`](tasks/README.md)**（codex-ready，含规格 + 起点 + 验收 + 约束）；本轮审计新增的待办若进入实施，需要后续补任务包。

按 PRD 验收口径分两组：未达验收的（必须做）/ 增强项（建议做）。

### 4.1 未达 PRD 验收（必须做）

| ID / 项 | 必要性 | 缺失点 | 备注 |
|---|---|---|---|
| F-PL-02 环境变量加密 | P0 | 已完成：`env_vars` 加密存储、AAD 错配失败 audit、migration 加密既有数据、worker 解密注入容器环境变量均有自动化证据；nightly/manual external-stack 还断言注入密钥不进入平台产出的 artifact 元数据、下载内容或归档日志；用户测试进程主动打印密钥后的平台级日志脱敏策略未另行实现 | PRD §3.2 验收"环境变量加密存储"已达；继续保留为验收档案，后续只需关注密钥轮换运营与真实 worker lane 稳定性 |
| F-PM-01 / F-PM-02 Git 凭证执行闭环 | P0 | 项目 schema 可保存 `git_auth_method` / `credential_id`，凭证 CRUD 可加密存储；但 manual/webhook Run 只把 `credential_id` 放入 metadata，`engine/executor.py::_clone_repo` 只用原始 `git_url` / `git_ref` 调 `GitSource.clone()`，未解密 token/SSH key 并注入 clone | 需补私有 HTTPS token / SSH key clone 支持、临时文件权限、错误脱敏与认证失败测试；避免把密钥写入日志或持久化 metadata |
| F-PL-01 collector 配置补齐 | P0 | Pipeline schema / ORM / `worker/tasks.py::_build_pipeline_config` 均无 collector 选择或配置；`RunExecutor.execute()` 固定 `get_collector("junit")` | PRD §3.2 要求可配置测试运行器、结果收集器、超时、重试策略；需决定当前 JUnit-only 是否改为正式限制，或新增 collector 配置与测试 |
| 审计日志查询 API | P0 | 已完成：`/api/v1/audit-events` 支持 Owner/Admin 分页查询、组合过滤、跨租户 404/空结果收敛，成功查询写 `audit_events.list` 自审计，member/viewer 403、跨租户过滤 404、API token `run.read`/`project.read`/空 scope 拒绝均不误写自审计，`audit.read` token 才能查询 | 审计查询仍未补入正式 PRD 章节；T02 任务包保留为验收档案 |
| 审计写入覆盖补齐 | P1 | single/batch cancel、batch retry、SSE ticket、audit-events 查询成功/拒绝副作用（含 `audit.read` 成功查询过滤字段/分页/total 自审计与 `run.read`/`project.read`/空 scope 拒绝 no self-audit）、projects/project members/pipelines/credentials/environments/notification rules/schedules、schedule worker 自动触发与 missing-pipeline skip、签名 webhook `run.trigger` 与 webhook filtered/duplicate 决策 audit 已补写入，cancel 控制面 Redis previous 与 audit before/after 一致性、项目 `git_url` userinfo、pipeline 复杂配置密钥与敏感字段脱敏或 delete before_state 的真实 DB 验证已覆盖；剩余写操作按安全风险继续补齐 | architecture §9.6 已改为“关键写操作主路径覆盖，覆盖率待补齐” |
| F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐 | P0 | 后端已递归上传 `results/` 目录文件并标记 Allure 目录产物；required integration 覆盖 environment `memory_mb` / `cpu_cores` / artifact limit 的 API create/get/list/update 读回、真实 DB 持久化和 audit env_vars 脱敏，artifact 列表元数据分页/越界页到下载链接的真实 JWT/RBAC/API token scope/API/DB 行、DB-only 无 S3 副作用、bucket/key/TTL 参数、多 artifact 下载逐条 presign-only、同一 `run.read` token 下归档日志回看 + artifact 列表 + 下载 URL 联合路径、软删除下载 404 no-presign、存储未配置 503、跨租户 404 收敛，以及 S3 上传失败不写孤儿 Artifact 行；`project.read` token 不能枚举 artifact 名称/路径或换取预签名 URL；nightly/manual performance smoke 覆盖 artifact 列表成功路径 DB-only 不触发 S3 presign/get_object、artifact 下载成功路径每请求一次 presign 且不读取对象、artifact 下载存储未配置稳定 503、artifact 列表拒绝不返回名称/路径和拒绝下载不 presign；nightly/manual external-stack smoke 覆盖真实 worker 后 artifact 列表、逐个预签名下载链接、JUnit/HTML/log/Allure 内容下载、真实 `run.read` API token 读取 worker 产出的 artifact list 和 JUnit/HTML/log/Allure 四类 artifact download、空 scope 拒绝且不泄露 artifact 名称/路径/内容片段，以及 worker 注入密钥不进入平台产出的 artifact 响应或真实 `run.trigger` 审计状态；前端 run detail 已有 HTML artifact 预览 E2E；OOM/timeout backend 结果写 Run `timeout`、Redis event 和日志收尾已有真实 DB/Redis 证据；内部 `disk_mb` 已能传到 Docker `StorageOpt.size`，但 API 暴露磁盘配额与资源用量记录未闭环 | PRD §3.2 要求限制产物大小并记录资源终止信息，PRD §3.4 要求预签名下载 + HTML 报告在线预览；当前 CPU/内存/超时、产物数量/大小限制、内部磁盘 HostConfig 传递、递归上传、失败上传无 DB 孤儿行、`download` JSON 和前端预览主路径已实现，资源记录仍待补 |
| F-EX-05 日志归档回看闭环 | P0 | Redis Stream 实时日志/状态事件、S3 JSONL 归档写入与归档日志读回 API 已实现；required integration 覆盖真实 API/RBAC/DB 下的 `/logs` 与 `/events` SSE 断点续传、归档失败真实 Redis retry marker/worker cron 重试、默认页、分页窗口、1500 行大页回看且只读归档对象不 presign、对象缺失 404、存储未配置 503、API token `run.read` scope、跨租户 Run ID 404 一致性，以及同一 `run.read` token 下归档日志回看 + artifact 列表 + 下载 URL 联合路径；nightly/manual external-stack smoke 覆盖真实 worker 完成后的归档日志读回、真实 `run.read` API token 对 worker 归档日志的读回、空 scope 拒绝且不泄露日志 key/行内容，并断言 worker 注入密钥不进入平台产出的归档日志或真实 `run.trigger` 审计状态；clone/setup failure 归档日志也通过真实 `run.read` token 重读，空 scope token 403 不泄露日志 key、credentialed URL secret/userinfo 或 setup stderr；用户测试进程主动打印密钥后的日志脱敏策略未另行实现；nightly/manual performance smoke 覆盖真实日志 SSE 与状态事件 SSE 推送 < 2s、1500 行大页回看、成功回看只读 `logs/{run_id}.jsonl` 且不 presign、对象缺失稳定 404 且只读目标归档对象、存储未配置稳定 503，以及跨租户拒绝不读 S3；前端终态 run 已接入归档日志 API 并用真实 DB+S3 E2E 覆盖回放/搜索 | PRD §3.3 验收要求“日志持久化可回看”；剩余增强是大日志虚拟列表体验和对象存储异常可观测性 |
| F-AU-02 API Token scope enforcement 补齐 | P1 | 已完成 | API token scopes 已贯通 tenant/project 权限依赖；真实 API 测试覆盖只读、run.trigger、artifact download 与 archived logs 的 run.read、audit-events 的 audit.read、错误/空 scope；create/revoke 审计状态不泄露 full token、secret 或 secret_hash |
| F-AU-04 跨租户 404 完整收敛 | P0 | 已完成 | Member/Viewer 的 path `project_id` 项目级权限依赖先验证当前租户可见性；跨 tenant、随机 UUID、软删除一致 404 |
| F-EX-01 手动触发参数与入队验收补齐 | P0 | `RunTrigger` 只接收 `pipeline_id` / `git_ref` / `priority`；PRD 要求可指定 commit 与 environment；触发后 < 5s 入队已纳入 nightly/manual performance smoke | 创建 Run 时 `environment_id` 取项目默认或首个环境，`git_sha` 不能由请求体指定；前端旧 `env_overrides` / `params` 偏移仍归 `T-FRONTEND-API` |
| F-EX-02 静默窗口 | P1 | 发布冻结期不触发 cron | PRD §3.3 验收 |
| F-EX-03 Webhook Git 平台事件解析 | P1 | 项目级 webhook 已支持 HMAC 验签、`allowed_branches` 分支过滤、同 commit `dedup_key` 去重、终态同 commit 再触发；webhook 成功触发后的入队 SLO、真实 Run metadata 保留字段保护和 `run.trigger` audit 脱敏已进入 nightly/manual performance smoke；仍缺 Git 平台 push/PR 事件解析与按 repo URL 匹配项目的正式入口 | 当前接口仍是 `POST /api/v1/webhooks/{project_id}/trigger`，不是 `POST /webhooks/{provider}` |
| F-EX-07 自动重试端到端补齐 | P2 | API-facing `max_attempts` / `retry_on`、waiting retry run、execute_run 基础设施异常、worker_lost callback 已补单测和真实 DB 测试；nightly/manual 已启动完整外部栈跑 worker smoke、worker_lost retry、credentialed clone failure 与 setup exit 1 黑盒，其中 clone/setup failure 会回看 archived logs API，并用真实 `run.read`/空 scope token 验证成功读回与拒绝不泄露 secret/userinfo/setup stderr | 剩余增强是把 Docker daemon 扰动扩到 external-stack 黑盒 |
| F-EX-08 优先级队列消费闭环 | P2 | 已补部署/测试主干 | Compose 启动 high/medium/low worker；manual priority 队列矩阵有单测和真实 API/DB queue metadata 测试；等待队列 priority+FIFO 有真实 DB 测试，`dequeue_waiting` cron 恢复入队和容量受限 high 越过 older low backlog 已有 nightly/manual performance smoke；external-stack 已覆盖 high/low worker 队列隔离，并用真实 `run.read`/空 scope token 回看匹配 worker 完成后的 high/low Run detail、archived logs、artifact list 与 JUnit download；更大规模真实长队公平性仍可作为专项黑盒增强 |
| F-LS-04 测试结果 suite/关键字过滤 | P0 | `main` 仅 status | PRD §3.7 验收；`feature/T07-test-results-filter` 已推送但未合入 |
| F-LS-01 执行列表过滤补齐 | P0 | 缺 pipeline / git_ref / time range 过滤 | 当前 `main` 支持 status 多选、project_id 与创建时间排序 |
| F-LS-02 剩余列表分页补齐 | P0 | credentials、project members、auth tokens 仍返回直接 list | 主要列表已使用 `PaginatedResponse` |
| F-LS-03 项目搜索排序补齐 | P1 | 缺名称字母序 | LIKE 转义已修；当前仍按 `created_at desc` |
| F-RE-05 单用例历史趋势补齐 | P1 | 缺单个用例历史趋势 API/视图 | 已有项目级趋势和 flaky 聚合 |
| F-NT-01 / F-NT-03 通知规则与模板验收补齐 | P1 | OR 条件、连续失败次数、每渠道模板、项目名与失败用例变量未实现 | 当前 main 只有状态/pass_rate/失败数 AND 条件和规则级基础变量替换 |
| F-NT-02 钉钉通知 | P1 | — | PRD §8 中国大陆网络硬约束 |
| F-NT-02 企业微信通知 | P1 | — | 同上 |

### 4.2 增强项（建议做，未阻塞合规）

| 项 | 必要性 | 备注 |
|---|---|---|
| OpenTelemetry 装配 | P2 | 仅声明部分依赖，无 OTLP HTTP exporter、`TracerProvider` / `FastAPIInstrumentor` 代码；设计见 §4.3 |
| 非功能性能压测 | P1 | 已补 nightly/manual performance smoke 覆盖读 API、写 API、手动/webhook/schedule 触发入队 SLO（每次采样都写 `run.trigger` 审计且状态字段一致，webhook 额外验证保留 metadata 不覆盖执行配置且不进审计，schedule 额外验证系统身份审计和 `queue:low` 元数据）、waiting dequeue 恢复入队 SLO、容量受限 priority backlog 中 high 越过 older low 的 preemption SLO、取消 API p99、Redis 日志写读、SSE 实时日志推送 < 2s、归档日志读回 API（小样本与 1500 行大对象分页均只读 `logs/{run_id}.jsonl` 且不 presign，对象缺失稳定 404 且只读目标归档对象，存储未配置稳定 503，跨租户拒绝不读 S3，真实空 scope API token 同租户拒绝不回显日志 key/行内容且不触发 S3）、artifact 列表元数据 API（成功路径 DB-only 不 presign/读 S3，并覆盖真实 `run.read` API token 下 1000 条大集合深页）、artifact 列表拒绝不返回元数据、artifact 下载链接 API（单次/burst 成功路径 presign-only 不读对象，存储未配置稳定 503，跨租户拒绝不 presign，真实空 scope API token 同租户拒绝不回显 artifact name/path 且不触发 S3）、audit events 查询 API 与成功自审计写入、真实 `audit.read` API token 下大量过滤深分页、audit-events 角色/跨租户拒绝和 `run.read`/`project.read`/空 scope API token 拒绝都不写自审计、执行摘要生成 < 3s 趋势并输出 p50/p99/max 失败摘要；严格产品 SLO 与完整压测仍需专项环境验证 |
| E2E CI 覆盖扩展 | P1 | PR 保留 `auth-flow.spec.ts`；nightly 固定跑 `real-login-flow` / `real-run-trigger` / `special-regressions`；`workflow_dispatch` 手动跑全量 E2E |
| 数据保留冷归档/读回增强 | P2 | 超期终态 Run 清理与级联删除、失败日志归档重试、归档日志读回 API 和前端终态 Run 回看主路径已闭环；当前仍缺 DB 行冷归档与对象存储生命周期运营报表 |
| 结构化日志全局化 | P2 | API app 默认 factory 已配置 structlog JSON renderer；worker/arq 入口未调用 `configure_logging`，engine / worker / plugin 多数模块仍经 stdlib logger 输出，需统一 worker 进程日志初始化与字段格式 |

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

**既有模型注意事项**：当前代码已有 schedule 级 `quiet_windows`（`Schedule.quiet_windows` + `domain/services/scheduling.py::should_fire`）。本设计新增的是 project 级、绝对时间窗口 `silent_windows`，两者不要混用：`silent_windows` 命中时必须写 audit 且不更新 `schedule.last_run_at`；既有 `quiet_windows` 仍按当前 schedule 级逻辑处理。

**调度行为**（修改 `worker/settings.py::check_schedules`）：
- 在 cron tick 创建 Run 前，从 ORM `Project.settings["silent_windows"]` 解析窗口列表，再调用 `domain/services/scheduling.py::is_in_silent_window(windows, now)`
- 判定区间为闭区间：`start_at <= now <= end_at`；`start_at` / `end_at` / `now` 都必须是 tz-aware，比较前统一到 UTC
- 命中：**不创建 Run**，写 audit 事件 `schedule_skipped_silent_window`；当前 `AuditEvent` 无 `metadata` 列，静默窗口跳过详情写入 `after_state`（含 `schedule_id`、`reason`、`window_end`）
- schedule 的 `last_run_at` 不更新（视为本次未触发）
- 手动触发（API / Webhook）忽略 silent_windows

**API**：复用 `PUT /api/v1/projects/{project_id}`，body 加 `silent_windows`；校验：`end_at > start_at`、单个项目 ≤ 20 条窗口。

**前端**：项目设置页加"静默窗口"区块（datetime 双选 + reason 文本框 + 列表删除）。

**不做**：周期性窗口（如"每周末"），当前用例不需要；后续可加 `cron_pattern` 字段扩展。

#### OpenTelemetry 装配

**协议**：OTLP/HTTP（非 gRPC，部署门槛低、所有后端兼容）。

**Instrumentation**：
- `FastAPIInstrumentor.instrument_app(app, ...)` — HTTP 入口链路（含 path、status_code）；只在 API 进程对实际 FastAPI app 装配。租户维度不会自动出现在 ASGI scope，若需要 `tenant.id` 属性，应在认证 dependency 解析 `UserIdentity` 后手动设置当前 span，且不得写 token/user_id 等敏感值
- `SQLAlchemyInstrumentor(engine=container.db_engine.sync_engine)` — DB 调用；当前项目使用 async SQLAlchemy engine，要传底层 `sync_engine`
- `RedisInstrumentor` — Redis 调用（含 arq broker、log_stream）
- `worker/tasks.py::execute_run` — 手动 `tracer.start_as_current_span("execute_run")` 包住整个 arq job；`engine/executor.py::RunExecutor.execute` 内部包子 span："source_clone" / "container_run" / "collect_results" / "upload_artifacts"

**配置**（扩展 `config.py`；当前已有 `otel_exporter_endpoint`，不要重复定义）：
```python
otel_enabled: bool = False  # 默认关闭，开发环境不强制依赖
otel_exporter_endpoint: str | None = None  # 启用时配置 OTLP/HTTP endpoint
otel_service_name: str = "qa-platform"
otel_sample_rate: float = 1.0  # 生产环境降到 0.1 节省后端成本
```

**装配位置**：
- `main.py` 创建 app 时对 FastAPI app 调 `instrument_app(app, ...)`；lifespan/container 初始化后对 `container.db_engine.sync_engine` 和 Redis 装配
- `worker/settings.py::on_startup` 在 `container.init_db()` 后装配 SQLAlchemy/Redis；worker 进程没有 FastAPI app，不调用 FastAPI app instrumentation；跨进程 trace context 传播不在本任务范围内

**敏感字段过滤**：FastAPIInstrumentor 启用 header capture 时必须配置 `http_capture_headers_sanitize_fields`（至少 `authorization` / `cookie` / `x-api-token` / `set-cookie`），不要依赖一个只修改 headers copy 的 request hook；当前认证入口仍是 `Authorization: Bearer ...`。

**不做**：日志-trace 关联（structlog inject trace_id）；后续 P3 优化。

---

## 5. 当前范围已决策不做（⛔）

| 项 | 决策理由 |
|---|---|
| 跨分支/跨环境对比专属视图 | PRD §2.3 测试经理诉求可由"按 branch 手动触发执行 + 仪表盘对比通过率"覆盖；专属视图工程量大、使用频次低。注：当前 `api/v1/analytics.py` **尚未支持 branch / git_ref 过滤**，若后续要做替代方案需先加这一参数 |
| 历史日志全文搜索 | 实时关键字过滤已能解决主路径；历史全文搜索需 ES/PG GIN，ROI 低 |
| 数据导出 CSV | PRD 提及但未绑定用户旅程；REST API 已可被外部脚本导出 |
| Slack 通知（F-NT-02e） | 国内团队优先级低；Webhook 通用通道可走 Slack incoming webhook |
| Phase 4 Kubernetes Job 后端 | PRD §8 假设"日 < 500、用户 < 50"。单机 Compose 够用，等容量墙再做 |
| Phase 4 多 Worker 节点管理 | arq 自身的 worker 注册够用 |
| Phase 4 历史数据分区 | 数据量未到阈值；当前先补数据保留清理闭环，不上分区表 |
| Phase 4 开放插件市场 | "远期目标"，无第二组织使用 |
| 邮箱验证（Phase 2 列出） | 内部工具场景，注册即同事 |
| 独立 Webhook 配置管理模块 | 合并到项目设置页即可 |
| 账户锁定（连续失败 5 次/15min） | 已与 PRD §4 同步删除。Redis 认证高风险端点滑动窗口 rate limit（5/min/限流桶）已能挡住绝大多数暴力破解；小团队内部工具场景下落库锁定 + unlock 窗口 + 审计的 ROI 低 |

---

## 6. 非功能指标对照（PRD §4）

状态机：`✅ 达标 / ⚠️ 未达 / ⏳ 未测量 / N/A 不适用`

| 维度 | 指标 | 目标 | 状态 |
|---|---|---|---|
| 响应时间 | 读 API p99 | < 100ms | ⚠️ 已有 nightly/manual smoke 趋势哨兵；严格 SLO 需专项环境压测 |
| 响应时间 | 写 API p99 | < 300ms | ⚠️ 已有 nightly/manual smoke 趋势哨兵；严格 SLO 需专项环境压测 |
| 响应时间 | 执行摘要生成 | < 3s | ⚠️ 已有 nightly/manual smoke 覆盖 JUnitCollector + summary DB 写入；严格 SLO 需专项环境压测 |
| 吞吐量 | 单 Worker 并发 | ≥ 10 容器 | ⏳ 未测量 |
| 可用性 | 月度可用率 | ≥ 99.5% | N/A 内部环境 |
| 日志延迟 | 实时推送 | < 2s | ⚠️ 已有 nightly/manual SSE delivery smoke；严格 SLO 需专项环境压测 |
| 容量 | 单 Run 日志缓冲 | 近似 10000 条 / Redis Stream MAXLEN auto-trim | ✅ |
| 容量 | 单条日志大小 | 4KB 上限 | ✅ |
| 容量 | 单次执行最大产物总大小 | 500MB | ⚠️ 环境级 `max_artifact_size_mb` / `max_artifacts_count` 已传入 worker 并在上传路径强制校验；内部 `disk_mb` 已能传到 Docker `StorageOpt.size`；仍缺 API 磁盘配额暴露与资源用量记录 |
| 安全 | 凭证加密 | AES-256-GCM | ✅ |
| 安全 | 通用 API Rate limit | 100/min/限流桶 | ✅ |
| 安全 | 认证高风险端点 Rate limit | 5/min/限流桶 | ✅ |
| 数据保留 | 执行记录 | 默认 90 天 | ✅ `cleanup_old_runs` 会硬删超期终态 Run 并级联清理 result/artifact/event，真实 Postgres 集成测试已覆盖 |
| 数据保留 | 审计日志 | 默认 1095 天配置 | ⚠️ `config.py` 已有 `retention_audit_days`；当前未发现独立审计清理任务 |

---

## 7. 维护约定

1. **新增功能**：在 §1 或 §2 添加一行；如属于 PRD §3 范围，先在 `prd.md` 增功能 ID 再回填到此表
2. **不得自造 PRD 子 ID**：禁止在 catalog 写 `F-XX-NNa/b/c` 这类子拆分；如确需拆分须先提 PRD 增补 PR 合并后再回填
3. **当前范围不做**：移到 §5，写清楚理由；理由不得引用尚未实现的功能作为替代方案
4. **状态变更**：✅ / ❌ / ⚠️ / ⏳ 与 `docs/TODO.md` 严格同步；catalog §4 是 TODO 的功能 backlog 真源
5. **代码与 catalog 冲突时**：优先信代码（grep 验证），同时更新 catalog；不能反过来用 catalog "认为"的状态去推断代码
6. **commit 风格**（项目惯例）：中文 commit message + semantic prefix（feat/fix/test/chore/docs），单一意图、宁拆勿合

### 已知偏移

- 详见 [`doc-conflict-audit.md`](doc-conflict-audit.md) 的审计证据。当前主要偏移包括：审计日志查询已实现但仍未补入正式 PRD 章节、任务验收口径已从全量 lint/build 修订为改动文件干净、首批 8 个 `feature/T*` 分支已推送但未合入 `main`。
