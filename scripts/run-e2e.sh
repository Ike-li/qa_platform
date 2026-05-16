#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

wait_for_health() {
  local service="$1"
  local deadline=$((SECONDS + 120))

  while (( SECONDS < deadline )); do
    local container_id
    container_id="$(docker compose ps -q "$service")"
    if [[ -n "$container_id" ]]; then
      local state
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
      if [[ "$state" == "healthy" || "$state" == "running" ]]; then
        return 0
      fi
    fi
    sleep 1
  done

  echo "Timed out waiting for $service to become healthy" >&2
  return 1
}

wait_for_url() {
  local url="$1"
  local deadline=$((SECONDS + 120))

  while (( SECONDS < deadline )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for $url" >&2
  return 1
}

docker compose up -d postgres redis minio
wait_for_health postgres
wait_for_health redis
wait_for_health minio

.venv/bin/python -m alembic upgrade head
ADMIN_USERNAME=admin ADMIN_PASSWORD=admin123 ADMIN_EMAIL=admin@qaplatform.local .venv/bin/python scripts/seed_admin.py

.venv/bin/python -m uvicorn qaplatform.main:create_app --factory --host 0.0.0.0 --port 8000 --app-dir src &
BACKEND_PID="$!"
wait_for_url http://localhost:8000/health

(
  cd frontend
  npm run dev -- --host 0.0.0.0 --port 5173
) &
FRONTEND_PID="$!"
wait_for_url http://localhost:5173

npx playwright install chromium
npx playwright test tests/e2e/real-*.spec.ts
