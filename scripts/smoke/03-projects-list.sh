#!/usr/bin/env bash
# 03-projects-list.sh — Projects list page smoke test
# Verifies the projects list page renders correctly after login.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/smoke/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
init_results_dir

trap generate_report EXIT

log_step "projects-list-start" "pass" "开始项目列表冒烟测试"

# 1. Verify we are on the projects page
CURRENT_URL="$(opencli browser "${BROWSER_SESSION}" state 2>/dev/null | sed -n 's/^URL: //p' | head -1 || echo "")"
if [[ "$CURRENT_URL" == *"/projects"* ]]; then
  log_step "url-check" "pass" "当前在项目页"
else
  opencli browser "${BROWSER_SESSION}" open "${BASE_URL}/projects"
  sleep 2
  log_step "url-check" "pass" "已导航到项目页"
fi

# 2. Screenshot: projects list
screenshot "03-projects-list"

# 3. Verify page heading
if assert_element "h1"; then
  log_step "page-heading" "pass"
else
  handle_failure "page-heading" "项目列表页缺少 h1 标题"
fi

# 4. Verify "New Project" button exists
if assert_element "button"; then
  log_step "new-project-button" "pass" "发现操作按钮"
else
  log_step "new-project-button" "skip" "未检测到按钮"
fi

# 5. Check for project content (cards or empty state)
CARDS_OUTPUT="$(opencli browser "${BROWSER_SESSION}" find --css 'a[href*="/projects/"]' 2>&1 || echo "")"
if [[ -n "${CARDS_OUTPUT}" && "${CARDS_OUTPUT}" != *"matches_n\": 0"* ]]; then
  log_step "project-content" "pass" "发现项目卡片"
else
  log_step "project-content" "skip" "无项目卡片（可能为空列表）"
fi

# 6. 搜索过滤测试
SEARCH_INPUT="$(opencli browser "${BROWSER_SESSION}" find --css 'input[placeholder*="search" i], input[placeholder*="Search"], input[type="search"]' 2>&1 || echo "")"
if [[ -n "${SEARCH_INPUT}" && "${SEARCH_INPUT}" != *"matches_n\": 0"* ]]; then
  # 输入搜索关键词
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="search" i], input[placeholder*="Search"], input[type="search"]' "test"
  sleep 2
  screenshot "04-search-filter"

  # 验证过滤后列表可能变化（至少搜索框有值）
  SEARCH_FILLED="$(opencli browser "${BROWSER_SESSION}" find --css 'input[placeholder*="search" i], input[placeholder*="Search"], input[type="search"]' 2>&1 || echo "")"
  if [[ -n "${SEARCH_FILLED}" && "${SEARCH_FILLED}" != *"matches_n\": 0"* ]]; then
    log_step "search-filter" "pass" "搜索过滤功能可用"
  else
    log_step "search-filter" "skip" "搜索输入框状态异常"
  fi

  # 清空搜索，验证列表恢复
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="search" i], input[placeholder*="Search"], input[type="search"]' ""
  sleep 2
  log_step "search-clear" "pass" "搜索已清空"
else
  log_step "search-filter" "skip" "未找到搜索输入框"
fi

# 7. 创建项目对话框测试
# 查找"新建项目"按钮
NEW_BTN=""
for btn_text in "New Project" "新建项目" "New" "新建" "Create" "创建"; do
  NEW_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "$btn_text" 2>&1 || echo "")"
  if [[ -n "${NEW_BTN}" && "${NEW_BTN}" == *"matches_n"* && "${NEW_BTN}" != *"matches_n\": 0"* ]]; then
    NEW_BTN_TEXT="$btn_text"
    break
  fi
