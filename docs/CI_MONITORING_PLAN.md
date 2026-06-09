# CI 状态监控方案

**问题**: 推送代码后没有检查 CI 是否通过，可能导致远程分支包含失败的代码。

**解决方案**: 建立 CI 状态监控机制

---

## 🚨 当前 CI 状态

**最新推送**: `0074043` Update status: mark report sharing feature as completed  
**CI 状态**: ⏳ 正在运行（已运行 3+ 分钟）  
**历史**: 有一次 CI 失败记录

---

## 🛠️ 已创建的工具

### 1. CI 状态检查脚本

**位置**: `scripts/check-ci.sh`

**功能**:
- 检查最近 5 次 CI 运行
- 显示最新运行状态
- 如果失败，提供修复建议
- 如果运行中，提示等待

**使用方法**:
```bash
./scripts/check-ci.sh
```

**输出示例**:
```
✅ CI 通过！代码已安全合并
或
❌ CI 失败！需要修复
或
⏳ CI 正在运行中...
```

---

## 📋 推荐工作流

### 方案 A: 推送后立即检查（推荐）⭐

```bash
# 1. 推送代码
git push

# 2. 立即检查 CI 状态
./scripts/check-ci.sh

# 3. 如果运行中，等待完成
gh run watch  # 实时监控

# 4. CI 通过后继续工作
```

### 方案 B: 推送后等待通知

```bash
# 1. 推送代码
git push

# 2. 等待 GitHub 邮件/通知
# （需要在 GitHub 设置中启用通知）

# 3. 收到通知后检查
./scripts/check-ci.sh
```

### 方案 C: 定期检查

```bash
# 每次会话结束前检查
./scripts/check-ci.sh

# 或在 BACKLOG 中添加检查任务
```

---

## 🔧 在 CLAUDE.md 中添加的建议

在 `~/.claude/CLAUDE.md` 中添加：

```markdown
## Git Push 后 CI 检查协议

**每次 git push 后，必须检查 CI 状态**：

1. **立即检查** (推送后)
   ```bash
   git push && ./scripts/check-ci.sh
   ```

2. **等待运行完成** (如果 CI 正在运行)
   - 使用 `gh run watch` 实时监控
   - 或等待 5-10 分钟后再次运行 `./scripts/check-ci.sh`

3. **处理失败** (如果 CI 失败)
   - 查看日志: `gh run view --log`
   - 修复问题
   - 重新提交和推送
   - 再次检查 CI

4. **确认通过** (必须)
   - 看到 "✅ CI 通过" 才算完成
   - 更新 DASHBOARD.md 标记 CI 状态

**不要**在 CI 失败或运行中时就认为工作完成。
```

---

## 🎯 改进的 Git 工作流

### 旧流程（有风险）
```bash
git add .
git commit -m "..."
git push
# 结束 ❌ 没检查 CI
```

### 新流程（安全）⭐
```bash
git add .
git commit -m "..."
git push

# 立即检查 CI
./scripts/check-ci.sh

# 如果运行中
gh run watch

# 确认通过
✅ CI 通过！工作完成
```

---

## 📊 CI 失败处理流程

```
CI 失败
  ↓
查看日志: gh run view --log
  ↓
识别问题类型:
  - 测试失败 → 修复测试
  - Lint 失败 → 修复代码质量
  - 构建失败 → 修复依赖/配置
  ↓
本地验证:
  - pytest --cov (后端)
  - npm run lint (前端)
  - npm run build (前端)
  ↓
提交修复:
  git add .
  git commit -m "Fix CI: ..."
  git push
  ↓
再次检查 CI
  ./scripts/check-ci.sh
  ↓
确认通过
```

---

## 🔍 常见 CI 失败原因

### 1. 测试失败
```bash
# 本地运行所有测试
pytest --cov

# 查看失败的测试
pytest -v --tb=short
```

### 2. 代码质量问题
```bash
# 后端
ruff check .

# 前端
cd frontend && npm run lint
```

### 3. 构建失败
```bash
# 前端构建
cd frontend && npm run build
```

### 4. 类型检查失败
```bash
# 前端类型检查
cd frontend && npm run type-check  # 如果有
```

---

## 🚀 自动化改进建议

### 短期（本周）

**1. 添加 pre-push hook**

```bash
# .git/hooks/pre-push
#!/bin/bash
echo "🔍 运行 pre-push 检查..."

# 后端测试
pytest --cov --cov-fail-under=83 || exit 1

# 后端 lint
ruff check . || exit 1

# 前端 lint
cd frontend && npm run lint || exit 1

echo "✅ Pre-push 检查通过"
```

**2. 更新 CLAUDE.md**
- 添加 CI 检查协议

### 中期（本月）

**3. 添加 GitHub Actions 状态徽章到 README**

```markdown
[![CI](https://github.com/Ike-li/qa_platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Ike-li/qa_platform/actions/workflows/ci.yml)
```

**4. 配置 GitHub 通知**
- 设置 → Notifications
- 启用 Actions 失败通知

### 长期（可选）

**5. CI 状态监控看板**
- 在 DASHBOARD.md 中添加 CI 状态
- 自动更新（通过 GitHub API）

**6. Slack/Email 集成**
- CI 失败自动通知
- 每日 CI 状态摘要

---

## 📝 DASHBOARD.md 集成

在 DASHBOARD.md 中添加 CI 状态：

```markdown
## 🔄 CI 状态

**最近运行**: ⏳ 运行中 / ✅ 通过 / ❌ 失败  
**最后通过**: 2026-06-09 00:51:22  
**检查命令**: `./scripts/check-ci.sh`
```

---

## 💡 最佳实践

### DO ✅
- ✅ 每次 push 后立即检查 CI
- ✅ CI 运行中时等待完成
- ✅ CI 失败立即修复
- ✅ 本地运行测试再推送
- ✅ 使用 pre-push hook

### DON'T ❌
- ❌ 推送后不检查就结束会话
- ❌ CI 失败后不修复就继续工作
- ❌ 跳过本地测试直接推送
- ❌ 假设 CI 会通过

---

## 🎯 当前行动计划

### 立即行动（现在）
1. [ ] 等待当前 CI 运行完成
2. [ ] 检查结果：`./scripts/check-ci.sh`
3. [ ] 如果失败，查看日志并修复
4. [ ] 如果通过，更新 DASHBOARD.md

### 本周内
1. [ ] 更新 CLAUDE.md 添加 CI 检查协议
2. [ ] 添加 pre-push hook
3. [ ] 更新 BACKLOG.md 添加 CI 检查任务

### 本月内
1. [ ] 在 README 添加 CI 状态徽章
2. [ ] 配置 GitHub 通知
3. [ ] 在 DASHBOARD.md 集成 CI 状态

---

## 📚 相关命令速查

```bash
# 检查 CI 状态
./scripts/check-ci.sh

# 实时监控 CI
gh run watch

# 查看失败日志
gh run view --log

# 列出最近运行
gh run list --limit 10

# 本地测试
pytest --cov
ruff check .
cd frontend && npm run lint && npm run build
```

---

**创建时间**: 2026-06-09  
**当前 CI 状态**: ⏳ 运行中（等待结果）  
**下次检查**: 立即运行 `./scripts/check-ci.sh`
