"""部署产物的不变量。

这些断言校验的是产品运行依赖的部署事实——worker 队列划分、workspace 挂载、
docker.sock 的暴露范围、镜像里必须带上的迁移与种子脚本。它们不依赖
`.github/`，所以不会因为 CI 配置被改动或删除而失效。

从 test_release_gate_workflow.py 拆出来的：原文件把这些断言和 1645 行 workflow
的逐字符校验混在一处，而后者每改一次 CI 就要跟着改一次，属于 AGENTS.md 明令
禁止的「把其他文件源文本钉死的元测试」。
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
DOCKER_COMPOSE = ROOT / "docker-compose.yml"
PLAYWRIGHT_CONFIG = ROOT / "playwright.config.ts"

WORKER_QUEUES = {
    "worker": "queue:medium",
    "worker-high": "queue:high",
    "worker-low": "queue:low",
}
WORKSPACE_MOUNT = (
    "${QAP_RUN_WORKSPACE_DIR:-/tmp/qap-workspaces}:"
    "${QAP_RUN_WORKSPACE_DIR:-/tmp/qap-workspaces}"
)
DOCKER_SOCK_MOUNT = "/var/run/docker.sock:/var/run/docker.sock"


def _compose() -> dict:
    return yaml.safe_load(DOCKER_COMPOSE.read_text(encoding="utf-8"))


def test_each_worker_service_listens_on_its_own_queue():
    """三个 worker 各守一条队列，漏配会让该优先级的 Run 永远排队。

    schedule 触发的 Run 进 queue:low，手动与 webhook 进 queue:medium。少起
    worker-low 的话定时任务能创建 Run 却永远不执行，且没有任何报错。
    """
    services = _compose()["services"]
    for service_name, queue_name in WORKER_QUEUES.items():
        env = services[service_name]["environment"]
        assert env["QAP_WORKER_QUEUE"] == queue_name


def test_worker_services_share_the_same_workspace_path_inside_and_outside():
    """workspace 在容器内外必须是同一个路径。

    worker 通过挂载的 docker.sock 让宿主 daemon 创建测试容器，传过去的挂载
    路径由宿主解析。容器内外路径不一致时，测试容器会挂到一个空目录上。
    """
    services = _compose()["services"]
    for service_name in WORKER_QUEUES:
        service = services[service_name]
        assert service["environment"]["QAP_RUN_WORKSPACE_DIR"] == (
            "${QAP_RUN_WORKSPACE_DIR:-/tmp/qap-workspaces}"
        )
        assert service["volumes"] == [DOCKER_SOCK_MOUNT, WORKSPACE_MOUNT]
        assert service["group_add"] == ["${QAP_DOCKER_SOCK_GROUP_ID:-0}"]


def test_only_worker_services_may_touch_the_docker_socket():
    """docker.sock 等同宿主 root，暴露面必须止于 worker。

    这是本文件里最重要的一条：api / frontend / postgres 之类的服务一旦拿到
    socket，一次应用层漏洞就直接升级为宿主接管。
    """
    services = _compose()["services"]
    for service_name, service in services.items():
        if service_name in WORKER_QUEUES:
            continue
        volumes = service.get("volumes", [])
        assert DOCKER_SOCK_MOUNT not in volumes, service_name
        assert WORKSPACE_MOUNT not in volumes, service_name
        assert "QAP_RUN_WORKSPACE_DIR" not in service.get("environment", {}), service_name
        assert service.get("group_add", []) != ["${QAP_DOCKER_SOCK_GROUP_ID:-0}"], service_name


def test_image_carries_migration_and_seed_entrypoints():
    """镜像里必须带上 alembic 与 seed 脚本，否则容器起来就是个空库。"""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY alembic.ini ." in dockerfile
    assert "COPY alembic/ alembic/" in dockerfile
    assert "COPY scripts/seed_admin.py scripts/seed_admin.py" in dockerfile


def test_playwright_emits_a_machine_readable_run_report():
    """e2e 必须产出可机读的运行报告。

    没有它就无法区分「用例真的跑过并通过」与「用例被 stub 掉或整体跳过」，
    而后者恰好是最容易蒙混过关的失败模式。
    """
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    assert '["json", { outputFile: "artifacts/e2e/playwright-run.json" }]' in config
    assert 'globalTeardown: "./tests/e2e/global-teardown.ts"' in config
