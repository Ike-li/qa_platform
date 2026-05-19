#!/usr/bin/env bash
# 01-browser-bridge.sh — Verify opencli Browser Bridge availability and session persistence
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

BROWSER_SESSION="${BROWSER_SESSION:-smoke}"

# ── Helpers ──────────────────────────────────────────────────────────
log()  { printf "\033[1;34m[browser-bridge]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[FAIL]\033[0m %s\n" "$*" >&2; exit 1; }

# ── 1. Check opencli is installed ───────────────────────────────────
log "Checking opencli installation..."
if ! command -v opencli >/dev/null 2>&1; then
  fail "opencli is not installed or not on PATH. Install it first:
  npm install -g opencli
  # or
  brew install opencli"
fi
log "opencli found: $(command -v opencli)"

# ── 2. Run opencli doctor ───────────────────────────────────────────
log "Running opencli doctor..."
if ! opencli doctor 2>&1; then
  warn "opencli doctor reported issues."
fi

# ── 3. Check Browser Bridge connectivity ────────────────────────────
log "Checking Browser Bridge status..."
# Try a simple state command to verify bridge is responsive
BRIDGE_OUTPUT=$(opencli browser "${BROWSER_SESSION}" state 2>&1) || true
if echo "$BRIDGE_OUTPUT" | grep -qi "not running\|not connected\|error\|ECONNREFUSED"; then
  warn "Browser Bridge does not appear to be running."
  echo ""
  echo "  To start the Browser Bridge, run:"
  echo "    opencli browser init"
  echo ""
  echo "  This will launch a Chrome instance that opencli can control."
  echo "  After initialization, re-run this script."
  exit 1
fi
log "Browser Bridge appears active."

# ── 4. Session persistence verification ─────────────────────────────
log "Verifying session persistence across calls..."

BASE_URL="${BASE_URL:-http://localhost:80}"

log "  Call 1: open $BASE_URL ..."
NAV_RESULT=$(opencli browser "${BROWSER_SESSION}" open "$BASE_URL" 2>&1) || true
if echo "$NAV_RESULT" | grep -qi "error\|fail"; then
  warn "Open command failed. Output:"
  echo "$NAV_RESULT"
  fail "Could not open $BASE_URL."
fi
log "  Open succeeded."

# Small delay to ensure session is retained
sleep 1

log "  Call 2: state check (should reuse same session)..."
STATE_RESULT=$(opencli browser "${BROWSER_SESSION}" state 2>&1) || true
if echo "$STATE_RESULT" | grep -qi "error\|fail\|no session\|session expired"; then
  warn "State command failed or session was not preserved. Output:"
  echo "$STATE_RESULT"
  echo ""
  warn "Session does not appear to persist across opencli browser calls."
  echo "  Consider using single-script mode instead of multi-step scripts."
  echo "  In single-script mode, all browser actions are chained in one invocation."
  exit 1
fi

log "  State check succeeded — session persisted across calls."

# ── 5. Summary ──────────────────────────────────────────────────────
log "Browser Bridge verification complete."
echo ""
echo "  opencli path:       $(command -v opencli)"
echo "  Bridge status:      active"
echo "  Session persistent: yes"
echo "  Base URL:           $BASE_URL"
echo "  Session name:       $BROWSER_SESSION"
