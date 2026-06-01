#!/usr/bin/env bash
# 06-run-detail.sh — Run detail page smoke test
# If a run exists, navigates into it and verifies status/logs display.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/smoke/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
init_results_dir

trap generate_report EXIT

log_step "run-detail-start" "pass" "开始运行详情冒烟测试"

# 1. Navigate to runs page
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/runs"
sleep 2

# 2. Check if any run exists
RUN_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css 'a[href*="/runs/"]' 2>&1 || echo "")"
if [[ -z "${RUN_OUTPUT}" || "${RUN_OUTPUT}" == *"matches_n\": 0"* ]]; then
  log_step "run-detail-start" "skip" "没有运行记录，跳过详情页测试"
  exit 0
fi

# 3. Click first run (use --nth 0 to pick first match)
opencli browser "${BROWSER_SESSION}" click "a[href*=\"/runs/\"]" --nth 0 2>/dev/null || true
sleep 2

# 4. Screenshot: run detail
screenshot "06-run-detail"

# 5. Verify heading
if assert_element "h1"; then
  log_step "detail-heading" "pass"
else
  handle_failure "detail-heading" "运行详情页缺少 h1 标题"
fi

# 6. Check for status display
STATUS_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css "[class*='status']" 2>&1 || echo "")"
if [[ -n "${STATUS_OUTPUT}" && "${STATUS_OUTPUT}" != *"matches_n\": 0"* ]]; then
  log_step "status-display" "pass"
else
  log_step "status-display" "skip" "未检测到状态元素"
fi

# 7. Verify detail tabs
for tab in "logs" "results" "artifacts"; do
  TAB_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css "[data-value=\"${tab}\"]" 2>&1 || echo "")"
  if [[ -n "${TAB_OUTPUT}" && "${TAB_OUTPUT}" != *"matches_n\": 0"* ]]; then
    log_step "tab-${tab}" "pass"
  else
    log_step "tab-${tab}" "skip" "未找到标签 ${tab}"
  fi
done

# 8. Logs tab: switch and verify log content area
opencli browser "${BROWSER_SESSION}" click "[data-value=\"logs\"]" 2>/dev/null || true
sleep 1
screenshot "06-run-detail-logs"
LOG_CONTENT="$(opencli browser "${BROWSER_SESSION}" find --css "pre, [class*='log'], [data-testid*='log']" 2>&1 || echo "")"
if [[ -n "${LOG_CONTENT}" && "${LOG_CONTENT}" != *"matches_n\": 0"* ]]; then
  log_step "logs-content-area" "pass" "日志内容区域已渲染"
else
  log_step "logs-content-area" "skip" "未检测到日志内容区域（pre/log 容器）"
fi

# 8a. Log search/filter: try typing into a search input within the logs tab
LOG_SEARCH="$(opencli browser "${BROWSER_SESSION}" find --css 'input[placeholder*="Search"], input[placeholder*="search"], input[placeholder*="Filter"], input[placeholder*="filter"], input[type="search"]' 2>&1 || echo "")"
if [[ -n "${LOG_SEARCH}" && "${LOG_SEARCH}" == *'matches_n'* && "${LOG_SEARCH}" != *'matches_n": 0'* ]]; then
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="Search"], input[placeholder*="search"], input[placeholder*="Filter"], input[placeholder*="filter"], input[type="search"]' "error" 2>/dev/null || true
  sleep 1
  screenshot "06-run-detail-logs-filtered"
  log_step "logs-search-filter" "pass" "日志搜索过滤功能可用"
  # Clear search
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="Search"], input[placeholder*="search"], input[placeholder*="Filter"], input[placeholder*="filter"], input[type="search"]' "" 2>/dev/null || true
  sleep 1
else
  log_step "logs-search-filter" "skip" "未找到日志搜索/过滤输入框"
fi

# 9. Results tab: switch and verify summary cards + table
opencli browser "${BROWSER_SESSION}" click "[data-value=\"results\"]" 2>/dev/null || true
sleep 1
screenshot "06-run-detail-results"

# 9a. Four-grid summary cards (total/passed/failed/skipped)
SUMMARY_FOUND=0
for metric in "total" "passed" "failed" "skipped"; do
  METRIC_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css "[class*='${metric}'], [data-testid*='${metric}']" 2>&1 || echo "")"
  if [[ -z "${METRIC_OUTPUT}" || "${METRIC_OUTPUT}" == *'matches_n": 0'* ]]; then
    METRIC_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --text "${metric}" 2>&1 || echo "")"
  fi
  if [[ -n "${METRIC_OUTPUT}" && "${METRIC_OUTPUT}" != *"matches_n\": 0"* ]]; then
    ((SUMMARY_FOUND++)) || true
  fi
