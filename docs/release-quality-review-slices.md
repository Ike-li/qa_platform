# Release Quality Review Slices

This branch is intentionally broad because it turns the release candidate gate into an evidence gate. Review it in slices instead of as one undifferentiated diff.

## Remote Evidence

- GitHub Actions run: https://github.com/Ike-li/qa_platform/actions/runs/26615972963
- Gate profile: `release_candidate`
- Result: all jobs passed, including `Release Candidate Gate`
- Release evidence markers:
  - `performance_summary_gate_profile=release_candidate`
  - `performance_trend_validation=passed`
  - `release_candidate_oom_tests=passed`
  - `mode=release_candidate`
  - `testcase_count=10`
  - `actual_testcase_count=10`
- Backend integration gate evidence:
  - required integration: 147 tests, 0 skipped
  - heavy Docker integration: 12 tests, 0 skipped
  - external stack integration: 6 tests, 0 skipped
  - external stack performance: 2 tests, 0 skipped
  - backend performance smoke: 31 tests, 0 skipped
  - skip inventory: `total skipped: 0`

## Slice 1: Contract And CI Gate

Primary files:

- `.github/workflows/ci.yml`
- `scripts/export_openapi.py`
- `scripts/validate_backend_integration_artifacts.py`
- `tests/unit/test_frontend_api_contract.py`
- `tests/unit/test_backend_integration_artifact_validator.py`
- `tests/unit/test_release_gate_workflow.py`

Review focus:

- `workflow_dispatch` defaults to `release_candidate`.
- Release gate downloads backend, frontend contract, integration, and E2E artifacts.
- Gate fails on missing evidence, skipped tests, missing OpenAPI schema, or missing trend markers.
- E2E evidence path handling supports both flattened and nested upload-artifact layouts.

## Slice 2: Real E2E

Primary files:

- `playwright.config.ts`
- `tests/e2e/global-setup.ts`
- `tests/e2e/global-teardown.ts`
- `tests/e2e/helpers.ts`
- `tests/e2e/real-login-flow.spec.ts`
- `tests/e2e/real-run-trigger.spec.ts`
- `tests/e2e/special-regressions.spec.ts`

Review focus:

- Release candidate E2E uses real auth and real worker execution instead of mocked run progression.
- Playwright writes both JUnit and JSON evidence.
- The gate checks actual executed test counts, unexpected/flaky/skipped counts, and required specs.

## Slice 3: Worker Results And Runtime Evidence

Primary files:

- `src/qaplatform/engine/executor.py`
- `src/qaplatform/engine/docker_backend.py`
- `src/qaplatform/engine/log_stream.py`
- `src/qaplatform/worker/tasks.py`
- `src/qaplatform/infra/database/repositories/run_repo.py`
- `docker-compose.yml`
- `Dockerfile`
- `tests/integration/test_worker_execute.py`
- `tests/integration/test_oom_e2e.py`
- `tests/unit/test_engine/test_executor.py`
- `tests/unit/test_engine/test_docker_backend.py`

Review focus:

- Worker execution persists logs, artifacts, summaries, and terminal state for release evidence.
- Docker-backed execution captures aiodocker text logs and inspects OOM state robustly.
- Compose workers can reach the Docker socket and shared run workspace on GitHub runners.
- Release candidate OOM tests are required and surfaced in the final evidence manifest.

## Slice 4: Integration Skip Inventory

Primary files:

- `scripts/report_integration_skips.py`
- `tests/unit/test_integration_skip_report.py`
- `.github/workflows/ci.yml`

Review focus:

- JUnit skipped testcases are categorized into environment gates, infrastructure gates, or unknown.
- Release candidate gate requires `integration_skip_inventory=written skipped=0`.
- The latest release candidate evidence reported zero skipped tests across all integration lanes.

## Slice 5: Performance SLO Trend Gate

Primary files:

- `.github/performance-slo-manifest.json`
- `.github/performance-slo-baseline.json`
- `scripts/validate_performance_summary.py`
- `tests/integration/test_performance_smoke.py`
- `tests/unit/test_performance_summary_validator.py`

Review focus:

- Performance validation now writes `performance-trend.json`.
- Each SLO compares the current summary with a named baseline and regression budget.
- Release candidate gate requires `performance_trend_validation=passed`.

## Slice 6: Documentation And Operator Runbooks

Primary files:

- `docs/testing-strategy.md`
- `docs/testing-quality-ops.md`
- `docs/backend-test-audit.md`
- `docs/runbook.md`
- `docs/TODO.md`
- this file

Review focus:

- Testing strategy describes the release gate and evidence expectations.
- QA TODOs distinguish shipped gate coverage from remaining operational follow-up.
- This review map is the suggested split if the branch is later broken into smaller PRs.
