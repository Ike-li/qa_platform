# Changelog

All notable changes to the QA Platform project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows calendar versioning (CalVer).

---

## [Unreleased]

### Fixed
- **恢复 GitHub Actions 并修到全绿**：`.github` 于 2026-07-05 被整体删除，此后远程无 CI。
  从历史恢复后逐个修掉暴露出来的失败——ruff 规则集未显式声明导致本地与 CI 结论不同、
  FastAPI 0.141 起 `include_router` 不再展开子路由使 README 路由契约失效、六处集成测试
  期望未跟上 T15/T17 的 schema 演进、e2e 断言未跟上前端双行渲染。
- **五个端点 100% 崩溃**：`Action` 枚举成员不存在、`get_run_for_action` 位置参数调用、
  `user.id` 不存在、`write_audit` 签名不符、`RunResponse` 当 dict 下标访问。影响
  retry-failed 与报告分享的全部管理端点。
- **「一键重跑失败」实际重跑全部用例**：nodeid 与 `test_path` 同时传给 pytest，
  末尾的目录参数让过滤形同虚设。
- **通知条件 `new_failed` / `recovered` 无法配置**：领域层与 worker 早已实现，
  API 层 Literal 未跟上，创建返回 422、读取返回 500，T15 的降噪能力对外不可用。
- **项目 settings 明文回显 `webhook_secret`**；同时修掉脱敏后「读取—改一处—回写」
  会静默清空密钥的问题。
- **webhook 挑中被禁用的占位 pipeline**：选择逻辑不看 `enabled`，而外部结果导入会
  创建 `enabled=False` 的占位 pipeline 并成为最新的那个。
- **quarantine 重复隔离返回 201 且返回更新前的数据**：identity map 缓存使 RETURNING
  结果被替换成旧实例，接口与审计都拿到旧的 reason。
- **schedule 跨 worker 重复触发**：`FOR UPDATE SKIP LOCKED` 的锁被循环内的 commit
  提前释放，而三个 worker 容器都在跑同一个 cron。改为条件 UPDATE 抢槽。

### Added
- **`missed_fire_policy` 三态语义**：`skip` / `run_once` / `run_all`，带 90 秒宽限窗口
  与三道补跑上限。此前该字段落库但从不被读取。
- **quarantine `expires_at` 生效**：过期判定放在查询层，附每小时清理任务（7 天宽限）。

### Changed
- **行为变更**：`missed_fire_policy` 默认值 `skip` 现在真的一个都不补跑。此前不论停机
  多久、配的是哪种策略，恢复后都只补跑一次。丢弃会写 `schedule_skipped_missed_fire` 审计。
- 显式固定 ruff 规则集（`E4/E7/E9/F/I`），消除本地与 CI 因版本差异得出不同结论。
- 升级依赖：Python 侧修复 1 个 critical（anyio）与 2 个 high；前端 17 个漏洞降到 4 个
  moderate，high/critical 清零。
- 移除 `DASHBOARD.md`、`STATUS.md` 与 14 份 AI 自评快照。健康度评分与「可以上线」这类
  结论必然腐败——2026-09 实测时它们标着「上线就绪」而五个端点全崩。

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
- **上线质量审查**: 安全问题修复与 P1-2 漏洞验证
  - 所有安全问题已修复
  - P1-2 漏洞已验证修复
  - （原文此处记有「10/10 验证项」与「测试覆盖率 100%」，两项均无数据支撑，
    2026-09-22 核实后移除）

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
