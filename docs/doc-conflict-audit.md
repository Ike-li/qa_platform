# 文档冲突审计报告

> 生成日期：2026-05-26
> 审计范围：`README.md`、`DESIGN.md`、`docs/**`、`frontend/README.md`、`frontend/FRONTEND_PROMPT.md`，并用 `main` 分支源码与配置做交叉验证。
> 审计方式：初始阶段为只读检索与源码核对；后续按审计结论完成了一轮低风险文档、配置与 E2E 入口修正。本文同时记录原始发现、已落地修复和剩余待决事项。

## 0. 当前结论

初始审计发现仓库文档之间存在系统性冲突，不是单个错别字级别的问题。主要原因是多份文档承担了不同历史阶段的职责，但没有标清“当前真相源”和“历史档案”边界。当前已完成第一轮低风险修复，剩余问题主要是需要 maintainer 决策的产品/架构边界，以及 feature 分支尚未合入 `main` 的状态表达。

> 修复进度：本文记录的是本轮审计的原始发现。2026-05-26 已完成第一轮文档清理：任务验收口径、`docs/tasks/` 8 个任务包的来源/路径/依赖/安全口径、README/development/.env/Makefile、feature-catalog/TODO、PRD 当前验收边界、architecture/runbook、frontend README/历史 prompt、fix-roadmap 历史定位、DESIGN 产品设计系统已更新；CI 已补 `workflow_dispatch`，push / PR 会自动跑稳定 `tests/e2e/auth-flow.spec.ts`，手动触发会跑全量 E2E；E2E real specs 已改用 `E2E_ADMIN_PASSWORD`；frontend lint 已恢复为 0 error、剩余 warning 不阻塞。仍需 maintainer 决策的问题见 §17。

当前最重要的事实：

- 当前分支：`main`。
- 本文是审计证据档案，不是实时 git 状态源；分支、SHA、ahead/behind 数均为审计时快照，后续请用 `git status --short --branch`、`git rev-parse --short HEAD`、`git rev-list --count origin/main..main` 和 `git rev-list --count main..origin/main` 现场确认。
- 最近一次已提交的审计收口以 `git log -1 --oneline` 为准；本文不硬编码当前 `HEAD`，避免提交后立即过期。
- 审计期间观察到 `origin/HEAD` 曾指向 `origin/phase1-release-prep` 而非 `origin/main`；后续脚本或人工操作应显式使用 `main` / `origin/main`，不要依赖 `origin/HEAD`。
- `feature/T01-env-vars-encryption`、`feature/T02-audit-query-api`、`feature/T03-dingtalk-notify`、`feature/T04-wecom-notify`、`feature/T05-silent-windows`、`feature/T06-webhook-branch-dedup`、`feature/T07-test-results-filter`、`feature/T10-opentelemetry` 均未合入 `main`。
- 因此，文档里凡是描述“已完成并合并”的状态，必须区分“`main` 已有”与“feature 分支已推送/验收”。
- `docs/fix-roadmap.md` 是历史 review 合并路线图，不应当作为当前实现状态的唯一真相源。
- `docs/doc-conflict-audit.md` 本身也是审计证据档案；当前执行真源仍是 `docs/feature-catalog.md`、`docs/TODO.md` 和 `docs/tasks/`。

建议的真相源边界：

| 文档 | 建议定位 |
|---|---|
| `docs/prd.md` | 产品目标与验收意图。只描述目标，不应误报当前实现状态。 |
| `docs/feature-catalog.md` | 当前 `main` 的功能盘点和近期 backlog。已完成第一轮状态与路径修正，后续要继续区分 `main` 已有与 feature 分支已推送。 |
| `docs/tasks/*.md` | 可执行任务包。应跟随 `main` 代码现状和 maintainer 最新验收口径。 |
| `docs/doc-conflict-audit.md` | 本轮文档冲突审计证据档案。可查为什么改，但不作为实时 git 状态或 backlog 排期真源。 |
| `docs/fix-roadmap.md` | 历史 review 档案和决策记录。建议加醒目说明：非当前 backlog。 |
| `frontend/FRONTEND_PROMPT.md` | 前端初始实现提示/历史提示词。已标为历史资料，不应作为 API 契约真相源。 |
| `DESIGN.md` | 当前 QA Platform 产品设计系统。应跟随前端实现和后台工具体验约束维护。 |

### 0.1 本轮已落地修复清单

以下是“十多轮”文档核对与修复已经写入仓库的结果：

| 范围 | 已落地内容 |
|---|---|
| 任务包 | 统一验收口径为“改动文件干净且不引入新错误”；修正 T01/T02/T03/T04/T05/T10 的加密服务命名、权限口径、通知渠道敏感信息处理、cron 入口、worker 内部项目解析、依赖风险和健康检查路径；复核 T06/T07 与当前源码一致；任务包来源改为按功能项引用 catalog，不再绑定会随排序变化的 §4 行号。 |
| 本地启动 | 修正 `make infra-up`、`make seed`、`.env.example` 默认值、rate limit env 名称、MinIO/JWT/encryption key/S3/CORS/HSTS 示例，并把快速启动统一到 `python3` + `.venv/bin/...`；`.env.example` 已文档化当前 `Settings` 的全部 `QAP_` 字段，其中可选 `QAP_ENCRYPTION_KEYS` 保持注释示例。 |
| README / development | 对齐本地启动、seed、SSE ticket 路径、插件清单、测试入口与 `qaplatform.main:create_app`；常用 Makefile 命令说明为依赖已激活虚拟环境，README 项目树的内置插件清单已同步为 pytest / Jest / Playwright / Go / JUnit / Git；单元测试、testcontainers 集成测试、`RUN_INTEGRATION_TESTS=1` 重型集成测试和 E2E 入口已拆开说明，E2E 本地运行说明已补充根目录 npm 依赖、`frontend/` 依赖和 `.venv` 前置条件。 |
| Python/Node toolchain | README、development 和 frontend README 的 Python/Node 前置条件已对齐：后端为 Python 3.12+，前端从过低的旧 Node 前置条件调整为 Node 22.13+ 或 20.19+，对齐 Vite 8 / ESLint 10 的 lockfile engines 与 CI Node 22。 |
| PRD / catalog / TODO | 拆分当前验收与远期愿景；修正 Slack、CSV、日志搜索、跨分支对比、F-AU-01 登录口径、F-AU-02 API token scope enforcement 状态、F-PM-01/F-PM-02 Git 凭证执行链路状态、F-PL-01 collector 配置状态、F-PL-03 资源限制状态、F-EX-01 手动触发 commit/environment/入队验收状态、F-EX-05 实时日志归档回看状态、F-EX-07 自动重试状态、F-EX-08 优先级队列状态、F-LS-01/02/03 列表搜索状态、F-RE-04 产物/Allure 预览状态、F-RE-05 单用例趋势状态、F-NT-01 AND 语义、F-NT-03 模板变量/每渠道模板状态、分支未合并状态、Phase 1/2/3 阶段进度、worker_lost 自动重试目标与当前实现边界、审计查询来源、审计写入覆盖率、审计保留状态、数据保留清理闭环和路径缩写约定。 |
| architecture / runbook | 对齐 React 前端、Pipeline 字段与 collector 当前固定 JUnit 边界、Git 凭证存储与 clone 注入链路边界、JSONB 设置、Redis Stream TTL、健康检查路径、API 路径、rate limit / 账户锁定口径、环境变量加密未达状态、审计写入覆盖边界、审计保留配置、审计查询 API 当前状态、实时日志与归档回看边界、状态事件 Redis Stream 机制、日志产物路径、资源限制与产物上传/预览当前边界、执行隔离默认网络策略与显式联网例外、重试与优先级队列当前闭环边界、开发/完整 Compose 栈边界、数据保留/S3 lifecycle 边界，以及 Docker socket 当前暴露与生产加固边界。 |
| frontend docs | 将 `FRONTEND_PROMPT.md` 标为历史提示词，补强“不可直接作为实现输入”的警示并修正其中最容易误用的 auth / SSE / artifact / Run / Pipeline schema / route / component library 示例；重写 `frontend/README.md` 为当前前端维护指南，并补充 `frontend/src/types/api.ts` 目前不可作为原始后端契约源。 |
| design | 将 `DESIGN.md` 从外部产品视觉参考重写为 QA Platform 当前产品设计系统；同时清理历史 frontend prompt 中与当前设计系统冲突的负字距与新卡片圆角口径。 |
| CI / E2E / frontend lint | CI 增加 `workflow_dispatch`；push / PR 跑稳定 `tests/e2e/auth-flow.spec.ts`，手动触发跑全量 E2E；Playwright config、CI 和本地文档已统一为根目录 E2E 项目、`frontend/` Vite dev server、`.venv/bin/python` 后端入口；real E2E specs 改用 `E2E_ADMIN_PASSWORD`；CI/test 默认 JWT secret 已满足 32 bytes 校验；frontend type/build 改为债务感知，只允许 3 个已知 TS 债务文件失败；修复 `environment-editor.tsx` 的 lint error，未触碰 3 个历史 TS 债务文件。 |
| dev extra | `pyproject.toml` 的 dev extra 增加 `ruff`，让开发文档中的 lint 命令有可安装来源。 |

### 0.2 本轮验证证据

| 检查 | 结果 |
|---|---|
| `git diff --check` | 通过 |
| Markdown 相对链接检查 | 通过，检查 21 个文档文件、20 个相对链接，缺失链接数 0 |
| 文档 API 路径 vs 当前 FastAPI router 清单 | 通过，endpoint doc issues 0；计划中的 `/api/v1/audit-events` 单独作为 T02 待办处理 |
| 文档命令引用 vs Makefile / npm scripts | 通过，command doc issues 0 |
| PRD 功能 ID vs feature-catalog 覆盖检查 | 通过，PRD 30 个 `F-*` 功能 ID 均在 catalog 中有状态行；catalog 无额外自造 PRD ID |
| TODO vs catalog §4 待办同步检查 | 通过，catalog §4.1 必做项 22 个均在 TODO 中有对应项；TODO 编号 1-27 连续；性能压测 / E2E CI 覆盖扩展 / OTel / 数据保留 / 部署 checklist 作为增强或运维项单列 |
| 任务包索引 vs 实际文件检查 | 通过，`docs/tasks/` 当前 8 个任务包均在索引中；`T<NN>` 为首批任务包稳定编号，不再声明等同 catalog §4 当前行号；T10 索引已补充计划新增的 `observability/tracing.py`。 |
| `.env.example` 加载 `qaplatform.config.Settings` | 通过，`rate_limit_per_minute=100`、`s3_presigned_url_ttl=3600`、`enable_hsts=True`、`cors_origins=["http://localhost:5173"]`、`retention_audit_days=1095` |
| `Settings` 字段 vs `.env.example` 覆盖检查 | 通过，39 个 `Settings` 的 `QAP_` 字段均已文档化；可选 `QAP_ENCRYPTION_KEYS` 为注释示例，额外的 `QAP_DB_USER`、`QAP_DB_PASSWORD`、`QAP_DB_NAME` 是 docker-compose 辅助变量 |
| README / development 快速启动命令 | 已统一为 `python3 -m venv .venv`、`.venv/bin/pip`、`.venv/bin/alembic`、`.venv/bin/python`、`.venv/bin/uvicorn` |
| `make -n infra-up seed` | 通过，目标展开为 `docker compose up -d postgres redis minio` 与 `python scripts/seed_admin.py` |
| `.github/workflows/ci.yml` YAML 解析 | 通过 |
| Python/Node 工具链版本对照 | 通过，`pyproject.toml` `requires-python >=3.12`，CI Python 为 3.12；README/development 写 Python 3.12+；CI Node 为 22，frontend README/README/development 写 Node 22.13+ 或 20.19+；lockfile 中 Vite 要求 `^20.19.0 || >=22.12.0`，ESLint 要求 `^20.19.0 || ^22.13.0 || >=24` |
| Docker/Compose 运行时对照 | 通过，`docker-compose.yml` 当前包含 postgres、redis、minio、api、frontend、worker；`make infra-up` 只启动基础设施，`make up` 启动完整栈；Dockerfile `qaplatform.api:create_app` 入口通过 lazy shim 指向 `qaplatform.main:create_app` |
| Docker/Compose 服务数当前复跑 | 通过，`docker compose config --services` 当前输出 6 个服务：minio、postgres、redis、api、frontend、worker；README 与 architecture 中“`make infra-up` 启动 PostgreSQL/Redis/MinIO、`make up` 启动完整 6 服务栈”的说法仍与 Makefile / Compose 一致。 |
| Docker socket / 执行隔离文档对照 | 通过，`docker-compose.yml` worker 仍直接挂载 `/var/run/docker.sock`；Docker backend 默认 `network_policy=deny` → `NetworkMode=none`，但 `allow` 会显式使用 bridge，`restricted` 需要部署侧创建 `qap-restricted` 网络；architecture 已改成当前事实 + 生产加固建议，runbook 已新增 Docker socket 风险章节 |
| 数据保留 / 日志归档闭环对照 | 有已知偏移，`LogStream.archive_logs` 成功后设置 1h TTL、失败后设置 24h TTL 并登记失败 Run；`worker/settings.py::retry_failed_archives` 会重试失败归档；`cleanup_old_runs` 已注册 cron 并硬删超期终态 Run（`done/failed/cancelled/timeout`）且覆盖 result/artifact/event 级联；归档日志读回 API 已补真实 DB/RBAC/API 测试，仍未发现 Redis 内存阈值拒绝入队实现，前端归档日志回看入口仍缺失 |
| F-EX-05 实时日志 / 归档回看对照 | 有已知偏移，`api/v1/sse.py` 已支持 `/runs/{run_id}/logs` 和 `Last-Event-ID`，`engine/log_stream.py` 已把日志归档到 `logs/{run_id}.jsonl`；后端已提供归档日志读回 API，前端 `log-viewer.tsx` 仅接 SSE 实时窗口，Redis TTL 过期后的 UI 回看闭环仍缺失 |
| 资源限制 / 产物 / Allure 预览闭环对照 | 有已知偏移，CPU/内存/超时已实现；worker 已把环境级产物 size/count 限制传入 executor，上传侧已在写 S3/DB 前强制校验；上传侧会递归上传 `results/` 下文件并标记 Allure 目录文件；`disk_bytes` 未进入 Docker HostConfig；OOM/timeout 能映射为 `timeout`，但未发现资源用量记录闭环；`api/v1/artifacts.py` 已返回 `download_url` / `expires_in`；`frontend` 仅对 `artifact.type === "allure-report"` 展示预览按钮，完整预览体验仍待补 |
| Playwright / E2E 配置对照 | 通过，根目录 `package.json` 提供 `npm run test:e2e`；`playwright.config.ts` 的 `testDir` 为 `tests/e2e`，会启动 `frontend` dev server 和 `.venv/bin/python -m uvicorn qaplatform.main:create_app --factory --app-dir src`，`global-setup.ts` 会启动 postgres/redis/minio、执行 alembic upgrade 与 seed |
| E2E 辅助脚本入口复核 | 发现 `scripts/run-e2e.sh` 仍直接用 `ADMIN_PASSWORD=admin123` seed 后运行 `tests/e2e/real-*.spec.ts`；默认值与 real specs 的 `E2E_ADMIN_PASSWORD || "admin123"` fallback 一致，但若调用者显式设置 `E2E_ADMIN_PASSWORD`，该脚本不会同步 seed 密码。当前 README/development/CI 的推荐入口仍是根目录 `npm run test:e2e`，不受此脚本偏差影响；若后续保留脚本，应让它透传 `E2E_ADMIN_PASSWORD`。 |
| Git refs / merge state 对照 | 审计快照通过：本地 8 个 `feature/T*` 分支与对应 `origin/feature/T*` SHA 一致且均未合入本地 `main`；审计时本地 `main` 比 `origin/main` 多 5 个 docs commit，`origin/HEAD` 指向 `origin/phase1-release-prep`。该行保留为快照，实时状态以现场 git 命令为准。 |
| Alembic 迁移链对照 | 通过，源码迁移链为单 head `006`；本地数据库当前版本为 `005`，需要在运行依赖真实 DB 的测试前执行 `.venv/bin/alembic upgrade head` |
| 通知 / Webhook 当前实现对照 | 通过，`main` 的 `ChannelRouter` 仅注册 `email` / `webhook`；T03/T04 钉钉/企微仍是未合入 feature 分支能力；`api/v1/webhooks.py` 当前仅做项目级触发与 HMAC 验签，T06 分支过滤/去重仍未合入 `main` |
| 通知规则 / 模板能力对照 | 有已知偏移，当前通知条件只支持 `status` / `pass_rate` / `failed` 的 AND 组合；模板是规则级 `NotificationRule.template`，变量仅 `run_id/status/passed/failed/total/pass_rate`，PRD 中的连续失败次数、每渠道模板、项目名与失败用例变量未闭环 |
| 自动重试 / 优先级队列闭环对照 | 有已知偏移，`worker/tasks.py` 已有 `_should_retry` / `_attempt_retry` 原语；当前已统一 API-facing `max_attempts` / `retry_on` 与 worker 读取口径，并覆盖 execute_run 基础设施异常真实 DB retry run；worker_lost 黑盒已进 nightly/manual external-stack，真实 Docker/clone/setup/container wait 其它黑盒场景仍留后续；`worker/scheduler.py` 会写 `queue:high/medium/low`，多队列消费闭环按当前 runbook/CI 分层继续维护 |
| Analytics / Flaky 实现口径对照 | 通过，项目级趋势与 flaky API / 前端入口存在；flaky 当前是同一 suite/name 在窗口内既有 passed 又有 failed/error 的聚合启发式，feature-catalog 已写清该口径 |
| smoke 脚本覆盖数对照 | 通过，`scripts/smoke/` 当前有 6 个页面脚本；原 catalog 固定写“83 测试点”已改为“检查点以脚本内 `log_step` 为准”，避免数字随脚本增长失真 |
| 审计写入覆盖对照 | 有已知偏移，多数主路径 mutating routes 已写 audit；`api/v1/runs.py` 的 `/batch/cancel`、`/batch/retry` 与 `/auth/sse-ticket` 临时票据创建已补审计写入；仍需按业务风险矩阵继续覆盖剩余写路径 |
| 前端 API 类型 vs 后端 schema 对照 | 有已知偏移，`frontend/src/types/api.ts` 中 `Run` 使用 UI 归一化字段 `branch`、`duration_seconds`、`total_tests` 等，而后端 `RunResponse` 是 `git_ref`、`duration_ms`、`summary`；`use-runs.ts` 触发 payload 仍带后端不接收的 `env_overrides/params`，且归一化时读取复数 `summary.errors`；Environment 仍有 `variables` 旧字段且缺 `env_vars` / resource limit 字段，`environment-editor.tsx` 也提交旧 `variables` payload；Pipeline 嵌套 selector / retry shape 仍是旧前端形状，`pipeline-modal.tsx` 也提交旧 payload；`use-projects.ts` 搜索参数仍传 `search` 而后端使用 `q`；`use-pipelines.ts` 仍调用不存在的 `/pipelines/{id}`；`use-notifications.ts` 把 paginated 通知规则列表当成裸数组；`use-sse.ts` fallback 会把 SSE URL 当 JSON API 轮询；当前部分页面由 hook 做适配，需单独 T-FRONTEND-API 拆分 DTO / view model 并修正 hook 路径/响应形状 |
| Run summary 字段口径对照 | 有已知偏移，当前执行摘要字段为 `total/passed/failed/skipped/error/pass_rate`，其中 `error` 为单数；feature-catalog 已从 `errors` 复数修正为 `error` 单数，但前端 `use-runs.ts::normalizeRun` 仍读取 `summary.errors`，已归入 `T-FRONTEND-API` |
| 历史前端 prompt schema 复扫 | 通过，`frontend/FRONTEND_PROMPT.md` 虽仍是历史资料，但 Data Models 示例已把 Run status 对齐为 `done/timeout`，并把 Pipeline `retry_policy` / `selector` / `trigger_config` 对齐当前 `api/schemas.py` 字段 |
| API token scope enforcement 对照 | 有已知偏移，`api/auth/permissions.py::check_permission` 支持 `scopes`，但 `api/deps.py::get_current_user` 会丢弃 middleware user 的 scopes，且 `require_project_permission` / `enforce_project_action` 构造 `PermissionContext` 时也未传 scopes；因此不能把 scope enforcement 标为全路由完成 |
| API token 传递方式对照 | 通过，architecture 已从旧 `X-API-Token` 口径改为当前 `Authorization: Bearer qap_<token_id>_<secret>`；T10 中剔除 `X-API-Token` 仅作为防御性敏感 header 过滤，不表示当前认证入口 |
| Rate limit 语义对照 | 通过，源码是认证高风险端点 strict rate limit（login/register/token/refresh/SSE ticket），不是仅失败请求；PRD、architecture、feature-catalog 和 `.env.example` 已同步该边界 |
| Rate limit 限流桶 / Redis 异常续扫 | 通过，补充当前实现细节：Bearer 请求按 token hash 限流，其他请求按 `QAP_TRUSTED_PROXIES` 解析后的客户端 IP 限流；Rate limit Redis 操作异常时，认证高风险端点 fail-closed 返回 503，非认证端点放行。已同步 PRD、architecture、feature-catalog 与 runbook。 |
| T02 审计查询过滤参数对照 | 通过，`AuditEvent` ORM 与写入端字段为 `resource_type/resource_id`；T02 任务包已从旧 `target_type/target_id` 示例修正为同名查询参数 |
| 凭据加密 / Project.settings 口径复扫 | 通过，凭据 AAD 已按源码写成 `credential:{project_id}:{name}` 上下文；architecture 已区分 `Project.settings.webhook_secret` 当前可用、`allowed_branches` / `silent_windows` 为 T06 / T05 计划字段；runbook 已把密文字段从旧 `Credential.value` 改成 `Credential.encrypted_value` |
| 测试运行入口对照 | 通过，单元测试建议 `pytest tests/unit -q`；`make test` 仍表示 pytest 默认集合，文档已标明可能触发未 gate 的 testcontainers 集成用例；完整重型集成测试使用 `RUN_INTEGRATION_TESTS=1` |
| CI / integration / E2E JWT secret 长度复扫 | 通过，当前配置中的默认测试 secret 均 ≥ 32 bytes |
| `ruff check tests/e2e/backend_app.py tests/integration/conftest.py tests/unit/test_auth_middleware.py` | 通过 |
| `pytest tests/unit/test_auth_middleware.py -q` | 通过，2 passed；仅有 testcontainers deprecation warning |
| frontend package lock engines | 已核对 Vite 8 要求 `^20.19.0 || >=22.12.0`，ESLint 10 要求 `^20.19.0 || ^22.13.0 || >=24` |
| 根目录 `npm run test:e2e -- --list tests/e2e/auth-flow.spec.ts` | 通过，列出 1 个稳定冒烟用例 |
| `cd frontend && npm run lint` | 通过，0 error；剩余 4 个 warning 均为既有 hook dependency/watch 提示 |
| frontend debt-aware build gate | 通过，5 个 TS 错误全部来自 `analytics-panel.tsx`、`notification-rules-panel.tsx`、`trigger-run-modal.tsx` |
| 高风险旧口径关键词复扫 | 通过，unexpected matches 0；剩余旧口径仅在本报告原始发现、`fix-roadmap.md` 历史档案、负向约束、“不要存 localStorage”的安全说明，或 `T-FRONTEND-API` 已登记的 `search/q`、`env_overrides/params`、`summary.errors` 偏移中；随后又清理了 `FRONTEND_PROMPT.md` Authentication Flow、Run schema 与设计 token 段的旧口径，并去掉了 `feature-catalog` 中已过时的“部分 API 路径过期”当前偏移表述 |
| 资源限制旧口径复扫 | 通过，`F-PL-03` 不再标 ✅；architecture 不再把磁盘限制或 OOM/timeout 资源用量记录写成当前已实现；PRD §4 的 500MB 产物容量目标已在 catalog 非功能表中标为 ⚠️ |
| Allure / 产物旧口径复扫 | 通过，`F-RE-04` 不再标 ✅；“Allure 已就位 / 需实测确认”只保留在本报告历史发现语境，当前 catalog / TODO / architecture 均改为部分完成与待补闭环 |
| 执行隔离网络策略复扫 | 通过，PRD / catalog / architecture 已改为“默认 deny 隔离 + allow/restricted 显式例外”；`restricted` 需要部署侧提供 `qap-restricted` 网络 |
| README / PRD / catalog 入口复扫 | 通过，README 核心功能已改为当前主链路、Docker OOMKilled 状态识别、`results/` 产物上传与预签名下载；PRD 顶部、worker_lost 场景和路线图均标明“产品目标不等于当前 main 完成状态”；catalog/TODO 负责记录 `main` 当前缺口 |
| PRD 用户旅程复扫 | 通过，测试经理旅程中的 release / main 对比已改为“基于已有 branch 执行记录的轻量对比”，避免与“跨分支/跨环境专属对比视图为远期增强”的范围说明冲突 |
| 当前文档代码路径引用抽查 | 通过，按当前脚本口径解析到 317 个仓库路径引用且均可解析；另有 8 个明确计划新增路径、285 个 glob/模板路径按非文件路径跳过；缺失仓库路径 0 |
| catalog 剩余 ✅ 项抽查 | 通过，抽查 archived 项目触发 409、`F-RE-01/03` JUnit 与 `/runs/{run_id}/results`、`F-AU-01/03` JWT/Argon2/RBAC、项目成员 CRUD、通知规则 CRUD、SSE ticket、Prometheus `/metrics`、`/health` / `/ready`、安全头与 iframe sandbox；`F-PL-01`、`F-AU-04` 与 `F-EX-01` 在后续更细复核中发现验收缺口，见下方专项记录。 |

