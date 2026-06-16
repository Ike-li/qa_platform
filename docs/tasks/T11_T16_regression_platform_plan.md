# T11–T16 持续回归平台改造计划

> **给执行模型的总纲**。每个工作包（WP）章节自包含，可整体执行，也可按章节单独分派给不同会话。
> 编号接续 `docs/tasks/` 现有 T01–T10。路径约定：未带前缀的后端路径相对 `src/qaplatform/`，前端路径相对 `frontend/src/`。
> 制定日期：2026-06-10。来源：第一性原理需求重审（`docs/archive/first-principles-prd-fable-5.md`）+ 与维护者的定位讨论。

---

## 0. 背景（执行前必读）

产品定位从"QA 自动化执行平台"调整为**持续回归平台：双入口、单核心**：

- **入口 A（已有）**：平台代跑——容器化执行 + cron 定时回归（服务独立维护外部测试的 QA）。
- **入口 B（新建）**：结果导入——外部 CI 上传 JUnit XML（服务已有 CI 的开发团队）。
- **单核心**：测试结果的记忆与解读——失败分诊（为什么红）、release verdict（能不能发）、flaky 治理（哪些测试在说谎）。

本计划的全部工作围绕：打通入口 B、建设解读层视图、补齐入口 A 的高频动作（失败子集重跑）。**PR comment、MCP server、quarantine 工作流等属 PRD v2 范围，刻意不在本批——不要顺手实现。**

需求追溯（PRD = [`docs/archive/first-principles-prd-fable-5.md`](../archive/first-principles-prd-fable-5.md)，每个 WP 必须能对回需求）：

| WP | 承载的需求 |
|----|-----------|
| T11 | PRD D2（一行接入）+ D3（首次价值 ≤10 分钟） |
| T12 | PRD D4a（失败分诊——"为什么红"，使用频率最高的视图） |
| T13 | 定位讨论补充的入口 A 高频动作：每日回归只重跑失败用例 |
| T14 | PRD §8 v0 gate（dogfooding）的工程前置 |
| T15 | PRD D3（冷启动诚实，低样本不下确定结论）+ D5（通知仅状态变化打扰） |
| T16 | PRD D1（TestCase 履历/身份解析）的最小落地 |

**明确不做（执行时不要"顺手优化"以下模块）**：SSE 实时日志、webhook 触发、优先级队列、多租户 RBAC 扩展、覆盖率拔高类改动。

## 0.1 全局执行约定（每个 WP 都必须遵守）

继承自 `docs/tasks/README.md`：

- **审计**：所有新增写 API 必须同步审计事件；传入审计前先用不含 secret/PII 的 Pydantic schema 或 `model_dump()`，再交 `_serialize(...)`；不要依赖自动按 key 脱敏。审计基线由架构契约测试锁定，新增写路由后运行相关契约测试确认。
- **租户隔离**：跨租户 ID 访问返回 **404**（非 403）；取资源用 `get_for_tenant` 模式，禁止 `get_by_id + 手工 tenant 校验`。
- **commit**：中文 message + semantic 前缀（feat/fix/test/docs/refactor），每个 commit 单一意图，宁拆勿合。
- **依赖**：不引入新的 Python/npm 依赖（WP 内明确允许的除外）。
- **Hook/CI**：不使用 `--no-verify`；push 后运行 `./scripts/check-ci.sh`，CI 绿才算完成。
- **测试**：后端改动配 pytest 单测+集成测试，整体覆盖率不得低于现状（90%+）；前端改动配 vitest 测试；`ruff check src tests` 与 `npm run lint` 零告警。
- **文档**：每个 WP 完成后更新 `docs/feature-catalog.md` 对应条目与 `docs/BACKLOG.md`。

## 0.2 关键代码事实（已核实，直接引用）

