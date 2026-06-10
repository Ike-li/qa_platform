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

- [x] 提升低覆盖率模块 (2026-06-10)
  - user_repo.py: 61% → 97% ✅
  - 添加 13 个集成测试覆盖所有 repository 方法
  - 总覆盖率: 89.53% → 90%
  - **Commit**: 999953a

### 可观测性

- [ ] 完成 OpenTelemetry OTLP 部署验证
  - 基础已就绪，见 TODO.md #25
  - 配置 QAP_OTEL_EXPORTER_ENDPOINT
  - 验证 traces 数据导出
  - **估时**: 半天

---

## 🟢 低优先级 (可选改进)

### 文档

- [ ] 创建 CONTRIBUTING.md
  - 贡献流程
  - 代码规范
  - PR 模板

- [ ] 报告分享功能用户文档
  - 添加到 docs/feature-catalog.md
  - API 文档示例

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
