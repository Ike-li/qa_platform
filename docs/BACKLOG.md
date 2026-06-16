# 技术改进 Backlog

> 本文件记录日常审查发现的改进点、技术债和小优化，区别于 [`TODO.md`](TODO.md) 记录的功能开发任务。
> 
> **更新策略**：
> - 每次审查后添加新发现
> - 完成后标记日期并保留（便于回溯）
> - 每月归档已完成项到 `archive/`

---

## 🎯 当前目标（2026-06）

**打磨「执行 + 回归」端到端体验** —— 顺核心用户旅程找出并补齐卡点与粗糙处，不新增大功能：

> 跑回归 / 导入结果 → 看失败分诊 → 一键重跑失败 → 判断能不能发版

优先级高于一切新功能投入；T17（flaky 隔离）等新功能在本目标达成前不启动。

---

## 🔧 端到端体验打磨进度（2026-06-16 起）

端到端走查「跑回归/导入 → 看失败分诊 → 一键重跑失败 → 判断能不能发版」发现 4 个断点：

- [x] **卡点 A**：前端接入「重跑失败用例」(2026-06-16) — 后端 retry-failed API 早已就绪，但前端从未接线（detail.tsx「重跑」实为整跑）。已加 `useRetryFailedRun` hook + `RetryFailedButton` 组件 + 分诊区按钮 + i18n + vitest（3 例）；lint / 全量 158 测试绿。
- [x] **卡点 B**：打通 run 详情 → 能不能发版 (2026-06-16) — 已在 run 详情页添加「Release Verdict」跳转链接，直达项目 analytics 并自动携带 git_ref/baseline_git_ref 过滤。
- [x] **卡点 C**：分诊信息前置 + 消除 `runs.triage.*` / `runs.failureTriage.*` 命名重叠 (2026-06-16) — FailureTriagePanel 已移至详情页主区域前置展示，重命名顶栏 runs.triage 键为 runs.summary 并清理了命名冲突。
- [x] **卡点 D**：import run 标识 (2026-06-16) — 各个运行列表及详情页均增加了 trigger_type 字段及 import 专属徽标，以直观区分导入运行与平台内执行运行。


---

## 🚨 高优先级 (本周完成)

### 文档管理改进 ⭐ 新增

- [x] 创建 CHANGELOG.md (2026-06-09)
  - 记录版本历史和主要变更
  - 基于 Keep a Changelog 格式
- [x] 修复文档健康检查脚本 (2026-06-09)
  - 修复链接检测逻辑，使用 Python 正确解析 Markdown 链接
  - 检测到 1 个断链（代码示例中的正则表达式，可忽略）
- [x] 在 CI 中添加文档健康检查 (2026-06-09)
  - 新增 doc-health-check job
  - 每次 push/PR 自动运行
- [x] 修复 DASHBOARD 和 STATUS 断链 (2026-06-09)
  - 移除不存在的 PROJECT_REVIEW_REPORT.md 等引用
  - 添加 CHANGELOG.md 链接
- [x] 调研文档管理最佳实践 (2026-06-09)
  - 分析 10+ 个业界工具
  - 创建调研报告 docs/archive/DOC_MANAGEMENT_RESEARCH.md
- [x] 设计 Doc Health Skill (2026-06-09)
  - 完成技术架构设计
  - 创建设计文档 docs/archive/DOC_HEALTH_SKILL_DESIGN.md

### CI 修复

- [x] 修复 CI backend-integration-test 环境变量缺失 (2026-06-09)
  - 添加 7 个基础环境变量到 backend-integration-test job
  - **Commit**: ad720b0
- [x] 修复 CI frontend-api-contract 环境变量缺失 (2026-06-09)
  - 添加环境变量到 frontend-api-contract job
  - 修复 export_openapi.py Settings 初始化失败
  - **Commit**: 3aac17f
- [x] 更新 API test matrix 以匹配报告分享功能 (2026-06-09)
  - 添加 3 个报告分享端点，移除 1 个废弃 webhook 端点
  - 更新 operation_count: 70 → 72, case_count: 420 → 432
  - 更新相关单元测试和集成测试
  - **Commits**: 15a711d, caa4a70, e04b63d

### 代码质量

- [x] 修复 Ruff 检测的 3 个未使用变量 (2026-06-09)
  - report_shares.py, report_share_service.py
  - **Commit**: 5c62232