### 0.3 最终复核记录

2026-05-26 收尾复核再次确认：

| 检查 | 结果 |
|---|---|
| `git diff --check` | 通过 |
| Markdown 相对链接检查 | 通过，检查 21 个文档文件，缺失相对链接 0 个 |
| TODO 编号连续性 | 通过，表格编号 1-27 连续 |
| catalog §4.1 vs TODO | 通过，catalog §4.1 的 22 个未达 PRD 验收项均可在 TODO 中找到 |
| TODO / catalog / 审计任务映射当前复跑 | 通过，TODO 编号仍为 1-27 连续；catalog §4.1 仍为 22 个未达 PRD 验收项，§4.2 仍为 5 个增强项；本文 §15 的 21 个 `T-*` 后续任务别名均能在 TODO 或 catalog 找到落点；本文 §17 仍为 12 个 maintainer 决策项。 |
| 高风险旧口径扫描 | 无意外命中；剩余 `PRD §9.6`、`X-API-Token`、CSV / Slack / 跨分支对比只出现在旧引用说明、防御性过滤或当前范围不做语境；`search`、`env_overrides/params`、`summary.errors` 只出现在 `T-FRONTEND-API` 前端债务说明或历史档案语境 |
| 改动 Python 文件 ruff | 通过，`tests/e2e/backend_app.py`、`tests/integration/conftest.py`、`tests/unit/test_auth_middleware.py` 均干净 |
| 历史 frontend prompt 接口示例复扫 | 发现并修正项目列表搜索参数：当前 `api/v1/projects.py::list_projects` 使用 `q`，不是旧示例里的 `search` |
| 历史 frontend prompt 设计/路由复扫 | 继续清理旧 Linear 命名和 pipeline detail 路由暗示，并把文件结构示例补到当前 `runs/list.tsx`、`admin/status.tsx`、`not-found.tsx`、`index.css`、layout wrappers 等入口；当前设计源以 `DESIGN.md` 为准，当前前端没有独立 pipeline detail route |
| 前端路由与 CI 门禁续扫 | 通过，`frontend/src/App.tsx` 当前路由为 `/login`、`/`→`/projects`、`/projects`、`/projects/:id`、`/runs`、`/runs/:id`、`/settings`、`/admin/status` 和 catch-all；`frontend/FRONTEND_PROMPT.md` 的页面路由清单已与之对齐且标为历史提示词。CI 的 frontend type/build gate 均只豁免 `analytics-panel.tsx`、`notification-rules-panel.tsx`、`trigger-run-modal.tsx` 这 3 个 `T-FRONTEND-TS` 文件，`frontend/README.md` 已有 Known TypeScript Debt 说明。 |
| 前端 lint 续扫 | 通过，`frontend/` 下 `npm run lint` 当前为 0 error / 4 warning；warning 分别来自 `frontend/src/components/projects/create-project-modal.tsx`、`frontend/src/components/projects/pipeline-modal.tsx`、`frontend/src/components/runs/log-viewer.tsx`、`frontend/src/components/runs/trigger-run-modal.tsx` 的 React Compiler incompatible-library 提示，未新增 lint error。 |
| 前端 TS build 续扫 | 通过，`frontend/` 下 `npm run build` 仍失败于 5 个历史 TS error，且 error 只出现在 `frontend/src/components/projects/analytics-panel.tsx`、`frontend/src/components/projects/notification-rules-panel.tsx`、`frontend/src/components/runs/trigger-run-modal.tsx` 这 3 个 `T-FRONTEND-TS` 文件；未发现新的 TS 错误文件。 |
| CI workflow / E2E 入口续扫 | 通过，`.github/workflows/ci.yml` 当前包含 `push`、`pull_request`、`workflow_dispatch`；push / PR 的 E2E job 只运行 `tests/e2e/auth-flow.spec.ts`，`workflow_dispatch` 运行根目录 `npm run test:e2e` 全量；根目录 `package.json` 仅提供 `test:e2e`，`frontend/package.json` 提供 `dev/build/lint/preview`，与 README / development / TODO / catalog 当前说法一致。`playwright.config.ts` 与 `tests/e2e/global-setup.ts` 仍以 `.venv/bin/python`、docker compose 基础设施、`E2E_ADMIN_PASSWORD || "admin123"` seed 为本地 E2E 前置，已在前序 E2E 入口说明中记录。 |
| E2E 辅助脚本承接续扫 | 发现 `scripts/run-e2e.sh` 仍固定 `ADMIN_PASSWORD=admin123` seed，而标准 `tests/e2e/global-setup.ts` 已透传 `E2E_ADMIN_PASSWORD || "admin123"`；此偏差此前只写在本报告，现已补到 `docs/TODO.md` #24 与 `docs/feature-catalog.md` §4.2 的 E2E CI 覆盖扩展备注中。 |
| 内部章节引用复核 | 通过，`architecture §8.4`、`architecture §9.6`、`runbook §7` 和本文 `§17` 均存在；旧 `PRD §9.6` 仅保留在历史冲突说明或“旧引用不存在”语境 |
| feature 分支合并状态复核 | 通过，8 个 `feature/T*` 分支本地/远端 SHA 一致且均未合入 `main`；`origin/main` 仍是本地 `main` 的祖先，本地 `main` 未落后远端 |
| Git refs 续扫 | 审计快照通过：审计时分支为 `main` 且无 upstream；本地 `main=34937a3`、`origin/main=302ede0`，`origin/main...main` 为 `0 5`；`origin/HEAD` 指向 `origin/phase1-release-prep`。T01/T02/T03/T04/T05/T06/T07/T10 的本地 feature 分支与对应 `origin/feature/*` SHA 均一致，且 `git merge-base --is-ancestor <feature> main` 均为 no。该行不表达提交后的实时状态。 |
| Git refs 当前复跑 | 审计快照通过：`docs/tasks/` 当时只有 T01/T02/T03/T04/T05/T06/T07/T10 这 8 个任务包；本地 T01/T02/T03/T04/T05/T06/T07/T10 对应首批任务分支与 `origin/feature/*` SHA 一致，且本地/远端 feature 均未合入 `main`；`origin/main...main` 当时为 `0 5`，`origin/HEAD` 指向 `origin/phase1-release-prep`。实时状态以现场 git 命令为准。 |
| 任务包索引语义复核 | 已把 `docs/tasks/README.md` 表格的 `是否需 alembic` 改成 `Alembic / 数据迁移`，并用“需要/不需要”替代 ✅/❌，避免误读为任务完成状态 |
| 路径/命令引用复核 | Makefile 引用、npm scripts 和 Compose 服务数量均对齐；已把当前 TODO/catalog 中的 `runs.py`、`auth-flow.spec.ts` 短名补成 `api/v1/runs.py`、`tests/e2e/auth-flow.spec.ts` |
| CI / E2E 待办语义复核 | `E2E 测试 CI 自动触发` 已更名为 `E2E CI 覆盖扩展`；当前事实是 push / PR 已跑稳定 `tests/e2e/auth-flow.spec.ts`，剩余待办仅是是否扩大自动覆盖。 |
| fix-roadmap E2E 状态复核 | 发现 `fix-roadmap.md` 历史条目仍保留“auth-flow push 触发未启用”的 2026-05-25 状态；已追加 2026-05-26 后续更新，说明当前 CI 已在 push / pull_request 跑 `tests/e2e/auth-flow.spec.ts`，workflow_dispatch 跑全量 E2E，剩余项仅是覆盖扩展。 |
| 继续复核校验 | 通过，重跑 endpoint / command / backlog 脚本：早期批次的 FastAPI route / endpoint 计数已被后续 `create_app()` 65 个 HTTP 路由复核覆盖；catalog §4.1 的 22 个必做项与 §4.2 的 5 个增强项均已在 TODO 中承接；`git diff --check` 通过。扫描中的 `/admin/status` 是前端路由，旧 SSE / environment 路径和 `make ...` 只在历史冲突说明中出现，已按语境过滤。 |
| 章节与路径引用续扫 | 通过，显式章节引用除历史负向 `PRD §9.6` 外问题 0；当前仓库路径引用均可解析，计划新增路径单独归类，glob/template 引用按非文件路径跳过。已顺手把 T10 tenant-span deps 引用、T02 planned router、T05 scheduling 注释、architecture compose 注释和 fix-roadmap auth 路径简写改成更明确的路径写法。 |
| 审计报告计数自洽性复核 | 通过，追加多轮复核记录后不再在中间批次行保留易漂移的章节引用总数；以最终机器校验行记录当前 TODO、catalog、PRD、任务别名、链接和旧计数残留扫描结果。 |
| 后续任务承接复核 | 发现本文 §15 的 `T-*` 后续任务别名在 TODO 中不全可搜索；已在 `docs/TODO.md` 增加“审计报告任务 ID 对照”。复核结果：本文 §15 的 21 个 `T-*` 任务别名全部能在 TODO 或 catalog 找到落点，缺失 0。 |
| maintainer 决策承接复核 | 发现本文 §17 的 12 个产品/架构决策项此前只散落在对应 TODO 项中，缺少集中映射；已在 `docs/TODO.md` 增加“Maintainer 决策待确认”表。复核结果：§17 的 12 个决策关键词均能在 TODO 找到承接，TODO 编号仍为 1-27 连续。 |
| “不做”范围语义复核 | PRD 对跨分支对比、历史全文搜索、CSV、Phase 4 等写的是当前阶段不纳入验收；catalog/TODO 已改成“当前范围不做”，避免误读为永久性产品禁令。 |
| PRD 功能 ID 映射复核 | `docs/prd.md` 中 30 个 `F-*` 功能 ID 均在 `feature-catalog.md` 中有对应行；catalog 未自造额外 PRD 功能 ID。 |
| catalog 维护约定复核 | `feature-catalog.md` 的状态图例和维护约定已同步为“当前范围已决策不做 / 当前范围不做”，避免后续把远期增强误写成永久禁令。 |
| 非历史文档行号复核 | `feature-catalog.md` 与首批任务包中的源码引用已从易漂移的具体行号改为文件级或 `file.py::symbol` 引用；`fix-roadmap.md` 作为历史档案仍保留当时 review 行号。 |
| 任务包 “不做” 口径复核 | T02 中搜索全文 / CSV 导出约束已改为“当前范围不做，见 catalog §5”，与 PRD 远期增强口径保持一致。 |
| T10 依赖例外复核 | T10 已明确：未获 maintainer 确认时必须停下报告，不得写无法导入的 OTLP exporter 代码；若获准新增 exporter 依赖，PR 描述必须说明偏离。 |
| 通知渠道范围复核 | `feature-catalog.md` 的 Slack 口径已同步为“当前范围不做”，钉钉/企微仍作为 PRD §8 中国大陆网络硬约束待补。 |
| 任务包完整性复核 | `docs/tasks/README.md` 已列全 8 个 `T*.md` 文件；每个任务包均包含来源、必要性、背景、实施起点、验收标准、约束、不要做和 semantic commit 建议。 |
| 任务包旧口径负向命中复核 | 任务包专项扫描中剩余 `pytest-httpx`、`/health/live`、`PRD §9.6` 等命中均为“不要引入 / 旧引用不存在 / 当前源码不是该路径”的负向说明，不是执行要求。 |
| 任务包结构量化复核 | 通过，8 个任务包逐一扫描：来源 / 必要性 / 预计 / 背景 / 验收标准 / 约束 / 不要做 / commit 信息缺失数 0；`pytest-httpx` 命中 2 处，均为 T03/T04 “不要引入”的负向约束；`httpx_mock`、旧 `make lint 干净`、旧 `npm run build 通过` 意外命中 0。 |
| 前端 nginx / 静态资源安全头复核 | 通过，`frontend/Dockerfile` 会复制 `frontend/nginx.conf`，该配置已包含 `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Strict-Transport-Security`、`Permissions-Policy`；`feature-catalog.md` 的安全头 ✅ 口径与当前仓库一致。 |
| FastAPI 路由清单复核 | 通过，通过 `create_app()` 导出的当前路由重新核对 `/api/v1`、`/health`、`/ready`、`/metrics`；文档中仍出现的 `/api/v1/audit-events` 是 T02 待办项，未误标为 main 已实现。 |
| FastAPI 端点引用续扫 | 通过，`create_app()` 当前导出 65 个 HTTP route，其中 58 个属于 `/api/v1`，加上 `/health` / `/ready` / `/metrics` 后为 61 个后端运行路径；抽取文档中的 207 个端点引用后，剩余不匹配仅为本报告历史冲突说明里的旧 `/api/v1/environments/{id}` 和 `fix-roadmap.md` 历史建议里的旧 `/api/v1/artifacts/{id}` / `/api/v1/runs/{id}/test-results`，均未作为当前实现状态使用。 |
| Makefile / npm script 引用复核 | 通过，README、development 与任务 README 中出现的 `make ...` 均能在 Makefile 找到；`npm run test:e2e`、`npm run dev/build/lint/preview` 均分别对应根目录或 `frontend/package.json` scripts。 |
| Makefile / npm script 当前复跑 | 通过，当前 Makefile targets 为 `up/down/infra-up/logs/migrate/migrate-create/test/lint/format/seed`；根目录 `package.json` 只有 `test:e2e`，`frontend/package.json` 有 `dev/build/lint/preview`。非历史文档中的 `make` 与 `npm run` 引用问题数均为 0；不存在的 `make frontend-test` 仅保留在本文历史冲突说明中。 |
| 运行时版本口径复核 | 通过，`pyproject.toml` 要求 Python `>=3.12`，CI 与 Dockerfile 使用 Python 3.12；CI 与前端 Dockerfile 使用 Node 22，README / development / frontend README 的 Node 22.13+ 或 20.19+ 前置条件覆盖 Vite 8 与 ESLint 10 的 engines。 |
| Python / Node 版本当前复跑 | 通过，`pyproject.toml` 仍为 `requires-python >=3.12`，后端 Dockerfile 为 `python:3.12-slim`，CI Python 为 3.12；前端 Dockerfile 为 `node:22-alpine`，CI Node 为 22；`frontend/package-lock.json` 中 Vite 8.0.13 要求 `^20.19.0 || >=22.12.0`，ESLint 10.4.0 要求 `^20.19.0 || ^22.13.0 || >=24`，README / development / frontend README 的 Node 前置条件仍覆盖当前依赖。 |
| 待确认 / 待补措辞复核 | 通过，非历史文档中的“待补 / 未实现 / 缺口 / 需确认”均已归入 TODO、catalog §4 或本文 §17 决策清单；`fix-roadmap.md` 中的旧 ✅ / TODO 语境由历史档案说明隔离，不再作为当前 `main` 真相源。 |
| 分层 import / DB access 复核 | 发现当前实现偏离 architecture 目标：`engine` 仍反向依赖 `api.metrics` / `worker._redact`，部分 API 路由仍直接 SQLAlchemy 查询；architecture 已改为“目标规则 + 当前偏差”，TODO 已新增 `T-ARCH-LAYERS` 技术债。 |
| S3 / MinIO 路径与 lifecycle 复核 | 通过，`engine/log_stream.py` 归档日志到 `logs/{run_id}.jsonl`，`engine/executor.py::_upload_artifacts` 上传 `results/` 文件到 `reports/{run_id}/{relative_path}`；runbook 的 `logs/` 与 `reports/` lifecycle 前缀和当前代码一致。 |
| 插件协议示例复核 | 通过，README 插件开发示例包含当前 `RunnerProtocol` 要求的 `build_command()` 与 `run_tests(..., env_vars=None)`；architecture §7.2 的协议片段与 `plugins/protocols.py` 当前签名一致。 |
| Run / TestResult 状态枚举复核 | 通过并发现前端类型债：Run 后端枚举与前端 README 映射说明已对齐；TestResult 后端枚举含 `xfail`，PRD / catalog / T07 / TODO / frontend README / historical frontend prompt 已同步为“PRD 最低验收 + 后端扩展”，前端运行类型缺口归入 `T-FRONTEND-API`。 |
| 文档端点示例复核 | 通过，README、architecture、historical frontend prompt 中列出的端点均能和当前 FastAPI router 对齐；T05 任务包和 feature-catalog 的静默窗口项目更新示例均已统一为完整 `PUT /api/v1/projects/{project_id}`。 |
| 前端 API 类型字段复核 | 发现并登记前端类型债扩大面：`Project` / `TestResult` / `Artifact` 顶层字段与后端响应基本对齐，但 `Run`、`Environment`、Pipeline 嵌套 selector / retry shape 仍与后端 schema 偏离；frontend README、TODO 与本文 §3.9 已同步，代码修复留给 `T-FRONTEND-API`。 |
| 历史 frontend prompt Pipeline 示例复核 | 通过，`FRONTEND_PROMPT.md` 的 Pipeline 示例已补齐 stage `plugin/config/continue_on_error/phase` 字段，不再保留未定义的 `Stage[]` 类型；运行代码里的旧 Pipeline 类型偏移仍归 `T-FRONTEND-API`。 |
| architecture 实体字段表复核 | 发现 Environment 行过于抽象，只写 `resource_limits(JSONB)` 容易遮蔽当前 API 暴露的 `memory_mb`、`cpu_cores`、产物限制、`cache_key` 等离散字段；architecture §8.2 已补齐这些字段并说明 ORM 仍保留 `resource_limits` JSONB。 |
| Environment 资源字段存储复核 | 通过并细化，`alembic/versions/002_add_environment_resource_fields.py` 只新增 `memory_mb` / `cpu_cores` 两个离散列；`api/v1/environments.py` 将 `max_artifact_size_mb` / `max_artifacts_count` 写入 `Environment.resource_limits` JSONB 后再映射到 API response。architecture §8.2 已改为明确这两个产物限制字段不是 ORM 独立列。 |
| 历史 frontend prompt API token 字段复核 | 发现 settings 页文案仍写旧 `last_used` / `prefix`；已改为当前 `ApiTokenListItem` 返回的 `token_id/name/scopes/expires_at/last_used_at/is_revoked/created_at`。 |
| 历史 frontend prompt 项目详情字段复核 | 发现项目详情示例仍把 pipeline 列表写成旧 `framework` 字段、environment 列表写成纯 key-value；已改成 stage/trigger/retry 摘要与 base image/resource/env vars 口径，运行代码中的 API 形状偏移仍归 `T-FRONTEND-API`。 |
| 前端 pipeline hook 路径复核 | 发现 `frontend/src/hooks/use-pipelines.ts` 的详情/更新/删除仍调用不存在的 `/pipelines/{id}`；后端实际路由是 `/api/v1/projects/{project_id}/pipelines/{pipeline_id}`。已登记到 `T-FRONTEND-API`，本轮文档审计不修改运行代码。 |
| 前端 notification hook 响应形状复核 | 发现 `frontend/src/hooks/use-notifications.ts` 将通知规则列表声明为 `NotificationRule[]`，但后端 `api/v1/notifications.py::list_notification_rules` 返回 `PaginatedResponse[NotificationRuleResponse]`；已登记到 `T-FRONTEND-API`。 |
| 前端 SSE fallback 复核 | 发现 `frontend/src/hooks/use-sse.ts` 的 fallback 会对传入 SSE URL 执行 `api.get<T>(url)`；当前日志组件传入 `/api/v1/runs/{id}/logs`，该路径是 SSE ticket 流，不是普通 JSON API，且可能与 axios baseURL 形成双 `/api/v1`。历史 prompt 已从“polling fallback”改为“重连或另建 JSON 端点”。 |
| 前端 pipeline modal payload 复核 | 发现 `frontend/src/components/projects/pipeline-modal.tsx` 仍以 `framework/pattern/on_push/on_schedule/max_retries/backoff` 构造 payload；后端 `PipelineCreate/Update` 接收的是 `stages`、`selector.include_paths/exclude_paths/tags/expression/regex/on_empty`、`trigger_config.type/source/conditions/target/dedup_window_seconds`、`retry_policy.max_attempts/retry_on/backoff_seconds/scope`。已登记到 `T-FRONTEND-API`。 |
| 前端 environment editor payload 复核 | 发现 `frontend/src/components/projects/environment-editor.tsx` 创建/更新仍提交 `variables` 字段；后端 `EnvironmentCreate/Update` 使用 `base_image`、`env_vars`、资源/产物限制、`network_policy`、`cache_key` 等字段。已登记到 `T-FRONTEND-API`，本轮不改运行代码。 |
| 前端 project search 参数复核 | 发现 `frontend/src/hooks/use-projects.ts` 的列表查询参数仍是 `search`；后端 `api/v1/projects.py::list_projects` 当前只声明 `q`。已登记到 `T-FRONTEND-API`，运行代码修复留给专项任务。 |
| 前端 run trigger / summary 归一化复核 | 发现 `frontend/src/hooks/use-runs.ts::useTriggerRun` 仍提交 `env_overrides` / `params`，但后端 `RunTrigger` 只接收 `pipeline_id`、`git_ref`、`priority`；同文件 `normalizeRun` 仍读取复数 `summary.errors`，而后端 executor / runner summary 使用单数 `error`。已登记到 `T-FRONTEND-API`。 |
| 历史 frontend prompt health 路径复核 | 通过，当前健康检查在根路径 `/health` 而非 `/api/v1/health`；`FRONTEND_PROMPT.md` 已把 Health 小节标为 outside `/api/v1`，避免被前面的 Base URL 误读。 |
| 文档源码路径存在性复核 | 通过，非历史文档里的源码路径均存在；仅 `docs/tasks/T02_audit_query_api.md` 的 `src/qaplatform/api/v1/audit_events.py` 与 `docs/tasks/T10_opentelemetry.md` 的 `src/qaplatform/observability/tracing.py` 是任务包明确要求新增的计划文件。 |
| Markdown 本地链接复核 | 通过，README、DESIGN、frontend 文档与 `docs/**/*.md` 中的相对 Markdown 链接均能解析到现有文件。 |
| 任务包章节引用复核 | 通过，8 个任务包的来源均指向存在的 PRD / feature-catalog / fix-roadmap 章节；旧 `PRD §9.6` 仅保留在 T02 和本报告的“旧引用不存在”说明中，不再作为执行依据。 |
| 任务包硬约束复核 | 通过，任务 README 已集中声明审计写入、commit 拆分、跨租户 404、依赖新增和 hook 约束；原先“Hook：不跳过 `--no-verify`”的歧义措辞已改为“不要使用 `--no-verify` 或 `--no-gpg-sign` 跳过 hook / 签名”。 |
| Settings / `.env.example` 续扫 | 通过，排除 Pydantic 自身 `model_config` 后，`Settings` 的 39 个 `QAP_` 字段均在 `.env.example` 中有记录；额外 `QAP_DB_USER`、`QAP_DB_PASSWORD`、`QAP_DB_NAME` 是 docker-compose 本地辅助变量。 |
| 环境变量命名全量续扫 | 通过，文档/测试中除 `Settings` 与 docker-compose 辅助变量外的 `QAP_*` 命中均已归因：`QAP_` 是通用前缀说明，`QAP_API_URL` / `QAP_TEST_OOM` 是测试辅助开关，`QAP_WORKER_QUEUE` 是 `WorkerSettings` 直接读取的 worker 队列配置，`QAP_OTEL_ENABLED` 是 T10 计划新增配置，`QAP_RATE_LIMIT_REQUESTS` 仅保留在历史冲突说明中。 |
| 配置 / CI env 续扫 | 通过，重新抽取 `Settings`、`WorkerSettings`、`.env.example`、`docker-compose.yml`、CI、测试和脚本中的环境变量：39 个 `Settings` 字段在 `.env.example` 缺失 0；`.env.example` 额外 `QAP_DB_USER` / `QAP_DB_PASSWORD` / `QAP_DB_NAME` 均为 compose 辅助；`QAP_WORKER_QUEUE` 为 arq worker 直接读取；`QAP_API_URL` / `QAP_TEST_OOM` 为测试辅助；`QAP_OTEL_ENABLED` 为 T10 计划字段；CI 中 `QAP_JWT_SECRET` 均满足 32 bytes，`QAP_ENCRYPTION_KEY` 均为 64 hex。 |
| 配置 / env 当前复跑 | 通过，当前 `Settings` 仍为 39 个 `QAP_` 字段，`.env.example` 覆盖缺失 0；额外 `QAP_DB_USER` / `QAP_DB_PASSWORD` / `QAP_DB_NAME` 仍只由 `docker-compose.yml` 使用；`WorkerSettings.queue_name` 仍直接读取 `QAP_WORKER_QUEUE` 且默认 `queue:medium`，与 F-EX-08 队列消费缺口说明一致。 |
| Makefile / npm scripts 续扫 | 通过，非审计报告文档中 24 个 `make ...` 引用均能在 Makefile 找到；18 个 `npm run ...` 引用均能对应根目录或 `frontend/package.json` scripts。审计报告里剩余 `make frontend-test` 只在历史冲突章节中作为已修复问题出现。 |
| PRD / catalog / task 索引续扫 | 通过，PRD 30 个 `F-*` 功能 ID 与 feature-catalog 完全一致；`docs/tasks/` 的 8 个任务包均在任务索引中，索引无过期引用。 |
| 任务包结构误报复核 | 通过，任务包使用顶部元信息块记录“来源 / 必要性 / 预计”，再用“背景 / 缺什么 / 实施起点 / 验收标准 / 约束 / 不要做”等章节承载执行内容；简单按固定 `## 来源` 标题扫描会误报，不代表任务包缺少这些信息。 |
| 任务包索引与提交口径复核 | 通过，`docs/tasks/` 当前 8 个 `T*.md` 文件与索引 8 条记录完全一致，无缺失/悬空；索引必要性与任务文件 `**必要性**` 元信息一致；8 个任务包均有来源/必要性/预计元信息、验收标准、约束、不要做和 commit 建议。 |
| FastAPI 路由续扫 | 通过，重新通过 `create_app()` 导出路由清单；非历史文档中 `/api/v1/audit-events` 仍是 T02 待办，`/pipelines/{id}` 仅出现在 `T-FRONTEND-API` 前端债务语境，`/health/live` / `/health/ready` 仅在 T10 “当前源码不是该路径”的负向说明中出现。 |
| catalog ✅ 项续扫 | 通过，复核 `F-PM-02` 凭据 AES-GCM + `credential:{project_id}:{name}` AAD、`F-PM-03` archived 项目触发返回 409、项目成员 CRUD、通知规则 CRUD、SSE ticket、iframe sandbox `allow-scripts` 和 `frontend/nginx.conf` 安全头；其中 `F-PM-02` 在后续更细复核中发现 Git clone 使用链路缺口，已降为 ⚠️。 |
| catalog 结构化日志状态复核 | 发现 `structlog（JSON 格式）` 原标记为全局 ✅ 过强；当前 `qaplatform.logging.configure_logging` 只在 API app 默认 factory 路径调用，worker/arq 入口未调用该配置，engine / worker / plugin 多数模块仍直接使用 stdlib `logging.getLogger`。已把 catalog 该项降为 ⚠️，新增 `结构化日志全局化` backlog，并在 TODO 中登记 `T-LOGGING` 技术债。 |
| catalog 执行隔离 / 取消 / smoke 续扫 | 通过，`engine/docker_backend.py::DockerBackend.create_execution` 会把 `container_config` 传给 `aiodocker.containers.create_or_replace`，其中包含默认 `NetworkMode=none`、`User=1000:1000`、只读 rootfs、`CapDrop`、`no-new-privileges`、`PidsLimit`、`MemorySwap == Memory`、`Init=True` 与 `/tmp` tmpfs；单测覆盖网络/内存 swap/init/SIGTERM，集成测试覆盖 HTTP cancel → 容器退出 < 10s 与重复 cancel 不 5xx。`scripts/smoke/` 当前 9 个 shell 入口中 02-07 为 6 个页面 smoke 脚本，catalog 的“6 个页面脚本”口径准确。 |
| PRD 日志容量口径复核 | 发现 PRD §4 把 `MAXLEN 10000 条 + 单条 4KB` 写成 50MB，和当前 `engine/log_stream.py` 的 `_MAXLEN = 10_000`、`_MAX_LINE_BYTES = 4096` 不严格一致；该约束对应约 40MB 日志 payload，且 Redis Stream 使用 approximate auto-trim，不是精确硬上限。已把 PRD 非功能表改为“约 40MB / 最近约 10000 条”。 |
| F-AU-04 跨租户 404 细化复核 | 发现 catalog 把租户隔离标为 ✅ 过强。当前聚合根查询、Owner/Admin 主要路径、run/artifact/SSE 等路径通过 `get_for_tenant` 或 tenant filter 返回 404；但 `api/deps.py::require_project_permission` 对非 Owner/Admin 的 path `project_id` 路由会先查 `ProjectMember`，无成员关系时直接 403，路由体内的 `get_for_tenant` 还未执行。现有 `tests/integration/test_cross_tenant_isolation.py` 主要用 owner 身份验证 404，部分路由还把 403 分支标成 xfail，因此不能证明“所有跨租户 ID 访问返回 404”。已把 catalog `F-AU-04` 降为 ⚠️，新增 catalog/TODO 项 `F-AU-04 跨租户 404 完整收敛`。 |
| 项目质量仪表盘状态复核 | 发现 catalog 扩展项 `项目质量仪表盘` 原标 ✅ 过强。当前 `api/v1/analytics.py` 的 trends / flaky API、`frontend/src/hooks/use-analytics.ts`、项目详情 analytics tab 和 `AnalyticsPanel` 均存在；但当前 `cd frontend && npm run build 2>&1 | grep "error TS"` 仍显示 `frontend/src/components/projects/analytics-panel.tsx` 有 2 个 TS2322 错误，属于已知 `T-FRONTEND-TS` 债务。已把该扩展项降为 ⚠️，说明“功能入口存在，但生产 build 需先清 TS 债”。 |
| 扩展功能与非功能 ✅ 续扫 | 通过，`api/v1/runs.py` 的 batch cancel / retry 有单元测试覆盖，审计缺口已由 TODO 中的“审计写入覆盖补齐”承接；`api/v1/notifications.py` 提供通知规则 list/create/get/update/delete 且写 audit，前端 paginated response 适配问题已归入 `T-FRONTEND-API`；`api/v1/admin.py` + `frontend/src/pages/admin/status.tsx` 对齐 `/api/v1/admin/status`；Jest / Playwright / Go runner 插件文件均存在并实现 `RunnerProtocol` 风格的 `build_command` / `run_tests`；`engine/log_stream.py` 使用 `_MAXLEN = 10_000` + Redis Stream `maxlen` auto-trim 和 `_MAX_LINE_BYTES = 4096`，已把 catalog 非功能表的日志缓冲措辞从精确“10000 条”改为“近似 10000 条”。 |
| T01 加密服务命名复核 | 发现 T01 / catalog / TODO 仍写旧 `CredentialCipher` 名称；当前源码为 `dependencies.py::CryptoService`，凭据路由经 `container.crypto_service` 调用。已修正文档引用和 T01 中的迁移示例，避免后续按不存在的类实施。 |
| T02 权限口径复核 | 发现 T02 同时参考 `api/v1/admin.py` 和要求租户 Owner/Admin 访问，容易误抄 `admin.py::_require_platform_admin` 的平台管理员校验。T02 已补充说明：`admin.py` 只作路由组织参考，权限应按租户 Owner/Admin 实现；响应也应新增 `AuditEventResponse` schema，而不是直接暴露 SQLAlchemy ORM。 |
| T03/T04 通知渠道安全口径复核 | 发现 T03 写“用 redact”，但当前仓库只有 URL userinfo 脱敏 helper，没有通用 token/key redaction helper；T03/T04 已改为要求不在日志或错误信息中构造完整 URL、签名串或配置，并明确新渠道单独使用 10s 超时，不改既有 `WebhookChannel.TIMEOUT = 30`。 |
| T03/T04 通知 payload 复核 | 发现 T03/T04 只笼统写“或 markdown 类型”，容易把 text payload 结构直接套到 markdown；钉钉 markdown 需要 `markdown.title` + `markdown.text`，企微 markdown 使用 `markdown.content`。T03/T04 已补充 text/markdown 的具体 JSON 形状，并要求用 httpx `params` 传 token/key/sign，避免手工拼完整敏感 URL。 |
| T05 cron 项目解析复核 | 发现 T05 伪代码沿用了 API `get_for_tenant(...)` 口径，但 `worker/settings.py::check_schedules` 是内部 cron tick，没有 `CurrentUser`。T05 已改为说明 worker 可按 `schedule.project_id` 读取 Project 或 eager-load `Pipeline.project`；对外 API 路由仍必须按租户隔离查询并跨租户返回 404。 |
| T01 env_vars 存储形态复核 | 发现 `CryptoService.encrypt(...)` 返回 `bytes`，但现有 `Environment.env_vars` 是 JSONB；若 T01 选择“保留原列加密存储”，不能直接把 raw bytes 写入 JSONB。T01 已补充二选一路径：改二进制列并迁移，或在 JSONB 中存 JSON-safe base64/envelope；同时补充 `worker/tasks.py` 执行侧必须解密 env_vars 后再传 executor。 |
| T01 AAD 创建时序复核 | 发现 T01 要求 AAD 绑定 `environment_id`，但当前 `Environment.id` 由数据库 `server_default` 生成；创建路径若先 encrypt 再 flush 会没有稳定 id。T01 已补充要求应用侧预生成 UUID，或先 flush 出 id 后再 encrypt/update，确保密文 AAD 与最终落库 id 一致。 |
| T01 / 加密口径当前复跑 | 通过，`dependencies.py::CryptoService` 仍返回 bytes 格式密文并支持 0-15 key version；凭据路由仍用 `credential:{project_id}:{name}` AAD 写入 `Credential.encrypted_value`；`api/v1/environments.py` 仍直接读写明文 `Environment.env_vars` JSONB，T01 / TODO / catalog / architecture 均已把 env_vars 加密列为未达验收而不是已完成能力。 |
| T02 router / permission 注册复核 | 发现新增 `src/qaplatform/api/v1/audit_events.py` 不会被自动发现，必须在 `main.py::create_app` 显式 include router；同时当前 `Action` 枚举没有 `AUDIT_READ`，现有普通读权限会放行 Member。T02 已补充：要么新增只授予 Owner/Admin 的 tenant-scoped action，要么在路由内写显式 Owner/Admin guard。 |
| T02 分页口径复核 | 发现 T02 验收写“分页头返回 page/per_page/total”，但当前仓库统一使用 `PaginatedResponse` 响应体字段，不是 HTTP pagination headers。T02 已改为响应体分页口径，避免实现者额外设计 header。 |
| T05 audit metadata 字段复核 | 发现 T05 写“audit metadata 包含 …”，但当前 `AuditEvent` ORM 没有 `metadata` 列，且 T05 明确不新增 alembic 列。T05 已改为把 `schedule_id`、`reason`、`window_end` 写入 `after_state`，并说明 cron worker 不应调用依赖 `CurrentUser` 的 API audit helper。 |
| T05 Project.settings 读取复核 | 发现 T05 伪代码使用 `project.silent_windows`，但 worker 通过仓储拿到的是 ORM `Project`，当前只有 `settings` JSONB，没有 `.silent_windows` 属性。T05 已改为要求 API 将 `silent_windows` 合并进 `Project.settings["silent_windows"]`，worker 从 settings 解析 `list[SilentWindow]` 后再调用判定函数。 |
| T06 webhook 响应模型复核 | 发现 T06 要求 filtered / duplicate 返回 200 + `{status: ...}`，但当前 `webhook_trigger` 声明 `response_model=RunResponse`、正常返回 201；直接 `return {...}, 200` 会与 FastAPI 响应模型/状态码口径冲突。T06 已补充要求用 `JSONResponse(status_code=200, content=...)` 或调整 response model，并说明当前 `WebhookTriggerRequest` 只有 `git_ref/git_sha/metadata`，`git_sha` 缺失时跳过去重但仍保留分支过滤。 |
| T06 allowed_branches schema 复核 | 发现当前 `ProjectCreate/Update.settings` 是自由 dict，若 `allowed_branches` 被写成字符串，webhook 过滤会把它当字符序列参与 `fnmatch`。T06 已补充写入校验：`allowed_branches` 必须是合法 `list[str]`，元素非空并限制数量/长度，非法配置 422。 |
| T07 LIKE helper 复核 | 发现 T07 要求“复用 `_escape_like`”，但当前 `projects.py` 的 `_escape_like` 是 `list_projects()` 内部局部函数，不能从 `runs.py` 直接 import。T07 已改为要求保持同一 LIKE 转义规则，可提取共享 helper 或在 `runs.py` 建同规则私有 helper。 |
| T10 OTel instrumentor API 复核 | 查官方 OpenTelemetry Python 文档后发现：FastAPI app 级装配应使用 `FastAPIInstrumentor.instrument_app(app, ...)`，request hook 不能靠修改 headers copy 证明敏感 header 不落 trace；当前项目使用 async SQLAlchemy engine，SQLAlchemy instrumentation 应传 `container.db_engine.sync_engine`；worker 进程没有 FastAPI app。T10 与 catalog 已补充 app/infra 分离装配、`http_capture_headers_sanitize_fields`、async engine `sync_engine` 和幂等测试要求。 |
| T10 tenant span 属性复核 | 发现 catalog 说 FastAPI span “含 tenant_id”，但当前认证用户在 FastAPI dependency 中解析，不会自动出现在 `server_request_hook` 的 ASGI scope。T10/catalog 已改为：HTTP span 自动能力只声明 path/status 等；若需要 tenant 维度，应在 `src/qaplatform/api/deps.py::get_current_user` 归一化后手动设置当前 span 的低敏属性，且不得写 token/user_id。 |
| 旧口径关键字续扫 | 通过，`PRD §9.6`、`/health/live`、`/health/ready`、`make frontend-test`、`httpx_mock`、`pytest-httpx`、`X-API-Token`、`/admin/audit-events`、`POST /webhooks/{provider}` 等剩余命中均在历史冲突说明、负向说明、防御性过滤或当前不做语境中；任务包执行要求未继续引用这些旧口径。 |
| 固定源码行号续扫 | 通过，当前执行性文档不再依赖易漂移的源码 line number；剩余 `path:line` / `path:line-line` 主要集中在 `docs/fix-roadmap.md` 的历史 review 档案中，且该文件顶部已声明非当前实现状态真相源。 |
| 最终收口复扫 | 通过，继续复扫 `PRD §9.6`、`/admin/audit-events`、`/health/live`、`/health/ready`、`make frontend-test`、`pytest-httpx`、`httpx_mock`、`X-API-Token`、`env_overrides/params`、`summary.errors`、OTel `instrument_app` / `http_capture_headers_sanitize_fields`、T01 `raw bytes` / `environment_id`、T03/T04 完整敏感 URL、T05 audit metadata、T06 `return {...}, 200` 等高风险词；剩余命中均为历史说明、负向约束、防御性过滤或已登记债务，未发现新的执行性文档冲突。 |
| 机械抽取复核 | 通过，非历史文档中 49 个源码路径候选均存在；14 个 `make` 目标与 1 个 `npm run` script 均能在 Makefile / package scripts 中找到；当前 `create_app()` 导出 65 个 HTTP 路由，非历史文档抽取到 76 个显式端点候选，其中 68 个匹配当前路由、4 个为 T02 `/api/v1/audit-events` 计划新增、2 个为 T10 旧 `/health/live` / `/health/ready` 负向说明、1 个为 backlog/负向语境，未发现新的未归类端点。 |
| 章节引用深扫 | 通过，显式章节引用已和对应文档标题编号对照；唯一特殊项仍是刻意保留的旧 `PRD §9.6` 负向/历史说明。非历史文档中裸 `§x` 引用已无无法归属的问题；T05/T10 顶部的“设计见 §4.3”、TODO 的 `PRD §3.2 / §3.4` 和 feature-catalog 的 architecture 章节来源已补成完整目标文档名。 |
| backlog / 任务包必要性复核 | 发现 `feature-catalog.md` 第 4.1 节的 F-LS-04 待办写成 P1，但 `feature-catalog.md` 第 1.7 节与 T07 任务包均为 P0；已把第 4.1 节行修正为 P0。复核结果：首批任务包的必要性与 PRD 功能表一致，catalog 第 4.1 节的 F-* 待办必要性也与 `feature-catalog.md` 第 1 节 PRD 功能表一致。 |
| catalog 状态承接复核 | 通过，`feature-catalog.md` 中 ⚠️/❌/⏳ 状态项均已在 catalog backlog 或 TODO 中承接；其中非 F-ID 别名按当前文档语义映射：`API Token 吊销 + scope` → F-AU-02，`审计日志（who/what/when/from）` → 审计日志查询 API + 审计写入覆盖补齐，`OpenTelemetry 追踪` → OpenTelemetry 装配，`项目质量仪表盘` → T-FRONTEND-TS。 |
| TODO 编号映射复核 | 发现新增 F-AU-04 后 TODO 编号整体漂移，但 `T-EXEC-RETRY` / `T-QUEUE-PRIORITY` / `T-NOTIFICATION-TEMPLATE` / `T-RETENTION-OPS` 和 Maintainer 决策表仍引用旧编号；当时先同步到最新编号。2026-05-27 稳定性复核后，`docs/TODO.md` 已改为稳定标题映射，不再依赖会随排序变化的编号。 |
| F-EX-01 手动触发验收复核 | 发现 PRD §3.3 要求手动触发可指定分支/commit/管道/环境且触发后 < 5s 入队；当前 `RunTrigger` 只接收 `pipeline_id` / `git_ref` / `priority`，`api/v1/runs.py::trigger_run` 创建 Run 时 `environment_id` 取项目默认或首个环境，`git_sha` 不能由请求体指定，且入队时延未纳入自动验收。已把 catalog 的 F-EX-01 降为 ⚠️，并在 TODO 新增 `F-EX-01 手动触发参数与入队验收补齐`。 |
| F-EX-07 重试次数边界复核 | 曾发现 PRD §3.3 要求最大重试次数 1-5，而 `RetryPolicyInput.max_attempts` 和 worker 读取口径不一致；当前已补 `max_attempts` 1-5 边界、兼容 legacy `max_retries`，并用单测/真实 DB 测试锁定。 |
| F-RE-02 摘要生成时延复核 | 通过并补验收归属，`engine/executor.py` 在 collector 产出结果后同步汇总 `total/passed/failed/skipped/error/pass_rate`，随后写入终态 Run；未发现单独的后台摘要任务缺口。但 PRD §3.4 的“执行结束后 < 3s 生成摘要”属于性能验收，已并入 TODO / catalog 的“非功能性能压测”。 |
| F-RE-03 失败详情路由命名复核 | 通过并细化，当前后端路径是 `api/v1/runs.py` 的 `/runs/{run_id}/results`，响应含 `error_message` / `stack_trace`；前端 `components/test-results-table.tsx` 对 failed/error 用例支持点击展开详情。feature-catalog 已从模糊的 “test-results endpoint” 改为真实 `/runs/{run_id}/results`。 |
| F-PM-01 / F-PM-02 Git 凭证执行链路复核 | 发现项目 schema 与 API 可保存 `git_auth_method` / `credential_id`，凭证 CRUD 已加密存储并支持轮换；manual/webhook 创建 Run 时也会把 `credential_id` 放进 metadata。但 `engine/executor.py::_clone_repo` 只读取 `git_url` 并调用 `GitSource.clone(git_url, run.git_ref, dest)`，没有解密 token / SSH key，也没有将凭证安全注入 Git clone。因此私有 HTTPS/SSH 仓库执行链路未达 PRD §3.1 验收。已把 F-PM-01 / F-PM-02 降为 ⚠️，新增 Git 凭证执行闭环 TODO。 |
| Git source / 凭证文档口径复核 | 发现 architecture 内置插件表写“Git clone（HTTPS/SSH）”容易被误读为私有 HTTPS token / SSH key 执行链路已闭环；实际 `GitSource` 只校验/执行 `https://` 或 SSH URL 形态并默认 shallow clone，不解密项目凭证。已把 README 与 architecture 改为“凭据存储已就位，私有仓库凭据注入 clone 待补”。 |
| F-PL-01 collector 配置复核 | 发现 PRD §3.2 要求 Pipeline 可配置测试运行器、结果收集器、超时、重试策略；当前 `PipelineCreate/Update` 与 ORM 只有 `stages`、`selector`、`trigger_config`、`timeout_seconds`、`retry_policy`，`worker/tasks.py::_build_pipeline_config` 也没有 collector 字段，`RunExecutor.execute()` 固定 `self.plugin_registry.get_collector("junit")`。因此“多 Pipeline / runner stage / timeout / retry”已部分实现，但结果收集器配置未达验收。已把 F-PL-01 降为 ⚠️，新增 collector 配置 TODO 与 maintainer 决策项。 |
| 任务包 / 分支状态续扫 | 审计快照通过：`docs/tasks/` 当时为 T01/T02/T03/T04/T05/T06/T07/T10 这 8 个首批任务包；本地 8 个 `feature/T*` 分支与 `origin/feature/T*` SHA 一致，且均未合入本地 `main`。本地 `main=34937a3`，`origin/main=302ede0` 且是本地 `main` 祖先，`origin/HEAD` 指向 `origin/phase1-release-prep`。任务包旧全量 `make lint` / `npm run build` 验收口径仅保留在本文历史冲突说明中，执行性任务 README 已改为改动文件干净口径。 |
| 配置 / 命令 / 前端 API 当前续扫 | 通过，`Settings` 仍有 39 个 `QAP_` 字段且 `.env.example` 缺失 0，额外 `QAP_DB_USER` / `QAP_DB_PASSWORD` / `QAP_DB_NAME` 仍只服务 Compose；Makefile 目标为 `up/down/infra-up/logs/migrate/migrate-create/test/lint/format/seed`，根目录 npm script 仍只有 `test:e2e`，frontend scripts 为 `dev/build/lint/preview`。前端源码当前抽取到 24 个 API 字面量调用；除 `frontend/src/hooks/use-pipelines.ts` 的 3 个 `/pipelines/{id}` 旧路径外，其余路径形状均能映射到当前 `/api/v1` backend 路由或已知 SSE / auth / artifact 入口；该旧路径仍由 `T-FRONTEND-API` 承接。 |
| 最终机器校验复跑 | 通过，`git diff --check` 无输出；`docs/TODO.md` 编号 1-27 连续；`feature-catalog` §4.1 为 22 个必做项、§4.2 为 5 个增强项；PRD 与 catalog 均含 30 个 `F-*` 功能 ID 且无缺失/额外；catalog 非绿色项均能在 TODO 中找到承接；本文 §15 当前有 21 个 `T-*` 后续任务别名且均有 TODO / catalog 落点；Markdown 相对链接检查 20 个链接、缺失 0；旧计数/旧编号残留扫描无命中。 |
| Git refs / 配置命令最终复跑 | 审计快照通过：本地 `main=34937a3`、`origin/main=302ede0` 且 `origin/main` 是本地 `main` 祖先，`origin/HEAD` 指向 `origin/phase1-release-prep`；8 个 `feature/T*` 分支本地 SHA 与对应 `origin/feature/*` 一致且均未合入 `main`。配置命令部分仍按当时源码复核：`Settings` 为 39 个 `QAP_` 字段，`.env.example` 缺失 0，额外 `QAP_DB_USER` / `QAP_DB_PASSWORD` / `QAP_DB_NAME` 只服务 Compose；Makefile 与 npm scripts 与 README / development / frontend README 引用一致。 |
| Runbook 变量命名最终复跑 | 发现 `docs/runbook.md` 轮换章节标题和正文仍使用无前缀 `JWT_SECRET` / `ENCRYPTION_KEY`，而当前 `Settings` 使用 `QAP_` 前缀；已改为 `QAP_JWT_SECRET` / `QAP_ENCRYPTION_KEY`，并同步 `.env.example` 注释。 |
| 前端依赖安装口径复跑 | 发现 README / frontend README 快速启动仍写 `npm install`，但仓库有 `package-lock.json`，CI、E2E 与 development 文档均使用 `npm ci`；已统一快速启动为 `npm ci`，减少本地依赖树与 CI 锁文件漂移。 |
| 依赖与 Alembic 最终复跑 | 通过，`pyproject.toml` 的 `dev` extra 仍包含 pytest / pytest-asyncio / pytest-cov / httpx / testcontainers / ruff，可支撑 README / development 的后端本地命令；根目录与 frontend 均有 `package-lock.json`，执行性文档已统一用 `npm ci`。Alembic 源码迁移链仍为单 head `006`，本地数据库 current 仍为 `005`，因此真实 DB 测试前需先 `alembic upgrade head` 的提醒仍成立。 |
| 非历史真源文档旧 PRD 章节引用复跑 | 发现 `docs/feature-catalog.md` / `docs/TODO.md` 仍直接提到不存在的旧 `PRD §9.6`；已改为当前事实口径：审计日志查询 API 以 catalog/T02 为执行来源，正式 PRD 章节仍待补。历史细节继续保留在本文冲突记录中。 |
| 文档真源稳定性复跑 | 2026-05-27 review 发现本文的 git SHA / ahead 计数、`docs/feature-catalog.md` 的同步源说明、`docs/fix-roadmap.md` 的当前真源列表和 `docs/TODO.md` 的 `TODO #n` 映射存在易漂移风险；已改为审计快照、证据档案与稳定标题映射。 |

