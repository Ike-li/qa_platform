#!/usr/bin/env bash
# 冒烟测试运行器 — 依次执行所有 smoke 脚本
# 用法: ./scripts/smoke/run-all.sh
# 环境变量: BASE_URL, BROWSER_SESSION, RESULTS_DIR

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

init_results_dir

# ── 脚本列表（按顺序执行）─────────────────────────────────

SCRIPTS=(
  "00-setup.sh"
  "01-browser-bridge.sh"
  "02-login-smoke.sh"
  "03-projects-list.sh"
  "04-project-detail.sh"
  "05-runs-list.sh"
  "06-run-detail.sh"
  "07-settings.sh"
)

# ── 依次执行 ──────────────────────────────────────────────

for script in "${SCRIPTS[@]}"; do
  script_path="${SCRIPT_DIR}/${script}"

  if [[ ! -f "${script_path}" ]]; then
    log_step "${script}" "skip" "文件不存在"
    continue
  fi

  echo ""
  echo ">>> 执行 ${script}"
  if bash "${script_path}"; then
    log_step "${script}" "pass"
  else
    log_step "${script}" "fail" "退出码: $?"
    # 失败但继续执行下一个脚本
  fi
done

# ── 生成报告 ──────────────────────────────────────────────

generate_report
report_exit=$?

echo ""
echo "冒烟测试完成。产物目录:"
echo "  ${RESULTS_DIR}"

exit ${report_exit}
