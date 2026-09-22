"""Manual worker-backed E2E smoke for a local QA Platform stack.

This script is intentionally aligned with the Playwright worker E2E: it uses a
small in-workspace pytest simulator so the smoke verifies the platform worker
chain without depending on a third-party repository's test layout.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import suppress
from time import monotonic

import httpx

RAW_BASE_URL = os.environ.get("QAP_API_URL", "http://localhost:8000").rstrip("/")
BASE_URL = RAW_BASE_URL if RAW_BASE_URL.endswith("/api/v1") else f"{RAW_BASE_URL}/api/v1"
ADMIN_PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD", "admin123")
GIT_URL = os.environ.get("QAP_EXTERNAL_STACK_GIT_URL", "https://github.com/octocat/Hello-World.git")
GIT_REF = os.environ.get("QAP_EXTERNAL_STACK_GIT_REF", "master")
RUN_TIMEOUT_SECONDS = int(os.environ.get("QAP_E2E_WORKER_TIMEOUT_SECONDS", "600"))
TEST_CASE_NAME = "manual_e2e_worker_smoke"
TERMINAL_STATUSES = {"done", "failed", "cancelled", "timeout"}


def _worker_setup_script() -> str:
    pytest_source = f"""from pathlib import Path
import sys

junit = "results/junit.xml"
for arg in sys.argv[1:]:
    if arg.startswith("--junitxml="):
        junit = arg.split("=", 1)[1]

path = Path(junit)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    '<testsuite name="manual-worker-smoke" tests="1" failures="0" errors="0" skipped="0">'
    '<testcase classname="manual_worker" name="{TEST_CASE_NAME}" time="0.01" />'
    "</testsuite>",
    encoding="utf-8",
)
print("===== 1 passed in 0.01s =====", flush=True)
"""
    test_source = """from pathlib import Path


def test_manual_worker_smoke():
    assert Path("pytest.py").exists()
"""
    return f"""python - <<'PY'
from pathlib import Path