| 事实 | 位置 |
|------|------|
| `Run` 模型：`pipeline_id`/`environment_id`/`git_ref` 均 NOT NULL；`trigger_type` 为自由 Text；已有 `retry_group_id`/`attempt`/`source_run_id`/`summary(JSONB)`/`metadata(JSONB)` | `infra/database/models.py:314` |
| `RunStatusEnum` 取值：`queued/preparing/running/collecting/done/failed/cancelled/timeout`——**成功终态是 `done`，没有 "passed"** | `infra/database/models.py:40` |
| `TestResult` 模型：身份 = `(run_id, suite, name)` 唯一约束；**没有跨 Run 的 TestCase 实体**；已有索引 `idx_test_result_flaky(suite,name,status)`；status 枚举含 `xfail`（不算失败） | `infra/database/models.py:456` |
| **`suite` 字段实际存 JUnit 的 `classname`**（pytest 输出形如 `tests.unit.test_x` 或 `tests.unit.test_x.TestClass`；classname 缺失才回退 testsuite name，collector 已实现该兜底） | `plugins/builtin/junit_collector.py:122-152` |
| JUnit XML 解析：`JUnitCollector._parse_junit_xml(xml_path) -> list[TestResultData]` | `plugins/builtin/junit_collector.py:99` |
| `Pipeline.stages` 为 NOT NULL JSONB **无默认值**；`Pipeline.enabled` 布尔列存在；`Environment.base_image` 为 NOT NULL Text **无默认值**（get-or-create 必须显式提供） | `infra/database/models.py:236,204` |
| Analytics 现有端点：trends / flaky / release-summary / test-history | `api/v1/analytics.py:46,98,149,186` |
| flaky 判定查询：`TestResultRepository.list_flaky_tests`；release-summary 的 flaky-adjusted 计算（按 `(suite,name)` 元组聚合） | `infra/database/repositories/test_result_repo.py:83`、`run_analytics_repo.py:176` |
| 通知评估入口：`evaluate_terminal_notifications`，由 **worker 执行收尾路径**调用——绕过 worker 的 Run 不会触发通知 | `worker/run_execution.py:14,87` |
| API Token 认证：认证中间件已统一支持 Bearer API token，业务路由无需额外处理 | `api/auth/middleware.py:62` |
| Runner 命令构造：executor 在 `_run_stages` 中调 `runner.build_command(stage.config)`；pytest runner 的 `config["args"]`（自由追加）与 `config["test_paths"]`（**经 `safe_workspace_paths` 路径校验**）分别注入 | `engine/executor.py:494-513`、`plugins/builtin/pytest_runner.py` |
| 通知渠道（钉钉/企微/邮件/webhook 已落地）；**不存在"新项目默认通知规则"机制**，规则均由用户显式创建 | `worker/notifications/channels.py`、`api/v1/notifications.py` |
| 前端页面 | `pages/runs/`、`pages/projects/`、`pages/admin/` |
| Alembic 迁移命名 `NNN_slug.py`，最新 `009_add_report_share_tokens.py`，下一个用 `010_` | `alembic/versions/` |

---

## T11：外部结果导入 API（入口 B）⭐ 最高优先级

### 目标
任何外部 CI 用一次 HTTP 调用把 JUnit XML 导入平台，生成一条终态 Run + TestResult 行，立即进入现有 Analytics/通知管线。

### 设计决策（已定，不要重新发明）
- 端点：`POST /api/v1/projects/{project_id}/runs/import`。**请求体为原始 JUnit XML**（`Content-Type: application/xml`，≤10MB 超限 413），元数据走 query 参数——**不要用 multipart/form-data**（需要 `python-multipart` 依赖，项目从未引入且无 `UploadFile` 用法，违反依赖约定；raw body 还让 CI 端只需 `curl --data-binary`）：
  - `git_ref`（必填 query）、`git_sha`、`branch`（可选）
  - `pipeline_name`（可选，默认 `"external-import"`）、`environment_name`（可选，默认 `"external"`）
  - `started_at`/`finished_at`（可选 ISO8601；缺省用服务器当前时间与 XML 的 time 总和推导）