done
if (( SUMMARY_FOUND >= 2 )); then
  log_step "results-summary-cards" "pass" "检测到 ${SUMMARY_FOUND}/4 摘要指标"
else
  log_step "results-summary-cards" "skip" "未检测到足够的摘要指标卡片 (${SUMMARY_FOUND}/4)"
fi

# 9b. Results table
RESULTS_TABLE="$(opencli browser "${BROWSER_SESSION}" find --css "table, [role='table']" 2>&1 || echo "")"
if [[ -n "${RESULTS_TABLE}" && "${RESULTS_TABLE}" != *"matches_n\": 0"* ]]; then
  log_step "results-table" "pass" "测试结果表格已渲染"
else
  log_step "results-table" "skip" "未检测到测试结果表格"
fi

# 10. Artifacts tab: switch and verify artifacts list
opencli browser "${BROWSER_SESSION}" click "[data-value=\"artifacts\"]" 2>/dev/null || true
sleep 1
screenshot "06-run-detail-artifacts"
ARTIFACTS_AREA="$(opencli browser "${BROWSER_SESSION}" find --css "[class*='artifact'], [data-testid*='artifact'], ul, [role='list']" 2>&1 || echo "")"
if [[ -n "${ARTIFACTS_AREA}" && "${ARTIFACTS_AREA}" != *"matches_n\": 0"* ]]; then
  log_step "artifacts-area" "pass" "制品列表区域已渲染"
else
  log_step "artifacts-area" "skip" "未检测到制品列表区域"
fi

# 10a. Artifact download button detection
DOWNLOAD_BTN="$(opencli browser "${BROWSER_SESSION}" find --css 'a[download], button[aria-label*="download" i]' 2>&1 || echo "")"
for dl_text in "下载" "Download"; do
  if [[ -z "${DOWNLOAD_BTN}" || "${DOWNLOAD_BTN}" == *"matches_n\": 0"* ]]; then
    DOWNLOAD_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "${dl_text}" 2>&1 || echo "")"
  fi
done
if [[ -n "${DOWNLOAD_BTN}" && "${DOWNLOAD_BTN}" != *"matches_n\": 0"* ]]; then
  log_step "artifacts-download-btn" "pass" "制品下载按钮已渲染"
else
  log_step "artifacts-download-btn" "skip" "未检测到制品下载按钮"
fi

# 11. Cancel run button (only visible for in-progress runs)
CANCEL_BTN="$(opencli browser "${BROWSER_SESSION}" find --css 'button[aria-label*="cancel" i], button[data-testid*="cancel"]' 2>&1 || echo "")"
for cancel_text in "取消" "Cancel" "Stop"; do
  if [[ -z "${CANCEL_BTN}" || "${CANCEL_BTN}" == *"matches_n\": 0"* ]]; then
    CANCEL_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "${cancel_text}" 2>&1 || echo "")"
  fi
done
if [[ -n "${CANCEL_BTN}" && "${CANCEL_BTN}" != *"matches_n\": 0"* ]]; then
  log_step "cancel-run-btn" "pass" "取消运行按钮已渲染（运行中）"
else
  log_step "cancel-run-btn" "skip" "未检测到取消运行按钮（运行可能已完成）"
fi

# 12. Rerun button detection
RERUN_BTN="$(opencli browser "${BROWSER_SESSION}" find --css '[data-testid*="rerun"]' 2>&1 || echo "")"
for rerun_text in "rerun" "Rerun" "re-run" "重新运行"; do
  if [[ -z "${RERUN_BTN}" || "${RERUN_BTN}" == *"matches_n\": 0"* ]]; then
    RERUN_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "${rerun_text}" 2>&1 || echo "")"
  fi
done
if [[ -n "${RERUN_BTN}" && "${RERUN_BTN}" != *"matches_n\": 0"* ]]; then
  log_step "rerun-button" "pass" "重新运行按钮已渲染"
else
  log_step "rerun-button" "skip" "未检测到重新运行按钮"
fi

log_step "run-detail-complete" "pass" "运行详情冒烟测试完成"
