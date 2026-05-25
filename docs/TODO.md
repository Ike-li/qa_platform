# QA 平台 TODO

> 完整功能盘子与状态见 [`feature-catalog.md`](feature-catalog.md)
> **每项待办的可交付任务包见 [`tasks/`](tasks/README.md)**（codex-ready，含规格 + 起点 + 验收 + 约束）
> 本文件按优先级排序"近期要做什么 / 不做什么"，与 catalog §4 保持同步。
> 更新于 2026-05-25（PRD 与代码已对齐：账户锁定从 PRD 删除、rate limit 10→5 对齐到代码默认；Vue→React 已修；8 个任务包已起草）

---

## 1. 高优先级 — PRD 验收未达（必须做）

| # | 项 | 来源 | 缺什么 |
|---|---|---|---|
| 1 | F-PL-02 环境变量加密 | PRD §3.2 验收 | `env_vars` 当前明文 JSONB；需复用 `dependencies.py` CredentialCipher |
| 2 | 审计日志查询 API | PRD §9.6 | 写入端已就位，缺 `/admin/audit-events` 查询路由 |
| 3 | F-NT-02 钉钉通知 | PRD §8 | 中国大陆网络硬约束 |
| 4 | F-NT-02 企业微信通知 | PRD §8 | 同上 |

## 2. 中优先级 — 验收边角 + 性能验证

| # | 项 | 来源 | 缺什么 |
|---|---|---|---|
| 5 | F-EX-02 静默窗口 | PRD §3.3 验收 | 发布冻结期不触发 cron 未实现 |
| 6 | F-EX-03 Webhook 分支过滤 + 同 commit 去重 | PRD §3.3 验收 | `dedup_key` 字段在 ORM 已有，路由层未接入 |
| 7 | F-LS-04 测试结果 suite/关键字过滤 | PRD §3.7 验收 | 当前仅 status |
| 8 | 非功能性能压测 | PRD §4 | 读/写 API p99、日志推送 < 2s 目标未验证 |
| 9 | E2E 测试 CI 自动触发 | fix-roadmap §4.3 | 当前 `workflow_dispatch`，需启用 push 触发 |

## 3. 低优先级 — 增强项

| # | 项 | 备注 |
|---|---|---|
| 10 | OpenTelemetry 装配 | 仅声明依赖，无 instrumentation 代码 |
| 11 | 部署 checklist 完善 | 密钥/CIDR/lifecycle 一键勾选；附到 `runbook.md` |

## 4. 明确不做

详见 [`feature-catalog.md`](feature-catalog.md) §5。摘要：
- 账户锁定（已与 PRD §4 同步删除，滑动窗口 rate limit 已挡）
- 跨分支/跨环境对比专属视图、历史日志全文搜索、数据导出 CSV、Slack 通知
- Phase 4 全部项（K8s Job、多 Worker 管理、分区、插件市场）
- 邮箱验证、独立 Webhook 配置模块、3 年审计保留

---

## 历史阶段进度

| 阶段 | 状态 |
|---|---|
| Phase 1 MVP | ✅ 全部完成 |
| Phase 2 自动化与通知 | ✅ 主线完成（含 F-EX-08 优先级队列），差钉钉/企微 |
| Phase 3 洞察与报告 | ✅ 主线完成（仪表盘/Flaky/Allure/系统状态页/趋势） |
| Phase 4 规模化 | ⛔ 整体不在当前范围 |

逐项细节见 [`feature-catalog.md`](feature-catalog.md)。
