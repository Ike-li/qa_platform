"""OpenAPI black-box behavior that needs a real worker/S3 stack.

This suite only uses public HTTP APIs to construct prerequisite state. It covers
the success paths that cannot be produced by the in-process integration client
without worker result ingestion and artifact/log archival.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import textwrap
import urllib.parse
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from tests.support.api_data import api_data_factory

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
    pytest.mark.heavy_docker,
    pytest.mark.external_stack,
    pytest.mark.openapi_contract,
]

BASE_URL = os.environ.get("QAP_API_URL", "http://localhost:8000")
EXTERNAL_STACK_GIT_URL = os.environ.get(
    "QAP_EXTERNAL_STACK_GIT_URL",
    "https://github.com/octocat/Hello-World.git",
)
EXTERNAL_STACK_GIT_REF = os.environ.get("QAP_EXTERNAL_STACK_GIT_REF", "master")
EXTERNAL_STACK_S3_URL = os.environ.get(
    "QAP_EXTERNAL_STACK_S3_URL",
    "http://localhost:9000",
)
REPO_ROOT = Path(__file__).resolve().parents[2]
TERMINAL_STATUSES = {"done", "failed", "cancelled", "timeout"}


@dataclass(frozen=True)
class RealStackRuns:
    headers: dict[str, str]
    project_id: str
    pass_run_id: str
    failed_run_id: str
    suffix: str
    test_suite: str
    test_name: str
    pass_run: dict
    failed_run: dict


def _external_stack_required() -> bool:
    return os.environ.get("QAP_EXTERNAL_STACK_REQUIRED") == "1"


def _skip_or_fail_external_stack(reason: str) -> None:
    if _external_stack_required():
        pytest.fail(reason)
    pytest.skip(reason)


def _compose(
    args: list[str],
    *,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["docker", "compose", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        _skip_or_fail_external_stack("docker compose is not available")
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"docker compose {' '.join(args)} timed out after {timeout}s: {exc}")

    if check and result.returncode != 0:
        pytest.fail(
            "docker compose "
            f"{' '.join(args)} failed with {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _running_compose_services() -> set[str]:
    result = _compose(
        ["ps", "--services", "--filter", "status=running"],
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        _skip_or_fail_external_stack(
            "docker compose services are not available for this external stack"
        )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


@pytest.fixture(scope="module")
def api_server_available() -> None:
    services = _running_compose_services()
    required = {"api", "postgres", "redis", "minio", "worker"}
    missing = required - services
    if missing:
        _skip_or_fail_external_stack(
            "OpenAPI real-stack behavior requires running compose services: "
            f"{', '.join(sorted(missing))}"
        )

    try:
        with httpx.Client(
            base_url=BASE_URL,
            timeout=3.0,
            trust_env=False,
        ) as client:
            response = client.get("/ready")
    except httpx.HTTPError as exc:
        _skip_or_fail_external_stack(
            f"external API stack not ready at {BASE_URL}: {exc!r}"
        )

    if response.status_code != 200:
        _skip_or_fail_external_stack(
            "external API stack not ready at "
            f"{BASE_URL}: {response.status_code} {response.text[:300]}"
        )
    try:
        body = response.json()
    except ValueError:
        _skip_or_fail_external_stack(
            "external API stack did not serve QA Platform /ready JSON at "
            f"{BASE_URL}: {response.text[:300]}"
        )
    if body.get("status") != "ok" or not isinstance(body.get("checks"), dict):
        _skip_or_fail_external_stack(
            "external API stack did not serve a healthy QA Platform /ready "
            f"response at {BASE_URL}: {body}"
        )


@pytest.fixture
async def api_client(api_server_available):
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=30.0,
        trust_env=False,
    ) as client:
        yield client


async def _wait_for_terminal(
    api_client,
    headers: dict[str, str],
    run_id: str,
    *,
    timeout_seconds: int = 240,
) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_seen = None
    while asyncio.get_event_loop().time() < deadline:
        response = await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)
        last_seen = f"{response.status_code}: {response.text[:500]}"
        if response.status_code == 200:
            body = response.json()
            if body["status"] in TERMINAL_STATUSES:
                return body
        await asyncio.sleep(3)
    pytest.fail(
        f"run {run_id} did not reach terminal within {timeout_seconds}s; "
        f"last={last_seen}"
    )


async def _poll_json(
    api_client,
    url: str,
    headers: dict[str, str],
    predicate,
    *,
    timeout_seconds: int = 60,
):
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_seen = None
    while asyncio.get_event_loop().time() < deadline:
        response = await api_client.get(url, headers=headers)
        last_seen = f"{response.status_code}: {response.text[:500]}"
        if response.status_code == 200:
            body = response.json()
            if predicate(body):
                return body
        await asyncio.sleep(2)
    pytest.fail(f"{url} did not satisfy predicate within {timeout_seconds}s; last={last_seen}")


def _artifact_names(body: dict) -> set[str]:
    return {artifact["name"] for artifact in body["data"]}


def _host_reachable_presigned_request(download_url: str) -> tuple[str, dict[str, str]]:
    parsed = urllib.parse.urlparse(download_url)
    if parsed.hostname != "minio":
        return download_url, {}

    public = urllib.parse.urlparse(EXTERNAL_STACK_S3_URL)
    request_url = urllib.parse.urlunparse(
        parsed._replace(scheme=public.scheme, netloc=public.netloc)
    )
    return request_url, {"Host": parsed.netloc}


async def _download_presigned_text(download_url: str) -> str:
    request_url, headers = _host_reachable_presigned_request(download_url)
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        response = await client.get(request_url, headers=headers)
    assert response.status_code == 200, response.text[:500]
    return response.text


def _pytest_setup_script(
    *,
    failed: bool,
    marker: str,
    with_preview_artifacts: bool,
) -> str:
    failure_node = (
        "<failure message='expected checkout to pass'>"
        "openapi real-stack failure"
        "</failure>"
        if failed
        else ""
    )
    junit_xml = (
        "<testsuite name='openapi-real-stack' tests='1' "
        f"failures='{1 if failed else 0}' errors='0' skipped='0'>"
        "<testcase classname='openapi_real_stack' "
        "name='test_flaky_checkout' time='0.02'>"
        f"{failure_node}"
        "</testcase>"
        "</testsuite>"
    )
    artifact_lines = ""
    if with_preview_artifacts:
        artifact_lines = f"""
