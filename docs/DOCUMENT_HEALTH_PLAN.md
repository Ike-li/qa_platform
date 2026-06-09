# 文档审计与瘦身方案

**审计日期**: 2026-06-09  
**总文档数**: 26 个 Markdown 文件  
**总行数**: ~5,571 行

---

## 📊 文档现状分析

### 当前文档分类

```
根目录 (9 个):
- README.md (267 行) - 项目主入口 ✅
- DASHBOARD.md (86 行) - 一页纸状态 ⭐ 今天新增
- STATUS.md (231 行) - 完整状态 ⭐ 今天新增
- PROJECT_REVIEW_REPORT.md (516 行) - 审查报告 ⭐ 今天新增
- CODE_QUALITY_FIXES.md (151 行) - 修复记录 ⭐ 今天新增
- ACTION_ITEMS.md (218 行) - 行动清单 ⭐ 今天新增
- DESIGN.md (235 行) - 设计文档 ✅
- AGENTS.md (未统计) - AI 协作指南 ✅

docs/ (18 个):
- BACKLOG.md (176 行) - 技术改进 ⭐ 今天新增
- TODO.md (135 行) - 功能开发 ✅
- architecture.md (591 行) - 架构设计 ✅
- feature-catalog.md (289 行) - 功能目录 ✅
- testing-strategy.md (206 行) - 测试策略 ✅
- development.md (117 行) - 开发指南 ✅
- runbook.md (222 行) - 运维手册 ✅
- product.md (395 行) - 产品文档 ✅
- PROJECT_STATUS_SYSTEM.md (257 行) - 体系指南 ⭐ 今天新增
- NEW_SESSION_TEST.md (192 行) - 测试指南 ⭐ 今天新增
- ... (其他检查清单、矩阵)
```

---

## 🚨 发现的问题

### 1. 文档重复和冗余 ⚠️

**问题**: 今天新增的 6 个文档可能造成信息重复

| 文档 | 内容 | 重复风险 |
|------|------|---------|
| **DASHBOARD.md** | 项目状态 | ✅ 必要（快速导航） |
| **STATUS.md** | 详细状态 | ⚠️ 可能与 TODO.md 重复 |
| **PROJECT_REVIEW_REPORT.md** | 完整审查 | ⚠️ 一次性报告，会过期 |
| **CODE_QUALITY_FIXES.md** | 修复记录 | ⚠️ 一次性记录，会过期 |
| **ACTION_ITEMS.md** | 行动清单 | ⚠️ 与 BACKLOG.md 重复 |
| **BACKLOG.md** | 技术改进 | ✅ 必要（工作清单） |
| **PROJECT_STATUS_SYSTEM.md** | 体系指南 | ⚠️ 元文档，不常用 |
| **NEW_SESSION_TEST.md** | 测试指南 | ⚠️ 元文档，不常用 |

### 2. 信息同步负担 ⚠️

**当前需要同步更新的文档**:
- DASHBOARD.md ← 项目状态变化时
- STATUS.md ← 项目状态变化时
- BACKLOG.md ← 每天完成任务时
- TODO.md ← 功能完成时
- feature-catalog.md ← 功能上线时

**问题**: 一个状态变化可能需要更新 3-5 个文档

### 3. 文档衰退风险 🔴

**高风险文档** (容易过期):
- PROJECT_REVIEW_REPORT.md - 快照报告，一周后就不准确
- CODE_QUALITY_FIXES.md - 修复记录，完成后不再更新
- ACTION_ITEMS.md - 行动清单，快速过期
- STATUS.md - 详细状态，维护成本高

**中风险文档** (可能不同步):
- DASHBOARD.md - 需要每周更新
- BACKLOG.md - 需要每天更新

### 4. 文档发现困难 ⚠️

**问题**: 
- 根目录 9 个 .md 文件，哪个先看？
- docs/ 目录 18 个文件，容易迷失
- 没有清晰的文档生命周期

---

## 💊 瘦身方案

### 方案 A: 激进瘦身（推荐）⭐

**立即归档** (移到 `docs/archive/reviews/2026-06-09/`):
```bash
- PROJECT_REVIEW_REPORT.md      # 快照报告
- CODE_QUALITY_FIXES.md         # 一次性记录
- ACTION_ITEMS.md               # 与 BACKLOG 重复
- PROJECT_STATUS_SYSTEM.md      # 元文档
- NEW_SESSION_TEST.md           # 元文档
```