- [x] 修复 ESLint 检测的 2 个未使用 catch 参数 (2026-06-09)
  - **Commit**: 5c62232

### 未提交功能

- [x] Review 并提交报告分享功能 (2026-06-09)
  - 包含 11 个文件 (后端 6 + 前端 3 + 配置 4)
  - 代码质量已修复
  - 安全性已验证
  - **Commit**: 96d81af

### 依赖更新

- [x] 更新前端依赖 (2026-06-09)
  - 运行 npm update 更新 26+ 个包
  - **Commit**: f044d81

---

## ⚠️ 中优先级 (本月完成)

### 测试改进

- [x] 为前端添加单元测试框架 (2026-06-10)
  - 安装 Vitest + Testing Library + jsdom
  - 添加测试配置和 i18n 支持
  - 创建 11 个测试文件覆盖组件和页面
  - 组件测试: utils, contracts, DurationDisplay, PriorityBadge, RunStatusBadge, BranchBadge, RelativeTime, LanguageSwitcher, ErrorBoundary
  - 页面测试: NotFound, Login
  - 59 个测试通过，67.7% 覆盖率
  - 添加 frontend-unit-test job 到 CI
  - **Commits**: 9bb2bbd, 8886f33, fe7aa32, 3ef010a, e08c325

- [x] 前端测试覆盖率提升到 70%+ (2026-06-10)
  - 122 个测试全部通过（100% 通过率）
  - 覆盖率：Statements 69.38% | Branches 65.66% | Functions 65.66% | Lines 70.33%
  - **测试统计**: 19 个文件，122 个测试用例
  - **新增测试**: mutations (trigger/cancel/update)、queries (results/artifacts/pipelines/environments)、utils、api token 管理
  - **Commit**: bdec52a

- [x] 提升低覆盖率模块 (2026-06-10)
  - user_repo.py: 61% → 97% ✅
  - report_share_service.py: 21% → 100% ✅
  - report_share_token_repo.py: 44% → 97% ✅
  - project_repo.py: 57% → 100% ✅
  - 添加 32 个集成测试（13 user + 12 report_share + 7 project）
  - 总覆盖率: 89.53% → 90.4%
  - **Commits**: 999953a, 1e6e23e, 50788ca

### 可观测性

- [x] 完成 OpenTelemetry OTLP 部署验证 (2026-06-16)
  - 通过 opentelemetry-exporter-otlp-proto-http 导出链路追踪
  - 验证接口和 Redis spans 导出，成功完成 Jaeger 本地端到端部署验证

---

## 🟢 低优先级 (可选改进)

### 文档

- [x] 创建 CONTRIBUTING.md (2026-06-10)
  - 开发环境设置
  - 代码规范 (Python/Ruff, TypeScript/ESLint)
  - 提交指南和 PR 流程
  - 测试要求
  - **Commit**: 60e16e4

- [x] 报告分享功能用户文档 (2026-06-10)
  - 添加到 docs/feature-catalog.md
  - 创建 docs/report-sharing.md
  - API 文档示例和使用场景
  - **Commit**: add6d28

### 文档管理工具化 ⭐ 新增

- [ ] 开发 Doc Health Skill MVP
  - 实现断链检测
  - 实现新鲜度检查
  - 实现日期标记自动修复
  - **估时**: 1 周
  - **设计文档**: docs/archive/DOC_HEALTH_SKILL_DESIGN.md

- [ ] 添加 markdownlint 配置
  - 统一 Markdown 格式规范
  - 集成到 CI
  - **估时**: 2 小时

- [ ] 添加 OpenAPI spec 双向验证
  - 验证 API 文档与实际路由一致
  - 扩展现有 frontend-api-contract job
  - **估时**: 半天

### 文档健康维护 ⭐ 新增

- [ ] 每月运行文档健康检查
  - 命令: `./scripts/check-docs.sh`
  - 修复警告和错误
  - 归档过期文档
  - **频率**: 每月第一周

### 性能优化

- [ ] 数据库查询 profiling
  - 识别 N+1 查询
  - 优化慢查询
  - **工具**: pg_stat_statements

- [ ] 添加查询缓存层
  - Redis 已配置但使用不充分
  - 候选: 项目列表、用户信息

- [ ] 前端性能监控
  - 集成 Web Vitals
  - 添加性能预算

### CI/CD

- [ ] 配置 Dependabot
  - 自动依赖更新 PR
  - 安全漏洞告警

