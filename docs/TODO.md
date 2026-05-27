# QA 平台 TODO

> 完整功能盘子与状态见 [`feature-catalog.md`](feature-catalog.md)
> **首批可交付任务包见 [`tasks/`](tasks/README.md)**（codex-ready，含规格 + 起点 + 验收 + 约束）；本轮审计新增的待办若进入实施，需要后续补任务包。
> 本文件按优先级排序"近期要做什么 / 不做什么"，与 catalog §4 保持同步。
> 更新于 2026-05-27（PRD / catalog / tasks 与代码仍有已知偏移，审计证据见 [`doc-conflict-audit.md`](doc-conflict-audit.md)；首批 8 个任务包与对应 `feature/T*` 分支均已推送但未合入 `main`）

---

## 1. 高优先级 — PRD 验收未达（必须做）

| # | 项 | 来源 | 缺什么 |
|---|---|---|---|
| 1 | F-PL-02 环境变量加密 | PRD §3.2 验收 | `env_vars` 当前明文 JSONB；需复用 `dependencies.py::CryptoService`（凭据路由经 `container.crypto_service` 调用） |
| 2 | F-PM-01 / F-PM-02 Git 凭证执行闭环 | PRD §3.1 验收 | 项目和凭证 API 可保存 `git_auth_method` / `credential_id` 与加密凭证，但执行侧 clone 只使用原始 `git_url`，未解密并注入 HTTPS token / SSH key |
| 3 | F-PL-01 collector 配置补齐 | PRD §3.2 验收 | Pipeline schema / ORM / worker 拼装均无结果收集器选择或配置，`RunExecutor.execute()` 固定 `get_collector("junit")`；需决定 JUnit-only 是否改为正式限制，或补 collector 配置闭环 |
| 4 | 审计日志查询 API | catalog §4.1 | 已完成：`/api/v1/audit-events` 支持 Owner/Admin 分页查询、组合过滤、跨租户 404/空结果收敛，并写 `audit_events.list` 自审计；正式 PRD 章节仍未补 |
| 5 | 审计写入覆盖补齐 | architecture §9.6 | 单 run cancel、批量取消/批量重试、SSE ticket、projects/project members/pipelines/credentials/environments/notification rules/schedules、schedule worker 自动触发与 missing-pipeline skip、签名 webhook `run.trigger` 与 webhook filtered/duplicate 决策 audit 已补真实 DB 验证；cancel 控制面已验证 Redis status event `previous` 与 audit before/after 一致，项目 `git_url` userinfo、pipeline 复杂配置密钥与敏感字段脱敏或 delete before_state 已覆盖；剩余写操作按安全风险继续补齐 |
| 6 | F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐 | PRD §3.2 / PRD §3.4 验收 | CPU/内存/超时、产物数量/大小限制、`results/` 递归上传和 Allure 目录文件落库已实现并有真实 DB/S3 验证；required integration 覆盖 artifact 列表元数据到下载链接的真实 JWT/RBAC/API token scope/API/DB 行与 bucket/key/TTL 参数，`project.read` token 不能枚举 artifact 名称/路径或换取预签名 URL，跨租户真实 artifact ID 与随机 UUID 一致 404 且不 presign；OOM/timeout backend 结果写 Run `timeout`、Redis status event 和日志收尾已有真实 DB/Redis 证据；nightly/manual external-stack smoke 覆盖真实 worker 后 artifact 列表、预签名下载链接与 JUnit 内容下载；前端 run detail 已补 HTML artifact 预览 E2E；仍缺磁盘限制、资源用量记录和多资源报告加载口径 |
| 7 | F-EX-05 日志归档回看闭环 | PRD §3.3 验收 | Redis Stream 实时日志、断线续传、S3 JSONL 归档写入与归档日志读回 API 已实现；required integration 覆盖真实 API/RBAC/DB 下的 SSE `Last-Event-ID` 断点续传、归档失败真实 Redis retry marker/worker cron 重试、默认页、分页窗口、对象缺失 404、API token `run.read` scope 和跨租户 Run ID 404 一致性；nightly/manual external-stack smoke 覆盖真实 worker 完成后的归档日志读回；nightly/manual performance smoke 覆盖真实 SSE 推送 < 2s；前端终态 run 已接入归档日志 API，并由真实 DB+S3 E2E 覆盖回放/搜索 |
| 8 | F-AU-02 API Token scope enforcement 补齐 | PRD §3.6 验收 | 已完成：API token scopes 已贯通 tenant/project 权限依赖，并有真实 API 矩阵覆盖只读、run.trigger、artifact download 与 archived logs 的 run.read、错误/空 scope；create/revoke 审计状态不泄露 full token、secret 或 secret_hash |
| 9 | F-AU-04 跨租户 404 完整收敛 | PRD §3.6 验收 | 已完成：Member/Viewer 的 path `project_id` 项目级权限依赖先验证租户可见性；跨 tenant、随机 UUID、软删除一致 404 |
| 10 | F-EX-01 手动触发参数与入队验收补齐 | PRD §3.3 验收 | 当前 `RunTrigger` 只接收 `pipeline_id` / `git_ref` / `priority`；缺 commit / environment 指定入参；“触发后 < 5s 入队”已纳入 nightly/manual performance smoke 趋势哨兵 |
| 11 | F-NT-02 钉钉通知 | PRD §8 | 中国大陆网络硬约束 |
| 12 | F-NT-02 企业微信通知 | PRD §8 | 同上 |