- 路由注册：优先放 `api/v1/runs.py`；若其 router prefix（`/runs`）不容纳 `/projects/{project_id}/runs/import`，则新建 `api/v1/run_imports.py` 并参照现有 v1 路由在 `api/v1/__init__.py`（或应用工厂）的注册方式挂载——不要为此改动现有 router 的 prefix。
- **NOT NULL 外键的处理**：get-or-create 该项目下名为 `pipeline_name`/`environment_name` 的 Pipeline 与 Environment（幂等，并发安全——利用 `uq_pipeline_project_name`/`uq_environment_project_name` 唯一约束 + on-conflict 或先查后建+冲突重试）。两个模型都有**无默认值的 NOT NULL 字段**，必须显式提供：
  - Pipeline：`stages` 给最小合法占位——stages 的解析与校验在 `engine/pipeline_config.py:42`（`PipelineConfig`），给一个能通过它解析的最小 stage；**`enabled=false`**，防止 import 占位 pipeline 被调度或手动触发执行；`timeout_seconds` 用列默认。
  - Environment：`base_image` 给占位值 `"import/none"`（不会被执行）；其余字段用列默认。
- Run 直接以终态创建：`trigger_type='import'`，status 按结果推导——存在 `failed`/`error` 结果 → `RunStatusEnum.FAILED`（`'failed'`），否则 → **`RunStatusEnum.DONE`（`'done'`，注意枚举里没有 "passed"）**；`summary` **复用 `build_results_summary`（`engine/executor_results.py`，executor 同款构造器）**，保证与执行路径结构一致、Run 详情页无感。不入队、不经过 executor。
- **通知补偿**：通知评估只在 worker 收尾路径触发（`worker/run_execution.py:14,87`）——import 绕过 worker，必须在落库后显式调用 **`evaluate_and_notify(run_id=..., project_id=..., status=..., summary=..., session_factory=...)`（`worker/notifications/__init__.py:270`）**；该函数只需 session_factory，API 进程可满足；其支持的终态为 done/failed/timeout，import 的两个终态均覆盖。
- 解析复用：把 `JUnitCollector._parse_junit_xml` 的核心逻辑抽成可从内存内容（bytes/str）调用的纯函数，文件路径版改为调用它，避免复制粘贴。注意：classname 缺失回退 testsuite name 的兜底 collector 已实现（`junit_collector.py:125`），无需重做。
- **入库复用链（全部现成，按此组装）**：解析得到 `list[TestResultData]` → `build_test_result_rows`（`engine/executor_results.py`，TestResultData→行 dict）→ `TestResultRepository.bulk_create(rows)`（`infra/database/repositories/test_result_repo.py:75`）；summary 用上文 `build_results_summary`。不要手写字段映射。
- 解析宽容：缺 `time` 记 0（已有）；整个 XML 不可解析才 422。同一 `(suite,name)` 重复出现时合并保留最后一条（满足 `uq_test_result_run_suite_name` 唯一约束）。
- 权限：项目 Developer 及以上（与触发执行同级）。API Token 认证由中间件统一处理（`api/auth/middleware.py:62`），路由无需额外工作，但验收必须包含一条用 API token 的用例。
- 审计：记录 `run.import` 审计事件（含 project_id、run_id、结果计数；不含 XML 内容）。

### 验收标准
1. `curl --data-binary @junit.xml -H "Content-Type: application/xml" -H "Authorization: Bearer <api-token>" ".../runs/import?git_ref=main"` 返回 201 + RunResponse；Run 详情页/列表正常显示该 Run，测试结果可过滤查询。
2. 导入的数据出现在 analytics trends / flaky / release-summary / test-history 中（集成测试断言）。
3. 跨租户 project_id 返回 404；无权限 403；坏 XML 422；超大 413。
4. 重复导入同一文件生成两条独立 Run（import 不去重，幂等性由调用方负责）——文档中写明。
5. 单测覆盖解析边界（参数化用例名、缺字段、多 testsuite 嵌套）；新增集成测试走完整 HTTP 路径。
6. OpenAPI 矩阵同步：更新 `scripts/validate_api_test_matrix.py` 所依赖的清单与 `docs/api-test-matrix.md`（参照 T07 的做法）。

