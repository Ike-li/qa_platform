# 功能清单 · QA 自动化执行平台

> **用途**：一页看全产品功能盘子。PRD 对照 / 发版门禁 / 新人 onboarding 都从这里出发。
> **当前真源**：`docs/product.md` 提供产品目标、功能 ID 与试点产品化边界，`docs/architecture.md` 提供当前实现边界，`docs/TODO.md` 提供排期；`docs/archive/doc-conflict-audit.md` 仅作审计证据档案，不作为实时状态源。
> **最后更新**：2026-06-07
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

## 1. PRD 功能 ID 对照（来自 `product.md` §3）

### 1.1 项目管理

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-PM-01 | 创建项目 | P0 | ✅ | `api/v1/projects.py` + `worker/tasks.py` + `plugins/builtin/git_source.py` · 项目创建、Git URL、默认分支和 `git_auth_method` / `credential_id` 字段已实现；绑定凭证时校验项目/租户归属、类型与 URL 形态，执行侧会按 Run metadata 解密并注入 HTTPS token / SSH key clone |
| F-PM-02 | 凭证管理 | P0 | ✅ | `api/v1/credentials.py` + `worker/tasks.py` · AES-256-GCM 加密、AAD 绑定 `credential:{project_id}:{name}`、轮换与删除保护已实现；worker 仅在执行时解密，Run metadata 与审计状态只保存凭证引用，不保存明文 |
| F-PM-03 | 项目归档 | P0 | ✅ | `api/v1/projects.py` · archived 项目 `trigger_run` 返回 409 |

### 1.2 执行管道

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-PL-01 | 定义管道 | P0 | ✅ | `api/v1/pipelines.py` + `worker/tasks.py` + `engine/executor.py` · stages / selector / trigger_config / retry_policy / `collectors[]` 与多 Pipeline 已实现；默认 JUnit collector，执行侧按配置调用 collector，JUnit 支持相对 report path 配置 |
| F-PL-02 | 环境配置 | P0 | ✅ | `api/v1/environments.py` + `domain/services/env_vars_crypto.py` + migration `007` · `env_vars` 以 JSON-safe AES-256-GCM envelope 存入 JSONB，AAD 绑定 environment_id；API create/fetch/update 解密返回，解密失败写 audit；worker 执行侧解密后注入容器环境变量。验收与密钥脱敏证据见 §4.1 |
| F-PL-03 | 资源限制 | P0 | ⚠️ | `engine/docker_backend.py` + `engine/executor.py` · CPU/内存/超时与 SIGTERM → 30s → SIGKILL 已实现；environment `memory_mb` / `cpu_cores` / `disk_mb` / artifact limit 可配置，`disk_mb` 映射到 Docker `StorageOpt.size`；OOM/timeout 结果归一到 Run `timeout` 终态，终止原因/退出码/耗时与 Docker stats 峰值 CPU/内存采样写入 Run summary。验收、stats 黑盒与 OOMKilled gate 证据见 §4.1 |

