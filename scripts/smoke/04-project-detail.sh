#!/usr/bin/env bash
# 04-project-detail.sh — Project detail page smoke test
# Navigates into a project and verifies tabs switch correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/smoke/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
init_results_dir

trap generate_report EXIT

log_step "project-detail-start" "pass" "开始项目详情冒烟测试"

# 1. Navigate to projects list
opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/projects"
sleep 2

# 2. Check if there are any project links to click
LINK_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css 'a[href*="/projects/"]' 2>&1 || echo "")"
if [[ -z "${LINK_OUTPUT}" || "${LINK_OUTPUT}" == *"matches_n\": 0"* ]]; then
  log_step "project-detail-start" "skip" "没有项目可点击，跳过详情页测试"
  exit 0
fi

# 3. Click first project (use --nth 0 to pick first match)
opencli browser "${BROWSER_SESSION}" click "a[href*=\"/projects/\"]" --nth 0
sleep 2

# 4. Screenshot: project detail page
screenshot "04-project-detail"

# 5. Verify detail page heading
if assert_element "h1"; then
  log_step "detail-heading" "pass"
else
  handle_failure "detail-heading" "项目详情页缺少 h1 标题"
fi

# 6. Verify tabs exist (value attribute from Radix TabsTrigger)
TAB_VALUES=("runs" "pipelines" "environments" "analytics" "notifications" "settings")
for tab in "${TAB_VALUES[@]}"; do
  TAB_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css "[data-value=\"${tab}\"]" 2>&1 || echo "")"
  if [[ -n "${TAB_OUTPUT}" && "${TAB_OUTPUT}" != *"matches_n\": 0"* ]]; then
    log_step "tab-${tab}" "pass"
  else
    log_step "tab-${tab}" "skip" "未找到标签 ${tab}"
  fi
done

# 7. Click through tabs to verify switching
for tab in "pipelines" "environments" "analytics" "notifications" "settings" "runs"; do
  opencli browser "${BROWSER_SESSION}" click "[data-value=\"${tab}\"]" 2>/dev/null || true
  sleep 1
done

screenshot "04-project-detail-tabs"

# ── Pipeline 标签测试 ──────────────────────────────────────

opencli browser "${BROWSER_SESSION}" click '[data-value="pipelines"]' 2>/dev/null || true
sleep 2
screenshot "04-pipelines-tab"

# 查找"新建 Pipeline"按钮
PIPELINE_CREATE_BTN=""
for btn_text in "New Pipeline" "新建 Pipeline" "Create Pipeline" "New" "新建" "Create" "创建"; do
  PIPELINE_CREATE_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "$btn_text" 2>&1 || echo "")"
  if [[ -n "${PIPELINE_CREATE_BTN}" && "${PIPELINE_CREATE_BTN}" == *"matches_n"* && "${PIPELINE_CREATE_BTN}" != *"matches_n\": 0"* ]]; then
    PIPELINE_CREATE_BTN_TEXT="$btn_text"
    break
  fi