---

## T12：失败分诊（核心解读视图）

### 目标
Run 详情页的失败列表从"平铺"升级为"自动分诊"：每个失败归入 **新增失败 / 已知 flaky / 持续失败** 三类，新增失败置顶。这是产品使用频率最高的视图。

### 设计决策
- 后端新增 `GET /api/v1/runs/{run_id}/triage`，对该 run 内每个 `failed/error` 的 `(suite, name)`：
  - `known_flaky`：命中现有 flaky 判定（复用 `TestResultRepository.list_flaky_tests`，`infra/database/repositories/test_result_repo.py:83`，窗口参数与 analytics 端点保持一致；不要重写算法。注意该方法带 `offset/limit` 分页——判定时取全量，可加大 limit 调用或抽出其聚合判定条件复用，二者皆可）。
  - `persistent`：本 run 之前同项目最近 3 次观测全部为 failed/error。
  - `new`：其余（上次观测 passed，或无历史）。
  - 判定优先级：known_flaky > persistent > new。
  - **历史口径**：persistent/new 的"历史观测"与现有 analytics 保持一致——project 级按 `(suite, name)` 聚合（经 `analytics_run_filters`），**不按 pipeline 切分**；不要发明新口径。
- 错误签名聚类：`error_message` 首行（截断 200 字符、数字/UUID/路径归一为占位符）作为签名，同签名的失败折叠为一组。纯函数实现，不引入依赖。
- 响应每项附最近 10 次观测的状态序列（**参考 test-history 端点的查询模式新写批量版**：一次查询取齐本 run 全部失败用例的历史，禁止按用例循环查询造成 N+1）。
- 响应附 `confidence`：两态枚举——观测次数 < 10 为 `"observing"`（前端显示"观察中"），否则 `"established"`。
- 前端：`pages/runs/` 的 Run 详情失败区改为三组折叠面板（新增失败默认展开），每项可展开堆栈 + 履历迷你条（10 格状态色块）。沿用现有组件风格（Radix UI + Tailwind）。
- 权限与隔离：与现有 run 详情读取一致（项目 Viewer 可读）。

### 验收标准
1. 集成测试：构造历史（A 用例翻转、B 用例连续失败 3 次、C 用例首次失败）→ triage 返回三类正确归类。
2. 同签名失败正确聚类；签名归一化有单测（路径/数字替换）。
3. 前端 vitest：三组渲染、空态（无失败时不显示分诊区）、观察中标记。
4. triage 端点 p95 < 500ms（用例数 ≤ 5000 的 run，本地集成测试断言粗粒度即可）。
5. OpenAPI 矩阵同步（同 T11 第 6 条）。

---

## T13：失败子集重跑（入口 A 的高频动作）

### 目标
每日回归红了 N 个用例后，一键只重跑失败的用例，而不是整个 run。

