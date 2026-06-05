# Project Memory

Last updated: 2026-06-05

## Current State

- Latest local commit: `782254a Refactor platform architecture boundaries`.
- Refactor scope remains behavior-preserving: no database migration, public API response shape change, OpenAPI component rename, audit action, RBAC, or error semantics change.
- Auth, webhook, run route, worker orchestration, pipeline config, schema package, and frontend large-component splits are in place.
- `qaplatform.api.schemas` remains the compatibility import surface; grouped schema modules live under `src/qaplatform/api/schemas/`.
- Boundary tests lock API routes away from direct SQL, engine away from API/worker, and schema/OpenAPI/frontend DTO compatibility.

## Important Files

- `docs/architecture.md`: backend layering, route/service/helper boundaries, schema package split, worker split.
- `docs/testing-strategy.md`: current test-layer contract and architecture gates.
- `src/qaplatform/api/auth/commands.py`: auth command/service workflows used by `api/v1/auth.py`.
- `src/qaplatform/api/webhook_helpers.py`: webhook parsing/filter/dedup/audit helper surface.
- `src/qaplatform/api/run_*.py`: run access, command, batch, and presenter helpers used by `api/v1/runs.py`.
- `src/qaplatform/api/schemas/`: grouped schema modules with `api.schemas` re-export compatibility.
- `src/qaplatform/engine/pipeline_config_builder.py`: shared PipelineConfig construction.
- `src/qaplatform/worker/schedule_firing.py`, `src/qaplatform/worker/run_execution.py`: worker orchestration helpers split out of settings/tasks.
- `tests/unit/test_architecture_boundaries.py`: architecture drift guards.
- `tests/unit/test_frontend_api_contract.py`: OpenAPI/frontend DTO drift guard.

## Last Verified

- Focused run API tests: 58 passed.
- Frontend build passed.
- Frontend lint passed.
- Ruff passed.
- Full backend unit suite: 1922 passed.
- Temporary `.venv-312` environment removed.

## Local Runtime Note

- `.venv-312` must be removed after any validation run that recreates it.