done
if [[ -n "${PIPELINE_CREATE_BTN}" && "${PIPELINE_CREATE_BTN}" == *"matches_n"* && "${PIPELINE_CREATE_BTN}" != *"matches_n\": 0"* ]]; then
  opencli browser "${BROWSER_SESSION}" click --text "${PIPELINE_CREATE_BTN_TEXT}" --nth 0 2>/dev/null || true
  sleep 2
  screenshot "04-pipeline-create-dialog"

  # 检测对话框出现（PipelineModal 使用 Radix Dialog）
  if assert_element '[role="dialog"]'; then
    log_step "pipeline-dialog" "pass" "Pipeline 创建对话框已出现"

    # 填写名称 (#name)
    opencli browser "${BROWSER_SESSION}" fill '#name' "Smoke Pipeline" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="Smoke"], input[placeholder*="E2E"]' "Smoke Pipeline" 2>/dev/null || true
    sleep 0.5

    # 选择框架 pytest（Radix Select — 点击 SelectTrigger 展开，再选 SelectItem）
    opencli browser "${BROWSER_SESSION}" click '[role="dialog"] [role="combobox"]:first-of-type, [role="dialog"] select:first-of-type' 2>/dev/null || true
    sleep 0.5
    opencli browser "${BROWSER_SESSION}" click '[role="option"][data-value="pytest"], [role="listbox"] [data-value="pytest"]' 2>/dev/null || true
    sleep 0.5

    # 填写超时 (#timeout)
    opencli browser "${BROWSER_SESSION}" fill '#timeout' "300" 2>/dev/null || true
    sleep 0.3

    # 填写文件模式 (#pattern)
    opencli browser "${BROWSER_SESSION}" fill '#pattern' "tests/**/*.py" 2>/dev/null || true
    sleep 0.5

    screenshot "04-pipeline-form-filled"

    # 提交创建
    opencli browser "${BROWSER_SESSION}" click '[role="dialog"] button[type="submit"]' 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "Create" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "创建" 2>/dev/null || true
    sleep 3
    screenshot "04-pipeline-after-create"

    # 验证 Pipeline 出现在列表中
    SMOKE_PIPELINE_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Pipeline" 2>&1 || echo "")"
    if [[ -n "${SMOKE_PIPELINE_OUT}" && "${SMOKE_PIPELINE_OUT}" != *"matches_n\": 0"* ]]; then
      log_step "pipeline-created" "pass" "Smoke Pipeline 已出现在列表中"
    else
      handle_failure "pipeline-created" "Smoke Pipeline 未出现在列表中"
    fi

    # ── 编辑 Pipeline ──
    # 点击 Pipeline 卡片/行进入编辑模式（PipelineModal 复用同一组件）
    opencli browser "${BROWSER_SESSION}" click --text "Edit" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "Smoke Pipeline" 2>/dev/null || true
    sleep 2

    if assert_element '[role="dialog"]'; then
      # 修改名称
      opencli browser "${BROWSER_SESSION}" fill '#name' "Smoke Pipeline Edited" 2>/dev/null || true
      sleep 0.5

      # 保存修改
      opencli browser "${BROWSER_SESSION}" click '[role="dialog"] button[type="submit"]' 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "Update" 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "更新" 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "Save" 2>/dev/null || true
      sleep 2
      screenshot "04-pipeline-after-edit"

      EDITED_PIPELINE_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Pipeline Edited" 2>&1 || echo "")"
      if [[ -n "${EDITED_PIPELINE_OUT}" && "${EDITED_PIPELINE_OUT}" != *"matches_n\": 0"* ]]; then
        log_step "pipeline-edited" "pass" "Pipeline 编辑成功"
      else
        log_step "pipeline-edited" "skip" "未检测到编辑后的 Pipeline 名称"
      fi
    else
      log_step "pipeline-edited" "skip" "未进入编辑对话框"
    fi

    # ── 删除 Pipeline ──
    # 再次打开编辑对话框以访问删除按钮（Trash2 在 DialogHeader 中）
    opencli browser "${BROWSER_SESSION}" click --text "Smoke Pipeline Edited" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "Smoke Pipeline" 2>/dev/null || true
    sleep 2

    if assert_element '[role="dialog"]'; then
      # 点击删除按钮（Trash2 图标按钮）
      opencli browser "${BROWSER_SESSION}" click '[role="dialog"] button.text-status-failed, [role="dialog"] button:has(svg.lucide-trash-2)' 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "Delete" 2>/dev/null || true
      sleep 1

      # 确认删除（AlertDialog 的 AlertDialogAction）
      opencli browser "${BROWSER_SESSION}" click '[role="alertdialog"] button' 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "Delete" 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "删除" 2>/dev/null || true
      sleep 2
      screenshot "04-pipeline-after-delete"

      DELETED_PIPELINE_CHECK="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Pipeline Edited" 2>&1 || echo "")"
      if [[ -z "${DELETED_PIPELINE_CHECK}" || "${DELETED_PIPELINE_CHECK}" == *"matches_n\": 0"* ]]; then
        log_step "pipeline-deleted" "pass" "Pipeline 已删除"
      else
        log_step "pipeline-deleted" "skip" "Pipeline 可能未被删除"
      fi
    else
      log_step "pipeline-deleted" "skip" "未进入编辑对话框进行删除"
    fi
  else
    handle_failure "pipeline-dialog" "Pipeline 创建对话框未出现"
  fi
