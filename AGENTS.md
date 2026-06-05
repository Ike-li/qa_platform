# Repository Guidelines

## Project Structure & Module Organization

Backend code lives in `src/qaplatform/`: FastAPI routes in `api/v1/`, domain logic in `domain/`, database models/repositories in `infra/database/`, worker code in `worker/`, and execution logic in `engine/`. Alembic migrations are in `alembic/`. Frontend code lives in `frontend/src/`, with components, pages, API clients, and shared types in `components/`, `pages/`, `lib/`, and `types/`. Tests are split into `tests/unit/`, `tests/integration/`, and `tests/e2e/`. Docs are in `docs/`; helper scripts are in `scripts/`.

## Build, Test, and Development Commands

- `.venv/bin/python -m pytest tests/unit -q`: run backend unit tests.
- `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration -q`: run integration tests with PostgreSQL/Redis testcontainers where needed.
- `.venv/bin/python -m ruff check src tests scripts`: lint Python.
- `.venv/bin/python scripts/export_openapi.py`: export backend OpenAPI JSON.
- `cd frontend && npm run dev`: start the Vite frontend dev server.
- `cd frontend && npm run build`: type-check and build the frontend.
- `cd frontend && npm run lint`: run frontend ESLint.
- `npm run test:e2e -- tests/e2e/auth-flow.spec.ts`: run a focused Playwright smoke from the repository root.

## Coding Style & Naming Conventions

Use Python 3.12+ with 4-space indentation, type hints, and async APIs where surrounding code is async. Keep FastAPI schemas in `api/schemas.py` or local route modules when narrowly scoped. Prefer repository/service helpers over direct SQL in routes. Frontend files generally use kebab-case filenames; React components use PascalCase. Keep generated artifacts out of commits unless intentional.

## Testing Guidelines

Use `pytest` and `pytest-asyncio` for backend tests. Name test files `test_*.py` and test functions `test_*`. Integration tests that require containers or real services must be guarded with markers/env flags such as `RUN_INTEGRATION_TESTS=1`, `heavy_docker`, `external_stack`, `performance`, or `openapi_contract`. Coverage for `qaplatform` has an 83% fail-under target.

Tests must verify the observable behavior of product code. Do not add meta-tests that assert documentation strings, ledger/registry wording, or the source text of other test files. Quality and coverage evidence belongs in the PR description and CI artifacts, not in `tests/` assertions; documentation is maintained by people, not pinned character-by-character by tests.

## Commit & Pull Request Guidelines

Recent commits use concise imperative subjects, for example `Keep backend gates importable under CI parity`. Keep commits focused and avoid mixing unrelated frontend, backend, and docs churn. PRs should describe behavior changes, list commands run, link issues or tasks, and include screenshots for visible UI changes. Note skipped tests, required environment variables, and follow-up risks.

## Security & Configuration Tips

Configuration is loaded through `QAP_*` environment variables; do not commit real secrets. `QAP_JWT_SECRET` must be at least 32 bytes, and `QAP_ENCRYPTION_KEY` must be 64 hex characters. Prefer `.env.example` for documented defaults and keep local `.env` values private.