## 2. 中优先级 — 验收边角 + 性能验证

| # | 项 | 来源 | 缺什么 |
|---|---|---|---|
| 13 | F-EX-02 静默窗口 | PRD §3.3 验收 | 发布冻结期不触发 cron 未实现 |
| 14 | F-EX-03 Webhook Git 平台事件解析 | PRD §3.3 验收 | 当前项目级 webhook 已支持 HMAC 验签、`allowed_branches` 分支过滤、同 commit `dedup_key` 去重、终态同 commit 再触发；仍缺 Git 平台 push/PR 事件解析与按 repo URL 匹配项目的正式入口 |
| 15 | F-EX-07 自动重试端到端补齐 | PRD §3.3 验收 | API-facing `max_attempts` / `retry_on`、waiting retry run、execute_run 基础设施异常、worker_lost callback 已补单测和真实 DB 测试；nightly/manual external-stack 已补 worker_lost 黑盒重试；剩余增强是明确 clone/setup/Docker daemon 失败是否也进入自动 retry 并补对应黑盒场景 |
| 16 | F-EX-08 优先级队列消费闭环 | PRD §3.3 验收 | 已补 compose high/medium/low worker 部署、manual priority 队列矩阵单测、真实 API/DB queue metadata 测试、真实 DB priority+FIFO 排序测试；真实长队抢占黑盒仍可作为 nightly/manual 增强 |
| 17 | F-LS-04 测试结果 suite/关键字过滤 | PRD §3.7 验收 | 当前 `main` 仅 status（后端状态枚举含 `passed/failed/error/skipped/xfail`）；`feature/T07-test-results-filter` 已推送但未合入 |
| 18 | F-LS-01 执行列表过滤补齐 | PRD §3.7 验收 | 当前 `main` 支持 status 多选、project_id 与创建时间排序；缺 pipeline / git_ref / time range 过滤 |
| 19 | F-LS-02 剩余列表分页补齐 | PRD §3.7 验收 | credentials、project members、auth tokens 仍返回直接 list，未走 `PaginatedResponse` |
| 20 | F-LS-03 项目搜索排序补齐 | PRD §3.7 验收 | LIKE 转义已修；结果仍按 `created_at desc`，缺名称字母序 |
| 21 | F-RE-05 单用例历史趋势补齐 | PRD §3.4 验收 | 当前已有项目级趋势和 flaky 聚合；缺单个用例历史趋势 API/视图 |
| 22 | F-NT-01 / F-NT-03 通知规则与模板验收补齐 | PRD §3.5 验收 | 当前仅状态/pass_rate/失败数 AND 条件和规则级基础变量模板；缺 OR、连续失败次数、每渠道模板、项目名与失败用例变量 |
| 23 | 非功能性能压测 | PRD §4 / PRD §3.4 验收 | 已补 nightly/manual performance smoke 覆盖读 API、写 API、触发入队 SLO、取消 API p99、Redis 日志写读、SSE 实时日志推送 < 2s、归档日志读回 API、artifact 列表元数据 API、artifact 下载链接 API、audit events 查询 API、执行摘要生成 < 3s 趋势并输出 p50/p99/max 失败摘要；严格产品 SLO 与完整压测仍需专项环境验证 |
| 24 | E2E CI 覆盖扩展 | fix-roadmap §4.3 | 已补 nightly 固定真实 E2E：`real-login-flow`、`real-run-trigger`、`special-regressions`；PR 仍保留轻量 `auth-flow`，manual 仍跑全量 |
| 25 | 数据保留冷归档/读回增强 | architecture §8.4 / runbook §7 | 超期终态 Run 清理与级联删除、失败日志归档重试、归档日志读回 API 和前端终态 Run 回看主路径已闭环；当前仍缺 DB 行冷归档与对象存储生命周期运营报表 |

## 3. 低优先级 — 增强项