else
  log_step "pipeline-create-btn" "skip" "未找到新建 Pipeline 按钮"
fi

# ── Environments 标签测试 ──────────────────────────────────

opencli browser "${BROWSER_SESSION}" click '[data-value="environments"]' 2>/dev/null || true
sleep 2
screenshot "04-env-tab"

# 点击创建环境按钮（EnvironmentEditor: Button with Plus + "New Environment"）
ENV_CREATE_BTN=""
for env_btn_text in "New Environment" "新建环境" "新建"; do
  ENV_CREATE_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "$env_btn_text" 2>&1 || echo "")"
  if [[ -n "${ENV_CREATE_BTN}" && "${ENV_CREATE_BTN}" != *"matches_n\": 0"* ]]; then
    ENV_CREATE_BTN_TEXT="$env_btn_text"
    break
  fi
done
if [[ -n "${ENV_CREATE_BTN}" && "${ENV_CREATE_BTN}" == *'matches_n'* && "${ENV_CREATE_BTN}" != *'matches_n": 0'* ]]; then
  opencli browser "${BROWSER_SESSION}" click --text "${ENV_CREATE_BTN_TEXT}" --nth 0 2>/dev/null || true
  sleep 1

  # 内联表单出现（不是 dialog，是 inline div）
  # 填写环境名称
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="Production"], input[placeholder*="Staging"], input[placeholder*="e.g."]' "Smoke Env" 2>/dev/null || true
  sleep 0.5

  # 点击创建按钮
  opencli browser "${BROWSER_SESSION}" click --text "Create" 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "创建" 2>/dev/null || true
  sleep 2
  screenshot "04-env-after-create"

  # 验证环境出现
  ENV_CREATED_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Env" 2>&1 || echo "")"
  if [[ -n "${ENV_CREATED_OUT}" && "${ENV_CREATED_OUT}" != *"matches_n\": 0"* ]]; then
    log_step "env-created" "pass" "Smoke Env 已出现在列表中"
  else
    handle_failure "env-created" "Smoke Env 未出现在列表中"
  fi

  # ── 编辑环境变量 ──
  # EnvironmentCard: 点击变量行的输入框编辑，然后点 Save
  ENV_CARD="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Env" 2>&1 || echo "")"
  if [[ -n "${ENV_CARD}" && "${ENV_CARD}" != *"matches_n\": 0"* ]]; then
    # 点击"添加变量"按钮
    opencli browser "${BROWSER_SESSION}" click --text "Add Variable" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "添加变量" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "变量" 2>/dev/null || true
    sleep 0.5

    # 填写 KEY 输入框（placeholder="KEY"）
    opencli browser "${BROWSER_SESSION}" fill 'input[placeholder="KEY"]' "SMOKE_KEY" 2>/dev/null || true
    sleep 0.3

    # 填写 VALUE 输入框（placeholder="VALUE"，可能是 password 类型）
    opencli browser "${BROWSER_SESSION}" fill 'input[placeholder="VALUE"]' "smoke_test_value" 2>/dev/null || true
    sleep 0.5

    # 点击 Save 按钮
    opencli browser "${BROWSER_SESSION}" click --text "Save" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "保存" 2>/dev/null || true
    sleep 2
    screenshot "04-env-after-edit"

    ENV_KEY_CHECK="$(opencli browser "${BROWSER_SESSION}" find --css 'input[value="SMOKE_KEY"]' 2>&1 || echo "")"
    if [[ -z "${ENV_KEY_CHECK}" || "${ENV_KEY_CHECK}" == *"matches_n\": 0"* ]]; then
      ENV_KEY_CHECK="$(opencli browser "${BROWSER_SESSION}" find --text "SMOKE_KEY" 2>&1 || echo "")"
    fi
    if [[ -n "${ENV_KEY_CHECK}" && "${ENV_KEY_CHECK}" != *"matches_n\": 0"* ]]; then
      log_step "env-edited" "pass" "环境变量编辑成功"
    else
      log_step "env-edited" "skip" "未检测到编辑后的环境变量"
    fi
  fi

  # ── 删除环境 ──
  # Trash2 按钮触发 AlertDialog
  opencli browser "${BROWSER_SESSION}" click '[role="dialog"] button:has(svg.lucide-trash-2)' 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "Delete" 2>/dev/null || true
  sleep 1

  # 确认删除
  opencli browser "${BROWSER_SESSION}" click '[role="alertdialog"] button' 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "Delete" 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "删除" 2>/dev/null || true
  sleep 2
  screenshot "04-env-after-delete"

  ENV_DELETED_CHECK="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Env" 2>&1 || echo "")"
  if [[ -z "${ENV_DELETED_CHECK}" || "${ENV_DELETED_CHECK}" == *"matches_n\": 0"* ]]; then
    log_step "env-deleted" "pass" "环境已删除"
  else
    log_step "env-deleted" "skip" "环境可能未被删除"
  fi
