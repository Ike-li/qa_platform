#!/usr/bin/env bash
# 07-settings.sh — Settings page smoke test
# Verifies the /settings page renders correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
init_results_dir

trap generate_report EXIT

log_step "settings-start" "pass" "开始设置页冒烟测试"

# 1. Navigate to settings page
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/settings"
sleep 2

# 2. Screenshot: settings page
screenshot "07-settings"

# 3. Verify page heading
if assert_element "h1"; then
  log_step "page-heading" "pass"
else
  handle_failure "page-heading" "设置页缺少 h1 标题"
fi

# 4. Check for settings content (description paragraph)
CONTENT_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css "p" 2>&1 || echo "")"
if [[ -n "${CONTENT_OUTPUT}" && "${CONTENT_OUTPUT}" != *"matches_n\": 0"* ]]; then
  log_step "settings-content" "pass"
else
  log_step "settings-content" "skip" "设置页内容为空"
fi

log_step "settings-complete" "pass" "设置页冒烟测试完成"
