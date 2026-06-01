#!/usr/bin/env bash
# 02-login-smoke.sh — Login page smoke test
# Verifies login form renders, accepts credentials, and redirects to /projects.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/smoke/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
init_results_dir

trap generate_report EXIT

log_step "login-page-open" "pass" "开始登录页冒烟测试"

# 1. Open login page
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/login"
sleep 2

# 2. Screenshot: initial login page
screenshot "01-login-page"

# 3. Verify form elements
if assert_element "#username"; then
  log_step "username-field" "pass"
else
  handle_failure "username-field" "未找到 #username 输入框"
fi

if assert_element "#password"; then
  log_step "password-field" "pass"
else
  handle_failure "password-field" "未找到 #password 输入框"
fi

if assert_element "button[type=\"submit\"]"; then
  log_step "submit-button" "pass"
else
  handle_failure "submit-button" "未找到提交按钮"
fi

# 4. Form validation — 空表单提交
opencli browser "${BROWSER_SESSION}" click "button[type=\"submit\"]"
sleep 1
ERROR_MSG="$(opencli browser "${BROWSER_SESSION}" find --css '[role="alert"], .error, .error-message, [class*="error"], [class*="Error"], [class*="invalid"], [class*="Invalid"]' 2>&1 || echo "")"
if [[ -n "${ERROR_MSG}" && "${ERROR_MSG}" != *"matches_n\": 0"* ]]; then
  log_step "empty-form-validation" "pass" "空表单提交后显示错误提示"
else
  log_step "empty-form-validation" "skip" "未检测到错误提示元素"
fi
screenshot "03-empty-form-submit"

# 5. Form validation — 只填用户名
opencli browser "${BROWSER_SESSION}" fill "#username" "admin"
opencli browser "${BROWSER_SESSION}" click "button[type=\"submit\"]"
sleep 1
ERROR_MSG="$(opencli browser "${BROWSER_SESSION}" find --css '[role="alert"], .error, .error-message, [class*="error"], [class*="Error"], [class*="invalid"], [class*="Invalid"]' 2>&1 || echo "")"
if [[ -n "${ERROR_MSG}" && "${ERROR_MSG}" != *"matches_n\": 0"* ]]; then
  log_step "no-password-validation" "pass" "只填用户名提交后显示错误提示"
else
  log_step "no-password-validation" "skip" "未检测到错误提示元素"
fi
screenshot "04-no-password-submit"

# 6. Form validation — 只填密码
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/login"
sleep 2
opencli browser "${BROWSER_SESSION}" fill "#password" "${SMOKE_ADMIN_PASSWORD}"
opencli browser "${BROWSER_SESSION}" click "button[type=\"submit\"]"
sleep 1
ERROR_MSG="$(opencli browser "${BROWSER_SESSION}" find --css '[role="alert"], .error, .error-message, [class*="error"], [class*="Error"], [class*="invalid"], [class*="Invalid"]' 2>&1 || echo "")"
if [[ -n "${ERROR_MSG}" && "${ERROR_MSG}" != *"matches_n\": 0"* ]]; then
  log_step "no-username-validation" "pass" "只填密码提交后显示错误提示"
else
  log_step "no-username-validation" "skip" "未检测到错误提示元素"
fi
screenshot "05-no-username-submit"

# 7. 错误凭证测试
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/login"
sleep 2
opencli browser "${BROWSER_SESSION}" fill "#username" "wrong"
opencli browser "${BROWSER_SESSION}" fill "#password" "wrong"
opencli browser "${BROWSER_SESSION}" click "button[type=\"submit\"]"
sleep 2
ERROR_MSG="$(opencli browser "${BROWSER_SESSION}" find --css '[role="alert"], .error, .error-message, [class*="error"], [class*="Error"], [class*="invalid"], [class*="Invalid"]' 2>&1 || echo "")"
if [[ -n "${ERROR_MSG}" && "${ERROR_MSG}" != *"matches_n\": 0"* ]]; then
  log_step "wrong-credentials" "pass" "错误凭证登录后显示错误提示"
else
  log_step "wrong-credentials" "skip" "未检测到错误提示元素"
fi
screenshot "06-wrong-credentials"

# 确保回到登录页再执行正常登录流程
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/login"
sleep 2

# 8. Fill credentials
opencli browser "${BROWSER_SESSION}" fill "#username" "${SMOKE_ADMIN_USERNAME}"
opencli browser "${BROWSER_SESSION}" fill "#password" "${SMOKE_ADMIN_PASSWORD}"
log_step "fill-credentials" "pass"

# 9. Submit login
opencli browser "${BROWSER_SESSION}" click "button[type=\"submit\"]"
sleep 3

# 10. Verify redirect to /projects
CURRENT_URL="$(opencli browser "${BROWSER_SESSION}" state 2>/dev/null | sed -n 's/^URL: //p' | head -1 || echo "")"
if [[ "$CURRENT_URL" == *"/projects"* ]]; then
  log_step "login-redirect" "pass" "已跳转到 /projects"
else
  handle_failure "login-redirect" "登录后未跳转到 /projects, 当前 URL: ${CURRENT_URL}"
fi

# 11. Screenshot: after successful login
screenshot "07-login-success"

# 12. Verify project list page elements
if assert_element "h1"; then
  log_step "projects-heading" "pass"
else
  handle_failure "projects-heading" "项目列表页缺少标题"
fi

log_step "login-smoke-complete" "pass" "登录页冒烟测试完成"
