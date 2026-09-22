# T17：Flaky 隔离（Quarantine）— 回归解读线的闭环收尾

> **给执行模型的总纲**。本工作包自包含，可整体执行。编号接续 `docs/tasks/` 现有 T01–T16。
> 路径约定：未带前缀的后端路径相对 `src/qaplatform/`，前端路径相对 `frontend/src/`。
> 制定日期：2026-06-16。来源：回归线补齐优先级分析（quarantine / TIA / 单 run 分片三选一，quarantine 改动最小、架构最顺、是 T12+T15 的自然收尾）。

---

## 0. 背景（执行前必读）

产品定位是**持续回归平台：双入口、单核心**，单核心 = 测试结果的记忆与解读（失败分诊 / release verdict / flaky 治理）。

T12 已实现 flaky **检测**（分诊三类含 known_flaky），T15 已实现 flaky **降噪**（纯 flaky 翻转不计入 `new_failed`、不通知）。**回归解读线只差最后一环：把一个 flaky 用例显式"隔离"，使它既不计入 release 判断、也不触发通知，直到被修复或解除。** 这就是 quarantine。

本工作包的全部价值落在一句话：**让 `release-summary` 回答"能不能发"时，能排除被人工隔离的 flaky 噪声**——而这恰好是 ReportPortal 等开源解读平台没有开箱绑定 release 判断的能力，是 QA Platform 已独有的 `release-summary` 的自然延伸。

**明确不做（执行时不要"顺手"做以下任何一项）**：
- **Test Impact Analysis / 只跑受影响测试**（TIA）：平台导入侧不持有代码与覆盖率，架构逆风，留待 dogfooding 验证需求后另立任务。
- **单 run 分片**：只服务入口 A 代跑，改动大、收益窄，远期。
- **自动 quarantine 建议 / 一键批量隔离**：本期只做手动隔离；候选展示沿用 analytics flaky 列表，不做"智能推荐"。
- **quarantine 自动过期清理 cron**：表里留 `expires_at` 字段占位即可，不实现定时清理 worker。
- 不碰 SSE、webhook、优先级队列、执行引擎、TIA、覆盖率拔高类改动。

需求追溯：本包是 PRD D4a（失败分诊）/ D5（通知仅状态变化打扰）/ 试点 §9 release 判断的收尾，不新增 PRD 功能 ID（quarantine 是 flaky 治理的实现细节，归入既有 flaky 能力，回填 catalog 时挂到 F-RE-05 / 通知条目下）。

## 0.1 全局执行约定（继承 `docs/tasks/README.md` 与 T11–T16 §0.1）

- **审计**：所有新增写 API 必须同步审计事件；传入审计前先用不含 secret/PII 的 schema 或 `model_dump()`，再交 `write_audit(...)`。新增写路由后运行架构契约测试 `tests/unit/test_architecture_boundaries.py` 确认审计基线不破。
- **租户隔离**：跨租户 ID 访问返回 **404**（非 403）；取资源用 `get_for_tenant`，禁止 `get_by_id + 手工 tenant 校验`。
- **分层**：路由模块不得直接 `session.execute()`；DB 访问下沉到 repository（受 `test_architecture_boundaries.py` 锁定）。
- **commit**：中文 message + semantic 前缀（feat/fix/test/docs），每个 commit 单一意图，宁拆勿合。
- **依赖**：不引入新的 Python/npm 依赖。
- **Hook/CI**：不使用 `--no-verify`；push 后运行 `./scripts/check-ci.sh`，CI 绿才算完成。
- **测试**：后端配 pytest 单测 + 集成测试，整体覆盖率不低于现状（90%+）；前端配 vitest；`ruff check src tests` 与 `npm run lint -- --max-warnings=0` 零告警。
- **文档**：完成后更新 `docs/feature-catalog.md`、`docs/BACKLOG.md`、`docs/api-test-matrix.md`。

## 0.2 关键代码事实（已核实，直接引用）