结论：本轮“十多轮”审计结果已经落到本文和相关真相源文档中；剩余事项不是文档漏写，而是需要后续产品/实现任务继续处理的 backlog。

## 1. 分支与合并状态冲突

### 1.1 feature 分支未合入 main

本轮审计确认：当前 `main` 只包含 `main` 自身，任务分支均处于 `git branch --no-merged main` 列表。8 个 `feature/T*` 分支的本地 SHA 与远端 SHA 一致：

| 分支 | SHA |
|---|---|
| `feature/T01-env-vars-encryption` | `90f4f1f` |
| `feature/T02-audit-query-api` | `bf61e9b` |
| `feature/T03-dingtalk-notify` | `cf01689` |
| `feature/T04-wecom-notify` | `f2d101c` |
| `feature/T05-silent-windows` | `bb1dbae` |
| `feature/T06-webhook-branch-dedup` | `855b040` |
| `feature/T07-test-results-filter` | `62333b7` |
| `feature/T10-opentelemetry` | `41e8b91` |

修复进度：`feature-catalog` / `TODO` / 本报告已改为区分 `main` 当前状态、feature 分支已推送状态与待实现项；任务分支合并本身不在本轮文档修复范围内。

影响：

- 用户曾确认 T07、T03、T04、T02、T06、T05 等分支已推送/验收，但这不等于 `main` 已包含这些实现。
- `docs/feature-catalog.md` 的状态如果标为“完成并合并”，应只表示 `main` 已包含；否则应标成“feature 分支已推送/待合并”。
- 后续继续任务前，如果直接从 `main` 切分支，会看不到已推送 feature 分支中的实现。

