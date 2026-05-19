#!/usr/bin/env bash
# 00-setup.sh — Environment setup for smoke tests
# Starts Docker Compose services, runs migrations, seeds admin user,
# and initializes test artifact directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

BASE_URL="${BASE_URL:-http://localhost:80}"
PYTHON="${PYTHON:-.venv/bin/python}"

# ── Helpers ──────────────────────────────────────────────────────────
log()  { printf "\033[1;34m[setup]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[FAIL]\033[0m %s\n" "$*" >&2; exit 1; }

wait_for_port() {
  local host="$1" port="$2" timeout="${3:-60}"
  local end=$((SECONDS + timeout))
  while (( SECONDS < end )); do
    if (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

service_health() {
  local service="$1"
  local cid
  cid=$(docker compose ps -q "$service" 2>/dev/null) || true
  if [[ -z "$cid" ]]; then
    echo "missing"
    return
  fi
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo "unknown"
}

wait_for_healthy() {
  local timeout="${1:-120}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local all_ok=true
    for svc in postgres redis minio api frontend; do
      local st
      st=$(service_health "$svc")
      if [[ "$st" != "healthy" && "$st" != "running" ]]; then
        all_ok=false
        break
      fi
    done
    if $all_ok; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# ── 1. Docker check ─────────────────────────────────────────────────
log "Checking Docker daemon..."
if ! docker info >/dev/null 2>&1; then
  fail "Docker is not running. Please start Docker Desktop and retry."
fi
log "Docker is running."

# ── 2. Start services ───────────────────────────────────────────────
log "Starting docker-compose services..."
docker compose up -d

# ── 3. Wait for healthchecks ────────────────────────────────────────
log "Waiting for all services to become healthy (up to 120s)..."
if ! wait_for_healthy 120; then
  for svc in postgres redis minio api frontend; do
    printf "  %-10s %s\n" "$svc" "$(service_health "$svc")"
  done
  fail "Timed out waiting for services to become healthy."
fi
log "All services healthy."

# ── 4. Run migrations ──────────────────────────────────────────────
log "Running alembic upgrade head..."
if [[ -f .venv/bin/alembic ]]; then
  .venv/bin/alembic upgrade head
elif [[ -f .venv/bin/python ]]; then
  "$PYTHON" -m alembic upgrade head
else
  fail "Neither .venv/bin/alembic nor .venv/bin/python found. Is the virtualenv set up?"
fi

# ── 5. Seed admin user ─────────────────────────────────────────────
log "Seeding admin user (admin/admin123)..."
ADMIN_USERNAME=admin \
ADMIN_PASSWORD=admin123 \
ADMIN_EMAIL=admin@qaplatform.local \
"$PYTHON" scripts/seed_admin.py

# ── 6. Wait for frontend on port 80 ────────────────────────────────
local_port=80
log "Verifying frontend is accessible at $BASE_URL (port $local_port)..."
if ! wait_for_port 127.0.0.1 "$local_port" 30; then
  fail "Frontend port $local_port not reachable after 30s."
fi

# Quick HTTP check
if command -v curl >/dev/null 2>&1; then
  if ! curl -sf -o /dev/null --max-time 5 "$BASE_URL"; then
    fail "Frontend HTTP check failed at $BASE_URL."
  fi
fi
log "Frontend accessible at $BASE_URL."

# ── 7. Create test artifact directory ──────────────────────────────
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="tests/smoke-results/$TIMESTAMP"
mkdir -p "$RESULTS_DIR"
log "Test artifacts will be stored in $RESULTS_DIR"

# Write metadata
cat > "$RESULTS_DIR/meta.json" <<EOF
{
  "timestamp": "$TIMESTAMP",
  "base_url": "$BASE_URL",
  "git_sha": "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)",
  "git_branch": "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
}
EOF

log "Environment setup complete."
