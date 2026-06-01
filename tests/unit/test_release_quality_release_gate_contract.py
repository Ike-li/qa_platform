from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
RELEASE_GATE_WORKFLOW = ROOT / "tests" / "unit" / "test_release_gate_workflow.py"


def test_quality_ops_capture_performance_slo_workflow_env_exact_contract():
    row = _quality_ops_row_containing("Performance SLO workflow env 双向契约")
    release_gate_workflow = _read(RELEASE_GATE_WORKFLOW)

    assert "Performance SLO workflow env 双向契约" in row
    assert "必须精确等于 SLO manifest 的 `threshold_env` 清单" in row
    assert "assert threshold_envs == workflow_envs" in release_gate_workflow
    assert "assert threshold_envs <= workflow_envs" not in release_gate_workflow


def test_quality_ops_capture_release_candidate_e2e_exact_spec_list_contract():
    row = _quality_ops_row_containing("Release candidate E2E spec 清单精确契约")
    release_gate_workflow = _read(RELEASE_GATE_WORKFLOW)

    assert "Release candidate E2E spec 清单精确契约" in row
    assert "当前 E2E spec 文件清单必须精确等于" in row
    assert "新增 E2E spec 同步更新 gate 文档和证据口径" in row
    assert "assert spec_files == [" in release_gate_workflow
    assert '"auth-flow.spec.ts",' in release_gate_workflow
    assert '"real-login-flow.spec.ts",' in release_gate_workflow
    assert '"real-run-trigger.spec.ts",' in release_gate_workflow
    assert '"special-regressions.spec.ts",' in release_gate_workflow
    assert "<= set(spec_files)" not in release_gate_workflow


def test_quality_ops_capture_ci_workflow_job_topology_exact_contract():
    row = _quality_ops_row_containing("CI workflow job 拓扑精确契约")
    release_gate_workflow = _read(RELEASE_GATE_WORKFLOW)

    assert "CI workflow job 拓扑精确契约" in row
    assert (
        "CI workflow job 集合现在必须精确等于 lint-and-type-check、backend-test、"
        "backend-integration-test、frontend-api-contract、frontend-build、e2e-test、"
        "release-gate"
    ) in row
    assert "删掉前端 typecheck/lint 或 build job 仍会通过" in row
    assert 'assert set(workflow["jobs"]) == {' in release_gate_workflow
    assert '"lint-and-type-check",' in release_gate_workflow
    assert '"frontend-build",' in release_gate_workflow
    assert '} <= set(workflow["jobs"])' not in release_gate_workflow


def test_quality_ops_capture_release_candidate_gate_profile_structured_contract():
    row = _quality_ops_row_containing(
        "Release candidate gate profile 结构化契约"
    )
    release_gate_workflow = _read(RELEASE_GATE_WORKFLOW)

    assert "Release candidate gate profile 结构化契约" in row
    assert "解析 workflow YAML" in row
    assert "`workflow_dispatch.inputs.gate`" in row
    assert "release-gate 的 name/if/needs" in row
    assert "配置文本出现过" in row
    assert "def _workflow_yaml() -> dict:" in release_gate_workflow
    assert "def _workflow_on(workflow: dict) -> dict:" in release_gate_workflow
    assert "gate_input == {" in release_gate_workflow
    assert '"options": ["pr_like", "nightly", "release_candidate"]' in (
        release_gate_workflow
    )
    assert 'assert workflow_on["schedule"] == [{"cron": "0 19 * * *"}]' in (
        release_gate_workflow
    )
    assert 'assert release_gate["name"] == "Release Candidate Gate"' in (
        release_gate_workflow
    )
    assert 'assert release_gate["needs"] == expected_release_needs' in (
        release_gate_workflow
    )
    assert 'backend_integration["env"]["QAP_PERFORMANCE_GATE_PROFILE"]' in (
        release_gate_workflow
    )
    assert 'assert "workflow_dispatch:" in text' not in release_gate_workflow
    assert 'assert f"- {gate}" in text' not in release_gate_workflow


def test_quality_ops_capture_release_gate_compose_worker_permission_contract():
    row = _quality_ops_row_containing(
        "Release gate compose worker 权限精确契约"
    )
    release_gate_workflow = _read(RELEASE_GATE_WORKFLOW)

    assert "Release gate compose worker 权限精确契约" in row
    assert "固定 worker/worker-high/worker-low 三个服务的 queue" in row
    assert "确认非 worker 服务没有这些执行器权限" in row
    assert "避免 release gate 只证明配置文本出现过" in row
    assert 'compose = yaml.safe_load(docker_compose)' in release_gate_workflow
    assert 'worker_queues = {' in release_gate_workflow
    assert '"worker-high": "queue:high"' in release_gate_workflow
    assert 'assert service["volumes"] == [' in release_gate_workflow
    assert 'assert service["group_add"] == ["${QAP_DOCKER_SOCK_GROUP_ID:-0}"]' in (
        release_gate_workflow
    )
    assert 'for service_name, service in services.items():' in release_gate_workflow
    assert 'assert "QAP_RUN_WORKSPACE_DIR" not in service.get("environment", {})' in (
        release_gate_workflow
    )
    assert (
        'docker_compose.count("- /var/run/docker.sock:/var/run/docker.sock") >= 3'
        not in release_gate_workflow
    )
    assert (
        'docker_compose.count("${QAP_DOCKER_SOCK_GROUP_ID:-0}") >= 3'
        not in release_gate_workflow
    )
    assert (
        "docker_compose.count('${QAP_DOCKER_SOCK_GROUP_ID:-0}') >= 3"
        not in release_gate_workflow
    )
    assert 'docker_compose.count("QAP_RUN_WORKSPACE_DIR") >= 6' not in (
        release_gate_workflow
    )
    assert 'docker_compose.count("/tmp/qap-workspaces") >= 6' not in (
        release_gate_workflow
    )


def test_quality_ops_capture_performance_slo_manifest_exact_name_contract():
    row = _quality_ops_row_containing("Performance SLO manifest 名称精确契约")
    release_gate_workflow = _read(RELEASE_GATE_WORKFLOW)

    assert "Performance SLO manifest 名称精确契约" in row
    assert "release gate 单测现在固定 39 个 SLO 名称" in row
    assert "archived log、artifact denial、API token 并发读" in row
    assert "新增/删除 SLO 必须同步更新发布证据口径" in row
    assert "expected_slos = {" in release_gate_workflow
    assert "archived log storage-unavailable API" in release_gate_workflow
    assert "run.read empty-scope denied log/artifact no-S3 API" in (
        release_gate_workflow
    )
    assert "assert names == expected_slos" in release_gate_workflow
    assert "assert required_slos <= names" not in release_gate_workflow