建议：

- 后续任务输出汇总继续单独列“已推送分支”和“已合入 main”。
- 后续自动化脚本应显式使用 `main` / `origin/main`，不要依赖当前 `origin/HEAD`。

### 1.2 本地 main 与远端 main 的审计快照

本节记录的是 2026-05-26 审计时的 git refs 快照，不是实时状态源。实时状态请现场执行：

```bash
git status --short --branch
git rev-parse --short HEAD
git rev-list --count origin/main..main
git rev-list --count main..origin/main
git symbolic-ref --short refs/remotes/origin/HEAD || true
```

当时复核确认：本地 `main` 没有 upstream 配置；`git ls-remote --heads origin main` 返回 `302ede0`，本地 `main` 是 `34937a3`。`origin/main` 是本地 `main` 的祖先，本地多出的 5 个提交均为 docs commit：

```text
34937a3 docs(roadmap): 修正 §4.3 E2E 实际状态
b4837fa docs(TODO): 精简对齐 catalog §4 待办
788c1e8 docs: 起 codex-ready 任务包（8 项 + 索引）
0f21d30 docs: 新增 feature-catalog 一页功能全貌
e3fe38d docs(prd): 与代码现状对齐三处偏移
```

影响：

- 不应根据本文内的 SHA 或 ahead/behind 数直接判断当前是否可 push / pull / reset；必须先用上方 git 命令复核。
- 后续若需要让远端 main 包含本地 docs commit，应由 maintainer 明确决定推送或通过 PR 合入。

## 2. PRD / catalog / TODO / tasks 之间的冲突

### 2.1 `PRD §9.6` 不存在

冲突：

- 旧文档中的 `docs/TODO.md`、`docs/feature-catalog.md`、`docs/tasks/T02_audit_query_api.md` 都引用 `PRD §9.6` 作为审计日志查询 API 来源。
- `docs/prd.md` 实际只到第 8 章，没有第 9 章，也没有 `§9.6`。

影响：

- 旧 T02 PR 描述要求引用不存在的 `PRD §9.6`，该引用无法成立。
- 后续 reviewer 会无法追溯审计查询 API 的产品验收出处。

建议：

- 方案 A：在 `docs/prd.md` 补充审计日志章节，并明确编号。
- 方案 B：把所有旧 `PRD §9.6` 引用改成真实来源，例如 `docs/architecture.md` 的审计设计章节，或 `feature-catalog.md §4.1`。

修复进度：`TODO`、`feature-catalog`、T02 任务包已改为引用 `catalog §4.1` / `feature-catalog.md`，不再把不存在的 `PRD §9.6` 作为执行依据。是否在 PRD 正式补审计查询章节仍需 maintainer 决策。

### 2.2 PRD Phase 3/4 与 catalog “当前范围不做”冲突

修复进度：已在第一轮清理中把 PRD 改为“当前验收 / 远期增强”分层，并把 Slack 改为通用 Webhook 覆盖而非一等渠道。