### 1.3 测试执行

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-EX-01 | 手动触发 | P0 | ✅ | `api/v1/runs.py` + `components/runs/trigger-run-modal.tsx` · 支持按 pipeline 触发，可指定 `git_ref`、40 位 `git_sha`、environment 与 priority；显式 environment 校验归属项目，完整 commit SHA 会传给执行器 checkout。入队验收与 priority 队列元数据证据见 §4.1 |
| F-EX-02 | Cron 定时触发 | P1 | ✅ | `api/v1/schedules.py` + `worker/settings.py::check_schedules` · timezone 已实现；schedule worker 成功触发、missing-pipeline skip audit、schedule tick 入队 SLO 和项目级 `silent_windows` 发布冻结期均有自动化证据；`PUT /api/v1/projects/{project_id}` 可保存 `silent_windows` 到 `Project.settings`，前端项目设置页可编辑，cron 命中时不创建 Run、写 `schedule_skipped_silent_window` audit 且不更新 `last_run_at`；schedule 级 `quiet_windows` 仍作为单条 schedule 的周期性跳过逻辑保留 |
| F-EX-03 | Webhook 触发 | P1 | ⚠️ | `api/v1/webhooks.py` · 项目级 webhook 已实现 HMAC-SHA256 签名验证、`allowed_branches` 分支过滤、同 commit `dedup_key` 去重、终态同 commit 再触发；GitHub provider 入口 `/webhooks/github` 与 `/api/v1/webhooks/github` 支持 push payload 解析、按 repository URL candidates 匹配项目、按匹配项目 `webhook_secret` 验签、系统身份触发与 filtered/duplicate 决策 audit。验收与入队 SLO 证据见 §4.1；剩余 GitLab/Gitee、PR/fork 策略、URL 规范化和更完整 provider 事件矩阵见 §4 |
| F-EX-04 | 执行隔离 | P0 | ✅ | `engine/docker_backend.py` · 默认 `network_policy=deny` → `NetworkMode=none`；容器以 `1000:1000`、只读 rootfs、drop all caps、no-new-privileges 运行；`allow` 会显式使用 bridge，`restricted` 需要部署侧提供 `qap-restricted` 网络 |
| F-EX-05 | 实时日志 | P0 | ⚠️ | `engine/log_stream.py` + `api/v1/sse.py` + `api/v1/runs.py` · Redis Stream 实时日志/状态事件、`Last-Event-ID` 续传、S3 JSONL 归档写入与归档日志读回 API 已实现；前端终态 Run 回看入口已接入归档日志 API。SSE 续传、归档读回、密钥脱敏与跨租户/scope 拒绝证据见 §4.1；剩余大日志体验/异常可观测性见 §4 |
| F-EX-06 | 取消执行 | P0 | ✅ | `engine/cancel.py` + `api/v1/runs.py` · required integration 覆盖单 run/batch cancel 的真实 DB 终态、Redis status event `previous` 与 audit before/after 一致性；nightly/manual performance smoke 覆盖取消 API p99；heavy Docker 覆盖真实容器取消 |
| F-EX-07 | 自动重试 | P1 | ⚠️ | `worker/tasks.py` 已按 API-facing `max_attempts` / `retry_on` 创建 retry Run，execute_run 基础设施异常会先提交 failed 再调度 retry；`engine/reclaim.py` 的 worker_lost callback 会创建 retry Run。worker_lost / clone / setup 失败黑盒证据见 §4.1；Docker daemon 失败 external-stack 扰动仍作为后续增强 |
| F-EX-08 | 优先级队列 | P2 | ⚠️ | `worker/scheduler.py` 已按 priority 写入 `queue:high/medium/low` 并做 per-project quota；compose/CI nightly 启动 medium/high/low 三组 worker。queue metadata、`dequeue_waiting` 恢复、preemption 与队列隔离证据见 §4.1；剩余更大规模长队公平性黑盒验收见 §4 |

### 1.4 结果与报告

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-RE-01 | 结构化结果（JUnit） | P0 | ✅ | `plugins/builtin/junit_collector.py` |
| F-RE-02 | 执行摘要 | P0 | ✅ | `engine/executor.py` · `passed` / `failed` / `skipped` / `error` / `pass_rate`；PRD 的 < 3s 生成目标已进入 nightly/manual performance smoke |
| F-RE-03 | 失败详情 | P0 | ✅ | `api/v1/runs.py` · `/runs/{run_id}/results` 返回 `error_message` / `stack_trace`；前端 Run 详情页提供失败排障摘要、日志/报告/产物/Re-run 连续入口，测试结果表默认优先展示 failed/error，用例展开后可进入单用例历史 |
| F-RE-04 | 产物管理 | P0 | ⚠️ | `api/v1/artifacts.py` 返回预签名 URL；`engine/executor.py` 递归上传 `results/` 下文件并强制环境级产物数量/大小限制，Allure 目录文件标记为 `allure-report`，S3 上传失败不写孤儿 Artifact 行；前端 Allure HTML 预览主路径有 E2E，普通 `html`/`text/html` 预览由前端契约测试锁住。RBAC/scope/跨租户/presign 副作用与 worker 黑盒证据见 §4.1；剩余多资源报告加载体验见 §4 |
| F-RE-05 | 历史趋势 | P1 | ✅ | `api/v1/analytics.py` · 项目级每日 run 趋势、flaky 测试聚合和单用例历史趋势均已实现；trends/flaky 支持可选 `git_ref` 过滤，`/analytics/release-summary` 返回目标 ref 与 baseline 的 run 数、raw pass rate、flaky-adjusted pass rate、新增失败和恢复用例；`/analytics/test-history` 按 suite/name 精确查询最近 N 天 run_id、run_created_at、run_status、用例 status、duration_ms、error_message 与 git_ref，前端 Analytics 面板可从 flaky 行或失败 Run 进入单用例历史表 |

### 1.5 通知

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-NT-01 | 条件通知 | P1 | ✅ | `worker/notifications/__init__.py` · 支持 `status` / `pass_rate` / `failed` / `consecutive_failures` 条件，支持顶层 AND 与嵌套 `any` / `all` 条件组；前端规则表单可选择满足全部或任一条件 |
| F-NT-02 | 多渠道通知 | P1 | ✅ | `worker/notifications/channels.py` · Email (SMTP) + Webhook (HTTP) + DingTalk 自定义机器人 + WeCom 群机器人已实现；前端通知规则表单可创建四类渠道，单条规则中每种一等渠道只能配置一次（Email 通过 `to_addresses` 支持多个收件人）；Slack 当前范围不做（见 §5） |
| F-NT-03 | 通知模板 | P1 | ✅ | `worker/notifications/` · 支持规则级模板和 `channels[].template` 每渠道覆盖，变量含 `run_id/status/project_name/passed/failed/total/pass_rate/failed_tests`；`engine/executor.py` 会从 collector 结果把失败/错误用例名写入真实执行 summary，最多保留前 20 条并记录省略数 |

