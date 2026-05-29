# QA 平台 TODO

> 完整功能盘子与状态见 [`feature-catalog.md`](feature-catalog.md)
> **首批可交付任务包见 [`tasks/`](tasks/README.md)**（codex-ready，含规格 + 起点 + 验收 + 约束）；本轮审计新增的待办若进入实施，需要后续补任务包。
> 本文件按优先级排序"近期要做什么 / 不做什么"，与 catalog §4 保持同步。
> 更新于 2026-05-29（PRD / catalog / tasks 与代码仍有已知偏移，审计证据见 [`doc-conflict-audit.md`](doc-conflict-audit.md)；首批 8 个任务包与对应 `feature/T*` 分支均已推送但未合入 `main`）

---

## 1. 高优先级 — PRD 验收未达（必须做）

| # | 项 | 来源 | 缺什么 |
|---|---|---|---|
| 1 | F-PL-02 环境变量加密 | PRD §3.2 验收 | 已完成：`env_vars` 以 JSON-safe AES-256-GCM envelope 存入 JSONB，API create/fetch/update、AAD 错配失败 audit、migration 加密既有数据、worker 解密注入容器环境变量均有自动化证据；nightly/manual external-stack 还断言 worker 注入密钥不会出现在平台产出的 artifact 元数据、下载内容或归档日志回看中；用户测试进程主动把密钥打印到 stdout/stderr 后的平台级日志脱敏仍需另立产品策略 |
| 2 | F-PM-01 / F-PM-02 Git 凭证执行闭环 | PRD §3.1 验收 | 已完成基线：项目绑定会校验凭证归属/类型与 Git URL 形态，manual/webhook/schedule Run metadata 只保存 `git_auth_method` / `credential_id` 引用，worker 执行时按项目/租户解密 token 或 SSH key 并通过临时 `GIT_ASKPASS` / `GIT_SSH_COMMAND` 注入 `GitSource.clone()`；unit 覆盖 token/SSH 注入、错误脱敏、worker 解密与 metadata 传播，required integration 覆盖真实 API/DB 下绑定项目后触发 Run 且 Run metadata / AuditEvent 不含 token 明文。剩余增强是用受控私有仓库补 nightly/manual 成功 clone 与凭证轮换黑盒 |
| 3 | F-PL-01 collector 配置补齐 | PRD §3.2 验收 | 已完成：Pipeline schema / ORM / migration / worker / executor 均支持 `collectors[]` 配置，默认保持 JUnit；`RunExecutor.execute()` 按配置调用 collector，JUnit collector 支持 `config.path` / `config.junit_xml` 相对路径；unit 与 required integration 覆盖 API 写回、审计脱敏、worker 映射和执行侧非硬编码 |
| 4 | 审计日志查询 API | catalog §4.1 | 已完成：`/api/v1/audit-events` 支持 Owner/Admin 分页查询、组合过滤、跨租户 404/空结果收敛，成功查询写 `audit_events.list` 自审计，member/viewer 403 与跨租户过滤 404 不误写自审计；API token 必须具备 `audit.read`，`run.read`/`project.read`/空 scope 被拒绝且不写自审计；正式 PRD 章节仍未补 |
| 5 | 审计写入覆盖补齐 | architecture §9.6 | 单 run cancel、批量取消/批量重试、SSE ticket、auth 失败审计 outage、audit-events 查询成功/拒绝副作用（含 `audit.read` 成功自审计查询过滤字段/分页/total 与 `run.read`/`project.read`/空 scope 拒绝 no self-audit）、projects/project members/pipelines/credentials/environments/notification rules/schedules、schedule worker 自动触发与 missing-pipeline skip、签名 webhook `run.trigger` 与 webhook filtered/duplicate 决策 audit 已补真实 DB 验证；refresh revoke Redis blip 不阻断 token 轮换，register/refresh/logout/API token 审计已验证不泄露 password、access token、refresh token、API token secret/hash，cancel 控制面已验证 Redis status event `previous` 与 audit before/after 一致，项目 `git_url` userinfo、pipeline 复杂配置密钥与敏感字段脱敏或 delete before_state 已覆盖；剩余写操作按安全风险继续补齐 |
| 6 | F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐 | PRD §3.2 / PRD §3.4 验收 | CPU/内存/超时、产物数量/大小限制、API `disk_mb` 到 Docker `StorageOpt.size` 传递、`results/` 递归上传和 Allure 目录文件落库已实现并有自动化证据；required integration 覆盖 environment `memory_mb` / `cpu_cores` / `disk_mb` / artifact limit 的 API create/get/list/update 读回、真实 DB 持久化和 audit before/after 脱敏，artifact 列表元数据分页/越界页到下载链接的真实 JWT/RBAC/API token scope/API/DB 行、DB-only 无 S3 副作用、对象存储未配置 503、bucket/key/TTL 参数与多 artifact 下载逐条 presign-only，同一 `run.read` token 下归档日志回看 + artifact 列表 + 下载 URL 联合路径，软删除 artifact 行确认 `deleted_at` 后下载入口与随机 UUID 一致 404 且不触发 presign/get_object，`project.read` token 不能枚举 artifact 名称/路径或换取预签名 URL，跨租户真实 artifact ID 与随机 UUID 一致 404 且不 presign；nightly/manual performance smoke 还覆盖 artifact 列表成功路径 DB-only 不触发 S3 presign/get_object、artifact 下载成功路径每请求一次 presign 且不读取对象、artifact 下载存储未配置稳定 503、artifact 列表拒绝不返回名称/路径、跨租户拒绝下载 p99 且拒绝路径不触发 presign；OOM/timeout backend 结果写 Run `timeout`、Redis status event 和日志收尾已有真实 DB/Redis 证据；nightly/manual external-stack smoke 覆盖真实 worker 后多 artifact 列表、预签名下载链接与 JUnit/HTML/log/Allure 内容下载，并断言 worker 注入密钥不进入平台产出的 artifact 元数据、下载内容或真实 `run.trigger` 审计状态；前端 run detail 已补 HTML artifact 预览 E2E；终止原因/退出码/耗时和 Docker stats 峰值 CPU/内存采样已写 Run summary 与日志，真实 Docker stats stream 黑盒已覆盖；release_candidate CI 会强制 OOMKilled heavy-docker 用例不被 skip/fail；仍缺多资源报告加载口径 |
| 7 | F-EX-05 日志归档回看闭环 | PRD §3.3 验收 | Redis Stream 实时日志/状态事件、断线续传、S3 JSONL 归档写入与归档日志读回 API 已实现；required integration 覆盖真实 API/RBAC/DB 下的 `/logs` 与 `/events` SSE `Last-Event-ID` 断点续传、归档失败真实 Redis retry marker/worker cron 重试、默认页、分页窗口、1500 行归档对象大页分页只读归档对象且不 presign、对象缺失 404、对象存储未配置 503、API token `run.read` scope 和跨租户 Run ID 404 一致性，并用同一 `run.read` token 串联 archived logs、artifact list 和 artifact download URL，断言日志只读 `logs/{run_id}.jsonl`、artifact 只 presign 不读对象；nightly/manual external-stack smoke 覆盖真实 worker 完成后的归档日志读回，并断言 worker 注入密钥不进入平台产出的归档日志响应或真实 `run.trigger` 审计状态；用户测试进程主动打印密钥后的日志脱敏策略未另行实现；nightly/manual performance smoke 覆盖真实日志 SSE 与状态事件 SSE 推送 < 2s、1500 行归档对象大页分页回看、成功回看只读 `logs/{run_id}.jsonl` 且不 presign、对象缺失稳定 404 且只读目标归档对象、存储未配置稳定 503，以及跨租户拒绝回看 p99 且拒绝路径不触发 S3 get_object；前端终态 run 已接入归档日志 API，并由真实 DB+S3 E2E 覆盖回放/搜索 |
| 8 | F-AU-02 API Token scope enforcement 补齐 | PRD §3.6 验收 | 已完成：API token scopes 已贯通 tenant/project 权限依赖，并有真实 API 矩阵覆盖只读、run.trigger、artifact download 与 archived logs 的 `run.read`、audit-events 的 `audit.read`、错误/空 scope；create/revoke 审计状态不泄露 full token、secret 或 secret_hash |
| 9 | F-AU-04 跨租户 404 完整收敛 | PRD §3.6 验收 | 已完成：Member/Viewer 的 path `project_id` 项目级权限依赖先验证租户可见性；跨 tenant、随机 UUID、软删除一致 404 |
| 10 | F-EX-01 手动触发参数与入队验收补齐 | PRD §3.3 验收 | 已完成：`RunTrigger` 接收 `pipeline_id` / `git_ref` / 40 位 `git_sha` / `environment_id` / `priority`，显式 environment 会校验归属项目；完整 commit SHA 会传给执行器 checkout；required integration 断言 API response、Run DB 行和 `run.trigger` audit after_state 一致；“触发后 < 5s 入队”已纳入 nightly/manual performance smoke 趋势哨兵 |
| 11 | F-NT-02 钉钉通知 | PRD §8 | 中国大陆网络硬约束 |
| 12 | F-NT-02 企业微信通知 | PRD §8 | 同上 |