冲突：

- `docs/prd.md` Phase 3/4 仍列出跨分支/跨环境对比、日志搜索、CSV 数据导出、Kubernetes Job、多 Worker、插件市场等内容。
- `docs/TODO.md` 与 `docs/feature-catalog.md` 曾把跨分支/跨环境对比、日志全文搜索、CSV 导出、Slack 通知、Phase 4 项列为“明确不做”或当前不做。

影响：

- 任务包执行者会不知道 PRD 和 catalog 谁优先。
- PRD 中的“未来目标”容易被误读为当前验收缺口。

建议：

- 在 PRD 中标明“远期愿景，不属于当前验收”。
- 或在 catalog 的“不做”中改写为“当前阶段不做，PRD 远期保留”。

### 2.3 TODO 顶部“PRD 与代码已对齐”不再成立

冲突：

- 旧 `docs/TODO.md` 顶部写“PRD 与代码已对齐”。
- 当前审计已确认多个不一致：`PRD §9.6` 不存在、健康检查路径不一致、Phase 项与 catalog 冲突、任务验收口径不一致。
- 本轮继续发现 F-LS-01/02/03、F-RE-05 等新增待办尚无任务包，因此 TODO / catalog 也不能继续暗示“每项待办都有任务包”。

建议：

- 把这句话改成“PRD 与代码存在已知偏移，详见 `doc-conflict-audit.md`”。

修复进度：`docs/TODO.md` 顶部已改成“仍有已知偏移，详见 `doc-conflict-audit.md`”；`docs/TODO.md` 与 `docs/feature-catalog.md` 的任务包说明也改为“首批可交付任务包见 tasks，本轮审计新增待办需要后续补任务包”。

### 2.4 任务 README 验收口径过期

冲突：

- `docs/tasks/README.md` 仍要求每个任务 `make lint` 干净、`make test` 通过、前端任务 `npm run build` 通过。
- maintainer 后续已清理后端 ruff 历史债务；后端验收现在是 `ruff check src tests` 全量干净。
- maintainer 已把前端验收修订为“改动文件 TS 干净 + 不引入新 TS 错误”。
- 当前 `main` 仍存在历史 TS 债务，完整前端 build 不能作为每个功能任务的无条件阻塞项。

建议：

- 更新 `docs/tasks/README.md` 的通用验收基线。
- 在每个任务包中避免继续写死 `make lint` 或完整 `npm run build` 作为唯一通过标准。

修复进度：`docs/tasks/README.md` 已改为后端 `ruff check src tests` 全量干净、前端改动文件 TS 干净且不引入新错误的修订验收口径；后端 `T-LINT` 已处理，前端 TS 债务仍单独处理。

### 2.5 `make frontend-test` 目标不存在

冲突：

- `docs/tasks/README.md` 提到涉及前端更新时运行 `make frontend-test`。
- `Makefile` 中没有 `frontend-test` 目标。

建议：

- 删除该命令，或新增 Makefile 目标。
- 若保留当前修订口径，应写成“运行改动文件 TS 检查；若仓库新增前端单测目标，则运行对应单测”。

修复进度：任务 README 已删除 `make frontend-test` 要求，改用前端修订验收口径。

## 3. API 路径与前端契约冲突

### 3.1 SSE 日志路径有多套说法

冲突：

- `README.md` 写 `GET /api/v1/sse/runs/{id}/logs`。
- `docs/architecture.md` 写 `GET /stream/{id}/logs`。
- `frontend/FRONTEND_PROMPT.md` 写 `GET /runs/{id}/logs/stream`。
- 源码实际路由为 `/api/v1/runs/{run_id}/logs`，并使用一次性 SSE ticket。

建议：

- 统一成源码当前路由：`POST /api/v1/auth/sse-ticket` 获取 ticket，然后 `GET /api/v1/runs/{run_id}/logs?ticket=...`。
- 同步更新 README、architecture、frontend prompt。

修复进度：README、architecture、frontend README 已统一到 SSE ticket 路径；`frontend/FRONTEND_PROMPT.md` 已标为历史提示词，不再作为当前 API 契约，且已把其中的 SSE 示例改为 `POST /auth/sse-ticket` + `GET /runs/{id}/logs?ticket=...` / `events?ticket=...`，降低误用风险。

### 3.2 审计查询 API 路径冲突

冲突：

- `docs/TODO.md` 和 `docs/feature-catalog.md` 提到缺 `/admin/audit-events`。
- `docs/tasks/T02_audit_query_api.md` 设计为 `GET /api/v1/audit-events`。
- 当前 `main` 尚无审计查询路由。

建议：

- 在 task/catalog/TODO 中统一一个路径。
- 如果采用 T02 实现路径，应把 `/admin/audit-events` 全部改成 `/api/v1/audit-events`。

修复进度：T02 任务包、TODO、feature-catalog 已统一为 `GET /api/v1/audit-events`。

补充修复：T02 任务包的过滤参数也已对齐当前 ORM / 写入端字段，从旧示例 `target_type` / `target_id` 改为 `resource_type` / `resource_id`，避免查询 API 新增一套与表字段不一致的命名。

### 3.3 环境变量 API 路径冲突

冲突：

- `docs/tasks/T01_env_vars_encryption.md` 验收写 `GET /api/v1/environments/{id}`。
- 当前源码环境变量路由是嵌套项目路径：`/api/v1/projects/{project_id}/environments/{env_id}`。

建议：

- 修正 T01 任务包路径，避免后续实现者新增不一致的 flat route。

修复进度：T01 任务包已改为项目嵌套路由 `GET /api/v1/projects/{project_id}/environments/{env_id}`。

### 3.4 健康检查路径冲突

冲突：

- `docs/feature-catalog.md` 和 `docs/architecture.md` 写 `/health/live`、`/health/ready`。
- 当前源码实际是 `/health`、`/ready`，另有 `/metrics`。
- `docs/tasks/T10_opentelemetry.md` 也把 `/health/live`、`/health/ready` 写入 span 排除验收。

建议：

- 统一为当前源码路径，或明确计划引入 `/health/live`、`/health/ready` 兼容路由。
- T10 的 excluded_urls 验收必须跟实际路径一致。

修复进度：architecture、feature-catalog、T10 任务包已统一为当前源码路径 `/health`、`/ready` 和 `/metrics`；T10 示例中的 `excluded_urls` 已补齐 `ready`，避免示例与验收清单不一致。

### 3.5 Auth 前端提示词过期

冲突：

- `frontend/FRONTEND_PROMPT.md` 写 `POST /login`、`POST /refresh`，以及 email/password 登录。
- 当前源码 auth router 是 `/api/v1/auth/login`、`/api/v1/auth/refresh`。
- 当前登录使用 username/password/可选 tenant_id，不是 email/password。
- 当前 refresh token 通过 HttpOnly cookie，不是返回 JSON 后存 localStorage。
- `docs/prd.md` 原 F-AU-01 也写“邮箱注册/登录”，容易被误读为 email login；当前注册收集 email，但登录凭据是 username/password。

建议：

- 把 `frontend/FRONTEND_PROMPT.md` 标为历史提示词，或更新成当前 API 契约。
- 禁止再把 refresh token localStorage 作为实现建议。

修复进度：`frontend/FRONTEND_PROMPT.md` 已标为历史提示词，且其中 auth 示例、Login Page 和 Authentication Flow 已改为 username/password、`/auth/login`、`/auth/refresh`、`/auth/tokens` 与 HttpOnly refresh cookie 口径；`frontend/README.md` 已记录当前 `/api/v1/auth/*` 与 HttpOnly refresh cookie 契约；PRD 和 feature-catalog 已改为“用户名注册/登录，注册时收集 email”。

### 3.6 Artifact 下载行为冲突

冲突：

- `frontend/FRONTEND_PROMPT.md` 写 artifact download 是 presigned URL redirect。
- 当前源码 `GET /api/v1/artifacts/{artifact_id}/download` 返回 JSON：`{"download_url": ..., "expires_in": ...}`。

建议：

- 前端契约统一为 JSON 响应。

修复进度：`frontend/README.md` 已记录 artifact download 返回 JSON `download_url` / `expires_in`；`frontend/FRONTEND_PROMPT.md` 中的历史示例也已改为 JSON 返回而非 redirect。

### 3.7 Pipeline / Run Trigger 数据模型冲突

冲突：

- `docs/architecture.md` 仍描述 `runner_type`、`runner_config`、`collector_type`、`collector_config`。
- 当前 `api/schemas.py` 使用 `stages`、`selector`、`trigger_config`、`retry_policy`。
- `frontend/FRONTEND_PROMPT.md` 的 Run trigger 写 `{ pipeline_id, branch?, env_overrides?, params? }`。
- 当前 `RunTrigger` 只包含 `pipeline_id`、`git_ref`、`priority`。

建议：

- 以 `api/schemas.py` 当前 schema 为准更新 architecture 和 frontend prompt。

修复进度：architecture 已改为当前 Pipeline schema；frontend prompt 已标为历史提示词，不再作为当前 schema 来源，且其中 `POST /runs` 示例已补充对齐为当前 `RunTrigger` 的 `{ pipeline_id, git_ref?, priority? }`，Run response 示例也已去掉 `env_overrides` / `params` 等旧字段并对齐当前 `RunResponse` 的 `git_ref`、`duration_ms`、`summary`。

### 3.8 前端页面路由清单过期

冲突：

- `frontend/FRONTEND_PROMPT.md` 原列出 `/projects/:id/pipelines/:pid` pipeline detail 页面。
- 当前 `frontend/src/App.tsx` 实际路由没有 pipeline detail 页面；有 `/runs` 列表和 `/admin/status` 页面。

修复进度：`FRONTEND_PROMPT.md` 的页面路由清单已改为当前 App 路由：`/login`、`/`、`/projects`、`/projects/:id`、`/runs`、`/runs/:id`、`/settings`、`/admin/status`。

### 3.9 `frontend/src/types/api.ts` 不应作为原始后端契约源

现状：

- 后端 `RunResponse` 字段为 `git_ref`、`duration_ms`、`summary`、`triggered_by: UUID | None` 等。
- `frontend/src/types/api.ts` 的 `Run` 仍包含 `branch`、`duration_seconds`、`total_tests`、`passed_tests`、`failed_tests`、`env_overrides`、`params` 等 UI 视图字段，且缺后端 `tenant_id`、`environment_id`、`attempt`、`git_ref`、`duration_ms`、`summary` 等原始字段。
- `frontend/src/types/api.ts` 的 `Environment` 仍使用旧 `variables` 字段，并缺后端 `base_image`、`setup_script`、`memory_mb`、`cpu_cores`、`max_artifact_size_mb`、`max_artifacts_count`、`network_policy`、`env_vars`、`cache_key` 等字段。
- `frontend/src/components/projects/environment-editor.tsx` 创建环境时提交 `{ name, variables: {} }`，更新时提交 `{ ...env, variables }`，同样沿用旧 Environment payload，且没有填写后端 `EnvironmentCreate` 必需的 `base_image`。
- `frontend/src/types/api.ts` 的 `Pipeline` 顶层字段名与后端响应接近，但嵌套 `selector` / `trigger_config` / `retry_policy` shape 仍是旧前端形状；历史 `FRONTEND_PROMPT.md` 已改为当前后端 shape，并补齐 stage 的 `plugin/config/continue_on_error/phase` 字段，不应再从运行类型反推 API 契约。
- `frontend/src/components/projects/pipeline-modal.tsx` 的表单和 payload 同样沿用旧 `framework/pattern/on_push/max_retries/backoff` 口径，不能直接满足当前 `PipelineCreate/Update` schema。
- `frontend/src/hooks/use-projects.ts` 列表查询传 `search`，但后端 `api/v1/projects.py::list_projects` 查询参数是 `q`。
- `frontend/src/hooks/use-runs.ts::useTriggerRun` 仍提交 `env_overrides` / `params`，但后端 `RunTrigger` 只接收 `pipeline_id`、`git_ref`、`priority`，这些旧字段不会形成真实执行参数覆盖。
- `frontend/src/hooks/use-runs.ts::normalizeRun` 仍用 `summary.errors` 判断 `done` 是否应映射成 failed，但后端 executor / runner summary 使用单数 `error`。
- `frontend/src/hooks/use-pipelines.ts` 的详情/更新/删除仍调用 `/pipelines/{id}`，但后端当前只有 `/api/v1/projects/{project_id}/pipelines/{pipeline_id}` 嵌套路由。
- `frontend/src/hooks/use-notifications.ts` 把 `GET /projects/{project_id}/notification-rules` 声明为 `NotificationRule[]`，但后端当前返回 `PaginatedResponse[NotificationRuleResponse]`。
- `frontend/src/hooks/use-sse.ts` 的 fallback 会把传入 URL 交给 `api.get<T>(url)`；当前 `LogViewer` 传的是 `/api/v1/runs/{run_id}/logs`，这是 ticket SSE 流，不是 JSON API。
- 后端 Run 状态枚举为 `queued/preparing/running/collecting/done/failed/cancelled/timeout`；当前前端 UI 视图会把 `done` 结合 summary 映射成 `passed` 或 `failed`，把 `timeout` 映射成 `timed_out`。
- 后端 TestResult 状态枚举为 `passed/failed/error/skipped/xfail`；当前 `frontend/src/types/api.ts` 的 TestResult 状态未列 `xfail`，历史前端 prompt 中的示例类型已补入 `xfail`，避免继续传播旧四态口径。
- `frontend/src/hooks/use-runs.ts::normalizeRun` 会把后端 `git_ref` / `duration_ms` / `summary` 归一化成这些 UI 字段，所以当前页面能继续使用，但类型文件命名容易让维护者误以为它等同后端 API DTO。

影响：

- 后续从 `frontend/src/types/api.ts` 反推 API 契约，会重新引入历史 prompt 中的旧字段。
- 若新增前端功能直接使用 `Run` 作为 axios 响应类型，TypeScript 可能掩盖真实后端响应字段缺失。

修复进度：`frontend/README.md` 已明确后端 schemas / OpenAPI 是契约源，并提示 `types/api.ts` 目前混合 DTO 与 view model、部分 hook 路径/响应形状也需对齐；同时补充 Run status 的后端枚举与前端 UI 映射关系、Run / Environment / Pipeline 嵌套类型偏移、run trigger payload 偏移、run summary `error/errors` 偏移、environment editor payload 偏移、pipeline modal payload 偏移、project search 参数偏移、pipeline hook 路径偏移、notification hook pagination 偏移、SSE fallback 偏移、TestResult `xfail` 类型缺口；`FRONTEND_PROMPT.md` 的历史示例类型已补入 `xfail`，并把 polling fallback 降级为需另建 JSON 端点或重连策略；`docs/TODO.md` 已新增 `T-FRONTEND-API`，建议后续拆分 `Backend*` DTO / `*ViewModel` 或引入生成式 DTO，并修正 hook 路径/响应形状。

### 3.10 Run summary 字段名单细节

现状：

- `engine/executor.py` 写入 `summary` 的字段为 `total`、`passed`、`failed`、`skipped`、`error`、`pass_rate`。
- `domain/models/run.py::RunSummary` 与内置 runner 示例也使用 `error` 单数字段。
- `feature-catalog.md` 原把 F-RE-02 写成 `passed/failed/skipped/errors`，容易让后续前端或通知模板误用 `errors`。

修复进度：feature-catalog 已改为 `passed` / `failed` / `skipped` / `error` / `pass_rate`；前端 `use-runs.ts::normalizeRun` 的旧 `summary.errors` 读取已登记到 `T-FRONTEND-API`，本轮不改运行代码。

## 4. 任务包与代码现状冲突

### 4.1 T05 静默窗口指向错文件

冲突：

- `docs/tasks/T05_silent_windows.md` 和 `docs/feature-catalog.md` 说 cron tick 创建 Run 前判断应修改 `src/qaplatform/worker/scheduler.py`。
- 当前 cron tick 实际在 `src/qaplatform/worker/settings.py::check_schedules`。
- `worker/scheduler.py` 是 enqueue-side fair scheduler，不是 cron tick。

建议：

- T05 任务包应把主要后端修改点改为 `worker/settings.py`。
- 可保留 `worker/scheduler.py` 仅作为入队行为参考。

修复进度：已把 T05 任务包和 catalog 的 cron tick 入口改为 `worker/settings.py::check_schedules`，并说明 `worker/scheduler.py` 仅作为入队行为参考；判定函数位置也已收敛到既有 `domain/services/scheduling.py`，不再建议新增 `schedule.py` / `schedule_service.py`。

### 4.2 T05 与既有 `quiet_windows` 概念冲突

冲突：

- 代码已有 schedule 级别 `quiet_windows`：
  - `infra/database/models.py` 的 `Schedule.quiet_windows`
  - `api/schemas.py` 的 `ScheduleCreate/Update/Response.quiet_windows`
  - `domain/services/scheduling.py::should_fire`
- T05 设计要求新增 project 级 `Project.settings.silent_windows`，且是绝对时间窗口，命中时要写 audit，不更新 `last_run_at`。
- 既有 `quiet_windows` 当前只是 schedule 级跳过逻辑，没有 T05 要求的 audit 行为。

建议：

- T05 文档必须明确 `quiet_windows` 与 `silent_windows` 的关系：
  - 是保留两个机制？
  - 还是废弃/迁移 `quiet_windows`？
  - 两者同时存在时优先级是什么？

修复进度：已在 T05 任务包和 catalog 中补充说明：`quiet_windows` 为既有 schedule 级逻辑，`silent_windows` 为新增 project 级绝对时间窗口，worker 从 ORM `Project.settings["silent_windows"]` 解析窗口列表后判定；命中时必须写 audit 且不更新 `schedule.last_run_at`；`is_in_silent_window` 使用 tz-aware datetime、UTC 归一化和闭区间边界；当前 `AuditEvent` 无 `metadata` 列，静默窗口跳过详情统一写入 `after_state`（`schedule_id`、`reason`、`window_end`）。是否长期共存仍需 maintainer 决策。

### 4.3 T10 OpenTelemetry 缺 exporter 依赖

冲突：

- T10 伪代码使用 `OTLPSpanExporter`。
- `pyproject.toml` 仅声明 `opentelemetry-api`、`opentelemetry-sdk`、FastAPI/SQLAlchemy/Redis instrumentation。
- 未声明 `opentelemetry-exporter-otlp-proto-http` 或等价 HTTP exporter 包。
- T10 又要求“不引入超出 pyproject 已声明的 OTel 包；如缺包必须在 PR 里说明”。

建议：

- T10 任务包应提前把 exporter 依赖缺口列为硬冲突。
- 若允许新增依赖，需在任务包中明确允许；否则无法按伪代码完成。

### 4.4 T10 配置字段与现有配置重叠

冲突：

- T10 说在 `config.py` 加 4 个 OTel 字段。
- 当前 `config.py` 已有 `otel_exporter_endpoint: str | None = None`。

建议：

- T10 应写成“扩展已有 OTel 配置”，避免重复添加字段或改变现有语义。

### 4.5 T03 测试依赖口径过期

冲突：

- `docs/tasks/T03_dingtalk_notify.md` 写使用 `httpx_mock`。
- 当前依赖中没有 `pytest-httpx`。
- maintainer 后续已明确沿用 patch `httpx.AsyncClient` 的测试风格。

建议：

- T03/T04 任务包应删除 `httpx_mock` 指令，避免实现者引入新依赖。

修复进度：T03/T04 任务包已明确不要引入 `pytest-httpx` / `httpx_mock`，沿用 patch `httpx.AsyncClient` 的本地测试风格。

### 4.6 T02 权限验收表述需要细化

冲突：

- T02 要求 Member/Viewer 返回 403，同时也有硬约束“跨租户返回 404 非 403”。
- 对审计查询列表端点而言，过滤跨租户数据通常表现为“只返回当前租户数据”，不是对某个跨租户 id 返回 404。

建议：

