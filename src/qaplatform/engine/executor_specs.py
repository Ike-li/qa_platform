"""ExecutionSpec builders for run executor containers."""

from __future__ import annotations

import shlex
from pathlib import Path

from qaplatform.engine.docker_backend import (
    ExecutionSpec,
    Mount,
    ResourceLimits,
    SandboxSecurity,
)
from qaplatform.engine.pipeline_config import PipelineConfig


def workspace_mount(working_dir: Path) -> Mount:
    return Mount(source=str(working_dir), target="/workspace", read_only=False)


def build_stage_execution_spec(
    *,
    run_id: str,
    stage_name: str,
    image: str,
    command: str,
    env_vars: dict[str, str],
    working_dir: Path,
    resource_limits: ResourceLimits,
    network_policy: str,
) -> ExecutionSpec:
    return ExecutionSpec(
        image=image,
        command=["sh", "-c", command],
        env_vars=env_vars,
        mounts=[workspace_mount(working_dir)],
        resource_limits=resource_limits,
        network_policy=network_policy,
        security=SandboxSecurity(readonly_rootfs=False),
        labels={"run_id": run_id, "stage": stage_name},
    )


def build_setup_execution_spec(
    *,
    run_id: str,
    pipeline: PipelineConfig,
    working_dir: Path,
) -> ExecutionSpec:
    return ExecutionSpec(
        image=pipeline.image,
        command=["sh", "-c", f"cd /workspace && {pipeline.setup_script or ''}"],
        env_vars=pipeline.env_vars,
        mounts=[workspace_mount(working_dir)],
        resource_limits=pipeline.resource_limits,
        network_policy=pipeline.network_policy,
        security=SandboxSecurity(readonly_rootfs=False),
        user="1000:1000",
        labels={"run_id": run_id, "phase": "setup"},
    )


def allure_report_command() -> str:
    return " ".join(
        shlex.quote(part)
        for part in [
            "allure",
            "generate",
            "results/allure-results",
            "-o",
            "results/allure-report",
            "--clean",
        ]
    )


def build_allure_report_execution_spec(
    *,
    run_id: str,
    pipeline: PipelineConfig,
    working_dir: Path,
) -> ExecutionSpec:
    return ExecutionSpec(
        image=pipeline.image,
        command=["sh", "-c", f"cd /workspace && {allure_report_command()}"],
        env_vars=pipeline.env_vars,
        mounts=[workspace_mount(working_dir)],
        resource_limits=pipeline.resource_limits,
        network_policy=pipeline.network_policy,
        security=SandboxSecurity(readonly_rootfs=False),
        labels={"run_id": run_id, "stage": "allure-report"},
    )
