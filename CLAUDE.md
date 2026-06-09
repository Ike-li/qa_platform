# QA Platform 项目指南

**项目专属配置** - 仅适用于 qa_platform 项目

---

## 新会话启动协议

**每次新会话开始时，按以下顺序操作**：

1. **读取项目状态** (必须)
   - 打开 `DASHBOARD.md` - 30 秒了解项目当前状态、健康度、本周重点
   - 查看"本周重点"和"进行中"任务
   
2. **确定工作内容** (根据用户输入)
   - 如果用户有明确任务 → 直接执行
   - 如果用户说"继续" → 打开 `docs/BACKLOG.md` 查看高优先级未完成任务
   - 如果不确定 → 询问用户想要做什么

3. **完成后更新状态** (必须)
   - 更新 `docs/BACKLOG.md` 标记完成任务 `[x]` + 日期
   - 如有需要，更新 `DASHBOARD.md` 和 `STATUS.md`

**关键文档**：
- `DASHBOARD.md` - 一页纸项目状态（新会话必看）⭐
- `STATUS.md` - 完整状态仪表盘（需要详细信息时看）
- `docs/BACKLOG.md` - 技术改进待办清单（日常工作）
- `docs/TODO.md` - 功能开发任务（PRD 验收）

**不要**在没有读取 DASHBOARD.md 的情况下开始工作，除非用户有非常明确的紧急任务。

---

## 文档同步要求（防止文档腐败）

完成以下操作时，**必须**同步更新对应文档：

### 强制更新触发器
1. **完成任务** → 更新 `docs/BACKLOG.md` 标记 `[x]` + 日期
2. **功能上线** → 更新 `docs/TODO.md` 和 `docs/feature-catalog.md`
3. **架构变更** → 更新 `docs/architecture.md`
4. **API 变更** → 更新 `docs/api-test-matrix.md`
5. **每周末** → 更新 `DASHBOARD.md` 项目状态（如有变化）

### 单一真相源（SSOT）原则
每个事实只在一个地方维护，其他地方只引用或汇总：
- 项目健康度 → `DASHBOARD.md`（主）
- 本周任务 → `docs/BACKLOG.md`（主）
- 功能状态 → `docs/TODO.md`（主）
- 架构设计 → `docs/architecture.md`（主）

### 文档生命周期
- **活跃文档**（每天/周更新）: DASHBOARD.md, BACKLOG.md, TODO.md
- **稳定文档**（偶尔更新）: architecture.md, feature-catalog.md
- **快照文档**（一次性）: 审查报告等，完成后立即归档到 `docs/archive/`

**不要**在文档过期后继续引用它作为"当前状态"。如果发现过期文档，提醒用户更新或归档。

---

## Git Push 后 CI 检查协议

**每次 git push 后，必须检查 CI 状态**：

1. **立即检查** (推送后)
   ```bash
   git push
   # 等待 30-60 秒让 CI 启动
   ./scripts/check-ci.sh
   ```

2. **等待运行完成** (如果 CI 正在运行)
   - 使用 `gh run watch` 实时监控（需要 gh auth login）
   - 或等待 5-10 分钟后再次运行 `./scripts/check-ci.sh`

3. **处理失败** (如果 CI 失败)
   - 查看日志: `gh run view --log-failed`
   - 或访问: https://github.com/Ike-li/qa_platform/actions
   - 修复问题
   - 重新提交和推送
   - 再次检查 CI

4. **确认通过** (必须)
   - 看到 "✅ CI 通过" 才算完成
   - 更新 BACKLOG.md 标记 CI 状态

**不要**在 CI 失败或运行中时就认为工作完成。CI 通过是任务完成的必要条件。

**工具**:
- `./scripts/check-ci.sh` - 检查 CI 状态
- `gh run watch` - 实时监控（需要认证）
- `gh run view --log-failed` - 查看失败日志

---

## 快速命令

```bash
# 查看项目状态
cat DASHBOARD.md

# 查看工作清单
cat docs/BACKLOG.md

# 检查文档健康
./scripts/check-docs.sh

# 检查 CI 状态
./scripts/check-ci.sh

# 运行测试
pytest --cov

# 前端 lint
cd frontend && npm run lint
```

---

**最后更新**: 2026-06-09  
**项目**: QA Platform  
**GitHub**: https://github.com/Ike-li/qa_platform