- [ ] 添加自动代码质量检查
  - PR 时自动运行 Ruff + ESLint
  - 覆盖率回归检查

- [ ] 性能回归测试
  - 基于 performance-slo-manifest.json
  - CI 中运行性能 smoke

---

## 📋 技术债清单

### 已知问题
- [ ] 修复不稳定测试 (xfail: OOM detection test)
  - 见 commit b9433e9
  - **优先级**: 中

- [ ] services/ 目录结构审查
  - 当前只有 report_share_service.py
  - 是否需要统一迁移 service 层

### 架构改进
- [ ] 评估引入 DDD 聚合根模式
  - 当前部分使用 Repository Pattern
  - 考虑完整 DDD tactical patterns

- [ ] API 版本化策略
  - 当前所有端点在 /api/v1
  - 未来 breaking changes 如何处理

---

## 🎯 本周聚焦 (2026-06-09 ~ 2026-06-15)

**本周目标**: 
1. ✅ 修复代码质量问题 (已完成)
2. ✅ 提交报告分享功能 (已完成)
3. ✅ 更新前端依赖 (已完成)
4. ✅ 修复 CI 环境变量问题 (已完成)
5. ✅ 更新 API test matrix (已完成)
6. ✅ T11 外部结果导入 API (2026-06-10 完成)
   - `POST /api/v1/projects/{project_id}/runs/import`：原始 JUnit XML 一次调用导入为终态 Run
   - 解析复用 junit_collector（抽出内存版纯函数 `parse_junit_xml_content`），入库复用 `build_results_summary` + `build_test_result_rows` + `bulk_create`
   - 占位 Pipeline（enabled=false）/Environment（import/none）get-or-create 并发安全；落库后补偿调用 `evaluate_and_notify`
   - 注意：导入不去重，重复上传同一文件生成两条独立 Run（幂等性由调用方负责）
   - 测试：30 个 API 单测 + 12 个解析单测 + 7 个集成测试（含 API token、跨租户 404、analytics 四端点可见性）
   - 后续：T14 dogfooding 数据流依赖本接口
7. ✅ T14 Dogfooding 数据流 (2026-06-10 完成)
   - `scripts/import_ci_results.sh`：gh 拉取 main 最近 CI run 的 JUnit artifact → T11 接口导入；状态文件防重复；--dry-run；缺失 artifact 跳过
   - vitest 输出 JUnit（`frontend/test-results/vitest-junit.xml`），CI 新增 `frontend-unit-junit` artifact（if: always()）
   - 本地端到端验证：3 个 CI run 导入 16 条 Run（ci-backend-unit/integration/e2e），trends 有数据，重复运行 0 重复
   - **下一步：开始 7 天 dogfooding（PRD §8 v0 gate）——连续 7 天用平台而非 GitHub Actions 页面判断 main 状态**
8. ✅ T12 失败分诊 (2026-06-11 完成)
   - `GET /api/v1/runs/{run_id}/triage`：failed/error 用例归入 新增失败/已知 flaky/持续失败（优先级 known_flaky > persistent > new）
   - flaky 复用 `list_flaky_tests`（30 天/min_runs=3 与 analytics 默认一致）；persistent/new 历史口径 project 级 `(suite,name)` 聚合（analytics_run_filters），窗口锚定 run.created_at
   - 错误签名聚类（首行截 200、数字/UUID/路径归一）；批量历史查询（窗口函数，无 N+1）；confidence 两态（<10 次观测 observing）
   - 前端 `failure-triage-panel.tsx` 三组折叠面板（新增失败默认展开、堆栈展开、10 格履历迷你条、观察中徽标），无失败不渲染
   - 测试：13 签名单测 + 16 组装/端点单测 + 2 repo 契约单测 + 5 集成测试（三类归类/聚类/空态/跨租户 404/性能：5000 用例中位约 300ms < 500ms）
   - 矩阵同步：74 operations / 444 cases
