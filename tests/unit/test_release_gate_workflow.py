from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PLAYWRIGHT_CONFIG = ROOT / "playwright.config.ts"
DOCKERFILE = ROOT / "Dockerfile"
DOCKER_COMPOSE = ROOT / "docker-compose.yml"
SLO_MANIFEST = ROOT / ".github" / "performance-slo-manifest.json"
SLO_BASELINE = ROOT / ".github" / "performance-slo-baseline.json"
E2E_DIR = ROOT / "tests" / "e2e"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job_block(text: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"{job_name} job missing"
    return match.group(0)


def test_release_candidate_gate_profiles_are_explicit():
    text = _workflow_text()

    assert "workflow_dispatch:" in text
    assert "default: release_candidate" in text
    for gate in ("pr_like", "nightly", "release_candidate"):
        assert f"- {gate}" in text
    assert "schedule:" in text

    assert "backend-integration-test:" in text
    assert "e2e-test:" in text
    assert "release-gate:" in text
    assert "name: Release Candidate Gate" in text
    assert "if: github.event_name == 'workflow_dispatch' && inputs.gate == 'release_candidate'" in text
    assert "QAP_PERFORMANCE_GATE_PROFILE" in text
    assert "github.event_name == 'workflow_dispatch' && inputs.gate || 'nightly'" in text

    for required_job in (
        "lint-and-type-check",
        "backend-test",
        "frontend-api-contract",
        "backend-integration-test",
        "frontend-build",
        "e2e-test",
    ):
        assert f"- {required_job}" in text
    assert "release_candidate_gate=passed" in text
    assert "evidence=frontend-api-contract,required-integration,heavy-docker,external-stack,performance-slo,full-playwright" in text


def test_frontend_api_contract_is_a_release_gate_job():
    text = _workflow_text()
    contract_block = _job_block(text, "frontend-api-contract")
    release_block = _job_block(text, "release-gate")

    assert "python scripts/export_openapi.py" in contract_block
    assert "pytest -q tests/unit/test_frontend_api_contract.py" in contract_block
    assert "frontend-api-contract-artifacts" in contract_block
    assert "- frontend-api-contract" in release_block


def test_ci_playwright_config_emits_actual_run_json_report():
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")

    assert '["json", { outputFile: "artifacts/e2e/playwright-run.json" }]' in config
    assert 'globalTeardown: "./tests/e2e/global-teardown.ts"' in config


def test_release_gate_validates_downloaded_evidence_markers():
    release_block = _job_block(_workflow_text(), "release-gate")

    assert "actions/download-artifact@v4" in release_block
    assert "backend-test-artifacts/evidence-manifest.txt" in release_block
    assert "frontend-api-contract-artifacts/openapi.json" in release_block
    assert "backend-integration-artifacts/evidence-manifest.txt" in release_block
    assert "e2e-artifacts/evidence-manifest.txt" in release_block
    assert "e2e-artifacts/artifacts/e2e/evidence-manifest.txt" in release_block
    for marker in (
        "backend_test_artifacts_validation=passed",
        "collect_validation=passed",
        "junit_validation=strict_skips=True",
        "integration_skip_inventory=written skipped=0",
        "nodeid_validation=passed",
        "performance_summary_gate_profile=release_candidate",
        "performance_trend_validation=passed",
        "release_candidate_oom_tests=passed",
        "mode=release_candidate",
        "failure_count=0",
        "error_count=0",
        "skipped_count=0",
        "actual_unexpected_count=0",
        "actual_flaky_count=0",
        "actual_skipped_count=0",
        "playwright_actual_run_validation=passed",
        "playwright_junit_validation=passed",
        "release_gate_frontend_api_contract=passed",
    ):
        assert marker in release_block
    assert "release-gate-evidence" in release_block


def test_release_candidate_jobs_have_realistic_time_budgets():
    text = _workflow_text()
    backend_block = _job_block(text, "backend-integration-test")
    e2e_block = _job_block(text, "e2e-test")

    assert "timeout-minutes: 90" in backend_block
    assert "timeout-minutes: 45" in e2e_block


def test_release_candidate_backend_gate_runs_real_stack_and_slo_validation():
    text = _workflow_text()
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    docker_compose = DOCKER_COMPOSE.read_text(encoding="utf-8")

    for step in (
        "Run heavy docker integration tests (nightly/release candidate)",
        "Start external API/worker stack (nightly/release candidate)",
        "Run external-stack worker integration tests (nightly/release candidate)",
        "Run external-stack worker performance smoke (nightly/release candidate)",
        "Run backend performance smoke (nightly/release candidate)",
    ):
        assert step in text

    assert '-m "heavy_docker and not external_stack"' in text
    assert '-m "external_stack and not performance"' in text
    assert '-m "external_stack and performance"' in text
    assert '-m "performance"' in text
    assert ".github/performance-slo-manifest.json" in text
    assert ".github/performance-slo-baseline.json" in text
    assert "scripts/validate_performance_summary.py" in text
    assert "scripts/report_integration_skips.py" in text
    assert "scripts/validate_backend_integration_artifacts.py" in text
    assert "QAP_DOCKER_SOCK_GROUP_ID=$(stat -c '%g' /var/run/docker.sock)" in text
    assert docker_compose.count("- /var/run/docker.sock:/var/run/docker.sock") >= 3
    assert docker_compose.count('${QAP_DOCKER_SOCK_GROUP_ID:-0}') >= 3
    assert "QAP_RUN_WORKSPACE_DIR=$PWD/.qap-workspaces" in text
    assert docker_compose.count("QAP_RUN_WORKSPACE_DIR") >= 6
    assert docker_compose.count("/tmp/qap-workspaces") >= 6
    assert "python -m alembic upgrade head" in text
    assert "python scripts/seed_admin.py" in text
    assert "COPY alembic.ini ." in dockerfile
    assert "COPY alembic/ alembic/" in dockerfile
    assert "COPY scripts/seed_admin.py scripts/seed_admin.py" in dockerfile
    assert "nodeid_validation=skipped" not in text
    assert "expected_gate_profile=\"${{ inputs.gate }}\"" in text

    for oom_test in (
        "test_executor_maps_real_oom_to_timeout_summary_and_redis",
        "test_oom_kill_sets_oom_killed_true",
        "test_normal_exit_oom_killed_false",
    ):
        assert oom_test in text
    assert "skipped_release_candidate_oom_test" in text
    assert "release_candidate_oom_tests=passed" in text


def test_release_candidate_e2e_gate_runs_all_specs_with_evidence_validation():
    text = _workflow_text()
    spec_files = sorted(path.name for path in E2E_DIR.glob("*.spec.ts"))
    real_run_spec = (E2E_DIR / "real-run-trigger.spec.ts").read_text(encoding="utf-8")

    assert {"auth-flow.spec.ts", "real-login-flow.spec.ts", "real-run-trigger.spec.ts", "special-regressions.spec.ts"} <= set(spec_files)
    assert "find tests/e2e -maxdepth 1 -name '*.spec.ts' -print | sort > artifacts/e2e/e2e-specs.txt" in text
    assert "export QAP_E2E_WORKER=1" in text
    assert "export QAP_WORKER_MAX_JOBS=1" in text
    assert "export QAP_EXTERNAL_STACK_GIT_URL=https://github.com/octocat/Hello-World.git" in text
    assert "export QAP_EXTERNAL_STACK_GIT_REF=master" in text
    assert "Pull E2E worker images (nightly/release candidate, with retry)" in text
    assert "docker pull \"$image\"" in text
    assert "python:3.12-alpine" in text
    assert "artifacts/e2e/playwright-run.json" in text
    assert "npm run test:e2e" in text
    assert "tests/e2e/auth-flow.spec.ts" in text
    assert "tests/e2e/real-login-flow.spec.ts" in text
    assert "tests/e2e/real-run-trigger.spec.ts" in text
    assert "tests/e2e/special-regressions.spec.ts" in text

    for guard in (
        "missing_release_candidate_required_e2e_spec",
        "playwright_spec_without_tests",
        "playwright_testcase_count_mismatch",
        "playwright_spec_testcase_count_mismatch",
        "playwright_spec_title_mismatch",
        "playwright_actual_count_mismatch",
        "playwright_actual_spec_count_mismatch",
        "playwright_actual_spec_title_mismatch",
        "playwright_actual_spec_full_title_mismatch",
        "playwright_actual_missing_result",
        "playwright_actual_unexpected_count",
        "playwright_actual_flaky_count",
        "playwright_actual_skipped_count",
        "playwright_actual_unexpected_result_statuses",
        "expected_junit_titles",
        "playwright_failure_count",
        "playwright_error_count",
        "playwright_skipped_count",
    ):
        assert guard in text

    assert "advanceRunToRunning" not in real_run_spec
    assert "QAP_E2E_WORKER" in real_run_spec
    assert "QAP_EXTERNAL_STACK_GIT_URL" in real_run_spec
    assert "waitForRunTerminal" in real_run_spec
    assert "testCaseName" in real_run_spec
    assert "Repository cloned successfully" in real_run_spec
    assert "Starting stage: pytest" in real_run_spec
    assert "Uploaded artifact: junit.xml" in real_run_spec
    assert "Run completed: done" in real_run_spec


def test_performance_slo_manifest_matches_ci_threshold_env():
    text = _workflow_text()
    manifest = json.loads(SLO_MANIFEST.read_text(encoding="utf-8"))
    baseline = json.loads(SLO_BASELINE.read_text(encoding="utf-8"))
    slos = manifest["slos"]
    names = {item["name"] for item in slos}
    threshold_envs = {item["threshold_env"] for item in slos}
    baseline_by_name = {item["name"]: item for item in baseline["slos"]}

    required_slos = {
        "read run API",
        "write run API",
        "trigger enqueue SLO",
        "webhook trigger enqueue SLO",
        "schedule tick enqueue SLO",
        "dequeue waiting runs SLO",
        "dequeue waiting priority preemption SLO",
        "cancel run API",
        "realtime log SSE delivery",
        "realtime status event SSE delivery",
        "artifact list API",
        "artifact download URL API",
        "audit events list API",
        "execution summary generation",
        "external stack worker end-to-end",
        "external stack worker 10 containers ready",
        "external stack worker 10 containers terminal",
    }
    assert required_slos <= names

    assert len(names) == len(slos), "SLO names must be unique"
    assert len(threshold_envs) == len(slos), "threshold env vars must be unique"
    assert set(baseline_by_name) == names
    for item in slos:
        assert isinstance(item["min_samples"], int)
        assert item["min_samples"] >= 1
        assert item["kind"]
        baseline_item = baseline_by_name[item["name"]]
        assert baseline_item["metric"] in {"elapsed_ms", "p99_ms"}
        assert baseline_item["baseline_ms"] > 0
        assert baseline_item["max_regression_ratio"] >= 1

    workflow_envs = set(re.findall(r"^      (PERF_[A-Z0-9_]+):", text, re.MULTILINE))
    assert threshold_envs <= workflow_envs