### 1.6 权限与多租户

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-AU-01 | 用户认证 | P0 | ✅ | `api/v1/auth.py` · username/password 登录，注册时收集 email；JWT + Argon2id |
| F-AU-02 | API Token | P1 | ✅ | `api/v1/auth.py` tokens + `api/auth/middleware.py` · 创建/过期/吊销/认证已实现；scope 已传入 tenant/project 权限依赖，真实 API 覆盖只读、run.trigger、run detail、artifact download 与 archived logs 的 run.read、audit-events 的 audit.read、错误/空 scope；create/revoke AuditEvent 只记录可追溯元数据，不落 full token / secret / hash |
| F-AU-03 | 双层 RBAC | P0 | ✅ | `api/auth/permissions.py` · 租户 × 项目角色交集 |
| F-AU-04 | 租户隔离 | P0 | ✅ | 聚合根查询、Owner/Admin 主要路径、Run/artifact/SSE 等资源路径使用 `get_for_tenant` / tenant filter 返回 404；`require_project_permission` 对非 Owner/Admin 的 path `project_id` 路由会先验证当前租户可见性，再查 `ProjectMember`，因此跨 tenant、随机 UUID、软删除项目一致 404，真实 integration 与 RBAC dependency unit 已覆盖 |

### 1.7 列表与搜索

| ID | 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|---|
| F-LS-01 | 执行列表过滤 | P0 | ✅ | `api/v1/runs.py` · 支持 status 多选、project_id、pipeline_id、git_ref、created_from/created_to 与创建时间排序；required integration 覆盖真实 DB 行的 pipeline/git_ref/time range 过滤 |
| F-LS-02 | 分页 | P0 | ✅ | 所有当前列表接口均使用 `PaginatedResponse` 响应体字段（projects/runs/pipelines/environments/schedules/notifications/results/artifacts/credentials/project members/auth tokens）；credentials、members、auth tokens 已补 unit 与真实 DB/API integration |
| F-LS-03 | 项目搜索 | P1 | ✅ | `api/v1/projects.py` · 支持 `q` 按 name/description 模糊搜索并转义 LIKE 通配符；结果按项目名称升序，unit + required integration 覆盖名称字母序 |
| F-LS-04 | 测试结果过滤 | P0 | ✅ | `api/v1/runs.py` · `/runs/{run_id}/results` 支持 status、suite、q 组合过滤，q 覆盖用例名和错误信息并转义 LIKE 通配符；unit 与 required integration 均有真实过滤证据 |

---

## 2. 扩展功能（Phase 2/3 新增，未占用 PRD ID）

| 功能 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|
| 项目质量仪表盘 | P1 | ✅ | `api/v1/analytics.py` + `pages/projects/detail.tsx` / `components/projects/analytics-panel.tsx` 已有项目趋势、flaky 聚合、单用例历史趋势和轻量 release/ref 判断入口；前端 TypeScript/build/lint gate 通过 |
| Flaky test 检测 | P1 | ✅ | `api/v1/analytics.py` · 同一 suite/name 在时间窗口内既有 passed 又有 failed/error 的聚合判定 |
| 多 Runner 插件（pytest / Jest / Playwright / Go test） | P2 | ✅ | `plugins/builtin/pytest_runner.py` · `plugins/builtin/jest_runner.py` · `plugins/builtin/playwright_runner.py` · `plugins/builtin/go_test_runner.py` |
| 批量操作（批量取消/重试） | P1 | ✅ | `api/v1/runs.py` batch_cancel / batch_retry |
| 系统状态页 | P2 | ✅ | `api/v1/admin.py` + `pages/admin/status.tsx` |
| 项目成员管理 | P1 | ✅ | `api/v1/project_members.py` · 双层 RBAC 配套 |
| 通知规则 CRUD | P1 | ✅ | `api/v1/notifications.py` |
| SSE Ticket 鉴权 | P0 | ✅ | `api/v1/sse.py` · ticket 短期凭证防 EventSource 跨域 |
| 报告分享（公开链接） | P2 | ✅ | `api/v1/report_shares.py` + `services/report_share_service.py` · 生成时间限制/访问次数限制的分享令牌，支持列表/撤销，公开访问无需登录 |
| 冒烟测试框架 | P2 | ✅ | `scripts/smoke/run-all.sh` 聚合 `00-setup.sh`、`01-browser-bridge.sh` 和 6 个页面脚本；默认 skip 计失败，探索性运行才允许 `SMOKE_ALLOW_SKIPS=1`；父级 `RESULTS_DIR` 下保留汇总 report，子脚本证据落在 `${RESULTS_DIR}/<script-name>/`，具体检查点以脚本内 `log_step` 为准 |