9. ✅ T13 失败子集重跑 (2026-06-11 完成)
   - `POST /api/v1/runs/{run_id}/retry-failed`：创建只重跑失败用例的新 Run（v1 仅支持 pytest runner）
   - nodeid 重构：`(suite, name)` → pytest nodeid（dotted path → 文件路径，末段大写开头视为类名，参数化原样拼接）
   - executor 注入：run.metadata.retry_failed_cases → 追加 nodeids 到 stage.config["args"]（pytest 位置参数）
   - 前置校验：终态 + 存在 failed/error + pytest runner；失败 > 200 个拒绝（命令行长度风险）
   - metadata.retry_failed_cases 记录 `[(suite, name), ...]`；trigger_type='retry_failed'；审计 run.retry_failed
   - 测试：8 nodeid 单测 + 6 命令单测（非终态/无失败/过多失败/非 pytest/成功路径）+ 4 集成测试（跨租户 404/无失败 409/非终态 409/非 pytest skip）
   - 矩阵同步：75 operations / 450 cases
   - **后续修复** (2026-06-11)：nodeid 嵌套类解析 bug、审计契约、API 矩阵同步、retry_failed 测试 Mock 问题 (commit: d23fc08)
10. ✅ T15 置信度展示 + 通知降噪 (2026-06-11 完成)
   - Analytics 置信度字段：FlakyTest/TestHistoryPoint/ReleaseSummaryResponse 增加 `observation_count`（观测次数）和 `window_days`（窗口天数）
   - 通知降噪条件：新增 `new_failed`（相对上一终态 run 新增失败数，排除 flaky）和 `recovered`（上次失败本次通过数）字段
   - 实现 `_load_new_failed_and_recovered`：查询上一终态 run，计算差集并过滤 flaky 用例
   - 前端同步：TypeScript 类型定义更新
   - 测试：7 个新测试用例（3 个 analytics + 4 个通知），123 个 T15 相关测试全通过
   - **Commits**: 5b21e2b (置信度), 8fe957b (通知降噪)
11. ✅ T16 TestCase 身份规范化 (2026-06-11 完成)
   - 规范化函数：`normalize_case_name(name)` 剥离尾部 `[...]` 和 `(...)` 参数段，使用配对计数处理嵌套括号
   - Analytics flaky 端点：新增 `collapse_params: bool = False` 参数，true 时按规范化名聚合（Python 层）
   - Analytics test-history 端点：新增 `collapse_params` 参数（暂无特殊逻辑）
   - 前端开关：Analytics 页面 Flaky tests 区域添加"折叠参数化用例"checkbox，默认关闭
   - 测试：10 个规范化边界测试 + 2 个 API 折叠测试 + 155 个前端测试全通过
   - **保守方案**：不改表结构，取回后聚合；用例改名履历合并留待后续
   - **Commits**: ecfe24c (后端), 35a7da7 (前端)

**下周预计**:
1. 启动 7 天 v0 gate（PRD §8）- 用平台判断 main 状态
2. OpenTelemetry 配置验证

---

## 📝 使用说明

### 添加新项目
```markdown
- [ ] 任务描述
  - 详细说明
  - **估时**: X 小时/天
  - **Context**: 相关背景或文档链接
  - **风险**: 高/中/低
```

### 完成项目
```markdown
- [x] 任务描述 (完成日期)
  - 简短总结
  - **Commit**: git SHA (如适用)
```

### 归档策略
每月将已完成的项目移至 `archive/backlog-YYYY-MM.md`，保留最近一个月的历史。

---

**最后更新**: 2026-06-09  
**维护者**: @raylee

### 前端测试覆盖 ⭐ 新完成

- [x] 搭建前端测试基础设施 (2026-06-10)
  - 安装 MSW (Mock Service Worker) 用于 API mocking
  - 创建 test fixtures 和 handlers
  - 扩展 test-utils 支持 QueryClient 和 Router
  - **Commit**: ed88cee
- [x] 添加 API Hooks 单元测试 (2026-06-10)
  - use-runs: 9 个测试（查询、状态规范化）
  - use-projects: 11 个测试（CRUD、分页、搜索）
  - use-api-tokens: 3 个测试（创建、列表）
  - 验证 Run 状态映射、cache invalidation、错误处理
  - **Commit**: ed88cee
- [x] 添加 Modal 组件单元测试 (2026-06-10)
  - TriggerRunModal: 3 个测试
  - CreateProjectModal: 3 个测试
  - CreateApiTokenDialog: 4 个测试
  - 验证表单渲染、默认值、提交流程
  - **Commit**: ed88cee
- [x] 前端测试覆盖率从 0% 提升到 59.84% (2026-06-10)
  - 89 个测试全部通过（100% 通过率）
  - CI 门禁已包含 frontend-unit-test job
  - **测试统计**: 17 个文件，89 个测试用例