### 设计决策
- 端点：`POST /api/v1/runs/{run_id}/retry-failed`。前置校验：原 run 为终态（`done/failed/timeout/cancelled`）且存在 `failed/error` 测试结果，否则 409。
- 新 Run：复用原 run 的 pipeline/environment/git_ref；`trigger_type='retry_failed'`，`source_run_id=原 run id`，`retry_group_id` 沿用原值（为空则新建），`metadata.retry_failed_cases` 记录选中的 `(suite, name)` 清单。**Run 创建与入队的参考实现：`batch_retry_run_command`（`api/run_batch_commands.py:102`）**，复用其创建路径而非另写。
- 执行端用例过滤：**v1 仅支持 pytest runner**。由 `(suite, name)` 重构 nodeid——注意 **`TestResult.suite` 存的就是 JUnit classname**（见 §0.2）：dotted path 转文件路径（`tests.unit.test_x` → `tests/unit/test_x.py`；**末段判定规则：以大写字母开头视为类名**，输出 `tests/unit/test_x.py::TestClass`，否则全段视为模块路径——这是确定性规则，不要引入其他启发式），加 `::name`（参数化 `name[param]` 原样拼接）。
- **注入通道（已查明，按此实现）**：executor 在 `_run_stages` 中调 `runner.build_command(stage.config)`（`engine/executor.py:494-513`），config 来自 pipeline 静态配置——per-run 过滤需在此处合并：若 run 的 `metadata` 含 `retry_failed_cases`（**executor 持有的是 domain Run，字段名是 `metadata`，`domain/models/run.py:103`；ORM 属性名才是 `metadata_`，勿混淆**），把重构出的 nodeid 列表**追加进 `stage.config["args"]` 的副本**（pytest 位置参数即 nodeid；勿原地修改共享的 pipeline 配置对象）。**不要走 `config["test_paths"]`**——它经 `safe_workspace_paths` 路径校验，nodeid 含 `::` 会被拒。
- 降级规则：非 pytest runner 返回 409（消息说明暂不支持）；失败用例 > 200 个时拒绝并提示整跑（命令行长度风险）。
- nodeid 重构是有损映射：执行时若 pytest 报 "no tests ran"/collect error，run 正常落 failed 并保留日志——不做静默兜底，错误可见即可。
- 前端：Run 详情失败区加"重跑失败用例 (N)"按钮，成功后跳转新 run。
- 权限：项目 Developer+（与触发执行同级）；写路径同步审计（`run.retry_failed`）。

### 验收标准
1. 集成测试（可标 `heavy_docker`）：一个含 2 败 3 过的 pytest run → retry-failed 创建的新 run 只执行 2 个用例。
2. 单测覆盖 nodeid 重构（模块级函数、类方法、参数化、深层路径）。
3. 非 pytest pipeline 调用返回 409；无失败用例返回 409；跨租户 404。
4. 前端按钮状态（运行中禁用、无失败隐藏）有 vitest 覆盖。
5. OpenAPI 矩阵同步（同 T11 第 6 条）。

---

## T14：Dogfooding 数据流（依赖 T11）

### 目标
本仓库自己的 CI 测试结果每天进入一个本地运行的平台实例，平台从此有第一个真实数据流。

### 任务
1. 前端 vitest 输出 JUnit：`frontend/vite.config.ts` 已有 `test:` 配置块（约 12 行处），加 `reporters: ['default', 'junit']` 与 `outputFile: { junit: 'test-results/vitest-junit.xml' }`；同步在 `.github/workflows/ci.yml` 的 frontend-unit-test job 新增 **`if: always()`** 的 upload-artifact 步骤（artifact 名 `frontend-unit-junit`，失败时的结果更有价值，不能只在成功时上传）。vitest 内置 junit reporter，无新依赖。
2. 新建 `scripts/import_ci_results.sh`（pull 模式，本地运行，不改 CI 的上传逻辑）：
   - `gh run list --branch main --limit N` 取最近完成的 run → `gh run download <id>` 拉 `backend-test-artifacts`、`backend-integration-artifacts`、`e2e-artifacts`、`frontend-unit-junit` 中的 `*.xml`
   - 对每份 XML 调 T11 的 import 接口（`git_sha` 用该 CI run 的 head sha，`pipeline_name` 用 artifact 名区分，如 `ci-backend-unit`）
   - 已导入的 CI run id 记录在本地状态文件（如 `.qap-import-state.json`，gitignore），避免重复导入
   - 环境变量：`QAP_IMPORT_URL`、`QAP_IMPORT_TOKEN`、`QAP_IMPORT_PROJECT_ID`
3. `docs/development.md` 增加 dogfooding 一节：如何起本地实例、建项目和 token、配 cron（macOS launchd 或手动）。

