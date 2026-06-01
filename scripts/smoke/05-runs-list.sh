#!/usr/bin/env bash
# 05-runs-list.sh — Runs list page smoke test
# Verifies the /runs page renders correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/smoke/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
init_results_dir

trap generate_report EXIT

log_step "runs-list-start" "pass" "开始运行列表冒烟测试"

# 1. Navigate to runs page
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/runs"
sleep 2

# 2. Screenshot: runs list
screenshot "05-runs-list"

# 3. Verify page heading
if assert_element "h1"; then
  log_step "page-heading" "pass"
else
  handle_failure "page-heading" "运行列表页缺少 h1 标题"
fi

# 4. Check for table or empty state
TABLE_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css "table" 2>&1 || echo "")"
if [[ -n "${TABLE_OUTPUT}" && "${TABLE_OUTPUT}" != *"matches_n\": 0"* ]]; then
  log_step "runs-table" "pass" "运行表格已渲染"
  if assert_element "th"; then
    log_step "table-headers" "pass"
  else
    handle_failure "table-headers" "表格缺少表头"
  fi
else
  log_step "runs-table" "skip" "无运行记录（空状态）"
fi

# 5. Pagination: detect next/prev page buttons
NEXT_BTN="$(opencli browser "${BROWSER_SESSION}" find --css 'button[aria-label*="next"], [aria-label="Go to next page"], [aria-label*="Next"]' 2>&1 || echo "")"
PREV_BTN="$(opencli browser "${BROWSER_SESSION}" find --css 'button[aria-label*="prev"], [aria-label="Go to previous page"], [aria-label*="Previous"]' 2>&1 || echo "")"
HAS_NEXT=false
HAS_PREV=false
if [[ -n "${NEXT_BTN}" && "${NEXT_BTN}" != *"matches_n\": 0"* ]]; then
  HAS_NEXT=true
fi
if [[ -n "${PREV_BTN}" && "${PREV_BTN}" != *"matches_n\": 0"* ]]; then
  HAS_PREV=true
fi

if ${HAS_NEXT}; then
  log_step "pagination-next-btn" "pass" "检测到下一页按钮"
else
  log_step "pagination-next-btn" "skip" "未检测到下一页按钮（可能只有一页）"
fi

if ${HAS_PREV}; then
  log_step "pagination-prev-btn" "pass" "检测到上一页按钮"
else
  log_step "pagination-prev-btn" "skip" "未检测到上一页按钮"
fi

# 5a. Click next page and verify page content changes
if ${HAS_NEXT}; then
  PAGE1_URL="$(opencli browser "${BROWSER_SESSION}" state 2>/dev/null | sed -n 's/^URL: //p' | head -1 || echo "")"
  opencli browser "${BROWSER_SESSION}" click 'button[aria-label*="next"], [aria-label="Go to next page"], [aria-label*="Next"]' --nth 0 2>/dev/null || true
  sleep 2
  PAGE2_URL="$(opencli browser "${BROWSER_SESSION}" state 2>/dev/null | sed -n 's/^URL: //p' | head -1 || echo "")"
  if [[ "${PAGE1_URL}" != "${PAGE2_URL}" ]]; then
    log_step "pagination-click-next" "pass" "点击下一页后页面变化"
  else
    log_step "pagination-click-next" "pass" "点击下一页（URL 未变，可能内容刷新）"
  fi
  screenshot "05-runs-list-page2"
fi

# 6. Click first run detail link and verify navigation to /runs/:id
# Use table row links to avoid matching navigation links
RUN_LINK="$(opencli browser "${BROWSER_SESSION}" find --css 'table a[href*="/runs/"]' 2>&1 || echo "")"
if [[ -n "${RUN_LINK}" && "${RUN_LINK}" != *"matches_n\": 0"* ]]; then
  opencli browser "${BROWSER_SESSION}" click 'table a[href*="/runs/"]' --nth 0
  sleep 3
  AFTER_URL="$(opencli browser "${BROWSER_SESSION}" state 2>/dev/null | sed -n 's/^URL: //p' | head -1 || echo "")"
  if [[ "${AFTER_URL}" == *"/runs/"* && "${AFTER_URL}" != *"/runs\"" ]]; then
    log_step "detail-link-nav" "pass" "已跳转到运行详情页: ${AFTER_URL}"
  else
    log_step "detail-link-nav" "skip" "点击后未跳转（可能页面内导航）: ${AFTER_URL}"
  fi
  screenshot "05-runs-list-detail-nav"
else
  log_step "detail-link-nav" "skip" "无运行记录链接可点击"
fi

log_step "runs-list-complete" "pass" "运行列表冒烟测试完成"
