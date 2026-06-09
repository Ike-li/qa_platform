# Doc Health Skill 设计文档

**版本**: v0.1.0-alpha  
**创建日期**: 2026-06-09  
**目标**: 为 Claude Code 创建可复用的文档健康检查 Skill

---

## 🎯 产品定位

### 一句话描述
让文档像代码一样可测试、可维护的 Claude Code Skill。

### 目标用户
1. **个人开发者** - 管理个人项目文档
2. **AI 辅助开发团队** - 维护 CLAUDE.md 和项目文档
3. **技术写作团队** - 需要自动化质量检查

### 解决的问题
- ❌ 文档断链无人发现，用户点击 404
- ❌ 文档过期但继续被引用为"当前状态"
- ❌ 代码重构后文档未更新
- ❌ 多处维护同一信息导致不一致
- ❌ 新成员不知道从哪个文档开始看

---

## 🛠️ 功能设计

### 核心命令

```bash
/doc-health check           # 运行所有检查
/doc-health check --links   # 只检查断链
/doc-health check --fresh   # 只检查新鲜度
/doc-health fix             # 自动修复可修复的问题
/doc-health init            # 初始化文档配置
/doc-health report          # 生成健康度报告
```

### 检查项矩阵

| 检查项 | 优先级 | 可自动修复 | 实现复杂度 |
|--------|--------|-----------|-----------|
| **断链检测** | P0 | ❌ | 低 |
| **关键文档存在性** | P0 | ⚠️ 部分 | 低 |
| **日期标记验证** | P1 | ✅ | 低 |
| **文档新鲜度** | P1 | ❌ | 中 |
| **代码引用验证** | P1 | ⚠️ 部分 | 中 |
| **版本号一致性** | P2 | ❌ | 中 |
| **CLAUDE.md 漂移** | P2 | ❌ | 高 |
| **术语一致性** | P2 | ❌ | 高 |

---

## 📐 技术架构

### 目录结构

```
~/.claude/skills/doc-health/
├── __init__.py                 # Skill 入口
├── config.yaml                 # 默认配置
├── README.md                   # 使用文档
├── core/
│   ├── checker.py              # 检查引擎
│   ├── fixer.py                # 自动修复引擎
│   └── reporter.py             # 报告生成器
├── checks/
│   ├── __init__.py
│   ├── links.py                # 断链检测
│   ├── freshness.py            # 新鲜度检查
│   ├── existence.py            # 文档存在性
│   ├── references.py           # 代码引用验证
│   ├── consistency.py          # 版本一致性
│   └── claude_md.py            # CLAUDE.md 专项检查
├── fixes/
│   ├── __init__.py
│   ├── date_marker.py          # 日期标记修复
│   ├── broken_links.py         # 断链修复建议
│   └── templates.py            # 文档模板
└── templates/
    ├── doc-health.yaml         # 项目配置模板
    ├── DASHBOARD.md.template   # 仪表盘模板
    └── CHANGELOG.md.template   # 变更记录模板
```

### 配置文件设计

```yaml
# .doc-health.yaml
version: 1

# 检查配置
checks:
  links:
    enabled: true
    exclude_patterns:
      - "node_modules/**"
      - ".venv/**"
    
  freshness:
    enabled: true
    max_age_days: 30
    exclude:
      - "archive/**"
      - "CHANGELOG.md"
    
  existence:
    enabled: true
    required_files:
      - README.md
      - CHANGELOG.md
      - docs/architecture.md
    
  references:
    enabled: true
    check_code_paths: true
    check_functions: false  # 需要 LSP 支持，默认关闭
    
  consistency:
    enabled: true
    version_sources:
      - package.json
      - pyproject.toml
      - go.mod

# 自动修复配置
fixes:
  date_markers:
    enabled: true
    format: "YYYY-MM-DD"
    field: "最后更新"
  
  broken_links:
    suggest_only: true  # 只建议，不自动修复

# 报告配置
report:
  format: markdown  # markdown | html | json
  output: docs/doc-health-report.md
  include_passed: false

# 文档层级定义
tiers:
  - name: 活跃文档
    pattern: ["DASHBOARD.md", "docs/BACKLOG.md"]
    max_age_days: 7
  
  - name: 稳定文档
    pattern: ["docs/architecture.md", "README.md"]
    max_age_days: 90
  
  - name: 归档文档
    pattern: ["docs/archive/**"]
    max_age_days: null  # 不检查

# 自定义规则
rules:
  - id: ssot-violation
    name: 单一真相源违规
    description: 检测多个文档维护相同信息
    enabled: false  # 实验性功能
```

---

## 🔧 实现细节

### 1. 断链检测

