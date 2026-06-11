#!/bin/bash
# T14 dogfooding：从 GitHub Actions 拉取最近 CI 测试结果（JUnit XML），
# 通过 T11 import 接口导入本地 QA Platform 实例（pull 模式，本地运行）。
#
# 用法:
#   ./scripts/import_ci_results.sh [--dry-run] [--limit N]
#
# 环境变量:
#   QAP_IMPORT_TOKEN       API token（qap_ 开头，需 run.trigger scope）【必填】
#   QAP_IMPORT_PROJECT_ID  目标项目 ID【必填】
#   QAP_IMPORT_URL         平台地址，默认 http://localhost:8000
#   QAP_IMPORT_STATE_FILE  状态文件路径，默认 <仓库根>/.qap-import-state.json
#
# 行为约定:
#   - 已导入的 CI run id 记录在状态文件，重复运行不重复导入
#   - artifact 缺失 / 无 JUnit XML 的 run 跳过并打印原因，不中断
#   - 文件级 HTTP 4xx（坏数据，重试无用）只告警，run 仍标记已处理；
#     HTTP 5xx / 网络错误不标记，下次运行重试

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMPORT_URL="${QAP_IMPORT_URL:-http://localhost:8000}"
STATE_FILE="${QAP_IMPORT_STATE_FILE:-${REPO_ROOT}/.qap-import-state.json}"
LIMIT=5
DRY_RUN=0

# artifact 名 → 平台 pipeline_name（T11 的占位 pipeline 按名字 get-or-create）
ARTIFACTS=(
    "backend-test-artifacts:ci-backend-unit"
    "backend-integration-artifacts:ci-backend-integration"
    "e2e-artifacts:ci-e2e"
    "frontend-unit-junit:ci-frontend-unit"
)

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --limit) LIMIT="$2"; shift 2 ;;
        *) echo "未知参数: $1"; echo "用法: $0 [--dry-run] [--limit N]"; exit 1 ;;
    esac
done

for cmd in gh jq curl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "❌ 缺少依赖: $cmd"
        exit 1
    fi
done
if ! gh auth status >/dev/null 2>&1; then
    echo "❌ GitHub CLI 未认证，先运行: gh auth login"
    exit 1
fi
if [[ $DRY_RUN -eq 0 ]]; then
    : "${QAP_IMPORT_TOKEN:?必须设置 QAP_IMPORT_TOKEN（qap_ 开头的 API token）}"
    : "${QAP_IMPORT_PROJECT_ID:?必须设置 QAP_IMPORT_PROJECT_ID（目标项目 ID）}"
fi

[[ -f "$STATE_FILE" ]] || echo '{"imported_run_ids": []}' > "$STATE_FILE"

is_imported() {
    jq -e --argjson id "$1" '.imported_run_ids | index($id) != null' "$STATE_FILE" >/dev/null
}

mark_imported() {
    local tmp
    tmp="$(mktemp)"
    jq --argjson id "$1" '.imported_run_ids += [$id]' "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
}

urlencode_ts() {
    # ISO8601 时间戳只需编码冒号与加号
    echo "$1" | sed -e 's/:/%3A/g' -e 's/+/%2B/g'
}

echo "🔄 拉取最近 $LIMIT 个已完成的 main 分支 CI run..."
RUNS_JSON="$(gh run list --workflow CI --branch main --status completed --limit "$LIMIT" \
    --json databaseId,headSha,conclusion,createdAt)"

RUN_COUNT="$(echo "$RUNS_JSON" | jq 'length')"
if [[ "$RUN_COUNT" -eq 0 ]]; then
    echo "没有已完成的 CI run，结束。"
    exit 0
fi

TOTAL_IMPORTED=0
TOTAL_WARNED=0
RETRYABLE_FAILURE=0

