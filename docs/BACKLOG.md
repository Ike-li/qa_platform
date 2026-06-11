# 技术改进 Backlog

> 本文件记录日常审查发现的改进点、技术债和小优化，区别于 [`TODO.md`](TODO.md) 记录的功能开发任务。
> 
> **更新策略**：
> - 每次审查后添加新发现
> - 完成后标记日期并保留（便于回溯）
> - 每月归档已完成项到 `archive/`

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
  - 创建调研报告 docs/DOC_MANAGEMENT_RESEARCH.md
- [x] 设计 Doc Health Skill (2026-06-09)
  - 完成技术架构设计
  - 创建设计文档 docs/DOC_HEALTH_SKILL_DESIGN.md

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

- [ ] 完成 OpenTelemetry OTLP 部署验证
  - 基础已就绪，见 TODO.md #25
  - 配置 QAP_OTEL_EXPORTER_ENDPOINT
  - 验证 traces 数据导出
  - **估时**: 半天

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
  - **设计文档**: docs/DOC_HEALTH_SKILL_DESIGN.md

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

**下周预计**:
1. 前端单元测试框架
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