```python
# checks/links.py
import re
from pathlib import Path
from typing import List, Tuple

class LinkChecker:
    def __init__(self, project_root: Path, config: dict):
        self.project_root = project_root
        self.config = config
        
    def check(self, file_path: Path) -> List[Tuple[str, str]]:
        """
        检查文档中的断链
        返回: [(link, reason), ...]
        """
        broken_links = []
        content = file_path.read_text(encoding='utf-8')
        
        # 匹配 [text](link) 格式
        pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        matches = re.findall(pattern, content)
        
        for text, link in matches:
            # 跳过外部链接
            if link.startswith(('http://', 'https://', '#')):
                continue
            
            # 移除锚点
            clean_link = link.split('#')[0]
            if not clean_link:
                continue
            
            # 计算目标路径
            target = self._resolve_path(file_path, clean_link)
            
            if not target.exists():
                broken_links.append((link, f"目标不存在: {target}"))
        
        return broken_links
    
    def _resolve_path(self, source: Path, link: str) -> Path:
        """解析相对路径"""
        if link.startswith('/'):
            return self.project_root / link[1:]
        else:
            return (source.parent / link).resolve()
```

### 2. 新鲜度检查

```python
# checks/freshness.py
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
from typing import Optional

class FreshnessChecker:
    def __init__(self, project_root: Path, config: dict):
        self.project_root = project_root
        self.max_age_days = config.get('max_age_days', 30)
        
    def check(self, file_path: Path) -> Optional[dict]:
        """
        检查文档新鲜度
        返回: None (正常) 或 {"age_days": int, "last_modified": str}
        """
        # 1. 检查文档中的日期标记
        date_marker = self._extract_date_marker(file_path)
        if date_marker:
            age_days = (datetime.now() - date_marker).days
            if age_days > self.max_age_days:
                return {
                    "age_days": age_days,
                    "last_modified": date_marker.strftime("%Y-%m-%d"),
                    "source": "date_marker"
                }
        
        # 2. 检查 Git 最后修改时间
        git_date = self._get_git_last_modified(file_path)
        if git_date:
            age_days = (datetime.now() - git_date).days
            if age_days > self.max_age_days:
                return {
                    "age_days": age_days,
                    "last_modified": git_date.strftime("%Y-%m-%d"),
                    "source": "git"
                }
        
        return None
    
    def _extract_date_marker(self, file_path: Path) -> Optional[datetime]:
        """从文档 frontmatter 或内容中提取日期"""
        content = file_path.read_text(encoding='utf-8')
        
        # 匹配常见日期格式
        patterns = [
            r'最后更新[：:]\s*(\d{4}-\d{2}-\d{2})',
            r'Last updated[：:]\s*(\d{4}-\d{2}-\d{2})',
            r'date[：:]\s*(\d{4}-\d{2}-\d{2})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                date_str = match.group(1)
                return datetime.strptime(date_str, "%Y-%m-%d")
        
        return None
    
    def _get_git_last_modified(self, file_path: Path) -> Optional[datetime]:
        """获取文件 Git 最后修改时间"""
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%ci', str(file_path)],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                date_str = result.stdout.strip().split()[0]
                return datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            pass
        
        return None
```

### 3. 自动修复引擎

```python
# fixes/date_marker.py
from datetime import datetime
from pathlib import Path
import re

class DateMarkerFixer:
    def __init__(self, config: dict):
        self.date_format = config.get('format', 'YYYY-MM-DD')
        self.field = config.get('field', '最后更新')
        
    def fix(self, file_path: Path) -> bool:
        """更新文档日期标记"""
        content = file_path.read_text(encoding='utf-8')
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 匹配并替换日期
        patterns = [
            (rf'({self.field}[：:]\s*)\d{{4}}-\d{{2}}-\d{{2}}', rf'\g<1>{today}'),
            (rf'(Last updated[：:]\s*)\d{{4}}-\d{{2}}-\d{{2}}', rf'\g<1>{today}'),
        ]
        
        modified = False
        for pattern, replacement in patterns:
            new_content, count = re.subn(pattern, replacement, content)
            if count > 0:
                content = new_content
                modified = True
        
        # 如果没有日期标记，在文档开头添加
        if not modified:
            # 检查是否有 frontmatter
            if content.startswith('---\n'):
                # YAML frontmatter
                parts = content.split('---\n', 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    if 'date:' not in frontmatter and '最后更新:' not in frontmatter:
                        frontmatter += f'\ndate: {today}\n'
                        content = f'---\n{frontmatter}---\n{parts[2]}'
                        modified = True
            else:
                # 在标题后添加
                lines = content.split('\n')
                if lines[0].startswith('#'):
                    lines.insert(1, f'\n> **最后更新**: {today}')
                    content = '\n'.join(lines)
                    modified = True
        
        if modified:
            file_path.write_text(content, encoding='utf-8')
            return True
        
        return False
```

### 4. 报告生成器

