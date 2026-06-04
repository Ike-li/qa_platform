# Project Memory

Last updated: 2026-06-04

## Current State

- Worktree was clean after the latest handoff commit.
- Latest API-test commits:
  - `08b4c0e Cover seeded OpenAPI success paths`
  - `df2897f Expand OpenAPI black-box API coverage`
- OpenAPI interface testing is at full matrix coverage:
  - 70/70 OpenAPI operations covered.
  - 420/420 atomic test cases covered.
  - 0 blocked, 0 missing, 0 partial.
  - Pytest collection for the OpenAPI API-test slice is 347 items.

## Important Files

- `docs/api-test-matrix.md`: current API test matrix plan, coverage status, commands, and seed-tool rules.
- `tests/api_matrix/openapi_operation_matrix.yml`: operation-level OpenAPI coverage matrix.
- `tests/api_matrix/openapi_test_case_matrix.yml`: atomic test-case matrix metadata and dimension rules.
- `tests/integration/test_openapi_contract_smoke.py`: contract/auth/declared-response smoke over the OpenAPI surface.
- `tests/integration/test_openapi_behavior_blackbox.py`: in-process black-box behavior suite.
- `tests/integration/test_openapi_real_stack_behavior.py`: compose API/worker/MinIO black-box workflow.
- `tests/support/api_data.py`: public HTTP API test-data factory.
- `tests/support/api_seed.py`: explicit test-environment seed helper for setup states that public APIs cannot create.
- `src/qaplatform/api/middleware/security_headers.py`: security header middleware now preserves route-specific headers such as artifact preview CSP.

## API Test Boundary

Default rule: behavior tests create setup data through public HTTP APIs and assert through HTTP APIs.

Explicit exception: `tests/support/api_seed.py` may seed only test-environment prerequisite state that public APIs cannot currently create. The current allowed seed cases are:

- Promote a registered test user to platform admin for `GET /api/v1/admin/status`.
- Create a second user in the same tenant for project member create/update/delete success paths.
- Serve a deterministic local HTTPS Git repository for `POST /api/v1/projects/branches`.

The seed helper must not construct the response under test. Interface calls, assertions, and cleanup checks still go through HTTP APIs.

## Last Verified Commands

```bash
.venv/bin/python -m ruff check scripts/validate_api_test_matrix.py scripts/validate_api_test_case_matrix.py tests/support/api_data.py tests/support/api_seed.py tests/integration/test_openapi_contract_smoke.py tests/integration/test_openapi_behavior_blackbox.py tests/integration/test_openapi_real_stack_behavior.py tests/integration/conftest.py tests/unit/test_release_gate_workflow.py tests/unit/test_api_test_matrix_validator.py tests/unit/test_api_test_case_matrix_validator.py
.venv/bin/python scripts/validate_api_test_matrix.py
.venv/bin/python scripts/validate_api_test_case_matrix.py
.venv/bin/python -m pytest tests/unit/test_api_test_matrix_validator.py tests/unit/test_api_test_case_matrix_validator.py tests/unit/test_frontend_api_contract.py tests/unit/test_release_gate_workflow.py -q
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_behavior_blackbox.py -q
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_contract_smoke.py -q
RUN_INTEGRATION_TESTS=1 QAP_EXTERNAL_STACK_REQUIRED=1 .venv/bin/python -m pytest tests/integration/test_openapi_real_stack_behavior.py -q
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_contract_smoke.py tests/integration/test_openapi_behavior_blackbox.py tests/integration/test_openapi_real_stack_behavior.py --collect-only -q
git diff --check
```

Verified results:

- Ruff passed.
- Matrix validators reported `operations=70 covered=70 partial=0 blocked=0`.
- Case matrix validator reported `cases=420 covered=420 blocked=0 missing=0`.
- Related unit tests: 55 passed.
- Behavior blackbox: 133 passed.
- Contract smoke: 213 passed.
- Real-stack behavior: 1 passed.
- Collect-only: 347 tests collected.

## Local Runtime Note

During handoff, compose services were still running locally and healthy:

- `api`
- `worker`
- `postgres`
- `redis`
- `minio`

The API and worker images had been rebuilt locally to include the latest source changes.
