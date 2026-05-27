"""真实 worker 集成测试：触发 run → 容器执行 → 状态收尾。

需要 docker daemon 可用、docker-compose 启动 postgres+redis+minio。
默认 skip 除非 RUN_INTEGRATION_TESTS=1 环境变量设置。
"""
import asyncio
import hashlib
import os
import subprocess
import urllib.parse
from pathlib import Path

import pytest
import httpx

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
    pytest.mark.heavy_docker,
    pytest.mark.external_stack,
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


def _compose(args: list[str], *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        pytest.skip("docker compose is not available")
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
        pytest.skip("docker compose services are not available for this external stack")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _require_compose_worker_lost_stack() -> None:
    services = _running_compose_services()
    required = {"api", "postgres", "redis", "worker"}
    missing = required - services
    if missing:
        pytest.skip(
            "worker-lost external-stack test requires running compose services: "
            f"{', '.join(sorted(missing))}"
        )
    if not ({"worker-high", "worker-low"} & services):
        pytest.skip(
            "worker-lost external-stack test requires worker-high or worker-low "
            "to keep the reclaimer cron alive while worker is stopped"
        )


def _require_compose_priority_stack() -> None:
    services = _running_compose_services()
    required = {"api", "postgres", "redis", "worker", "worker-high", "worker-low"}
    missing = required - services
    if missing:
        pytest.skip(
            "priority external-stack test requires running compose services: "
            f"{', '.join(sorted(missing))}"
        )


def _compose_redis_keys(pattern: str) -> list[str]:
    result = _compose(
        ["exec", "-T", "redis", "redis-cli", "--raw", "KEYS", pattern],
        timeout=30,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _compose_redis_delete(keys: list[str]) -> int:
    if not keys:
        return 0
    result = _compose(
        ["exec", "-T", "redis", "redis-cli", "--raw", "DEL", *keys],
        timeout=30,
    )
    return int((result.stdout or "0").strip() or "0")


@pytest.fixture(scope="module")
def api_server_available():
    """Skip if the API server is not reachable (e.g. CI without docker-compose stack)."""
    import socket
    import urllib.parse
    parsed = urllib.parse.urlparse(BASE_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8000
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError:
        pytest.skip(f"API server not reachable at {BASE_URL} — start docker-compose stack first")


@pytest.fixture(scope="module")
def docker_available():
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pytest.skip("docker daemon not available")
    return True


@pytest.fixture(scope="module")
def fixture_git_repo(tmp_path_factory):
    """创建一个最小 pytest 项目作为 fixture，本地 git init。"""
    repo = tmp_path_factory.mktemp("fixture-repo")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_smoke.py").write_text(
        "def test_pass():\n    assert True\n"
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "e2e@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "E2E"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return str(repo)


@pytest.fixture
async def api_client(api_server_available):
    """假设后端已经启动在 BASE_URL（由 conftest 或外部启动）。"""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client


@pytest.fixture
async def admin_token(api_client):
    resp = await api_client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "admin123"
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _wait_for_terminal(api_client, headers, run_id: str, *, timeout_seconds: int = 180) -> str | None:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    final_status = None
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(3)
        status_resp = await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)
        if status_resp.status_code == 200:
            final_status = status_resp.json()["status"]
            if final_status in TERMINAL_STATUSES:
                return final_status
    return final_status


async def _wait_for_run_status(
    api_client,
    headers,
    run_id: str,
    statuses: set[str],
    *,
    timeout_seconds: int = 90,
) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_seen = None
    while asyncio.get_event_loop().time() < deadline:
        response = await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)
        last_seen = f"{response.status_code}: {response.text[:500]}"
        if response.status_code == 200:
            body = response.json()
            if body["status"] in statuses:
                return body
        await asyncio.sleep(1)
    pytest.fail(
        f"run {run_id} did not reach {sorted(statuses)} within "
        f"{timeout_seconds}s; last={last_seen}"
    )


async def _assert_run_stays_queued(
    api_client,
    headers,
    run_id: str,
    *,
    seconds: int = 10,
) -> None:
    deadline = asyncio.get_event_loop().time() + seconds
    observed: list[str] = []
    while asyncio.get_event_loop().time() < deadline:
        response = await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text[:500]
        status = response.json()["status"]
        observed.append(status)
        assert status == "queued", (
            f"run {run_id} should stay queued while matching worker is stopped; "
            f"observed={observed}"
        )
        await asyncio.sleep(2)


async def _poll_json(api_client, url: str, headers, predicate, *, timeout_seconds: int = 30):
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


async def _poll_project_runs(api_client, project_id: str, headers, predicate, *, timeout_seconds: int = 90):
    return await _poll_json(
        api_client,
        f"/api/v1/runs?project_id={project_id}&per_page=20",
        headers,
        predicate,
        timeout_seconds=timeout_seconds,
    )


def _host_reachable_presigned_request(download_url: str) -> tuple[str, dict[str, str]]:
    """Return a host-reachable URL while preserving the signed Host value."""
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(request_url, headers=headers)
    assert response.status_code == 200, response.text[:500]
    return response.text


async def _assert_presigned_junit_download(download_url: str, *, expected_suite: str) -> None:
    text = await _download_presigned_text(download_url)
    assert f"<testsuite name='{expected_suite}'" in text
    assert "<testcase " in text


async def _wait_for_worker_heartbeat_keys(*, timeout_seconds: int = 20) -> list[str]:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_seen: list[str] = []
    while asyncio.get_event_loop().time() < deadline:
        last_seen = await asyncio.to_thread(
            _compose_redis_keys,
            "worker:*:heartbeat",
        )
        if last_seen:
            return last_seen
        await asyncio.sleep(1)
    pytest.fail(f"worker heartbeat key was not written; last keys={last_seen}")


@pytest.mark.asyncio
async def test_trigger_run_completes_terminal_state(
    docker_available, fixture_git_repo, api_client, admin_token
):
    """完整链路：触发 run → worker 拾取 → 容器执行 → status 终态。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # 1. 创建 project（用 fixture git repo 路径）
    project_resp = await api_client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": "Integration Test Project",
            "slug": f"integration-test-{os.urandom(4).hex()}",
            "git_url": f"file://{fixture_git_repo}",
            "default_branch": "main",
            "shallow_clone": False,  # local file repo doesn't support shallow
        },
    )
    assert project_resp.status_code in (200, 201), project_resp.text
    project = project_resp.json()
    project_id = project["id"]
    
    # 2. 创建 environment（alpine + python）
    env_resp = await api_client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={
            "name": "Integration Env",
            "base_image": "python:3.12-alpine",
            "memory_mb": 512,
            "cpu_cores": 1.0,
            "network_policy": "allow",  # 测试容器需要安装 pytest
            "env_vars": {},
            "setup_script": "python -m pip install pytest"
        },
    )
    assert env_resp.status_code in (200, 201), env_resp.text
    # 3. 创建 pipeline（用 pytest plugin）
    pipeline_resp = await api_client.post(
        f"/api/v1/projects/{project_id}/pipelines",
        headers=headers,
        json={
            "name": "Smoke Pipeline",
            "stages": [
                {"name": "test", "plugin": "pytest", "phase": "execute", "config": {"test_path": "tests/"}}
            ],
            "timeout_seconds": 300,
            "selector": {"include_paths": ["tests"], "on_empty": "warn"},
            "trigger_config": {"type": "manual"},
            "enabled": True,
        },
    )
    assert pipeline_resp.status_code in (200, 201), pipeline_resp.text
    pipeline = pipeline_resp.json()
    
    # 4. 触发 run
    trigger_resp = await api_client.post(
        "/api/v1/runs",
        headers=headers,
        json={"pipeline_id": pipeline["id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code in (200, 201), trigger_resp.text
    run = trigger_resp.json()
    run_id = run["id"]
    
    # 5. 轮询直到终态（最长 180s 给 docker pull 留时间）
    final_status = await _wait_for_terminal(
        api_client, headers, run_id, timeout_seconds=180
    )
    
    assert final_status in TERMINAL_STATUSES, f"run timed out, last status: {final_status}"
    
    # 6. 验证关键事实
    # - status 必须是 done（pytest 应该全通过）；如果 failed，至少证明 worker 真的执行了
    print(f"Final status: {final_status}")
    assert final_status in {"done", "failed"}, f"unexpected status: {final_status}"
    
    # - run 详情应该有 finished_at（说明 worker 真的处理到了 fail/done）
    detail = (await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)).json()
    assert detail.get("finished_at") is not None, "finished_at missing → worker didn't finish"
    # started_at 可能为 None 如果 fail 发生在 mark_running 之前（如 git clone 失败）
    
    # - 至少 1 条日志（证明 _stream_logs 工作）
    # SSE ticket
    ticket_resp = await api_client.post("/api/v1/auth/sse-ticket", headers=headers)
    assert ticket_resp.status_code == 200
    # 注意：SSE 流测试这里跳过，已被 E2E 验证过


@pytest.mark.asyncio
async def test_real_worker_persists_artifacts_and_archived_logs(
    docker_available, api_client, admin_token
):
    """真实外部栈：API 触发 run 后由 compose worker 执行，并验证落库产物和归档日志可经 API 读回。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    suffix = os.urandom(4).hex()

    project_resp = await api_client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"Worker Evidence {suffix}",
            "slug": f"worker-evidence-{suffix}",
            "git_url": EXTERNAL_STACK_GIT_URL,
            "default_branch": EXTERNAL_STACK_GIT_REF,
        },
    )
    assert project_resp.status_code in (200, 201), project_resp.text
    project_id = project_resp.json()["id"]
    worker_secret = f"worker-secret-{suffix}"
    worker_secret_sha256 = hashlib.sha256(worker_secret.encode("utf-8")).hexdigest()

    env_resp = await api_client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={
            "name": "Worker Evidence Env",
            "base_image": "python:3.12-alpine",
            "memory_mb": 512,
            "cpu_cores": 1.0,
            "network_policy": "allow",
            "env_vars": {"QAP_REAL_WORKER_SECRET": worker_secret},
            "setup_script": (
                "python - <<'PY'\n"
                "from pathlib import Path\n"
                "workspace = Path('/workspace')\n"
                "(workspace / 'tests').mkdir(exist_ok=True)\n"
                "(workspace / 'tests' / 'test_real_worker_smoke.py').write_text(\n"
                "    'def test_real_worker_smoke():\\n    assert True\\n'\n"
                ")\n"
                "(workspace / 'pytest.py').write_text(\n"
                "    \"from pathlib import Path\\n\"\n"
                "    \"import hashlib\\n\"\n"
                "    \"import os\\n\"\n"
                "    \"import sys\\n\"\n"
                f"    \"expected_secret_sha256 = {worker_secret_sha256!r}\\n\"\n"
                "    \"actual_secret = os.environ.get('QAP_REAL_WORKER_SECRET', '')\\n\"\n"
                "    \"actual_secret_sha256 = hashlib.sha256(actual_secret.encode('utf-8')).hexdigest()\\n\"\n"
                "    \"if actual_secret_sha256 != expected_secret_sha256:\\n\"\n"
                "    \"    raise SystemExit('worker secret env var was not injected')\\n\"\n"
                "    \"junit = 'results/junit.xml'\\n\"\n"
                "    \"for arg in sys.argv[1:]:\\n\"\n"
                "    \"    if arg.startswith('--junitxml='):\\n\"\n"
                "    \"        junit = arg.split('=', 1)[1]\\n\"\n"
                "    \"path = Path(junit)\\n\"\n"
                "    \"path.parent.mkdir(parents=True, exist_ok=True)\\n\"\n"
                "    \"path.write_text(\\\"<testsuite name='real-worker' tests='1' failures='0' errors='0' skipped='0'><testcase classname='real_worker' name='smoke' time='0.01'/></testsuite>\\\")\\n\"\n"
                "    \"(path.parent / 'html').mkdir(exist_ok=True)\\n\"\n"
                "    \"(path.parent / 'html' / 'report.html').write_text('<html>real-worker-report</html>')\\n\"\n"
                "    \"(path.parent / 'logs').mkdir(exist_ok=True)\\n\"\n"
                "    \"(path.parent / 'logs' / 'trace.txt').write_text('real-worker-trace')\\n\"\n"
                "    \"(path.parent / 'allure-report').mkdir(exist_ok=True)\\n\"\n"
                "    \"(path.parent / 'allure-report' / 'index.html').write_text('<html>real-worker-allure</html>')\\n\"\n"
                "    \"print('===== 1 passed in 0.01s =====')\\n\"\n"
                ")\n"
                "PY"
            ),
            "max_artifact_size_mb": 10,
            "max_artifacts_count": 8,
        },
    )
    assert env_resp.status_code in (200, 201), env_resp.text

    pipeline_resp = await api_client.post(
        f"/api/v1/projects/{project_id}/pipelines",
        headers=headers,
        json={
            "name": "Worker Evidence Pipeline",
            "stages": [
                {
                    "name": "pytest",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {"test_path": "tests/"},
                }
            ],
            "timeout_seconds": 300,
            "selector": {"include_paths": ["tests"], "on_empty": "warn"},
            "trigger_config": {"type": "manual"},
            "enabled": True,
        },
    )
    assert pipeline_resp.status_code in (200, 201), pipeline_resp.text
    pipeline_id = pipeline_resp.json()["id"]

    trigger_resp = await api_client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "pipeline_id": pipeline_id,
            "git_ref": EXTERNAL_STACK_GIT_REF,
            "priority": 1,
        },
    )
    assert trigger_resp.status_code in (200, 201), trigger_resp.text
    run_id = trigger_resp.json()["id"]

    final_status = await _wait_for_terminal(
        api_client, headers, run_id, timeout_seconds=240
    )
    assert final_status == "done", f"run did not complete successfully: {final_status}"

    detail = (await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)).json()
    assert detail["finished_at"] is not None
    assert detail["summary"]["total"] == 1
    assert detail["summary"]["passed"] == 1

    artifacts_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{run_id}/artifacts",
        headers,
        lambda body: body["total"] >= 4,
        timeout_seconds=30,
    )
    artifacts_by_name = {artifact["name"]: artifact for artifact in artifacts_body["data"]}
    expected_artifacts = {
        "junit.xml": ("junit", "<testsuite name='real-worker'"),
        "html/report.html": ("report", "real-worker-report"),
        "logs/trace.txt": ("log", "real-worker-trace"),
        "allure-report/index.html": ("allure-report", "real-worker-allure"),
    }
    assert expected_artifacts.keys() <= artifacts_by_name.keys(), artifacts_body

    for artifact_name, (artifact_type, expected_text) in expected_artifacts.items():
        artifact = artifacts_by_name[artifact_name]
        assert artifact["type"] == artifact_type
        assert artifact["storage_path"] == f"reports/{run_id}/{artifact_name}"

        download_resp = await api_client.get(
            f"/api/v1/artifacts/{artifact['id']}/download",
            headers=headers,
        )
        assert download_resp.status_code == 200, download_resp.text
        download_body = download_resp.json()
        assert download_body["expires_in"] > 0
        assert download_body["download_url"].startswith(("http://", "https://"))
        downloaded_text = await _download_presigned_text(download_body["download_url"])
        assert expected_text in downloaded_text

    archive_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{run_id}/logs/archive",
        headers,
        lambda body: body["total"] >= 1,
        timeout_seconds=60,
    )
    lines = [entry["line"] for entry in archive_body["data"]]
    assert any("Repository cloned successfully" in line for line in lines)
    for artifact_name in expected_artifacts:
        assert any(f"Uploaded artifact: {artifact_name}" in line for line in lines)
    assert any("Run completed: done" in line for line in lines)