for i in $(seq 0 $((RUN_COUNT - 1))); do
    RUN_ID="$(echo "$RUNS_JSON" | jq -r ".[$i].databaseId")"
    HEAD_SHA="$(echo "$RUNS_JSON" | jq -r ".[$i].headSha")"
    CONCLUSION="$(echo "$RUNS_JSON" | jq -r ".[$i].conclusion")"
    CREATED_AT="$(echo "$RUNS_JSON" | jq -r ".[$i].createdAt")"

    if is_imported "$RUN_ID"; then
        echo "⏭  run $RUN_ID 已导入过，跳过"
        continue
    fi

    echo ""
    echo "📦 处理 CI run ${RUN_ID}（conclusion=${CONCLUSION}, sha=${HEAD_SHA:0:8}）"
    WORK_DIR="$(mktemp -d)"
    trap 'rm -rf "$WORK_DIR"' EXIT

    RUN_IMPORTED=0
    RUN_WARNED=0
    RUN_RETRYABLE=0

    for entry in "${ARTIFACTS[@]}"; do
        ARTIFACT_NAME="${entry%%:*}"
        PIPELINE_NAME="${entry##*:}"
        DEST_DIR="$WORK_DIR/$ARTIFACT_NAME"

        if ! gh run download "$RUN_ID" --name "$ARTIFACT_NAME" --dir "$DEST_DIR" 2>/dev/null; then
            echo "  ⏭  artifact $ARTIFACT_NAME 缺失（可能未上传或已过期），跳过"
            continue
        fi

        # 只导入 JUnit 格式（coverage XML 等同目录产物不含 <testsuite）
        XML_FILES="$(grep -rl --include='*.xml' '<testsuite' "$DEST_DIR" 2>/dev/null || true)"
        if [[ -z "$XML_FILES" ]]; then
            echo "  ⏭  artifact $ARTIFACT_NAME 内没有 JUnit XML，跳过"
            continue
        fi

        while IFS= read -r xml_file; do
            REL_NAME="${xml_file#"$DEST_DIR"/}"
            if [[ $DRY_RUN -eq 1 ]]; then
                echo "  [dry-run] 将导入 $ARTIFACT_NAME/$REL_NAME → pipeline=$PIPELINE_NAME"
                RUN_IMPORTED=$((RUN_IMPORTED + 1))
                continue
            fi

            QUERY="git_ref=main&git_sha=${HEAD_SHA}&pipeline_name=${PIPELINE_NAME}"
            QUERY="${QUERY}&started_at=$(urlencode_ts "$CREATED_AT")"
            HTTP_CODE="$(curl -sS -o "$WORK_DIR/resp.json" -w '%{http_code}' \
                -X POST \
                -H "Authorization: Bearer ${QAP_IMPORT_TOKEN}" \
                -H "Content-Type: application/xml" \
                --data-binary @"$xml_file" \
                "${IMPORT_URL}/api/v1/projects/${QAP_IMPORT_PROJECT_ID}/runs/import?${QUERY}")" \
                || { echo "  ❌ 平台不可达（${IMPORT_URL}），中止"; exit 1; }

            if [[ "$HTTP_CODE" == "201" ]]; then
                PLATFORM_RUN="$(jq -r '.id' "$WORK_DIR/resp.json" 2>/dev/null || echo '?')"
                echo "  ✅ $ARTIFACT_NAME/$REL_NAME → pipeline=$PIPELINE_NAME run=$PLATFORM_RUN"
                RUN_IMPORTED=$((RUN_IMPORTED + 1))
            elif [[ "$HTTP_CODE" =~ ^4 ]]; then
                echo "  ⚠️  $REL_NAME 被平台拒绝（HTTP ${HTTP_CODE}，重试无用）: $(head -c 200 "$WORK_DIR/resp.json")"
                RUN_WARNED=$((RUN_WARNED + 1))
            else
                echo "  ❌ $REL_NAME 导入失败（HTTP ${HTTP_CODE}，将在下次运行重试）: $(head -c 200 "$WORK_DIR/resp.json")"
                RUN_RETRYABLE=$((RUN_RETRYABLE + 1))
            fi
        done <<< "$XML_FILES"
    done

    rm -rf "$WORK_DIR"
    trap - EXIT

    TOTAL_IMPORTED=$((TOTAL_IMPORTED + RUN_IMPORTED))
    TOTAL_WARNED=$((TOTAL_WARNED + RUN_WARNED))
    if [[ $RUN_RETRYABLE -gt 0 ]]; then
        RETRYABLE_FAILURE=1
        echo "  ⚠️  run $RUN_ID 有可重试失败，不记入状态文件"
    elif [[ $DRY_RUN -eq 0 ]]; then
        mark_imported "$RUN_ID"
        echo "  📝 run $RUN_ID 标记为已处理（导入 $RUN_IMPORTED 份）"
    fi
done

echo ""
if [[ $DRY_RUN -eq 1 ]]; then
    echo "🔍 dry-run 完成：将导入 $TOTAL_IMPORTED 份 JUnit XML（未实际写入，状态文件未更新）"
else
    echo "✅ 完成：导入 $TOTAL_IMPORTED 份，拒绝 $TOTAL_WARNED 份"
fi
exit $RETRYABLE_FAILURE