---

## 3. 安全与可观测（来自 PRD §4 / architecture §9 / architecture §11）

| 项 | 必要性 | 状态 | 实现位置 |
|---|---|---|---|
| JWT access + refresh token | P0 | ✅ | `api/v1/auth.py` · 1h / 7d |
| Argon2id 密码哈希 | P0 | ✅ | `api/v1/auth.py` |
| API Token 吊销 + scope | P1 | ✅ | `api/auth/middleware.py` + `api/auth/permissions.py` · token 吊销/过期/认证已实现；scope 已传入 tenant/project 权限依赖；真实 API 覆盖只读、run.trigger、run detail、artifact download 与 archived logs 的 run.read、audit-events 的 audit.read、错误/空 scope |
| AES-256-GCM 凭据加密 | P0 | ✅ | `dependencies.py::CryptoService` · 多版本密钥、凭据路由经 `container.crypto_service` 加密，并用 `credential:{project_id}:{name}` 做 AAD |
| 认证高风险端点 rate limit（5/min/限流桶） | P0 | ✅ | `api/middleware/rate_limit.py` + `config.py` `rate_limit_auth_failure=5` · 覆盖 login / register / token / refresh / SSE ticket；变量名保留历史 `auth_failure`，实际是端点级 strict limit；Bearer 请求按 token hash，其他请求按可信代理解析后的 IP；required integration 已用真实 FastAPI + Redis 验证 login、register、refresh、API token create、SSE ticket 第 6 次请求 429，Bearer 路径 Redis key 不存原始 token，IP/cookie 路径 Redis key 不含 username/password/refresh token，限流请求不额外写审计 |
| 通用 API rate limit（100/min/限流桶） | P1 | ✅ | `api/middleware/rate_limit.py` · Bearer 请求按 token hash，其他请求按可信代理解析后的 IP |
| Webhook 签名验证 | P1 | ✅ | `api/v1/webhooks.py` · HMAC-SHA256 |
| Container 安全头（X-Frame, HSTS 等） | P1 | ✅ | `api/middleware/security_headers.py`（CSP 等）+ `frontend/nginx.conf`（静态资源） |
| iframe sandbox 加固 | P0 | ✅ | `components/runs/artifact-preview.tsx` · 仅 `allow-scripts`，去掉 `allow-same-origin` |
| 审计日志（who/what/when/from） | P0 | ⚠️ | `infra/audit.py::write_audit` 写入端（`api/audit.py` 为兼容 re-export）+ `infra/database/repositories/audit_repo.py` 仓储已实现；写入覆盖与脱敏、查询 API 与自审计细节见 §4.1「审计写入覆盖补齐」「审计日志查询 API」；正式 PRD 章节仍未补，见 §4 |
| structlog（JSON 格式） | P1 | ✅ | `qaplatform.logging.configure_logging` 已在 API app 默认 factory 与 worker/arq `on_startup` 路径配置 structlog / JSON renderer；stdlib `logging.getLogger` 输出经统一 root handler / ProcessorFormatter 结构化 |
| OpenTelemetry 追踪 | P2 | ⚠️ | 基础追踪已实现：`src/qaplatform/observability/tracing.py` 提供 `setup_tracing` / `instrument_fastapi` / `instrument_infra`，`main.py` 与 `worker/settings.py` 已装配，worker/executor 有手动 span；仍缺 OTLP HTTP exporter 依赖决策和接收端部署验证，见 §4 |
| Prometheus 指标 | P1 | ✅ | `/metrics` endpoint |
| 健康检查 `/health` `/ready` | P0 | ✅ | `main.py` |
| Dockerfile USER 非 root | P1 | ✅ | `Dockerfile` |

---

## 4. PRD 验收矩阵与待办（状态 + 剩余缺口）

> **首批可交付任务包见 [`tasks/`](tasks/README.md)**（codex-ready，含规格 + 起点 + 验收 + 约束）；本轮审计新增的待办若进入实施，需要后续补任务包。

按 PRD 验收口径分两组：状态与剩余必做项 / 增强项（建议做）。

### 4.1 验收状态与剩余必做项