### 验收标准
1. 本地 `make infra-up` + API 实例下，运行脚本一次，平台出现 ≥3 条 import Run（backend-unit / integration / e2e 各一；`frontend-unit-junit` 在本 WP 的 CI 改动合入后的下一次 CI run 才产生，首轮允许缺失），Analytics 有数据。
2. 重复运行脚本不产生重复导入（状态文件生效）。
3. 脚本有 `--dry-run`；对缺失 artifact 的 CI run 跳过并打印原因，不中断。

---

## T15：解读层可信度收紧（置信度展示 + 通知降噪）

### 目标
让平台的判断"诚实"：低样本不下确定结论；通知只在状态变化时打扰。

### 任务
1. **置信度**：`analytics.py` 的 flaky / test-history / release-summary 响应增加 `observation_count`（及 flaky 的 `window_days`）字段；前端对应视图在 `observation_count < 10` 时显示"观察中（N 次观测）"徽标代替确定性标签。Pydantic schema 同步，OpenAPI 矩阵同步。
2. **通知降噪**：通知条件是 `{field, operator, value}` 表达式（支持 all/any 组合），**字段白名单 `NOTIFICATION_CONDITION_FIELDS` 现为 `status / pass_rate / failed / consecutive_failures`**（`worker/notifications/__init__.py:37,89`；评估入口 `evaluate_and_notify` 同文件 :270）。做法是**新增条件字段，不是新增"条件类型"机制**：
   - 新增字段 `new_failed`：本次 run 相对**同 project + 同 pipeline 的上一个终态 run** 的新增失败用例数（按 `(suite,name)` 差集；上一 run 必须限定同 pipeline，否则 unit 与 e2e 流水线的失败集合会互相污染产生误报）。已知 flaky 用例（复用 T12 的判定）不计入 `new_failed`——这就是"纯 flaky 翻转不打扰"的实现点。
   - 同时新增字段 `recovered`：上一终态 run 失败、本次通过的用例数（与 `new_failed` 是同一差集计算的另一半，边际成本极低）；"恢复通知"由 `recovered > 0` 规则表达。
   - 实现参考：`consecutive_failures` 字段已是"查历史"的先例，沿用其评估处的实现模式。
   - **不存在"新项目默认通知规则"机制（已核实），不要去找**。降噪的落点是：前端创建通知规则表单的默认条件改为 `new_failed > 0`。
   - 已有规则不迁移、行为不变（向后兼容）。
3. 文档：`docs/feature-catalog.md` 通知条目更新。

### 验收标准
1. 单测（规则配 `new_failed > 0` / `recovered > 0`）：连续两次相同失败集合 → 第二次不通知；出现新增失败 → 通知；用例恢复 → `recovered` 规则通知。旧字段（如 `failed > 0`）行为不变（向后兼容回归）。
2. 已知 flaky 用例单独翻转不计入 `new_failed`、不触发通知（集成测试）。
3. 前端"观察中"徽标有 vitest 覆盖。

---

## T16：TestCase 身份规范化（后置，最小方案）

### 目标
参数化用例（`test_x[param1]`、`test_x[param2]`）在分析视图中可折叠为母用例，履历不被参数打散。

### 设计决策（保守，明确不做大改）
- **不新建 TestCase 表、不改 test_result 表结构。** 仅在分析查询层提供规范化选项。
- 纯函数 `normalize_case_name(name) -> str`：剥离尾部 `[...]` 与 `(...)` 参数段；放在 `domain/` 下，单测覆盖边界（嵌套括号、名字本身含括号、空参数）。
- `analytics.py` 的 flaky 与 test-history 端点增加查询参数 `collapse_params: bool = false`；为 true 时按规范化名聚合（SQL 层用表达式或取回后聚合，以现有 repo 模式为准，注意性能——数据量大时优先 SQL 表达式 + functional index，迁移用执行时的下一个可用编号）。
- 前端 Analytics 页加"折叠参数化用例"开关，默认关。
- 用例改名的履历合并：**本期不做**，在 `docs/BACKLOG.md` 留条目。