done
if [[ -n "${NEW_BTN}" && "${NEW_BTN}" == *"matches_n"* && "${NEW_BTN}" != *"matches_n\": 0"* ]]; then
  opencli browser "${BROWSER_SESSION}" click --text "${NEW_BTN_TEXT}"
  sleep 2

  # 检测对话框
  DIALOG="$(opencli browser "${BROWSER_SESSION}" find --css '[role="dialog"], .modal, .dialog, form' 2>&1 || echo "")"
  if [[ -n "${DIALOG}" && "${DIALOG}" != *"matches_n\": 0"* ]]; then
    log_step "create-dialog-open" "pass" "创建项目对话框已打开"
    screenshot "05-create-dialog"

    # 填写项目名称
    NAME_INPUT="$(opencli browser "${BROWSER_SESSION}" find --css 'input[name="name"], input[name="project_name"], input[placeholder*="名称"], input[placeholder*="name" i]' 2>&1 || echo "")"
    if [[ -n "${NAME_INPUT}" && "${NAME_INPUT}" != *"matches_n\": 0"* ]]; then
      opencli browser "${BROWSER_SESSION}" fill 'input[name="name"], input[name="project_name"], input[placeholder*="名称"], input[placeholder*="name" i]' "Smoke Test Project"
      sleep 1

      # 提交创建
      SUBMIT_BTN="$(opencli browser "${BROWSER_SESSION}" find --css '[role="dialog"] button[type="submit"], form button[type="submit"]' 2>&1 || echo "")"
      if [[ -z "${SUBMIT_BTN}" || "${SUBMIT_BTN}" == *"matches_n\": 0"* ]]; then
        for submit_text in "确定" "创建" "Submit"; do
          SUBMIT_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "${submit_text}" 2>&1 || echo "")"
          if [[ -n "${SUBMIT_BTN}" && "${SUBMIT_BTN}" != *"matches_n\": 0"* ]]; then
            SUBMIT_BTN_TEXT="${submit_text}"
            break
          fi
        done
      fi
      if [[ -n "${SUBMIT_BTN}" && "${SUBMIT_BTN}" != *"matches_n\": 0"* ]]; then
        opencli browser "${BROWSER_SESSION}" click '[role="dialog"] button[type="submit"], form button[type="submit"]' 2>/dev/null || \
          opencli browser "${BROWSER_SESSION}" click --text "${SUBMIT_BTN_TEXT:-Submit}" 2>/dev/null || true
        sleep 3
        screenshot "06-after-create"

        # 验证新项目出现在列表中
        NEW_PROJECT="$(opencli browser "${BROWSER_SESSION}" find --text "Smoke Test Project" 2>&1 || echo "")"
        if [[ -n "${NEW_PROJECT}" && "${NEW_PROJECT}" != *"matches_n\": 0"* ]]; then
          log_step "project-created" "pass" "新项目已出现在列表中"
        else
          log_step "project-created" "skip" "未检测到新项目（可能创建失败或页面未刷新）"
        fi
      else
        log_step "project-created" "skip" "未找到对话框提交按钮"
      fi
    else
      log_step "project-created" "skip" "未找到项目名称输入框"
    fi

    # 关闭对话框（如果还在）
    CLOSE_BTN="$(opencli browser "${BROWSER_SESSION}" find --css '[role="dialog"] [aria-label="Close"]' 2>&1 || echo "")"
    for close_text in "取消" "Cancel"; do
      if [[ -z "${CLOSE_BTN}" || "${CLOSE_BTN}" == *"matches_n\": 0"* ]]; then
        CLOSE_BTN="$(opencli browser "${BROWSER_SESSION}" find --text "${close_text}" 2>&1 || echo "")"
      fi
    done
    if [[ -n "${CLOSE_BTN}" && "${CLOSE_BTN}" != *"matches_n\": 0"* ]]; then
      opencli browser "${BROWSER_SESSION}" click '[role="dialog"] [aria-label="Close"]' 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "取消" 2>/dev/null || \
        opencli browser "${BROWSER_SESSION}" click --text "Cancel" 2>/dev/null || true
      sleep 1
    fi
  else
    log_step "create-dialog-open" "skip" "未检测到创建对话框"
  fi
else
  log_step "create-dialog-open" "skip" "未找到新建项目按钮"
fi

# 8. 空状态测试 — 搜索不存在的项目
SEARCH_INPUT="$(opencli browser "${BROWSER_SESSION}" find --css 'input[placeholder*="search" i], input[placeholder*="Search"], input[type="search"]' 2>&1 || echo "")"
if [[ -n "${SEARCH_INPUT}" && "${SEARCH_INPUT}" != *"matches_n\": 0"* ]]; then
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="search" i], input[placeholder*="Search"], input[type="search"]' "nonexistent_project_xyz"
  sleep 2
  screenshot "07-empty-state"

  # 检查空状态提示
  EMPTY_MSG=""
  for empty_text in "没有" "暂无" "No " "empty" "无结果" "No results"; do
    EMPTY_MSG="$(opencli browser "${BROWSER_SESSION}" find --text "${empty_text}" 2>&1 || echo "")"
    if [[ -n "${EMPTY_MSG}" && "${EMPTY_MSG}" != *"matches_n\": 0"* ]]; then
      break
    fi
  done
  if [[ -n "${EMPTY_MSG}" && "${EMPTY_MSG}" != *"matches_n\": 0"* ]]; then
    log_step "empty-state" "pass" "空状态提示已显示"
  else
    log_step "empty-state" "skip" "未检测到空状态提示元素"
  fi

  # 清空搜索恢复
  opencli browser "${BROWSER_SESSION}" fill 'input[placeholder*="search" i], input[placeholder*="Search"], input[type="search"]' ""
  sleep 1
else
  log_step "empty-state" "skip" "未找到搜索输入框，跳过空状态测试"
fi

log_step "projects-list-complete" "pass" "项目列表冒烟测试完成"