(path.parent / 'html').mkdir(exist_ok=True)
(path.parent / 'html' / 'report.html').write_text(
    '<html>openapi-real-stack-report-{marker}</html>'
)
(path.parent / 'logs').mkdir(exist_ok=True)
(path.parent / 'logs' / 'trace.txt').write_text('openapi-real-stack-trace-{marker}')
(path.parent / 'allure-report').mkdir(exist_ok=True)
(path.parent / 'allure-report' / 'index.html').write_text(
    '<html>openapi-real-stack-allure-{marker}</html>'
)
"""

    runner_source = f"""from pathlib import Path
import sys

junit = "results/junit.xml"
for arg in sys.argv[1:]:
    if arg.startswith("--junitxml="):
        junit = arg.split("=", 1)[1]
path = Path(junit)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text({junit_xml!r})
{artifact_lines}
print("openapi-real-stack-marker={marker}", flush=True)
print("===== 1 {'failed' if failed else 'passed'} in 0.02s =====", flush=True)
raise SystemExit({1 if failed else 0})
"""
    return textwrap.dedent(
        f"""\
        python - <<'PY'
        from pathlib import Path

        workspace = Path('/workspace')
        (workspace / 'tests').mkdir(exist_ok=True)
        (workspace / 'tests' / 'test_openapi_real_stack.py').write_text(
            'def test_openapi_real_stack_placeholder():\\n'
            '    assert True\\n'
        )
        (workspace / 'pytest.py').write_text({runner_source!r})
        PY
        """
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def real_stack_runs(api_server_available) -> AsyncIterator[RealStackRuns]:
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=30.0,
        trust_env=False,
    ) as setup_client:
        async with api_data_factory(setup_client) as api_data:
            actor = await api_data.register_actor("real_stack")
            headers = actor.headers
            suffix = os.urandom(4).hex()
            test_suite = "openapi_real_stack"
            test_name = "test_flaky_checkout"

            project = await api_data.create_project(
                headers=headers,
                prefix="openapi-real-stack",
                git_url=EXTERNAL_STACK_GIT_URL,
                payload_overrides={
                    "name": f"OpenAPI Real Stack {suffix}",
                    "slug": f"openapi-real-stack-{suffix}",
                    "default_branch": EXTERNAL_STACK_GIT_REF,
                },
            )
            project_id = project["id"]

            pass_environment = await api_data.create_environment(
                headers=headers,
                project_id=project_id,
                name="OpenAPI Real Stack Passed Env",
                payload_overrides={
                    "base_image": "python:3.12-alpine",
                    "memory_mb": 512,
                    "cpu_cores": 1.0,
                    "network_policy": "allow",
                    "setup_script": _pytest_setup_script(
                        failed=False,
                        marker=f"passed-{suffix}",
                        with_preview_artifacts=True,
                    ),
                    "max_artifact_size_mb": 10,
                    "max_artifacts_count": 8,
                },
            )
            pass_env_id = pass_environment["id"]

            fail_environment = await api_data.create_environment(
                headers=headers,
                project_id=project_id,
                name="OpenAPI Real Stack Failed Env",
                payload_overrides={
                    "base_image": "python:3.12-alpine",
                    "memory_mb": 512,
                    "cpu_cores": 1.0,
                    "network_policy": "allow",
                    "setup_script": _pytest_setup_script(
                        failed=True,
                        marker=f"failed-{suffix}",
                        with_preview_artifacts=False,
                    ),
                    "max_artifact_size_mb": 10,
                    "max_artifacts_count": 2,
                },
            )
            fail_env_id = fail_environment["id"]

            pipeline = await api_data.create_pipeline(
                headers=headers,
                project_id=project_id,
                name="OpenAPI Real Stack Pipeline",
                payload_overrides={
                    "stages": [
                        {
                            "name": "pytest",
                            "plugin": "pytest",
                            "phase": "execute",
                            "config": {"test_path": "tests/"},
                        }
                    ],
                    "collectors": [{"plugin": "junit", "config": {}, "enabled": True}],
                    "timeout_seconds": 300,
                    "selector": {"include_paths": ["tests"], "on_empty": "warn"},
                    "trigger_config": {"type": "manual"},
                    "enabled": True,
                },
            )
            pipeline_id = pipeline["id"]

            pass_trigger_resp = await setup_client.post(
                "/api/v1/runs",
                headers=headers,
                json={
                    "pipeline_id": pipeline_id,
                    "environment_id": pass_env_id,
                    "git_ref": EXTERNAL_STACK_GIT_REF,
                    "priority": 1,
                },
            )
            assert pass_trigger_resp.status_code == 201, pass_trigger_resp.text
            pass_run_id = pass_trigger_resp.json()["id"]
            pass_run = await _wait_for_terminal(setup_client, headers, pass_run_id)

            fail_trigger_resp = await setup_client.post(
                "/api/v1/runs",
                headers=headers,
                json={
                    "pipeline_id": pipeline_id,
                    "environment_id": fail_env_id,
                    "git_ref": EXTERNAL_STACK_GIT_REF,
                    "priority": 1,
                },
            )
            assert fail_trigger_resp.status_code == 201, fail_trigger_resp.text
            failed_run_id = fail_trigger_resp.json()["id"]
            failed_run = await _wait_for_terminal(
                setup_client,
                headers,
                failed_run_id,
            )

            yield RealStackRuns(
                headers=headers,
                project_id=project_id,
                pass_run_id=pass_run_id,
                failed_run_id=failed_run_id,
                suffix=suffix,
                test_suite=test_suite,
                test_name=test_name,
                pass_run=pass_run,
                failed_run=failed_run,
            )


@pytest.mark.asyncio
async def test_real_stack_run_results_success(real_stack_runs: RealStackRuns):
    pass_run = real_stack_runs.pass_run
    assert pass_run["status"] == "done"
    assert pass_run["summary"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "error": 0,
        "pass_rate": 1.0,
    }

    failed_run = real_stack_runs.failed_run
    assert failed_run["status"] == "failed"
    assert failed_run["summary"]["total"] == 1
    assert failed_run["summary"]["failed"] == 1
    assert failed_run["summary"]["failed_tests"] == [
        {
            "suite": real_stack_runs.test_suite,
            "name": real_stack_runs.test_name,
            "status": "failed",
        }
    ]


@pytest.mark.asyncio
async def test_real_stack_artifact_download_and_preview_success(
    api_client,
    real_stack_runs: RealStackRuns,
):
    pass_run_id = real_stack_runs.pass_run_id
    headers = real_stack_runs.headers
    artifacts_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{pass_run_id}/artifacts",
        headers,
        lambda body: _artifact_names(body)
        >= {
            "junit.xml",
            "html/report.html",
            "logs/trace.txt",
            "allure-report/index.html",
        },
    )
    artifacts_by_name = {artifact["name"]: artifact for artifact in artifacts_body["data"]}
    allure_artifact = artifacts_by_name["allure-report/index.html"]
    assert allure_artifact["type"] == "allure-report"
    assert allure_artifact["storage_path"] == (
        f"reports/{pass_run_id}/allure-report/index.html"
    )

    allure_resp = await api_client.get(
        f"/api/v1/runs/{pass_run_id}/artifacts/allure-report",
        headers=headers,
    )
    assert allure_resp.status_code == 200, allure_resp.text
    assert allure_resp.json()["id"] == allure_artifact["id"]

    download_resp = await api_client.get(
        f"/api/v1/artifacts/{allure_artifact['id']}/download",
        headers=headers,
    )
    assert download_resp.status_code == 200, download_resp.text
    download_body = download_resp.json()
    assert download_body["expires_in"] > 0
    assert download_body["download_url"].startswith(("http://", "https://"))
    downloaded_text = await _download_presigned_text(download_body["download_url"])
    assert f"openapi-real-stack-allure-passed-{real_stack_runs.suffix}" in (
        downloaded_text
    )

    preview_url_resp = await api_client.get(
        f"/api/v1/artifacts/{allure_artifact['id']}/preview-url",
        headers=headers,
    )
    assert preview_url_resp.status_code == 200, preview_url_resp.text
    preview_url_body = preview_url_resp.json()
    assert preview_url_body["expires_in"] > 0
    preview_url = preview_url_body["preview_url"]
    assert f"/api/v1/artifacts/{allure_artifact['id']}/preview/" in preview_url
    assert preview_url.endswith("/index.html")

    preview_resp = await api_client.get(preview_url)
    assert preview_resp.status_code == 200, preview_resp.text[:500]
    assert preview_resp.headers["content-type"].startswith("text/html")
    assert preview_resp.headers["x-content-type-options"] == "nosniff"
    assert "sandbox allow-scripts allow-downloads" in (
        preview_resp.headers["content-security-policy"]
    )
    assert f"openapi-real-stack-allure-passed-{real_stack_runs.suffix}" in (
        preview_resp.text
    )


@pytest.mark.asyncio
async def test_real_stack_archived_logs_success(
    api_client,
    real_stack_runs: RealStackRuns,
):
    pass_run_id = real_stack_runs.pass_run_id
    headers = real_stack_runs.headers
    archive_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{pass_run_id}/logs/archive",
        headers,
        lambda body: any(
            entry["line"]
            == f"openapi-real-stack-marker=passed-{real_stack_runs.suffix}"
            for entry in body.get("data", [])
        ),
    )
    assert archive_body["page"] == 1
    assert archive_body["per_page"] == 100
    assert archive_body["total"] >= len(archive_body["data"]) >= 1


@pytest.mark.asyncio
async def test_real_stack_analytics_success(
    api_client,
    real_stack_runs: RealStackRuns,
):
    headers = real_stack_runs.headers
    project_id = real_stack_runs.project_id
    pass_run_id = real_stack_runs.pass_run_id
    failed_run_id = real_stack_runs.failed_run_id
    test_suite = real_stack_runs.test_suite
    test_name = real_stack_runs.test_name

    trends_resp = await api_client.get(
        f"/api/v1/projects/{project_id}/analytics/trends",
        headers=headers,
        params={"days": 30},
    )
    assert trends_resp.status_code == 200, trends_resp.text
    trend_points = trends_resp.json()["data"]
    assert sum(point["total_runs"] for point in trend_points) == 2
    assert sum(point["passed_runs"] for point in trend_points) == 1
    assert sum(point["failed_runs"] for point in trend_points) == 1

    flaky_resp = await api_client.get(
        f"/api/v1/projects/{project_id}/analytics/flaky",
        headers=headers,
        params={"days": 30, "min_runs": 2},
    )
    assert flaky_resp.status_code == 200, flaky_resp.text
    assert flaky_resp.json() == {
        "data": [
            {
                "suite": test_suite,
                "name": test_name,
                "total_runs": 2,
                "passed_count": 1,
                "failed_count": 1,
                "flaky_rate": 0.5,
            }
        ],
        "pagination": {"offset": 0, "limit": 50, "total": 1},
    }

    history_resp = await api_client.get(
        f"/api/v1/projects/{project_id}/analytics/test-history",
        headers=headers,
        params={"suite": test_suite, "name": test_name, "days": 30},
    )
    assert history_resp.status_code == 200, history_resp.text
    history_body = history_resp.json()
    assert history_body["pagination"] == {"offset": 0, "limit": 50, "total": 2}
    history_by_run = {point["run_id"]: point for point in history_body["data"]}
    assert set(history_by_run) == {pass_run_id, failed_run_id}
    assert history_by_run[pass_run_id]["run_status"] == "done"
    assert history_by_run[pass_run_id]["status"] == "passed"
    assert history_by_run[pass_run_id]["duration_ms"] == 20
    assert history_by_run[pass_run_id]["git_ref"] == EXTERNAL_STACK_GIT_REF
    assert history_by_run[failed_run_id]["run_status"] == "failed"
    assert history_by_run[failed_run_id]["status"] == "failed"
    assert history_by_run[failed_run_id]["duration_ms"] == 20
    assert history_by_run[failed_run_id]["error_message"] == (
        "expected checkout to pass"
    )
    assert history_by_run[failed_run_id]["git_ref"] == EXTERNAL_STACK_GIT_REF

    summary_resp = await api_client.get(
        f"/api/v1/projects/{project_id}/analytics/release-summary",
        headers=headers,
        params={
            "days": 30,
            "git_ref": EXTERNAL_STACK_GIT_REF,
            "baseline_git_ref": EXTERNAL_STACK_GIT_REF,
        },
    )
    assert summary_resp.status_code == 200, summary_resp.text
    assert summary_resp.json() == {
        "git_ref": EXTERNAL_STACK_GIT_REF,
        "baseline_git_ref": EXTERNAL_STACK_GIT_REF,
        "total_runs": 2,
        "passed_runs": 1,
        "failed_runs": 1,
        "raw_pass_rate": 0.5,
        "flaky_adjusted_pass_rate": None,
        "new_failing_tests": [],
        "recovered_tests": [],
    }