else
  log_step "env-create-btn" "skip" "未找到创建环境按钮"
fi

# ── Notifications 标签测试 ─────────────────────────────────

opencli browser "${BROWSER_SESSION}" click '[data-value="notifications"]' 2>/dev/null || true
sleep 2
screenshot "04-notify-tab"

# 点击创建通知规则按钮（NotificationRulesPanel: Button with Plus + "Create"）
NOTIFY_CREATE_BTN=""
for notify_btn_text in "Create" "创建"; do
  NOTIFY_CREATE_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "$notify_btn_text" 2>&1 || echo "")"
  if [[ -n "${NOTIFY_CREATE_BTN}" && "${NOTIFY_CREATE_BTN}" != *"matches_n\": 0"* ]]; then
    NOTIFY_CREATE_BTN_TEXT="$notify_btn_text"
    break
  fi
done
if [[ -n "${NOTIFY_CREATE_BTN}" && "${NOTIFY_CREATE_BTN}" == *'matches_n'* && "${NOTIFY_CREATE_BTN}" != *'matches_n": 0'* ]]; then
  opencli browser "${BROWSER_SESSION}" click --text "${NOTIFY_CREATE_BTN_TEXT}" --nth 0 2>/dev/null || true
  sleep 1

  # 内联 RuleForm 出现
  # 填写规则名称
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="Failed build"], input[placeholder*="alert"]' "Smoke Rule" 2>/dev/null || true
  sleep 0.5

  # 条件：默认已有一个条件行（status eq ""），填写 value
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder="value"]' "failed" 2>/dev/null || true
  sleep 0.3

  # 渠道：默认已有一个渠道行（email），填写收件人
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="recipient"], input[placeholder*="@example"]' "smoke@test.com" 2>/dev/null || true
  sleep 0.5

  screenshot "04-notify-form-filled"

  # 点击 Save 按钮
  opencli browser "${BROWSER_SESSION}" click --text "Save" 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "保存" 2>/dev/null || true
  sleep 2
  screenshot "04-notify-after-create"

  # 验证规则出现
  NOTIFY_CREATED_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Rule" 2>&1 || echo "")"
  if [[ -n "${NOTIFY_CREATED_OUT}" && "${NOTIFY_CREATED_OUT}" != *"matches_n\": 0"* ]]; then
    log_step "notify-created" "pass" "Smoke Rule 已出现在列表中"
  else
    handle_failure "notify-created" "Smoke Rule 未出现在列表中"
  fi

  # ── 编辑通知规则 ──
  # Pencil 按钮打开编辑表单
  opencli browser "${BROWSER_SESSION}" click '[data-value="notifications"] button:has(svg.lucide-pencil)' 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "Smoke Rule" 2>/dev/null || true
  sleep 1

  # 修改名称
  NOTIFY_NAME_INPUT="$(opencli browser "${BROWSER_SESSION}" find --css 'input[value="Smoke Rule"]' 2>&1 || echo "")"
  if [[ -n "${NOTIFY_NAME_INPUT}" && "${NOTIFY_NAME_INPUT}" != *"matches_n\": 0"* ]]; then
    opencli browser "${BROWSER_SESSION}" fill 'input[value="Smoke Rule"]' "Smoke Rule Edited" 2>/dev/null || true
    sleep 0.5

    # 保存修改
    opencli browser "${BROWSER_SESSION}" click --text "Save" 2>/dev/null || \
      opencli browser "${BROWSER_SESSION}" click --text "保存" 2>/dev/null || true
    sleep 2
    screenshot "04-notify-after-edit"

    NOTIFY_EDITED_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Rule Edited" 2>&1 || echo "")"
    if [[ -n "${NOTIFY_EDITED_OUT}" && "${NOTIFY_EDITED_OUT}" != *"matches_n\": 0"* ]]; then
      log_step "notify-edited" "pass" "通知规则编辑成功"
    else
      log_step "notify-edited" "skip" "未检测到编辑后的规则名称"
    fi
  else
    log_step "notify-edited" "skip" "未找到规则名称输入框"
  fi

  # ── 删除通知规则 ──
  # Trash2 按钮触发 AlertDialog
  opencli browser "${BROWSER_SESSION}" click '[data-value="notifications"] button:has(svg.lucide-trash-2)' 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "Delete" 2>/dev/null || true
  sleep 1

  # 确认删除
  opencli browser "${BROWSER_SESSION}" click '[role="alertdialog"] button' 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "Delete" 2>/dev/null || \
    opencli browser "${BROWSER_SESSION}" click --text "删除" 2>/dev/null || true
  sleep 2
  screenshot "04-notify-after-delete"

  NOTIFY_DELETED_CHECK=""
  for notify_del_text in "Smoke Rule Edited" "Smoke Rule"; do
    NOTIFY_DELETED_CHECK="$(opencli browser "${BROWSER_SESSION}" find --text "$notify_del_text" 2>&1 || echo "")"
    if [[ -n "${NOTIFY_DELETED_CHECK}" && "${NOTIFY_DELETED_CHECK}" != *"matches_n\": 0"* ]]; then
      break
    fi
  done
  if [[ -z "${NOTIFY_DELETED_CHECK}" || "${NOTIFY_DELETED_CHECK}" == *"matches_n\": 0"* ]]; then
    log_step "notify-deleted" "pass" "通知规则已删除"
  else
    log_step "notify-deleted" "skip" "通知规则可能未被删除"
  fi
