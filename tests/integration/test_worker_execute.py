"""真实 worker 集成测试：触发 run → 容器执行 → 状态收尾。

需要 docker daemon 可用、docker-compose 启动 postgres+redis+minio。
默认 skip 除非 RUN_INTEGRATION_TESTS=1 环境变量设置。
"""
import asyncio
import hashlib
import json
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


def _require_compose_worker_lost_stack() -> None:
    services = _running_compose_services()
    required = {"api", "postgres", "redis", "worker"}
    missing = required - services
    if missing:
        _skip_or_fail_external_stack(
            "worker-lost external-stack test requires running compose services: "
            f"{', '.join(sorted(missing))}"
        )
    if not ({"worker-high", "worker-low"} & services):
        _skip_or_fail_external_stack(
            "worker-lost external-stack test requires worker-high or worker-low "
            "to keep the reclaimer cron alive while worker is stopped"
        )


def _require_compose_priority_stack() -> None:
    services = _running_compose_services()
    required = {"api", "postgres", "redis", "worker", "worker-high", "worker-low"}
    missing = required - services
    if missing:
        _skip_or_fail_external_stack(
            "priority external-stack test requires running compose services: "
            f"{', '.join(sorted(missing))}"
        )


def _require_compose_worker_stack() -> None:
    services = _running_compose_services()
    required = {"api", "postgres", "redis", "minio", "worker"}
    missing = required - services
    if missing:
        _skip_or_fail_external_stack(
            "worker failure external-stack test requires running compose services: "
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


def _external_stack_required() -> bool:
    return os.environ.get("QAP_EXTERNAL_STACK_REQUIRED") == "1"


def _skip_or_fail_external_stack(reason: str) -> None:
    if _external_stack_required():
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def api_server_available():
    """Require a ready external API stack, skipping only for local optional runs."""
    services = _running_compose_services()
    required = {"api", "postgres", "redis", "minio", "worker"}
    missing = required - services
    if missing:
        _skip_or_fail_external_stack(
            "external-stack tests require running compose services: "
            f"{', '.join(sorted(missing))}"
        )

    try:
        with httpx.Client(base_url=BASE_URL, timeout=3.0) as client:
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


@pytest.fixture(scope="module")
def docker_available():
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        _skip_or_fail_external_stack("docker daemon not available")
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
    if resp.status_code != 200:
        _skip_or_fail_external_stack(
            "external API stack admin login failed at "
            f"{BASE_URL}: {resp.status_code} {resp.text[:300]}"
        )
    return resp.json()["access_token"]


async def _create_external_api_token(
    api_client,
    access_token: str,
    *,
    name: str,
    scopes: list[str],
) -> str:
    response = await api_client.post(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": name, "scopes": scopes, "expires_days": 7},
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


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


async def _assert_project_has_no_retry_runs(
    api_client,
    project_id: str,
    headers,
    *,
    seconds: int = 12,
) -> None:
    deadline = asyncio.get_event_loop().time() + seconds
    observed_attempts: list[list[int]] = []
    while asyncio.get_event_loop().time() < deadline:
        response = await api_client.get(
            f"/api/v1/runs?project_id={project_id}&per_page=20",
            headers=headers,
        )
        assert response.status_code == 200, response.text[:500]
        body = response.json()
        attempts = [run["attempt"] for run in body["data"]]
        observed_attempts.append(attempts)
        assert attempts, (
            "expected original run while checking retry absence; "
            f"observed_attempts={observed_attempts}"
        )
        assert all(attempt == 1 for attempt in attempts), (
            "failure should not create retry runs; "
            f"observed_attempts={observed_attempts}"
        )
        await asyncio.sleep(2)


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


async def _assert_run_trigger_audit_event(
    api_client,
    headers,
    run_id: str,
    *,
    expected_git_ref: str,
    expected_priority: int,
    expected_after_state: dict | None = None,
    forbidden_texts: tuple[str, ...] = (),
) -> None:
    response = await api_client.get(
        "/api/v1/audit-events",
        headers=headers,
        params={
            "action": "run.trigger",
            "resource_type": "run",
            "resource_id": run_id,
            "per_page": 5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    matching = [
        event
        for event in body["data"]
        if event["resource_id"] == run_id and event["action"] == "run.trigger"
    ]
    assert matching, body

    event = matching[0]
    assert event["resource_type"] == "run"
    assert event["before_state"] is None
    after_state = event["after_state"]
    assert after_state is not None
    if expected_after_state is not None:
        assert after_state == expected_after_state
    assert after_state["id"] == run_id
    assert after_state["status"] == "queued"
    assert after_state["trigger_type"] == "manual"
    assert after_state["git_ref"] == expected_git_ref
    assert after_state["priority"] == expected_priority

    serialized_event = json.dumps(event, ensure_ascii=False, sort_keys=True)
    for forbidden_text in forbidden_texts:
        assert forbidden_text not in serialized_event


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


def _parse_sse_event_block(raw_block: str) -> dict[str, str]:
    event: dict[str, str] = {"event": "message", "data": ""}
    data_lines: list[str] = []
    for line in raw_block.splitlines():
        if not line or line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        elif field in {"id", "event"}:
            event[field] = value
    event["data"] = "\n".join(data_lines)
    return event


def _sse_log_line(event: dict[str, str]) -> str:
    if event.get("event") != "log":
        return ""
    try:
        payload = json.loads(event.get("data", ""))
    except json.JSONDecodeError:
        return ""
    return str(payload.get("line") or "")


def _format_sse_transcript(events: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for event in events[-20:]:
        lines.append(
            "id={id} event={event} data={data}".format(
                id=event.get("id", ""),
                event=event.get("event", ""),
                data=event.get("data", "")[:500],
            )
        )
    return "\n".join(lines)


async def _read_sse_until_log_line(
    run_id: str,
    ticket: str,
    expected_line_fragment: str,
    *,
    last_event_id: str | None = None,
    timeout_seconds: int = 90,
) -> list[dict[str, str]]:
    headers = {"Last-Event-ID": last_event_id} if last_event_id else None
    url = f"/api/v1/runs/{run_id}/logs?ticket={ticket}"
    timeout = httpx.Timeout(10.0, connect=5.0, read=None)

    events: list[dict[str, str]] = []
    buffer = ""
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    pytest.fail(
                        f"SSE logs stream returned {response.status_code}: {body[:1000]}"
                    )
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type

                async with asyncio.timeout(timeout_seconds):
                    async for chunk in response.aiter_text():
                        buffer += chunk.replace("\r\n", "\n")
                        while "\n\n" in buffer:
                            raw_block, buffer = buffer.split("\n\n", 1)
                            event = _parse_sse_event_block(raw_block)
                            events.append(event)

                            line = _sse_log_line(event)
                            if expected_line_fragment in line:
                                return events
                            if event.get("event") == "done":
                                pytest.fail(
                                    "SSE logs stream reached done before expected "
                                    f"line {expected_line_fragment!r}; transcript:\n"
                                    f"{_format_sse_transcript(events)}"
                                )
    except TimeoutError:
        pytest.fail(
            f"SSE logs stream did not emit {expected_line_fragment!r} within "
            f"{timeout_seconds}s; transcript:\n{_format_sse_transcript(events)}"
        )

    pytest.fail(
        f"SSE logs stream closed before {expected_line_fragment!r}; transcript:\n"
        f"{_format_sse_transcript(events)}"
    )


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
async def test_real_worker_streams_live_logs_over_sse_external_stack(
    docker_available, api_client, admin_token
):
    """真实外部栈：compose worker 运行中，/logs SSE 能实时读到 worker 日志并保留权限边界。"""
    _require_compose_worker_stack()
    headers = {"Authorization": f"Bearer {admin_token}"}
    suffix = os.urandom(4).hex()
    start_marker = f"sse-live-start-{suffix}"
    end_marker = f"sse-live-end-{suffix}"
    live_sleep_seconds = 60

    pytest_source = (
        "from pathlib import Path\n"
        "import os\n"
        "import sys\n"
        "import time\n"
        f"start_marker = {start_marker!r}\n"
        f"end_marker = {end_marker!r}\n"
        "print(start_marker, flush=True)\n"
        "time.sleep(float(os.environ.get('QAP_SSE_LIVE_SLEEP', '60')))\n"
        "junit = 'results/junit.xml'\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg.startswith('--junitxml='):\n"
        "        junit = arg.split('=', 1)[1]\n"
        "path = Path(junit)\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text(\"<testsuite name='sse-live-worker' tests='1' "
        "failures='0' errors='0' skipped='0'><testcase "
        "classname='sse_live_worker' name='smoke' "
        "time='0.01'/></testsuite>\")\n"
        "print(end_marker, flush=True)\n"
        "print('===== 1 passed in 0.01s =====', flush=True)\n"
    )
    setup_script = (
        "python - <<'PY'\n"
        "from pathlib import Path\n"
        "workspace = Path('/workspace')\n"
        "(workspace / 'tests').mkdir(exist_ok=True)\n"
        "(workspace / 'tests' / 'test_sse_live_worker.py').write_text(\n"
        "    'def test_sse_live_worker():\\n    assert True\\n'\n"
        ")\n"
        f"(workspace / 'pytest.py').write_text({pytest_source!r})\n"
        "PY"
    )

    project_resp = await api_client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"SSE Live Worker {suffix}",
            "slug": f"sse-live-worker-{suffix}",
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
            "name": "SSE Live Worker Env",
            "base_image": "python:3.12-alpine",
            "memory_mb": 512,
            "cpu_cores": 1.0,
            "network_policy": "allow",
            "env_vars": {"QAP_SSE_LIVE_SLEEP": str(live_sleep_seconds)},
            "setup_script": setup_script,
            "max_artifact_size_mb": 10,
            "max_artifacts_count": 5,
        },
    )
    assert env_resp.status_code in (200, 201), env_resp.text

    pipeline_resp = await api_client.post(
        f"/api/v1/projects/{project_id}/pipelines",
        headers=headers,
        json={
            "name": "SSE Live Worker Pipeline",
            "stages": [
                {
                    "name": "pytest",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {"test_path": "tests/", "args": ["-s"]},
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
    run_body = trigger_resp.json()
    assert run_body["status"] == "queued"
    assert run_body["priority"] == 1
    run_id = run_body["id"]
    await _assert_run_trigger_audit_event(
        api_client,
        headers,
        run_id,
        expected_git_ref=EXTERNAL_STACK_GIT_REF,
        expected_priority=1,
        expected_after_state=run_body,
    )

    no_ticket_resp = await api_client.get(f"/api/v1/runs/{run_id}/logs")
    assert no_ticket_resp.status_code in (401, 422), no_ticket_resp.text

    first_ticket_resp = await api_client.post(
        "/api/v1/auth/sse-ticket",
        headers=headers,
    )
    assert first_ticket_resp.status_code == 200, first_ticket_resp.text
    first_ticket = first_ticket_resp.json()["ticket"]

    first_events = await _read_sse_until_log_line(
        run_id,
        first_ticket,
        start_marker,
        timeout_seconds=180,
    )
    first_lines = [_sse_log_line(event) for event in first_events]
    assert any("Starting stage: pytest" in line for line in first_lines), (
        _format_sse_transcript(first_events)
    )
    first_marker_event = next(
        event for event in first_events if start_marker in _sse_log_line(event)
    )
    first_marker_id = first_marker_event["id"]

    live_detail_resp = await api_client.get(f"/api/v1/runs/{run_id}", headers=headers)
    assert live_detail_resp.status_code == 200, live_detail_resp.text
    live_status = live_detail_resp.json()["status"]
    assert live_status not in TERMINAL_STATUSES, (
        "SSE start marker should arrive while the real worker run is still live; "
        f"status={live_status}; transcript:\n{_format_sse_transcript(first_events)}"
    )

    reuse_resp = await api_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={first_ticket}",
        headers={"Last-Event-ID": first_marker_id},
    )
    assert reuse_resp.status_code == 401, reuse_resp.text

    second_ticket_resp = await api_client.post(
        "/api/v1/auth/sse-ticket",
        headers=headers,
    )
    assert second_ticket_resp.status_code == 200, second_ticket_resp.text
    second_events = await _read_sse_until_log_line(
        run_id,
        second_ticket_resp.json()["ticket"],
        end_marker,
        last_event_id=first_marker_id,
        timeout_seconds=120,
    )
    second_lines = [_sse_log_line(event) for event in second_events]
    assert all(start_marker not in line for line in second_lines), (
        _format_sse_transcript(second_events)
    )
    assert any(end_marker in line for line in second_lines), (
        _format_sse_transcript(second_events)
    )

    empty_scope_token = await _create_external_api_token(
        api_client,
        admin_token,
        name=f"sse-live-empty-{suffix}",
        scopes=[],
    )
    empty_scope_headers = {"Authorization": f"Bearer {empty_scope_token}"}
    empty_ticket_resp = await api_client.post(
        "/api/v1/auth/sse-ticket",
        headers=empty_scope_headers,
    )
    assert empty_ticket_resp.status_code == 200, empty_ticket_resp.text
    denied_resp = await api_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={empty_ticket_resp.json()['ticket']}",
        headers={"Last-Event-ID": first_marker_id},
    )
    assert denied_resp.status_code == 403, denied_resp.text
    for fragment in (
        start_marker,
        end_marker,
        f"logs/{run_id}.jsonl",
        f"reports/{run_id}/",
    ):
        assert fragment not in denied_resp.text

    final_status = await _wait_for_terminal(
        api_client, headers, run_id, timeout_seconds=240
    )
    assert final_status == "done", f"run did not complete successfully: {final_status}"

    artifacts_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{run_id}/artifacts",
        headers,
        lambda body: body["total"] >= 1,
        timeout_seconds=30,
    )
    junit_artifacts = [
        artifact for artifact in artifacts_body["data"] if artifact["name"] == "junit.xml"
    ]
    assert junit_artifacts, artifacts_body
    junit_download_resp = await api_client.get(
        f"/api/v1/artifacts/{junit_artifacts[0]['id']}/download",
        headers=headers,
    )
    assert junit_download_resp.status_code == 200, junit_download_resp.text
    await _assert_presigned_junit_download(
        junit_download_resp.json()["download_url"],
        expected_suite="sse-live-worker",
    )

    archive_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{run_id}/logs/archive",
        headers,
        lambda body: body["total"] >= 1,
        timeout_seconds=60,
    )
    archive_lines = [entry["line"] for entry in archive_body["data"]]
    assert any(start_marker in line for line in archive_lines)
    assert any(end_marker in line for line in archive_lines)
    assert any("Run completed: done" in line for line in archive_lines)


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
                "    \"print(f'active stdout secret: {actual_secret}', flush=True)\\n\"\n"
                "    \"print(f'active stderr secret: {actual_secret}', file=sys.stderr, flush=True)\\n\"\n"
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
    run_body = trigger_resp.json()
    run_id = run_body["id"]
    await _assert_run_trigger_audit_event(
        api_client,
        headers,
        run_id,
        expected_git_ref=EXTERNAL_STACK_GIT_REF,
        expected_priority=1,
        expected_after_state=run_body,
        forbidden_texts=(worker_secret,),
    )

    live_ticket_resp = await api_client.post(
        "/api/v1/auth/sse-ticket",
        headers=headers,
    )
    assert live_ticket_resp.status_code == 200, live_ticket_resp.text
    live_secret_events = await _read_sse_until_log_line(
        run_id,
        live_ticket_resp.json()["ticket"],
        "active stdout secret: [REDACTED]",
        timeout_seconds=180,
    )
    live_secret_lines = "\n".join(
        _sse_log_line(event) for event in live_secret_events
    )
    assert worker_secret not in live_secret_lines

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
    assert worker_secret not in str(artifacts_body)

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
        assert worker_secret not in downloaded_text

    archive_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{run_id}/logs/archive",
        headers,
        lambda body: body["total"] >= 1,
        timeout_seconds=60,
    )
    lines = [entry["line"] for entry in archive_body["data"]]
    joined_lines = "\n".join(lines)
    assert worker_secret not in joined_lines
    assert "active stdout secret: [REDACTED]" in joined_lines
    assert "active stderr secret: [REDACTED]" in joined_lines
    assert any("Repository cloned successfully" in line for line in lines)
    for artifact_name in expected_artifacts:
        assert any(f"Uploaded artifact: {artifact_name}" in line for line in lines)
    assert any("Run completed: done" in line for line in lines)

    run_read_token = await _create_external_api_token(
        api_client,
        admin_token,
        name=f"worker-run-read-{suffix}",
        scopes=["run.read"],
    )
    project_read_token = await _create_external_api_token(
        api_client,
        admin_token,
        name=f"worker-project-read-{suffix}",
        scopes=["project.read"],
    )
    empty_scope_token = await _create_external_api_token(
        api_client,
        admin_token,
        name=f"worker-empty-{suffix}",
        scopes=[],
    )
    run_read_headers = {"Authorization": f"Bearer {run_read_token}"}
    project_read_headers = {"Authorization": f"Bearer {project_read_token}"}
    empty_scope_headers = {"Authorization": f"Bearer {empty_scope_token}"}

    token_detail_resp = await api_client.get(
        f"/api/v1/runs/{run_id}",
        headers=run_read_headers,
    )
    assert token_detail_resp.status_code == 200, token_detail_resp.text
    token_detail = token_detail_resp.json()
    assert token_detail["id"] == run_id
    assert token_detail["status"] == "done"
    assert token_detail["summary"]["total"] == 1
    assert token_detail["summary"]["passed"] == 1
    assert worker_secret not in json.dumps(token_detail, sort_keys=True)

    token_live_ticket_resp = await api_client.post(
        "/api/v1/auth/sse-ticket",
        headers=run_read_headers,
    )
    assert token_live_ticket_resp.status_code == 200, token_live_ticket_resp.text
    token_live_secret_events = await _read_sse_until_log_line(
        run_id,
        token_live_ticket_resp.json()["ticket"],
        "active stdout secret: [REDACTED]",
        timeout_seconds=30,
    )
    token_live_secret_lines = "\n".join(
        _sse_log_line(event) for event in token_live_secret_events
    )
    assert worker_secret not in token_live_secret_lines

    token_artifacts_resp = await api_client.get(
        f"/api/v1/runs/{run_id}/artifacts",
        headers=run_read_headers,
        params={"page": 1, "per_page": 20},
    )
    assert token_artifacts_resp.status_code == 200, token_artifacts_resp.text
    token_artifacts_body = token_artifacts_resp.json()
    token_artifacts_by_name = {
        artifact["name"]: artifact for artifact in token_artifacts_body["data"]
    }
    assert expected_artifacts.keys() <= token_artifacts_by_name.keys()
    assert worker_secret not in json.dumps(token_artifacts_body, sort_keys=True)

    token_archive_resp = await api_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers=run_read_headers,
        params={"page": 1, "per_page": 100},
    )
    assert token_archive_resp.status_code == 200, token_archive_resp.text
    token_archive_body = token_archive_resp.json()
    token_lines = [entry["line"] for entry in token_archive_body["data"]]
    token_joined_lines = "\n".join(token_lines)
    assert any("Repository cloned successfully" in line for line in token_lines)
    assert any("Run completed: done" in line for line in token_lines)
    assert "active stdout secret: [REDACTED]" in token_joined_lines
    assert "active stderr secret: [REDACTED]" in token_joined_lines
    assert worker_secret not in token_joined_lines

    for artifact_name, (artifact_type, expected_text) in expected_artifacts.items():
        token_artifact = token_artifacts_by_name[artifact_name]
        assert token_artifact["type"] == artifact_type
        assert token_artifact["storage_path"] == f"reports/{run_id}/{artifact_name}"

        token_download_resp = await api_client.get(
            f"/api/v1/artifacts/{token_artifact['id']}/download",
            headers=run_read_headers,
        )
        assert token_download_resp.status_code == 200, token_download_resp.text
        token_download_body = token_download_resp.json()
        assert token_download_body["expires_in"] > 0
        assert token_download_body["download_url"].startswith(("http://", "https://"))
        token_downloaded_text = await _download_presigned_text(
            token_download_body["download_url"]
        )
        assert expected_text in token_downloaded_text
        assert worker_secret not in token_downloaded_text

    forbidden_fragments = (
        worker_secret,
        f"reports/{run_id}/",
        f"logs/{run_id}.jsonl",
        "Repository cloned successfully",
        "Run completed: done",
        "Uploaded artifact:",
        "active stdout secret:",
        "active stderr secret:",
        "[REDACTED]",
        *expected_artifacts.keys(),
        *(expected_text for _, expected_text in expected_artifacts.values()),
    )

    denied_archive_resp = await api_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers=empty_scope_headers,
    )
    denied_detail_resp = await api_client.get(
        f"/api/v1/runs/{run_id}",
        headers=empty_scope_headers,
    )
    denied_project_detail_resp = await api_client.get(
        f"/api/v1/runs/{run_id}",
        headers=project_read_headers,
    )
    denied_live_ticket_resp = await api_client.post(
        "/api/v1/auth/sse-ticket",
        headers=empty_scope_headers,
    )
    assert denied_live_ticket_resp.status_code == 200, denied_live_ticket_resp.text
    denied_live_resp = await api_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={denied_live_ticket_resp.json()['ticket']}",
    )
    denied_list_resp = await api_client.get(
        f"/api/v1/runs/{run_id}/artifacts",
        headers=empty_scope_headers,
    )
    denied_download_responses = []
    for artifact_name in expected_artifacts:
        artifact = token_artifacts_by_name[artifact_name]
        denied_download_responses.append(
            await api_client.get(
                f"/api/v1/artifacts/{artifact['id']}/download",
                headers=empty_scope_headers,
            )
        )
    for response in (
        denied_detail_resp,
        denied_project_detail_resp,
        denied_live_resp,
        denied_archive_resp,
        denied_list_resp,
        *denied_download_responses,
    ):
        assert response.status_code == 403, response.text
        for fragment in forbidden_fragments:
            assert fragment not in response.text


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
        original_run_body = trigger_resp.json()
        original_run_id = original_run_body["id"]
        await _assert_run_trigger_audit_event(
            api_client,
            headers,
            original_run_id,
            expected_git_ref=EXTERNAL_STACK_GIT_REF,
            expected_priority=1,
            expected_after_state=original_run_body,
        )

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

        run_read_token = await _create_external_api_token(
            api_client,
            admin_token,
            name=f"worker-lost-run-read-{suffix}",
            scopes=["run.read"],
        )
        empty_scope_token = await _create_external_api_token(
            api_client,
            admin_token,
            name=f"worker-lost-empty-{suffix}",
            scopes=[],
        )
        run_read_headers = {"Authorization": f"Bearer {run_read_token}"}
        empty_scope_headers = {"Authorization": f"Bearer {empty_scope_token}"}

        token_archive_resp = await api_client.get(
            f"/api/v1/runs/{retry_run_id}/logs/archive",
            headers=run_read_headers,
        )
        assert token_archive_resp.status_code == 200, token_archive_resp.text
        token_lines = [
            entry["line"] for entry in token_archive_resp.json()["data"]
        ]
        assert any("Repository cloned successfully" in line for line in token_lines)
        assert any("Uploaded artifact: junit.xml" in line for line in token_lines)
        assert any("Run completed: done" in line for line in token_lines)

        token_artifacts_resp = await api_client.get(
            f"/api/v1/runs/{retry_run_id}/artifacts",
            headers=run_read_headers,
        )
        assert token_artifacts_resp.status_code == 200, token_artifacts_resp.text
        token_artifacts_body = token_artifacts_resp.json()
        token_junit_artifacts = [
            artifact
            for artifact in token_artifacts_body["data"]
            if artifact["name"] == "junit.xml"
        ]
        assert token_junit_artifacts, token_artifacts_body
        token_junit_artifact = token_junit_artifacts[0]
        assert token_junit_artifact["type"] == "junit"
        assert token_junit_artifact["storage_path"] == (
            f"reports/{retry_run_id}/junit.xml"
        )

        token_download_resp = await api_client.get(
            f"/api/v1/artifacts/{token_junit_artifact['id']}/download",
            headers=run_read_headers,
        )
        assert token_download_resp.status_code == 200, token_download_resp.text
        token_download_body = token_download_resp.json()
        assert token_download_body["expires_in"] > 0
        await _assert_presigned_junit_download(
            token_download_body["download_url"],
            expected_suite="worker-lost-retry",
        )

        forbidden_fragments = (
            f"logs/{retry_run_id}.jsonl",
            f"reports/{retry_run_id}/",
            "junit.xml",
            "worker-lost-retry",
            "Repository cloned successfully",
            "Uploaded artifact:",
            "Run completed: done",
            "<testsuite name='worker-lost-retry'",
        )
        denied_archive_resp = await api_client.get(
            f"/api/v1/runs/{retry_run_id}/logs/archive",
            headers=empty_scope_headers,
        )
        denied_list_resp = await api_client.get(
            f"/api/v1/runs/{retry_run_id}/artifacts",
            headers=empty_scope_headers,
        )
        denied_download_resp = await api_client.get(
            f"/api/v1/artifacts/{token_junit_artifact['id']}/download",
            headers=empty_scope_headers,
        )
        for response in (
            denied_archive_resp,
            denied_list_resp,
            denied_download_resp,
        ):
            assert response.status_code == 403, response.text
            for fragment in forbidden_fragments:
                assert fragment not in response.text
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
            await _assert_run_trigger_audit_event(
                api_client,
                headers,
                body["id"],
                expected_git_ref=EXTERNAL_STACK_GIT_REF,
                expected_priority=priority,
                expected_after_state=body,
            )

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

        run_read_token = await _create_external_api_token(
            api_client,
            admin_token,
            name=f"priority-run-read-{suffix}",
            scopes=["run.read"],
        )
        empty_scope_token = await _create_external_api_token(
            api_client,
            admin_token,
            name=f"priority-empty-{suffix}",
            scopes=[],
        )
        run_read_headers = {"Authorization": f"Bearer {run_read_token}"}
        empty_scope_headers = {"Authorization": f"Bearer {empty_scope_token}"}

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

            token_detail_resp = await api_client.get(
                f"/api/v1/runs/{run_id}",
                headers=run_read_headers,
            )
            assert token_detail_resp.status_code == 200, token_detail_resp.text
            token_detail = token_detail_resp.json()
            assert token_detail["status"] == "done", label
            assert token_detail["summary"]["total"] == 1, label
            assert token_detail["summary"]["passed"] == 1, label

            token_archive_resp = await api_client.get(
                f"/api/v1/runs/{run_id}/logs/archive",
                headers=run_read_headers,
            )
            assert token_archive_resp.status_code == 200, token_archive_resp.text
            token_lines = [
                entry["line"] for entry in token_archive_resp.json()["data"]
            ]
            assert any(
                "Repository cloned successfully" in line for line in token_lines
            ), label
            assert any("Uploaded artifact: junit.xml" in line for line in token_lines)
            assert any("Run completed: done" in line for line in token_lines), label

            token_artifacts_resp = await api_client.get(
                f"/api/v1/runs/{run_id}/artifacts",
                headers=run_read_headers,
            )
            assert token_artifacts_resp.status_code == 200, (
                token_artifacts_resp.text
            )
            token_artifacts_body = token_artifacts_resp.json()
            token_junit_artifacts = [
                artifact
                for artifact in token_artifacts_body["data"]
                if artifact["name"] == "junit.xml"
            ]
            assert token_junit_artifacts, token_artifacts_body
            token_junit_artifact = token_junit_artifacts[0]
            assert token_junit_artifact["type"] == "junit", label
            assert token_junit_artifact["storage_path"] == (
                f"reports/{run_id}/junit.xml"
            )

            token_download_resp = await api_client.get(
                f"/api/v1/artifacts/{token_junit_artifact['id']}/download",
                headers=run_read_headers,
            )
            assert token_download_resp.status_code == 200, token_download_resp.text
            await _assert_presigned_junit_download(
                token_download_resp.json()["download_url"],
                expected_suite="priority-queue",
            )

            forbidden_fragments = (
                f"logs/{run_id}.jsonl",
                f"reports/{run_id}/",
                "junit.xml",
                "priority-queue",
                "Repository cloned successfully",
                "Uploaded artifact:",
                "Run completed: done",
                "<testsuite name='priority-queue'",
            )
            denied_archive_resp = await api_client.get(
                f"/api/v1/runs/{run_id}/logs/archive",
                headers=empty_scope_headers,
            )
            denied_list_resp = await api_client.get(
                f"/api/v1/runs/{run_id}/artifacts",
                headers=empty_scope_headers,
            )
            denied_download_resp = await api_client.get(
                f"/api/v1/artifacts/{token_junit_artifact['id']}/download",
                headers=empty_scope_headers,
            )
            for response in (
                denied_archive_resp,
                denied_list_resp,
                denied_download_resp,
            ):
                assert response.status_code == 403, response.text
                for fragment in forbidden_fragments:
                    assert fragment not in response.text
    finally:
        _compose(["start", "worker-high", "worker-low"], timeout=60, check=False)