| ID / 项 | 必要性 | 当前状态 / 剩余缺口 | 备注 |
|---|---|---|---|
| F-PL-02 环境变量加密 | P0 | 已完成：`env_vars` 加密存储、AAD 错配失败 audit、migration 加密既有数据、worker 解密注入容器环境变量均有自动化证据；nightly/manual external-stack 还断言注入密钥不进入平台产出的 artifact 元数据、下载内容或归档日志；用户测试进程主动把该密钥打印到 stdout/stderr 时，live SSE、archived logs 与真实 `run.read` token 读面只出现 `[REDACTED]` | PRD §3.2 验收"环境变量加密存储"已达；继续保留为验收档案，后续只需关注密钥轮换运营与真实 worker lane 稳定性 |
| F-PM-01 / F-PM-02 Git 凭证执行闭环 | P0 | 已完成基线：项目 schema/API 保存 `git_auth_method` / `credential_id` 并校验凭证归属/类型/URL 形态；manual/webhook/schedule Run metadata 只带凭证引用；worker 执行时解密项目凭证并传给 `PipelineConfig.source_auth`；`GitSource` 用临时 askpass 注入 HTTPS token、用 0600 临时 key + `GIT_SSH_COMMAND` 注入 SSH key，clone 错误会脱敏 token/userinfo | unit 覆盖 token/SSH 注入、错误脱敏、worker 解密与 metadata 传播；required integration 覆盖真实 API/DB 下绑定 token 后触发 Run 且 Run metadata / AuditEvent 不含 token 明文。后续增强是用受控私有仓库补 nightly/manual 成功 clone 与凭证轮换黑盒 |
| F-PL-01 collector 配置补齐 | P0 | 已完成：Pipeline API schema / ORM / migration / worker `_build_pipeline_config` / `RunExecutor.execute()` 均贯通 `collectors[]`；旧配置默认 JUnit，JUnit collector 消费 `config.path` / `config.junit_xml` 相对路径 | unit 覆盖 API 持久化、审计脱敏、worker 映射、executor 非硬编码和 JUnit 自定义路径；required integration 覆盖真实 API 创建/更新读回 |
| 审计日志查询 API | P0 | 已完成：`/api/v1/audit-events` 支持 Owner/Admin 分页查询、组合过滤、跨租户 404/空结果收敛，成功查询写 `audit_events.list` 自审计，member/viewer 403、跨租户过滤 404、API token `run.read`/`project.read`/空 scope 拒绝均不误写自审计，`audit.read` token 才能查询 | 审计查询仍未补入正式 PRD 章节；T02 任务包保留为验收档案 |
| 审计写入覆盖补齐 | P1 | 已覆盖：single/batch cancel、batch retry、SSE ticket、audit-events 查询成功/拒绝副作用、projects/members/pipelines/credentials/environments/notification rules/schedules、schedule worker 自动触发与 missing-pipeline skip、签名 webhook `run.trigger` 与 filtered/duplicate 决策 audit 均已补写入，审计 payload 对齐 API response 且敏感字段脱敏；API POST/PUT/PATCH/DELETE 路由由 AST 架构契约锁住直接写审计或委托已审计 helper。逐项脱敏与 before/after 断言见 `testing-strategy.md` 风险矩阵 | architecture §9.6 记录审计主路径与新增写接口契约；后续新增写路径必须补审计与脱敏回归 |
| F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐 | P0 | 已完成基线：后端递归上传 `results/` 目录文件并标记 Allure 产物，强制环境级数量/大小限制，S3 上传失败不写孤儿行；environment `memory_mb` / `cpu_cores` / `disk_mb` / artifact limit 可配置，`disk_mb` 传到 Docker `StorageOpt.size`；OOM/timeout 归一到 Run `timeout` 并采样 Docker stats 峰值 CPU/内存；前端 Allure HTML 预览有 E2E，普通 HTML/report 预览由前端契约测试覆盖。RBAC/scope/跨租户/presign 副作用、worker 黑盒与 OOMKilled gate 的完整测试证据见 `testing-strategy.md` 风险矩阵 | PRD §3.2 要求限制产物大小并记录资源终止信息，PRD §3.4 要求预签名下载 + HTML 报告在线预览；剩余是多资源报告加载体验 |
| F-EX-05 日志归档回看闭环 | P0 | 已完成：Redis Stream 实时日志/状态事件、SSE `Last-Event-ID` 断点续传、S3 JSONL 归档写入、归档失败 Redis retry marker + worker cron 重试、归档日志读回 API（分页/大页只读对象不 presign、对象缺失 404、存储未配置 503）均已实现；前端终态 run 已接入归档日志 API 并有真实 DB+S3 E2E 回放/搜索。`run.read` scope、跨租户 404、密钥脱敏与 worker 黑盒的完整测试证据见 `testing-strategy.md` 风险矩阵 | PRD §3.3 验收要求“日志持久化可回看”；剩余增强是大日志虚拟列表体验和对象存储异常可观测性 |
| F-AU-02 API Token scope enforcement 补齐 | P1 | 已完成 | API token scopes 已贯通 tenant/project 权限依赖；真实 API 测试覆盖只读、run.trigger、run detail、artifact download 与 archived logs 的 run.read、audit-events 的 audit.read、错误/空 scope；create/revoke 审计状态不泄露 full token、secret 或 secret_hash |
| F-AU-04 跨租户 404 完整收敛 | P0 | 已完成 | Member/Viewer 的 path `project_id` 项目级权限依赖先验证当前租户可见性；跨 tenant、随机 UUID、软删除一致 404 |
| F-EX-01 手动触发参数与入队验收补齐 | P0 | 已完成：`RunTrigger` 接收 `pipeline_id` / `git_ref` / 40 位 `git_sha` / `environment_id` / `priority`；前端触发弹窗可指定 environment 与 commit；触发后 < 5s 入队已纳入 nightly/manual performance smoke | required integration 断言 API response、Run DB 行和 `run.trigger` audit after_state 一致；完整 `git_sha` 会传给执行器 checkout |
| F-EX-02 静默窗口 | P1 | 已完成：发布冻结期使用项目级 `Project.settings.silent_windows`；`ProjectUpdate.silent_windows` 校验 tz-aware、`end_at > start_at` 与最多 20 条窗口，前端项目设置页可保存；cron tick 命中窗口时不创建 Run、不更新 `schedule.last_run_at`，并以系统身份写 `schedule_skipped_silent_window` audit；手动触发和 webhook 触发明确忽略 silent_windows | unit 覆盖 schema/worker/判定函数；required integration 覆盖真实 API 保存到 DB、窗口内/外 cron、manual/webhook 绕过；E2E 覆盖 UI 保存入口 |
| F-EX-03 Webhook Git 平台事件解析 | P1 | GitHub provider 入口已支持 `POST /webhooks/github` 与 `POST /api/v1/webhooks/github`：解析 push payload，按 repository URL candidates 匹配项目，使用匹配项目 `webhook_secret` 验签，无登录用户时以系统身份创建 Run 并写 audit；项目级 webhook 仍支持 HMAC 验签、`allowed_branches` 分支过滤、同 commit `dedup_key` 去重、终态同 commit 再触发；webhook 成功触发后的入队 SLO、真实 Run metadata 保留字段保护和 `run.trigger` audit 脱敏已进入 nightly/manual performance smoke | 剩余增强是 GitLab/Gitee provider、PR/fork 策略、URL 规范化/歧义运营提示和更完整事件矩阵 |
| F-EX-07 自动重试端到端补齐 | P2 | API-facing `max_attempts` / `retry_on`、waiting retry run、execute_run 基础设施异常、worker_lost callback 已补单测和真实 DB 测试；nightly/manual 已启动完整外部栈跑 worker smoke、worker_lost retry、credentialed clone failure 与 setup exit 1 黑盒，其中 clone/setup failure 会回看 archived logs API，并用真实 `run.read`/空 scope token 验证成功读回与拒绝不泄露 secret/userinfo/setup stderr | 剩余增强是把 Docker daemon 扰动扩到 external-stack 黑盒 |
| F-EX-08 优先级队列消费闭环 | P2 | 已补部署/测试主干 | Compose 启动 high/medium/low worker；manual priority 队列矩阵有单测和真实 API/DB queue metadata 测试；等待队列 priority+FIFO 有真实 DB 测试，`dequeue_waiting` cron 恢复入队和容量受限 high 越过 older low backlog 已有 nightly/manual performance smoke；external-stack 已覆盖 high/low worker 队列隔离，并用真实 `run.read`/空 scope token 回看匹配 worker 完成后的 high/low Run detail、archived logs、artifact list 与 JUnit download；更大规模真实长队公平性仍可作为专项黑盒增强 |
| F-LS-04 测试结果 suite/关键字过滤 | P0 | 已完成：status / suite / q 组合过滤，q 搜索用例名和错误信息并转义 LIKE 通配符 | unit 覆盖过滤条件；required integration 覆盖真实 DB 行组合过滤 |
| F-LS-01 执行列表过滤补齐 | P0 | 已完成：status 多选、project_id、pipeline_id、git_ref、created_from/created_to 与创建时间排序 | required integration 覆盖真实 DB 行过滤 |
| F-LS-02 剩余列表分页补齐 | P0 | 已完成：credentials、project members、auth tokens 均返回 `PaginatedResponse`，支持 `page` / `per_page` / `total` / `data` | unit 覆盖 offset/limit；required integration 覆盖真实 DB/API 分页、越界页空数组和 auth token 明文不回显 |
| F-LS-03 项目搜索排序补齐 | P1 | 已完成：项目搜索结果按名称升序 | unit 锁住 repository `order_by`；required integration 覆盖真实 DB/API 搜索结果名称字母序 |
| F-RE-05 单用例历史趋势补齐 | P1 | 已完成：`/analytics/test-history` 按 suite/name 返回单用例历史点，Analytics 面板可从 flaky 行查看历史 | required integration 覆盖真实 DB 下 passed/failed 两次历史、pagination、run_status、git_ref、duration/error；前端契约与 build/lint 覆盖 hook、DTO 和 UI 入口 |
| F-NT-01 条件通知验收补齐 | P1 | 已完成：AND / OR 条件组与连续失败次数 | unit 覆盖条件递归与 `consecutive_failures`；required integration 覆盖真实 DB 下连续 3 次失败触发、连续 4 次失败门槛不触发；前端契约覆盖任一/全部条件保存 |
| F-NT-02 多渠道通知 | P1 | 已完成：Email、Webhook、DingTalk、WeCom 均已实现并可经前端配置；API/前端禁止单条规则重复配置同一渠道类型，避免通知日志按渠道类型幂等时静默漏发 | unit 覆盖 channel payload / 加签 / 错误脱敏 / router；前端契约测试锁住 UI 支持四类渠道、email `to_addresses` 保存契约和重复渠道防线 |