| 事实 | 位置 |
|------|------|
| `release-summary` 的 flaky-adjusted 计算：`flaky_keys` = target 窗口内 passed>0 且 failed>0 的 `(suite,name)`；`stable_results` 排除 `flaky_keys` 后算 `flaky_adjusted_pass_rate`；`deltas()` 算 `new_failing_tests` / `recovered_tests` | `infra/database/repositories/run_analytics_repo.py:111`（方法）、`:176`（flaky_keys）、`:181`（stable_results）、`:201`（deltas）、`:222`（new/recovered） |
| release-summary 端点：`GET /projects/{project_id}/analytics/release-summary`，权限 `enforce_project_action(..., Action.RUN_READ)`，调 `repos.run.get_release_summary(project_id, cutoff, git_ref, baseline_git_ref)`，返回 `ReleaseSummaryResponse(**summary, observation_count, window_days)` | `api/v1/analytics.py:184-222` |
| flaky 判定：`list_flaky_tests(window_days, min_runs, ...)`（T12/analytics 复用，窗口 30 天 / min_runs=3） | `infra/database/repositories/test_result_repo.py:180` |
| 失败分诊端点 `GET /runs/{run_id}/triage`：对每个 failed/error 的 `(suite,name)` 归类，前端三组折叠面板 | `api/v1/runs.py`（triage）、`frontend/src/components/runs/failure-triage-panel.tsx` |
| 项目级治理配置（silent_windows）存 `Project.settings` JSONB、经 `PUT /projects/{id}` 写入、权限 `PROJECT_EDIT`、schema 校验模式 | `infra/database/models.py:94`（settings 列）、`api/schemas/projects.py:95-106,161,191` |
| 写权限动作枚举：`Action.PROJECT_EDIT="project.edit"`（项目 Admin）、`Action.RUN_READ="run.read"`、`Action.RUN_TRIGGER="run.trigger"`（Developer）；**无 quarantine 专用动作** | `api/auth/permissions.py:47-56` |
| import 端点写法参考：`get_for_tenant` 取项目、`enforce_project_action(session, user, project.id, Action.X)`、`write_audit(repos, user, action=..., resource_type=..., resource_id=..., after=...)`、`PaginatedResponse` 列表约定 | `api/v1/run_imports.py:262-337` |
| 最新 Alembic 迁移 `009_add_report_share_tokens.py`，**下一个用 `010_`** | `alembic/versions/` |
| API 矩阵当前基线 **75 operations / 450 cases**；校验脚本以 OpenAPI `operation_count` 为准 | `scripts/validate_api_test_matrix.py`、`docs/api-test-matrix.md` |

---

## 1. 目标

让用户把一个已知 flaky 的 `(suite, name)` 标记为"隔离"，此后：
1. `release-summary` 的发布判断**排除**该用例（既不算进 flaky-adjusted 通过率的失败侧，也不报为 `new_failing_tests`）。
2. 通知的 `new_failed` 条件**排除**该用例（隔离即不打扰，与 T15 语义一致）。
3. 失败分诊面板对已隔离用例显示徽标，并提供"隔离 / 解除"入口。

隔离是**手动、可解除、可追溯**的治理动作，默认空集时全平台行为与现状**完全一致**（向后兼容回归）。

## 2. 设计决策（已定，不要重新发明）

### 2.1 存储：独立表，不塞 settings

新增表 `test_quarantine`（迁移 `010_add_test_quarantine.py`）：

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | UUID PK | |
| `project_id` | UUID FK→projects | |
| `suite` | Text NOT NULL | 与 `TestResult.suite` 同口径（存 JUnit classname） |
| `name` | Text NOT NULL | |
| `reason` | Text NOT NULL | 1–200 字符，如 "flaky: 依赖外部时钟" |
| `created_by` | UUID | 操作者 user_id |
| `created_at` | timestamptz NOT NULL | |
| `expires_at` | timestamptz NULL | **占位字段**，本期不消费（不做自动过期 cron） |

唯一约束 `uq_quarantine_project_suite_name (project_id, suite, name)`。索引 `(project_id)` 供按项目批量取集合。

> 为什么不复用 `Project.settings`（silent_windows 那样）：silent_windows ≤20 条、是绝对时间窗口；quarantine 是 per-test、可能上百条且要记 reason/owner/时间，独立表更干净，也便于后续加自动过期。

新建 `infra/database/repositories/quarantine_repo.py::QuarantineRepository`（add/upsert、remove、list 分页、`list_keys(project_id) -> set[tuple[str,str]]`），注册进 `Repos` 容器（参照现有 repo 注册方式）。路由不得直接 `session.execute()`。

### 2.2 端点：新建 `api/v1/quarantine.py`