| # | 项 | 备注 |
|---|---|---|
| 26 | OpenTelemetry 装配 | 仅声明部分依赖，缺 OTLP HTTP exporter 与 instrumentation 代码 |
| 27 | 部署 checklist 完善 | 密钥/CIDR/lifecycle/Docker socket proxy 一键勾选；附到 `runbook.md` |

## 4. 技术债专项

| 任务 | 内容 | 备注 |
|---|---|---|
| T-LINT | 已完成：清理 main 既有 ruff 历史债务 | CI `backend-test` 已加入 `ruff check src tests`，后续新增债务会阻断 |
| T-FRONTEND-TS | 清理前端 3 个历史 TS 错误文件 | CI 目前只允许这 3 个已知文件失败；任何新 TS 错误仍阻断 |
| T-FRONTEND-API | 拆分/对齐前端 API DTO、hook 路径/响应形状与视图模型类型 | `frontend/src/types/api.ts` 仍混合后端响应与 UI 归一化字段（如 Run 的 `git_ref/summary/duration_ms` vs `branch/total_tests/duration_seconds`）；`frontend/src/hooks/use-runs.ts` 的触发 payload 仍带后端 `RunTrigger` 不接收的 `env_overrides/params`，且 `normalizeRun` 仍读取复数 `summary.errors` 而后端 summary 使用单数 `error`；Environment 仍有 `variables` 旧字段且缺 `base_image` / `env_vars` / resource limit 字段，`frontend/src/components/projects/environment-editor.tsx` 创建和更新也仍提交旧 `variables` payload；Pipeline 嵌套 selector / retry shape 仍是旧前端形状，`frontend/src/components/projects/pipeline-modal.tsx` 也提交旧 `framework/pattern/on_push/max_retries/backoff` payload，需对齐后端 `stages/selector/trigger_config/retry_policy` schema；`frontend/src/hooks/use-projects.ts` 项目搜索传 `search`，但后端 `api/v1/projects.py::list_projects` 参数是 `q`；`frontend/src/hooks/use-pipelines.ts` 仍调用不存在的 `/pipelines/{id}`，应改为 `/projects/{project_id}/pipelines/{pipeline_id}`；`frontend/src/hooks/use-notifications.ts` 把通知规则列表当成裸数组，但后端返回 `PaginatedResponse[NotificationRuleResponse]`；`frontend/src/hooks/use-sse.ts` fallback 目前会把 SSE URL 当 JSON API 轮询，需改为重连或普通 JSON 状态端点；TestResult 后端状态含 `xfail` 但当前前端类型未列；以后端 `api/schemas.py` 为契约源 |
| T-ARCH-LAYERS | 收敛分层 import / DB 访问偏差 | `engine` 当前仍反向依赖 `api.metrics` / `worker._redact`；部分 API 路由仍直接写 SQLAlchemy 查询，需逐步下沉到中立指标模块、`engine.redact` 和 repositories / query service |
| T-LOGGING | 结构化日志全局化 | API app 默认 factory 已配置 structlog JSON renderer；worker/arq 入口未调用 `configure_logging`，engine / worker / plugin 多数模块仍经 stdlib logger 输出，需统一 worker 进程日志初始化与字段格式 |

### 审计报告任务 ID 对照

`doc-conflict-audit.md` §15 使用 `T-*` 别名记录本轮审计拆出的后续任务；当前 TODO 的优先级与验收来源仍以上方表格为准。映射使用稳定标题，避免依赖会随排序变化的编号：

| 审计任务 ID | TODO / catalog 落点 |
|---|---|
| `T-DOC-01` | 已完成第一轮文档修复，见 `doc-conflict-audit.md` §15 |
| `T-DOC-02` | 已完成第一轮文档修复，见 `doc-conflict-audit.md` §15 |
| `T-DOC-03` | 已完成第一轮文档修复，见 `doc-conflict-audit.md` §15 |
| `T-DOC-04` | 已完成第一轮文档修复，见 `doc-conflict-audit.md` §15 |
| `T-DOC-05` | 已完成第一轮文档修复，见 `doc-conflict-audit.md` §15 |
| `T-GIT-CREDENTIALS` | F-PM-01 / F-PM-02 Git 凭证执行闭环 |
| `T-PIPELINE-COLLECTOR` | F-PL-01 collector 配置补齐 |
| `T-AUDIT-COVERAGE` | 审计写入覆盖补齐 |
| `T-ARTIFACT-PREVIEW` | F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐 |
| `T-LOG-REPLAY` | F-EX-05 日志归档回看闭环 |
| `T-AUTH-SCOPE` | F-AU-02 API Token scope enforcement 补齐 |
| `T-MANUAL-TRIGGER` | F-EX-01 手动触发参数与入队验收补齐 |
| `T-EXEC-RETRY` | F-EX-07 自动重试端到端补齐 |
| `T-QUEUE-PRIORITY` | F-EX-08 优先级队列消费闭环 |
| `T-NOTIFICATION-TEMPLATE` | F-NT-01 / F-NT-03 通知规则与模板验收补齐 |
| `T-RETENTION-OPS` | 数据保留冷归档/读回增强 |
| `T-LINT` | 技术债专项 |
| `T-FRONTEND-TS` | 技术债专项 |
| `T-FRONTEND-API` | 技术债专项 |
| `T-ARCH-LAYERS` | 技术债专项 |
| `T-LOGGING` | 技术债专项 |

