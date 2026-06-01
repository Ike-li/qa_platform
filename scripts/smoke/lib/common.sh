#!/usr/bin/env bash
# 通用工具函数 — 冒烟测试基础设施
# 所有 smoke 脚本通过 source lib/common.sh 加载

set -euo pipefail

# ── 全局变量 ──────────────────────────────────────────────

BASE_URL="${BASE_URL:-http://localhost:80}"
BROWSER_SESSION="${BROWSER_SESSION:-smoke}"
SMOKE_ALLOW_SKIPS="${SMOKE_ALLOW_SKIPS:-0}"
SMOKE_ADMIN_USERNAME="${SMOKE_ADMIN_USERNAME:-admin}"
SMOKE_ADMIN_PASSWORD="${SMOKE_ADMIN_PASSWORD:-${E2E_ADMIN_PASSWORD:-admin123}}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RESULTS_DIR="${RESULTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/tests/smoke-results/${TIMESTAMP}}"
LOG_FILE="${RESULTS_DIR}/steps.log"
REPORT_FILE="${RESULTS_DIR}/report.txt"

# 内部计数
_STEP_TOTAL=0
_STEP_PASSED=0
_STEP_FAILED=0
_STEP_SKIPPED=0

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y) return 0 ;;
    *) return 1 ;;
  esac
}

# ── 初始化 ────────────────────────────────────────────────

init_results_dir() {
  mkdir -p "${RESULTS_DIR}"
  : > "${LOG_FILE}"
  {
    echo "[$(date '+%H:%M:%S')] Smoke test run started"
    echo "[$(date '+%H:%M:%S')] BASE_URL=${BASE_URL}"
    echo "[$(date '+%H:%M:%S')] RESULTS_DIR=${RESULTS_DIR}"
  } >> "${LOG_FILE}"
}

# ── 截图 ──────────────────────────────────────────────────

screenshot() {
  local page_name="${1:?用法: screenshot <page_name>}"
  local filepath="${RESULTS_DIR}/${page_name}.png"
  opencli browser "${BROWSER_SESSION}" screenshot "${filepath}" 2>/dev/null || true
  echo "${filepath}"
}

# ── 元素断言 ──────────────────────────────────────────────

# 验证页面上存在匹配 CSS 选择器的元素
# 使用 opencli browser find --css 查找 DOM 元素
assert_element() {
  local selector="${1:?用法: assert_element <css_selector> [description]}"
  local description="${2:-元素 ${selector}}"
  local output

  output="$(opencli browser "${BROWSER_SESSION}" find --css "${selector}" 2>&1)" || true

  if [[ -z "${output}" || "${output}" == *"matches_n\": 0"* ]]; then
    return 1
  fi
  return 0
}

# ── 日志记录 ──────────────────────────────────────────────

log_step() {
  local step_name="${1:?用法: log_step <step_name> <status> [detail]}"
  local status="${2:?状态: pass|fail|skip}"
  local detail="${3:-}"
  local icon

  case "${status}" in
    pass) icon="PASS"; ((_STEP_PASSED++)) || true ;;
    fail) icon="FAIL"; ((_STEP_FAILED++)) || true ;;
    skip) icon="SKIP"; ((_STEP_SKIPPED++)) || true ;;
    *)    icon="UNKNOWN" ;;
  esac
  ((_STEP_TOTAL++)) || true

  local line
  line="[$(date '+%H:%M:%S')] [${icon}] ${step_name}"
  [[ -n "${detail}" ]] && line+=" — ${detail}"
  echo "${line}" >> "${LOG_FILE}"
  echo "${line}"
}

# ── 失败处理 ──────────────────────────────────────────────

# 失败时截图 + 记录错误，继续执行（不 exit）
handle_failure() {
  local step_name="${1:?用法: handle_failure <step_name> <error>}"
  local error="${2:-未知错误}"
  local shot

  shot="$(screenshot "fail_${step_name}")"
  log_step "${step_name}" "fail" "${error} (截图: ${shot})"
}

# ── 测试报告 ──────────────────────────────────────────────

generate_report() {
  {
    echo "=========================================="
    echo "  冒烟测试报告"
    echo "=========================================="
    echo ""
    echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "BASE_URL: ${BASE_URL}"
    echo "SMOKE_ALLOW_SKIPS: ${SMOKE_ALLOW_SKIPS}"
    echo ""
    echo "--- 汇总 ---"
    echo "总计: ${_STEP_TOTAL}"
    echo "通过: ${_STEP_PASSED}"
    echo "失败: ${_STEP_FAILED}"
    echo "跳过: ${_STEP_SKIPPED}"
    echo ""
    if (( _STEP_FAILED > 0 )); then
      echo "结果: FAIL"
    elif (( _STEP_SKIPPED > 0 )) && ! is_truthy "${SMOKE_ALLOW_SKIPS}"; then
      echo "结果: FAIL"
      echo "原因: 存在跳过步骤；如需探索性运行，请设置 SMOKE_ALLOW_SKIPS=1"
    elif (( _STEP_SKIPPED > 0 )); then
      echo "结果: PASS_WITH_SKIPS"
    else
      echo "结果: PASS"
    fi
    echo ""
    echo "--- 步骤明细 ---"
    cat "${LOG_FILE}"
    echo ""
    echo "产物目录: ${RESULTS_DIR}"
    echo "=========================================="
  } > "${REPORT_FILE}"

  echo ""
  echo "测试报告已生成: ${REPORT_FILE}"
  echo "产物目录: ${RESULTS_DIR}"

  # 返回总体结果供调用方判断。默认把 skip 当成失败，避免冒烟测试
  # 在缺少关键页面数据或元素时给出假绿。
  if (( _STEP_FAILED > 0 )); then
    return 1
  fi
  if (( _STEP_SKIPPED > 0 )) && ! is_truthy "${SMOKE_ALLOW_SKIPS}"; then
    return 1
  fi
  return 0
}