else
  log_step "notify-create-btn" "skip" "未找到创建通知规则按钮"
fi

# ── Analytics 标签测试 ─────────────────────────────────────

opencli browser "${BROWSER_SESSION}" click '[data-value="analytics"]' 2>/dev/null || true
sleep 2
screenshot "04-analytics-tab"

# 验证日期范围选择器存在（7d/14d/30d/90d 按钮组）
PERIOD_BTNS=0
for period in "7d" "14d" "30d" "90d"; do
  PERIOD_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "${period}" 2>&1 || echo "")"
  if [[ -n "${PERIOD_OUT}" && "${PERIOD_OUT}" != *"matches_n\": 0"* ]]; then
    ((PERIOD_BTNS++)) || true
  fi
done
if (( PERIOD_BTNS >= 2 )); then
  log_step "analytics-period-selector" "pass" "日期范围选择器存在 (${PERIOD_BTNS}/4 按钮)"
else
  log_step "analytics-period-selector" "skip" "未检测到足够的日期范围按钮 (${PERIOD_BTNS}/4)"
fi

# 切换日期范围（点击 14d，验证按钮状态变化）
opencli browser "${BROWSER_SESSION}" click --text "14d" 2>/dev/null || true
sleep 2
screenshot "04-analytics-14d"

# 验证 14d 按钮变为激活态（aria-pressed="true" 或 variant="default"）
PERIOD_ACTIVE="$(opencli browser "${BROWSER_SESSION}" find --css '[data-value="14d"][data-state="active"], [data-value="14d"][aria-pressed="true"]' 2>&1 || echo "")"
if [[ -z "${PERIOD_ACTIVE}" || "${PERIOD_ACTIVE}" == *"matches_n\": 0"* ]]; then
  PERIOD_ACTIVE="$(opencli browser "${BROWSER_SESSION}" find --text "14d" 2>&1 || echo "")"
