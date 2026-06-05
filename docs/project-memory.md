# Project Memory

Last updated: 2026-06-05

## Current State

- Worktree contains the staged architecture refactor set for local commit; do not assume a clean tree until that commit is created.
- Refactor scope is intentionally behavior-preserving: no database migration, no public API response shape change, no OpenAPI component rename, no audit action/RBAC/error semantics change.
- Auth routes now delegate register/login/refresh/logout/API token/SSE ticket workflows to `src/qaplatform/api/auth/commands.py`; route-level refresh-cookie helper compatibility remains in place.
- Webhook routes now delegate GitHub payload parsing, repository URL candidates, branch filtering, dedup key construction, and webhook decision audit state to `src/qaplatform/api/webhook_helpers.py`.
- Run route command/presenter helpers now live under `src/qaplatform/api/run_*.py`; batch cancel/retry preserve the legacy `200 BatchRunResponse` aggregate contract and do not add per-run project RBAC checks.
- Worker schedule firing and run execution cleanup are split into `src/qaplatform/worker/schedule_firing.py` and `src/qaplatform/worker/run_execution.py`; PipelineConfig construction lives in `src/qaplatform/engine/pipeline_config_builder.py`.
- `qaplatform.api.schemas` is now a package under `src/qaplatform/api/schemas/`; `src/qaplatform/api/schemas/__init__.py` re-exports the old public names so existing imports and OpenAPI component names remain compatible.
- Frontend large project/settings components have been split into focused components/helpers under `frontend/src/components/projects/`, `frontend/src/components/settings/`, and `frontend/src/pages/projects/detail-form.ts`.
- Architecture boundary tests now lock API routes away from direct SQL, lock engine imports away from API/worker, and lock schema re-export/OpenAPI component compatibility.

## Important Files

- `docs/architecture.md`: current backend layering, route/service/helper boundaries, schema package split, and worker orchestration split.
- `docs/testing-strategy.md`: current test-layer contract and architecture boundary gates.
- `src/qaplatform/api/auth/commands.py`: auth command/service workflows used by `api/v1/auth.py`.
- `src/qaplatform/api/webhook_helpers.py`: webhook parsing/filter/dedup/audit helper surface.
- `src/qaplatform/api/run_access.py`, `src/qaplatform/api/run_commands.py`, `src/qaplatform/api/run_batch_commands.py`, `src/qaplatform/api/run_presenters.py`: run access, command, batch, and presenter helpers used by `api/v1/runs.py`.
- `src/qaplatform/api/schemas/`: grouped schema modules with `api.schemas` re-export compatibility.
- `src/qaplatform/engine/pipeline_config_builder.py`: shared PipelineConfig construction.
- `src/qaplatform/worker/schedule_firing.py` and `src/qaplatform/worker/run_execution.py`: worker orchestration helpers split out of settings/tasks.
- `tests/unit/test_architecture_boundaries.py`: architecture drift guards.
- `tests/unit/frontend_contract_helpers.py` and `tests/unit/test_frontend_api_contract.py`: OpenAPI/frontend DTO contract helpers and assertions.

## Last Verified Commands

```bash
UV_PROJECT_ENVIRONMENT=.venv-312 uv run --python 3.12 --extra test python -m pytest tests/unit/test_api/test_runs.py -q
cd frontend && npm run build
cd frontend && npm run lint
UV_PROJECT_ENVIRONMENT=.venv-312 uv run --python 3.12 --extra dev python -m ruff check src tests scripts
UV_PROJECT_ENVIRONMENT=.venv-312 uv run --python 3.12 --extra test python -m pytest tests/unit -q
rm -rf .venv-312
test -d .venv-312 && echo .venv-312-exists || echo .venv-312-removed
```

Verified results:

- Focused run API tests: 58 passed.
- Frontend build passed.
- Frontend lint passed.
- Ruff passed.
- Full backend unit suite: 1922 passed.
- Temporary `.venv-312` environment removed.

## Local Runtime Note

- No local stage/commit existed at the time this memory entry was written.
- `.venv-312` must be removed after any validation run that recreates it.