### 4.2 增强项（建议做，未阻塞合规）

| 项 | 必要性 | 备注 |
|---|---|---|
| OpenTelemetry 装配 | P2 | 基础装配已补：`TracerProvider`、`FastAPIInstrumentor`、SQLAlchemy/Redis instrumentation 和 worker/executor 手动 span 已有代码与单测；剩余 OTLP HTTP exporter 依赖决策、接收端部署验证和 trace-log 关联后续优化；设计见 §4.3 |
| 非功能性能压测 | P1 | 已补 nightly/manual performance smoke：覆盖读/写 API、手动/webhook/schedule 触发入队、waiting dequeue 恢复、priority preemption、取消 API p99、SSE 推送 < 2s、真实 API token 并发读、归档/artifact 读面副作用、audit-events 查询、执行摘要 < 3s 和 external-stack worker 单样本/10 容器并发 SLO；release_candidate 按 `.github/performance-slo-manifest.json` 校验并输出 p50/p99/max 失败摘要。逐项 SLO 与拒绝路径断言见 `testing-strategy.md` Performance smoke 小节；完整容量压测和长期稳定性 SLO 仍需专项环境验证 |
| E2E CI 覆盖扩展 | P1 | PR 保留 `auth-flow.spec.ts`；nightly 固定跑 `real-login-flow` / `real-run-trigger` / `special-regressions`；`release_candidate` 手动跑全量 E2E 并校验四个关键 spec、testcase 数与 `--list` 一致且 failure/error/skipped 为 0；本地 `scripts/run-e2e.sh` 与 `tests/e2e/global-setup.ts` 对齐 seed/登录口径并默认导出 `QAP_E2E_WORKER=1`。逐项 evidence validation 见 `testing-strategy.md` E2E 小节 |
| 数据保留冷归档/读回增强 | P2 | 超期终态 Run 清理与级联删除、失败日志归档重试、归档日志读回 API 和前端终态 Run 回看主路径已闭环；当前仍缺 DB 行冷归档与对象存储生命周期运营报表 |
| 结构化日志全局化 | P2 | 已完成：API app 与 worker/arq 入口均调用统一 `configure_logging` | `tests/unit/test_lifespan.py` 覆盖 worker startup 在依赖初始化前配置日志；trace-log 关联仍属 OpenTelemetry 后续优化 |

