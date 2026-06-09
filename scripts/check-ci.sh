#!/bin/bash
# CI 状态检查脚本
# 在 git push 后检查 CI 运行状态

set -e

echo "🔍 检查 CI 状态..."
echo "===================="
echo ""

# 检查 gh CLI 是否可用
if ! command -v gh >/dev/null 2>&1; then
    echo "❌ GitHub CLI (gh) 未安装"
    echo "安装方法: brew install gh"
    exit 1
fi

# 检查是否已认证
if ! gh auth status >/dev/null 2>&1; then
    echo "❌ GitHub CLI 未认证"
    echo "认证方法: gh auth login"
    exit 1
fi

# 获取最新的 CI 运行
echo "📊 最近 5 次 CI 运行："
echo "--------------------"
gh run list --limit 5

echo ""
echo "--------------------"
echo ""

# 获取最新一次运行的状态
latest_status=$(gh run list --limit 1 --json status,conclusion,name,headBranch --jq '.[0]')
status=$(echo "$latest_status" | jq -r '.status')
conclusion=$(echo "$latest_status" | jq -r '.conclusion')
name=$(echo "$latest_status" | jq -r '.name')
branch=$(echo "$latest_status" | jq -r '.headBranch')

echo "🎯 最新 CI 运行："
echo "   提交: $name"
echo "   分支: $branch"
echo "   状态: $status"

if [ "$status" = "completed" ]; then
    echo "   结果: $conclusion"
    echo ""

    if [ "$conclusion" = "success" ]; then
        echo "✅ CI 通过！代码已安全合并"
        exit 0
    elif [ "$conclusion" = "failure" ]; then
        echo "❌ CI 失败！需要修复"
        echo ""
        echo "🔧 查看失败详情："
        echo "   gh run view --log"
        echo "   或访问: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions"
        exit 1
    else
        echo "⚠️  CI 状态: $conclusion"
        exit 1
    fi
else
    echo ""
    echo "⏳ CI 正在运行中..."
    echo ""
    echo "💡 等待完成后再次运行此脚本"
    echo "   或使用: gh run watch"
    exit 0
fi