- T02 应区分：
  - 端点权限不足：403。
  - 指定某个跨租户资源 id 查询：404 或空结果。
  - 普通列表：不得泄露其他 tenant 的事件。

修复进度：T02 任务包已明确区分列表端点“不泄露其他 tenant 数据”和资源 ID 跨租户访问 404；端点角色权限不足仍为 403。

### 4.7 T07 状态需区分“分支通过”与“main 已有”

冲突：

- 用户已确认 T07 验收通过并推送分支。
- 当前 `main` 尚未合入 T07。
- `feature-catalog.md` 中 F-LS-04 若按 `main` 仍是“仅 status”，按分支则已实现。

建议：

- catalog 状态要加分支维度，避免 reviewer 误解。

修复进度：feature-catalog 已把 F-LS-04 写成当前 `main` 仅 status，`feature/T07-test-results-filter` 已推送但未合入。

## 5. Lint / Test / CI 文档冲突

### 5.1 全量 ruff 与全量 TS build 不应作为功能任务阻塞项

冲突：

- 任务 README 仍要求 full lint/build。
- maintainer 已确认：
  - `main` 存在历史 ruff 债务。
  - 前端 build 存在 3 个历史 TS 错误文件：`analytics-panel.tsx`、`notification-rules-panel.tsx`、`trigger-run-modal.tsx`。
  - 功能任务验收应限定为改动文件干净且不引入新错误。

建议：

- 在 `docs/tasks/README.md` 写入修订口径。
- 单独新增 T-LINT 与 T-FRONTEND-TS 任务处理历史债务。

修复进度：任务 README 已写入后端 ruff / 前端 TS 的修订验收口径；CI frontend type/build gate 已改为债务感知，只允许 3 个已知 TS 债务文件失败；`frontend/src/components/projects/environment-editor.tsx` 的新增 lint error 已修复，`npm run lint` 当前为 0 error / 4 warning；后端 `T-LINT` 已处理并在 CI `backend-test` 加入 `ruff check src tests`，`T-FRONTEND-TS` 仍保留为独立任务。

### 5.2 `ruff` 未在 pyproject dev/test 依赖中声明

修复进度：已把 `ruff` 加入 `pyproject.toml` 的 `dev` extra，使 `pip install -e ".[dev]"` 后可运行 `make lint`。

冲突：

- Makefile 使用 `ruff check src tests` 和 `ruff format src tests`。
- `pyproject.toml` 的 `dev` / `test` extras 未声明 `ruff`。

建议：

- 若项目要求开发者运行 `make lint`，应把 `ruff` 加入 dev extra，或在开发文档中说明安装方式。

### 5.3 E2E workflow_dispatch 条件不可触发

修复进度：已在 `.github/workflows/ci.yml` 增加 `workflow_dispatch`；push / pull_request 自动运行稳定的 `tests/e2e/auth-flow.spec.ts`，workflow_dispatch 手动运行全量 E2E。TODO/catalog 中剩余待办已改名为 `E2E CI 覆盖扩展`，避免把已完成的稳定冒烟自动触发误读为未完成。

原始冲突：

- `.github/workflows/ci.yml` 顶部只有 push / pull_request。
- E2E job 条件是 `if: github.event_name == 'workflow_dispatch'`。
- 由于 workflow 未声明 `workflow_dispatch`，该 job 无法通过手动触发运行。

完成结果：

- `workflow_dispatch` 已加入 CI。
- push / pull_request 自动运行 `tests/e2e/auth-flow.spec.ts`。
- 手动触发运行全量 E2E。

### 5.4 E2E 密码硬编码仍有残留

修复进度：`tests/e2e/real-login-flow.spec.ts` 和 `tests/e2e/real-run-trigger.spec.ts` 已改为读取 `E2E_ADMIN_PASSWORD`，CI 也显式设置该变量。`global-setup.ts` 和部分 integration test 仍保留 `admin123` fallback / fixture，是否继续清理应单独处理。

原始冲突：

- `docs/fix-roadmap.md` 说 global setup 改用 `E2E_ADMIN_PASSWORD`。
- 当前 `tests/e2e/global-setup.ts` 有 fallback `admin123`。
- `tests/e2e/real-login-flow.spec.ts` 和 `tests/e2e/real-run-trigger.spec.ts` 曾直接填写 `admin123`。
- `tests/integration/test_worker_execute.py` 也出现 `admin123`。

建议：

- 文档应写成“部分改用 env，仍有硬编码残留”，不要写成完全修复。

修复进度：本报告按“部分改用 env，global setup / integration fixture 仍保留 fallback”记录；未顺手清理 fixture。

### 5.5 集成测试运行方式表述不统一

冲突：

- 部分 integration tests 默认需要 `RUN_INTEGRATION_TESTS=1`。
- `tests/integration/test_auth_audit_failure_paths.py` 未被 `RUN_INTEGRATION_TESTS` gate 掉，会通过 testcontainers 自启 PG/Redis；因此“pytest 默认跳过集成测试”不是严格事实。
- 开发文档同时给人“testcontainers 自动可跑”和“需要手动基础设施/API/worker”的混合印象。

建议：

- 把集成测试分层：
  - 纯 testcontainers。
  - 需要外部 Docker 服务。
  - 需要完整 API/worker/e2e 栈。

修复进度：development 文档已明确单元测试应跑 `pytest tests/unit -q`，`make test` 会执行 pytest 默认集合且可能触发未 gate 的 testcontainers 集成用例；完整集成测试需 `RUN_INTEGRATION_TESTS=1`、Docker daemon、基础设施/API/Worker。README 的集成测试命令也已加上 `RUN_INTEGRATION_TESTS=1`。

### 5.6 E2E 本地运行前置条件曾未完整写明

修复进度：README 与 development 文档已补充 E2E 的本地前置条件：从仓库根目录运行、安装根目录 Playwright 依赖、安装 `frontend/` 依赖，并按快速启动创建 `.venv`。这是因为 `playwright.config.ts` 会启动 `frontend` dev server，同时用 `.venv/bin/python -m uvicorn qaplatform.main:create_app --factory --app-dir src` 启动后端；`tests/e2e/global-setup.ts` 还会用 `.venv/bin/python` 执行 alembic upgrade 和 seed。

原始缺口：

- 文档只强调 E2E 不要在 `frontend/` 目录运行，但没有明确根目录 `npm ci` 也是必需的。
- 文档没有把 `.venv` 与 Playwright 后端启动 / global setup 绑定说明，开发者可能在已激活其他虚拟环境时仍失败，因为配置写死 `.venv/bin/python`。

完成结果：

- `README.md` 的测试段落补充根目录 npm 依赖、`frontend/` 依赖与 `.venv` 前置条件。
- `docs/development.md` 的 E2E 段落补充首次运行命令 `npm ci` 和 `npm ci --prefix frontend`。

## 6. 本地启动、环境变量与运维文档冲突

### 6.1 `make up` 说明冲突

冲突：

- `README.md` 和 `docs/development.md` 有地方说 `make up` 只启动 PostgreSQL、Redis、MinIO。
- `Makefile` 实际执行 `docker compose up -d`，会启动 compose 中全部服务。
- `README.md` 另有地方又说 `make up` 启动全部 6 个服务。

建议：

- 统一写法：
  - `make up`：启动完整 compose 栈。
  - 如只需基础设施，使用 `docker compose up -d postgres redis minio` 或新增 `make infra-up`。

修复进度：Makefile 已新增 `infra-up`；README / development 已区分 `make infra-up` 和 `make up`。

### 6.2 seed 命令指向不存在模块

冲突：

- `README.md` 和 `Makefile` 使用 `python -m qaplatform.seed`。
- 当前源码中未发现 `qaplatform.seed` 模块；实际更接近 `scripts/seed_admin.py`。

建议：

- 修正 Makefile 和 README seed 命令。

修复进度：Makefile 的 `seed` 已改为 `python scripts/seed_admin.py`；README / development 快速启动改为直接使用 `.venv/bin/python scripts/seed_admin.py`，避免未激活虚拟环境时裸 `python` 不存在。常用 Makefile 命令保留为“激活虚拟环境或 PATH 包含 `.venv/bin` 后使用”。

### 6.3 CI / 测试默认 JWT secret 仍有短值

冲突：

- `config.py` 要求 `jwt_secret` 至少 32 bytes。
- CI `backend-test` job、integration alembic 环境和 E2E fallback 中仍有少于 32 bytes 的测试 secret。

修复进度：`.github/workflows/ci.yml`、`tests/integration/conftest.py`、`tests/e2e/backend_app.py` 与 `tests/unit/test_auth_middleware.py` 的测试 secret 已统一改为 32+ bytes，避免配置校验失败。

### 6.4 `.env.example` 复制后不能直接通过配置校验

冲突：

- `.env.example` 写 `QAP_JWT_SECRET=REQUIRED`，但 `config.py` 要求 JWT secret 至少 32 bytes。
- `.env.example` 写 `QAP_ENCRYPTION_KEY=REQUIRED`，但 `config.py` 要求 64 hex chars。
- `.env.example` 注释提示生成命令，但默认值本身会导致服务启动失败。

建议：

- 改成可运行的 dev-only 示例值，或明确写“复制后必须替换，否则服务不能启动”。
- 对 Docker compose 快速启动，建议提供 `.env.dev.example`。

修复进度：`.env.example` 已改为可通过 `Settings` 校验的 dev 示例值；JWT secret、encryption key、MinIO/S3 默认值、presigned URL TTL、HSTS 与 CORS 示例已对齐当前 `Settings`；并保留 `QAP_ENCRYPTION_KEYS` 的注释示例用于后续多 key 轮换场景。

### 6.5 rate limit 环境变量名错误

冲突：

- `.env.example` 使用 `QAP_RATE_LIMIT_REQUESTS`。
- `config.py` 实际字段是 `rate_limit_per_minute`，对应 env var 是 `QAP_RATE_LIMIT_PER_MINUTE`。

建议：

- 修正 `.env.example`。

修复进度：`.env.example` 已改为 `QAP_RATE_LIMIT_PER_MINUTE`。

## 7. Architecture 与 Runbook 冲突

### 7.1 Architecture 仍写 Vue 3

冲突：

- `docs/architecture.md` 架构图写 Frontend SPA 为 Vue 3。
- README 和实际前端均为 React。

建议：

- 改为 React SPA。

修复进度：architecture 已改为 React 前端；README / frontend README 与实际前端栈一致。

### 7.2 Architecture 健康检查路径过期

冲突：

- Architecture 写 `/health/live`、`/health/ready`。
- 源码实际是 `/health`、`/ready`。

建议：

- 同 3.4，统一路径。

修复进度：architecture 已改为 `/health`、`/ready`、`/metrics`。

### 7.3 Architecture 的 Pipeline 字段过期

冲突：

- Architecture 仍写 `runner_type`、`runner_config`、`collector_type`、`collector_config`。
- 当前 schema 使用 staged pipeline 结构。

建议：

- 以 `api/schemas.py` 当前字段更新 architecture。

修复进度：architecture 已改为 `stages`、`selector`、`trigger_config`、`retry_policy`。

### 7.4 “所有业务表包含 tenant_id”是过度声明

冲突：

- Architecture 写“所有业务表包含 tenant_id，查询层自动过滤”。
- 实际上有些子表或事件表通过 Run/Project 间接关联，不一定直接有 `tenant_id`。

建议：

- 改成“租户隔离在项目/运行等聚合根处强制，子资源通过聚合根间接隔离”。

修复进度：architecture 和 PRD 已改为聚合根按 tenant 过滤、子资源通过聚合根间接隔离。

补充修复：architecture §8.1 / §8.2 已用当前 ORM 表清单校准数据模型摘录，把不存在的 `Run 1──N Notification` 改为 `Run 1──N NotificationLog`，并补充 `AppUser`、`ApiToken`、`Project`、`Environment`、`Schedule`、`RunEvent`、`ProjectMember`、`AuditEvent` 等关键实体字段，避免只列 4 个老实体造成 schema 边界误判。

### 7.5 日志归档路径与 Redis 生命周期冲突

冲突：

- `docs/runbook.md` 写日志路径为 `logs/{run_id}/output.log`。
- 当前代码归档为 `logs/{run_id}.jsonl`。
- `docs/architecture.md` 写归档完成后删除 Redis Stream。
- 当前代码归档成功后设置短 TTL，失败后设置 24h TTL。
- `docs/prd.md` F-EX-05 验收写“日志持久化可回看”，而当前 `main` 只发现 S3 归档写入，未发现读取 `logs/{run_id}.jsonl` 的 API 或前端回看入口。
- `docs/architecture.md` §10.2 曾写 Run 状态事件使用 Redis Pub/Sub；当前 `engine/events.py` 实际写 Redis Stream `run:{id}:events` 并更新 `run:{id}:status` hash，SSE 端点通过 Stream + hash 推送和判断终态。

建议：

- runbook 改成当前 JSONL 路径。
- architecture 改成“归档后设置 TTL，保留给 in-flight SSE 读者”。
- catalog / TODO 把 F-EX-05 从“已完成”改成“实时流已完成，归档回看闭环待补”。
- architecture §10.2 改成当前 Redis Stream / status hash 机制，不再写 Pub/Sub。

修复进度：runbook 已改为 `logs/{run_id}.jsonl`；architecture 已改为归档后 Redis Stream 设置 TTL，并补充“后端归档读回 API 已实现，前端 UI 回看入口仍缺失”；runbook 的 S3 lifecycle 示例已拆成 `logs/` 默认 90 天、`reports/` 默认 30 天，且不再把 lifecycle 对齐等同为 UI 日志回看闭环；catalog / TODO 已把 `F-EX-05 日志归档回看闭环` 更新为后端 API 已补、前端入口待补；architecture §10.2 已改为 Redis Stream + status hash。

### 7.6 retry failed archive 文档与实现不完整

历史冲突：

- worker settings 曾有 `retry_failed_archives` 周期任务，但函数体为空。
- 如果 runbook/architecture 暗示失败归档可自动重试，当时实现并不支持。

建议：

- 文档里标为未实现，或补实现。

修复进度：已补实现与测试。`archive_logs` 失败会把 Run ID 登记到 Redis retry set，`retry_failed_archives` cron 会重试并在成功后清理登记；architecture / runbook 已改为当前事实。归档日志读回 API 已补，前端 UI 入口仍归 F-EX-05。

### 7.7 Docker socket proxy 文档与 compose 现状要分层表达

现状：

- README 提醒生产建议使用 docker-socket-proxy。
- `docker-compose.yml` 当前直接挂载 `/var/run/docker.sock`。

建议：

- 文档要明确：当前 dev compose 直接挂载；生产加固建议另行部署 docker-socket-proxy 或 K8s Job。

修复进度：README 已把 docker-socket-proxy 表述为生产建议，并保留当前 dev compose 直接挂载 Docker socket 的事实；architecture §9.3 已去掉“已通过 Socket Proxy 限制”的过度声明，改为当前 compose 事实 + 生产加固路径；runbook 已新增 Worker Docker Socket 暴露风险章节和上线前检查命令。

### 7.8 数据保留、环境变量加密与 Redis 内存保护过度声明

冲突：

- `docs/architecture.md` 曾写“Git 凭证和环境变量使用 AES-256-GCM 加密存储”，但当前 `Environment.env_vars` 仍是明文 JSONB，T01 才是补齐任务。
- architecture 曾写“超期数据批量归档到冷存储”，但当前只看到 Run 日志归档到 S3；数据库 Run 行冷归档未实现。
- architecture 曾写“Redis 内存超过阈值时拒绝新执行入队”，但当前代码只有执行并发/项目并发限制，未发现 Redis 内存阈值入队保护。
- `cleanup_old_runs` 已注册 cron，当前实现可计算 cutoff 并调用仓储删除。
- `RunRepository.delete_terminal_older_than()` 当前硬删超期终态 Run（`done/failed/cancelled/timeout`），并通过真实 Postgres 集成测试验证 result/artifact/event 级联。

建议：

- architecture 区分“Git 凭证已加密”和“env_vars 待 T01”。
- 数据保留口径改为：日志/报告走 S3 lifecycle，DB Run 行清理覆盖超期终态 Run 与级联删除；DB 冷归档和归档日志读回仍是增强项。
- 把 Redis 内存阈值拒绝入队改成未实现增强项，不再写成现状。

修复进度：architecture、feature-catalog、TODO 和 runbook 已按上述口径更新；运行代码已补 retention 删除与归档重试，测试覆盖真实 DB 级联和 retry set。

### 7.9 分层依赖规则与当前 import 图偏差

复核结果：

- `domain`、`infra`、`plugins` 的方向性 import 与 architecture §2.2 基本一致。
- `engine` 当前仍有两类反向依赖：`engine/executor.py` 局部 import `api.metrics.run_terminal_total`，`engine/reclaim.py` import `worker._redact.redact_url_userinfo`。
- `api/v1/admin.py`、`api/v1/analytics.py`、`api/v1/auth.py`、`api/v1/runs.py` 和 `api/deps.py` 仍有直接 SQLAlchemy 查询，未完全满足“api 必须通过 repositories”的目标规则。

影响：

- architecture 原写法会让后续实现者误以为当前 `main` 已完全满足分层规则。
- 若未来继续在 engine 中引用 API / worker 辅助模块，会加重跨层耦合。

修复进度：architecture §2.2 已保留目标规则，同时新增“当前偏差”说明；TODO 技术债新增 `T-ARCH-LAYERS`，建议后续把 metrics 定义迁到中立模块、`engine/reclaim.py` 直接用 `engine.redact`，并逐步把 API 直接查询下沉到 repositories / query service。

## 8. Audit / 安全相关文档冲突

### 8.1 `_serialize` 被描述为脱敏，但实现不是通用 redaction

冲突：

- 任务 README 和任务包硬约束写“审计 `_serialize(value.model_dump())` 脱敏”。
- 当前 `api/audit.py::_serialize` 主要是 `model_dump` / dict / str 包装，没有通用 key redaction。
- 如果 schema 本身没有排除 secret，审计仍可能写入敏感字段。

建议：

- 明确“脱敏由响应 schema 保证”还是“`_serialize` 自身负责 redaction”。
- 如果是后者，需要新增通用 redaction 逻辑，而不是只依赖 `model_dump`。

修复进度：任务 README、T01、T05 已改为“先使用不含 secret/PII 的 schema 或 `value.model_dump()`，再交 `_serialize(...)` 规范化”，并明确不要依赖 `_serialize` 自动按 key 脱敏。通用 redaction 逻辑如要实现，应另起代码任务。

### 8.2 auth 端点直接写 audit，失败可能传播

冲突：

- `api/audit.py` helper 文档写 audit failure 不影响原请求。
- `src/qaplatform/api/v1/auth.py` 中 register/login/create token/revoke token 等成功路径直接使用 `AuditEventRepository.create`，并在同一事务异常时 rollback + raise。

影响：

- “audit best-effort”只对使用 `write_audit` helper 的路径成立，不适用于所有 auth 路径。

建议：

- 文档中区分 helper 行为与 auth 直写行为。
- 若产品要求 audit 失败不阻断业务，应统一 auth 写法。

修复进度：本报告已明确 helper best-effort 与 auth 直写路径差异；未改 auth 行为，是否统一为 best-effort 应作为代码任务评估。

### 8.3 跨租户 404 硬约束需要落到任务与测试中

现状：

- 用户硬约束要求跨租户访问返回 404，而不是 403。
- 部分路由已使用 `get_for_tenant`。
- 某些权限依赖可能在路由取数前返回 403，需要按端点逐个核对。

建议：

- 把“跨租户资源 id 访问返回 404”写成每个相关任务的测试项。
- 列表端点则验收为“不返回其他 tenant 数据”。

修复进度：任务 README 已保留跨租户 ID 访问 404 硬约束；T02 已补充列表端点“不返回其他 tenant 数据”的验收口径。

### 8.4 Rate limit、账户锁定与审计保留口径冲突

冲突：