### 4.3 实现口径档案

> 给维护者的提示：以下记录当前实现口径和后续增强边界，避免把已落地能力再次排成待办。

#### F-EX-02 静默窗口

**作用域**：项目级（同项目所有 schedule 共用）；不影响手动触发。

**Schema**：嵌入既有 `Project.settings` JSONB（与 `webhook_secret` 同源），路径 `settings.silent_windows`（默认 `[]`），每个元素：

```python
class SilentWindow(BaseModel):
    start_at: datetime  # 必须带时区
    end_at: datetime
    reason: str = Field(min_length=1, max_length=200)  # 如 "Release freeze 2026 Q2"
```

**既有模型注意事项**：当前代码保留 schedule 级 `quiet_windows`（`Schedule.quiet_windows` + `domain/services/scheduling.py::should_fire`），并已新增 project 级、绝对时间窗口 `silent_windows`。两者不要混用：`silent_windows` 命中时必须写 audit 且不更新 `schedule.last_run_at`；既有 `quiet_windows` 仍按 schedule 级逻辑处理。

**调度行为**（`worker/settings.py::check_schedules`）：
- 在 cron tick 创建 Run 前，从 ORM `Project.settings["silent_windows"]` 解析窗口列表，再调用 `domain/services/schedule.py::is_in_silent_window(windows, now)`
- 判定区间为闭区间：`start_at <= now <= end_at`；`start_at` / `end_at` / `now` 都必须是 tz-aware
- 命中：**不创建 Run**，写 audit 事件 `schedule_skipped_silent_window`；当前 `AuditEvent` 无 `metadata` 列，静默窗口跳过详情写入 `after_state`（含 `schedule_id` 与 `window`）
- schedule 的 `last_run_at` 不更新（视为本次未触发）
- 手动触发（API / Webhook）忽略 silent_windows

