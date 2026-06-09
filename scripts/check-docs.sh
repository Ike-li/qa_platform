#!/bin/bash
# 文档健康检查脚本
# 检查过期文档、断链、待办标记

set -e

echo "📚 文档健康检查"
echo "================"
echo ""

# 颜色定义
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# 计数器
warnings=0
errors=0

# 1. 检查过期文档（超过 30 天未更新）
echo "1️⃣  检查过期文档（超过 30 天未更新）..."
echo "----------------------------------------"

if command -v find >/dev/null 2>&1; then
  expired_docs=$(find . -name "*.md" -mtime +30 \
    -not -path "*/archive/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/.venv/*" \
    -not -path "*/.git/*" \
    -not -path "*/.pytest_cache/*" \
    -not -path "*/.omc/*" \
    2>/dev/null || true)

  if [ -n "$expired_docs" ]; then
    echo -e "${YELLOW}⚠️  发现过期文档:${NC}"
    echo "$expired_docs" | while read -r file; do
      echo "   - $file"
      warnings=$((warnings + 1))
    done
  else
    echo -e "${GREEN}✅ 没有过期文档${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  find 命令不可用，跳过过期检查${NC}"
fi

echo ""

# 2. 检查关键文档的更新日期标记
echo "2️⃣  检查关键文档更新日期标记..."
echo "----------------------------------------"

check_date_marker() {
  local file=$1
  if [ -f "$file" ]; then
    if grep -q "最后更新.*2026-06-09" "$file" 2>/dev/null; then
      echo -e "${GREEN}✅ $file - 日期标记正确${NC}"
    else
      echo -e "${YELLOW}⚠️  $file - 缺少或过期的日期标记${NC}"
      warnings=$((warnings + 1))
    fi
  else
    echo -e "${RED}❌ $file - 文件不存在${NC}"
    errors=$((errors + 1))
  fi
}

check_date_marker "DASHBOARD.md"
check_date_marker "STATUS.md"
check_date_marker "docs/BACKLOG.md"

echo ""

# 3. 检查内部链接（简化版）
echo "3️⃣  检查内部 Markdown 链接..."
echo "----------------------------------------"

broken_links=0
checked_links=0

if command -v grep >/dev/null 2>&1; then
  # 查找所有 .md 文件中的相对链接
  find . -name "*.md" \
    -not -path "*/archive/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/.venv/*" \
    -not -path "*/.git/*" \
    2>/dev/null | while read -r file; do

    # 提取相对路径链接（排除 http 链接）
    grep -oE '\[([^\]]+)\]\(([^)]+\.md[^)]*)\)' "$file" 2>/dev/null | \
      grep -v "http" | \
      sed 's/.*(\([^)]*\)).*/\1/' | \
      sed 's/#.*//' | while read -r link; do

      checked_links=$((checked_links + 1))

      # 计算链接的绝对路径
      dir=$(dirname "$file")
      target="$dir/$link"

      if [ ! -f "$target" ]; then
        echo -e "${YELLOW}⚠️  断链: $file -> $link${NC}"
        broken_links=$((broken_links + 1))
        warnings=$((warnings + 1))
      fi
    done
  done

  if [ $broken_links -eq 0 ]; then
    echo -e "${GREEN}✅ 没有发现断链 (检查了 $checked_links 个链接)${NC}"
  else
    echo -e "${YELLOW}⚠️  发现 $broken_links 个断链${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  grep 命令不可用，跳过链接检查${NC}"
fi

echo ""

# 4. 检查文档中的 TODO/FIXME 标记
echo "4️⃣  检查文档中的待办标记..."
echo "----------------------------------------"

todo_count=0
if command -v grep >/dev/null 2>&1; then
  todo_files=$(grep -r "TODO\|FIXME\|XXX" --include="*.md" docs/ . 2>/dev/null | \
    grep -v "archive" | \
    grep -v "node_modules" | \
    grep -v ".venv" | \
    grep -v "检查文档中的待办标记" || true)

  if [ -n "$todo_files" ]; then
    todo_count=$(echo "$todo_files" | wc -l | tr -d ' ')
    echo -e "${YELLOW}⚠️  发现 $todo_count 个待办标记:${NC}"
    echo "$todo_files" | head -10 | while read -r line; do
      echo "   - $line"
    done
    if [ $todo_count -gt 10 ]; then
      echo "   ... 还有 $((todo_count - 10)) 个"
    fi
  else
    echo -e "${GREEN}✅ 没有待办标记${NC}"
  fi
fi

echo ""

# 5. 检查关键文档是否存在
echo "5️⃣  检查关键文档是否存在..."
echo "----------------------------------------"

critical_docs=(
  "README.md"
  "DASHBOARD.md"
  "STATUS.md"
  "docs/BACKLOG.md"
  "docs/TODO.md"
  "docs/architecture.md"
  "docs/README.md"
)

for doc in "${critical_docs[@]}"; do
  if [ -f "$doc" ]; then
    echo -e "${GREEN}✅ $doc${NC}"
  else
    echo -e "${RED}❌ $doc - 缺失${NC}"
    errors=$((errors + 1))
  fi
done

echo ""

# 6. 统计文档数量
echo "6️⃣  文档统计..."
echo "----------------------------------------"

total_docs=$(find . -name "*.md" \
  -not -path "*/node_modules/*" \
  -not -path "*/.venv/*" \
  -not -path "*/.git/*" \
  -not -path "*/.pytest_cache/*" \
  -not -path "*/.omc/*" \
  2>/dev/null | wc -l | tr -d ' ')

active_docs=$(find . -name "*.md" \
  -not -path "*/archive/*" \
  -not -path "*/node_modules/*" \
  -not -path "*/.venv/*" \
  -not -path "*/.git/*" \
  -not -path "*/.pytest_cache/*" \
  -not -path "*/.omc/*" \
  2>/dev/null | wc -l | tr -d ' ')

archived_docs=$((total_docs - active_docs))

echo "总文档数: $total_docs"
echo "活跃文档: $active_docs"
echo "归档文档: $archived_docs"

echo ""

# 总结
echo "📊 检查总结"
echo "================"
echo -e "警告: ${YELLOW}$warnings${NC}"
echo -e "错误: ${RED}$errors${NC}"
echo ""

if [ $errors -eq 0 ] && [ $warnings -eq 0 ]; then
  echo -e "${GREEN}🎉 文档健康状态良好！${NC}"
  exit 0
elif [ $errors -eq 0 ]; then
  echo -e "${YELLOW}⚠️  有一些警告需要注意${NC}"
  exit 0
else
  echo -e "${RED}❌ 发现错误，请修复${NC}"
  exit 1
fi