- `docs/architecture.md` 原写认证端点 `10 次/分钟/IP`、通用 API `100 次/分钟/用户`、连续失败 5 次后锁定账户 15 分钟。
- 当前源码实际是对认证高风险端点（login / register / token / refresh / SSE ticket）使用 strict rate limit `5 次/分钟/限流桶`，不是只统计失败请求；通用 API 是 `100 次/分钟/限流桶`，且已决策不做落库账户锁定。限流桶为 Bearer token hash 或可信代理解析后的客户端 IP。
- `docs/feature-catalog.md` 和 `docs/TODO.md` 曾把“审计日志 3 年保留”放进不做列表；但 `config.py` / `.env.example` 当前默认 `retention_audit_days=1095`，architecture 也把审计日志 3 年保留作为安全策略。

修复进度：architecture §9.5、PRD §4 和 feature-catalog 已改为认证高风险端点 `5/min/限流桶`、通用 `100/min/限流桶`，并明确不是仅失败请求；同时补充 Bearer token hash / 可信代理解析 IP 的限流桶规则，以及认证高风险端点在 rate limit Redis 操作异常时 fail-closed 的 runbook 行为；同时明确不做落库账户锁定；architecture §8.4 / §9.6 已改为审计日志默认 1095 天且由 `QAP_RETENTION_AUDIT_DAYS` 控制；feature-catalog / TODO 已移除“审计日志 3 年保留”不做项，catalog 非功能表改为记录配置已存在但当前 `main` 未发现独立审计清理任务。

### 8.5 “所有写操作审计”表述过度绝对

冲突：

- `docs/architecture.md` 曾写“所有写操作记录审计事件”，README 也写“关键操作全量审计”。
- 当前 `main` 的项目、管道、环境、凭证、成员、通知、schedule、webhook、run trigger / cancel、auth 登录/登出/token 主路径已有审计写入。
- 但 `api/v1/runs.py` 的 `/batch/cancel`、`/batch/retry` 当前没有 audit 事件。
- `api/v1/auth.py` 的 `/sse-ticket` 会创建短期 Redis ticket；是否属于必须审计的临时凭证写入，需要产品确认。

建议：

- 当前文档不要写“所有写操作”或“全量审计”。
- 新增独立任务补齐批量操作审计，并确认 SSE ticket 是否纳入审计范围。

修复进度：README、architecture、feature-catalog、TODO 已改为“关键写操作主路径已覆盖，覆盖率待补齐”；未修改运行代码。

## 9. Feature Catalog 过期或过度声明

### 9.1 Health check 状态错误

冲突：

- catalog 标记 `/health/live`、`/health/ready` 已完成。
- 实际路径不是这两个。

建议：

- 改为 `/health`、`/ready`，或新增兼容路径后再标完成。

修复进度：feature-catalog 已改为 `/health`、`/ready`，T10 任务包也以当前路径做 excluded_urls 验收。

### 9.2 F-LS-01 执行列表过滤状态过度声明

冲突：

- `docs/feature-catalog.md` 原把 F-LS-01 标为 ✅，并写 `api/v1/runs.py` 支持状态/管道/分支/时间范围。
- 当前 `src/qaplatform/api/v1/runs.py::list_runs` 只支持 `status`（含多值）、`project_id` 和 `sort`；`RunListFilter` schema 也只有 `status`、分页和 `sort`。
- `docs/prd.md` §3.7 要求 pipeline / branch / time range 过滤仍未满足。

修复进度：feature-catalog 已把 F-LS-01 改为 ⚠️，TODO 已新增“F-LS-01 执行列表过滤补齐”项，说明缺 pipeline / git_ref / time range 过滤。

### 9.3 F-LS-02 分页状态过度声明

冲突：

- `docs/feature-catalog.md` 原把 F-LS-02 标为 ✅，并写“全局 PaginatedResponse”。
- 当前大部分列表已经分页，但并非“所有列表”：`credentials.py::list_credentials`、`project_members.py::list_project_members`、`auth.py::list_api_tokens` 返回直接 list。
- `docs/prd.md` §3.7 写“所有列表接口支持分页”，严格按 PRD 仍有缺口。

修复进度：feature-catalog 已把 F-LS-02 改为 ⚠️，并列出已分页主列表与仍未分页的 credentials / project members / auth tokens；TODO 已新增“F-LS-02 剩余列表分页补齐”项。

### 9.4 F-LS-03 项目搜索排序状态过度声明

冲突：

- `docs/feature-catalog.md` 原把 F-LS-03 标为 ✅。
- 当前 `src/qaplatform/api/v1/projects.py::list_projects` 已实现 LIKE 转义，并搜索 name / description。
- 但 `docs/prd.md` §3.7 要求“结果按名称字母序排序”；当前 `BaseRepository.list` 默认按 `created_at desc` 排序，未按名称排序。

修复进度：feature-catalog 已把 F-LS-03 改为 ⚠️；TODO 已新增“F-LS-03 项目搜索排序补齐”项。

### 9.5 F-RE-05 用例级历史趋势状态过度声明

冲突：

- `docs/feature-catalog.md` 原把 F-RE-05 “用例级历史趋势”标为 ✅。
- 当前 `api/v1/analytics.py::get_run_trends` 提供项目级每日 run 趋势；`get_flaky_tests` 提供 suite/name 维度 flaky 聚合。
- 尚未发现单个用例历史趋势 API/视图；这与 PRD “看到某个用例最近 N 次的通过率趋势”不完全一致。

修复进度：feature-catalog 已把 F-RE-05 改为 ⚠️，TODO 已新增“F-RE-05 单用例历史趋势补齐”项，历史阶段进度也从 Phase 3 ✅ 改为 ⚠️。

### 9.6 TODO 历史阶段进度过度声明

冲突：

- `docs/TODO.md` 原把 Phase 1 MVP 标为 ✅ 全部完成。
- 但 PRD Phase 1 范围包含 F-PL-02 与 F-LS-01~04；当前 TODO / catalog 同时列出这些功能仍有缺口。
- `docs/TODO.md` 原把 Phase 2 自动化与通知标为 ✅ 主线完成，仅提钉钉/企微缺口。
- 但当前 TODO / catalog 同时列出 F-EX-02 静默窗口、F-EX-03 Webhook 分支过滤 + 同 commit 去重、钉钉/企微仍未达验收。

修复进度：TODO 历史阶段进度已把 Phase 1、Phase 2 改为 ⚠️ 主线部分完成，并列出对应缺口；Phase 3 已在前序修正中改为 ⚠️。

### 9.7 OpenTelemetry 依赖描述不完整

冲突：

- catalog/T10 都说 pyproject 已声明 `opentelemetry-*` 依赖。
- 对 instrumentation 来说成立，但对 OTLP HTTP exporter 不完整。

建议：

- catalog 中明确“缺 exporter 依赖或需改实现方案”。

修复进度：feature-catalog 和 T10 任务包已明确缺 OTLP HTTP exporter 依赖；README / architecture 也改为当前 Prometheus + structlog，OpenTelemetry 追踪待 T10 装配。

### 9.8 Webhook 接收流程过度声明

冲突：

- `docs/architecture.md` 原写 `POST /webhooks/{provider}`，并描述按 repo URL 匹配项目、解析 push/PR/tag、分支过滤和同 commit 去重。
- 当前源码实际路由是 `POST /api/v1/webhooks/{project_id}/trigger`；通过项目 ID 定位项目，按 tenant 隔离，使用可选 `webhook_secret` 验签，随后选择首个 pipeline 与默认/首个 environment 创建 Run。
- 分支过滤与同 commit 去重尚未在 `main` 实现，已由 T06 任务包负责。

修复进度：architecture §6.5 已改为当前项目级 webhook trigger 流程，并显式说明 Git 平台事件解析、repo URL 匹配、分支过滤与去重待 T06 补齐。本轮复核 `api/v1/webhooks.py` 后确认：当前 `main` 仍只从 `Project.settings.webhook_secret` 读取 HMAC 密钥，创建 Run 时未传 `dedup_key`，也未读取 `allowed_branches`。

### 9.9 Allure HTML 预览状态过度声明

冲突：

- PRD F-RE-04 的验收目标包含 HTML 报告在线预览。
- 旧 catalog 曾把 F-RE-04 标为已完成，后续一度只写“Allure HTML 报告在线预览需实测确认”。
- 历史上 `engine/executor.py::_upload_artifacts` 只遍历 `working_dir / "results"` 下的直接文件，遇到目录会 `continue`；因此目录型 Allure HTML report 不会被上传。
- 当前 `_upload_artifacts` 会递归扫描 `results/` 下文件，保留相对路径，并把 `allure-report` / `allure-results` 目录下文件标成 `allure-report`。
- 前端 `runs/detail.tsx` 只在 `artifact.type === "allure-report"` 时展示预览按钮；`artifact-preview.tsx` 可以 iframe 预签名 URL，但主线执行链路未稳定产出可预览的 Allure HTML artifact。

建议：

- 把 F-RE-04 标为部分完成：预签名下载已实现，Allure/HTML 预览上传闭环未达。
- 新增独立任务补齐目录上传、入口文件预览 URL、S3 key 布局、size/count 限制与集成测试。

修复进度：feature-catalog 已把 F-RE-04 改为 ⚠️；TODO 已新增 `F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐`；architecture §6.1 已补当前上传边界；递归上传与 Allure 目录落库已补单测和真实 DB/S3 集成测试，前端完整预览体验仍待补。

### 9.10 F-PL-03 资源限制状态过度声明

冲突：

- PRD F-PL-03 的描述是“限制单次执行的 CPU/内存/产物大小”。
- 当前 CPU / 内存限制已在 `engine/docker_backend.py` HostConfig 中设置，timeout 也有 SIGTERM → 30s → SIGKILL 路径。
- `worker/tasks.py::_build_pipeline_config` 已把环境级 `max_artifact_size_mb` / `max_artifacts_count` 传入执行配置。
- `engine/executor.py::_upload_artifacts` 已在上传和写 DB 行前检查单文件大小与数量，并递归上传 `results/` 下文件；总大小、磁盘限制、资源用量记录与前端 Allure HTML 入口仍未闭环。
- `ResourceLimits.disk_bytes` 字段存在，但未进入 Docker HostConfig；architecture 原写“资源限制（CPU/内存/磁盘）”容易被误读为磁盘限制已实现。
- PRD 还要求 OOM/timeout 记录终止原因和资源用量；当前代码可把 OOM/timeout 映射为 `timeout`，但本轮未发现资源用量写入日志或 summary 的闭环。

建议：

- catalog 中 F-PL-03 改为部分完成。
- 将 F-PL-03 的产物大小限制与 F-RE-04 的上传/预览闭环合并成一个实施任务，避免两个任务重复改 `_upload_artifacts`。

修复进度：feature-catalog 已把 F-PL-03 改为 ⚠️；TODO / catalog §4.1 已把待办改为 `F-PL-03 / F-RE-04 产物限制与上传/预览闭环补齐`；architecture §6.1 / architecture §9.3 已补 CPU/内存、磁盘、产物限制与资源用量记录边界；环境级产物 size/count 限制与递归上传已补 worker 映射、executor 强制校验与真实 DB/S3 测试，剩余磁盘限制、资源用量记录和前端 Allure/HTML 预览入口。

### 9.11 通知条件 AND/OR 与模板能力过度声明

冲突：

- PRD F-NT-01 要求条件类型包括状态变更、通过率阈值、连续失败次数；F-NT-02/F-NT-03 还写到“每个渠道可独立配置模板”和项目名、失败用例等变量。
- 当前 `worker/notifications/__init__.py::_evaluate_conditions()` 只支持 `status`、`pass_rate`、`failed` 三类字段，且多个条件是 AND；OR 与连续失败次数未实现。
- 当前模板是 `NotificationRule.template` 规则级字段，不是 channel 内独立字段；变量替换只覆盖 `run_id`、`status`、`passed`、`failed`、`total`、`pass_rate`。
- 当前 `main` 未合入 T03/T04，`ChannelRouter` 只注册 `email` 与 `webhook`，钉钉 / 企业微信不应在 catalog 中标为 main 已完成。

建议：

- catalog 拆分通知能力：channel 支持、条件表达、模板、日志、失败处理。
- 后续补齐 F-NT-01/F-NT-03 时，先决定每渠道模板是嵌入 `channels[]`，还是沿用规则级模板并修改 PRD 验收。

修复进度：PRD 和 feature-catalog 已明确当前条件组合为 AND，OR 属于后续增强；channel 支持也区分当前 main 与 T03/T04 待合入。本轮复核通知源码后，feature-catalog 已把 F-NT-03 从 ✅ 改为 ⚠️，TODO / catalog §4.1 已新增“F-NT-01 / F-NT-03 通知规则与模板验收补齐”。

### 9.12 API token scope enforcement 需要避免过度表述

现状：

- API token 创建、过期、吊销、认证路径已实现，`middleware.CurrentUser` 也会携带 `scopes`。
- `api/auth/permissions.py::check_permission` 有 scope 判断：非 `*` scope 需要包含 `action.value`。
- 但 `api/deps.py::get_current_user` 把 middleware user 转成 `UserIdentity` 时没有保留 `scopes`。
- `api/deps.py::require_project_permission` 与 `enforce_project_action` 创建 `PermissionContext` 时也没有传入 `scopes`。
- `src/qaplatform/api/v1/auth.py` token 管理端点直接依赖 middleware `get_current_user`，没有进一步调用 `check_permission(Action.TOKEN_MANAGE)`。

建议：

- `F-AU-02` 不要标为完全完成；应拆出 API token scope enforcement 补齐任务。
- 修复时应覆盖 tenant-scoped、project-scoped、token 管理端点三类路径，并补测试证明受限 scope 不能越权。

修复进度：feature-catalog 已把 F-AU-02 和“API Token 吊销 + scope”降级为 ⚠️；TODO 已新增“F-AU-02 API Token scope enforcement 补齐”；architecture §9.1 也已改成“基础已实现，项目级路由传递仍需补齐”。

补充修复：`docs/architecture.md` 第 15.3 节原写 API Token 使用 `X-API-Token`；当前 `api/auth/middleware.py` 只通过 HTTP Bearer 解析 token，且 `TokenService.parse_bearer_token()` 要求 `qap_` 前缀。architecture 已改为 `Authorization: Bearer qap_<token_id>_<secret>`，并注明当前 middleware 不解析 `X-API-Token`。

### 9.13 执行隔离网络策略需要避免绝对化

现状：

- `ExecutionSpec.network_policy` 默认是 `deny`，`DockerBackend._network_mode("deny")` 返回 `none`，默认容器不可访问宿主网络。
- API schema 允许 `network_policy` 为 `allow` / `deny` / `restricted`；`allow` 会使用 Docker `bridge`，这是测试需要联网安装依赖时的显式例外。
- `restricted` 只映射到 `qap-restricted` 网络；仓库当前未发现 docker-compose 或部署脚本自动创建该网络。
- Docker backend 默认还设置 `User="1000:1000"`、只读 rootfs、drop all capabilities、`no-new-privileges` 和 PID limit。

建议：

- PRD / catalog / architecture 不要用“不可访问宿主网络”这种无条件口吻描述所有执行环境。
- 改为“默认 deny 隔离，联网必须由环境显式放开；restricted 网络需部署侧提供”。

修复进度：PRD §3.3 / §4、feature-catalog F-EX-04、architecture §9.3 已改为默认隔离 + 显式网络策略例外，并补充 `restricted` 部署前置条件。

## 10. Frontend 文档与设计文档冲突

### 10.1 `frontend/FRONTEND_PROMPT.md` 已不适合作为当前契约

冲突点包括：

- auth path 与 token 存储策略过期。
- SSE path 过期。
- artifact download 行为过期。
- pipeline/run/environment 类型与后端 schema 不一致。
- 部分 UX/组件结构与当前已实现前端可能不一致。

建议：

- 文件顶部加“历史提示词，仅供参考，当前 API 以 OpenAPI/schema 为准”。
- 或将其改写为当前前端维护指南。

修复进度：`frontend/FRONTEND_PROMPT.md` 已加历史提示词说明，并明确“不可不核对源码直接作为实现输入”；当前维护指南改由 `frontend/README.md` 承担。

### 10.2 `frontend/README.md` 是 Vite 模板文档

现状：

- `frontend/README.md` 主要是 Vite/React 模板说明，不是 QA Platform 前端开发指南。

建议：

- 改成项目级前端说明：启动、构建、API base URL、i18n、类型生成/维护、已知 TS 债务。

修复进度：`frontend/README.md` 已重写为 QA Platform 前端维护指南，覆盖本地启动、脚本、API 契约、i18n、类型维护和已知 TS 债务。

### 10.3 前端组件库口径过期

冲突：

- `frontend/FRONTEND_PROMPT.md` 原写 TailwindCSS + shadcn/ui，并要求 shadcn/ui installation。
- 当前 `frontend/package.json` 使用 Radix UI primitives、`cmdk`、`sonner` 与本地 `components/ui` 包装；没有 shadcn CLI/包作为运行时依赖。

修复进度：`FRONTEND_PROMPT.md` 已改成 TailwindCSS 4 + Radix UI primitives + local `components/ui` wrappers，并移除 shadcn 安装指令。

### 10.4 `DESIGN.md` 不像当前产品设计真相源

现状：

- `DESIGN.md` 内容偏外部 SaaS/Linear 风格分析、品牌/营销/视觉规范。
- 当前开发者指令强调 operational tool 应保持克制、密集、可扫描，不做营销式 landing page。

修复进度：已重写为 QA Platform 当前产品设计系统，覆盖目标、语气、token、组件、页面模式、交互状态、响应式、可访问性、i18n 与禁止模式。

建议：

- 后续新增前端页面时应以当前 `DESIGN.md`、`frontend/src/index.css` 和现有 UI primitives 为准。

### 10.5 前端 TS 历史债务需要独立任务

现状：

- maintainer 已确认前端 build 失败来自历史文件：
  - `analytics-panel.tsx`
  - `notification-rules-panel.tsx`
  - `trigger-run-modal.tsx`

建议：

- 新增 `T-FRONTEND-TS`，不要让普通功能任务承担全量修复。

修复进度：任务 README、TODO 和本报告均把历史 TS 债务保留为 `T-FRONTEND-TS` 独立任务；CI 目前只豁免 3 个已知文件，任何新 TS 错误仍会失败。

## 11. 数据库与模型文档冲突

### 11.1 Schedule quiet_windows 与 Project silent_windows 必须统一语义

见 4.2。这里是 T05 最大的模型层冲突。

需要决策：

- 是否保留 schedule 级 `quiet_windows`？
- 如果保留，是否仍可通过 schedule API 编辑？
- project 级 `silent_windows` 是否优先于 schedule 级 quiet windows？
- 两者命名是否应统一，避免“quiet”和“silent”双概念长期并存。

修复进度：任务包和 catalog 已记录两套机制的边界与当前实现差异；长期共存/迁移仍需 maintainer 决策。

### 11.2 soft delete 文档要区分历史迁移与最终 schema

现状：

- 历史迁移 005 曾给部分表加 `deleted_at`。
- 006 又移除了 `TestResult` / `RunEvent` / `NotificationLog` 的无用 soft delete。
- 最终 schema 可成立，但历史文档/路线图容易让读者以为这是当前矛盾。

建议：

- 在 architecture 中只描述最终 schema。
- `fix-roadmap.md` 保留历史记录即可。

修复进度：`fix-roadmap.md` 已标为历史档案，architecture 只描述当前 schema。

### 11.3 本地 pyc 迁移缓存不是实现

现状：

- 本地存在 `alembic/versions/__pycache__/007_encrypt_environment_env_vars...pyc` 一类缓存痕迹。
- 源码迁移文件不存在时，不能把 pyc 当作实现。

建议：

- 不在文档中引用 pyc。
- 若需要 T01 migration，应以 `.py` migration 文件为准。

修复进度：任务包继续要求新增 `.py` alembic migration；文档不把本地 pyc 当作实现依据。

