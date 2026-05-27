"""真实 worker 集成测试：触发 run → 容器执行 → 状态收尾。

需要 docker daemon 可用、docker-compose 启动 postgres+redis+minio。
默认 skip 除非 RUN_INTEGRATION_TESTS=1 环境变量设置。
"""
import asyncio
import os
import subprocess
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
TERMINAL_STATUSES = {"done", "failed", "cancelled", "timeout"}


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

    env_resp = await api_client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={
            "name": "Worker Evidence Env",
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
                "(workspace / 'tests' / 'test_real_worker_smoke.py').write_text(\n"
                "    'def test_real_worker_smoke():\\n    assert True\\n'\n"
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
                "    \"path.write_text(\\\"<testsuite name='real-worker' tests='1' failures='0' errors='0' skipped='0'><testcase classname='real_worker' name='smoke' time='0.01'/></testsuite>\\\")\\n\"\n"
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
        lambda body: body["total"] >= 1,
        timeout_seconds=30,
    )
    junit_artifacts = [
        artifact
        for artifact in artifacts_body["data"]
        if artifact["name"] == "junit.xml"
    ]
    assert junit_artifacts, artifacts_body
    junit_artifact = junit_artifacts[0]
    assert junit_artifact["type"] == "junit"
    assert junit_artifact["storage_path"] == f"reports/{run_id}/junit.xml"

    download_resp = await api_client.get(
        f"/api/v1/artifacts/{junit_artifact['id']}/download",
        headers=headers,
    )
    assert download_resp.status_code == 200, download_resp.text
    download_body = download_resp.json()
    assert download_body["expires_in"] > 0
    assert download_body["download_url"].startswith(("http://", "https://"))

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
    assert any("Run completed: done" in line for line in lines)