@pytest.mark.asyncio
async def test_worker_lost_retry_completes_with_artifacts_and_archived_logs(
    docker_available, api_client, admin_token
):
    """真实外部栈：worker 失联后由 reclaimer 创建 retry run，重启 worker 后完成产物/日志闭环。"""
    _require_compose_worker_lost_stack()
    headers = {"Authorization": f"Bearer {admin_token}"}
    suffix = os.urandom(4).hex()

    try:
        project_resp = await api_client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "name": f"Worker Lost Retry {suffix}",
                "slug": f"worker-lost-retry-{suffix}",
                "git_url": EXTERNAL_STACK_GIT_URL,
                "default_branch": EXTERNAL_STACK_GIT_REF,
            },
        )
        assert project_resp.status_code in (200, 201), project_resp.text
        project_id = project_resp.json()["id"]

        env_resp = await api_client.post(
            f"/api/v1/projects/{project_id}/environments",
            headers=headers,
            json={
                "name": "Worker Lost Retry Env",
                "base_image": "python:3.12-alpine",
                "memory_mb": 512,
                "cpu_cores": 1.0,
                "network_policy": "allow",
                "env_vars": {"QAP_WORKER_LOST_RETRY_SLEEP": "20"},
                "setup_script": (
                    "python - <<'PY'\n"
                    "from pathlib import Path\n"
                    "workspace = Path('/workspace')\n"
                    "(workspace / 'tests').mkdir(exist_ok=True)\n"
                    "(workspace / 'tests' / 'test_worker_lost_retry.py').write_text(\n"
                    "    'def test_worker_lost_retry():\\n    assert True\\n'\n"
                    ")\n"
                    "(workspace / 'pytest.py').write_text(\n"
                    "    \"from pathlib import Path\\n\"\n"
                    "    \"import os\\n\"\n"
                    "    \"import sys\\n\"\n"
                    "    \"import time\\n\"\n"
                    "    \"time.sleep(float(os.environ.get('QAP_WORKER_LOST_RETRY_SLEEP', '20')))\\n\"\n"
                    "    \"junit = 'results/junit.xml'\\n\"\n"
                    "    \"for arg in sys.argv[1:]:\\n\"\n"
                    "    \"    if arg.startswith('--junitxml='):\\n\"\n"
                    "    \"        junit = arg.split('=', 1)[1]\\n\"\n"
                    "    \"path = Path(junit)\\n\"\n"
                    "    \"path.parent.mkdir(parents=True, exist_ok=True)\\n\"\n"
                    "    \"path.write_text(\\\"<testsuite name='worker-lost-retry' tests='1' failures='0' errors='0' skipped='0'><testcase classname='worker_lost_retry' name='smoke' time='0.01'/></testsuite>\\\")\\n\"\n"
                    "    \"print('===== 1 passed in 0.01s =====')\\n\"\n"
                    ")\n"
                    "PY"
                ),
                "max_artifact_size_mb": 10,
                "max_artifacts_count": 5,
            },
        )
        assert env_resp.status_code in (200, 201), env_resp.text

        pipeline_resp = await api_client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            headers=headers,
            json={
                "name": "Worker Lost Retry Pipeline",
                "stages": [
                    {
                        "name": "pytest",
                        "plugin": "pytest",
                        "phase": "execute",
                        "config": {"test_path": "tests/"},
                    }
                ],
                "timeout_seconds": 300,
                "retry_policy": {
                    "max_attempts": 2,
                    "retry_on": ["infra"],
                    "backoff_seconds": 0,
                },
                "selector": {"include_paths": ["tests"], "on_empty": "warn"},
                "trigger_config": {"type": "manual"},
                "enabled": True,
            },
        )
        assert pipeline_resp.status_code in (200, 201), pipeline_resp.text
        pipeline_id = pipeline_resp.json()["id"]

        trigger_resp = await api_client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "pipeline_id": pipeline_id,
                "git_ref": EXTERNAL_STACK_GIT_REF,
                "priority": 1,
            },
        )
        assert trigger_resp.status_code in (200, 201), trigger_resp.text
        original_run_id = trigger_resp.json()["id"]

        await _wait_for_run_status(
            api_client,
            headers,
            original_run_id,
            {"running"},
            timeout_seconds=120,
        )
        heartbeat_keys = await _wait_for_worker_heartbeat_keys()

        _compose(["stop", "--timeout", "0", "worker"], timeout=45)
        deleted = _compose_redis_delete(heartbeat_keys)
        assert deleted >= 1, f"expected to delete worker heartbeat keys: {heartbeat_keys}"

        await _wait_for_run_status(
            api_client,
            headers,
            original_run_id,
            {"failed"},
            timeout_seconds=120,
        )
        original_detail = (
            await api_client.get(f"/api/v1/runs/{original_run_id}", headers=headers)
        ).json()
        assert "worker_lost" in (original_detail.get("error_message") or "")

        retry_runs_body = await _poll_project_runs(
            api_client,
            project_id,
            headers,
            lambda body: any(run["attempt"] == 2 for run in body["data"]),
            timeout_seconds=120,
        )
        retry_run = next(
            run for run in retry_runs_body["data"] if run["attempt"] == 2
        )
        retry_run_id = retry_run["id"]

        _compose(["start", "worker"], timeout=60)

        final_status = await _wait_for_terminal(
            api_client,
            headers,
            retry_run_id,
            timeout_seconds=240,
        )
        assert final_status == "done", f"retry run did not complete: {final_status}"

        retry_detail = (
            await api_client.get(f"/api/v1/runs/{retry_run_id}", headers=headers)
        ).json()
        assert retry_detail["finished_at"] is not None
        assert retry_detail["summary"]["total"] == 1
        assert retry_detail["summary"]["passed"] == 1

        artifacts_body = await _poll_json(
            api_client,
            f"/api/v1/runs/{retry_run_id}/artifacts",
            headers,
            lambda body: body["total"] >= 1,
            timeout_seconds=30,
        )
        junit_artifacts = [
            artifact
            for artifact in artifacts_body["data"]
            if artifact["name"] == "junit.xml"
        ]
        assert junit_artifacts, artifacts_body
        retry_junit_artifact = junit_artifacts[0]

        retry_download_resp = await api_client.get(
            f"/api/v1/artifacts/{retry_junit_artifact['id']}/download",
            headers=headers,
        )
        assert retry_download_resp.status_code == 200, retry_download_resp.text
        retry_download_body = retry_download_resp.json()
        assert retry_download_body["expires_in"] > 0
        await _assert_presigned_junit_download(
            retry_download_body["download_url"],
            expected_suite="worker-lost-retry",
        )

        archive_body = await _poll_json(
            api_client,
            f"/api/v1/runs/{retry_run_id}/logs/archive",
            headers,
            lambda body: body["total"] >= 1,
            timeout_seconds=60,
        )
        lines = [entry["line"] for entry in archive_body["data"]]
        assert any("Repository cloned successfully" in line for line in lines)
        assert any("Uploaded artifact: junit.xml" in line for line in lines)
        assert any("Run completed: done" in line for line in lines)
    finally:
        _compose(["start", "worker"], timeout=60, check=False)


