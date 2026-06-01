#!/usr/bin/env bash
# 冒烟测试运行器 — 依次执行所有 smoke 脚本
# 用法: ./scripts/smoke/run-all.sh
# 环境变量: BASE_URL, BROWSER_SESSION, RESULTS_DIR, SMOKE_ALLOW_SKIPS,
#           SMOKE_ADMIN_USERNAME, SMOKE_ADMIN_PASSWORD, E2E_ADMIN_PASSWORD

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/smoke/lib/common.sh
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
  script_results_dir="${RESULTS_DIR}/${script%.sh}"
  if RESULTS_DIR="${script_results_dir}" bash "${script_path}"; then
    log_step "${script}" "pass"
  else
    log_step "${script}" "fail" "退出码: $?"
    # 失败但继续执行下一个脚本
  fi
done

# ── 生成报告 ──────────────────────────────────────────────

if generate_report; then
  report_exit=0
else
  report_exit=$?
fi

echo ""
echo "冒烟测试完成。产物目录:"
echo "  ${RESULTS_DIR}"
echo "子脚本产物目录:"
echo "  ${RESULTS_DIR}/<script-name>/"

exit ${report_exit}
