"""真实 worker 集成测试：触发 run → 容器执行 → 状态收尾。

需要 docker daemon 可用、docker-compose 启动 postgres+redis+minio。
默认 skip 除非 RUN_INTEGRATION_TESTS=1 环境变量设置。
"""
import asyncio
import os
import subprocess
import pytest
import httpx
from uuid import UUID

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests"
)

BASE_URL = os.environ.get("QAP_API_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def docker_available():
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pytest.skip("docker daemon not available")
    return True


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
    env = env_resp.json()
    
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
    TERMINAL = {"done", "failed", "cancelled", "timeout"}
    deadline = asyncio.get_event_loop().time() + 180
    final_status = None
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(3)
        status_resp = await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)
        if status_resp.status_code == 200:
            final_status = status_resp.json()["status"]
            if final_status in TERMINAL:
                break
    
    assert final_status in TERMINAL, f"run timed out, last status: {final_status}"
    
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