### 验收标准
1. 构造 `test_a[1]` 失败、`test_a[2]` 通过的历史：collapse=false 时两条独立记录；collapse=true 时一条 `test_a`，状态序列合并、观测数相加。
2. normalize 函数单测 ≥ 8 个边界用例。
3. 开关状态前端测试覆盖；默认行为与现状完全一致（回归保障）。

---

## 执行顺序与依赖

```
T11 (import API)  ──→  T14 (dogfooding，依赖 T11)
T12 (分诊)        ──→  独立，可与 T11 并行
T13 (重跑失败)    ──→  独立，可并行
T15 (置信度+降噪) ──→  建议在 T12 后（共享"已知 flaky 集合"判定）
T16 (身份规范化)  ──→  最后，可选
```

建议单会话一次只做一个 WP。每个 WP 完成定义：代码 + 测试 + lint 零告警 + 文档同步 + commit（单一意图、中文、semantic 前缀）+ push 后 `./scripts/check-ci.sh` 确认 CI 绿。

## 全局完成定义（全部 WP 结束后）

1. 本地实例里能看到：自家 CI 导入的 Run（T11+T14）、带分诊的失败视图（T12）、可一键重跑失败用例的执行 Run（T13）。
2. `docs/tasks/README.md` 索引表更新 T11–T16 行的完成状态；`DASHBOARD.md` 本周重点更新。
3. 后端覆盖率 ≥ 90%，前端测试全绿，CI 全绿。
4. **工程完成 ≠ 项目完成**：T14 落地后立即启动 PRD §8 的 v0 gate——维护者连续 7 天用平台（而非 GitHub Actions 页面）判断 main 状态；T16 之后的任何新功能投入，必须以 gate 结果为依据，不得在无验证数据的情况下继续扩展功能。

---

## 附录：执行启动 Prompt 模板（每个 WP 一个会话，替换 `<WP>` 即用）

```text
执行 qa_platform 仓库的任务包 <WP>（见标题），工作目录为仓库根。

必读（按顺序，读完再动手）：
1. docs/tasks/T11_T16_regression_platform_plan.md —— 先读 §0/§0.1/§0.2（背景、执行约定、已核实的代码事实），再精读 <WP> 章节
2. docs/tasks/README.md —— 执行约定与验证基线（与计划 §0.1 取并集遵守）

硬性规则：
- 只做 <WP> 章节内的工作；计划 §0"明确不做"清单与其他 WP 一律不碰，不顺手重构相邻代码。
- 章节内标注"已定，不要重新发明"的设计决策直接照做，不替换方案、不另选技术路线。
- §0.2 的代码事实已逐条核实；若执行中发现文档与代码实际不符，停止该项，在最终报告中记录冲突（文件:行号 + 差异描述），不要自行偏离文档实现。
- 遵守：中文 commit + semantic 前缀、每个 commit 单一意图；ruff / eslint 零告警；不引入新依赖；不使用 --no-verify。

完成定义（缺一不可）：
1. <WP> 的验收标准逐条满足，报告中逐条给出证据（测试名 / 命令及输出摘要）
2. pytest tests/unit -q 全绿；涉及的集成测试通过；后端覆盖率不低于现状（90%+）
3. 文档同步：docs/feature-catalog.md 对应条目、docs/BACKLOG.md；涉及 API 的 WP 同步 docs/api-test-matrix.md
4. commit 完成；如允许推送，push 后运行 ./scripts/check-ci.sh 并等待 CI 绿

最终报告格式（必须包含）：
- 改动文件清单（路径 + 一句话目的）
- 验收标准逐条核对表（✓/✗ + 证据）
- 偏离说明（无则写"无"）
- 发现的文档-代码冲突（无则写"无"）
```

注意事项：
- 执行顺序：T11 → T14（依赖 T11 已合入）→ T12 / T13（互相独立，可并行不同会话）→ T15（建议在 T12 后）→ T16（可选）。
- T14 的会话启动前确认 T11 已合入 main；其余 WP 基于当时的 main 即可。
- 并行执行 T12/T13 时使用隔离工作区（如 git worktree），避免互相污染。