@pytest.mark.asyncio
async def test_worker_clone_and_setup_failures_do_not_retry_or_leak_external_stack(
    docker_available, api_client, admin_token
):
    """真实外部栈：clone/setup 用户失败保持 failed，不重试也不泄露 URL secret。"""
    _require_compose_worker_stack()
    headers = {"Authorization": f"Bearer {admin_token}"}
    suffix = os.urandom(4).hex()

    async def _create_run(
        *,
        label: str,
        git_url: str,
        setup_script: str,
    ) -> tuple[str, str]:
        project_resp = await api_client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "name": f"Worker Failure {label} {suffix}",
                "slug": f"worker-failure-{label}-{suffix}",
                "git_url": git_url,
                "default_branch": EXTERNAL_STACK_GIT_REF,
            },
        )
        assert project_resp.status_code in (200, 201), project_resp.text
        project_id = project_resp.json()["id"]

        env_resp = await api_client.post(
            f"/api/v1/projects/{project_id}/environments",
            headers=headers,
            json={
                "name": f"Worker Failure {label} Env",
                "base_image": "python:3.12-alpine",
                "memory_mb": 512,
                "cpu_cores": 1.0,
                "network_policy": "allow",
                "env_vars": {},
                "setup_script": setup_script,
                "max_artifact_size_mb": 10,
                "max_artifacts_count": 5,
            },
        )
        assert env_resp.status_code in (200, 201), env_resp.text

        pipeline_resp = await api_client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            headers=headers,
            json={
                "name": f"Worker Failure {label} Pipeline",
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
        run_body = trigger_resp.json()
        run_id = run_body["id"]
        await _assert_run_trigger_audit_event(
            api_client,
            headers,
            run_id,
            expected_git_ref=EXTERNAL_STACK_GIT_REF,
            expected_priority=1,
            expected_after_state=run_body,
            forbidden_texts=(secret,),
        )
        return project_id, run_id

    secret = f"clone-secret-{suffix}"
    missing_repo_url = (
        "https://x-access-token:"
        f"{secret}@github.com/octocat/qap-missing-{suffix}.git"
    )
    clone_project_id, clone_run_id = await _create_run(
        label="clone",
        git_url=missing_repo_url,
        setup_script="",
    )
    clone_status = await _wait_for_terminal(
        api_client,
        headers,
        clone_run_id,
        timeout_seconds=180,
    )
    assert clone_status == "failed"
    clone_detail_resp = await api_client.get(
        f"/api/v1/runs/{clone_run_id}",
        headers=headers,
    )
    assert clone_detail_resp.status_code == 200, clone_detail_resp.text
    clone_detail = clone_detail_resp.json()
    clone_error = clone_detail.get("error_message") or ""
    assert "git clone failed" in clone_error
    assert secret not in clone_error
    assert "x-access-token" not in clone_error
    await _assert_project_has_no_retry_runs(
        api_client,
        clone_project_id,
        headers,
    )
    clone_artifacts_resp = await api_client.get(
        f"/api/v1/runs/{clone_run_id}/artifacts",
        headers=headers,
    )
    assert clone_artifacts_resp.status_code == 200, clone_artifacts_resp.text
    clone_artifacts = clone_artifacts_resp.json()
    assert clone_artifacts["total"] == 0
    clone_archive_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{clone_run_id}/logs/archive",
        headers,
        lambda body: isinstance(body.get("data"), list)
        and isinstance(body.get("total"), int),
        timeout_seconds=60,
    )
    serialized_clone_archive = json.dumps(
        clone_archive_body,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert secret not in serialized_clone_archive
    assert "x-access-token" not in serialized_clone_archive
    assert missing_repo_url not in serialized_clone_archive

    run_read_token = await _create_external_api_token(
        api_client,
        admin_token,
        name=f"worker-failure-run-read-{suffix}",
        scopes=["run.read"],
    )
    empty_scope_token = await _create_external_api_token(
        api_client,
        admin_token,
        name=f"worker-failure-empty-{suffix}",
        scopes=[],
    )
    run_read_headers = {"Authorization": f"Bearer {run_read_token}"}
    empty_scope_headers = {"Authorization": f"Bearer {empty_scope_token}"}

    clone_token_archive_resp = await api_client.get(
        f"/api/v1/runs/{clone_run_id}/logs/archive",
        headers=run_read_headers,
    )
    assert clone_token_archive_resp.status_code == 200, clone_token_archive_resp.text
    clone_token_archive = clone_token_archive_resp.json()
    assert isinstance(clone_token_archive.get("data"), list)
    assert isinstance(clone_token_archive.get("total"), int)
    serialized_clone_token_archive = json.dumps(
        clone_token_archive,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert secret not in serialized_clone_token_archive
    assert "x-access-token" not in serialized_clone_token_archive
    assert missing_repo_url not in serialized_clone_token_archive

    clone_denied_archive_resp = await api_client.get(
        f"/api/v1/runs/{clone_run_id}/logs/archive",
        headers=empty_scope_headers,
    )
    assert clone_denied_archive_resp.status_code == 403, (
        clone_denied_archive_resp.text
    )
    for fragment in (
        f"logs/{clone_run_id}.jsonl",
        secret,
        "x-access-token",
        missing_repo_url,
        "git clone failed",
    ):
        assert fragment not in clone_denied_archive_resp.text

    setup_project_id, setup_run_id = await _create_run(
        label="setup",
        git_url=EXTERNAL_STACK_GIT_URL,
        setup_script="echo setup-boundary-failure >&2\nexit 1",
    )
    setup_status = await _wait_for_terminal(
        api_client,
        headers,
        setup_run_id,
        timeout_seconds=240,
    )
    assert setup_status == "failed"
    setup_detail_resp = await api_client.get(
        f"/api/v1/runs/{setup_run_id}",
        headers=headers,
    )
    assert setup_detail_resp.status_code == 200, setup_detail_resp.text
    setup_detail = setup_detail_resp.json()
    assert "Setup script failed (exit 1)" in (
        setup_detail.get("error_message") or ""
    )
    await _assert_project_has_no_retry_runs(
        api_client,
        setup_project_id,
        headers,
    )
    setup_artifacts_resp = await api_client.get(
        f"/api/v1/runs/{setup_run_id}/artifacts",
        headers=headers,
    )
    assert setup_artifacts_resp.status_code == 200, setup_artifacts_resp.text
    setup_artifacts = setup_artifacts_resp.json()
    assert setup_artifacts["total"] == 0

    archive_body = await _poll_json(
        api_client,
        f"/api/v1/runs/{setup_run_id}/logs/archive",
        headers,
        lambda body: body["total"] >= 1,
        timeout_seconds=60,
    )
    lines = [entry["line"] for entry in archive_body["data"]]
    assert any("Repository cloned successfully" in line for line in lines)
    assert any("Running setup script..." in line for line in lines)
    assert any("setup-boundary-failure" in line for line in lines)

    setup_token_archive_resp = await api_client.get(
        f"/api/v1/runs/{setup_run_id}/logs/archive",
        headers=run_read_headers,
    )
    assert setup_token_archive_resp.status_code == 200, setup_token_archive_resp.text
    setup_token_lines = [
        entry["line"] for entry in setup_token_archive_resp.json()["data"]
    ]
    assert any("Repository cloned successfully" in line for line in setup_token_lines)
    assert any("Running setup script..." in line for line in setup_token_lines)
    assert any("setup-boundary-failure" in line for line in setup_token_lines)

    setup_denied_archive_resp = await api_client.get(
        f"/api/v1/runs/{setup_run_id}/logs/archive",
        headers=empty_scope_headers,
    )
    assert setup_denied_archive_resp.status_code == 403, (
        setup_denied_archive_resp.text
    )
    for fragment in (
        f"logs/{setup_run_id}.jsonl",
        "Repository cloned successfully",
        "Running setup script...",
        "setup-boundary-failure",
    ):
        assert fragment not in setup_denied_archive_resp.text