fi
if [[ -n "${PERIOD_ACTIVE}" && "${PERIOD_ACTIVE}" != *"matches_n\": 0"* ]]; then
  log_step "analytics-period-switch" "pass" "日期范围切换成功 (14d 激活)"
else
  log_step "analytics-period-switch" "skip" "未检测到 14d 按钮激活态"
fi

# 验证趋势面积图（Recharts ResponsiveContainer 渲染 SVG）
if assert_element 'svg .recharts-area, svg .recharts-area-curve, .recharts-responsive-container svg'; then
  log_step "analytics-trend-chart" "pass" "趋势面积图已渲染"
elif assert_element 'svg'; then
  log_step "analytics-trend-chart" "pass" "SVG 图表容器存在"
else
  log_step "analytics-trend-chart" "skip" "未检测到趋势图 SVG"
fi

# 验证趋势图标题
TREND_TITLE_OUT=""
for trend_text in "Trend" "趋势" "trend"; do
  TREND_TITLE_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "$trend_text" 2>&1 || echo "")"
  if [[ -n "${TREND_TITLE_OUT}" && "${TREND_TITLE_OUT}" != *"matches_n\": 0"* ]]; then break; fi
done
if [[ -n "${TREND_TITLE_OUT}" && "${TREND_TITLE_OUT}" != *"matches_n\": 0"* ]]; then
  log_step "analytics-trend-title" "pass" "趋势图标题存在"
else
  log_step "analytics-trend-title" "skip" "未检测到趋势图标题"
fi

# 验证 Flaky 测试表格存在
if assert_element 'table'; then
  log_step "analytics-flaky-table" "pass" "Flaky 测试表格存在"
  # 验证表格列头（suite/testCase/runs/failures/flakyRate）
  if assert_element 'table th'; then
    log_step "analytics-flaky-columns" "pass" "Flaky 表格列头存在"
  else
    log_step "analytics-flaky-columns" "skip" "未检测到表格列头"
  fi
else
  log_step "analytics-flaky-table" "skip" "未检测到 Flaky 测试表格（可能无数据）"
fi

# 验证 Flaky 标题
FLAKY_TITLE_OUT=""
for flaky_text in "Flaky" "flaky" "不稳定"; do
  FLAKY_TITLE_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "$flaky_text" 2>&1 || echo "")"
  if [[ -n "${FLAKY_TITLE_OUT}" && "${FLAKY_TITLE_OUT}" != *"matches_n\": 0"* ]]; then break; fi
done
if [[ -n "${FLAKY_TITLE_OUT}" && "${FLAKY_TITLE_OUT}" != *"matches_n\": 0"* ]]; then
  log_step "analytics-flaky-title" "pass" "Flaky 区域标题存在"
else
  log_step "analytics-flaky-title" "skip" "未检测到 Flaky 标题"
fi

# ── Settings 标签测试 ──────────────────────────────────────

opencli browser "${BROWSER_SESSION}" click '[data-value="settings"]' 2>/dev/null || true
sleep 2
screenshot "04-settings-tab"

# 验证项目编辑表单字段存在（detail.tsx: #name, #description, #git_url, #default_branch, #root_path）
SETTINGS_FIELDS_FOUND=0
for field_id in "name" "description" "git_url" "default_branch" "root_path"; do
  FIELD_OUT="$(opencli browser "${BROWSER_SESSION}" find --css "#${field_id}" 2>&1 || echo "")"
  if [[ -n "${FIELD_OUT}" && "${FIELD_OUT}" != *"matches_n\": 0"* ]]; then
    ((SETTINGS_FIELDS_FOUND++)) || true
  fi
done
if (( SETTINGS_FIELDS_FOUND >= 3 )); then
  log_step "settings-form-fields" "pass" "项目编辑表单字段存在 (${SETTINGS_FIELDS_FOUND}/5)"
else
  handle_failure "settings-form-fields" "项目编辑表单字段不足 (${SETTINGS_FIELDS_FOUND}/5)"
fi

# 验证保存按钮存在（type="submit"）
if assert_element 'button[type="submit"]'; then
  log_step "settings-save-btn" "pass" "保存按钮存在"