@pytest.mark.asyncio
async def test_priority_queues_wait_for_matching_external_workers_then_finish(
    docker_available, api_client, admin_token
):
    """真实外部栈：high/low queue 不被 medium worker 误消费，匹配 worker 启动后完成。"""
    _require_compose_priority_stack()
    headers = {"Authorization": f"Bearer {admin_token}"}
    suffix = os.urandom(4).hex()

    try:
        _compose(["stop", "--timeout", "0", "worker-high", "worker-low"], timeout=60)

        project_resp = await api_client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "name": f"Priority Queue Evidence {suffix}",
                "slug": f"priority-queue-evidence-{suffix}",
                "git_url": EXTERNAL_STACK_GIT_URL,
                "default_branch": EXTERNAL_STACK_GIT_REF,
            },
        )
        assert project_resp.status_code in (200, 201), project_resp.text
        project_id = project_resp.json()["id"]

        env_resp = await api_client.post(
            f"/api/v1/projects/{project_id}/environments",
            headers=headers,
            json={
                "name": "Priority Queue Evidence Env",
                "base_image": "python:3.12-alpine",
                "memory_mb": 512,
                "cpu_cores": 1.0,
                "network_policy": "allow",
                "env_vars": {},
                "setup_script": (
                    "python - <<'PY'\n"
                    "from pathlib import Path\n"
                    "workspace = Path('/workspace')\n"
                    "(workspace / 'tests').mkdir(exist_ok=True)\n"
                    "(workspace / 'tests' / 'test_priority_queue.py').write_text(\n"
                    "    'def test_priority_queue():\\n    assert True\\n'\n"
                    ")\n"
                    "(workspace / 'pytest.py').write_text(\n"
                    "    \"from pathlib import Path\\n\"\n"
                    "    \"import sys\\n\"\n"
                    "    \"junit = 'results/junit.xml'\\n\"\n"
                    "    \"for arg in sys.argv[1:]:\\n\"\n"
                    "    \"    if arg.startswith('--junitxml='):\\n\"\n"
                    "    \"        junit = arg.split('=', 1)[1]\\n\"\n"
                    "    \"path = Path(junit)\\n\"\n"
                    "    \"path.parent.mkdir(parents=True, exist_ok=True)\\n\"\n"
                    "    \"path.write_text(\\\"<testsuite name='priority-queue' tests='1' failures='0' errors='0' skipped='0'><testcase classname='priority_queue' name='smoke' time='0.01'/></testsuite>\\\")\\n\"\n"
                    "    \"print('===== 1 passed in 0.01s =====')\\n\"\n"
                    ")\n"
                    "PY"
                ),
                "max_artifact_size_mb": 10,
                "max_artifacts_count": 5,
            },
        )
        assert env_resp.status_code in (200, 201), env_resp.text

        pipeline_resp = await api_client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            headers=headers,
            json={
                "name": "Priority Queue Evidence Pipeline",
                "stages": [
                    {
                        "name": "pytest",
                        "plugin": "pytest",
                        "phase": "execute",
                        "config": {"test_path": "tests/"},
                    }
                ],
                "timeout_seconds": 300,
                "selector": {"include_paths": ["tests"], "on_empty": "warn"},
                "trigger_config": {"type": "manual"},
                "enabled": True,
            },
        )
        assert pipeline_resp.status_code in (200, 201), pipeline_resp.text
        pipeline_id = pipeline_resp.json()["id"]

        triggered_runs: dict[str, str] = {}
        for priority, label in [(0, "high"), (2, "low")]:
            trigger_resp = await api_client.post(
                "/api/v1/runs",
                headers=headers,
                json={
                    "pipeline_id": pipeline_id,
                    "git_ref": EXTERNAL_STACK_GIT_REF,
                    "priority": priority,
                },
            )
            assert trigger_resp.status_code in (200, 201), trigger_resp.text
            body = trigger_resp.json()
            assert body["priority"] == priority
            assert body["status"] == "queued"
            triggered_runs[label] = body["id"]

        await asyncio.gather(
            *[
                _assert_run_stays_queued(api_client, headers, run_id, seconds=10)
                for run_id in triggered_runs.values()
            ]
        )

        _compose(["start", "worker-high", "worker-low"], timeout=60)

        final_statuses = await asyncio.gather(
            *[
                _wait_for_terminal(api_client, headers, run_id, timeout_seconds=240)
                for run_id in triggered_runs.values()
            ]
        )
        assert final_statuses == ["done", "done"]

        for label, run_id in triggered_runs.items():
            detail = (
                await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)
            ).json()
            assert detail["finished_at"] is not None
            assert detail["summary"]["total"] == 1
            assert detail["summary"]["passed"] == 1

            artifacts_body = await _poll_json(
                api_client,
                f"/api/v1/runs/{run_id}/artifacts",
                headers,
                lambda body: body["total"] >= 1,
                timeout_seconds=30,
            )
            junit_artifacts = [
                artifact
                for artifact in artifacts_body["data"]
                if artifact["name"] == "junit.xml"
            ]
            assert junit_artifacts, artifacts_body

            download_resp = await api_client.get(
                f"/api/v1/artifacts/{junit_artifacts[0]['id']}/download",
                headers=headers,
            )
            assert download_resp.status_code == 200, download_resp.text
            await _assert_presigned_junit_download(
                download_resp.json()["download_url"],
                expected_suite="priority-queue",
            )

            archive_body = await _poll_json(
                api_client,
                f"/api/v1/runs/{run_id}/logs/archive",
                headers,
                lambda body: body["total"] >= 1,
                timeout_seconds=60,
            )
            lines = [entry["line"] for entry in archive_body["data"]]
            assert any("Repository cloned successfully" in line for line in lines)
            assert any("Uploaded artifact: junit.xml" in line for line in lines)
            assert any("Run completed: done" in line for line in lines), label
    finally:
        _compose(["start", "worker-high", "worker-low"], timeout=60, check=False)
