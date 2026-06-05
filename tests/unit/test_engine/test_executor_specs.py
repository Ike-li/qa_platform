from __future__ import annotations

from qaplatform.engine import executor as executor_module
from qaplatform.engine import executor_specs as specs
from qaplatform.engine.docker_backend import ExecutionSpec, ResourceLimits
from qaplatform.engine.executor import PipelineConfig


def _mount_projection(mounts):
    return [
        {
            "source": mount.source,
            "target": mount.target,
            "read_only": mount.read_only,
        }
        for mount in mounts
    ]


def test_build_stage_execution_spec_uses_sandboxed_workspace_mount(tmp_path):
    resource_limits = ResourceLimits(memory_bytes=256 * 1024 * 1024)

    spec = specs.build_stage_execution_spec(
        run_id="run-1",
        stage_name="pytest",
        image="python:3.12-alpine",
        command="pytest -q",
        env_vars={"TOKEN": "secret"},
        working_dir=tmp_path,
        resource_limits=resource_limits,
        network_policy="deny",
    )

    assert isinstance(spec, ExecutionSpec)
    assert spec.image == "python:3.12-alpine"
    assert spec.command == ["sh", "-c", "pytest -q"]
    assert spec.env_vars == {"TOKEN": "secret"}
    assert spec.resource_limits is resource_limits
    assert spec.network_policy == "deny"
    assert spec.security.readonly_rootfs is False
    assert spec.user == "1000:1000"
    assert _mount_projection(spec.mounts) == [
        {"source": str(tmp_path), "target": "/workspace", "read_only": False}
    ]
    assert spec.labels == {"run_id": "run-1", "stage": "pytest"}


def test_build_setup_execution_spec_uses_fixed_container_user(tmp_path):
    resource_limits = ResourceLimits(memory_bytes=512 * 1024 * 1024)
    pipeline = PipelineConfig(
        image="python:3.12-alpine",
        stages=[],
        env_vars={"FOO": "bar"},
        resource_limits=resource_limits,
        network_policy="allow",
        setup_script="pip install -r requirements.txt",
    )

    spec = specs.build_setup_execution_spec(
        run_id="run-2",
        pipeline=pipeline,
        working_dir=tmp_path,
    )

    assert isinstance(spec, ExecutionSpec)
    assert spec.image == "python:3.12-alpine"
    assert spec.command == ["sh", "-c", "cd /workspace && pip install -r requirements.txt"]
    assert spec.env_vars == {"FOO": "bar"}
    assert spec.resource_limits is resource_limits
    assert spec.network_policy == "allow"
    assert spec.security.readonly_rootfs is False
    assert spec.user == "1000:1000"
    assert _mount_projection(spec.mounts) == [
        {"source": str(tmp_path), "target": "/workspace", "read_only": False}
    ]
    assert spec.labels == {"run_id": "run-2", "phase": "setup"}


def test_build_allure_report_execution_spec_uses_report_stage_label(tmp_path):
    resource_limits = ResourceLimits(memory_bytes=768 * 1024 * 1024)
    pipeline = PipelineConfig(
        image="python:3.12",
        stages=[],
        env_vars={"TOKEN": "secret"},
        resource_limits=resource_limits,
        network_policy="allow",
    )

    spec = specs.build_allure_report_execution_spec(
        run_id="run-3",
        pipeline=pipeline,
        working_dir=tmp_path,
    )

    assert isinstance(spec, ExecutionSpec)
    assert spec.image == "python:3.12"
    assert spec.command == [
        "sh",
        "-c",
        "cd /workspace && allure generate results/allure-results -o results/allure-report --clean",
    ]
    assert spec.env_vars == {"TOKEN": "secret"}
    assert spec.resource_limits is resource_limits
    assert spec.network_policy == "allow"
    assert spec.security.readonly_rootfs is False
    assert spec.user == "1000:1000"
    assert _mount_projection(spec.mounts) == [
        {"source": str(tmp_path), "target": "/workspace", "read_only": False}
    ]
    assert spec.labels == {"run_id": "run-3", "stage": "allure-report"}


def test_executor_module_keeps_execution_spec_compatibility_exports():
    assert executor_module.ExecutionSpec is specs.ExecutionSpec
    assert (
        executor_module._build_stage_execution_spec
        is specs.build_stage_execution_spec
    )
    assert (
        executor_module._build_setup_execution_spec
        is specs.build_setup_execution_spec
    )
    assert (
        executor_module._build_allure_report_execution_spec
        is specs.build_allure_report_execution_spec
    )