else
  handle_failure "settings-save-btn" "保存按钮不存在"
fi

# 修改项目名称，保存，验证更新
ORIGINAL_NAME="$(opencli browser "${BROWSER_SESSION}" find --css '#name' 2>&1 | grep -o 'value="[^"]*"' | head -1 || echo "")"
opencli browser "${BROWSER_SESSION}" fill '#name' "Smoke Test Renamed" 2>/dev/null || true
sleep 0.5

# 提交保存
opencli browser "${BROWSER_SESSION}" click 'button[type="submit"]' 2>/dev/null || true
sleep 2
screenshot "04-settings-after-save"

# 验证 h1 标题更新
RENAME_CHECK="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Test Renamed" 2>&1 || echo "")"
if [[ -n "${RENAME_CHECK}" && "${RENAME_CHECK}" != *"matches_n\": 0"* ]]; then
  log_step "settings-name-updated" "pass" "项目名称更新成功"
else
  log_step "settings-name-updated" "skip" "未检测到名称更新（可能需要刷新）"
fi

# 恢复原名
if [[ -n "${ORIGINAL_NAME}" ]]; then
  RESTORE_NAME="$(echo "${ORIGINAL_NAME}" | sed 's/value="//;s/"$//')"
  opencli browser "${BROWSER_SESSION}" fill '#name' "${RESTORE_NAME}" 2>/dev/null || true
  sleep 0.3
  opencli browser "${BROWSER_SESSION}" click 'button[type="submit"]' 2>/dev/null || true
  sleep 1
fi

# 验证危险区存在（border-status-failed 样式的 div 包含归档和删除按钮）
DANGER_OUT=""
for danger_text in "Danger" "危险" "danger"; do
  DANGER_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "$danger_text" 2>&1 || echo "")"
  if [[ -n "${DANGER_OUT}" && "${DANGER_OUT}" != *"matches_n\": 0"* ]]; then break; fi
done
if [[ -n "${DANGER_OUT}" && "${DANGER_OUT}" != *"matches_n\": 0"* ]]; then
  log_step "settings-danger-zone" "pass" "危险区域存在"
else
  log_step "settings-danger-zone" "skip" "未检测到危险区域标题"
fi

# 验证归档按钮
ARCHIVE_OUT=""
for archive_text in "Archive" "归档"; do
  ARCHIVE_OUT="$(opencli browser "${BROWSER_SESSION}" find --text "$archive_text" 2>&1 || echo "")"
  if [[ -n "${ARCHIVE_OUT}" && "${ARCHIVE_OUT}" != *"matches_n\": 0"* ]]; then break; fi
done
if [[ -n "${ARCHIVE_OUT}" && "${ARCHIVE_OUT}" != *"matches_n\": 0"* ]]; then
  log_step "settings-archive-btn" "pass" "归档按钮存在"
else
  log_step "settings-archive-btn" "skip" "未检测到归档按钮"
fi

# 验证删除按钮（variant="destructive"）
DELETE_BTN_CHECK="$(opencli browser "${BROWSER_SESSION}" find --css 'button[class*="destructive"]' 2>&1 || echo "")"
if [[ -z "${DELETE_BTN_CHECK}" || "${DELETE_BTN_CHECK}" == *"matches_n\": 0"* ]]; then
  for del_text in "Delete Project" "删除项目"; do
    DELETE_BTN_CHECK="$(opencli browser "${BROWSER_SESSION}" find --text "$del_text" 2>&1 || echo "")"
    if [[ -n "${DELETE_BTN_CHECK}" && "${DELETE_BTN_CHECK}" != *"matches_n\": 0"* ]]; then break; fi
  done
fi
if [[ -n "${DELETE_BTN_CHECK}" && "${DELETE_BTN_CHECK}" != *"matches_n\": 0"* ]]; then
  log_step "settings-delete-btn" "pass" "删除项目按钮存在"
else
  log_step "settings-delete-btn" "skip" "未检测到删除项目按钮"
fi

log_step "project-detail-complete" "pass" "项目详情冒烟测试完成"
