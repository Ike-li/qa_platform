#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-}"
if [[ -z "$RUN_ID" ]]; then
  echo "Usage: $0 <workflow_run_id>"
  echo "Get run_id from: gh run list --workflow=ci.yml"
  exit 1
fi

echo "=== Downloading logs for run $RUN_ID ==="
gh run download "$RUN_ID" --name backend-integration-test-logs || true
gh run download "$RUN_ID" --name e2e-test-logs || true
gh run download "$RUN_ID" --name release-gate-evidence || true

echo ""
echo "=== Checking ExitResult bug (should be empty) ==="
grep -r "ExitResult.*missing.*arguments" . 2>/dev/null || echo "✅ No ExitResult crash"

echo ""
echo "=== Checking heavy_docker ran (should have matches) ==="
grep -r "heavy_docker" . 2>/dev/null | head -3 || echo "⚠️  No heavy_docker marker found"

echo ""
echo "=== Checking external_stack ran (should have matches) ==="
grep -r "external_stack" . 2>/dev/null | head -3 || echo "⚠️  No external_stack marker found"

echo ""
echo "=== Evidence summary ==="
cat release-gate-evidence/release-evidence.md 2>/dev/null || echo "⚠️  No evidence file"

echo ""
echo "✅ Manual review complete. Check above for warnings."