prefix `/projects/{project_id}/quarantine`，参照 `run_imports.py` 在应用工厂 / `api/v1/__init__.py` 的注册方式挂载（不改现有 router 的 prefix）。三个端点，全部 `get_for_tenant` 取项目、跨租户 404：

| 方法 | 路径 | 权限 | 行为 |
|------|------|------|------|
| `GET` | `/projects/{id}/quarantine` | `RUN_READ` | 分页列出（`PaginatedResponse`） |
| `POST` | `/projects/{id}/quarantine` | **`PROJECT_EDIT`** | body `{suite, name, reason}`；幂等 upsert（已存在则更新 reason，返回 200；新建返回 201）；审计 `quarantine.add` |
| `DELETE` | `/projects/{id}/quarantine?suite=&name=` | **`PROJECT_EDIT`** | 解除；不存在返回 404；审计 `quarantine.remove`（before_state 保留被删行可追溯字段） |

> **2026-09-22 修订**：DELETE 改用查询参数 `?suite=&name=` 而非路径上的 `quarantine_id`。
> 消费方（失败分诊面板）手里拿到的是 `(suite, name)`，没有隔离记录的 id，用路径参数
> 会逼它先查一次列表。实现早已按查询参数落地并被 API 矩阵基线化，此处以实现为准。
>
> POST 的 200/201 区分则相反，以本文档为准：实现原先对新建与更新都返回 201，
> 已于同日修正。

**权限决策（已定）**：写用 `PROJECT_EDIT`（项目 Admin），与 silent_windows 同级——隔离会改变"能不能发"的事实口径，属治理动作，不应 Developer 随手做；读用 `RUN_READ`。**不新增 Action 枚举**，复用现有 `PROJECT_EDIT`。归档项目（`status=="archived"`）拒绝写入（409），参照 `run_imports.py:265`。

### 2.3 release-summary 接入（核心衔接，改动最小处）

- 端点 `get_release_summary`（`analytics.py:190`）在解析出 project 后，查 `quarantined_keys = await repos.quarantine.list_keys(project_id)`，传给 repo 方法。
- `RunAnalyticsRepository.get_release_summary`（`run_analytics_repo.py:111`）新增参数 `quarantined: set[tuple[str,str]] | None = None`（默认 `None`→空集，**向后兼容**）：
  - `:181` 的 `stable_results` 改为排除 `flaky_keys ∪ quarantined`（不只 flaky）。
  - `:222` 的 `new_failing_tests` 用 `deltas()` 计算后，**再过滤掉 quarantined**（隔离用例不应反复报"新增失败"）；`recovered_tests` 不动（恢复是好消息，不隐藏）。
- `ReleaseSummaryResponse`（schema）新增字段 `quarantined_excluded: list[{suite, name}]`（本次判断中实际命中并被排除的隔离用例），Pydantic schema 同步、`api.schemas` re-export 不漂移、OpenAPI 矩阵同步。

### 2.4 通知接入（与 T15 一致，纳入本包）

- T15 的 `_load_new_failed_and_recovered`（`worker/notifications/__init__.py`，计算 `new_failed` 时已排除 known_flaky）增加排除 `quarantined`：查当前 project 的 `quarantine.list_keys`，从 `new_failed` 差集中剔除。
- 语义：隔离用例的新失败既不进 release-summary 也不触发 `new_failed > 0` 规则。`recovered` 不变。

### 2.5 失败分诊接入（UI 入口）

- triage 端点（`runs.py`）每个 failed/error 项增加 `quarantined: bool`（该 `(suite,name)` 是否在 quarantine 表，按 project 一次性取 `list_keys` 后内存判定，无 N+1）。
- 前端 `failure-triage-panel.tsx`：每项加"隔离 / 解除"按钮 + 已隔离徽标；按钮仅在用户具备 `PROJECT_EDIT` 时可用（沿用现有权限判断；无则置灰/隐藏）；调 2.2 端点，成功后刷新分诊。
- Analytics release-summary 视图展示"已排除 N 个隔离用例"（消费 `quarantined_excluded`）。

## 3. 衔接点小结（一图速查）

```
test_quarantine 表 (010)
   │  QuarantineRepository.list_keys(project_id) -> set[(suite,name)]
   ├─→ release-summary 端点 → get_release_summary(quarantined=…)
   │        run_analytics_repo.py:181 stable_results 排除  + :222 new_failing 过滤
   ├─→ 通知 _load_new_failed_and_recovered  → new_failed 排除
   └─→ triage 端点 → 每项 quarantined: bool → 前端面板按钮/徽标
写入：POST/DELETE /projects/{id}/quarantine (PROJECT_EDIT + 审计)
```

