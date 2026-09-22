# QA Platform 项目指南

**项目专属配置** - 仅适用于 qa_platform 项目

---

## 新会话启动协议

**每次新会话开始时**：

1. **确定工作内容** (根据用户输入)
   - 如果用户有明确任务 → 直接执行
   - 如果用户说"继续" → 打开 `docs/BACKLOG.md` 查看高优先级未完成任务
   - 如果不确定 → 询问用户想要做什么

2. **判断项目状态时，看可执行的事实，不看文档里的结论**

   | 想知道 | 去哪里看 |
   |---|---|
   | 测试是否通过 | `pytest -q`，集成加 `RUN_INTEGRATION_TESTS=1` |
   | CI 是否绿 | `./scripts/check-ci.sh` 或 `gh run list --workflow=ci.yml` |
   | 最近改了什么 | `git log --oneline -20`，取舍理由在 commit trailer 里 |
   | 待办 | `docs/BACKLOG.md`（技术改进）、`docs/TODO.md`（功能验收） |

   **先把本地依赖与 CI 对齐**：`uv pip install -e '.[dev]' --upgrade`。CI 用
   `pip install -e '.[dev]'` 每次装最新版，本地版本落后时「本地全绿」不代表 CI 会绿。

3. **完成后更新** `docs/BACKLOG.md`，标记 `[x]` + 日期

**不要**依据任何文档里的健康度评分、"可以上线"之类的结论来判断项目状态。
这类快照必然腐败：2026-09 曾出现文档标着"上线就绪"而五个端点 100% 崩溃的情况，
原因就是没人去跑，只在文档之间互相抄。

---

## 文档同步要求（防止文档腐败）

完成以下操作时，**必须**同步更新对应文档：

### 强制更新触发器
1. **完成任务** → 更新 `docs/BACKLOG.md` 标记 `[x]` + 日期
2. **功能上线** → 更新 `docs/TODO.md` 和 `docs/feature-catalog.md`
3. **架构变更** → 更新 `docs/architecture.md`
4. **API 变更** → 更新 `docs/api-test-matrix.md`

### 单一真相源（SSOT）原则
每个事实只在一个地方维护，其他地方只引用或汇总：

| 事实 | 真源 |
|---|---|
| 功能有哪些、处于什么状态 | `docs/feature-catalog.md` |
| 待排期的功能验收 | `docs/TODO.md` |
| 技术改进待办 | `docs/BACKLOG.md` |
| 架构设计 | `docs/architecture.md` |
| 项目当前是否健康 | **没有文档**——跑测试、看 CI，见上文启动协议 |

项目健康度不设文档真源是有意的：任何写下来的评分都会在下一次改动后失效，
而失效的评分比没有评分更危险。

### 文档生命周期
- **活跃文档**（随改动更新）: BACKLOG.md, TODO.md, feature-catalog.md
- **稳定文档**（偶尔更新）: architecture.md, product.md
- **一次性快照**: 不再保留。这类文档只会在写下的那一刻正确，之后就变成误导。
  需要回溯某次决策时看 commit message 的 trailer。

**不要**在文档过期后继续引用它作为"当前状态"。

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

**最后更新**: 2026-09-22  
**项目**: QA Platform  
**GitHub**: https://github.com/Ike-li/qa_platform