**保留并整合**:
```bash
- DASHBOARD.md        ← 保留（快速导航核心）
- STATUS.md           ← 简化并合并部分到 DASHBOARD
- BACKLOG.md          ← 保留（工作清单核心）
- 其他已有文档       ← 不变
```

**预期效果**:
- 根目录从 9 个减少到 **5 个核心文档**
- 信息同步点从 5 个减少到 **2 个**（DASHBOARD + BACKLOG）
- 维护成本降低 60%

---

### 方案 B: 温和瘦身

**移到 docs/reviews/**:
```bash
- PROJECT_REVIEW_REPORT.md      # 归档但保留引用
- CODE_QUALITY_FIXES.md         
```

**合并**:
```bash
ACTION_ITEMS.md → 合并到 BACKLOG.md 开头
PROJECT_STATUS_SYSTEM.md → 合并到 docs/README.md
NEW_SESSION_TEST.md → 合并到 PROJECT_STATUS_SYSTEM.md
```

**保留**:
```bash
- DASHBOARD.md
- STATUS.md
- BACKLOG.md
```

**预期效果**:
- 根目录从 9 个减少到 **7 个**
- 中等维护成本

---

### 方案 C: 最小瘦身（如果你喜欢详细文档）

**仅归档快照报告**:
```bash
mkdir -p docs/archive/reviews/2026-06-09
mv PROJECT_REVIEW_REPORT.md docs/archive/reviews/2026-06-09/
mv CODE_QUALITY_FIXES.md docs/archive/reviews/2026-06-09/
```

**其他全部保留**

---

## 🛡️ 防止文档腐败的方案

### 1. 建立文档生命周期 ⭐

```markdown
## 文档分类与生命周期

### Tier 1: 活跃文档（每天/每周更新）
- DASHBOARD.md - 每周更新
- docs/BACKLOG.md - 每天更新
- docs/TODO.md - 功能完成时更新

**防腐措施**: 
- 文件顶部标注"最后更新日期"
- Claude 完成任务时自动更新
- 每周一检查一次

### Tier 2: 稳定文档（偶尔更新）
- README.md
- docs/architecture.md
- docs/feature-catalog.md
- docs/development.md
- docs/runbook.md
- docs/testing-strategy.md

**防腐措施**: 
- 架构变更时同步更新
- 每月审查一次
- 在文档中引用代码位置（可验证）

### Tier 3: 元文档（设置后很少变）
- DESIGN.md
- AGENTS.md
- docs/PROJECT_STATUS_SYSTEM.md

**防腐措施**: 
- 体系变更时更新
- 每季度审查一次

### Tier 4: 快照文档（一次性，会过期）
- docs/archive/reviews/YYYY-MM-DD/*.md

**防腐措施**: 
- 创建时标注日期和有效期
- 过期后自动归档
- 不要引用作为"当前状态"
```

---

### 2. 强制更新触发器 ⭐

**在 CLAUDE.md 中添加**:

```markdown
## 文档同步要求

完成以下操作时，**必须**同步更新文档：

1. **完成任务** → 更新 `docs/BACKLOG.md` 标记 `[x]` + 日期
2. **功能上线** → 更新 `docs/TODO.md` 和 `docs/feature-catalog.md`
3. **架构变更** → 更新 `docs/architecture.md`
4. **API 变更** → 更新 `docs/api-test-matrix.md`
5. **每周末** → 更新 `DASHBOARD.md` 状态

**不要**在文档过期时继续引用它作为"当前状态"。
```

---

### 3. 单一真相源（SSOT）原则 ⭐

**问题**: 同一信息出现在多个文档

**解决方案**: 建立引用关系

```markdown
## 信息所有权

| 信息类型 | 主文档 | 可引用 |
|---------|--------|--------|
| 项目健康度 | DASHBOARD.md | STATUS.md 引用 |
| 本周任务 | BACKLOG.md | DASHBOARD.md 汇总 |
| 功能状态 | TODO.md | feature-catalog.md 详细 |
| 架构设计 | architecture.md | 其他引用 |

**原则**: 
- 每个事实只在一个地方维护
- 其他地方只做汇总或引用
- 引用时标注来源
```

---

### 4. 自动化检测 ⚠️

**创建文档健康检查脚本**:

```bash
#!/bin/bash
# scripts/check-docs.sh

echo "📚 文档健康检查"

# 检查更新日期
echo "检查过期文档..."
find . -name "*.md" -mtime +30 -not -path "*/archive/*" \
  -not -path "*/node_modules/*" | while read f; do
  echo "⚠️  $f 超过 30 天未更新"
done

# 检查断链
echo "检查断链..."
grep -r "\[.*\](.*\.md)" --include="*.md" . | \
  grep -v "http" | while IFS=: read file link; do
  # 简单的断链检查
  echo "Checking: $file -> $link"
done

# 检查待办标记
echo "检查待办任务..."
grep -r "TODO\|FIXME\|XXX" --include="*.md" docs/ | wc -l

echo "✅ 检查完成"
```

---

### 5. 月度审查流程 📅

**每月第一周执行**:

```markdown
## 月度文档审查清单

- [ ] 检查 DASHBOARD.md 是否准确
- [ ] 归档已完成的 BACKLOG 任务
- [ ] 审查 architecture.md 是否同步代码
- [ ] 检查 feature-catalog.md 是否更新
- [ ] 归档过期的快照文档
- [ ] 运行 scripts/check-docs.sh
- [ ] 更新 docs/README.md 索引（如有新增）
```

---

## 🎯 推荐行动方案

### 立即执行（今天）

**1. 归档快照文档** (5 分钟)

```bash
mkdir -p docs/archive/reviews/2026-06-09
mv PROJECT_REVIEW_REPORT.md docs/archive/reviews/2026-06-09/
mv CODE_QUALITY_FIXES.md docs/archive/reviews/2026-06-09/
mv ACTION_ITEMS.md docs/archive/reviews/2026-06-09/
```

**2. 简化 STATUS.md** (10 分钟)
- 移除与 DASHBOARD 重复的部分
- 只保留"详细"信息（Git 状态、快速命令）

**3. 在 DASHBOARD.md 顶部添加有效期**

```markdown
> **最后更新**: 2026-06-09  
> **有效期**: 7 天（过期后请更新）
```

---

### 本周内（2-3 天）

**4. 更新 CLAUDE.md** (5 分钟)
- 添加文档同步要求
- 添加单一真相源原则

**5. 创建文档检查脚本** (30 分钟)
- `scripts/check-docs.sh`
- 加入到 CI（可选）

**6. 更新 docs/README.md** (10 分钟)
- 添加新文档的索引
- 明确生命周期分类

---

### 长期维护

**7. 建立月度审查习惯**
- 每月第一周审查一次
- 归档过期文档
- 更新活跃文档

**8. 强化自动化**
- Git pre-commit hook 检查文档更新
- CI 检查文档断链
- 定期生成文档健康报告

---

## 📊 预期效果

### 激进瘦身（方案 A）

| 指标 | 现在 | 瘦身后 | 改善 |
|------|------|--------|------|
| 根目录文档数 | 9 | 5 | -44% |
| 需同步文档数 | 5 | 2 | -60% |
| 每周维护时间 | 15 分钟 | 5 分钟 | -67% |
| 文档发现时间 | 5 分钟 | 1 分钟 | -80% |

### 温和瘦身（方案 B）

| 指标 | 现在 | 瘦身后 | 改善 |
|------|------|--------|------|
| 根目录文档数 | 9 | 7 | -22% |
| 需同步文档数 | 5 | 3 | -40% |
| 每周维护时间 | 15 分钟 | 10 分钟 | -33% |

---

## 🎯 我的建议

**推荐方案 A（激进瘦身） + 防腐措施**

**原因**:
1. 你是单人项目，文档越少越好
2. DASHBOARD + BACKLOG 足够日常使用
3. 详细报告归档保留，需要时可查
4. 降低维护负担，提高可持续性

**核心原则**:
- **少即是多** - 只保留经常用的
- **单一真相源** - 一个事实一个地方
- **自动触发** - 完成任务自动更新
- **定期清理** - 每月归档过期文档

---

需要我帮你执行激进瘦身方案吗？
