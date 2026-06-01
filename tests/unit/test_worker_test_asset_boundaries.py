from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKER_EXECUTE_TEST = ROOT / "tests" / "integration" / "test_worker_execute.py"
REAL_RUN_TRIGGER_SPEC = ROOT / "tests" / "e2e" / "real-run-trigger.spec.ts"
RUN_E2E_SCRIPT = ROOT / "scripts" / "run-e2e.sh"
E2E_WORKER_SCRIPT = ROOT / "scripts" / "e2e_worker_test.py"
PLAYWRIGHT_CONFIG = ROOT / "playwright.config.ts"
E2E_GLOBAL_SETUP = ROOT / "tests" / "e2e" / "global-setup.ts"
E2E_QAP_ENV = ROOT / "tests" / "e2e" / "qap-env.ts"
README = ROOT / "README.md"
DEVELOPMENT = ROOT / "docs" / "development.md"
TODO = ROOT / "docs" / "TODO.md"
FEATURE_CATALOG = ROOT / "docs" / "feature-catalog.md"


def test_worker_tests_keep_real_pytest_runner_coverage():
    source = WORKER_EXECUTE_TEST.read_text(encoding="utf-8")
    test_start = source.index("async def test_trigger_run_completes_terminal_state")
    test_end = source.index(
        "\n\n@pytest.mark.asyncio\nasync def test_real_worker_streams_live_logs_over_sse_external_stack",
        test_start,
    )
    test_block = source[test_start:test_end]

    assert "fixture_git_repo" not in source
    assert 'final_status in {"done", "failed"}' not in source
    assert "至少证明 worker 真的执行了" not in source
    assert "file://" not in test_block
    assert "git_url\": EXTERNAL_STACK_GIT_URL" in test_block
    assert "assert final_status == \"done\"" in test_block
    assert "python -m pip install pytest" in test_block
    assert "assert True" not in test_block
    assert "qap-real-pytest-marker.txt" in test_block
    assert "results_body" in test_block
    assert "junit_text" in test_block


def test_runner_simulators_are_explicitly_labelled_as_platform_chain_tests():
    worker_source = WORKER_EXECUTE_TEST.read_text(encoding="utf-8")
    e2e_source = REAL_RUN_TRIGGER_SPEC.read_text(encoding="utf-8")

    assert "runner simulator" in worker_source.lower()
    assert "runner simulator" in e2e_source.lower()
    assert "(workspace / 'pytest.py').write_text" in e2e_source
    assert "pytest.py" in worker_source


def test_run_e2e_script_enables_worker_backed_real_run_by_default():
    script = RUN_E2E_SCRIPT.read_text(encoding="utf-8")
    playwright_config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    global_setup = E2E_GLOBAL_SETUP.read_text(encoding="utf-8")
    qap_env = E2E_QAP_ENV.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    development = DEVELOPMENT.read_text(encoding="utf-8")
    todo = TODO.read_text(encoding="utf-8")
    catalog = FEATURE_CATALOG.read_text(encoding="utf-8")

    assert 'QAP_E2E_WORKER="${QAP_E2E_WORKER:-1}"' in script
    assert 'QAP_WORKER_MAX_JOBS="${QAP_WORKER_MAX_JOBS:-1}"' in script
    assert 'QAP_DATABASE_URL="${QAP_DATABASE_URL:-postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform}"' in script
    assert 'QAP_REDIS_URL="${QAP_REDIS_URL:-redis://localhost:6379/0}"' in script
    assert 'QAP_S3_BUCKET="${QAP_S3_BUCKET:-qa-platform}"' in script
    assert "export QAP_E2E_WORKER" in script
    assert "export QAP_DATABASE_URL" in script
    assert "export QAP_REDIS_URL" in script
    assert "npx playwright test tests/e2e/real-*.spec.ts" in script
    assert "applyQapE2eEnv();" in playwright_config
    assert "applyQapE2eEnv()" in global_setup
    assert "qapWorkerEnv()" in global_setup
    assert "QAP_E2E_DEFAULT_ENV" in qap_env
    assert "QAP_DATABASE_URL" in qap_env
    assert "QAP_REDIS_URL" in qap_env

    real_run_skip = REAL_RUN_TRIGGER_SPEC.read_text(encoding="utf-8")
    assert 'process.env.QAP_E2E_WORKER !== "1"' in real_run_skip

    for text in (readme, development):
        assert "E2E_ADMIN_PASSWORD=admin123 ./scripts/run-e2e.sh" in text
        assert "QAP_E2E_WORKER=1" in text
        assert "real-run-trigger" in text

    for text in (todo, catalog):
        assert "本地 `scripts/run-e2e.sh`" in text
        assert "QAP_E2E_WORKER=1" in text
        assert "QAP_WORKER_MAX_JOBS=1" in text
        assert "real-run-trigger" in text
        assert "worker gate 被跳过" in text


def test_manual_worker_smoke_fails_on_broken_log_evidence():
    script = E2E_WORKER_SCRIPT.read_text(encoding="utf-8")

    assert "with suppress(json.JSONDecodeError)" not in script
    assert "Malformed SSE log data" in script
    assert "Unexpected SSE log payload" in script
    assert "finished without log lines" in script
    assert "sys.exit(130)" in script