### Maintainer 决策待确认

`doc-conflict-audit.md` §17 汇总的是不能只靠文档修字完成的产品/架构决策；进入对应 TODO 实施前需先确认下表口径：

| 决策项 | 稳定落点 |
|---|---|
| 是否在 PRD 正式补审计日志查询章节 | 审计日志查询 API；当前执行依据为 catalog §4.1 |
| `Schedule.quiet_windows` 与 `Project.settings.silent_windows` 是否长期共存 | F-EX-02 静默窗口；catalog §4.3 已记录当前双机制边界 |
| T10 是否允许新增 OTLP HTTP exporter 依赖 | OpenTelemetry 装配 |
| 是否需要独立审计日志清理任务 | 数据保留清理闭环 |
| 是否需要 DB 行冷归档 | 数据保留冷归档/读回增强；`retry_failed_archives` 自动补偿已实现 |
| `/auth/sse-ticket` 临时凭证写入是否必须纳入审计 | 已按高风险凭证动作纳入审计；后续仅需确认产品展示口径 |
| Pipeline collector 配置是补实现还是将 JUnit-only 写成正式产品限制 | F-PL-01 collector 配置补齐 |
| Allure/HTML 报告前端预览采用已上传目录入口还是 zip/html 单产物 | F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐；后端已递归上传目录文件 |
| 是否补 clone/setup/Docker daemon 失败黑盒 retry 场景 | F-EX-07 自动重试端到端补齐；`execute_run` 真实 DB 异常路径与 `worker_lost` callback 已进入自动重试，worker_lost 黑盒已进 nightly/manual external-stack |
| F-EX-08 采用单 worker 多队列还是多 worker 部署 | F-EX-08 优先级队列消费闭环 |
| F-NT-03 每渠道模板是否嵌入 `channels[]` | F-NT-01 / F-NT-03 通知规则与模板验收补齐 |
| F-EX-05 归档日志回看走流式 API 还是 artifact 复用 | 已决定并落地普通 JSON 分页 API；前端终态 Run 直接消费该 API，后端 required integration 已覆盖分页、对象缺失 404、API token `run.read` scope 和跨租户 404 一致性，后续只保留大日志体验/异常提示增强 |

## 5. 当前范围不做

详见 [`feature-catalog.md`](feature-catalog.md) §5。摘要：
- 账户锁定（已与 PRD §4 同步删除，滑动窗口 rate limit 已挡）
- 跨分支/跨环境对比专属视图、历史日志全文搜索、数据导出 CSV、Slack 通知
- Phase 4 全部项（K8s Job、多 Worker 管理、分区、插件市场）
- 邮箱验证、独立 Webhook 配置模块

---

## 历史阶段进度

| 阶段 | 状态 |
|---|---|
| Phase 1 MVP | ⚠️ 主线部分完成（项目/管道/手动执行/日志/结果主链路已就位；Git 凭证 clone 使用、Pipeline collector 配置、F-EX-01 commit/environment 指定入参与入队时延验收、F-PL-02 env_vars 加密、F-PL-03 产物/磁盘/资源记录闭环、F-LS-01~04 列表过滤/分页/搜索边角仍缺） |
| Phase 2 自动化与通知 | ⚠️ 主线部分完成（cron/webhook/API token 基础、重试/优先级队列原语、通知规则/模板基础已就位；API token scope、webhook 分支过滤+去重、自动重试主干、优先级队列主干已有测试证据；F-EX-02 静默窗口、F-EX-03 Git 平台事件解析/按 repo 匹配、通知规则/模板验收、钉钉/企微仍缺） |
| Phase 3 洞察与报告 | ⚠️ 主线部分完成（仪表盘/Flaky/系统状态页/项目级趋势已就位；Allure/HTML 产物预览闭环和单用例历史趋势仍缺） |
| Phase 4 规模化 | ⛔ 整体不在当前范围 |

逐项细节见 [`feature-catalog.md`](feature-catalog.md)。