### 11.4 本地数据库当前版本低于源码 head

本轮复核迁移链时确认：

- `.venv/bin/alembic heads` 返回 `006 (head)`，源码迁移链是单 head。
- `.venv/bin/alembic current` 返回 `005`，当前本地数据库尚未应用 `006_remove_unused_deleted_at.py`。

影响：

- 这不是文档内容冲突，而是本地环境状态；README 和 development 中“运行迁移到 head”的说明是正确的。
- 运行依赖真实数据库的后端 / E2E 测试前，应先执行 `.venv/bin/alembic upgrade head`，否则当前数据库 schema 可能与 ORM / 文档描述的最终 schema 不一致。

处理边界：

- 本轮只记录状态，不自动迁移本地数据库，避免把文档审计任务变成环境变更。

## 12. Execution / Plugins 文档冲突

### 12.1 内置 runner 列表不一致

现状：

- 部分文档仍只突出 pytest/JUnit/Git。
- 当前代码已注册 Jest、Playwright、Go test runner。
- PRD Phase 4 又把 Go/Jest/Playwright 列为未来项。

建议：

- PRD 改成“已支持基础 Go/Jest/Playwright runner；更完整插件市场/高级插件能力仍属未来”。

修复进度：README、feature-catalog、architecture 已列出 Jest / Playwright / Go test 为当前内置 runner；PRD Phase 4 改为“更多第三方 Runner / Collector 扩展”和开放插件市场。

补充修复：README 项目结构树的 `plugins/builtin` 注释也已同步为 pytest / Jest / Playwright / Go / JUnit / Git，避免和 README 顶部插件能力描述不一致。

补充修复 2：README 的插件开发示例已补 `RunnerProtocol.build_command()`；architecture 的协议片段也已加入 `build_command` 与当前 `run_tests(..., env_vars: dict[str, str] | None = None)` 签名，避免照抄旧示例写出无法被 executor 调用的 runner。

### 12.2 Git shallow clone 状态过期

冲突：

- Architecture 写 shallow clone Phase 1 待实现。
- 当前代码和 schema 已有 `shallow_clone`，Git clone 路径也使用 `--depth 1`。

建议：

- 更新 architecture。

修复进度：architecture 已改为当前 git_source 默认支持 shallow clone（`--depth 1`）。

### 12.3 Docker executor / artifact 限制描述需要实测校准

冲突：

- 文档对 resource limit、artifact report 类型、Allure 在线预览等能力描述较满。
- 代码已实现 CPU/内存/超时、基础产物上传、预签名下载和环境级产物数量/大小上传侧强制校验。
- 当前会递归扫描 `results/` 文件并标记 Allure 目录文件，但前端仍缺稳定选择 `index.html` 作为入口并处理关联资源加载的完整体验。
- README 插件开发段落曾把 CollectorProtocol 示例写成“JUnit XML、Allure”，容易被理解为当前已有 Allure collector；实际内置 collector 仍只有 JUnit。

建议：

- 按实际 executor 行为补一组能力矩阵：
  - 已实现。
  - 部分实现。
  - 文档愿景。

修复进度：architecture 已补当前资源限制与产物上传边界；feature-catalog / TODO 已把 F-PL-03 与 F-RE-04 标为部分完成，并新增待办；README 插件开发示例已改为“当前内置 JUnit XML；Allure JSON/TAP 等可作为后续扩展”；产物 size/count 已补自动化证据，Allure 目录/预览与磁盘/资源用量仍待补。

### 12.4 F-EX-07 自动重试状态过度乐观

冲突：

- `docs/feature-catalog.md` 曾把 F-EX-07 标为 ✅，并写作 `engine/reclaim.py + worker/tasks.py` 已完成“仅基础设施失败重试”。
- `worker/tasks.py` 确实有 `_should_retry()` 和 `_attempt_retry()`，能按 pipeline `retry_policy` 创建共享 `retry_group_id`、递增 `attempt` 的 retry Run，并用 `_defer_by` 做指数退避。
- 历史上 API schema `RetryPolicyInput` 写入的是 `max_attempts`、`retry_on`、`backoff_seconds`、`scope`，但 `_should_retry()` 读取 legacy `max_retries`，测试里也用的是 `max_retries`，与实际 API 写入字段不一致；当前已统一为读取 `max_attempts` 并兼容 legacy `max_retries`。
- 但 `execute_run()` 只有在 `RunExecutor.execute()` 向外抛异常时才会调用 `_attempt_retry()`；当前 `RunExecutor.execute()` 会捕获多数 clone / setup / Docker 执行异常，调用 `fail_if_current()` 后返回 `RunStatus.FAILED`。
- `engine/reclaim.py` 的 worker_lost 逻辑只把失联 worker 的 Run 标为 `failed` 并清理 orphan container，不会创建 retry Run。
- `docs/prd.md` 的 worker_lost 异常路径曾直接写“如配置了自动重试，自动创建新 Run attempt”，容易被读成当前 `main` 已闭环。

建议：

- catalog / TODO 不应把真实 worker 黑盒重试场景标成 PR 必跑完成项；它应继续留在 nightly/manual lane。
- 当前已统一 retry policy schema 与 worker 读取口径，补了 API-facing `max_attempts` / `retry_on`、waiting retry run、worker_lost callback 与真实 DB retry run 测试；测试断言失败仍不重试。
- worker_lost 已进入自动重试 callback，并补了 nightly/manual external-stack 黑盒；真实 Docker/clone/setup/container wait 其它黑盒场景继续作为后续增强验证。

修复进度：feature-catalog / TODO / backend-test-audit 已改为当前边界；运行代码和测试已补自动重试核心闭环。

### 12.5 F-EX-08 优先级队列入队侧与消费侧脱节

冲突：

- `docs/feature-catalog.md` 曾把 F-EX-08 标为 ✅，写成三档队列 + 触发类型映射 + API priority 覆盖 + per-project quota 已完成。
- `worker/scheduler.py` 确实会按 Run `priority` 写入 `queue:high` / `queue:medium` / `queue:low`，并在入队前执行全局并发与单项目并发配额；`RunRepository.find_waiting()` 会按 `priority, created_at` 取等待队列。
- 但 `WorkerSettings.queue_name` 默认是 `queue:medium`，`docker-compose.yml` 只启动一个未设置 `QAP_WORKER_QUEUE` 的 worker。也就是说，默认部署只消费 medium 队列；写到 high/low 的任务缺少默认消费闭环。
- `TRIGGER_PRIORITY` 中 manual 默认是 medium，只有手动/API 触发在请求体显式设置 `priority=0` 才进入 high；这与“手动触发天然 high”的注释/直觉容易混淆。

建议：

- 后续任务需要选择实现方式：单 worker 支持多队列消费，或 compose / runbook 明确启动 high/medium/low 多组 worker。
- 补端到端测试验证 high 队列会被消费、高优先级能插队、同优先级 FIFO，以及默认 manual priority=1 / 显式 priority=0 的边界。

修复进度：feature-catalog 已把 F-EX-08 改为 ⚠️；TODO 已新增“F-EX-08 优先级队列消费闭环”；architecture §6.1 已补当前队列边界。

### 12.6 smoke 测试点数量写死

冲突：

- `docs/feature-catalog.md` 曾写“`scripts/smoke/` · 6 页面 83 测试点”。
- 当前 `scripts/smoke/` 确实包含 login / projects list / project detail / runs list / run detail / settings 这 6 个页面脚本，但脚本内 `log_step` 数量已经不是 83。

建议：

- 文档保留“覆盖 6 个页面脚本”即可，具体检查点数量以脚本为准，避免每次增加 smoke 检查都要同步维护一个容易漂移的总数。

修复进度：feature-catalog 已去掉固定 83 数字，改为“具体检查点以脚本内 `log_step` 为准”。

## 13. `fix-roadmap.md` 的定位

`docs/fix-roadmap.md` 不是当前功能 backlog，而是“合并多 review 共识版”的历史路线图。

已确认问题：

- 顶部基线已经过期：`ruff check` 干净、单元测试 608、`main @ a34ced4` 均不应当被当作当前事实。
- 部分条目写“已修”或“部分完成”，需要结合当前 `main` 源码复核。
- 其中“不要按这些误判修改”的内容仍有价值，应保留历史语境。

建议：

- 文件顶部加醒目说明：
  - “历史 review 档案，非当前实现状态真相源。”
  - “当前 backlog 以 `feature-catalog.md` 和 `tasks/` 为准。”
  - “已完成标记仅表示当时对应 commit/分支上下文，不保证当前 main 已包含。”

## 14. 建议修复顺序

### P0：先修任务执行会踩坑的文档

1. 更新 `docs/tasks/README.md` 验收口径。已完成第一轮修正。
2. 修正 T02 的不存在章节引用与 audit 路径。已完成第一轮修正。
3. 修正 T03 的 `httpx_mock` 依赖说明。已完成第一轮修正。
4. 修正 T05 的 cron tick 文件位置，并决策 `quiet_windows` vs `silent_windows`。文件位置已修；catalog 和任务包已补充两套窗口的边界说明，是否长期共存仍需 maintainer 决策。
5. 修正 T10 的 exporter 依赖缺口、健康检查路径、已有 config 字段。已完成第一轮修正；是否允许新增 exporter 依赖仍需 maintainer 决策。

### P1：修正对开发者启动/验证有直接影响的文档

1. 修正 README / development 中 `make up` 说明。已完成第一轮修正，并新增 `make infra-up`。
2. 修正 `make seed` 命令或 `Makefile`。已完成第一轮修正。
3. 修正 `.env.example` 的密钥默认值、rate limit env var 与缺失 `Settings` 字段。已完成第一轮修正。
4. 修正 CI/E2E 文档与 workflow trigger 不一致。已完成：push / PR 跑 `tests/e2e/auth-flow.spec.ts`，手动触发跑全量 E2E；本地 E2E 前置条件也已补充根目录 npm 依赖、`frontend/` 依赖和 `.venv`；TODO/catalog 剩余项已改为“E2E CI 覆盖扩展”。

### P2：修正长期真相源

1. 给 `fix-roadmap.md` 加历史档案说明。已完成第一轮修正。
2. 更新 `feature-catalog.md` 的状态定义与路径错误。已完成第一轮修正。
3. 更新 `docs/prd.md`，把远期愿景和当前验收拆开。已完成第一轮修正。
4. 更新 `docs/architecture.md` 与当前 schema/API/日志行为对齐。已完成第一轮修正。
5. 更新 `docs/runbook.md` 的日志路径和 Redis TTL 行为。已完成第一轮修正。

### P3：清理前端与设计历史文档

1. 把 `frontend/FRONTEND_PROMPT.md` 改成历史提示词，或重写为当前前端契约。已完成历史提示标注。
2. 重写 `frontend/README.md`。已完成第一轮修正。
3. 重定位或重写 `DESIGN.md`。已完成：已改为当前 QA Platform 产品设计系统。

## 15. 后续建议拆分任务

建议新增独立文档任务，避免混入功能 PR。当前本轮文档修复已覆盖 `T-DOC-01` 到 `T-DOC-05`；Git 凭证执行链路、Pipeline collector 配置、手动触发参数验收、审计覆盖、API token scope、数据保留运维闭环、分层边界、结构化日志全局化、lint、TS 与前端 API 类型债务仍应独立处理：

| 任务 | 内容 | 状态 |
|---|---|---|
| `T-DOC-01` | 修正 `docs/tasks/README.md` 与首批 8 个任务包的验收、来源、路径、依赖和安全口径冲突。 | 已完成第一轮修复 |
| `T-DOC-02` | 修正 README、development、`.env.example`、Makefile seed/up 文档。 | 已完成第一轮修复，`.env.example` 已文档化全部 `Settings` 的 `QAP_` 字段 |
| `T-DOC-03` | 修正 PRD、feature-catalog、TODO 的状态与引用。 | 已完成第一轮修复 |
| `T-DOC-04` | 修正 architecture/runbook 与当前实现冲突。 | 已完成第一轮修复 |
| `T-DOC-05` | 重写 frontend README / FRONTEND_PROMPT / DESIGN 定位。 | 已完成第一轮修复 |
| `T-GIT-CREDENTIALS` | 补齐 F-PM-01 / F-PM-02 Git 凭证执行闭环：解密项目绑定的 HTTPS token / SSH key 并安全注入 Git clone，确保错误与日志脱敏，覆盖私有仓库成功、认证失败、凭证轮换后的执行路径。 | 未处理，已记录为 PRD F-PM-01/F-PM-02 缺口 |
| `T-PIPELINE-COLLECTOR` | 补齐 F-PL-01 Pipeline collector 配置：决定当前 JUnit-only 是正式产品限制还是实现 collector 选择/配置；若补实现，需贯通 API schema、ORM/JSONB、worker `PipelineConfig`、executor `get_collector(...)` 与测试。 | 未处理，已记录为 PRD F-PL-01 缺口 |
| `T-AUDIT-COVERAGE` | 补齐审计写入覆盖：批量取消/批量重试至少应有 audit；SSE ticket 是否审计需产品确认。 | 批量取消/批量重试与 SSE ticket 已补审计写入；剩余写路径按业务风险矩阵继续补齐 |
| `T-ARTIFACT-PREVIEW` | 补齐 F-PL-03 / F-RE-04 产物限制与上传/预览闭环：传递并执行上传侧 size/count 限制，决定是否实现磁盘限制，补 OOM/timeout 资源用量记录，递归或打包上传 Allure HTML 报告、明确入口 URL 并补测试。 | 已补 size/count 限制映射、上传侧强制校验、递归上传 Allure/HTML 目录文件和真实 DB/S3 测试；磁盘限制、资源用量记录、前端预览入口/资源加载仍缺 |
| `T-LOG-REPLAY` | 补齐 F-EX-05 日志归档回看闭环：提供从 `logs/{run_id}.jsonl` 读取历史日志的 API / 前端入口，并处理 Redis Stream TTL 过期后的回放体验。 | 后端归档日志读回 API 与真实 DB/RBAC/API 测试已补；前端入口仍缺 |
| `T-AUTH-SCOPE` | 补齐 API token scope enforcement 在 tenant-scoped / project-scoped / token 管理端点的传递与测试。 | 未处理，已记录为 PRD F-AU-02 缺口 |
| `T-MANUAL-TRIGGER` | 补齐 F-EX-01 手动触发参数与入队验收：让后端可指定 commit / environment，明确与前端触发 payload 的边界，并补“触发后 < 5s 入队”的可验证测试或压测口径。 | 未处理，已记录为 PRD F-EX-01 缺口 |
| `T-EXEC-RETRY` | 补齐 F-EX-07 自动重试端到端闭环：统一 `RetryPolicyInput.max_attempts` 与 worker legacy `max_retries` 读取口径并补 1-5 边界校验，让真实 Docker/clone/setup 基础设施异常进入 `_attempt_retry()`，并确认 worker_lost 是否自动重试。 | 已补 API-facing max_attempts/retry_on、waiting retry run、worker_lost callback、真实 DB retry run 测试与 external-stack worker_lost 黑盒；其它 Docker/clone/setup 黑盒重试仍待产品化决策 |
| `T-QUEUE-PRIORITY` | 补齐 F-EX-08 优先级队列消费闭环：决定单 worker 多队列或多 worker 部署，验证 high/low 队列消费、高优先级插队和同优先级 FIFO。 | 已补 compose high/medium/low worker、manual priority 队列矩阵单测、真实 DB priority+FIFO 排序 |
| `T-NOTIFICATION-TEMPLATE` | 补齐 F-NT-01 / F-NT-03 通知规则与模板验收：OR、连续失败次数、每渠道模板、项目名和失败用例变量。 | 未处理，已记录为 PRD F-NT-01/F-NT-03 缺口 |
| `T-RETENTION-OPS` | 补齐数据保留清理闭环：修复 `cleanup_old_runs` 导入/测试，明确是否先 soft-delete 超期终态 Run、是否覆盖 `cancelled/timeout`，决定是否实现 `retry_failed_archives`、artifact 对象清理与 DB 行冷归档。 | 已补超期终态硬删、result/artifact/event 级联、失败归档 retry 与归档日志 API 读回；DB 行冷归档仍是增强项 |
| `T-ARCH-LAYERS` | 收敛分层 import / DB 访问偏差：把 `engine` 反向依赖的 `api.metrics` / `worker._redact` 迁出或改为中立模块，并逐步把 API 路由里的直接 SQLAlchemy 查询下沉到 repositories / query service。 | 未处理，已记录为技术债专项 |
| `T-LOGGING` | 结构化日志全局化：在 worker/arq 入口调用统一日志配置，收敛 engine / worker / plugin 的 stdlib logger 输出形态，保证 API 与后台任务日志字段一致。 | 未处理，已记录为技术债专项 |
| `T-LINT` | 清理 main 既有 ruff 历史债务。 | 已处理，CI `backend-test` 已加入 `ruff check src tests` |
| `T-FRONTEND-TS` | 清理前端 3 个历史 TS 错误文件。 | 未处理，保持独立任务 |
| `T-FRONTEND-API` | 拆分或对齐前端 API DTO、hook 路径/响应形状与 UI view model 类型，覆盖 Run、run trigger payload、run summary `error/errors` 归一化、Environment、environment editor payload、Pipeline 嵌套 selector / retry shape、pipeline modal payload、`use-projects.ts` search/q 参数、`use-pipelines.ts` 路径、`use-notifications.ts` pagination、`use-sse.ts` fallback、TestResult `xfail` 等已登记偏移。 | 未处理，避免在文档审计中改运行代码 |

## 16. 不建议做的事

- 不建议直接把 `fix-roadmap.md` 当作当前 backlog 全量执行。
- 不建议在功能任务中顺手清理全部历史 lint/TS 债务。
- 不建议在任务分支未合并前，把 catalog 标成“main 已完成”。
- 不建议继续从过期的 `frontend/FRONTEND_PROMPT.md` 生成前端代码。
- 不建议把 `frontend/src/types/api.ts` 当成后端原始契约源，除非先完成 DTO / view model 拆分。
- 不建议新增 API 路径来迎合旧文档，除非产品明确要兼容旧路径。

## 17. 仍需 maintainer 决策的问题

这些不是纯文档错别字，需要产品/架构决策：

1. 是否需要在 PRD 中正式补审计日志查询章节；当前任务包和 catalog 已改为引用 catalog，旧 `PRD §9.6` 引用不再作为执行依据。
2. T05 的 `Schedule.quiet_windows` 与 `Project.settings.silent_windows` 是否共存？
3. T10 是否允许新增 OTLP HTTP exporter 依赖？
4. 是否需要实现独立的审计日志清理任务；当前配置有 `retention_audit_days=1095`，但本轮只发现执行记录清理 cron。
5. 是否需要 DB 行冷归档；失败归档自动补偿与归档日志读回 API 已实现，但前端归档日志 UI 入口仍待产品决策。
6. `/auth/sse-ticket` 这种短期临时凭证写入已纳入审计；后续是否需要审计查询 UI 与告警规则仍待产品决策。
7. Pipeline collector 配置是补实现，还是把当前 JUnit-only 写成正式产品限制并调整 PRD F-PL-01 验收口径。
8. Allure/HTML 报告后端已递归上传静态目录文件；前端预览是直接选择并预签 `index.html`，还是把报告打包为单个 zip/html artifact 后专门渲染，仍需决策。
9. 真实 worker 黑盒自动重试是否要从 nightly/manual 提升为 PR 必跑门禁。
10. F-EX-08 采用 high/medium/low 多 worker 部署；后续如改为单 worker 多队列，需要重新补 runbook/CI 覆盖。
11. F-NT-03 的“每渠道模板”是否必须实现为 `channels[]` 内独立模板，还是接受当前规则级模板并调整 PRD 验收口径。
12. F-EX-05 的归档日志回看后端已采用 API 直接读取 `logs/{run_id}.jsonl`；前端是直接消费该 API，还是额外把归档日志注册成 artifact 复用下载/预览链路，仍需产品决策。
