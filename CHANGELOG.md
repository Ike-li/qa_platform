# Changelog

All notable changes to the QA Platform project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows calendar versioning (CalVer).

---

## [Unreleased]

### 进行中
- 报告分享功能待 CI 验证通过后发布
- 前端单元测试框架规划中

---

## [2026-06-09] - CI 修复与依赖更新

### Fixed
- **CI 环境变量**: 修复 `backend-integration-test` 和 `frontend-api-contract` job 缺失环境变量导致的失败
  - 添加 7 个基础环境变量（DATABASE_URL, REDIS_URL, JWT_SECRET 等）
  - 修复 export_openapi.py Settings 初始化失败
  - Commits: ad720b0, 3aac17f
- **API 测试矩阵**: 更新以匹配报告分享功能变更
  - 添加 3 个报告分享端点，移除 1 个废弃 webhook 端点
  - 更新 operation_count: 70 → 72, case_count: 420 → 432
  - Commits: 15a711d, caa4a70, e04b63d
- **代码质量**: 修复 Ruff 和 ESLint 检测的所有问题
  - 移除 3 个未使用的变量（后端）
  - 修复 2 个未使用的 catch 参数（前端）
  - Commit: 5c62232

### Changed
- **依赖更新**: 更新前端 26+ 个过时依赖包
  - Commit: f044d81

### Added
- **项目管理**: 新增项目专属 CLAUDE.md 和工作总结
  - 定义新会话启动协议和文档同步要求
  - Commit: 402d88b

---

## [2026-06-08] - 安全修复与上线审查

### Security
- **P1-2 安全漏洞修复**: seed_admin.py 空密码绕过漏洞
  - 添加空密码强制校验
  - 新增单元测试验证密码验证逻辑
  - 在 .env.example 中添加关键安全警告
  - Commits: 08381f0, 9a69e9e, a91ff0d

### Added
- **报告分享功能**: 基于临时 token 的报告访问机制
  - 11 个文件（后端 6 + 前端 3 + 配置 4）
  - 支持分享链接生成和过期控制
  - Commit: 96d81af
- **状态管理系统**: 建立项目状态管理体系和文档清理
  - 新增 DASHBOARD.md（一页纸状态）
  - 新增 STATUS.md（完整仪表盘）
  - 新增 docs/BACKLOG.md（技术改进清单）
  - Commit: 5e2006b

### Changed
- **上线质量审查**: 完成 10/10 验证项，确认上线就绪
  - 测试覆盖率 100%
  - 所有安全问题已修复
  - P1-2 漏洞已验证修复

---

## [2026-06-07] - Phase 1/2 功能完成

### Added
- **OOM 检测优化**: 修复 OOM 检测竞态条件
  - 对所有非零退出码重试 20 次检查 Docker OOMKilled 状态
  - Commit: c040baf
- **容器环境变量修复**: 非 root 容器绕过环境变量限制
  - 使用 pip --target + wrapper script 模式
  - Commits: 7b3bf36, 4183ef4, b3e26b7

### Fixed
- **E2E 测试**: 修复多个 E2E 测试问题
  - artifact preview 测试超时和 URL 断言
  - frontend-security 测试切换到 Artifacts tab
  - RC gate 端口冲突和数据库迁移冲突
  - Commits: 76a5e49, 2ef4bdb, e341721, 5647fc8, 5e57833, 7035933

### Security
- **安全强化**: P1/P2 安全改进
  - 生产环境保护和 seed_admin 密码强制要求
  - CORS/rate-limit/日志脱敏
  - Commits: 86b5bf8, 7e7021c

### Documentation
- **发布门禁检查清单**: 新增 release_candidate gate 检查清单与验证脚本
  - Commit: cfeabe2
- **重构检查清单**: 基于 CI 全红诊断经验创建
  - Commit: 28d066c

---

## [2026-06-03 之前] - 早期开发

### Added
- Phase 1 MVP 核心功能
  - 项目管理（项目、管道、凭证、环境）
  - 测试执行（手动触发、实时日志、容器隔离）
  - 结果与报告（JUnit 解析、执行摘要、失败详情）
  - 权限与多租户（用户认证、RBAC、租户隔离）
- Phase 2 自动化与通知
  - Cron 定时触发与 Webhook 触发
  - 自动重试与优先级队列
  - 多渠道通知（Email、Webhook、DingTalk、WeCom）
  - 条件通知（status/pass_rate/连续失败）
- Phase 3 洞察与报告
  - 项目级趋势分析
  - Flaky 测试检测
  - 单用例历史趋势
  - 系统状态页

---

## 版本说明

### 版本号规则
- 使用日期作为版本标识（CalVer: YYYY-MM-DD）
- 重大里程碑使用 Phase 标识（Phase 1/2/3）

### 类型说明
- **Added**: 新功能
- **Changed**: 功能变更
- **Fixed**: Bug 修复
- **Security**: 安全相关
- **Documentation**: 文档更新
- **Deprecated**: 即将废弃的功能
- **Removed**: 已移除的功能

---

**维护者**: @raylee  
**最后更新**: 2026-06-09