**API**：复用 `PUT /api/v1/projects/{project_id}`，body 支持 `silent_windows`；校验：tz-aware、`end_at > start_at`、单个项目 ≤ 20 条窗口。

**前端**：项目设置页加"静默窗口"区块（datetime 双选 + reason 文本框 + 列表删除）。

**不做**：周期性窗口（如"每周末"），当前用例不需要；后续可加 `cron_pattern` 字段扩展。

#### OpenTelemetry 装配

**协议**：OTLP/HTTP（非 gRPC，部署门槛低、所有后端兼容）。

**当前状态**：基础追踪装配已落地。`src/qaplatform/observability/tracing.py` 已实现 `setup_tracing(settings)`、`instrument_fastapi(app, provider)`、`instrument_infra(container, provider)`、OTLP exporter 可选导入和敏感 header 防线；`main.py` / `worker/settings.py` 已接入；`tests/unit/test_observability/test_tracing.py` 覆盖 enabled/disabled、幂等、缺 exporter、FastAPI 与 infra instrumentation。T10 后续只收口 exporter 依赖/部署验证/trace-log 关联，不应再把 tracing.py 或基础 instrumentation 当成未实现。

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
| 完整跨分支/跨环境对比专属视图 | PRD §2.3 测试经理诉求先由"按 branch 手动触发执行 + Analytics 按 `git_ref` 过滤 + release summary"覆盖；完整 diff 视图工程量大、使用频次仍需试点验证 |
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
| 吞吐量 | 单 Worker 并发 | ≥ 10 容器 | ⚠️ 已有 release_candidate external-stack performance 证据；仍需专项长稳压测 |
| 可用性 | 月度可用率 | ≥ 99.5% | N/A 内部环境 |
| 日志延迟 | 实时推送 | < 2s | ⚠️ 已有 nightly/manual SSE delivery smoke；严格 SLO 需专项环境压测 |
| 容量 | 单 Run 日志缓冲 | 近似 10000 条 / Redis Stream MAXLEN auto-trim | ✅ |
| 容量 | 单条日志大小 | 4KB 上限 | ✅ |
| 容量 | 单次执行最大产物总大小 | 500MB | ⚠️ 环境级 `max_artifact_size_mb` / `max_artifacts_count` 已传入 worker 并在上传路径强制校验；API `disk_mb` 已能传到 Docker `StorageOpt.size`；Docker stats 峰值 CPU/内存采样已写 summary 并有真实 Docker stream 黑盒；release_candidate 会强制 OOMKilled heavy-docker 用例不被 skip/fail |
| 安全 | 凭证加密 | AES-256-GCM | ✅ |
| 安全 | 通用 API Rate limit | 100/min/限流桶 | ✅ |
| 安全 | 认证高风险端点 Rate limit | 5/min/限流桶 | ✅ |
| 数据保留 | 执行记录 | 默认 90 天 | ✅ `cleanup_old_runs` 会硬删超期终态 Run 并级联清理 result/artifact/event，真实 Postgres 集成测试已覆盖 |
| 数据保留 | 审计日志 | 默认 1095 天 | ✅ `cleanup_old_audit_events` 会按 `retention_audit_days` 硬删超期 `audit.event`，unit 覆盖 worker cron 入口，真实 Postgres 集成测试覆盖普通租户审计与系统审计的保留/清理边界 |

---

## 7. 维护约定

1. **新增功能**：在 §1 或 §2 添加一行；如属于 PRD §3 范围，先在 `product.md` 增功能 ID 再回填到此表
2. **不得自造 PRD 子 ID**：禁止在 catalog 写 `F-XX-NNa/b/c` 这类子拆分；如确需拆分须先提 PRD 增补 PR 合并后再回填
3. **当前范围不做**：移到 §5，写清楚理由；理由不得引用尚未实现的功能作为替代方案
4. **状态变更**：✅ / ❌ / ⚠️ / ⏳ 与 `docs/TODO.md` 严格同步；catalog §4 是 TODO 的功能 backlog 真源
5. **代码与 catalog 冲突时**：优先信代码（grep 验证），同时更新 catalog；不能反过来用 catalog "认为"的状态去推断代码
6. **commit 风格**（项目惯例）：中文 commit message + semantic prefix（feat/fix/test/chore/docs），单一意图、宁拆勿合

### 已知偏移

- 详见 [`archive/doc-conflict-audit.md`](archive/doc-conflict-audit.md) 的审计证据。当前主要偏移包括：审计日志查询已实现但仍未补入正式 PRD 章节、任务验收口径已从全量 lint/build 修订为改动文件干净；旧 `feature/T*` 分支合并状态仅作为历史快照保留，实时状态以现场 git 命令为准。
