#!/usr/bin/env bash
# 07-settings.sh — Settings page smoke test
# Verifies the /settings page renders correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/smoke/lib/common.sh
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

# 4. Check for the API token management surface.
if assert_element "main button"; then
  log_step "api-token-create-control" "pass" "令牌创建入口存在"
else
  handle_failure "api-token-create-control" "缺少 API 令牌创建入口"
fi

if assert_element "main table"; then
  log_step "api-token-table" "pass" "令牌列表表格存在"
else
  handle_failure "api-token-table" "缺少 API 令牌列表表格"
fi

log_step "settings-complete" "pass" "设置页冒烟测试完成"