## 2. 中优先级 — 验收边角 + 性能验证

| # | 项 | 来源 | 缺什么 |
|---|---|---|---|
| 13 | F-EX-02 静默窗口 | PRD §3.3 验收 | schedule worker 成功触发、missing-pipeline skip audit、静默窗口和 schedule tick 入队 SLO 已有自动化证据；发布冻结期不触发 cron 的产品化入口仍未实现 |
| 14 | F-EX-03 Webhook Git 平台事件解析 | PRD §3.3 验收 | GitHub signed push provider 入口已补：`/webhooks/github` 与 `/api/v1/webhooks/github` 会按 repository URL candidates 匹配项目，用匹配项目 `webhook_secret` 验签，并以系统身份创建 Run / filtered audit；项目级 webhook 继续覆盖 HMAC、branch filter、dedup 与终态同 commit 再触发；剩余是 GitLab/Gitee provider、PR/fork 策略、URL 规范化/歧义运营提示和更完整事件矩阵 |
| 15 | F-EX-07 自动重试端到端补齐 | PRD §3.3 验收 | API-facing `max_attempts` / `retry_on`、waiting retry run、execute_run 基础设施异常、真实 `RunExecutor` setup Docker daemon `ConnectionError` retry、setup script 非 0 与 git clone 失败不误 retry、worker_lost reclaimer 的真实 DB/Redis status event `previous=running`、orphan cleanup 与 retry Run 入队已进 required integration；nightly/manual external-stack 已补 worker_lost 黑盒重试，以及 credentialed clone failure / setup exit 1 不 retry、不落 artifact、不泄密黑盒，其中 clone failure 会回看 archived logs API 并断言空或非空响应都不含 secret/userinfo；剩余增强是把 Docker daemon 扰动扩到 external-stack 黑盒 |
| 16 | F-EX-08 优先级队列消费闭环 | PRD §3.3 验收 | 已补 compose high/medium/low worker 部署、manual priority 队列矩阵单测、真实 API/DB queue metadata 测试、真实 DB priority+FIFO 排序测试、nightly/manual performance smoke 覆盖 `dequeue_waiting` 恢复 waiting Run 入队，以及容量受限长队中 newer high priority 越过 older low backlog 的 priority preemption smoke；nightly/manual external-stack 已覆盖 high/low worker 队列隔离黑盒；真实长队公平性/抢占的更大规模压测仍可作为专项增强 |
| 17 | F-LS-04 测试结果 suite/关键字过滤 | PRD §3.7 验收 | 已完成：`/runs/{run_id}/results` 支持 `status` / `suite` / `q` 组合过滤，`q` 覆盖用例名和错误信息并转义 LIKE 通配符；unit 覆盖过滤条件，required integration 覆盖真实 DB 行组合过滤和重复约束 rollback 后恢复查询 |
| 18 | F-LS-01 执行列表过滤补齐 | PRD §3.7 验收 | 已完成：`/runs` 支持 status 多选、project_id、pipeline_id、git_ref、created_from/created_to 和创建时间排序；required integration 覆盖真实 DB 行的 pipeline/git_ref/time range 过滤 |
| 19 | F-LS-02 剩余列表分页补齐 | PRD §3.7 验收 | 已完成：credentials、project members、auth tokens 均返回 `PaginatedResponse`，支持 `page` / `per_page` / `total` / `data`，`per_page <= 100`；unit 覆盖 offset/limit 传递，required integration 覆盖真实 DB/API 分页、越界页空数组和 token 明文不回显 |
| 20 | F-LS-03 项目搜索排序补齐 | PRD §3.7 验收 | LIKE 转义已修；结果仍按 `created_at desc`，缺名称字母序 |
| 21 | F-RE-05 单用例历史趋势补齐 | PRD §3.4 验收 | 当前已有项目级趋势和 flaky 聚合；缺单个用例历史趋势 API/视图 |
| 22 | F-NT-01 / F-NT-03 通知规则与模板验收补齐 | PRD §3.5 验收 | 当前仅状态/pass_rate/失败数 AND 条件和规则级基础变量模板；缺 OR、连续失败次数、每渠道模板、项目名与失败用例变量 |
| 23 | 非功能性能压测 | PRD §4 / PRD §3.4 验收 | 已补 nightly/manual performance smoke 覆盖读 API、写 API、手动/webhook/schedule 触发入队 SLO（每次采样都写 `run.trigger` 审计且状态字段一致，webhook 额外验证保留 metadata 不覆盖执行配置且不进审计，schedule 额外验证系统身份审计和 `queue:low` 元数据）、waiting dequeue 恢复入队 SLO、取消 API p99、Redis 日志写读、SSE 实时日志推送 < 2s、真实 API token 并发读路径（归档日志分页、artifact 下载 presign、audit-events list、自审计增量和 S3 副作用哨兵）、归档日志读回 API（小样本与 1500 行大对象分页均只读 `logs/{run_id}.jsonl` 且不 presign，对象缺失稳定 404 且只读目标归档对象，存储未配置稳定 503，跨租户拒绝不读 S3）、artifact 列表元数据 API（成功路径 DB-only 不 presign/读 S3，并覆盖真实 `run.read` API token 下 1000 条大集合深页）、artifact 列表拒绝不返回元数据、artifact 下载链接 API（单次/burst 成功路径 presign-only 不读对象，存储未配置稳定 503，跨租户拒绝不 presign）、audit events 查询 API 与成功自审计写入、真实 `audit.read` API token 下大量过滤深分页、audit-events 角色/跨租户拒绝和 `run.read`/`project.read`/空 scope API token 拒绝都不写自审计、执行摘要生成 < 3s 趋势、external-stack worker 单样本链路与单 worker 10 容器并发证据；release_candidate 会按 `.github/performance-slo-manifest.json` 校验 SLO 名称集合、阈值来源、`gate_profile`、每项 `min_samples` 与 `passed=true`，并输出 p50/p99/max 失败摘要；完整容量压测和长期稳定性 SLO 仍需专项环境验证 |
| 24 | E2E CI 覆盖扩展 | fix-roadmap §4.3 | 已补三档 gate：PR/pr_like 跑轻量 `auth-flow`，nightly/schedule 跑固定真实 E2E（`real-login-flow`、`real-run-trigger`、`special-regressions`），release_candidate 跑全量 Playwright 且强制四个关键 spec 存在；nightly/release_candidate 会设置 `QAP_E2E_WORKER=1` 启动受控 worker，`real-run-trigger` 不再直接改 DB/Redis 造状态，而是经 UI modal 触发真实 run，并验证 worker 产出的终态、归档日志、唯一 JUnit result、`junit.xml` artifact 和页面结果/产物；CI 校验并上传 html/junit/test-results、spec 清单、Playwright `--list` 文本/JSON 测试清单、实际执行 JSON 和 E2E evidence manifest，且每个预期 spec 至少有 1 个 testcase，实际执行 JSON/JUnit 总数、逐 spec testcase 数和逐 spec title 集合必须匹配 `--list`，failure/error/skipped/unexpected/flaky 必须为 0 |
| 25 | 数据保留冷归档/读回增强 | architecture §8.4 / runbook §7 | 超期终态 Run 清理与级联删除、失败日志归档重试、归档日志读回 API 和前端终态 Run 回看主路径已闭环；当前仍缺 DB 行冷归档与对象存储生命周期运营报表 |

