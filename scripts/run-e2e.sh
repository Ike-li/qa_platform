#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_PID=""
FRONTEND_PID=""
E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-admin123}"
QAP_E2E_WORKER="${QAP_E2E_WORKER:-1}"
QAP_WORKER_MAX_JOBS="${QAP_WORKER_MAX_JOBS:-1}"
QAP_DATABASE_URL="${QAP_DATABASE_URL:-postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform}"
QAP_REDIS_URL="${QAP_REDIS_URL:-redis://localhost:6379/0}"
QAP_S3_ENDPOINT="${QAP_S3_ENDPOINT:-http://localhost:9000}"
QAP_S3_ACCESS_KEY="${QAP_S3_ACCESS_KEY:-minioadmin}"
QAP_S3_SECRET_KEY="${QAP_S3_SECRET_KEY:-minioadmin}"
QAP_S3_BUCKET="${QAP_S3_BUCKET:-qa-platform}"
QAP_S3_REGION="${QAP_S3_REGION:-us-east-1}"
QAP_JWT_SECRET="${QAP_JWT_SECRET:-ci-test-jwt-secret-not-for-production-use}"
QAP_ENCRYPTION_KEY="${QAP_ENCRYPTION_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}"
export E2E_ADMIN_PASSWORD
export QAP_E2E_WORKER
export QAP_WORKER_MAX_JOBS
export QAP_DATABASE_URL
export QAP_REDIS_URL
export QAP_S3_ENDPOINT
export QAP_S3_ACCESS_KEY
export QAP_S3_SECRET_KEY
export QAP_S3_BUCKET
export QAP_S3_REGION
export QAP_JWT_SECRET
export QAP_ENCRYPTION_KEY

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
ADMIN_USERNAME=admin ADMIN_PASSWORD="$E2E_ADMIN_PASSWORD" ADMIN_EMAIL=admin@qaplatform.local .venv/bin/python scripts/seed_admin.py

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