```python
# core/reporter.py
from pathlib import Path
from datetime import datetime
from typing import Dict, List

class Reporter:
    def __init__(self, config: dict):
        self.config = config
        self.format = config.get('format', 'markdown')
        
    def generate(self, results: Dict[str, List]) -> str:
        """生成健康度报告"""
        if self.format == 'markdown':
            return self._generate_markdown(results)
        elif self.format == 'json':
            return self._generate_json(results)
        else:
            raise ValueError(f"不支持的格式: {self.format}")
    
    def _generate_markdown(self, results: Dict[str, List]) -> str:
        """生成 Markdown 报告"""
        lines = [
            "# 文档健康度报告",
            "",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
        ]
        
        # 计算健康度分数
        total_issues = sum(len(issues) for issues in results.values())
        health_score = max(0, 100 - total_issues * 2)
        
        lines.extend([
            "## 📊 健康度总览",
            "",
            f"**总分**: {health_score}/100",
            "",
            "| 检查项 | 问题数 | 状态 |",
            "|--------|--------|------|",
        ])
        
        for check_name, issues in results.items():
            issue_count = len(issues)
            status = "✅" if issue_count == 0 else "❌"
            lines.append(f"| {check_name} | {issue_count} | {status} |")
        
        lines.extend(["", "---", ""])
        
        # 详细问题列表
        for check_name, issues in results.items():
            if not issues:
                continue
            
            lines.extend([
                f"## {check_name}",
                "",
            ])
            
            for issue in issues:
                lines.append(f"- **{issue['file']}**: {issue['message']}")
            
            lines.append("")
        
        return '\n'.join(lines)
```

---

## 🎨 用户交互设计

### 命令行输出

```bash
$ /doc-health check

📚 运行文档健康检查...

1️⃣ 检查断链...
   ✅ 没有断链 (检查了 156 个链接)

2️⃣ 检查新鲜度...
   ⚠️ 发现 3 个过期文档:
   - docs/api-guide.md (已过期 45 天)
   - docs/deployment.md (已过期 60 天)
   - README.md (已过期 15 天)

3️⃣ 检查关键文档...
   ✅ 所有关键文档存在

4️⃣ 检查代码引用...
   ❌ 发现 2 个失效引用:
   - docs/architecture.md:15 引用 src/old_module.py (文件不存在)
   - README.md:42 引用 config/settings.yaml (文件不存在)

📊 健康度总分: 76/100

💡 建议:
1. 运行 /doc-health fix 自动更新日期标记
2. 检查并修复失效的代码引用
3. 考虑归档超过 60 天未更新的文档

详细报告已保存: docs/doc-health-report.md
```

### 对话式交互

```
用户: /doc-health check

Claude: 我发现了一些文档健康问题：

🔴 **严重问题** (2 个):
- docs/architecture.md 引用了不存在的文件 src/old_module.py
- README.md 中的安装步骤链接已失效

⚠️ **警告** (3 个):
- docs/api-guide.md 已 45 天未更新
- docs/deployment.md 已 60 天未更新  
- README.md 已 15 天未更新

✅ **良好** (5 项检查通过)

**健康度分数**: 76/100

需要我帮你修复这些问题吗？我可以：
1. 自动更新所有过期文档的日期标记
2. 生成断链修复建议
3. 标记需要归档的文档

请告诉我要执行哪些操作。
```

---

## 🚀 实施计划

### Phase 1: MVP (1 周)

**目标**: 实现核心检查功能

- [x] 项目初始化和目录结构
- [ ] 实现断链检测
- [ ] 实现新鲜度检查
- [ ] 实现关键文档存在性检查
- [ ] 实现日期标记自动修复
- [ ] 生成 Markdown 报告
- [ ] 在本项目测试

### Phase 2: 增强 (1 周)

**目标**: 添加高级功能

- [ ] 实现代码引用验证
- [ ] 实现版本号一致性检查
- [ ] 支持自定义配置文件
- [ ] 添加 HTML 报告格式
- [ ] 改进错误消息和修复建议

### Phase 3: 打磨 (3 天)

**目标**: 准备开源分享

- [ ] 编写完整文档
- [ ] 添加使用示例
- [ ] 创建测试套件
- [ ] 优化性能
- [ ] 发布到 Claude Skill 市场

---

## 📝 使用文档

### 安装

```bash
# 克隆到 Claude 技能目录
cd ~/.claude/skills
git clone https://github.com/raylee/doc-health.git

# 或者通过 Claude Skill 市场安装
/skill install doc-health
```

### 快速开始

```bash
# 1. 初始化配置
/doc-health init

# 2. 运行检查
/doc-health check

# 3. 自动修复
/doc-health fix

# 4. 生成报告
/doc-health report
```

### 配置示例

```yaml
# .doc-health.yaml
version: 1

checks:
  links:
    enabled: true
  freshness:
    enabled: true
    max_age_days: 30
  existence:
    enabled: true
    required_files:
      - README.md
      - CHANGELOG.md

fixes:
  date_markers:
    enabled: true
```

---

## 🎯 成功指标

### 技术指标
- 检查速度 < 10 秒（100 个文档）
- 误报率 < 5%
- 自动修复成功率 > 90%

### 用户指标
- 安装数 > 100（前 3 个月）
- 周活跃项目 > 20
- GitHub Stars > 50

### 影响指标
- 用户报告文档维护时间减少 > 50%
- 用户报告断链问题减少 > 80%

---

## 📚 参考实现

基于以下工具的最佳实践：
- [docs-health-action](https://github.com/joaquimscosta/docs-health-action)
- [dotmd](https://github.com/reowens/dotmd)
- [contextlint](https://github.com/nozomi-koborinai/contextlint)

---

**状态**: 设计阶段  
**下一步**: 开始 Phase 1 MVP 开发