workspace = Path("/workspace")
(workspace / "tests").mkdir(exist_ok=True)
(workspace / "tests" / "test_manual_worker_smoke.py").write_text({test_source!r}, encoding="utf-8")
(workspace / "pytest.py").write_text({pytest_source!r}, encoding="utf-8")
PY
"""


async def _expect_ok(response: httpx.Response, context: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"{context} failed: {response.status_code} {response.text}") from exc


async def _login(client: httpx.AsyncClient) -> None:
    print(">>> 1. Logging in...")
    response = await client.post(
        f"{BASE_URL}/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    await _expect_ok(response, "Login")
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    print("Successfully logged in.")


async def _ensure_project(client: httpx.AsyncClient) -> dict:
    print("\n>>> 2. Ensuring test project exists...")
    response = await client.get(f"{BASE_URL}/projects")
    await _expect_ok(response, "List projects")
    projects = response.json()["data"]
    project = next((p for p in projects if p["slug"] == "e2e-test-project"), None)

    if project:
        return project

    print("Creating test project...")
    response = await client.post(
        f"{BASE_URL}/projects",
        json={
            "name": "E2E Test Project",
            "slug": "e2e-test-project",
            "description": "Project for manual E2E worker verification",
            "git_url": GIT_URL,
            "git_auth_method": "none",
            "default_branch": GIT_REF,
            "root_path": ".",
            "shallow_clone": True,
            "settings": {},
        },
    )
    await _expect_ok(response, "Create project")
    return response.json()


async def _ensure_environment(client: httpx.AsyncClient, project_id: str) -> dict:
    print("\n>>> 3. Ensuring test environment exists...")
    response = await client.get(f"{BASE_URL}/projects/{project_id}/environments")
    await _expect_ok(response, "List environments")
    envs = response.json()["data"]
    env = next((e for e in envs if e["name"] == "E2E Env"), None)

    if env:
        return env

    print("Creating test environment...")
    response = await client.post(
        f"{BASE_URL}/projects/{project_id}/environments",
        json={
            "name": "E2E Env",
            "base_image": "python:3.12-alpine",
            "setup_script": _worker_setup_script(),
            "memory_mb": 512,
            "cpu_cores": 1.0,
            "network_policy": "allow",
            "env_vars": {},
            "max_artifact_size_mb": 10,
            "max_artifacts_count": 5,
        },
    )
    await _expect_ok(response, "Create environment")
    return response.json()


async def _ensure_pipeline(client: httpx.AsyncClient, project_id: str) -> dict:
    print("\n>>> 4. Ensuring test pipeline exists...")
    response = await client.get(f"{BASE_URL}/projects/{project_id}/pipelines")
    await _expect_ok(response, "List pipelines")
    pipelines = response.json()["data"]
    pipeline = next((p for p in pipelines if p["name"] == "E2E Pipeline"), None)

    if pipeline:
        return pipeline

    print("Creating test pipeline...")
    response = await client.post(
        f"{BASE_URL}/projects/{project_id}/pipelines",
        json={
            "name": "E2E Pipeline",
            "stages": [
                {
                    "name": "pytest",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {"test_path": "tests/", "args": ["-s"]},
                }
            ],
            "collectors": [
                {"plugin": "junit", "config": {"path": "results/junit.xml"}, "enabled": True}
            ],
            "selector": {"include_paths": ["tests"], "on_empty": "warn"},
            "trigger_config": {"type": "manual"},
            "timeout_seconds": 300,
            "enabled": True,
        },
    )
    await _expect_ok(response, "Create pipeline")
    return response.json()


async def _listen_logs(ticket: str, run_id: str) -> int:
    print("--- Log Stream Start ---")
    log_lines = 0
    try:
        async with httpx.AsyncClient(timeout=None) as stream_client:
            async with stream_client.stream(
                "GET",
                f"{BASE_URL}/runs/{run_id}/logs",
                params={"ticket": ticket},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if not data_str.strip():
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError as exc:
                            raise RuntimeError(
                                f"Malformed SSE log data for run {run_id}: {data_str!r}"
                            ) from exc
                        if not isinstance(data, dict) or "line" not in data:
                            raise RuntimeError(
                                f"Unexpected SSE log payload for run {run_id}: {data!r}"
                            )
                        log_lines += 1
                        print(f" {data['line']}", end="")
                    elif line.startswith("event: done"):
                        print("\n--- Log Stream Finished ---")
                        break
    except Exception as exc:
        print(f"\nSSE Stream error: {exc}")
        raise
    return log_lines


async def _wait_for_terminal_run(client: httpx.AsyncClient, run_id: str) -> dict:
    deadline = monotonic() + RUN_TIMEOUT_SECONDS
    last_run: dict | None = None

    while monotonic() < deadline:
        response = await client.get(f"{BASE_URL}/runs/{run_id}")
        await _expect_ok(response, f"Read run {run_id}")
        last_run = response.json()
        status = last_run["status"]
        print(f"Current status: {status}")
        if status in TERMINAL_STATUSES:
            return last_run
        await asyncio.sleep(5)

    raise TimeoutError(f"Run {run_id} did not reach a terminal state within {RUN_TIMEOUT_SECONDS}s: {last_run}")


async def _verify_results(client: httpx.AsyncClient, run_id: str) -> None:
    response = await client.get(f"{BASE_URL}/runs/{run_id}/results")
    await _expect_ok(response, "List run results")
    results = response.json()["data"]
    if not any(result["name"] == TEST_CASE_NAME and result["status"] == "passed" for result in results):
        raise RuntimeError(f"Expected passed result {TEST_CASE_NAME!r}, got: {results}")
    print(f"Verified passed test result: {TEST_CASE_NAME}")


async def _verify_artifacts(client: httpx.AsyncClient, run_id: str) -> None:
    print("\n>>> 8. Verifying artifacts...")
    response = await client.get(f"{BASE_URL}/runs/{run_id}/artifacts")
    await _expect_ok(response, "List run artifacts")
    artifacts = response.json()["data"]
    print(f"Found {len(artifacts)} artifacts.")

    junit_artifact = next((artifact for artifact in artifacts if artifact["name"] == "junit.xml"), None)
    if junit_artifact is None:
        raise RuntimeError(f"Expected junit.xml artifact, got: {artifacts}")

    response = await client.get(f"{BASE_URL}/artifacts/{junit_artifact['id']}/download")
    await _expect_ok(response, "Create artifact download URL")
    download_url = response.json().get("download_url")
    if not download_url:
        raise RuntimeError(f"Artifact download response did not include download_url: {response.text}")
    print(f"Verified download URL for {junit_artifact['name']}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        await _login(client)

        project = await _ensure_project(client)
        project_id = project["id"]
        print(f"Project ID: {project_id}")

        env = await _ensure_environment(client, project_id)
        env_id = env["id"]
        print(f"Environment ID: {env_id}")

        pipeline = await _ensure_pipeline(client, project_id)
        pipeline_id = pipeline["id"]
        print(f"Pipeline ID: {pipeline_id}")

        print("\n>>> 5. Triggering run...")
        response = await client.post(
            f"{BASE_URL}/runs",
            json={"pipeline_id": pipeline_id, "environment_id": env_id, "git_ref": GIT_REF},
        )
        await _expect_ok(response, "Trigger run")
        run = response.json()
        run_id = run["id"]
        print(f"Run ID: {run_id}")

        print("\n>>> 6. Getting SSE ticket...")
        response = await client.post(f"{BASE_URL}/auth/sse-ticket")
        await _expect_ok(response, "Create SSE ticket")
        ticket = response.json()["ticket"]
        print("SSE Ticket acquired.")

        print("\n>>> 7. Monitoring execution...")
        log_task = asyncio.create_task(_listen_logs(ticket, run_id))
        try:
            terminal_run = await _wait_for_terminal_run(client, run_id)
            status = terminal_run["status"]
            print(f"Final status: {status}")
            if status != "done":
                log_task.cancel()
                with suppress(asyncio.CancelledError):
                    await log_task
                raise RuntimeError(f"Expected run status 'done', got {status}: {terminal_run}")
            log_lines = await asyncio.wait_for(log_task, timeout=30)
            if log_lines == 0:
                raise RuntimeError(f"SSE log stream for run {run_id} finished without log lines")
        except asyncio.TimeoutError:
            log_task.cancel()
            with suppress(asyncio.CancelledError):
                await log_task
            raise

        await _verify_results(client, run_id)
        await _verify_artifacts(client, run_id)

        print("\nE2E Worker Verification Completed Successfully!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Script interrupted.")
        sys.exit(130)
    except Exception as exc:
        print(f"Script failed: {exc}")
        sys.exit(1)