## 4. 验收标准（逐条给证据）

1. 迁移 `010` 建表 + 唯一约束生效；`alembic upgrade head` / `downgrade` 往返干净。
2. 三端点真实 API/DB 集成测试：跨租户 404；`POST`/`DELETE` 用 Developer token 返回 403、Admin 成功；`RUN_READ` 可列出；重复 `POST` 同 `(suite,name)` upsert 更新 reason 不报错；审计写 `quarantine.add` / `quarantine.remove` 且不含敏感字段；归档项目写入 409。
3. **release-summary 集成测试**：构造一个 failed 用例 → 隔离它 → `flaky_adjusted_pass_rate` 不再被它拉低、`new_failing_tests` 不含它、响应 `quarantined_excluded` 含它；**解除后恢复原值**。
4. **向后兼容回归**：quarantine 为空时，release-summary 全字段与改动前逐字一致（快照/数值断言）。
5. **通知集成测试**：规则配 `new_failed > 0`；隔离用例新失败 → 不触发；非隔离用例新失败 → 触发。旧字段（`failed > 0` 等）行为不变。
6. triage：端点项含 `quarantined` 标记（单测 + 集成）；前端 vitest 覆盖"隔离/解除按钮、已隔离徽标、无 PROJECT_EDIT 时按钮不可用"。
7. API 矩阵同步：更新 `scripts/validate_api_test_matrix.py` 依赖清单与 `docs/api-test-matrix.md`（+3 operations，cases 相应增加，参照 T11/T13 做法），`pytest` 矩阵校验通过。
8. 后端覆盖率不低于现状；`ruff check src tests` 与 `npm run lint -- --max-warnings=0` 零告警；`./scripts/check-ci.sh` CI 绿。
9. 文档同步：`docs/feature-catalog.md`（flaky 治理 / release 判断条目）、`docs/BACKLOG.md`、`docs/api-test-matrix.md`。

## 5. 执行启动 Prompt（复制即用）

```text
执行 qa_platform 仓库的任务包 T17（Flaky 隔离 / Quarantine），工作目录为仓库根。

必读（按顺序，读完再动手）：
1. docs/tasks/T17_quarantine.md —— 先读 §0/§0.1/§0.2，再精读 §1–§4
2. docs/tasks/README.md —— 执行约定与验证基线（与 T17 §0.1 取并集遵守）

硬性规则：
- 只做 T17 内的工作；§0「明确不做」清单（TIA、单 run 分片、自动建议、过期 cron）一律不碰。
- §2 标注「已定，不要重新发明」的设计决策直接照做：独立表存储、PROJECT_EDIT 写权限、
  release-summary 用并集排除、通知与 triage 接入方式，均不替换方案。
- §0.2 代码事实已逐条核实；若执行中发现文档与代码不符，停止该项，在报告中记录冲突
  （文件:行号 + 差异描述），不要自行偏离文档实现。
- 中文 commit + semantic 前缀、单一意图；ruff / eslint 零告警；不引入新依赖；不使用 --no-verify。

完成定义（缺一不可）：
1. §4 验收标准逐条满足，报告逐条给证据（测试名 / 命令输出摘要）
2. pytest tests/unit -q 全绿；相关集成测试通过；后端覆盖率不低于现状（90%+）
3. 文档同步：feature-catalog.md、BACKLOG.md、api-test-matrix.md
4. commit 完成；如允许推送，push 后运行 ./scripts/check-ci.sh 并等 CI 绿

最终报告格式：
- 改动文件清单（路径 + 一句话目的）
- 验收标准逐条核对表（✓/✗ + 证据）
- 偏离说明（无则写"无"）
- 发现的文档-代码冲突（无则写"无"）
```

---

## 附：与 dogfooding 的关系

T17 是 7 天 v0 gate 的**最佳搭档**：dogfooding 第一天你就会被自家 CI 的 flaky 干扰，边用边隔离——隔离行为本身就是 quarantine 最真实的需求验证 + 验收数据。建议 T17 与 dogfooding 并行启动。回归解读线到 T17 即收口；**TIA 是否要做，以 7 天 gate 中"全量回归慢/贵"是否成为真实痛点为准**，无证据不投入。