## 3. 低优先级 — 增强项

| # | 项 | 备注 |
|---|---|---|
| 26 | OpenTelemetry 装配 | 仅声明部分依赖，缺 OTLP HTTP exporter 与 instrumentation 代码 |
| 27 | 部署 checklist 完善 | 密钥/CIDR/lifecycle/Docker socket proxy 一键勾选；附到 `runbook.md` |

## 4. 技术债专项

| 任务 | 内容 | 备注 |
|---|---|---|
| T-LINT | 已完成：清理 main 既有 ruff 历史债务 | CI `backend-test` 已加入 `ruff check src tests`，后续新增债务会阻断；backend-test 已收口到 `tests/unit`，并用 manifest 解析 unit JUnit/coverage XML/JSON，避免 integration skip 混进 unit 证据 |
| T-FRONTEND-TS | 已完成：清理前端历史 TS build 债 | CI 前端 type/build 不再走 debt-aware 豁免；`npm run build` / `npx tsc --noEmit` / `npm run lint -- --quiet` 均应保持全量通过 |
| T-FRONTEND-API | 拆分/对齐前端 API DTO、hook 路径/响应形状与视图模型类型 | 已对齐 Pipeline schema/payload/collector 配置、project search `search -> q`、pipeline 嵌套路由、notification rule 分页解包与渠道类型、run trigger `pipeline_id/git_ref/git_sha/environment_id/priority`、Run response/view model、SSE 重连游标、TestResult `xfail` 状态，以及 Environment response/view/create/update payload 边界；CI 已新增 `frontend-api-contract`，导出 FastAPI OpenAPI 并校验前端关键 DTO / hook 映射，防止手写类型再次漂移；后续若继续硬化，优先演进为 OpenAPI 生成 DTO/client；以后端 `api/schemas.py` 为契约源 |
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
| `T-PIPELINE-COLLECTOR` | 已完成：F-PL-01 collector 配置补齐，见本文件 §1 与 catalog §1.2 |
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
| 是否需要独立审计日志清理任务 | 已实现：worker `cleanup_old_audit_events` 按 `retention_audit_days` 清理 `audit.event`，unit + 真实 Postgres integration 覆盖 |
| 是否需要 DB 行冷归档 | 数据保留冷归档/读回增强；`retry_failed_archives` 自动补偿已实现 |
| `/auth/sse-ticket` 临时凭证写入是否必须纳入审计 | 已按高风险凭证动作纳入审计；后续仅需确认产品展示口径 |
| Pipeline collector 配置是补实现还是将单一 JUnit 写成正式产品限制 | 已选择补实现：Pipeline 暴露 `collectors[]`，默认 JUnit，JUnit 支持自定义相对 report path |
| Allure/HTML 报告前端预览采用已上传目录入口还是 zip/html 单产物 | F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐；后端已递归上传目录文件 |
| 是否补 clone/setup/Docker daemon 失败黑盒 retry 场景 | F-EX-07 自动重试端到端补齐；required integration 已明确 setup Docker daemon 基础设施异常会 retry，setup script 非 0 与 git clone 失败不会误 retry；nightly/manual external-stack 已覆盖 worker_lost、credentialed clone failure（含 archived logs API 防 secret/userinfo 泄漏）和 setup exit 1 黑盒；剩余只是是否继续投入 Docker daemon 扰动黑盒 |
| F-EX-08 采用单 worker 多队列还是多 worker 部署 | 已按多 worker 部署落地 compose high/medium/low，并有 external-stack 队列隔离黑盒；performance smoke 已覆盖容量受限 priority backlog 中 high 越过 older low，后续只剩是否追加更重的长队公平性压测 |
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
| Phase 1 MVP | ⚠️ 主线部分完成（项目/管道/手动执行/日志/结果主链路、F-PL-01 collector 配置、F-PL-02 env_vars 加密、F-PM-01/02 Git 凭证 clone 基线和 F-LS-01/02/04 列表验收已就位；F-PL-03 产物/资源记录闭环和 F-LS-03 项目排序边角仍缺） |
| Phase 2 自动化与通知 | ⚠️ 主线部分完成（cron/webhook/API token 基础、重试/优先级队列原语、通知规则/模板基础已就位；API token scope、webhook 分支过滤+去重、GitHub push provider repo 匹配、自动重试主干、优先级队列主干已有测试证据；F-EX-02 项目级静默窗口、F-EX-03 更完整 Git provider 事件矩阵、通知规则/模板验收、钉钉/企微仍缺） |
| Phase 3 洞察与报告 | ⚠️ 主线部分完成（仪表盘/Flaky/系统状态页/项目级趋势已就位；Allure/HTML 产物预览闭环和单用例历史趋势仍缺） |
| Phase 4 规模化 | ⛔ 整体不在当前范围 |

逐项细节见 [`feature-catalog.md`](feature-catalog.md)。
